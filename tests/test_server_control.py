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
