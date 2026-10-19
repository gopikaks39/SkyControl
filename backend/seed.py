"""First-run data: accounts (from setup or environment), runways, a synthetic schedule and the dataset register.

No password is embedded in the code. Accounts come from setup_accounts.py
(interactive) or, for Docker/CI, from SKYCONTROL_CONTROLLER_PASSWORD and
SKYCONTROL_SUPERVISOR_PASSWORD.
"""
from __future__ import annotations

import json
import os

from .auth import create_user
from .config import INDIA_SNAPSHOT_FILE, RECORDING_FILE, REFERENCE_FILE, DATA_DIR
from .database import connect, init_db, utcnow

# Synthetic classroom schedule using callsigns seen in the recording. Positions are illustrative.
SEED_FLIGHTS = [
    ('BAW425', 'British Airways', 'LMML', 'EGLL', '15:55', None, 'Approach', 'Normal', 34, 51.31, -0.45, 11000, 60, 220),
    ('BAW725', 'British Airways', 'LSZH', 'EGLL', '16:02', None, 'In Air', 'Normal', 41, 51.36, 0.21, 12000, 285, 240),
    ('EZY12AB', 'easyJet', 'EGKK', 'LFPG', '16:05', 'EGKK 26L', 'Scheduled', 'Normal', 88, 51.148, -0.19, 0, 260, 0),
    ('RYR52ZT', 'Ryanair', 'EIDW', 'EGSS', '16:10', None, 'Emergency', 'Critical', 9, 52.1, -0.6, 9000, 120, 250),
    ('KLM88U', 'KLM', 'EHAM', 'EGLL', '16:15', None, 'In Air', 'Normal', 52, 51.9, 1.9, 24000, 250, 410),
    ('DLH4PK', 'Lufthansa', 'EDDF', 'EGLL', '16:20', None, 'Delayed', 'High', 47, 51.2, 1.4, 16000, 290, 300),
    ('SHT13H', 'British Airways Shuttle', 'EGPH', 'EGLL', '16:25', None, 'In Air', 'Normal', 58, 52.6, -1.1, 18000, 160, 330),
    ('EIN38Y', 'Aer Lingus', 'EIDW', 'EGLL', '16:35', None, 'Scheduled', 'Normal', 70, 52.9, -1.9, 30000, 120, 440),
]

RUNWAYS = [('EGLL 27L', 'EGLL', 0), ('EGLL 27R', 'EGLL', 1), ('EGKK 26L', 'EGKK', 0), ('EGSS 22', 'EGSS', 0), ('EGGW 25', 'EGGW', 0)]


def _env_accounts(db):
    controller = os.environ.get('SKYCONTROL_CONTROLLER_PASSWORD') or os.environ.get('SKYCONTROL_DEMO_PASSWORD')
    supervisor = os.environ.get('SKYCONTROL_SUPERVISOR_PASSWORD')
    if controller and supervisor:
        create_user(db, 'controller', controller, 'controller', 'Duty controller', 'environment')
        create_user(db, 'supervisor', supervisor, 'supervisor', 'Watch supervisor', 'environment')
        return True
    return False


def register_datasets(db):
    from .analytics.recording import file_sha256
    meta = {}
    if RECORDING_FILE.exists():
        from .analytics.recording import read_raw
        meta = read_raw(RECORDING_FILE).get('metadata', {})
    entries = [
        ('London-Amsterdam OpenSky recording', 'trajectory recording', meta.get('source_provider', 'OpenSky Network'),
         f"{meta.get('start_utc', '')} to {meta.get('end_utc', '')}", meta.get('observation_count'),
         file_sha256(RECORDING_FILE) if RECORDING_FILE.exists() else None, 1,
         'Real recorded ADS-B/Mode S positions (90 min, 906 aircraft). Primary dataset for analysis, replay and model training.'),
        ('India OpenSky snapshot', 'state-vector snapshot', 'OpenSky Network REST /states/all', '2026-10-17 05:48:36 UTC', 284,
         file_sha256(INDIA_SNAPSHOT_FILE) if INDIA_SNAPSHOT_FILE.exists() else None, 1,
         'Single real snapshot over India from the previous project version; used for the airspace monitor history.'),
        ('US airport traffic, February 2011', 'aggregate counts', 'Plotly public datasets', 'February 2011', 40,
         file_sha256(DATA_DIR / 'historical_airport_traffic_2011_feb.csv'), 1,
         'Historical airport-level counts; reference only, not used for training.'),
        ('London reference data', 'airports and holding fixes', 'Public aeronautical information (approximate)', 'static', None,
         file_sha256(REFERENCE_FILE), 1, 'Approximate airport and stack positions for teaching; verify against the AIP.'),
        ('Scenario Lab exercises', 'constructed scenarios', 'SkyControl', 'generated', 21, None, 0,
         'Constructed trajectories with real callsigns; not reconstructions of real incidents.'),
    ]
    for e in entries:
        db.execute('INSERT OR IGNORE INTO datasets (name,kind,provider,period,records,sha256,is_real,notes,registered_at) '
                   'VALUES (?,?,?,?,?,?,?,?,?)', (*e, utcnow()))


def seed():
    init_db()
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if not db.execute('SELECT 1 FROM users LIMIT 1').fetchone() and not _env_accounts(db):
            db.rollback()
            raise RuntimeError('No accounts yet. Run "python setup_accounts.py" or set SKYCONTROL_CONTROLLER_PASSWORD '
                               'and SKYCONTROL_SUPERVISOR_PASSWORD.')
        for code, airport, priority in RUNWAYS:
            db.execute('INSERT OR IGNORE INTO runways (runway_code,airport,status,emergency_priority) VALUES (?,?,?,?)',
                       (code, airport, 'Available', priority))
        for f in SEED_FLIGHTS:
            db.execute('INSERT OR IGNORE INTO flights (flight_number,airline,origin,destination,flight_time,runway,status,'
                       'priority,fuel_pct,latitude,longitude,altitude_ft,heading_deg,speed_kt,source,created_at) '
                       'VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (*f, 'synthetic', utcnow()))
        if not db.execute('SELECT 1 FROM alerts LIMIT 1').fetchone():
            row = db.execute('SELECT id FROM flights WHERE flight_number=?', ('RYR52ZT',)).fetchone()
            if row:
                db.execute('INSERT INTO alerts (flight_id,type,severity,message,source,created_at) VALUES (?,?,?,?,?,?)',
                           (row['id'], 'Low fuel exercise', 'Critical',
                            'Synthetic fuel 9%: confirm with the crew (fuel is not part of ADS-B).', 'seed', utcnow()))
        register_datasets(db)
        db.commit()

    from .opensky import save_payload
    with connect() as db:
        has_snapshot = db.execute('SELECT 1 FROM snapshots LIMIT 1').fetchone()
    if INDIA_SNAPSHOT_FILE.exists() and not has_snapshot:
        save_payload(json.loads(INDIA_SNAPSHOT_FILE.read_text()), 'bundled_capture', 'OpenSky Network recorded response',
                     'imported', 'Bundled India capture; see opensky_india_provenance.json')
