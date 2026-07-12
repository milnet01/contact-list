import os
import sys
import types

import config
import resources
from resources import resource_path
from routes import sync as sync_module

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


def test_auth_command_from_source():
    cmd = sync_module._auth_command(False)
    assert cmd[0] == sys.executable
    assert cmd[1].endswith('google_auth.py')


def test_auth_command_when_frozen():
    assert sync_module._auth_command(True) == [sys.executable, '--google-auth']


def test_launcher_single_instance_opens_browser(monkeypatch):
    import launcher
    opened = {}
    monkeypatch.setattr(launcher, '_port_is_serving', lambda h, p: True)
    monkeypatch.setattr(launcher.webbrowser, 'open', lambda url: opened.setdefault('url', url))

    def _should_not_build():
        raise AssertionError('should not build app')

    # The already-serving path must short-circuit before building the app.
    monkeypatch.setattr('app.create_app', _should_not_build)
    assert launcher.main() == 0
    assert opened['url'].endswith(':5002')


def test_launcher_binds_loopback(monkeypatch):
    import launcher
    monkeypatch.setattr(launcher, '_port_is_serving', lambda h, p: False)
    monkeypatch.setattr(launcher, '_open_when_ready', lambda port: None)
    dummy = types.SimpleNamespace(run=lambda **kw: rec.update(kw))
    rec = {}
    monkeypatch.setattr('app.create_app', lambda: dummy)
    assert launcher.main() == 0
    assert rec['host'] == '127.0.0.1'


def test_pystray_in_requirements():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, 'requirements.txt')) as f:
        reqs = f.read()
    assert 'pystray' in reqs
