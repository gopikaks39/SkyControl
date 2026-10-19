"""Learned trajectory prediction on real traffic.

Conventional conflict probes extrapolate a straight line from the current
velocity. In a terminal area aircraft follow route structure (stack entries,
downwind legs, standard arrival turns), so straight lines drift quickly.
SkyControl learns a correction to the straight-line prediction from the
recorded traffic itself: gradient-boosted trees predict the along-track and
cross-track residual at each look-ahead horizon from position, speed, track,
turn rate, altitude and vertical rate.

Evaluation uses a strict temporal split: models train on the first 60 minutes
(targets must also fall inside that period) and are tested on the last 30
minutes, which the models never saw.
"""
from __future__ import annotations

import math

import numpy as np
from sklearn.ensemble import HistGradientBoostingRegressor

from .recording import Recording, velocities

HORIZONS = (60, 120, 300)
TRAIN_MINUTES = 60
FEATURES = ['x_nm', 'y_nm', 'speed_kt', 'sin_track', 'cos_track', 'turn_rate_dps', 'altitude_ft', 'vertical_rate_fpm']


def state_features(rec: Recording):
    """Feature matrix for every observation; rows with NaN are unusable."""
    vx, vy, vz, prev = velocities(rec)
    n = len(rec.t)
    speed = np.hypot(vx, vy) * 3600
    track = np.arctan2(vx, vy)
    p1 = prev
    has_p1 = p1 >= 0
    prev_track = np.full(n, np.nan)
    prev_track[has_p1] = track[p1[has_p1]]
    dt_turn = np.full(n, np.nan)
    p2 = np.full(n, -1)
    p2[has_p1] = prev[p1[has_p1]]
    ok2 = p2 >= 0
    dt_turn[ok2] = (rec.t[ok2] - rec.t[p2[ok2]]) / 2.0
    dtrack = (track - prev_track + math.pi) % (2 * math.pi) - math.pi
    with np.errstate(invalid='ignore', divide='ignore'):
        turn = np.degrees(dtrack) / dt_turn
    X = np.column_stack([rec.x, rec.y, speed, np.sin(track), np.cos(track), turn, rec.alt, vz * 60])
    usable = rec.airborne & np.all(np.isfinite(X), axis=1) & (speed > 60)
    return X, usable, vx, vy


def straight_line(rec: Recording, idx, vx, vy, h):
    return rec.x[idx] + vx[idx] * h, rec.y[idx] + vy[idx] * h


def future_truth(rec: Recording, h):
    """Interpolated true position h seconds after each observation (NaN if not observed continuously)."""
    tx = np.full(len(rec.t), np.nan)
    ty = np.full(len(rec.t), np.nan)
    for idx in rec.tracks.values():
        if len(idx) < 3:
            continue
        tt = rec.t[idx].astype(float)
        target = tt + h
        j = np.searchsorted(tt, target)
        valid = (j < len(tt)) & (j > 0)
        jj = np.clip(j, 1, len(tt) - 1)
        span = tt[jj] - tt[jj - 1]
        valid &= (span > 0) & (span <= 90)
        # no dropout between the observation and the target time
        big_gap = np.r_[np.diff(tt) > 90, False]
        gap_cum = np.cumsum(big_gap)
        valid &= (gap_cum[jj - 1] - gap_cum[np.arange(len(tt))]) == 0
        f = np.where(span > 0, (target - tt[jj - 1]) / np.where(span > 0, span, 1), 0)
        x = rec.x[idx][jj - 1] + (rec.x[idx][jj] - rec.x[idx][jj - 1]) * f
        y = rec.y[idx][jj - 1] + (rec.y[idx][jj] - rec.y[idx][jj - 1]) * f
        tx[idx[valid]] = x[valid]
        ty[idx[valid]] = y[valid]
    return tx, ty


def _frame(vx, vy):
    """Unit along-track vector components."""
    s = np.hypot(vx, vy)
    with np.errstate(invalid='ignore', divide='ignore'):
        return vx / s, vy / s


class TrajectoryPredictor:
    """Straight-line prediction plus learned along/cross-track correction."""

    def __init__(self):
        self.models = {}

    def fit(self, X, ux, uy, res_x, res_y, h):
        along = res_x * ux + res_y * uy
        cross = -res_x * uy + res_y * ux
        params = dict(max_iter=250, learning_rate=0.06, max_leaf_nodes=31, random_state=7)
        self.models[h] = (HistGradientBoostingRegressor(**params).fit(X, along),
                          HistGradientBoostingRegressor(**params).fit(X, cross))

    def correction(self, X, ux, uy, h):
        if h not in self.models:
            # Interpolate between the nearest trained horizons, scaling linearly.
            known = sorted(self.models)
            lower = max([k for k in known if k <= h], default=known[0])
            ax, ay = self.correction(X, ux, uy, lower)
            return ax * (h / lower), ay * (h / lower)
        ma, mc = self.models[h]
        along, cross = ma.predict(X), mc.predict(X)
        return along * ux - cross * uy, along * uy + cross * ux

    def predict(self, rec, idx, X, vx, vy, h):
        sx, sy = straight_line(rec, idx, vx, vy, h)
        ux, uy = _frame(vx[idx], vy[idx])
        cx, cy = self.correction(X[idx], ux, uy, h)
        return sx + cx, sy + cy


def fit_on(rec: Recording, X, usable, vx, vy, train_mask_fn):
    """Fit one predictor on the observations selected by train_mask_fn(h)."""
    predictor = TrajectoryPredictor()
    ux, uy = _frame(vx, vy)
    for h in HORIZONS:
        tx, ty = future_truth(rec, h)
        train = np.flatnonzero(usable & np.isfinite(tx) & train_mask_fn(h))
        sx, sy = straight_line(rec, train, vx, vy, h)
        predictor.fit(X[train], ux[train], uy[train], tx[train] - sx, ty[train] - sy, h)
    return predictor


def cross_fitted(rec: Recording):
    """Two predictors, each trained on one half of the recording.

    Using the predictor from the *other* half at every frame gives honest
    out-of-sample predictions across the whole 90 minutes.
    """
    X, usable, vx, vy = state_features(rec)
    mid = rec.frames[0] + (rec.frames[-1] - rec.frames[0]) / 2
    first = fit_on(rec, X, usable, vx, vy, lambda h: rec.t + h < mid)
    second = fit_on(rec, X, usable, vx, vy, lambda h: rec.t >= mid)
    return {'mid': mid, 'first_half_model': first, 'second_half_model': second, 'X': X, 'usable': usable}


def train_and_evaluate(rec: Recording, stats):
    X, usable, vx, vy = state_features(rec)
    split_t = rec.frames[0] + TRAIN_MINUTES * 60
    predictor = TrajectoryPredictor()
    results, curves = [], []
    for h in HORIZONS:
        tx, ty = future_truth(rec, h)
        ok = usable & np.isfinite(tx)
        train = np.flatnonzero(ok & (rec.t + h < split_t))
        test = np.flatnonzero(ok & (rec.t >= split_t))
        sx, sy = straight_line(rec, np.arange(len(rec.t)), vx, vy, h)
        ux, uy = _frame(vx, vy)
        predictor.fit(X[train], ux[train], uy[train], tx[train] - sx[train], ty[train] - sy[train], h)
        mx, my = predictor.predict(rec, test, X, vx, vy, h)
        e_line = np.hypot(tx[test] - sx[test], ty[test] - sy[test])
        e_ml = np.hypot(tx[test] - mx, ty[test] - my)
        comparison = stats.paired(e_line, e_ml, 'Straight-line extrapolation', 'SkyControl learned predictor')
        turning = np.abs(X[test, 5]) > 0.5
        comparison.update({
            'horizon_s': h, 'train_samples': int(len(train)), 'test_samples': int(len(test)),
            'baseline_p95': round(float(np.percentile(e_line, 95)), 3),
            'proposed_p95': round(float(np.percentile(e_ml, 95)), 3),
            'turning_cases': int(turning.sum()),
            'turning_baseline_mean': round(float(e_line[turning].mean()), 3) if turning.any() else None,
            'turning_proposed_mean': round(float(e_ml[turning].mean()), 3) if turning.any() else None,
        })
        results.append(comparison)
        bins = np.array([0, 5000, 10000, 20000, 30000, 50000])
        alt_bin = np.digitize(X[test, 6], bins) - 1
        for b in range(len(bins) - 1):
            m = alt_bin == b
            if m.sum() > 50:
                curves.append({'horizon_s': h, 'band': f'{bins[b] // 1000}-{bins[b + 1] // 1000}k ft',
                               'n': int(m.sum()), 'baseline_mean': round(float(e_line[m].mean()), 3),
                               'proposed_mean': round(float(e_ml[m].mean()), 3)})
    importances = feature_importance(predictor, X, usable, vx, vy, rec, split_t)
    return predictor, {
        'method': ('Straight-line extrapolation vs gradient-boosted residual correction. Temporal split: train on '
                   f'minutes 0-{TRAIN_MINUTES}, test on minutes {TRAIN_MINUTES}-90 of the real recording.'),
        'features': FEATURES, 'horizons': results, 'by_altitude_band': curves,
        'feature_importance': importances,
    }


def feature_importance(predictor, X, usable, vx, vy, rec, split_t, h=300, n=3000):
    """Permutation importance (increase in mean error when one feature is shuffled)."""
    tx, ty = future_truth(rec, h)
    idx = np.flatnonzero(usable & np.isfinite(tx) & (rec.t >= split_t))
    rng = np.random.default_rng(11)
    idx = rng.choice(idx, size=min(n, len(idx)), replace=False)
    base_x, base_y = predictor.predict(rec, idx, X, vx, vy, h)
    base = np.hypot(tx[idx] - base_x, ty[idx] - base_y).mean()
    out = []
    for k, name in enumerate(FEATURES):
        Xp = X.copy()
        Xp[idx, k] = rng.permutation(Xp[idx, k])
        px, py = predictor.predict(rec, idx, Xp, vx, vy, h)
        out.append({'feature': name, 'error_increase_nm': round(float(np.hypot(tx[idx] - px, ty[idx] - py).mean() - base), 3)})
    return sorted(out, key=lambda r: -r['error_increase_nm'])
