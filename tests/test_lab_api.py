"""Scenario Lab API: approval gate, roles, persistence across accounts and replay controls."""


def test_critical_plan_needs_supervisor_and_run_persists(api, controller, supervisor):
    run = api.post('/api/lab/runs', json={'scenario': 'low_fuel'}, headers=controller).json()
    assert run['approval'] == 'Pending' and run['approver'] == 'supervisor'
    denied = api.post(f"/api/lab/runs/{run['id']}/control", json={'action': 'approve'}, headers=controller)
    assert denied.status_code == 403
    ok = api.post(f"/api/lab/runs/{run['id']}/control", json={'action': 'approve'}, headers=supervisor)
    assert ok.json()['approval'] == 'Approved'
    assert api.post(f"/api/lab/runs/{run['id']}/control", json={'action': 'approve'}, headers=supervisor).status_code == 409


def test_controller_can_approve_high_severity_consent(api, controller):
    run = api.post('/api/lab/runs', json={'scenario': 'readback_error'}, headers=controller).json()
    assert run['current_level'] == 'CONSENT'
    r = api.post(f"/api/lab/runs/{run['id']}/control", json={'action': 'approve'}, headers=controller)
    assert r.status_code == 200 and r.json()['approval'] == 'Approved'


def test_normal_runs_without_approval_and_controls(api, controller, supervisor):
    run = api.post('/api/lab/runs', json={'scenario': 'normal'}, headers=controller).json()
    assert run['approval'] == 'Not required' and run['current_level'] == 'AUTO'
    rid = run['id']
    assert api.post(f'/api/lab/runs/{rid}/control', json={'action': 'speed', 'speed': 3}, headers=controller).status_code == 400
    assert api.post(f'/api/lab/runs/{rid}/control', json={'action': 'speed', 'speed': 64}, headers=controller).json()['speed'] == 64
    seek = api.post(f'/api/lab/runs/{rid}/control', json={'action': 'seek', 'time': 300}, headers=controller).json()
    assert seek['time'] == 300 and any(s['status'] == 'done' for s in seek['steps'])
    assert api.post(f'/api/lab/runs/{rid}/control', json={'action': 'override'}, headers=supervisor).status_code == 409


def test_override_requires_reason_and_supervisor(api, controller, supervisor):
    rid = api.post('/api/lab/runs', json={'scenario': 'weather'}, headers=controller).json()['id']
    assert api.post(f'/api/lab/runs/{rid}/control', json={'action': 'override', 'note': 'x'}, headers=controller).status_code == 403
    assert api.post(f'/api/lab/runs/{rid}/control', json={'action': 'override'}, headers=supervisor).status_code == 400
    r = api.post(f'/api/lab/runs/{rid}/control', json={'action': 'override', 'note': 'Weather radar confirms cell'}, headers=supervisor)
    assert r.json()['approval'] == 'Overridden'


def test_runs_from_recording_and_managed_sources(api, controller):
    rec = api.post('/api/lab/runs', json={'scenario': 'collision', 'source': 'recording'}, headers=controller).json()
    assert 'London-Amsterdam recording' in rec['source']
    managed = api.post('/api/lab/runs', json={'scenario': 'medical', 'source': 'managed'}, headers=controller).json()
    assert managed['source'] == 'Managed classroom flights'
    assert len(api.get('/api/lab/runs', headers=controller).json()) == 2
