"""Classroom runway-calendar scheduler, NOT a certified runway capacity/separation system.

Intervals are UTC half-open [start,end). A configurable conservative *lab* buffer
covers same-runway setup / occupancy differences; it is NOT wake-turbulence or ATC minima.
All write operations must hold SQLite BEGIN IMMEDIATE before calling conflict checks.
"""
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException
from .database import rows, one

# Classroom-only parameters; no aircraft categories, NOT a real separation standard.
MIN_SECONDS={'arrival':180,'departure':120}
LAB_BUFFER_SECONDS=90
# Simplified sequence-dependent lab buffer (seconds), not runway separation minima.
SEQUENCE_BUFFER_SECONDS={('arrival','arrival'):120,('arrival','departure'):150,('departure','arrival'):180,('departure','departure'):90}
MAX_WINDOW_SECONDS=120*60

def iso(ts):
    if not isinstance(ts,str):raise HTTPException(400,'start_at and end_at require UTC ISO timestamps with timezone')
    try:d=datetime.fromisoformat(ts.replace('Z','+00:00'))
    except ValueError:raise HTTPException(400,'Invalid ISO timestamp')
    if d.tzinfo is None or d.utcoffset() is None:raise HTTPException(400,'Timezone offset required; use UTC +00:00')
    return d.astimezone(timezone.utc)

def parsed(body):
    try:flight_id=int(body['flight_id']);runway_id=int(body['runway_id'])
    except (KeyError,ValueError,TypeError):raise HTTPException(400,'flight_id and runway_id must be integers')
    op=body.get('operation')
    if op not in MIN_SECONDS:raise HTTPException(400,'operation must be arrival or departure')
    start=iso(body.get('start_at'));end=iso(body.get('end_at'))
    if end<=start or (end-start).total_seconds()<MIN_SECONDS[op] or (end-start).total_seconds()>MAX_WINDOW_SECONDS:
        raise HTTPException(400,f'{op} requires {MIN_SECONDS[op]}..{MAX_WINDOW_SECONDS} seconds, end > start')
    return {'flight_id':flight_id,'runway_id':runway_id,'operation':op,'start_at':start,'end_at':end}

def label(d):return d.isoformat(timespec='seconds')

def check(db,p,ignore_id=None):
    runway=one(db.execute('SELECT * FROM runways WHERE id=?',(p['runway_id'],)))
    if not runway:raise HTTPException(404,'Runway not found')
    if not db.execute('SELECT 1 FROM flights WHERE id=?',(p['flight_id'],)).fetchone():raise HTTPException(404,'Flight not found')
    flight=db.execute('SELECT status FROM flights WHERE id=?',(p['flight_id'],)).fetchone()
    if flight['status'] in ('Cancelled','Landed'):raise HTTPException(409,'Flight is not active')
    start,end=p['start_at'],p['end_at']
    issues=[]
    if runway['status']=='Closed':issues.append({'type':'closed_runway','message':'Runway closed'})
    if runway['status']=='Occupied':
        try:occupied_until=iso(runway['occupied_until'])
        except HTTPException:occupied_until=None
        if occupied_until is None or start < occupied_until+timedelta(seconds=LAB_BUFFER_SECONDS):
            issues.append({'type':'current_occupation','message':'Runway currently occupied; no verified release time or insufficient buffer'})
    # Indexed time-filtering is possible later; bounded lab calendar fits SQLite.
    slots=rows(db.execute('SELECT * FROM runway_slots WHERE status="Booked"'+(' AND id!=?' if ignore_id else ''),((ignore_id,) if ignore_id else ())))
    for s in slots:
        a,b=iso(s['start_at']),iso(s['end_at'])
        if s['flight_id']==p['flight_id'] and start<b and a<end:
            issues.append({'type':'flight_double_booked','slot_id':s['id'],'message':'Flight already occupies an overlapping calendar slot'})
        if s['runway_id']==p['runway_id']:
            following_gap=timedelta(seconds=SEQUENCE_BUFFER_SECONDS[(s['operation'],p['operation'])])
            preceding_gap=timedelta(seconds=SEQUENCE_BUFFER_SECONDS[(p['operation'],s['operation'])])
            if start<b+following_gap and a-preceding_gap<end:
                issues.append({'type':'runway_overlap','slot_id':s['id'],'flight_id':s['flight_id'],
                               'message':'Runway interval or lab separation buffer overlaps an existing booking'})
    return issues

def suggest(db,p,max_suggestions=5,step_minutes=5,horizon_minutes=240):
    options=[]; start=p['start_at'];duration=p['end_at']-start
    runways=rows(db.execute('SELECT id,runway_code,status FROM runways ORDER BY id'))
    # Same-time alternative runway first, then earliest feasible later slots.
    for delta in range(0,horizon_minutes+1,step_minutes):
        for r in sorted(runways,key=lambda r:(r['id']!=p['runway_id'],r['id'])):
            cand={**p,'runway_id':r['id'],'start_at':start+timedelta(minutes=delta),'end_at':start+timedelta(minutes=delta)+duration}
            if not check(db,cand):
                options.append({'runway_id':r['id'],'runway_code':r['runway_code'],
                               'start_at':label(cand['start_at']),'end_at':label(cand['end_at']),
                               'operation':p['operation'],'delay_minutes':delta,
                               'requires_controller_confirmation':True,'status':'PROPOSAL_ONLY'})
                if len(options)>=max_suggestions:return options
    return options

def capacity_disclaimer():
    return 'Educational half-open intervals, minimum modeled occupancy, sequence-dependent 90–180s buffers; excludes wake separation, aircraft class, weather, taxi routing, LVP, NOTAMs, and local procedures. No runway clearance is issued.'
