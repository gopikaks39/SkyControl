"""Login portal security: PBKDF2 passwords, opaque sessions, CSRF, lockout and a full attempt log.

Every login attempt (right or wrong) is written to auth_attempts with the
username tried, client IP, user agent, outcome and reason. Wrong credentials
always get the same message so the response does not reveal whether the
username exists. Seven failures for one username, or forty from one IP,
within 15 minutes lock further attempts for the rest of that window.
"""
from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from .config import LOGIN_IP_LIMIT, LOGIN_LOCKOUT_FAILURES, LOGIN_WINDOW_MINUTES, SESSION_HOURS
from .database import audit, connect, one, utcnow

ITERATIONS = 310000
WRONG_CREDENTIALS = 'Wrong username or password'
LOCKED = f'Too many failed attempts. Try again in {LOGIN_WINDOW_MINUTES} minutes.'


def hash_password(pwd, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', pwd.encode(), bytes.fromhex(salt), ITERATIONS).hex()
    return f'pbkdf2_sha256${ITERATIONS}${salt}${digest}'


def check_password(pwd, encoded):
    try:
        alg, iterations, salt, digest = encoded.split('$')
        if alg != 'pbkdf2_sha256':
            return False
        check = hashlib.pbkdf2_hmac('sha256', pwd.encode(), bytes.fromhex(salt), int(iterations)).hex()
        return hmac.compare_digest(check, digest)
    except (ValueError, TypeError):
        return False


def password_problems(pwd):
    """Simple policy: 12+ characters with letters and digits."""
    problems = []
    if len(pwd) < 12:
        problems.append('at least 12 characters')
    if len(pwd) > 256:
        problems.append('at most 256 characters')
    if not re.search(r'[A-Za-z]', pwd) or not re.search(r'\d', pwd):
        problems.append('letters and digits')
    return problems


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def login(username, password, ip, user_agent=''):
    username = str(username or '').strip()[:80]
    password = str(password or '')[:512]
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=LOGIN_WINDOW_MINUTES)).isoformat(timespec='seconds')
        failures = db.execute('SELECT COUNT(*) FROM auth_attempts WHERE username=? AND successful=0 AND created_at>=?',
                              (username, cutoff)).fetchone()[0]
        ip_failures = db.execute('SELECT COUNT(*) FROM auth_attempts WHERE ip=? AND successful=0 AND created_at>=?',
                                 (ip, cutoff)).fetchone()[0]
        user = one(db.execute('SELECT * FROM users WHERE username=?', (username,)))
        valid = bool(user and user['active'] and check_password(password, user['password_hash']))
        if not username:
            reason = 'missing_username'
        elif ip_failures >= LOGIN_IP_LIMIT:
            reason = 'ip_rate_limited'
        elif failures >= LOGIN_LOCKOUT_FAILURES:
            reason = 'locked_out'
        elif valid:
            reason = 'success'
        elif user and not user['active']:
            reason = 'account_disabled'
        elif user:
            reason = 'wrong_password'
        else:
            reason = 'unknown_username'
        successful = reason == 'success'
        db.execute('INSERT INTO auth_attempts (username,ip,user_agent,successful,reason,created_at) VALUES (?,?,?,?,?,?)',
                   (username, ip, str(user_agent or '')[:200], int(successful), reason, utcnow()))
        audit(db, username or 'anonymous', 'auth.login', 'users', user['id'] if user else '',
              {'successful': successful, 'reason': reason, 'ip': ip})
        if not successful:
            db.commit()
            locked = reason in ('locked_out', 'ip_rate_limited')
            remaining = max(0, LOGIN_LOCKOUT_FAILURES - failures - 1)
            raise HTTPException(status_code=429 if locked else 401,
                                detail={'message': LOCKED if locked else WRONG_CREDENTIALS,
                                        'attempts_remaining': 0 if locked else remaining})
        token, csrf = secrets.token_urlsafe(40), secrets.token_urlsafe(24)
        expires = (datetime.now(timezone.utc) + timedelta(hours=SESSION_HOURS)).isoformat(timespec='seconds')
        db.execute('INSERT INTO sessions (user_id,token_hash,csrf,created_at,expires_at) VALUES (?,?,?,?,?)',
                   (user['id'], token_hash(token), csrf, utcnow(), expires))
        db.commit()
    return {'token': token, 'csrf': csrf, 'expires_at': expires,
            'user': {'id': user['id'], 'username': user['username'], 'full_name': user['full_name'], 'role': user['role']}}


def identity(request: Request, mutation=False):
    bearer = request.headers.get('authorization', '')
    token = bearer[7:] if bearer.lower().startswith('bearer ') else request.cookies.get('skycontrol_session', '')
    if not token:
        raise HTTPException(status_code=401, detail='Authentication required')
    with connect() as db:
        session = one(db.execute('SELECT s.*,u.username,u.full_name,u.role,u.active FROM sessions s '
                                 'JOIN users u ON u.id=s.user_id WHERE s.token_hash=?', (token_hash(token),)))
    if not session or not session['active'] or session['expires_at'] < utcnow():
        raise HTTPException(status_code=401, detail='Session expired or invalid')
    if mutation and not bearer.lower().startswith('bearer '):
        if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), session['csrf']):
            raise HTTPException(status_code=403, detail='CSRF token missing or invalid')
    return session


def require(request, supervisor=False, mutation=False):
    user = identity(request, mutation)
    if supervisor and user['role'] != 'supervisor':
        raise HTTPException(status_code=403, detail='Supervisor role required')
    return user


def create_user(db, username, password, role, full_name='', created_by='setup'):
    username = str(username or '').strip()
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{3,40}', username):
        raise ValueError('Username must be 3-40 letters, digits, dot, dash or underscore')
    if role not in ('controller', 'supervisor'):
        raise ValueError('Role must be controller or supervisor')
    problems = password_problems(password)
    if problems:
        raise ValueError('Password needs ' + ', '.join(problems))
    db.execute('INSERT INTO users (username,full_name,password_hash,role,created_at,created_by) VALUES (?,?,?,?,?,?)',
               (username, str(full_name or '')[:80], hash_password(password), role, utcnow(), created_by))
