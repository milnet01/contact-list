import tray


def test_open_opens_browser_at_port(monkeypatch):
    opened = {}
    monkeypatch.setattr(tray, 'open_url', lambda url: opened.setdefault('url', url))
    tray._open(5002)
    assert opened['url'] == 'http://127.0.0.1:5002'


def test_restart_calls_schedule(monkeypatch):
    called = {}
    monkeypatch.setattr(tray.server_control, 'schedule',
                        lambda action: called.setdefault('action', action))
    tray._restart()
    assert called['action'] == 'restart'


def test_quit_shuts_down_then_stops_icon():
    calls = []

    class FakeServer:
        def shutdown(self):
            calls.append('shutdown')

    class FakeIcon:
        def stop(self):
            calls.append('stop')

    tray._quit(FakeIcon(), FakeServer())
    assert calls == ['shutdown', 'stop']  # order matters: unblock serve_forever, then return Icon.run()
