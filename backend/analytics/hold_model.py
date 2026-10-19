"""Predicting holding before the aircraft reaches the stack (real labels).

Today a controller usually learns that an arrival must hold when it is handed
over near the stack. If the ground system predicts the hold while the aircraft
is still 30-80 NM away, delay can be absorbed by speed control instead.

Samples: every stack-bound arrival, observed at the first moment it is 30-80 NM
from the stack it later passes (and before any hold). Labels come from the
real tracks (did the aircraft hold at that stack?). Features are things a
ground system knows at that moment: distance, altitude, ground speed, aircraft
already holding at that stack, aircraft within 25 NM of it, and inbound
aircraft ahead in the queue. Temporal split: train on the first 55 minutes,
test on the rest. The sample is small, so results are indicative.
"""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from .holding import stacks
from .recording import Recording, label, velocities

FEATURES = ['distance_nm', 'altitude_ft', 'ground_speed_kt', 'holding_now', 'within_25nm', 'inbound_ahead']
TRAIN_MINUTES = 55
MIN_D, MAX_D = 30, 80


def _stack_bound(rec: Recording, holds):
    """Map aircraft -> stack for arrivals that pass within 12 NM of a stack below FL200."""
    fixes = stacks()
    held = {h['ac']: h for h in holds if h['stack'] != 'Other orbit'}
    out = {}
    for a, idx in rec.tracks.items():
        if a in held:
            out[a] = held[a]['stack']
            continue
        low = idx[rec.airborne[idx] & (rec.alt[idx] < 20000)]
        if len(low) == 0:
            continue
        best = None
        for s in fixes:
            d = np.hypot(rec.x[low] - s['xy'][0], rec.y[low] - s['xy'][1]).min()
            if d < 12 and (best is None or d < best[0]):
                best = (d, s['name'])
        if best:
            out[a] = best[1]
    return out, held


def build_samples(rec: Recording, holds):
    vx, vy, _, _ = velocities(rec)
    fixes = {s['name']: s['xy'] for s in stacks()}
    bound, held = _stack_bound(rec, holds)
    rows = []
    for a, stack in bound.items():
        sx, sy = fixes[stack]
        idx = rec.tracks[a]
        idx = idx[rec.airborne[idx] & ~np.isnan(vx[idx])]
        d = np.hypot(rec.x[idx] - sx, rec.y[idx] - sy)
        hold_start = held[a]['start'] if a in held else np.inf
        cand = np.flatnonzero((d >= MIN_D) & (d <= MAX_D) & (rec.t[idx] < hold_start))
        # Only arrivals that are getting closer to their stack.
        cand = [k for k in cand if k + 1 < len(idx) and d[k + 1] < d[k]]
        if not cand:
            continue
        k = cand[0]
        i = idx[k]
        ts = int(rec.t[i])
        frame = rec.frame_index[ts]
        frame = frame[rec.airborne[frame]]
        fd = np.hypot(rec.x[frame] - sx, rec.y[frame] - sy)
        holding_now = sum(1 for h in holds if h['stack'] == stack and h['start'] <= ts <= h['end'])
        others = [rec.ac[j] for j, dist in zip(frame, fd) if dist < d[k] and rec.ac[j] != a and bound.get(int(rec.ac[j])) == stack]
        rows.append({
            'ac': a, 'callsign': label(rec, a), 'stack': stack, 't': ts,
            'distance_nm': float(d[k]), 'altitude_ft': float(rec.alt[i]),
            'ground_speed_kt': float(np.hypot(vx[i], vy[i]) * 3600),
            'holding_now': holding_now, 'within_25nm': int((fd < 25).sum()), 'inbound_ahead': len(others),
            'label': int(a in held),
            'lead_time_min': round((hold_start - ts) / 60, 1) if a in held else None,
        })
    return rows


def analyse(rec: Recording, holds, stats):
    rows = build_samples(rec, holds)
    if len(rows) < 20 or len({r['label'] for r in rows}) < 2:
        return {'available': False, 'reason': 'Not enough labelled arrivals in this recording.', 'samples': len(rows)}
    split = rec.frames[0] + TRAIN_MINUTES * 60
    X = np.array([[r[f] for f in FEATURES] for r in rows], float)
    y = np.array([r['label'] for r in rows])
    train = np.array([r['t'] < split for r in rows])
    test = ~train
    model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000, class_weight='balanced'))
    model.fit(X[train], y[train])
    prob = model.predict_proba(X)[:, 1]
    result = {'available': True, 'samples': len(rows), 'train_samples': int(train.sum()), 'test_samples': int(test.sum()),
              'positives_total': int(y.sum()), 'positives_test': int(y[test].sum()), 'features': FEATURES,
              'method': __doc__.strip().split('\n\n')[1].replace('\n', ' ')}
    if len(set(y[test])) == 2:
        auc = roc_auc_score(y[test], prob[test])
        rng = np.random.default_rng(5)
        boot = []
        for _ in range(1000):
            s = rng.integers(0, test.sum(), test.sum())
            yy, pp = y[test][s], prob[test][s]
            if len(set(yy)) == 2:
                boot.append(roc_auc_score(yy, pp))
        pred = prob[test] >= 0.5
        tp = int((pred & (y[test] == 1)).sum())
        fp = int((pred & (y[test] == 0)).sum())
        fn = int((~pred & (y[test] == 1)).sum())
        tn = int((~pred & (y[test] == 0)).sum())
        result.update({
            'test_auc': round(float(auc), 3),
            'test_auc_ci95': [round(float(np.quantile(boot, 0.025)), 3), round(float(np.quantile(boot, 0.975)), 3)],
            'test_brier': round(float(brier_score_loss(y[test], prob[test])), 3),
            'confusion': {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn},
            'precision': round(tp / (tp + fp), 3) if tp + fp else None,
            'recall': round(tp / (tp + fn), 3) if tp + fn else None,
            'recall_ci95': stats.wilson(tp, tp + fn),
            'base_rate_test': round(float(y[test].mean()), 3),
        })
    coefs = model.named_steps['logisticregression'].coef_[0]
    result['coefficients'] = sorted([{'feature': f, 'weight': round(float(c), 3)} for f, c in zip(FEATURES, coefs)],
                                    key=lambda r: -abs(r['weight']))
    caught = [r['lead_time_min'] for r, p in zip(rows, prob) if r['label'] and p >= 0.5 and r['lead_time_min'] is not None]
    result['mean_lead_time_min'] = round(float(np.mean(caught)), 1) if caught else None
    result['predictions'] = [{k: (round(v, 1) if isinstance(v, float) else v) for k, v in r.items() if k != 'ac'} | {'probability': round(float(p), 3), 'split': 'train' if tr else 'test'}
                             for r, p, tr in zip(rows, prob, train)]
    return result
