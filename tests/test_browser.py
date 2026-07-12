import browser


def test_system_env_drops_ld_path_when_no_orig(monkeypatch):
    monkeypatch.setenv('LD_LIBRARY_PATH', '/frozen/_internal')
    monkeypatch.delenv('LD_LIBRARY_PATH_ORIG', raising=False)
    env = browser._system_env()
    assert 'LD_LIBRARY_PATH' not in env


def test_system_env_restores_orig(monkeypatch):
    monkeypatch.setenv('LD_LIBRARY_PATH', '/frozen/_internal')
    monkeypatch.setenv('LD_LIBRARY_PATH_ORIG', '/usr/lib/custom')
    env = browser._system_env()
    assert env['LD_LIBRARY_PATH'] == '/usr/lib/custom'
    assert 'LD_LIBRARY_PATH_ORIG' not in env


def test_open_url_uses_webbrowser_when_not_frozen(monkeypatch):
    monkeypatch.setattr(browser.sys, 'frozen', False, raising=False)
    opened = {}
    monkeypatch.setattr(browser.webbrowser, 'open', lambda u: opened.setdefault('u', u))
    browser.open_url('http://127.0.0.1:5002')
    assert opened['u'] == 'http://127.0.0.1:5002'


def test_open_url_spawns_xdg_open_with_clean_env_when_frozen_linux(monkeypatch):
    monkeypatch.setattr(browser.sys, 'frozen', True, raising=False)
    monkeypatch.setattr(browser.sys, 'platform', 'linux')
    monkeypatch.setenv('LD_LIBRARY_PATH', '/frozen/_internal')
    monkeypatch.delenv('LD_LIBRARY_PATH_ORIG', raising=False)
    calls = {}
    def fake_popen(cmd, env=None, **kw):
        calls['cmd'] = cmd
        calls['env'] = env
        return object()
    monkeypatch.setattr(browser.subprocess, 'Popen', fake_popen)
    browser.open_url('http://127.0.0.1:5002')
    assert calls['cmd'] == ['xdg-open', 'http://127.0.0.1:5002']
    assert 'LD_LIBRARY_PATH' not in calls['env']  # bundle removed for the child
