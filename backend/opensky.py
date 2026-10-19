"""OpenSky REST ingestion (live capture or imported JSON) with strict provenance and bounds.

No fallback ever fabricates data: a failed live request is logged and reported as a failure.
"""
import json
import os
import urllib.request
import urllib.error
from datetime import datetime, timezone
from .database import connect, audit, utcnow, one, rows

FIELDS=('icao24','callsign','origin_country','time_position','last_contact','longitude','latitude','baro_altitude','on_ground','velocity','true_track','vertical_rate','sensors','geo_altitude','squawk','spi','position_source','category')

def parse_vectors(raw):
    valid=[]
    for entry in raw.get('states',[]):
        if not isinstance(entry,list) or len(entry)<17:continue
        s=dict(zip(FIELDS,entry))
        try:
            lat=float(s['latitude']);lon=float(s['longitude'])
            if not (-90<=lat<=90 and -180<=lon<=180):continue
            icao=str(s['icao24'] or '').strip().lower()
            if not icao or len(icao)>12:continue
            speed=float(s['velocity'])*1.943844 if s['velocity'] is not None else None
            alt=float(s['baro_altitude'])*3.28084 if s['baro_altitude'] is not None else None
            rate=float(s['vertical_rate'])*196.8504 if s['vertical_rate'] is not None else None
            valid.append({'icao24':icao,'callsign':str(s['callsign'] or '').strip()[:24],
                          'origin_country':str(s['origin_country'] or '')[:64],
                          'longitude':lon,'latitude':lat,'altitude_ft':round(alt) if alt is not None else None,
                          'speed_kt':round(speed,1) if speed is not None else None,
                          'heading_deg':round(float(s['true_track']),1) if s['true_track'] is not None else None,
                          'vertical_rate_fpm':round(rate) if rate is not None else None,
                          'on_ground':int(bool(s['on_ground'])),'squawk':str(s['squawk'] or '')[:8],
                          'last_contact':int(s['last_contact']) if s['last_contact'] is not None else None})
        except (ValueError,TypeError,OverflowError):continue
    return valid

def save_payload(raw,actor,provider='OpenSky Network',dataset_type='imported',notes=''):
    if not isinstance(raw,dict) or not isinstance(raw.get('states'),list): raise ValueError('OpenSky object requires a states array')
    if len(raw['states'])>10000:raise ValueError('Snapshot exceeds 10,000 states')
    vectors=parse_vectors(raw)
    if not vectors:raise ValueError('No valid aircraft positions found')
    ts=raw.get('time')
    observed=datetime.fromtimestamp(int(ts),timezone.utc).isoformat(timespec='seconds') if isinstance(ts,(int,float)) and 0<int(ts)<4102444800 else utcnow()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        cur=db.execute('INSERT INTO snapshots (observed_at,recorded_at,provider,dataset_type,aircraft_count,notes) VALUES (?,?,?,?,?,?)',
                  (observed,utcnow(),provider,dataset_type,len(vectors),notes[:300]))
        sid=cur.lastrowid
        for v in vectors:
            db.execute('''INSERT OR IGNORE INTO state_vectors (snapshot_id,icao24,callsign,origin_country,longitude,latitude,altitude_ft,speed_kt,heading_deg,vertical_rate_fpm,on_ground,squawk,last_contact) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (sid,*(v[k] for k in ('icao24','callsign','origin_country','longitude','latitude','altitude_ft','speed_kt','heading_deg','vertical_rate_fpm','on_ground','squawk','last_contact'))))
        count=db.execute('SELECT COUNT(*) FROM state_vectors WHERE snapshot_id=?',(sid,)).fetchone()[0]
        db.execute('UPDATE snapshots SET aircraft_count=? WHERE id=?',(count,sid))
        audit(db,actor,'dataset.import','snapshots',sid,{'aircraft_count':count,'provider':provider,'dataset_type':dataset_type})
        db.commit()
    return {'snapshot_id':sid,'aircraft_count':count,'observed_at':observed,'source':provider,'dataset_type':dataset_type}

def fetch_live(bounds=None):
    """Explicit network fetch, no fallbacks to fake data. Optional OAuth2 client credentials."""
    bounds=bounds or {'lamin':49.5,'lamax':54.5,'lomin':-2.0,'lomax':3.0}
    for k,v in bounds.items():
        if not (-180<=float(v)<=180):raise ValueError('Invalid geographic bounds')
    if float(bounds['lamin'])>=float(bounds['lamax']) or float(bounds['lomin'])>=float(bounds['lomax']):raise ValueError('Invalid bounds ordering')
    from urllib.parse import urlencode
    auth_header={}
    client_id=os.environ.get('OPENSKY_CLIENT_ID');secret=os.environ.get('OPENSKY_CLIENT_SECRET')
    if client_id and secret:
        from urllib.parse import urlencode as encode
        req=urllib.request.Request('https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token',
                    data=encode({'grant_type':'client_credentials','client_id':client_id,'client_secret':secret}).encode(),
                    headers={'Content-Type':'application/x-www-form-urlencoded'},method='POST')
        with urllib.request.urlopen(req,timeout=15) as r: token=json.load(r)['access_token']
        auth_header={'Authorization':'Bearer '+token}
    url='https://opensky-network.org/api/states/all?'+urlencode(bounds)
    with urllib.request.urlopen(urllib.request.Request(url,headers=auth_header),timeout=22) as r:
        return json.load(r)

def get_snapshot(sid):
    with connect() as db:
        header=one(db.execute('SELECT * FROM snapshots WHERE id=?',(sid,)))
        if not header:return None
        header['aircraft']=rows(db.execute('SELECT * FROM state_vectors WHERE snapshot_id=? ORDER BY id LIMIT 1000',(sid,)))
    return header

# The 90-second threshold below is a research UI freshness parameter, not a radar service-level assurance.
def snapshot_freshness(header,aircraft=None,max_age_seconds=90,now=None):
    from datetime import datetime, timezone
    now=now or datetime.now(timezone.utc)
    ts=datetime.fromisoformat(header['observed_at'].replace('Z','+00:00'))
    age=(now-ts).total_seconds()
    data_type=header['dataset_type']
    count=len(aircraft or [])
    valid_time=0;stale_position=0;missing_contact=0;future_contact=0
    for a in aircraft or []:
        t=a.get('last_contact')
        if t is None:missing_contact+=1;continue
        delta=now.timestamp()-int(t)
        if delta < -30:future_contact+=1
        elif delta>max_age_seconds:stale_position+=1
        else:valid_time+=1
    fresh=(data_type=='live' and -30<=age<=max_age_seconds and stale_position==0 and future_contact==0 and missing_contact==0 and count>0)
    return {'dataset_type':data_type,'provider':header['provider'],'snapshot_observed_at':header['observed_at'],
            'snapshot_recorded_at':header['recorded_at'],'age_seconds':round(age,1),
            'freshness_threshold_seconds':max_age_seconds,'is_fresh_live':fresh,'stale':not fresh,
            'aircraft_count':count,'fresh_contacts':valid_time,'stale_contacts':stale_position,
            'missing_contacts':missing_contact,'future_contacts':future_contact,
            'freshness_note':'Live requires current observation AND individually recent contacts. Imported and historical never qualify as live. No operational surveillance guarantees.'}

def feed_health():
    with connect() as db:
        latest=one(db.execute('SELECT * FROM snapshots ORDER BY id DESC LIMIT 1'))
        latest_live=one(db.execute("SELECT * FROM snapshots WHERE dataset_type='live' ORDER BY id DESC LIMIT 1"))
        evt=one(db.execute('SELECT * FROM feed_events ORDER BY id DESC LIMIT 1'))
    details={'last_capture_event':evt,'latest_any':None,'latest_live':None,'status':'NO_VERIFIED_LIVE_CAPTURE'}
    for key,snap in [('latest_any',latest),('latest_live',latest_live)]:
        if snap:
            recorded=get_snapshot(snap['id'])
            details[key]={'snapshot_id':snap['id'],**snapshot_freshness(recorded,recorded['aircraft'])}
    if details['latest_live']:
        details['status']='FRESH_LIVE_CAPTURE' if details['latest_live']['is_fresh_live'] else 'STALE_LIVE_CAPTURE'
    if evt and not evt['success'] and (not latest_live or evt['id']>0):
        # Distinguish most recent failed fetch from last successfully recorded observation.
        details['last_attempt_failed']=True
    return details
