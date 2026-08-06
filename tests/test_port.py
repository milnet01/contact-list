"""Port resolution from the environment (CL-0056).

Precedence is PORT → CONTACT_LIST_PORT → 5002. PORT is the machine-facing knob
(range-checked, never silently defaulted); CONTACT_LIST_PORT is the human one
(unchanged behaviour, no range check).
"""

import pytest
import werkzeug.serving

import app as app_module
import config
import launcher
import tray
from config import DEFAULT_PORT, PortError, resolve_port


class _FakeServer:
    """Stands in for the Werkzeug server handle: binds nothing, stops at once."""

    def serve_forever(self) -> None:
        pass

    def shutdown(self) -> None:
        pass


def _stub_startup(monkeypatch, bound: dict) -> None:
    """Let launcher.main() run its full startup path without binding a socket,
    creating the real app, or opening a browser. Records what make_server got.

    The open_url stub matters since CL-0060: main()'s tray-failure branch now opens
    a real browser, so a caller that lets the tray raise would spawn a window on
    every test run. run_tray is deliberately NOT stubbed here — every caller that
    reaches the tray block sets its own, and two of them do so *before* calling this
    helper, where a stub here would silently overwrite theirs.
    """
    def fake_make_server(host, port, app, **kwargs):
        bound['host'] = host
        bound['port'] = port
        return _FakeServer()

    monkeypatch.setattr(werkzeug.serving, 'make_server', fake_make_server)
    monkeypatch.setattr(app_module, 'create_app', lambda: object())
    monkeypatch.setattr(launcher, '_port_is_serving', lambda host, port, **kw: False)
    monkeypatch.setattr(launcher, 'open_url', lambda url: None)


# --------------------------------------------------------------------------
# resolve_port
# --------------------------------------------------------------------------

def test_port_absent_uses_default(monkeypatch):
    monkeypatch.delenv('PORT', raising=False)
    assert resolve_port(5002) == (5002, False)


def test_port_empty_is_absent(monkeypatch):
    monkeypatch.setenv('PORT', '')
    assert resolve_port(5002) == (5002, False)


def test_port_valid_is_explicit(monkeypatch):
    monkeypatch.setenv('PORT', '5999')
    assert resolve_port(5002) == (5999, True)


def test_port_wins_over_contact_list_port(monkeypatch):
    monkeypatch.setenv('PORT', '5998')
    monkeypatch.setenv('CONTACT_LIST_PORT', '5001')
    # The caller passes Config.PORT (the CONTACT_LIST_PORT fallback) as default.
    assert resolve_port(config._contact_list_port()) == (5998, True)


def test_contact_list_port_used_when_port_absent(monkeypatch):
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.setenv('CONTACT_LIST_PORT', '5001')
    assert resolve_port(config._contact_list_port()) == (5001, False)


def test_default_is_5002(monkeypatch):
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.delenv('CONTACT_LIST_PORT', raising=False)
    assert resolve_port(config._contact_list_port()) == (DEFAULT_PORT, False)
    assert DEFAULT_PORT == 5002


@pytest.mark.parametrize('bad', ['abc', '[abc]', '80', '0', '65536', '5002.5', ' '])
def test_invalid_port_raises_and_names_the_value(monkeypatch, bad):
    """Never a silent fall back, and the message carries the offending value
    verbatim — including a bracketed one, which a console layer elsewhere once
    swallowed as a style tag."""
    monkeypatch.setenv('PORT', bad)
    with pytest.raises(PortError) as excinfo:
        resolve_port(5002)
    assert bad in str(excinfo.value)


def test_boundary_ports_are_valid(monkeypatch):
    for value in ('1024', '65535'):
        monkeypatch.setenv('PORT', value)
        assert resolve_port(5002) == (int(value), True)


# --------------------------------------------------------------------------
# CONTACT_LIST_PORT — unchanged range, no longer an import-time crash
# --------------------------------------------------------------------------

def test_contact_list_port_keeps_its_range(monkeypatch):
    """Privileged/high ports stay allowed here: this is a human naming a port for
    their own program, not a manager talking to us."""
    monkeypatch.setenv('CONTACT_LIST_PORT', '80')
    assert config._contact_list_port() == 80


def test_contact_list_port_garbage_falls_back(monkeypatch):
    monkeypatch.setenv('CONTACT_LIST_PORT', 'abc')
    assert config._contact_list_port() == DEFAULT_PORT


def test_contact_list_port_empty_falls_back(monkeypatch):
    monkeypatch.setenv('CONTACT_LIST_PORT', '')
    assert config._contact_list_port() == DEFAULT_PORT


# --------------------------------------------------------------------------
# launcher.main — the single-instance split and the URL line
# --------------------------------------------------------------------------

def test_launcher_exits_nonzero_on_invalid_port(monkeypatch, capsys):
    monkeypatch.setenv('PORT', '[abc]')
    monkeypatch.setattr(launcher, '_port_is_serving',
                        lambda *a, **kw: pytest.fail('must not probe the port'))
    assert launcher.main() != 0
    err = capsys.readouterr().err
    assert '[abc]' in err


def test_busy_port_with_explicit_port_fails_without_a_browser(monkeypatch, capsys):
    """A manager named the port and did not get it — a failure, not a hand-off."""
    monkeypatch.setenv('PORT', '5999')
    monkeypatch.setattr(launcher, '_port_is_serving', lambda host, port, **kw: True)
    monkeypatch.setattr(launcher, 'open_url',
                        lambda url: pytest.fail('must not open a browser'))
    assert launcher.main() != 0
    assert '5999' in capsys.readouterr().err


def test_busy_port_without_port_env_keeps_inv4_handoff(monkeypatch):
    """PORT absent → INV-4 unchanged: open the existing instance and exit 0."""
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.delenv('CONTACT_LIST_PORT', raising=False)
    opened = {}
    monkeypatch.setattr(launcher, '_port_is_serving', lambda host, port, **kw: True)
    monkeypatch.setattr(launcher, 'open_url', lambda url: opened.setdefault('url', url))
    assert launcher.main() == 0
    assert opened['url'] == f'http://127.0.0.1:{DEFAULT_PORT}'


def test_port_reaches_make_server_and_url_is_printed(monkeypatch, capsys):
    """The value make_server binds is the one derived from PORT, and the URL line
    lands on stdout — make_server prints no banner of its own."""
    monkeypatch.setenv('PORT', '5999')
    monkeypatch.setenv('LWSM_MANAGED', '1')  # skip the tray; port must be unaffected
    bound: dict = {}
    _stub_startup(monkeypatch, bound)

    assert launcher.main() == 0
    assert bound == {'host': '127.0.0.1', 'port': 5999}
    assert 'Listening on http://127.0.0.1:5999' in capsys.readouterr().out


def test_lwsm_managed_skips_the_tray(monkeypatch):
    monkeypatch.delenv('PORT', raising=False)
    monkeypatch.setenv('LWSM_MANAGED', '1')
    monkeypatch.setattr(tray, 'run_tray',
                        lambda *a: pytest.fail('tray must not run when managed'))
    _stub_startup(monkeypatch, {})
    assert launcher.main() == 0


@pytest.mark.parametrize('value', [None, '0', 'true', ''])
def test_tray_runs_unless_lwsm_managed_is_1(monkeypatch, value):
    """Absent or anything other than 1 behaves exactly as today: tray included."""
    monkeypatch.delenv('PORT', raising=False)
    if value is None:
        monkeypatch.delenv('LWSM_MANAGED', raising=False)
    else:
        monkeypatch.setenv('LWSM_MANAGED', value)
    ran = {}
    monkeypatch.setattr(tray, 'run_tray',
                        lambda server, port: ran.setdefault('port', port))
    bound: dict = {}
    _stub_startup(monkeypatch, bound)

    assert launcher.main() == 0
    assert ran['port'] == bound['port']
