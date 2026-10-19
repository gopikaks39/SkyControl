"""Day-to-day operations: flights, runways, runway calendar, priority queue, alerts and incident reports."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Body, HTTPException, Request

from ..auth import require
from ..database import audit, connect, one, rows, utcnow
from ..scheduling import capacity_disclaimer, check as check_slot, iso, label as iso_label, parsed as parse_slot, suggest as slot_suggest

router = APIRouter(prefix='/api')

FLIGHT_FIELDS = ('flight_number', 'airline', 'origin', 'destination', 'flight_time', 'runway', 'status', 'priority',
                 'fuel_pct', 'latitude', 'longitude', 'altitude_ft', 'heading_deg', 'speed_kt')
STATUSES = ('Scheduled', 'In Air', 'Approach', 'Delayed', 'Emergency', 'Landed', 'Cancelled')
PRIORITIES = ('Normal', 'High', 'Critical')
SEVERITIES = ('Low', 'Medium', 'High', 'Critical')


def validate_flight(payload, partial=False):
    if not isinstance(payload, dict):
        raise HTTPException(400, 'JSON object required')
    if not partial:
        for key in ('flight_number', 'airline', 'origin', 'destination', 'flight_time', 'status'):
            if not payload.get(key):
                raise HTTPException(400, f'{key} is required')
    if not any(k in FLIGHT_FIELDS for k in payload):
        raise HTTPException(400, 'No editable field provided')
    for key in ('flight_number', 'airline', 'origin', 'destination', 'flight_time'):
        if key in payload and (not isinstance(payload[key], str) or not payload[key].strip() or len(payload[key]) > 90):
            raise HTTPException(400, f'Invalid {key}')
    if 'status' in payload and payload['status'] not in STATUSES:
        raise HTTPException(400, 'Invalid flight status')
    if 'priority' in payload and payload['priority'] not in PRIORITIES:
        raise HTTPException(400, 'Invalid priority')
    for key, lo, hi in (('fuel_pct', 0, 100), ('latitude', -90, 90), ('longitude', -180, 180), ('altitude_ft', -1500, 65000),
                        ('speed_kt', 0, 1500), ('heading_deg', 0, 360)):
        if payload.get(key) is not None:
            try:
                value = float(payload[key])
            except (TypeError, ValueError):
                raise HTTPException(400, f'Invalid {key}')
            if not lo <= value <= hi:
                raise HTTPException(400, f'Out-of-range {key}')
    if payload.get('runway') not in (None, '', '-'):
        with connect() as db:
            if not db.execute('SELECT 1 FROM runways WHERE runway_code=?', (payload['runway'],)).fetchone():
                raise HTTPException(400, 'Unknown runway')


# ---------------------------------------------------------------- flights

@router.get('/flights')
def flights(request: Request, q: str = '', status: str = ''):
    require(request)
    query, args = 'SELECT * FROM flights WHERE 1=1', []
    if q:
        query += ' AND (flight_number LIKE ? OR airline LIKE ? OR origin LIKE ? OR destination LIKE ?)'
        args += ['%' + q[:60] + '%'] * 4
    if status:
        query += ' AND status=?'
        args.append(status)
    with connect() as db:
        return rows(db.execute(query + ' ORDER BY id DESC LIMIT 1000', args))


@router.get('/flights/{flight_id}')
def flight_detail(flight_id: int, request: Request):
    require(request)
    with connect() as db:
        r = one(db.execute('SELECT * FROM flights WHERE id=?', (flight_id,)))
    if not r:
        raise HTTPException(404, 'Flight not found')
    return r


@router.post('/flights', status_code=201)
def create_flight(request: Request, body: dict = Body(...)):
    user = require(request, mutation=True)
    validate_flight(body)
    d = {k: body.get(k) for k in FLIGHT_FIELDS}
    if d['status'] == 'Emergency':
        d['priority'] = 'Critical'
    d['priority'] = d['priority'] or 'Normal'
    with connect() as db:
        try:
            c = db.execute(f"INSERT INTO flights ({','.join(FLIGHT_FIELDS)},source,created_at) VALUES ({','.join('?' * len(FLIGHT_FIELDS))},?,?)",
                           (*[d[k] for k in FLIGHT_FIELDS], 'controller_entered', utcnow()))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Duplicate flight number')
        audit(db, user['username'], 'flight.create', 'flights', c.lastrowid, {'flight_number': d['flight_number']})
        return one(db.execute('SELECT * FROM flights WHERE id=?', (c.lastrowid,)))


@router.put('/flights/{flight_id}')
def update_flight(flight_id: int, request: Request, body: dict = Body(...)):
    user = require(request, mutation=True)
    validate_flight(body, partial=True)
    with connect() as db:
        if not db.execute('SELECT 1 FROM flights WHERE id=?', (flight_id,)).fetchone():
            raise HTTPException(404, 'Flight not found')
        edit = {k: body[k] for k in FLIGHT_FIELDS if k in body}
        if edit.get('status') == 'Emergency':
            edit['priority'] = 'Critical'
        try:
            db.execute('UPDATE flights SET ' + ','.join(k + '=?' for k in edit) + ' WHERE id=?', (*edit.values(), flight_id))
        except sqlite3.IntegrityError:
            raise HTTPException(409, 'Duplicate flight number')
        audit(db, user['username'], 'flight.update', 'flights', flight_id, edit)
        return one(db.execute('SELECT * FROM flights WHERE id=?', (flight_id,)))


@router.post('/flights/{flight_id}/cancel')
def cancel_flight(flight_id: int, request: Request):
    user = require(request, mutation=True)
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM flights WHERE id=?', (flight_id,)).fetchone():
            raise HTTPException(404, 'Flight not found')
        db.execute("UPDATE flights SET status='Cancelled', runway=NULL WHERE id=?", (flight_id,))
        db.execute("UPDATE runway_slots SET status='Cancelled', cancelled_by=?, cancelled_at=? WHERE flight_id=? AND status='Booked'",
                   (user['username'], utcnow(), flight_id))
        db.execute("UPDATE runways SET status='Available', assigned_flight_id=NULL, occupied_until=NULL WHERE assigned_flight_id=?", (flight_id,))
        audit(db, user['username'], 'flight.cancel', 'flights', flight_id)
        db.commit()
    return {'status': 'Cancelled'}


@router.delete('/flights/{flight_id}')
def delete_flight(flight_id: int, request: Request):
    user = require(request, supervisor=True, mutation=True)
    with connect() as db:
        db.execute("UPDATE runways SET status='Available', assigned_flight_id=NULL, occupied_until=NULL WHERE assigned_flight_id=?", (flight_id,))
        if not db.execute('DELETE FROM flights WHERE id=?', (flight_id,)).rowcount:
            raise HTTPException(404, 'Flight not found')
        audit(db, user['username'], 'flight.delete', 'flights', flight_id)
    return {'message': 'Flight deleted'}


@router.get('/priority-queue')
def priority_queue(request: Request):
    require(request)
    with connect() as db:
        return rows(db.execute("""SELECT * FROM flights WHERE status NOT IN ('Cancelled','Landed')
            ORDER BY CASE WHEN status='Emergency' THEN 0 WHEN priority='Critical' THEN 1 WHEN fuel_pct<20 THEN 2
            WHEN priority='High' THEN 3 ELSE 4 END, COALESCE(fuel_pct,100), flight_time, id"""))


# ---------------------------------------------------------------- runways

@router.get('/runways')
def runways(request: Request):
    require(request)
    with connect() as db:
        return rows(db.execute('SELECT r.*, f.flight_number AS assigned_flight FROM runways r '
                               'LEFT JOIN flights f ON f.id=r.assigned_flight_id ORDER BY r.id'))


def _alert(db, flight_id, kind, severity, message, source='operations'):
    db.execute('INSERT INTO alerts (flight_id,type,severity,message,source,created_at) VALUES (?,?,?,?,?,?)',
               (flight_id, kind, severity, message, source, utcnow()))


@router.put('/runways/{runway_id}/allocate')
def allocate(runway_id: int, request: Request, body: dict = Body(...)):
    user = require(request, mutation=True)
    try:
        flight_id = int(body.get('flight_id'))
    except (TypeError, ValueError):
        raise HTTPException(400, 'Valid flight_id required')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        r = one(db.execute('SELECT * FROM runways WHERE id=?', (runway_id,)))
        f = one(db.execute('SELECT * FROM flights WHERE id=?', (flight_id,)))
        if not r or not f:
            raise HTTPException(404, 'Runway or flight not found')
        if f['status'] in ('Cancelled', 'Landed'):
            raise HTTPException(409, 'Flight is not active')
        if r['status'] != 'Available':
            _alert(db, flight_id, 'Runway conflict', 'Critical', f"Blocked allocation: {r['runway_code']} is {r['status']}")
            audit(db, user['username'], 'runway.blocked', 'runways', runway_id, {'flight_id': flight_id, 'status': r['status']})
            db.commit()
            raise HTTPException(409, 'Runway unavailable; allocation blocked and alert stored')
        start = datetime.now(timezone.utc)
        try:
            end = iso(body.get('occupied_until'))
        except HTTPException:
            end = start + timedelta(minutes=30)
        if end <= start:
            end = start + timedelta(minutes=30)
        for other in rows(db.execute("SELECT * FROM runway_slots WHERE runway_id=? AND status='Booked' AND flight_id!=?", (runway_id, flight_id))):
            if iso(other['start_at']) < end and start < iso(other['end_at']):
                _alert(db, flight_id, 'Runway reservation conflict', 'Critical', 'Current occupancy would overlap a calendar booking')
                audit(db, user['username'], 'runway.blocked-reservation', 'runways', runway_id, {'slot_id': other['id']})
                db.commit()
                raise HTTPException(409, 'Allocation overlaps a different flight reserved on this runway')
        if db.execute("SELECT 1 FROM runways WHERE assigned_flight_id=? AND status='Occupied'", (flight_id,)).fetchone():
            raise HTTPException(409, 'Flight already assigned to an occupied runway')
        db.execute("UPDATE runways SET status='Occupied', assigned_flight_id=?, occupied_until=? WHERE id=?",
                   (flight_id, end.isoformat(timespec='seconds'), runway_id))
        db.execute('UPDATE flights SET runway=? WHERE id=?', (r['runway_code'], flight_id))
        audit(db, user['username'], 'runway.allocate', 'runways', runway_id, {'flight_id': flight_id})
        db.commit()
    return {'message': 'Runway allocated', 'runway': r['runway_code']}


@router.put('/runways/{runway_id}/release')
def release(runway_id: int, request: Request):
    user = require(request, mutation=True)
    with connect() as db:
        r = one(db.execute('SELECT * FROM runways WHERE id=?', (runway_id,)))
        if not r:
            raise HTTPException(404, 'Runway not found')
        if r['status'] == 'Closed':
            raise HTTPException(409, 'Cannot release a closed runway; a supervisor must reopen it')
        db.execute("UPDATE runways SET status='Available', assigned_flight_id=NULL, occupied_until=NULL WHERE id=?", (runway_id,))
        audit(db, user['username'], 'runway.release', 'runways', runway_id)
    return {'message': 'Runway released'}


@router.put('/runways/{runway_id}/status')
def runway_status(runway_id: int, request: Request, body: dict = Body(...)):
    user = require(request, supervisor=True, mutation=True)
    status = body.get('status')
    if status not in ('Available', 'Closed'):
        raise HTTPException(400, 'Status must be Available or Closed')
    with connect() as db:
        r = one(db.execute('SELECT * FROM runways WHERE id=?', (runway_id,)))
        if not r:
            raise HTTPException(404, 'Runway not found')
        if r['status'] == 'Occupied':
            raise HTTPException(409, 'Release the occupied runway before closing or opening it')
        if status == 'Closed' and db.execute("SELECT 1 FROM runway_slots WHERE runway_id=? AND status='Booked' AND end_at>? LIMIT 1",
                                             (runway_id, utcnow())).fetchone():
            raise HTTPException(409, 'Cancel future bookings before closing')
        db.execute('UPDATE runways SET status=?, assigned_flight_id=NULL, occupied_until=NULL WHERE id=?', (status, runway_id))
        audit(db, user['username'], 'runway.status', 'runways', runway_id, {'status': status})
    return {'status': status}


# ---------------------------------------------------------------- runway calendar

@router.get('/schedule/bookings')
def bookings(request: Request, runway_id: int | None = None):
    require(request)
    query = ("SELECT s.*, f.flight_number, r.runway_code FROM runway_slots s JOIN flights f ON f.id=s.flight_id "
             "JOIN runways r ON r.id=s.runway_id WHERE s.status='Booked'")
    args = []
    if runway_id is not None:
        query += ' AND s.runway_id=?'
        args.append(runway_id)
    with connect() as db:
        return {'slots': rows(db.execute(query + ' ORDER BY s.start_at, s.runway_id LIMIT 1000', args)), 'rules': capacity_disclaimer()}


@router.post('/schedule/suggest')
def suggestions(request: Request, body: dict = Body(...)):
    require(request)
    p = parse_slot(body)
    with connect() as db:
        issues = check_slot(db, p)
        options = slot_suggest(db, p)
    return {'feasible': not issues, 'conflicts': issues, 'alternatives': options, 'rules': capacity_disclaimer()}


@router.post('/schedule/bookings', status_code=201)
def book(request: Request, body: dict = Body(...)):
    user = require(request, mutation=True)
    p = parse_slot(body)
    if body.get('confirm') is not True:
        raise HTTPException(400, 'Explicit confirm=true required for booking')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        issues = check_slot(db, p)
        if issues:
            _alert(db, p['flight_id'], 'Runway time-slot conflict', 'High', 'Blocked overlapping or unavailable runway request')
            audit(db, user['username'], 'schedule.blocked', 'runway_slots', '', {'conflicts': issues})
            alternatives = slot_suggest(db, p)
            db.commit()
            raise HTTPException(409, {'message': 'Requested slot conflicts with the calendar', 'conflicts': issues, 'alternatives': alternatives})
        c = db.execute('INSERT INTO runway_slots (flight_id,runway_id,operation,start_at,end_at,status,booked_by,created_at) VALUES (?,?,?,?,?,?,?,?)',
                       (p['flight_id'], p['runway_id'], p['operation'], iso_label(p['start_at']), iso_label(p['end_at']), 'Booked',
                        user['username'], utcnow()))
        audit(db, user['username'], 'schedule.book', 'runway_slots', c.lastrowid, {'runway_id': p['runway_id']})
        db.commit()
        return {'booking': one(db.execute('SELECT * FROM runway_slots WHERE id=?', (c.lastrowid,))), 'status': 'BOOKED'}


@router.delete('/schedule/bookings/{slot_id}')
def cancel_booking(slot_id: int, request: Request):
    user = require(request, mutation=True)
    with connect() as db:
        c = db.execute("UPDATE runway_slots SET status='Cancelled', cancelled_by=?, cancelled_at=? WHERE id=? AND status='Booked'",
                       (user['username'], utcnow(), slot_id))
        if not c.rowcount:
            raise HTTPException(404, 'Active booking not found')
        audit(db, user['username'], 'schedule.cancel', 'runway_slots', slot_id)
    return {'message': 'Booking cancelled'}


# ---------------------------------------------------------------- alerts and incident reports

@router.get('/alerts')
def alerts(request: Request, all: bool = False):
    require(request)
    where = '' if all else "WHERE a.status!='Resolved' "
    with connect() as db:
        return rows(db.execute('SELECT a.*, f.flight_number FROM alerts a LEFT JOIN flights f ON f.id=a.flight_id ' + where +
                               'ORDER BY a.id DESC LIMIT 500'))


@router.post('/alerts', status_code=201)
def create_alert(request: Request, body: dict = Body(...)):
    user = require(request, mutation=True)
    if body.get('severity') not in SEVERITIES or not body.get('type') or not body.get('message'):
        raise HTTPException(400, 'type, severity and message are required')
    if len(str(body['message'])) > 1000:
        raise HTTPException(400, 'Message too long')
    with connect() as db:
        try:
            c = db.execute('INSERT INTO alerts (flight_id,type,severity,message,source,created_at) VALUES (?,?,?,?,?,?)',
                           (body.get('flight_id'), str(body['type'])[:80], body['severity'], body['message'], 'controller', utcnow()))
        except sqlite3.IntegrityError:
            raise HTTPException(404, 'Flight not found')
        audit(db, user['username'], 'alert.create', 'alerts', c.lastrowid)
        return one(db.execute('SELECT * FROM alerts WHERE id=?', (c.lastrowid,)))


@router.put('/alerts/{alert_id}/{operation}')
def alert_operation(alert_id: int, operation: str, request: Request):
    user = require(request, mutation=True)
    status = {'acknowledge': 'Acknowledged', 'resolve': 'Resolved'}.get(operation)
    if not status:
        raise HTTPException(400, 'Invalid alert operation')
    with connect() as db:
        if not db.execute('UPDATE alerts SET status=?, updated_at=? WHERE id=?', (status, utcnow(), alert_id)).rowcount:
            raise HTTPException(404, 'Alert not found')
        audit(db, user['username'], 'alert.' + operation, 'alerts', alert_id)
    return {'message': 'Alert ' + status.lower()}


@router.get('/incident-reports')
def incident_reports(request: Request):
    require(request)
    with connect() as db:
        return rows(db.execute('SELECT i.*, f.flight_number FROM incident_reports i JOIN flights f ON f.id=i.flight_id ORDER BY i.id DESC LIMIT 300'))


@router.post('/incident-reports', status_code=201)
def submit_incident(request: Request, body: dict = Body(...)):
    user = require(request, mutation=True)
    category = str(body.get('category') or '').strip()[:80]
    details = str(body.get('details') or '').strip()[:800]
    source = str(body.get('source_kind') or '')
    if not category or not details or source not in ('controller_entered', 'crew_report_transcribed', 'synthetic_exercise', 'external_document_unverified'):
        raise HTTPException(400, 'category, details and a valid source_kind are required')
    try:
        flight_id = int(body['flight_id'])
    except (KeyError, TypeError, ValueError):
        raise HTTPException(400, 'Valid flight_id required')
    fuel = body.get('reported_fuel_pct')
    if fuel is not None:
        try:
            fuel = float(fuel)
        except (TypeError, ValueError):
            raise HTTPException(400, 'Invalid fuel percentage')
        if not 0 <= fuel <= 100:
            raise HTTPException(400, 'Fuel must be 0-100%')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM flights WHERE id=?', (flight_id,)).fetchone():
            raise HTTPException(404, 'Flight not found')
        c = db.execute('INSERT INTO incident_reports (flight_id,category,reported_fuel_pct,details,source_kind,reference,recorded_by,recorded_at) '
                       'VALUES (?,?,?,?,?,?,?,?)', (flight_id, category, fuel, details, source, str(body.get('reference') or '')[:200],
                                                    user['username'], utcnow()))
        if (fuel is not None and fuel < 20) or category.lower() in ('medical', 'engine failure', 'emergency', 'low fuel'):
            _alert(db, flight_id, 'Unverified incident report', 'High',
                   f'Reported {category}; source={source}; confirm with the crew (fuel is not part of ADS-B).')
        audit(db, user['username'], 'incident.report', 'incident_reports', c.lastrowid, {'category': category})
        db.commit()
        return one(db.execute('SELECT * FROM incident_reports WHERE id=?', (c.lastrowid,)))


# ---------------------------------------------------------------- dashboard

@router.get('/dashboard')
def dashboard(request: Request):
    require(request)
    with connect() as db:
        n = lambda table, where='1=1': db.execute(f'SELECT COUNT(*) FROM {table} WHERE {where}').fetchone()[0]
        return {
            'active_flights': n('flights', "status NOT IN ('Landed','Cancelled')"), 'delayed_flights': n('flights', "status='Delayed'"),
            'emergencies': n('flights', "status='Emergency'"), 'runways_in_use': n('runways', "status='Occupied'"),
            'runways_total': n('runways'), 'priority_alerts': n('alerts', "status!='Resolved' AND severity IN ('High','Critical')"),
            'open_alerts': n('alerts', "status!='Resolved'"), 'scenario_runs': n('lab_runs'),
            'pending_approvals': n('lab_runs', "json_extract(data,'$.approval') IN ('Pending','Rejected')"),
            'emergency_runs': n('emergency_runs'), 'readback_checks': n('comm_checks'),
            'failed_logins_24h': n('auth_attempts', f"successful=0 AND created_at>='{(datetime.now(timezone.utc) - timedelta(hours=24)).isoformat(timespec='seconds')}'"),
        }
