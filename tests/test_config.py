"""Tests for the secret-key persistence race fix (CL-0069).

_load_or_create_secret_key used to be read-then-truncate-write with no
O_EXCL and no atomic rename: two processes starting at once each minted a
different key and each O_TRUNC'd the file, so the loser signed cookies with
a key present in no file and 403'd every POST -- the exact failure the
persisted key was introduced to fix. It now writes to a tempfile.mkstemp
temp file and os.links it into place, so the first writer wins the race and
every later caller re-reads the winner's key instead of minting its own.
The read side also used to catch FileNotFoundError only, so a
PermissionError or a decode error on an existing-but-unreadable key file
escaped uncaught, at import time, before file logging is installed -- the
app then failed to start with no message on any surface. It now treats any
OSError/UnicodeDecodeError on the read the same as a missing file: log and
mint a new key.
"""

from __future__ import annotations

import concurrent.futures
import os

import pytest

import config


@pytest.fixture(autouse=True)
def _no_env_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    # conftest.py sets SECRET_KEY so the rest of the suite never touches the
    # real ~/.config/contact-list. That env var would make
    # _load_or_create_secret_key() short-circuit before ever reaching the
    # file-based logic these tests exist to lock, so remove it here only --
    # monkeypatch restores it for every other test.
    monkeypatch.delenv('SECRET_KEY', raising=False)


class TestSecretKeyRaceSafety:
    def test_concurrent_creation_converges_on_one_key(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        cfg_dir = str(tmp_path / 'contact-list')
        monkeypatch.setattr(config, '_CONFIG_DIR', cfg_dir)

        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            results = list(
                pool.map(lambda _: config._load_or_create_secret_key(), range(8))
            )

        # Every concurrent caller must agree on the same key -- the pre-fix
        # read-then-truncate let each writer mint and persist its own.
        assert len(set(results)) == 1
        winner = results[0]

        key_path = os.path.join(cfg_dir, 'secret_key')
        with open(key_path, encoding='utf-8') as fh:
            on_disk = fh.read().strip()
        assert on_disk == winner

        leftovers = [f for f in os.listdir(cfg_dir) if f.endswith('.tmp')]
        assert leftovers == []

    def test_unreadable_key_file_does_not_raise(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # A directory sitting at the key path makes any open() raise
        # IsADirectoryError -- an OSError the old FileNotFoundError-only
        # except did not catch, so this used to escape uncaught.
        cfg_dir = tmp_path / 'contact-list'
        cfg_dir.mkdir()
        monkeypatch.setattr(config, '_CONFIG_DIR', str(cfg_dir))
        (cfg_dir / 'secret_key').mkdir()

        key = config._load_or_create_secret_key()
        assert isinstance(key, str) and key

    def test_permission_denied_key_file_does_not_raise(
        self, tmp_path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        if hasattr(os, 'geteuid') and os.geteuid() == 0:
            pytest.skip('running as root: chmod 000 does not deny read')

        cfg_dir = tmp_path / 'contact-list'
        cfg_dir.mkdir()
        monkeypatch.setattr(config, '_CONFIG_DIR', str(cfg_dir))
        key_path = cfg_dir / 'secret_key'
        key_path.write_text('irrelevant')
        key_path.chmod(0o000)
        try:
            key = config._load_or_create_secret_key()
        finally:
            key_path.chmod(0o600)  # restore so tmp_path teardown can remove it

        assert isinstance(key, str) and key


class TestSecretKeyFloor:
    """CL-0069: SECRET_KEY from the environment had no length floor, so
    SECRET_KEY=x signed every session and CSRF token with a one-byte key."""

    def test_short_env_key_is_ignored(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, '_CONFIG_DIR', str(tmp_path / 'contact-list'))
        monkeypatch.setenv('SECRET_KEY', 'x')
        key = config._load_or_create_secret_key()
        assert key != 'x'
        assert len(key) >= config.MIN_SECRET_KEY_LEN

    def test_long_env_key_is_used(self, tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(config, '_CONFIG_DIR', str(tmp_path / 'contact-list'))
        long_key = 'k' * config.MIN_SECRET_KEY_LEN
        monkeypatch.setenv('SECRET_KEY', long_key)
        assert config._load_or_create_secret_key() == long_key


class TestConfigDirIsPrivate:
    """CL-0069: create_app locked only the photos dir, so the credentials dir
    above it stayed at the umask's 0755 whenever SECRET_KEY was set -- the
    branch that used to tighten it as a side effect never ran."""

    def test_create_app_locks_the_credentials_dir(self, tmp_path) -> None:
        from app import create_app
        creds = tmp_path / 'contact-list'
        creds.mkdir(mode=0o755)
        os.chmod(creds, 0o755)
        create_app({
            'TESTING': True,
            'DATABASE': str(tmp_path / 'test.db'),
            'SECRET_KEY': 'test-secret',
            'GOOGLE_CREDENTIALS_DIR': str(creds),
        })
        assert (creds.stat().st_mode & 0o777) == 0o700
