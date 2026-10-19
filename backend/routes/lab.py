"""Scenario Lab runtime: persistent runs, replay clock, approval gate and step-by-step progress."""
from __future__ import annotations

import json
import time

from fastapi import APIRouter, Body, HTTPException, Request

from ..auth import require
from ..core import scenarios
from ..core.separation import pos
from ..database import audit, connect, rows, utcnow
from ..opensky import get_snapshot

router = APIRouter(prefix='/api/lab')
ENGINE = 7
EXECUTING = ('Approved', 'Overridden', 'Not required')


def advance(d, elapsed):
    """Move the replay clock; the run stops at the approval gate until a decision is made."""
    if d['playing']:
        old = d['time']
        d['time'] = min(d['duration'], old + max(0.0, elapsed) * d['speed'])
        if d['approval'] in ('Pending', 'Rejected'):
            d['time'] = min(d['gate'], d['time'])
        for e in d['planned_events']:
            if old < e['t'] <= d['time']:
                d['events'].append(e)
        if d['time'] >= d['duration']:
            d['playing'] = False
            d['outcome'] = 'Resolved' if d['plan_valid'] else 'Unresolved'
            if old < d['duration']:
                d['events'].append({'t': d['duration'], 'message': d['outcome'] + ': all aircraft reached their terminal state'})
        elif d['approval'] in EXECUTING:
            d['outcome'] = 'Executing approved plan'
    return d


def frame(d):
    """Add positions, step status and current automation level for the client."""
    if d.get('engine_version') != ENGINE:
        raise HTTPException(409, 'This saved exercise uses an older engine. Start a new scenario.')
    key = 'resolved' if d['approval'] in EXECUTING else 'baseline'
    t = d['time']
    d['positions'] = [{'name': a['name'], **pos(a[key], t), 'action': a['action'], 'role': a.get('role', 'traffic'),
                       'complete': t >= a[key][-1]['t']} for a in d['aircraft']]
    d['waiting'] = t >= d['gate'] and d['approval'] in ('Pending', 'Rejected')
    level = d['context_log'][0]['level']
    for entry in d['context_log']:
        if entry['t'] <= t:
            level = entry['level']
    d['current_level'] = level
    for step in d['steps']:
        if step['phase'] == 'AUTHORISE':
            step['status'] = 'done' if d['approval'] in EXECUTING else ('active' if t >= step['t'] else 'pending')
        elif step['t'] <= t and (step['t'] <= d['gate'] or d['approval'] in EXECUTING):
            step['status'] = 'done'
        else:
            step['status'] = 'pending'
    nxt = next((s for s in d['steps'] if s['status'] == 'pending'), None)
    if nxt and not d['waiting']:
        nxt['status'] = 'active'
    return d


def _source_flights(body):
    if body.get('snapshot_id'):
        snap = get_snapshot(int(body['snapshot_id']))
        if not snap:
            raise HTTPException(404, 'Snapshot not found')
        return snap['aircraft'], f"Recorded callsigns - {snap['provider']} - {snap['observed_at']}"
    if body.get('source') == 'managed':
        with connect() as db:
            return rows(db.execute("SELECT * FROM flights WHERE status NOT IN ('Cancelled','Landed') ORDER BY id")), 'Managed classroom flights'
    from ..analytics.recording import load
    rec = load()
    offset = int(body.get('recording_offset', 1800))
    ts, idx = rec.frame_at(rec.frames[0] + offset)
    names = [{'callsign': rec.obs_callsign[i]} for i in idx if rec.obs_callsign[i] and rec.airborne[i]]
    return names, f"Callsigns airborne at {time.strftime('%H:%M:%S', time.gmtime(int(ts)))} UTC in the London-Amsterdam recording"


@router.get('/catalog')
def catalog(request: Request):
    require(request)
    return scenarios.catalog()


@router.get('/benchmark')
def benchmark(request: Request):
    require(request)
    return scenarios.benchmark()


@router.post('/runs', status_code=201)
def create(request: Request, body: dict = Body(...)):
    u = require(request, mutation=True)
    key = body.get('scenario', 'collision')
    if key not in scenarios.SPECS:
        raise HTTPException(400, 'Unknown scenario')
    flights, source = _source_flights(body)
    try:
        d = scenarios.build(key, flights, source)
    except ValueError as e:
        raise HTTPException(400, str(e))
    d['created_at'] = utcnow()
    d['created_by'] = u['username']
    with connect() as db:
        c = db.execute('INSERT INTO lab_runs (scenario,data,created_by,updated) VALUES (?,?,?,?)', (key, '{}', u['username'], time.time()))
        d['id'] = c.lastrowid
        if d['approval'] != 'Not required':
            alert = db.execute('INSERT INTO alerts (type,severity,message,source,created_at) VALUES (?,?,?,?,?)',
                               (d['title'], d['severity'], f"Scenario #{d['id']}: {d['problem']}", 'scenario_lab', utcnow()))
            d['alert_id'] = alert.lastrowid
        db.execute('UPDATE lab_runs SET data=? WHERE id=?', (json.dumps(d), d['id']))
        audit(db, u['username'], 'lab.create', 'lab_runs', d['id'], {'scenario': key})
    return frame(d)


@router.get('/runs')
def list_runs(request: Request):
    require(request)
    with connect() as db:
        out = []
        for r in rows(db.execute('SELECT id, scenario, created_by, data FROM lab_runs ORDER BY id DESC LIMIT 50')):
            d = json.loads(r['data'])
            out.append({'id': r['id'], 'scenario': r['scenario'], 'title': d.get('title'), 'created_by': r['created_by'],
                        'approval': d.get('approval'), 'outcome': d.get('outcome'), 'created_at': d.get('created_at')})
        return out


def _load(db, run_id):
    r = db.execute('SELECT * FROM lab_runs WHERE id=?', (run_id,)).fetchone()
    if not r:
        raise HTTPException(404, 'Run not found')
    return r


@router.get('/runs/{run_id}')
def get_run(run_id: int, request: Request):
    require(request)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        r = _load(db, run_id)
        now = time.time()
        d = json.loads(r['data'])
        if d.get('engine_version') == ENGINE:
            d = advance(d, now - r['updated'])
            if d.get('outcome') == 'Resolved' and d.get('alert_id'):
                db.execute("UPDATE alerts SET status='Resolved', updated_at=? WHERE id=?", (utcnow(), d['alert_id']))
        db.execute('UPDATE lab_runs SET data=?, updated=? WHERE id=?', (json.dumps(d), now, run_id))
        db.commit()
    return frame(d)


@router.post('/runs/{run_id}/control')
def control(run_id: int, request: Request, body: dict = Body(...)):
    u = require(request, mutation=True)
    op = body.get('action')
    note = str(body.get('note') or '').strip()[:300]
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        r = _load(db, run_id)
        now = time.time()
        d = json.loads(r['data'])
        if d.get('engine_version') != ENGINE:
            raise HTTPException(409, 'Start a new exercise to use the updated engine')
        d = advance(d, now - r['updated'])
        if op in ('approve', 'reject', 'override'):
            if d['approval'] not in ('Pending', 'Rejected'):
                raise HTTPException(409, 'This plan has already been reviewed')
            if op != 'reject' and not d['plan_valid']:
                raise HTTPException(409, 'Plan fails the safety checks; approval is blocked')
            needs_supervisor = d.get('approver') == 'supervisor' or op == 'override'
            if needs_supervisor and u['role'] != 'supervisor':
                raise HTTPException(403, 'Supervisor approval required. Sign in as a supervisor; this run is kept.')
            if op == 'override' and not note:
                raise HTTPException(400, 'Enter a reason for the override')
            d['approval'] = {'approve': 'Approved', 'reject': 'Rejected', 'override': 'Overridden'}[op]
            d['reviewed_by'] = u['username']
            if op != 'reject':
                d['playing'] = True
            d['events'].append({'t': round(d['time']), 'message': f"{u['username']} ({u['role']}): {d['approval']}" + (f' - {note}' if note else '')})
        elif op == 'play':
            d['playing'] = True
        elif op == 'pause':
            d['playing'] = False
        elif op == 'reset':
            d.update(time=0, playing=False, outcome='Awaiting execution',
                     approval='Not required' if d.get('approver') is None else 'Pending',
                     events=[{'t': 0, 'message': 'Exercise reset; review required again'}])
            if d.get('alert_id'):
                db.execute("UPDATE alerts SET status='Open', updated_at=? WHERE id=?", (utcnow(), d['alert_id']))
        elif op == 'speed':
            if body.get('speed') not in (1, 2, 5, 10, 16, 32, 64):
                raise HTTPException(400, 'Choose an available replay speed')
            d['speed'] = body['speed']
        elif op == 'seek':
            try:
                target = float(body.get('time'))
            except (TypeError, ValueError):
                raise HTTPException(400, 'time required')
            limit = d['duration'] if d['approval'] in EXECUTING else d['gate']
            d['time'] = max(0.0, min(limit, target))
            d['events'] = [e for e in d['events'] if e['t'] <= d['time']] + \
                          [e for e in d['planned_events'] if e['t'] <= d['time'] and e not in d['events']]
        else:
            raise HTTPException(400, 'Unknown control')
        db.execute('UPDATE lab_runs SET data=?, updated=? WHERE id=?', (json.dumps(d), now, run_id))
        audit(db, u['username'], 'lab.' + op, 'lab_runs', run_id, {'note': note} if note else None)
        db.commit()
    return frame(d)
