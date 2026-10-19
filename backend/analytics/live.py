"""Per-moment views of the real recording for the 3D airspace replay.

For a chosen time the replay shows what SkyControl's monitors would display
at that moment: intent-aware predicted conflicts, duplicate targets, similar
callsigns sharing airspace, aircraft holding, and tracks being coasted.
"""
from __future__ import annotations

from functools import lru_cache

import numpy as np

from ..core.comms import callsign_similarity
from ..core.geo import LONDON
from . import conflicts, pipeline, prediction
from .recording import label, load, reference, velocities


@lru_cache(maxsize=1)
def _context():
    rec = load()
    X, usable, _, _ = prediction.state_features(rec)
    model = pipeline.predictor()
    learned = {'mid': 0, 'first_half_model': model, 'second_half_model': model, 'X': X, 'usable': usable}
    analysis = pipeline.get()
    dup_icao = set(analysis['duplicates'])
    duplicates = {i for i, code in enumerate(rec.icao) if code in dup_icao}
    return rec, learned, conflicts.cleared_levels(rec), duplicates, analysis['holding']['holds']


def meta():
    rec, *_ = _context()
    ref = reference()
    return {
        'start': int(rec.frames[0]), 'end': int(rec.frames[-1]), 'frames': [int(t - rec.frames[0]) for t in rec.frames],
        'aircraft': rec.n_aircraft, 'observations': int(len(rec.t)), 'origin': {'lat': LONDON.lat0, 'lon': LONDON.lon0},
        'airports': ref['airports'], 'holding_fixes': ref['holding_fixes'], 'bounding_box': rec.meta.get('bounding_box'),
        'dataset': rec.meta.get('dataset_name'), 'start_utc': rec.meta.get('start_utc'), 'end_utc': rec.meta.get('end_utc'),
    }


@lru_cache(maxsize=1)
def tracks():
    """Compact per-aircraft tracks: [seconds from start, lat, lon, altitude ft (or -1 on ground)]."""
    rec, _, _, duplicates, _ = _context()
    t0 = int(rec.frames[0])
    out = []
    for a, idx in rec.tracks.items():
        pts = []
        for i in idx:
            alt = -1 if rec.ground[i] or np.isnan(rec.alt[i]) else int(rec.alt[i])
            pts.append([int(rec.t[i] - t0), round(float(rec.lat[i]), 4), round(float(rec.lon[i]), 4), alt])
        out.append({'id': rec.icao[a], 'cs': rec.callsign[a], 'dup': a in duplicates, 'p': pts})
    return {'start': t0, 'tracks': out}


def frame(ts):
    """Monitor outputs at the frame nearest to unix time ts (cached per recorded frame)."""
    rec = _context()[0]
    return _frame(int(rec.frame_at(ts)[0]))


@lru_cache(maxsize=512)
def _frame(ts):
    rec, learned, levels, duplicates, holds = _context()
    idx = rec.frame_index[ts]
    vx, vy, vz, _ = velocities(rec)
    cfg = conflicts.METHODS['intent_probe']
    eligible = idx[rec.airborne[idx] & (rec.alt[idx] >= 3000) & ~np.isnan(vx[idx]) & ~np.isin(rec.ac[idx], list(duplicates))]
    predicted = []
    if len(eligible) > 1:
        px, py, pz = conflicts._predicted_paths(rec, eligible, ts, cfg, levels, learned)
        i, j = np.triu_indices(len(eligible), 1)
        near = np.hypot(rec.x[eligible[i]] - rec.x[eligible[j]], rec.y[eligible[i]] - rec.y[eligible[j]]) < 80
        i, j = i[near], j[near]
        thr = conflicts.horizontal_threshold(rec.alt[eligible[i]], rec.alt[eligible[j]])[:, None]
        inside = (np.hypot(px[i] - px[j], py[i] - py[j]) < thr) & (np.abs(pz[i] - pz[j]) < conflicts.V_THRESHOLD)
        for k in np.flatnonzero(inside.any(axis=1)):
            first = int(np.argmax(inside[k])) * conflicts.SAMPLE_S
            a, b = eligible[i[k]], eligible[j[k]]
            predicted.append({'a': label(rec, rec.ac[a]), 'b': label(rec, rec.ac[b]), 'a_id': rec.icao[rec.ac[a]],
                              'b_id': rec.icao[rec.ac[b]], 'in_seconds': first,
                              'now_nm': round(float(np.hypot(rec.x[a] - rec.x[b], rec.y[a] - rec.y[b])), 1),
                              'now_ft': int(abs(rec.alt[a] - rec.alt[b]))})
    predicted.sort(key=lambda r: r['in_seconds'])

    airborne = idx[rec.airborne[idx]]
    similar = []
    names = [(rec.obs_callsign[i], i) for i in airborne if len(rec.obs_callsign[i]) > 3]
    for p in range(len(names)):
        for q in range(p + 1, len(names)):
            (ca, ia), (cb, ib) = names[p], names[q]
            if ca[:3] != cb[:3]:
                continue
            score, reason = callsign_similarity(ca, cb)
            d = float(np.hypot(rec.x[ia] - rec.x[ib], rec.y[ia] - rec.y[ib]))
            if score >= 0.7 and d < 40 and abs(rec.alt[ia] - rec.alt[ib]) < 10000:
                similar.append({'a': ca, 'b': cb, 'reason': reason, 'distance_nm': round(d, 1)})

    holding = [{'callsign': h['callsign'], 'stack': h['stack'], 'minutes_so_far': round((ts - h['start']) / 60, 1)}
               for h in holds if h['start'] <= ts <= h['end']]
    present = set(int(rec.ac[i]) for i in idx)
    coasting = []
    for a, track in rec.tracks.items():
        if a in present:
            continue
        before = track[rec.t[track] < ts]
        after = track[rec.t[track] > ts]
        if len(before) and len(after) and not rec.ground[before[-1]] and 60 < ts - rec.t[before[-1]] < 600:
            coasting.append({'callsign': label(rec, a), 'id': rec.icao[a], 'stale_s': int(ts - rec.t[before[-1]])})
    ghosts = [rec.icao[int(rec.ac[i])] for i in idx if int(rec.ac[i]) in duplicates]
    return {
        'time': ts, 'offset': ts - int(rec.frames[0]), 'aircraft': int(len(idx)), 'airborne': int(len(airborne)),
        'predicted_conflicts': predicted[:25], 'similar_callsigns': similar, 'holding': holding,
        'coasting': coasting[:25], 'duplicates': ghosts,
        'probe': 'Intent-aware 5-minute probe with the learned trajectory predictor; duplicates merged.',
    }


def predictions(ts, horizon=300):
    """Straight-line and learned predicted positions for every airborne aircraft (cached per frame)."""
    rec = _context()[0]
    return _predictions(int(rec.frame_at(ts)[0]), horizon)


@lru_cache(maxsize=256)
def _predictions(ts, horizon):
    rec, learned, _, duplicates, _ = _context()
    idx = rec.frame_index[ts]
    vx, vy, _, _ = velocities(rec)
    idx = idx[rec.airborne[idx] & ~np.isnan(vx[idx]) & learned['usable'][idx]]
    if not len(idx):
        return {'time': int(ts), 'horizon_s': horizon, 'aircraft': []}
    lx, ly = rec.x[idx] + vx[idx] * horizon, rec.y[idx] + vy[idx] * horizon
    mx, my = learned['first_half_model'].predict(rec, idx, learned['X'], vx, vy, horizon)
    out = []
    for k, i in enumerate(idx):
        sl = LONDON.to_latlon(lx[k], ly[k])
        ml = LONDON.to_latlon(mx[k], my[k])
        out.append({'id': rec.icao[int(rec.ac[i])], 'callsign': label(rec, int(rec.ac[i])),
                    'line': [round(sl[0], 4), round(sl[1], 4)], 'learned': [round(ml[0], 4), round(ml[1], 4)]})
    return {'time': int(ts), 'horizon_s': horizon, 'aircraft': out}
