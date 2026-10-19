PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL UNIQUE,
    full_name TEXT NOT NULL DEFAULT '',
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL CHECK(role IN ('controller','supervisor')),
    active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT 'setup'
);

CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_hash TEXT NOT NULL UNIQUE,
    csrf TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

-- Every login attempt, successful or not. Passwords are never stored here.
CREATE TABLE IF NOT EXISTS auth_attempts (
    id INTEGER PRIMARY KEY,
    username TEXT NOT NULL,
    ip TEXT,
    user_agent TEXT,
    successful INTEGER NOT NULL,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_attempt_user ON auth_attempts(username, created_at);
CREATE INDEX IF NOT EXISTS ix_attempt_ip ON auth_attempts(ip, created_at);

CREATE TABLE IF NOT EXISTS flights (
    id INTEGER PRIMARY KEY,
    flight_number TEXT UNIQUE NOT NULL,
    airline TEXT NOT NULL,
    origin TEXT NOT NULL,
    destination TEXT NOT NULL,
    flight_time TEXT NOT NULL,
    runway TEXT,
    status TEXT NOT NULL CHECK(status IN ('Scheduled','In Air','Approach','Delayed','Emergency','Landed','Cancelled')),
    priority TEXT NOT NULL CHECK(priority IN ('Normal','High','Critical')),
    fuel_pct REAL,
    latitude REAL, longitude REAL, altitude_ft REAL, heading_deg REAL, speed_kt REAL,
    source TEXT NOT NULL DEFAULT 'synthetic',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runways (
    id INTEGER PRIMARY KEY,
    runway_code TEXT UNIQUE NOT NULL,
    airport TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'Available' CHECK(status IN ('Available','Occupied','Closed')),
    occupied_until TEXT,
    assigned_flight_id INTEGER REFERENCES flights(id) ON DELETE SET NULL,
    emergency_priority INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS runway_slots (
    id INTEGER PRIMARY KEY,
    flight_id INTEGER NOT NULL REFERENCES flights(id) ON DELETE CASCADE,
    runway_id INTEGER NOT NULL REFERENCES runways(id),
    operation TEXT NOT NULL CHECK(operation IN ('arrival','departure')),
    start_at TEXT NOT NULL,
    end_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Booked' CHECK(status IN ('Booked','Cancelled')),
    booked_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    cancelled_at TEXT,
    cancelled_by TEXT
);
CREATE INDEX IF NOT EXISTS ix_slot_runway_start ON runway_slots(runway_id, start_at, status);
CREATE INDEX IF NOT EXISTS ix_slot_flight ON runway_slots(flight_id, status);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    flight_id INTEGER REFERENCES flights(id) ON DELETE SET NULL,
    type TEXT NOT NULL,
    severity TEXT NOT NULL CHECK(severity IN ('Low','Medium','High','Critical')),
    message TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'operations',
    status TEXT NOT NULL DEFAULT 'Open' CHECK(status IN ('Open','Acknowledged','Resolved')),
    created_at TEXT NOT NULL,
    updated_at TEXT
);

CREATE TABLE IF NOT EXISTS incident_reports (
    id INTEGER PRIMARY KEY,
    flight_id INTEGER NOT NULL REFERENCES flights(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    reported_fuel_pct REAL,
    details TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('controller_entered','crew_report_transcribed','synthetic_exercise','external_document_unverified')),
    reference TEXT,
    verification_status TEXT NOT NULL DEFAULT 'unverified',
    verified_by TEXT,
    recorded_by TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    verified_at TEXT
);

-- Dataset register: every dataset the app uses, with provenance and checksum.
CREATE TABLE IF NOT EXISTS datasets (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE,
    kind TEXT NOT NULL,
    provider TEXT NOT NULL,
    period TEXT,
    records INTEGER,
    sha256 TEXT,
    is_real INTEGER NOT NULL,
    notes TEXT,
    registered_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    observed_at TEXT NOT NULL,
    recorded_at TEXT NOT NULL,
    provider TEXT NOT NULL,
    dataset_type TEXT NOT NULL CHECK(dataset_type IN ('live','imported','synthetic')),
    aircraft_count INTEGER NOT NULL,
    notes TEXT
);

CREATE TABLE IF NOT EXISTS state_vectors (
    id INTEGER PRIMARY KEY,
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    icao24 TEXT NOT NULL, callsign TEXT, origin_country TEXT,
    longitude REAL NOT NULL, latitude REAL NOT NULL,
    altitude_ft REAL, speed_kt REAL, heading_deg REAL, vertical_rate_fpm REAL,
    on_ground INTEGER DEFAULT 0, squawk TEXT, last_contact INTEGER,
    UNIQUE(snapshot_id, icao24)
);
CREATE INDEX IF NOT EXISTS ix_state_snapshot ON state_vectors(snapshot_id);

CREATE TABLE IF NOT EXISTS feed_events (
    id INTEGER PRIMARY KEY,
    event_type TEXT NOT NULL,
    success INTEGER NOT NULL,
    detail TEXT,
    recorded_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS lab_runs (
    id INTEGER PRIMARY KEY,
    scenario TEXT NOT NULL DEFAULT '',
    data TEXT NOT NULL,
    created_by TEXT NOT NULL DEFAULT '',
    updated REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS emergency_runs (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    icao24 TEXT NOT NULL,
    callsign TEXT,
    recording_time INTEGER NOT NULL,
    result_json TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'Proposed' CHECK(status IN ('Proposed','Approved','Rejected')),
    created_by TEXT NOT NULL,
    created_at TEXT NOT NULL,
    reviewed_by TEXT,
    reviewed_at TEXT
);

-- Readback checks performed in the Communication assistant.
CREATE TABLE IF NOT EXISTS comm_checks (
    id INTEGER PRIMARY KEY,
    callsign TEXT NOT NULL,
    clearance_json TEXT NOT NULL,
    phraseology TEXT NOT NULL,
    readback TEXT NOT NULL,
    verdict TEXT NOT NULL,
    result_json TEXT NOT NULL,
    checked_by TEXT NOT NULL,
    checked_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS audit_events (
    id INTEGER PRIMARY KEY,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    entity TEXT NOT NULL,
    entity_id TEXT,
    details TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_audit_created ON audit_events(created_at);
