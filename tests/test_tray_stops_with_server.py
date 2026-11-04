"""The tray icon goes away when the server stops, however it stops (CL-0108).

A tray left up after the server has gone sits in front of nothing, and keeps
the process alive. Two ways the server stops without the tray's own Quit:

* a signal — SIGINT/SIGTERM call server.shutdown(), so serve_forever returns;
* a crash — serve_forever raises.

Either way the server thread ends, and launcher.main() must then stop the tray.
The fake tray below blocks the way Icon.run() does, until something stops it,
and gives up after a timeout so a regression fails instead of hanging.
"""
from __future__ import annotations

import threading
from typing import Any

import pytest
import werkzeug.serving

import app as app_module
import launcher
import tray

_TRAY_TIMEOUT = 5.0


class _ReturningServer:
    """serve_forever returns at once, as it does after a signal's shutdown()."""

    def serve_forever(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


class _CrashingServer(_ReturningServer):
    """serve_forever raises, as a crashed server thread does."""

    def serve_forever(self) -> None:
        raise OSError('server thread died')


class _BlockingTray:
    """Stands in for tray.run_tray: blocks until the stopper stops it."""

    def __init__(self) -> None:
        self.stopped = False

    def __call__(self, server: Any, port: int,
                 stopper: tray.TrayStopper | None = None) -> None:
        icon = _FakeIcon()
        if stopper is not None:
            tray._on_ready(icon, stopper)
        self.stopped = icon.stop_called.wait(_TRAY_TIMEOUT)


class _FakeIcon:
    def __init__(self) -> None:
        self.visible = False
        self.stop_called = threading.Event()

    def stop(self) -> None:
        self.stop_called.set()


def _start(monkeypatch: pytest.MonkeyPatch, server: _ReturningServer) -> _BlockingTray:
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.delenv('LWSM_MANAGED', raising=False)
    monkeypatch.setattr(launcher, '_port_is_serving', lambda host, port, **kw: False)
    monkeypatch.setattr(app_module, 'create_app', lambda: object())
    monkeypatch.setattr(werkzeug.serving, 'make_server', lambda *a, **kw: server)
    monkeypatch.setattr(launcher, 'open_url', lambda url: None)
    fake_tray = _BlockingTray()
    monkeypatch.setattr(tray, 'run_tray', fake_tray)
    return fake_tray


def test_server_stopped_by_signal_stops_the_tray(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_tray = _start(monkeypatch, _ReturningServer())
    assert launcher.main() == 0
    assert fake_tray.stopped


def test_crashed_server_stops_the_tray_and_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_tray = _start(monkeypatch, _CrashingServer())
    assert launcher.main() == 1
    assert fake_tray.stopped


class TestTrayStopper:
    """The stop can arrive before or after the icon is up; both must stop it."""

    def test_stop_after_ready_stops_the_icon(self) -> None:
        stopper = tray.TrayStopper()
        icon = _FakeIcon()
        tray._on_ready(icon, stopper)
        assert icon.visible
        assert not icon.stop_called.is_set()
        stopper.stop()
        assert icon.stop_called.is_set()

    def test_stop_before_ready_stops_the_icon_when_it_comes_up(self) -> None:
        stopper = tray.TrayStopper()
        stopper.stop()  # the server died before the icon's loop started
        icon = _FakeIcon()
        tray._on_ready(icon, stopper)
        assert icon.stop_called.is_set()
