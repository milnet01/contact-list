import os
import sys

import config
import resources
from resources import resource_path

# Test isolation (SECRET_KEY) lives in tests/conftest.py so it applies before any
# test module imports config/app.


def test_resource_path_from_source():
    # From source: base is the repo root (resources.py's dir).
    got = resource_path('migrations')
    assert got == os.path.join(os.path.dirname(os.path.abspath(resources.__file__)), 'migrations')


def test_resource_path_uses_meipass_when_set(monkeypatch):
    monkeypatch.setattr(sys, '_MEIPASS', '/tmp/frozen', raising=False)
    assert resource_path('templates') == os.path.join('/tmp/frozen', 'templates')


def test_default_db_path_from_source():
    assert config._default_db_path().endswith('contacts.db')
    # From source it is next to the code, NOT under ~/.config.
    assert '.config/contact-list' not in config._default_db_path()


def test_default_db_path_when_frozen(monkeypatch):
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    got = config._default_db_path()
    assert got == os.path.join(config._CONFIG_DIR, 'contacts.db')


from routes import sync as sync_module


def test_auth_command_from_source():
    cmd = sync_module._auth_command(False)
    assert cmd[0] == sys.executable
    assert cmd[1].endswith('google_auth.py')


def test_auth_command_when_frozen():
    assert sync_module._auth_command(True) == [sys.executable, '--google-auth']
