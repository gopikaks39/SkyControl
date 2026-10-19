"""Early detection of emergency-like behaviour in real traffic.

ADS-B carries no "fuel low" or "medical" field, and the recording contains no
declared emergencies, so supervised emergency labels do not exist. SkyControl
therefore learns what *normal* kinematics look like from the real traffic
(Isolation Forest) and flags departures from it. To measure detection we
inject synthetic emergencies into copies of real test-period tracks:

* emergency descent (cabin depressurisation): -6,000 ft/min to 10,000 ft;
* engine-out drift-down: speed decays by 20% while descending at 1,500 ft/min;
* unannounced turn-back: a 180 deg turn at 3 deg/s while descending 1,000 ft/min.

Lost-communication (squawk 7600) has no kinematic signature and is handled by
the communication monitor instead; we report that limitation explicitly.

The conventional comparator is a fixed rule (|vertical rate| > 4,000 ft/min),
the kind of single-threshold flag a controller display can show. The ML
detector is set to a 1% false-alarm rate on normal test-period observations.
SkyControl's hybrid detector is the union of the rule and the ML detector.
Cleared-level adherence monitoring (CLAM) additionally needs the cleared level,
which the digital clearance record supplies; injected emergencies start from
level flight, so the cleared level is the level held at onset.
"""
from __future__ import annotations

import math

import numpy as np
from sklearn.ensemble import IsolationForest

from .recording import Recording

TRAIN_MINUTES = 60
TARGET_FA = 0.01
FEATURES = ['vertical_rate_fpm', 'abs_turn_rate_dps', 'speed_change_kt_per_s', 'vertical_accel_fpm_per_s', 'altitude_ft', 'speed_kt']


def track_features(t, x, y, z):
    """Per-point features from three consecutive points of one track."""
    t = t.astype(float)
    n = len(t)
    f = np.full((n, len(FEATURES)), np.nan)
    if n < 4:
        return f
    dt = np.diff(t)
    vx, vy, vz = np.diff(x) / dt, np.diff(y) / dt, np.diff(z) / dt * 60
    spd = np.hypot(vx, vy) * 3600
    trk = np.degrees(np.arctan2(vx, vy))
    for k in range(2, n):
        a, b = k - 2, k - 1        # velocity indices ending at k-1 and k
        gap = t[k] - t[k - 2]
        if gap > 75 or dt[a] <= 0 or dt[b] <= 0:
            continue
        turn = ((trk[b] - trk[a] + 540) % 360 - 180) / (gap / 2)
        f[k] = [vz[b], abs(turn), (spd[b] - spd[a]) / (gap / 2), (vz[b] - vz[a]) / (gap / 2), z[k], spd[b]]
    return f


def inject(t, x, y, z, kind, onset):
    """Return modified copies of a track after the onset index."""
    x, y, z = x.copy(), y.copy(), z.copy()
    vx = (x[onset] - x[onset - 1]) / (t[onset] - t[onset - 1])
    vy = (y[onset] - y[onset - 1]) / (t[onset] - t[onset - 1])
    speed = math.hypot(vx, vy)
    heading = math.atan2(vx, vy)
    for k in range(onset + 1, len(t)):
        dt = float(t[k] - t[k - 1])
        el = float(t[k] - t[onset])
        if kind == 'emergency_descent':
            z[k] = max(10000.0, z[k - 1] - 6000 / 60 * dt)
            s, h = speed, heading
        elif kind == 'engine_out':
            z[k] = max(5000.0, z[k - 1] - 1500 / 60 * dt)
            s, h = speed * max(0.8, 1 - 0.002 * el), heading
        else:  # turn_back
            z[k] = max(5000.0, z[k - 1] - 1000 / 60 * dt)
            s, h = speed, heading + math.radians(min(180.0, 3.0 * el))
        x[k] = x[k - 1] + s * math.sin(h) * dt
        y[k] = y[k - 1] + s * math.cos(h) * dt
    return x, y, z


def all_features(rec: Recording):
    F = np.full((len(rec.t), len(FEATURES)), np.nan)
    for idx in rec.tracks.values():
        F[idx] = track_features(rec.t[idx], rec.x[idx], rec.y[idx], rec.alt[idx])
    ok = np.all(np.isfinite(F), axis=1) & rec.airborne & (rec.alt > 3000)
    return F, ok


def analyse(rec: Recording, stats):
    F, ok = all_features(rec)
    split = rec.frames[0] + TRAIN_MINUTES * 60
    train = ok & (rec.t < split)
    test = ok & (rec.t >= split)
    forest = IsolationForest(n_estimators=200, contamination='auto', random_state=3).fit(F[train])
    normal_scores = -forest.score_samples(F[test])
    ml_threshold = float(np.quantile(normal_scores, 1 - TARGET_FA))
    rule = np.abs(F[test, 0])
    rule_threshold = 4000.0
    rule_fa = float((rule > rule_threshold).mean())

    rng = np.random.default_rng(17)
    candidates = [a for a, idx in rec.tracks.items()
                  if (rec.t[idx] >= split).sum() > 25 and rec.airborne[idx].all() and np.nanmin(rec.alt[idx]) > 15000]
    rng.shuffle(candidates)
    kinds = ('emergency_descent', 'engine_out', 'turn_back')
    outcome = {k: {m: [] for m in ('ml', 'rule', 'hybrid', 'clam', 'ml_delay', 'rule_delay', 'hybrid_delay', 'clam_delay')} for k in kinds}
    examples = []
    for a in candidates[:60]:
        idx = rec.tracks[a]
        idx = idx[rec.t[idx] >= split]
        dt_ok = np.all(np.diff(rec.t[idx]) <= 30)
        if not dt_ok or len(idx) < 20:
            continue
        level = np.abs(np.diff(rec.alt[idx])) <= 50
        onsets = [k for k in range(5, len(idx) - 12) if level[k - 2] and level[k - 1]]
        if not onsets:
            continue
        onset = onsets[0]
        cleared = rec.alt[idx[onset]]
        for kind in kinds:
            x, y, z = inject(rec.t[idx], rec.x[idx], rec.y[idx], rec.alt[idx], kind, onset)
            f = track_features(rec.t[idx], x, y, z)
            window = [k for k in range(onset + 1, len(idx)) if rec.t[idx[k]] - rec.t[idx[onset]] <= 120 and np.all(np.isfinite(f[k]))]
            if not window:
                continue
            scores = -forest.score_samples(f[window])
            hits = {
                'ml': [k for k, sc in zip(window, scores) if sc > ml_threshold],
                'rule': [k for k in window if abs(f[k, 0]) > rule_threshold],
                'clam': [k for k in window if abs(z[k] - cleared) > 300],
            }
            hits['hybrid'] = sorted(set(hits['ml']) | set(hits['rule']))
            o = outcome[kind]
            for m, found in hits.items():
                o[m].append(bool(found))
                if found:
                    o[m + '_delay'].append(float(rec.t[idx[found[0]]] - rec.t[idx[onset]]))
            if len(examples) < 6 and kind != 'turn_back':
                examples.append({'callsign': rec.callsign[a], 'kind': kind, 'detected_ml': bool(hits['ml']),
                                 'detected_rule': bool(hits['rule']), 'detected_clam': bool(hits['clam'])})
    rows = []
    for kind, o in outcome.items():
        n = len(o['ml'])
        row = {'kind': kind, 'injections': n}
        for m in ('rule', 'ml', 'hybrid', 'clam'):
            row[m + '_detected'] = int(sum(o[m]))
            row[m + '_rate_ci95'] = stats.wilson(sum(o[m]), n)
            row[m + '_median_delay_s'] = round(float(np.median(o[m + '_delay'])), 1) if o[m + '_delay'] else None
        rows.append(row)
    hybrid_fa = float(((normal_scores > ml_threshold) | (rule > rule_threshold)).mean())
    total = sum(r['injections'] for r in rows)
    return {
        'method': __doc__.strip().split('\n\n')[1].replace('\n', ' '),
        'features': FEATURES, 'train_observations': int(train.sum()), 'test_observations': int(test.sum()),
        'false_alarm_rate_ml': TARGET_FA, 'false_alarm_rate_rule': round(rule_fa, 4),
        'false_alarm_rate_hybrid': round(hybrid_fa, 4),
        'detection': rows,
        'totals': {m: sum(r[m + '_detected'] for r in rows) for m in ('rule', 'ml', 'hybrid', 'clam')},
        'injections_total': total,
        'limitation': 'Lost communications and onboard medical or fuel emergencies have no kinematic signature until the crew acts; they are covered by the communication monitor and crew reports.',
        'examples': examples,
    }
