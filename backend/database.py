"""SQLite persistence. All timestamps are UTC ISO-8601. Isolate tests with SKYCONTROL_DB."""
from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from .config import DATA_DIR


def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def db_path():
    return Path(os.getenv('SKYCONTROL_DB', str(DATA_DIR / 'skycontrol.sqlite3')))


@contextmanager
def connect():
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path), timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA busy_timeout=10000')
    try:
        yield db
    finally:
        db.close()


def init_db():
    with connect() as db:
        db.execute('PRAGMA journal_mode=WAL')
        db.executescript((Path(__file__).parent / 'schema.sql').read_text())


def rows(cursor):
    return [dict(r) for r in cursor.fetchall()]


def one(cursor):
    r = cursor.fetchone()
    return dict(r) if r else None


def audit(db, actor, action, entity, entity_id='', details=None):
    db.execute('INSERT INTO audit_events (actor,action,entity,entity_id,details,created_at) VALUES (?,?,?,?,?,?)',
               (actor, action, entity, str(entity_id), json.dumps(details or {}, default=str), utcnow()))
