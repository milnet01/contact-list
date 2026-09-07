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
