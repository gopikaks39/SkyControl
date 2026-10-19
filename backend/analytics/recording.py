"""Loader for the recorded OpenSky dataset (skycontrol.opensky.recording.v1).

The file is a real 90-minute recording of the London-Amsterdam area. We keep
every source row except exact duplicates (same aircraft, same timestamp), and
convert it to column arrays so the analyses can be vectorised with NumPy.
"""
from __future__ import annotations

import gzip
import hashlib
import json
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from ..config import RECORDING_FILE, REFERENCE_FILE
from ..core.geo import LONDON


@dataclass
class Recording:
    meta: dict
    sha256: str
    t: np.ndarray            # unix seconds per observation
    ac: np.ndarray           # aircraft index per observation
    lat: np.ndarray
    lon: np.ndarray
    alt: np.ndarray          # feet, NaN when missing
    ground: np.ndarray       # bool
    speed: np.ndarray        # knots (derived), NaN when missing
    heading: np.ndarray      # degrees (derived), NaN when missing
    vrate: np.ndarray        # ft/min (derived), NaN when missing
    x: np.ndarray            # NM east of projection origin
    y: np.ndarray            # NM north of projection origin
    icao: list               # per aircraft index
    callsign: list           # per aircraft index; most frequent non-empty callsign or ''
    obs_callsign: list       # per observation, as recorded
    frames: np.ndarray       # sorted unique timestamps
    tracks: dict = field(default_factory=dict)        # ac index -> observation indices (time sorted)
    frame_index: dict = field(default_factory=dict)   # timestamp -> observation indices
    duplicates_removed: int = 0

    @property
    def n_aircraft(self):
        return len(self.icao)

    @property
    def airborne(self):
        return (~self.ground) & ~np.isnan(self.alt)

    def frame_at(self, ts):
        """Observation indices for the frame closest to (and not after) ts."""
        i = int(np.searchsorted(self.frames, ts, side='right')) - 1
        i = max(0, min(i, len(self.frames) - 1))
        return self.frames[i], self.frame_index[int(self.frames[i])]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, 'rb') as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_raw(path: Path = RECORDING_FILE) -> dict:
    opener = gzip.open if str(path).endswith('.gz') else open
    with opener(path, 'rt', encoding='utf-8') as fp:
        raw = json.load(fp)
    if raw.get('format') != 'skycontrol.opensky.recording.v1' or not isinstance(raw.get('observations'), list):
        raise ValueError('Unsupported recording format')
    return raw


def build(raw: dict, sha: str = '') -> Recording:
    rows = {}
    for o in raw['observations']:
        if o.get('latitude') is None or o.get('longitude') is None or not o.get('icao24'):
            continue
        rows[(int(o['timestamp_unix_utc']), o['icao24'])] = o
    duplicates = len(raw['observations']) - len(rows)
    ordered = sorted(rows.values(), key=lambda o: (o['timestamp_unix_utc'], o['icao24']))

    icao_ids, names = {}, []
    for o in ordered:
        if o['icao24'] not in icao_ids:
            icao_ids[o['icao24']] = len(names)
            names.append(o['icao24'])

    def col(key, dtype=float):
        return np.array([np.nan if o.get(key) is None else o[key] for o in ordered], dtype=dtype)

    t = np.array([o['timestamp_unix_utc'] for o in ordered], dtype=np.int64)
    ac = np.array([icao_ids[o['icao24']] for o in ordered], dtype=np.int32)
    lat, lon = col('latitude'), col('longitude')
    x, y = LONDON.to_xy(lat, lon)
    obs_callsign = [(o.get('callsign') or '').strip() for o in ordered]

    votes = [Counter() for _ in names]
    for a, cs in zip(ac, obs_callsign):
        if cs:
            votes[a][cs] += 1
    callsigns = [v.most_common(1)[0][0] if v else '' for v in votes]

    rec = Recording(
        meta=raw.get('metadata', {}), sha256=sha, t=t, ac=ac, lat=lat, lon=lon,
        alt=col('altitude_ft'), ground=np.array([bool(o.get('on_ground')) for o in ordered]),
        speed=col('derived_speed_kt'), heading=col('derived_heading_deg'), vrate=col('derived_vertical_rate_fpm'),
        x=np.asarray(x), y=np.asarray(y), icao=names, callsign=callsigns, obs_callsign=obs_callsign,
        frames=np.unique(t), duplicates_removed=duplicates,
    )
    order = np.lexsort((t, ac))
    split = np.flatnonzero(np.diff(ac[order])) + 1
    for chunk in np.split(order, split):
        rec.tracks[int(ac[chunk[0]])] = chunk
    frame_split = np.flatnonzero(np.diff(t)) + 1
    for chunk in np.split(np.arange(len(t)), frame_split):
        rec.frame_index[int(t[chunk[0]])] = chunk
    return rec


@lru_cache(maxsize=1)
def load(path: str = str(RECORDING_FILE)) -> Recording:
    p = Path(path)
    return build(read_raw(p), file_sha256(p))


@lru_cache(maxsize=1)
def reference() -> dict:
    with open(REFERENCE_FILE, encoding='utf-8') as fp:
        return json.load(fp)


def label(rec: Recording, a: int) -> str:
    return rec.callsign[a] or rec.icao[a].upper()


def velocities(rec: Recording, max_gap: float = 60.0):
    """Backward-difference velocity for every observation.

    Returns (vx, vy, vz, prev) where vx/vy are NM per second, vz is ft per second
    and prev is the index of the previous observation of the same aircraft
    (-1 when none within max_gap seconds). Values are NaN without a usable
    predecessor.
    """
    if getattr(rec, '_vel', None) is not None:
        return rec._vel
    n = len(rec.t)
    vx, vy, vz = (np.full(n, np.nan) for _ in range(3))
    prev = np.full(n, -1, dtype=np.int64)
    for idx in rec.tracks.values():
        if len(idx) < 2:
            continue
        a, b = idx[:-1], idx[1:]
        dt = (rec.t[b] - rec.t[a]).astype(float)
        ok = (dt > 0) & (dt <= max_gap)
        a, b, dt = a[ok], b[ok], dt[ok]
        prev[b] = a
        vx[b] = (rec.x[b] - rec.x[a]) / dt
        vy[b] = (rec.y[b] - rec.y[a]) / dt
        vz[b] = (rec.alt[b] - rec.alt[a]) / dt
    rec._vel = (vx, vy, vz, prev)
    return rec._vel
