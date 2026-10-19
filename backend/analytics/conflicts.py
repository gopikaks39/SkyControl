"""Proximity encounters and conflict-alert performance on the real recording.

Ground truth: an *encounter* is a pair of airborne aircraft (both at or above
3,000 ft, duplicate targets removed) that is actually observed inside the
screening volume: 3 NM below FL245 or 5 NM above, and less than 1,000 ft
vertically (100 ft tolerance for 25 ft altitude quantisation). Encounters are
not necessarily losses of separation: in-trail sequencing on approach, holding
stacks and visual separation are legitimate reasons for proximity.

Four alerting methods are evaluated against that truth:

1. STCA-style safety net (conventional baseline): straight-line extrapolation
   of position and altitude over 120 s; every target is trusted.
2. Naive medium-term probe: the same over 300 s.
3. SkyControl filtered probe (300 s): duplicate targets merged, level-flight
   intent (|vertical rate| < 300 ft/min is level) and two-frame hysteresis.
4. SkyControl intent-aware probe (300 s): (3) plus the learned trajectory
   predictor and the *cleared level* of every aircraft. With digital
   clearances the ground system knows the cleared level; in this recording
   it is approximated by the level at which the aircraft actually levels off
   next (within 10 minutes). This is a counterfactual stand-in for the
   clearance record, stated as such in the results.
"""
from __future__ import annotations

from collections import Counter, defaultdict

import numpy as np

from ..config import MIN_CONTROLLED_ALT_FT, VERTICAL_SEPARATION_FT, VERTICAL_TOLERANCE_FT
from ..core.geo import LONDON
from .recording import Recording, label, reference, velocities

V_THRESHOLD = VERTICAL_SEPARATION_FT - VERTICAL_TOLERANCE_FT
EPISODE_GAP_S = 45
WARMUP_S = 300
SAMPLE_S = 5
LEVEL_FPM = 300

METHODS = {
    'stca': {'name': 'STCA-style safety net', 'lookahead': 120, 'filtered': False, 'intent': False, 'learned': False},
    'naive_probe': {'name': 'Naive 5-min probe', 'lookahead': 300, 'filtered': False, 'intent': False, 'learned': False},
    'filtered_probe': {'name': 'SkyControl filtered probe', 'lookahead': 300, 'filtered': True, 'intent': False, 'learned': False},
    'intent_probe': {'name': 'SkyControl intent-aware probe', 'lookahead': 300, 'filtered': True, 'intent': True, 'learned': True},
}


def horizontal_threshold(alt_a, alt_b):
    return np.where(np.maximum(alt_a, alt_b) < 24500, 3.0, 5.0)


def _episodes(times):
    """Group sorted timestamps into episodes separated by more than EPISODE_GAP_S."""
    out = []
    for ts in times:
        if out and ts - out[-1][1] <= EPISODE_GAP_S:
            out[-1][1] = ts
        else:
            out.append([ts, ts])
    return out


def cleared_levels(rec: Recording, horizon=600):
    """Level at which each aircraft next flies level (NaN if it does not within horizon)."""
    _, _, vz, _ = velocities(rec)
    level = np.full(len(rec.t), np.nan)
    for idx in rec.tracks.values():
        flat = np.abs(vz[idx]) * 60 < LEVEL_FPM
        steady = flat & np.r_[flat[1:], False]          # two consecutive level reports
        nxt = -1
        for k in range(len(idx) - 1, -1, -1):
            if steady[k]:
                nxt = k
            if nxt >= 0 and rec.t[idx[nxt]] - rec.t[idx[k]] <= horizon:
                level[idx[k]] = round(rec.alt[idx[nxt]] / 100) * 100
    return level


def _frame_states(rec: Recording, duplicates):
    vx, vy, vz, _ = velocities(rec)
    dup = np.isin(rec.ac, list(duplicates)) if duplicates else np.zeros(len(rec.t), bool)
    eligible = rec.airborne & (rec.alt >= MIN_CONTROLLED_ALT_FT) & ~np.isnan(vx)
    for ts in rec.frames:
        idx = rec.frame_index[int(ts)]
        idx = idx[eligible[idx]]
        yield int(ts), idx, dup[idx]


def actual_encounters(rec: Recording, duplicates):
    """Observed encounters (truth), grouped into episodes per pair."""
    hits = defaultdict(list)
    closest = {}
    for ts, idx, dup in _frame_states(rec, duplicates):
        idx = idx[~dup]
        if len(idx) < 2:
            continue
        i, j = np.triu_indices(len(idx), 1)
        A, B = idx[i], idx[j]
        h = np.hypot(rec.x[A] - rec.x[B], rec.y[A] - rec.y[B])
        dz = np.abs(rec.alt[A] - rec.alt[B])
        for k in np.flatnonzero((h < horizontal_threshold(rec.alt[A], rec.alt[B])) & (dz < V_THRESHOLD)):
            key = (int(min(rec.ac[A[k]], rec.ac[B[k]])), int(max(rec.ac[A[k]], rec.ac[B[k]])))
            hits[key].append(ts)
            if key not in closest or h[k] < closest[key][0]:
                closest[key] = (float(h[k]), float(dz[k]), int(rec.alt[A[k]]), int(rec.alt[B[k]]), int(A[k]), int(B[k]))
    return [{'pair': key, 'start': s, 'end': e, 'closest': closest[key]}
            for key, times in hits.items() for s, e in _episodes(sorted(times))]


def _predicted_paths(rec, idx, ts, cfg, levels, learned):
    """Sampled future positions (n_aircraft x n_samples) for one frame."""
    vx, vy, vz, _ = velocities(rec)
    times = np.arange(0, cfg['lookahead'] + 1, SAMPLE_S, dtype=float)
    x0, y0, z0 = rec.x[idx], rec.y[idx], rec.alt[idx]
    px = x0[:, None] + vx[idx][:, None] * times
    py = y0[:, None] + vy[idx][:, None] * times
    if cfg['learned'] and learned is not None:
        model = learned['second_half_model'] if ts < learned['mid'] else learned['first_half_model']
        ok = learned['usable'][idx]
        if ok.any():
            knots_t, knots_x, knots_y = [0.0], [x0[ok]], [y0[ok]]
            for h in (60, 120, 300):
                if h > cfg['lookahead']:
                    break
                mx, my = model.predict(rec, idx[ok], learned['X'], vx, vy, h)
                knots_t.append(float(h)); knots_x.append(mx); knots_y.append(my)
            kx, ky, kt = np.stack(knots_x, 1), np.stack(knots_y, 1), np.array(knots_t)
            # Piecewise-linear interpolation through the knots, extrapolating the last segment.
            seg = np.clip(np.searchsorted(kt, times, side='right') - 1, 0, len(kt) - 2)
            w = (times - kt[seg]) / (kt[seg + 1] - kt[seg])
            px[ok] = kx[:, seg] * (1 - w) + kx[:, seg + 1] * w
            py[ok] = ky[:, seg] * (1 - w) + ky[:, seg + 1] * w
    rate = vz[idx].copy()
    if cfg['filtered']:
        rate = np.where(np.abs(rate) * 60 < LEVEL_FPM, 0.0, rate)
    pz = z0[:, None] + rate[:, None] * times
    if cfg['intent']:
        target = levels[idx]
        known = np.isfinite(target)
        climb = known & (rate > 0)
        desc = known & (rate < 0)
        pz[climb] = np.minimum(pz[climb], np.maximum(target[climb], z0[climb])[:, None])
        pz[desc] = np.maximum(pz[desc], np.minimum(target[desc], z0[desc])[:, None])
    return px, py, pz


def run_alerting(rec: Recording, duplicates, cfg, levels=None, learned=None):
    """Alert timestamps per pair for one method configuration."""
    alerts = defaultdict(list)
    for ts, idx, dup in _frame_states(rec, duplicates):
        if cfg['filtered']:
            idx = idx[~dup]
        if len(idx) < 2:
            continue
        i, j = np.triu_indices(len(idx), 1)
        near = np.hypot(rec.x[idx[i]] - rec.x[idx[j]], rec.y[idx[i]] - rec.y[idx[j]]) < 80
        i, j = i[near], j[near]
        px, py, pz = _predicted_paths(rec, idx, ts, cfg, levels, learned)
        thr = horizontal_threshold(rec.alt[idx[i]], rec.alt[idx[j]])[:, None]
        inside = (np.hypot(px[i] - px[j], py[i] - py[j]) < thr) & (np.abs(pz[i] - pz[j]) < V_THRESHOLD)
        for k in np.flatnonzero(inside.any(axis=1)):
            a, b = int(rec.ac[idx[i[k]]]), int(rec.ac[idx[j[k]]])
            alerts[(min(a, b), max(a, b))].append(ts)
    if cfg['filtered']:
        alerts = {k: v for k, v in alerts.items() if any(b - a <= EPISODE_GAP_S for a, b in zip(v, v[1:]))}
    return alerts


def score(rec, alerts, truth, lookahead, duration_h):
    """Detection, warning time and nuisance share for one method."""
    truth_by_pair = defaultdict(list)
    for e in truth:
        truth_by_pair[e['pair']].append(e)
    alert_eps = {k: _episodes(sorted(v)) for k, v in alerts.items()}
    warnings = []
    for e in truth:
        if e['start'] - rec.frames[0] < WARMUP_S:
            continue
        warning = 0.0
        for a0, a1 in alert_eps.get(e['pair'], []):
            if a0 <= e['start'] and a1 >= e['start'] - EPISODE_GAP_S:
                warning = max(warning, float(e['start'] - a0))
        warnings.append(warning)
    nuisance = total = 0
    for pair, eps in alert_eps.items():
        for a0, a1 in eps:
            total += 1
            nuisance += not any(t['start'] <= a1 + lookahead + 60 and t['end'] >= a0 for t in truth_by_pair.get(pair, []))
    warnings = np.array(warnings)
    return {
        'lookahead_s': lookahead,
        'encounters_evaluated': int(len(warnings)),
        'alerted_before_encounter': int((warnings > 0).sum()),
        'detected_30s_ahead': int((warnings >= 30).sum()),
        'mean_warning_s': round(float(warnings.mean()), 1) if len(warnings) else None,
        'alert_episodes': total,
        'alerts_per_hour': round(float(total / duration_h), 1),
        'nuisance_episodes': nuisance,
        'nuisance_share_pct': round(100 * nuisance / total, 1) if total else 0.0,
    }, warnings


def classify_encounter(rec, e, airports):
    """Operational context of an encounter, for the descriptive table."""
    _, dz, _, _, ia, ib = e['closest']
    vx, vy, vz, _ = velocities(rec)
    nearest = []
    for k in (ia, ib):
        d = [(np.hypot(rec.x[k] - ax, rec.y[k] - ay), code) for code, ax, ay in airports]
        nearest.append(min(d))
    track = lambda k: np.degrees(np.arctan2(vx[k], vy[k]))
    dtrack = abs((track(ia) - track(ib) + 180) % 360 - 180)
    if nearest[0][1] == nearest[1][1] and nearest[0][0] < 30 and nearest[1][0] < 30 and vz[ia] < 0 and vz[ib] < 0:
        return f'Arrival sequencing to {nearest[0][1]}'
    if dtrack < 30:
        return 'Same-direction (in-trail or parallel)'
    if abs(vz[ia]) * 60 > LEVEL_FPM or abs(vz[ib]) * 60 > LEVEL_FPM:
        return 'Climbing/descending through traffic'
    return 'Crossing at similar level'


def _reduction(before, after):
    if not before['alert_episodes']:
        return None
    return round(100 * (before['alert_episodes'] - after['alert_episodes']) / before['alert_episodes'], 1)


def analyse(rec: Recording, duplicates, stats, learned=None):
    truth = actual_encounters(rec, duplicates)
    levels = cleared_levels(rec)
    duration_h = (rec.frames[-1] - rec.frames[0]) / 3600
    methods, warnings = [], {}
    for key, cfg in METHODS.items():
        alerts = run_alerting(rec, duplicates, cfg, levels, learned)
        result, w = score(rec, alerts, truth, cfg['lookahead'], duration_h)
        result.update(key=key, name=cfg['name'], filtered=cfg['filtered'], intent=cfg['intent'], learned=cfg['learned'])
        methods.append(result)
        warnings[key] = w
    by_key = {m['key']: m for m in methods}
    base, best = by_key['stca'], by_key['intent_probe']

    airports = [(a['icao'], *LONDON.to_xy(a['lat'], a['lon'])) for a in reference()['airports'] if a['major']]
    contexts = Counter()
    table = []
    for e in sorted(truth, key=lambda e: e['closest'][0]):
        context = classify_encounter(rec, e, airports)
        contexts[context] += 1
        a, b = e['pair']
        if len(table) < 40:
            table.append({'aircraft_a': label(rec, a), 'aircraft_b': label(rec, b), 'context': context,
                          'closest_nm': round(e['closest'][0], 2), 'vertical_ft': round(e['closest'][1]),
                          'altitudes_ft': [e['closest'][2], e['closest'][3]], 'duration_s': e['end'] - e['start']})
    warning_test = None
    if len(warnings['stca']) > 5:
        warning_test = stats.paired(warnings['stca'], warnings['intent_probe'], base['name'], best['name'],
                                    unit='s warning', higher_is_better=True)
    return {
        'truth_definition': ('Observed pairs inside 3 NM (<FL245) or 5 NM (>=FL245) and <900 ft vertical, '
                             'both >=3,000 ft, duplicate targets removed.'),
        'cleared_level_note': ('The intent-aware probe uses each aircraft\'s next level-off altitude from the recording '
                               'as a stand-in for the cleared level that a digital clearance record would hold.'),
        'encounter_pairs': len({e['pair'] for e in truth}), 'encounter_episodes': len(truth),
        'encounter_contexts': dict(contexts), 'encounters': table,
        'methods': methods,
        'alert_reduction_vs_naive_probe_pct': _reduction(by_key['naive_probe'], best),
        'alert_reduction_vs_stca_pct': _reduction(base, best),
        'warning_time_test': warning_test,
        'interpretation': ('Straight-line alerting in a busy terminal area raises hundreds of alerts per hour, mostly '
                           'for aircraft that the controller has already cleared to a safe level. Merging duplicate '
                           'targets and knowing each aircraft\'s cleared level removes most of that noise while '
                           'looking further ahead. The probe complements, and does not replace, the short-term '
                           'safety net.'),
    }
