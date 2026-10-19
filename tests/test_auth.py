"""Login portal: verified credentials, wrong-credential handling, stored attempts, lockout, CSRF, roles."""
from conftest import CONTROLLER_PASSWORD, SUPERVISOR_PASSWORD


def test_wrong_password_is_rejected_and_stored(api, supervisor):
    r = api.post('/api/auth/login', json={'username': 'controller', 'password': 'not-the-password1'})
    assert r.status_code == 401
    assert r.json()['error'] == 'Wrong username or password'
    assert r.json()['details']['attempts_remaining'] == 6
    attempts = api.get('/api/auth/attempts', headers=supervisor).json()['attempts']
    failed = [a for a in attempts if a['username'] == 'controller' and not a['successful']]
    assert len(failed) == 1 and failed[0]['reason'] == 'wrong_password'


def test_unknown_username_gets_the_same_message_and_is_stored(api, supervisor):
    r = api.post('/api/auth/login', json={'username': 'intruder', 'password': 'whatever12345'})
    assert r.status_code == 401
    assert r.json()['error'] == 'Wrong username or password'
    reasons = {a['username']: a['reason'] for a in api.get('/api/auth/attempts', headers=supervisor).json()['attempts']}
    assert reasons['intruder'] == 'unknown_username'


def test_every_attempt_is_recorded_without_passwords(api, supervisor):
    for pwd in ('bad-one-111', 'bad-two-222', CONTROLLER_PASSWORD):
        api.post('/api/auth/login', json={'username': 'controller', 'password': pwd})
    data = api.get('/api/auth/attempts', headers=supervisor).json()
    rows = [a for a in data['attempts'] if a['username'] == 'controller']
    assert [a['successful'] for a in rows] == [1, 0, 0]
    assert all(set(a) >= {'ip', 'user_agent', 'reason', 'created_at'} for a in rows)
    assert 'bad-one' not in str(data) and CONTROLLER_PASSWORD not in str(data)


def test_lockout_after_seven_failures_even_with_correct_password(api, supervisor):
    for _ in range(7):
        assert api.post('/api/auth/login', json={'username': 'controller', 'password': 'WRONG-pass-1'}).status_code == 401
    blocked = api.post('/api/auth/login', json={'username': 'controller', 'password': CONTROLLER_PASSWORD})
    assert blocked.status_code == 429
    reasons = [a['reason'] for a in api.get('/api/auth/attempts', headers=supervisor).json()['attempts'] if a['username'] == 'controller']
    assert reasons[0] == 'locked_out' and reasons.count('wrong_password') == 7


def test_attempt_log_is_supervisor_only(api, controller):
    assert api.get('/api/auth/attempts', headers=controller).status_code == 403


def test_unauthenticated_requests_and_csrf(api):
    assert api.get('/api/flights').status_code == 401
    d = api.post('/api/auth/login', json={'username': 'controller', 'password': CONTROLLER_PASSWORD}).json()
    alert = {'type': 'Test', 'severity': 'High', 'message': 'x'}
    assert api.post('/api/alerts', json=alert).status_code == 403          # cookie session without CSRF header
    assert api.post('/api/alerts', json=alert, headers={'X-CSRF-Token': d['csrf']}).status_code == 201


def test_supervisor_creates_and_disables_users(api, supervisor):
    weak = api.post('/api/auth/users', json={'username': 'trainee', 'password': 'short', 'role': 'controller'}, headers=supervisor)
    assert weak.status_code == 400
    ok = api.post('/api/auth/users', json={'username': 'trainee', 'password': 'trainee2026pass', 'role': 'controller'}, headers=supervisor)
    assert ok.status_code == 201
    assert api.post('/api/auth/login', json={'username': 'trainee', 'password': 'trainee2026pass'}).status_code == 200
    api.put(f"/api/auth/users/{ok.json()['id']}/active", json={'active': False}, headers=supervisor)
    r = api.post('/api/auth/login', json={'username': 'trainee', 'password': 'trainee2026pass'})
    assert r.status_code == 401


def test_password_change_requires_current_password(api, controller):
    assert api.post('/api/auth/password', json={'current': 'wrong', 'password': 'newpassword2026'}, headers=controller).status_code == 403
    assert api.post('/api/auth/password', json={'current': CONTROLLER_PASSWORD, 'password': 'newpassword2026'}, headers=controller).status_code == 200
    assert api.post('/api/auth/login', json={'username': 'controller', 'password': 'newpassword2026'}).status_code == 200


def test_me_and_logout(api):
    r = api.post('/api/auth/login', json={'username': 'supervisor', 'password': SUPERVISOR_PASSWORD})
    me = api.get('/api/auth/me').json()
    assert me['user']['role'] == 'supervisor'
    assert api.post('/api/auth/logout', headers={'X-CSRF-Token': r.json()['csrf']}).status_code == 200
    assert api.get('/api/auth/me').status_code == 401
