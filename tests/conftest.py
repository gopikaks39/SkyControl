"""Shared fixtures. Each test gets its own SQLite file; the real-data analysis is built once per session."""
import os
import tempfile

import pytest

CONTROLLER_PASSWORD = 'controller2026pass'
SUPERVISOR_PASSWORD = 'supervisor2026pass'

_session_dir = tempfile.mkdtemp(prefix='skycontrol-tests-')
os.environ.setdefault('SKYCONTROL_CACHE_DIR', os.path.join(_session_dir, 'cache'))
os.environ['SKYCONTROL_CONTROLLER_PASSWORD'] = CONTROLLER_PASSWORD
os.environ['SKYCONTROL_SUPERVISOR_PASSWORD'] = SUPERVISOR_PASSWORD
os.environ['SKYCONTROL_SKIP_WARMUP'] = '1'


@pytest.fixture()
def api(tmp_path, monkeypatch):
    monkeypatch.setenv('SKYCONTROL_DB', str(tmp_path / 'test.sqlite3'))
    from fastapi.testclient import TestClient
    from backend.app import app
    with TestClient(app) as client:
        yield client


def _login(api, username, password):
    r = api.post('/api/auth/login', json={'username': username, 'password': password})
    assert r.status_code == 200, r.text
    return {'Authorization': 'Bearer ' + r.json()['token']}


@pytest.fixture()
def controller(api):
    return _login(api, 'controller', CONTROLLER_PASSWORD)


@pytest.fixture()
def supervisor(api):
    return _login(api, 'supervisor', SUPERVISOR_PASSWORD)


@pytest.fixture(scope='session')
def recording():
    from backend.analytics.recording import load
    return load()


@pytest.fixture(scope='session')
def analysis():
    from backend.analytics import pipeline
    return pipeline.get()
