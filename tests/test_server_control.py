"""Tests for the in-app Restart / Shutdown server controls (CL-0046).

Test safety: NO test ever execs or exits the process. Two safeguards —
(1) the route tests patch ``server_control.schedule`` and the ``schedule`` unit
test patches ``threading.Thread`` (so the real body never runs); (2)
``_run_after_delay`` returns early when ``PYTEST_CURRENT_TEST`` is set, so even a
missed patch cannot replace/kill the pytest interpreter.
"""

import pytest

import server_control
from app import create_app


@pytest.fixture()
def app(tmp_path):
    gcreds = tmp_path / 'gcreds'
    return create_app({
        'TESTING': True,
        'DATABASE': str(tmp_path / 'test.db'),
        'SECRET_KEY': 'test-secret',
        'GOOGLE_CREDENTIALS_DIR': str(gcreds),
        'GOOGLE_CREDENTIALS_FILE': str(gcreds / 'creds.json'),
        'GOOGLE_TOKEN_FILE': str(gcreds / 'token.json'),
    })


@pytest.fixture()
def client(app):
    return app.test_client()


def _get_csrf(client) -> str:
    client.get('/settings')
    with client.session_transaction() as sess:
        return sess.get('_csrf_token', '')


class _ThreadRecorder:
    """Stand-in for threading.Thread that records construction but never starts,
    so the real _run_after_delay body cannot run in a test."""

    instances: list['_ThreadRecorder'] = []

    def __init__(self, *, target=None, args=(), daemon=None):
        self.target, self.args, self.daemon = target, args, daemon
        _ThreadRecorder.instances.append(self)

    def start(self):
        pass  # deliberately does NOT invoke target


class TestSchedule:
    def test_unknown_action_raises(self):
        with pytest.raises(ValueError):
            server_control.schedule('bogus')

    @pytest.mark.parametrize('action', ['restart', 'shutdown'])
    def test_spawns_one_daemon_thread(self, action, monkeypatch):
        _ThreadRecorder.instances = []
        monkeypatch.setattr(server_control.threading, 'Thread', _ThreadRecorder)
        server_control.schedule(action)
        assert len(_ThreadRecorder.instances) == 1
        t = _ThreadRecorder.instances[0]
        assert t.daemon is True
        assert t.target is server_control._run_after_delay
        assert t.args == (action,)

    def test_run_after_delay_is_inert_under_pytest(self, monkeypatch):
        # PYTEST_CURRENT_TEST is set by pytest during this call, so the guard
        # must return before spawning/exiting. Make either path fail loudly.
        def boom(*a, **k):
            raise AssertionError('process-control call fired under pytest')

        monkeypatch.setattr(server_control.subprocess, 'Popen', boom)
        monkeypatch.setattr(server_control.os, '_exit', boom)
        server_control._run_after_delay('restart')   # must return, not raise
        server_control._run_after_delay('shutdown')


class TestServerControlRoute:
    def test_restart_schedules_and_renders(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(server_control, 'schedule', calls.append)
        token = _get_csrf(client)
        resp = client.post('/settings/server',
                           data={'_csrf_token': token, 'action': 'restart'})
        assert resp.status_code == 200
        assert b'Restarting' in resp.data
        assert calls == ['restart']

    def test_shutdown_schedules_and_renders(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(server_control, 'schedule', calls.append)
        token = _get_csrf(client)
        resp = client.post('/settings/server',
                           data={'_csrf_token': token, 'action': 'shutdown'})
        assert resp.status_code == 200
        assert b'stopped' in resp.data
        assert b'icon' in resp.data
        assert calls == ['shutdown']

    def test_invalid_action_400_and_no_schedule(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(server_control, 'schedule', calls.append)
        token = _get_csrf(client)
        resp = client.post('/settings/server',
                           data={'_csrf_token': token, 'action': 'nuke'})
        assert resp.status_code == 400
        assert calls == []

    def test_missing_csrf_403_and_no_schedule(self, client, monkeypatch):
        calls = []
        monkeypatch.setattr(server_control, 'schedule', calls.append)
        resp = client.post('/settings/server', data={'action': 'restart'})
        assert resp.status_code == 403
        assert calls == []

    def test_settings_page_shows_both_buttons(self, client):
        resp = client.get('/settings')
        assert resp.status_code == 200
        assert b'value="restart"' in resp.data
        assert b'value="shutdown"' in resp.data

    def test_settings_tab_scaffold(self, client):
        # CL-0047: the four tab panels are server-rendered (present in the no-JS
        # DOM), and every tab button is type="button" so a click can't submit the
        # settings form. All section controls remain present regardless of tabs.
        resp = client.get('/settings')
        body = resp.data
        for pid in (b'id="tab-appearance"', b'id="tab-dates"',
                    b'id="tab-contacts"', b'id="tab-server"'):
            assert pid in body
        # No tab button may default to submit.
        assert body.count(b'class="tab"') == body.count(b'role="tab"')
        assert b'<button type="button" class="tab"' in body
        # Controls from every section still present (panels are not JS-gated server-side).
        assert b'name="theme"' in body        # Appearance
        assert b'name="timezone"' in body      # Dates & Time
        assert b'name="per_page"' in body      # Contacts & Phone


# --- Respawn command and restart marker (CL-0063, CL-0054; spec §2.1.1-2) ---

import os  # noqa: E402
import sys  # noqa: E402

import launcher  # noqa: E402


class TestRespawnCommand:
    """INV-9: the child's argv and env for each row of spec §2.1.1."""

    def _frozen(self, monkeypatch, exe, appimage=None, appdir=None):
        monkeypatch.setattr(sys, 'frozen', True, raising=False)
        monkeypatch.setattr(sys, 'executable', exe)
        monkeypatch.setattr(sys, 'argv', [exe, '--flag'])
        for key, value in (('APPIMAGE', appimage), ('APPDIR', appdir)):
            if value is None:
                monkeypatch.delenv(key, raising=False)
            else:
                monkeypatch.setenv(key, value)
        monkeypatch.setenv('LD_LIBRARY_PATH', '/bundle/lib')
        monkeypatch.setenv('LD_LIBRARY_PATH_ORIG', '/usr/lib')

    def test_from_source_keeps_the_script_and_marks_the_child(self, monkeypatch):
        monkeypatch.delattr(sys, 'frozen', raising=False)
        monkeypatch.setattr(sys, 'argv', ['launcher.py', '--x'])
        argv, env = server_control._respawn_command()
        assert argv == [sys.executable, os.path.abspath('launcher.py'), '--x']
        assert env[server_control.RESTART_MARKER] == '1'
        assert server_control.RESTART_MARKER not in os.environ

    def test_appimage_reruns_the_appimage_file(self, monkeypatch, tmp_path):
        mount = tmp_path / 'mount'
        (mount / 'usr').mkdir(parents=True)
        self._frozen(monkeypatch, str(mount / 'usr' / 'contact-list'),
                     appimage='/home/u/Contact-List.AppImage', appdir=str(mount))
        argv, env = server_control._respawn_command()
        assert argv == ['/home/u/Contact-List.AppImage', '--flag']
        assert env['PYINSTALLER_RESET_ENVIRONMENT'] == '1'
        assert env['LD_LIBRARY_PATH'] == '/usr/lib'
        assert env[server_control.RESTART_MARKER] == '1'

    def test_inherited_appimage_from_another_app_is_ignored(
            self, monkeypatch, tmp_path):
        # APPIMAGE/APPDIR belong to some OTHER AppImage that started us.
        self._frozen(monkeypatch, '/opt/contact-list/contact-list',
                     appimage='/home/u/SomeOtherTool.AppImage',
                     appdir=str(tmp_path / 'other-mount'))
        argv, env = server_control._respawn_command()
        assert argv == ['/opt/contact-list/contact-list', '--flag']
        assert env['PYINSTALLER_RESET_ENVIRONMENT'] == '1'

    def test_frozen_binary_is_not_passed_its_own_path(self, monkeypatch):
        self._frozen(monkeypatch, 'C:\\Apps\\contact-list.exe')
        argv, env = server_control._respawn_command()
        assert argv == ['C:\\Apps\\contact-list.exe', '--flag']
        assert env['PYINSTALLER_RESET_ENVIRONMENT'] == '1'
        assert env[server_control.RESTART_MARKER] == '1'


class TestRestartWait:
    """INV-10: a restart child waits for the parent to release the port."""

    def test_waits_until_the_port_is_free_and_drops_the_marker(self, monkeypatch):
        monkeypatch.setenv(server_control.RESTART_MARKER, '1')
        answers = iter([True, True, False])
        calls = []

        def probe(host, port, timeout=0.25):
            calls.append(port)
            return next(answers)
        monkeypatch.setattr(launcher, '_port_is_serving', probe)
        launcher._wait_for_restart_release(5002, timeout=5, interval=0)
        assert calls == [5002, 5002, 5002]
        assert server_control.RESTART_MARKER not in os.environ

    def test_gives_up_at_the_timeout(self, monkeypatch):
        monkeypatch.setenv(server_control.RESTART_MARKER, '1')
        monkeypatch.setattr(launcher, '_port_is_serving', lambda *a, **k: True)
        launcher._wait_for_restart_release(5002, timeout=0.05, interval=0.01)
        assert server_control.RESTART_MARKER not in os.environ

    def test_without_the_marker_it_does_not_probe(self, monkeypatch):
        monkeypatch.delenv(server_control.RESTART_MARKER, raising=False)

        def probe(*a, **k):
            raise AssertionError('probed without a restart marker')
        monkeypatch.setattr(launcher, '_port_is_serving', probe)
        launcher._wait_for_restart_release(5002)

    def test_main_waits_before_the_already_serving_check(self, monkeypatch):
        order = []
        monkeypatch.setattr(launcher, '_wait_for_restart_release',
                            lambda port: order.append('wait'))

        def probe(*a, **k):
            order.append('probe')
            return True
        monkeypatch.setattr(launcher, '_port_is_serving', probe)
        monkeypatch.setattr(launcher, 'open_url', lambda url: None)
        monkeypatch.delenv('PORT', raising=False)
        assert launcher.main() == 0
        assert order == ['wait', 'probe']
