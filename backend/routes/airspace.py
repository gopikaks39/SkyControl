"""3D airspace replay of the real recording, live monitor outputs and emergency injection."""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, HTTPException, Request

from ..analytics import emergency, live
from ..analytics.recording import load
from ..auth import require
from ..database import audit, connect, one, rows, utcnow

router = APIRouter(prefix='/api/airspace')


@router.get('/meta')
def meta(request: Request):
    require(request)
    return live.meta()


@router.get('/tracks')
def tracks(request: Request):
    require(request)
    return live.tracks()


@router.get('/frame')
def frame(request: Request, offset: int = 0):
    require(request)
    rec = load()
    return live.frame(int(rec.frames[0]) + max(0, offset))


@router.get('/predictions')
def predictions(request: Request, offset: int = 0, horizon: int = 300):
    require(request)
    if horizon not in (60, 120, 300):
        raise HTTPException(400, 'Horizon must be 60, 120 or 300 seconds')
    rec = load()
    return live.predictions(int(rec.frames[0]) + max(0, offset), horizon)


@router.get('/emergency/kinds')
def kinds(request: Request):
    require(request)
    return [{'id': k, **v} for k, v in emergency.KINDS.items()]


@router.post('/emergency', status_code=201)
def inject(request: Request, body: dict = Body(...)):
    u = require(request, mutation=True)
    rec = load()
    try:
        offset = int(body.get('offset', 0))
        result = emergency.plan(rec, int(rec.frames[0]) + offset, str(body.get('icao', '')).lower(), body.get('kind', 'low_fuel'))
    except (TypeError, ValueError) as e:
        raise HTTPException(400, str(e))
    with connect() as db:
        c = db.execute('INSERT INTO emergency_runs (kind,icao24,callsign,recording_time,result_json,created_by,created_at) VALUES (?,?,?,?,?,?,?)',
                       (result['kind'], result['aircraft']['icao'], result['aircraft']['callsign'], result['time'], json.dumps(result),
                        u['username'], utcnow()))
        db.execute('INSERT INTO alerts (type,severity,message,source,created_at) VALUES (?,?,?,?,?)',
                   (result['title'], result['severity'], f"{result['aircraft']['callsign']}: {result['steps'][3]['detail']}", 'emergency_injection', utcnow()))
        audit(db, u['username'], 'emergency.inject', 'emergency_runs', c.lastrowid, {'kind': result['kind'], 'icao': result['aircraft']['icao']})
    return {'id': c.lastrowid, **result}


@router.get('/emergency/runs')
def runs(request: Request):
    require(request)
    with connect() as db:
        return rows(db.execute('SELECT id,kind,icao24,callsign,recording_time,status,created_by,created_at,reviewed_by FROM emergency_runs ORDER BY id DESC LIMIT 100'))


@router.post('/emergency/runs/{run_id}/review')
def review(run_id: int, request: Request, body: dict = Body(...)):
    u = require(request, mutation=True)
    decision = body.get('decision')
    if decision not in ('approve', 'reject'):
        raise HTTPException(400, 'decision must be approve or reject')
    with connect() as db:
        r = one(db.execute('SELECT * FROM emergency_runs WHERE id=?', (run_id,)))
        if not r:
            raise HTTPException(404, 'Run not found')
        approver = json.loads(r['result_json']).get('approver')
        if approver == 'supervisor' and u['role'] != 'supervisor':
            raise HTTPException(403, 'Supervisor approval required for this emergency plan')
        if r['status'] != 'Proposed':
            raise HTTPException(409, 'Already reviewed')
        status = 'Approved' if decision == 'approve' else 'Rejected'
        db.execute('UPDATE emergency_runs SET status=?, reviewed_by=?, reviewed_at=? WHERE id=?', (status, u['username'], utcnow(), run_id))
        audit(db, u['username'], 'emergency.' + decision, 'emergency_runs', run_id)
    return {'status': status}
