"""Dataset register, OpenSky snapshots (import / live capture), historical counts and the audit log."""
from __future__ import annotations

import csv
import json
from datetime import datetime, timezone

from fastapi import APIRouter, Body, HTTPException, Request

from ..auth import require
from ..config import DATA_DIR
from ..database import connect, one, rows, utcnow
from ..opensky import feed_health, fetch_live, get_snapshot, save_payload, snapshot_freshness

router = APIRouter(prefix='/api')


@router.get('/data/datasets')
def datasets(request: Request):
    require(request)
    with connect() as db:
        return rows(db.execute('SELECT * FROM datasets ORDER BY id'))


@router.get('/data/snapshots')
def snapshots(request: Request):
    require(request)
    with connect() as db:
        return rows(db.execute('SELECT * FROM snapshots ORDER BY id DESC LIMIT 300'))


@router.get('/data/snapshots/{snapshot_id}')
def snapshot(snapshot_id: int, request: Request):
    require(request)
    result = get_snapshot(snapshot_id)
    if not result:
        raise HTTPException(404, 'Snapshot not found')
    result['freshness'] = snapshot_freshness(result, result['aircraft'])
    return result


@router.post('/data/import', status_code=201)
def import_opensky(request: Request, body: dict = Body(...)):
    user = require(request, mutation=True)
    try:
        return save_payload(body, user['username'], provider='OpenSky format - user-supplied (unverified)', dataset_type='imported')
    except (ValueError, OverflowError) as e:
        raise HTTPException(400, str(e))


@router.get('/data/feed-health')
def health(request: Request):
    require(request)
    return feed_health()


@router.post('/data/capture', status_code=201)
def capture(request: Request, body: dict = Body(default={})):
    """Live OpenSky request. Never fabricates data: failures are logged and returned as errors."""
    user = require(request, mutation=True)
    bounds = {k: body.get(k, default) for k, default in (('lamin', 49.5), ('lamax', 54.5), ('lomin', -2.0), ('lomax', 3.0))}
    with connect() as db:
        latest = one(db.execute("SELECT * FROM snapshots WHERE dataset_type='live' ORDER BY id DESC LIMIT 1"))
    if latest and latest.get('notes') == json.dumps(bounds) and \
            (datetime.now(timezone.utc) - datetime.fromisoformat(latest['recorded_at'])).total_seconds() < 60:
        return {'snapshot_id': latest['id'], 'cached': True, 'aircraft_count': latest['aircraft_count']}
    try:
        payload = fetch_live(bounds)
        result = save_payload(payload, user['username'], provider='OpenSky Network REST /states/all', dataset_type='live',
                              notes=json.dumps(bounds))
        with connect() as db:
            db.execute('INSERT INTO feed_events (event_type,success,detail,recorded_at) VALUES (?,?,?,?)', ('capture', 1, 'saved', utcnow()))
        return result
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # network or provider failure
        with connect() as db:
            db.execute('INSERT INTO feed_events (event_type,success,detail,recorded_at) VALUES (?,?,?,?)',
                       ('capture', 0, type(e).__name__[:80], utcnow()))
        raise HTTPException(502, 'OpenSky live capture unavailable: ' + str(e)[:200])


@router.get('/data/traffic-history')
def traffic_history(request: Request):
    require(request)
    with open(DATA_DIR / 'historical_airport_traffic_2011_feb.csv') as fp:
        history = list(csv.DictReader(fp))
    return {'dataset': 'Historical US airport counts, February 2011 (public Plotly dataset)',
            'provenance': 'https://github.com/plotly/datasets/blob/master/2011_february_us_airport_traffic.csv',
            'limitation': 'Single-month airport-level aggregate. Not trajectories and not used for training.',
            'records': [{'airport': r['airport'], 'iata': r['iata'], 'latitude': float(r['lat']), 'longitude': float(r['long']),
                         'count': int(r['cnt'])} for r in history]}


@router.get('/audit')
def audit_log(request: Request, limit: int = 200):
    require(request, supervisor=True)
    with connect() as db:
        return rows(db.execute('SELECT * FROM audit_events ORDER BY id DESC LIMIT ?', (min(max(limit, 1), 1000),)))
