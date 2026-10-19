"""Login portal, session, password change, login-attempt log and user management."""
from __future__ import annotations

import os
import sqlite3

from fastapi import APIRouter, Body, HTTPException, Request, Response

from ..auth import check_password, create_user, hash_password, login, password_problems, require
from ..config import SESSION_HOURS
from ..database import audit, connect, one, rows

router = APIRouter(prefix='/api/auth')


@router.post('/login')
def signin(request: Request, response: Response, body: dict = Body(...)):
    if not isinstance(body, dict):
        raise HTTPException(400, 'JSON object required')
    result = login(body.get('username'), body.get('password'), request.client.host if request.client else '',
                   request.headers.get('user-agent', ''))
    response.set_cookie('skycontrol_session', result['token'], httponly=True, samesite='lax',
                        secure=os.getenv('SKYCONTROL_HTTPS') == '1', max_age=SESSION_HOURS * 3600, path='/')
    return {'message': 'Login successful', **result}


@router.post('/logout')
def logout(request: Request, response: Response):
    user = require(request, mutation=True)
    with connect() as db:
        db.execute('DELETE FROM sessions WHERE id=?', (user['id'],))
        audit(db, user['username'], 'auth.logout', 'sessions', user['id'])
    response.delete_cookie('skycontrol_session', path='/')
    return {'message': 'Signed out'}


@router.get('/me')
def me(request: Request):
    u = require(request)
    return {'user': {'id': u['user_id'], 'username': u['username'], 'full_name': u['full_name'], 'role': u['role']},
            'csrf': u['csrf'], 'expires_at': u['expires_at']}


@router.post('/password')
def change_password(request: Request, body: dict = Body(...)):
    u = require(request, mutation=True)
    new = str(body.get('password', ''))
    problems = password_problems(new)
    if problems:
        raise HTTPException(400, 'Password needs ' + ', '.join(problems))
    with connect() as db:
        current = db.execute('SELECT password_hash FROM users WHERE id=?', (u['user_id'],)).fetchone()
        if not check_password(str(body.get('current', '')), current[0]):
            raise HTTPException(403, 'Current password is incorrect')
        db.execute('UPDATE users SET password_hash=? WHERE id=?', (hash_password(new), u['user_id']))
        db.execute('DELETE FROM sessions WHERE user_id=? AND id!=?', (u['user_id'], u['id']))
        audit(db, u['username'], 'auth.password_changed', 'users', u['user_id'])
    return {'message': 'Password changed; other sessions signed out'}


@router.get('/attempts')
def attempts(request: Request, limit: int = 200, failed_only: bool = False):
    require(request, supervisor=True)
    query = 'SELECT id,username,ip,user_agent,successful,reason,created_at FROM auth_attempts'
    if failed_only:
        query += ' WHERE successful=0'
    with connect() as db:
        items = rows(db.execute(query + ' ORDER BY id DESC LIMIT ?', (min(max(limit, 1), 1000),)))
        summary = rows(db.execute('SELECT reason, COUNT(*) AS count FROM auth_attempts GROUP BY reason ORDER BY count DESC'))
    return {'attempts': items, 'summary': summary}


@router.get('/users')
def users(request: Request):
    require(request, supervisor=True)
    with connect() as db:
        return rows(db.execute('SELECT id,username,full_name,role,active,created_at,created_by FROM users ORDER BY id'))


@router.post('/users', status_code=201)
def add_user(request: Request, body: dict = Body(...)):
    u = require(request, supervisor=True, mutation=True)
    with connect() as db:
        try:
            create_user(db, body.get('username'), str(body.get('password', '')), body.get('role'),
                        body.get('full_name', ''), u['username'])
        except ValueError as e:
            raise HTTPException(400, str(e))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Username already exists')
        audit(db, u['username'], 'user.create', 'users', body.get('username'), {'role': body.get('role')})
        return one(db.execute('SELECT id,username,full_name,role,active,created_at,created_by FROM users WHERE username=?',
                              (body.get('username'),)))


@router.put('/users/{user_id}/active')
def set_active(user_id: int, request: Request, body: dict = Body(...)):
    u = require(request, supervisor=True, mutation=True)
    if user_id == u['user_id']:
        raise HTTPException(409, 'You cannot disable your own account')
    active = 1 if body.get('active') else 0
    with connect() as db:
        c = db.execute('UPDATE users SET active=? WHERE id=?', (active, user_id))
        if not c.rowcount:
            raise HTTPException(404, 'User not found')
        if not active:
            db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
        audit(db, u['username'], 'user.active', 'users', user_id, {'active': bool(active)})
    return {'active': bool(active)}
