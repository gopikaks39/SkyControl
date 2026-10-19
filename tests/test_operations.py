"""Flights, runways, runway calendar, priority queue, alerts and incident reports."""
from datetime import datetime, timedelta, timezone


def iso(minutes):
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).replace(microsecond=0).isoformat()


def test_flight_crud_validation_and_cancel(api, controller):
    d = {'flight_number': 'UT001', 'airline': 'TestAir', 'origin': 'EGLL', 'destination': 'EHAM', 'flight_time': '20:00', 'status': 'Scheduled'}
    r = api.post('/api/flights', json=d, headers=controller)
    assert r.status_code == 201
    fid = r.json()['id']
    assert api.post('/api/flights', json=d, headers=controller).status_code == 409
    assert api.post('/api/flights', json={**d, 'flight_number': 'UT002', 'fuel_pct': 140}, headers=controller).status_code == 400
    assert api.put(f'/api/flights/{fid}', json={'status': 'Emergency'}, headers=controller).json()['priority'] == 'Critical'
    assert api.post(f'/api/flights/{fid}/cancel', headers=controller).json()['status'] == 'Cancelled'
    assert any(f['flight_number'] == 'UT001' for f in api.get('/api/flights?q=UT0', headers=controller).json())


def test_runway_allocation_blocks_conflicts_and_raises_alert(api, controller, supervisor):
    runways = api.get('/api/runways', headers=controller).json()
    flights = api.get('/api/flights', headers=controller).json()
    rid, a, b = runways[0]['id'], flights[0]['id'], flights[1]['id']
    assert api.put(f'/api/runways/{rid}/allocate', json={'flight_id': a}, headers=controller).status_code == 200
    blocked = api.put(f'/api/runways/{rid}/allocate', json={'flight_id': b}, headers=controller)
    assert blocked.status_code == 409
    assert any(x['type'] == 'Runway conflict' for x in api.get('/api/alerts', headers=controller).json())
    assert api.put(f'/api/runways/{rid}/status', json={'status': 'Closed'}, headers=supervisor).status_code == 409
    api.put(f'/api/runways/{rid}/release', headers=controller)
    assert api.put(f'/api/runways/{rid}/status', json={'status': 'Closed'}, headers=controller).status_code == 403
    assert api.put(f'/api/runways/{rid}/status', json={'status': 'Closed'}, headers=supervisor).status_code == 200


def test_runway_calendar_conflict_returns_alternatives(api, controller):
    flights = api.get('/api/flights', headers=controller).json()
    runway = api.get('/api/runways', headers=controller).json()[2]['id']
    slot = {'flight_id': flights[0]['id'], 'runway_id': runway, 'operation': 'arrival', 'start_at': iso(30), 'end_at': iso(34), 'confirm': True}
    assert api.post('/api/schedule/bookings', json=slot, headers=controller).status_code == 201
    clash = api.post('/api/schedule/bookings', json={**slot, 'flight_id': flights[1]['id']}, headers=controller)
    assert clash.status_code == 409
    assert clash.json()['details']['alternatives']
    assert api.post('/api/schedule/bookings', json={**slot, 'flight_id': flights[1]['id'], 'confirm': False}, headers=controller).status_code == 400


def test_priority_queue_puts_emergencies_first(api, controller):
    queue = api.get('/api/priority-queue', headers=controller).json()
    assert queue[0]['status'] == 'Emergency'


def test_alert_lifecycle_and_incident_report(api, controller):
    a = api.post('/api/alerts', json={'type': 'Test', 'severity': 'Low', 'message': 'hello'}, headers=controller).json()
    assert api.put(f"/api/alerts/{a['id']}/acknowledge", headers=controller).status_code == 200
    assert api.put(f"/api/alerts/{a['id']}/resolve", headers=controller).status_code == 200
    fid = api.get('/api/flights', headers=controller).json()[0]['id']
    r = api.post('/api/incident-reports', json={'flight_id': fid, 'category': 'Low fuel', 'details': 'Crew report', 'source_kind': 'crew_report_transcribed',
                                               'reported_fuel_pct': 8}, headers=controller)
    assert r.status_code == 201
    assert any(x['type'] == 'Unverified incident report' for x in api.get('/api/alerts', headers=controller).json())


def test_dashboard_counts_failed_logins(api, controller):
    api.post('/api/auth/login', json={'username': 'controller', 'password': 'nope-nope-1'})
    d = api.get('/api/dashboard', headers=controller).json()
    assert d['failed_logins_24h'] >= 1 and d['runways_total'] == 5
