"""A normal start opens no browser; a tray-less one does (CL-0060).

Locks the three cases of
docs/specs/2026-08-06-tray-delivery-and-page-opening.md:

* INV-4 — tray comes up  → nothing opens. The headline behaviour change.
* INV-8 — tray fails     → the browser opens, so a running app is never
  unreachable. Needed because a frozen windowed build has no console to print
  its URL to, and a desktop with no tray support (GNOME without an
  AppIndicator extension) shows no icon either.
* INV-9 — LWSM_MANAGED=1 → nothing opens, whether or not a tray would have
  worked. A deliberately skipped tray is not a failed one.

Every assertion runs on the main thread after main() returns: since the daemon
poll thread was deleted, no browser-open happens off-thread, so there is nothing
to race and nothing to wait for.
"""
from __future__ import annotations

import os
import sys
from typing import Any

import pytest
import werkzeug.serving

import app as app_module
import launcher
import tray
from config import DEFAULT_PORT


class _FakeServer:
    """Binds nothing and stops at once."""

    def serve_forever(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _stub_start(monkeypatch: pytest.MonkeyPatch, opened: list[str]) -> None:
    """Run main()'s full startup path with no socket, no real app and no browser.

    Records every URL main() tries to open into ``opened`` rather than raising, so
    the assertion happens on the main thread where pytest can see it.
    """
    monkeypatch.setattr(launcher, '_port_is_serving', lambda host, port, **kw: False)
    monkeypatch.setattr(app_module, 'create_app', lambda: object())
    monkeypatch.setattr(werkzeug.serving, 'make_server',
                        lambda *a, **kw: _FakeServer())
    monkeypatch.setattr(launcher, 'open_url', lambda url: opened.append(url))


def _boom(server: Any, port: int) -> None:
    """A tray that cannot start — what a desktop with no StatusNotifier host does."""
    raise ImportError("No module named 'gi'")


def test_start_with_working_tray_opens_no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """INV-4: the tray came up, so the user has an icon to click — open nothing."""
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.delenv('LWSM_MANAGED', raising=False)
    opened: list[str] = []
    _stub_start(monkeypatch, opened)
    # Returning immediately stands in for the user picking Quit.
    monkeypatch.setattr(tray, 'run_tray', lambda server, port: None)

    assert launcher.main() == 0
    assert opened == []


def test_tray_failure_opens_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """INV-8: no icon means no way in, so the page opens after all."""
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.delenv('CONTACT_LIST_PORT', raising=False)
    monkeypatch.delenv('LWSM_MANAGED', raising=False)
    opened: list[str] = []
    _stub_start(monkeypatch, opened)
    monkeypatch.setattr(tray, 'run_tray', _boom)

    assert launcher.main() == 0
    assert opened == [f'http://127.0.0.1:{DEFAULT_PORT}']


def test_managed_start_opens_no_browser(monkeypatch: pytest.MonkeyPatch) -> None:
    """INV-9: a managed run skips the tray on purpose, which is not a failure.

    run_tray is made to RAISE here on purpose: if the managed branch ever stopped
    returning early and fell through to the tray block, this would take INV-8's
    fallback and open a browser. Stubbing run_tray to a no-op instead would pass
    either way and prove nothing.
    """
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.setenv('LWSM_MANAGED', '1')
    opened: list[str] = []
    _stub_start(monkeypatch, opened)
    monkeypatch.setattr(tray, 'run_tray', _boom)

    assert launcher.main() == 0
    assert opened == []


class TestPystrayBackendGuard:
    """PYSTRAY_BACKEND=appindicator is pinned on Linux only.

    Why this exists: pystray imports pystray._<name> unconditionally for a named
    backend and does NOT fall back when that import fails; _appindicator opens
    with `import gi`, which does not exist on Windows or macOS. Setting the
    variable unconditionally made run_tray raise ImportError on both platforms,
    so the tray never appeared and the except-branch fallback opened a browser
    tab on every launch -- the very thing CL-0060 removed.
    """

    def _run(self, monkeypatch: pytest.MonkeyPatch, platform: str) -> None:
        monkeypatch.delenv('PORT', raising=False)
        monkeypatch.delenv('LWSM_MANAGED', raising=False)
        # Snapshotting the (absent) key here means monkeypatch's teardown
        # deletes it again afterwards, however main() sets it -- the test must
        # not leak PYSTRAY_BACKEND into the environment of other tests.
        monkeypatch.delenv('PYSTRAY_BACKEND', raising=False)
        monkeypatch.setattr(sys, 'platform', platform)
        opened: list[str] = []
        _stub_start(monkeypatch, opened)
        # A working tray that returns immediately, like the user picking Quit.
        monkeypatch.setattr(tray, 'run_tray', lambda server, port: None)

        assert launcher.main() == 0

    def test_windows_does_not_set_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._run(monkeypatch, 'win32')
        assert 'PYSTRAY_BACKEND' not in os.environ

    def test_macos_does_not_set_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._run(monkeypatch, 'darwin')
        assert 'PYSTRAY_BACKEND' not in os.environ

    def test_linux_sets_backend(self, monkeypatch: pytest.MonkeyPatch) -> None:
        self._run(monkeypatch, 'linux')
        assert os.environ.get('PYSTRAY_BACKEND') == 'appindicator'
