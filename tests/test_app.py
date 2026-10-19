"""Application wiring: health, static frontend, security headers and the dataset register."""


def test_health_and_frontend(api):
    h = api.get('/api/health').json()
    assert h['status'] == 'ok' and h['mode'] == 'RESEARCH_SIMULATION_ONLY'
    page = api.get('/')
    assert page.status_code == 200 and 'SKYCONTROL' in page.text
    assert api.get('/static/js/main.js').status_code == 200
    assert api.get('/static/vendor/three.module.min.js').status_code == 200


def test_security_headers(api):
    r = api.get('/api/health')
    assert r.headers['X-Frame-Options'] == 'DENY'
    assert "script-src 'self'" in r.headers['Content-Security-Policy']
    assert r.headers['Cache-Control'] == 'no-store'


def test_dataset_register_and_snapshot(api, controller):
    names = [d['name'] for d in api.get('/api/data/datasets', headers=controller).json()]
    assert 'London-Amsterdam OpenSky recording' in names
    snaps = api.get('/api/data/snapshots', headers=controller).json()
    assert snaps and snaps[0]['aircraft_count'] == 284


def test_audit_is_supervisor_only(api, controller, supervisor):
    assert api.get('/api/audit', headers=controller).status_code == 403
    assert any(e['action'] == 'auth.login' for e in api.get('/api/audit', headers=supervisor).json())
