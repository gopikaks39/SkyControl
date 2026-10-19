"""Airborne holding in the real recording and what an extended AMAN could absorb.

Gap addressed: arrival delay in London is largely absorbed in low-level
holding stacks (BNN, OCK, BIG, LAM for Heathrow), where aircraft burn fuel at
low altitude. An arrival manager that knows the delay early can absorb part of
it en route by small speed reductions ("linear holding"), which costs far less
fuel. Holding is detected from the real tracks; the fuel figures rest on the
assumptions listed in ASSUMPTIONS and are reported with sensitivity ranges.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from ..core.geo import LONDON, angle_diff
from .recording import Recording, label, reference, velocities

HOLD_TURN_DEG = 330          # cumulative turn that marks one holding circuit
HOLD_WINDOW_S = 480          # ... completed within 8 minutes
STACK_RADIUS_NM = 15
MIN_HOLD_ALT_FT = 4000

ASSUMPTIONS = {
    'holding_fuel_kg_per_min': 40,
    'holding_fuel_range_kg_per_min': [30, 100],
    'co2_per_kg_fuel': 3.16,
    'max_cruise_speed_reduction': 0.10,
    'linear_holding_fuel_share': 0.25,
    'extended_horizon_nm': 350,
    'cruise_speed_kt': 450,
    'sources': [
        'Holding burn of about 40 kg/min is typical of the narrow-body jets that dominate London traffic; wide-bodies burn up to about 100 kg/min.',
        'CO2 factor 3.16 kg per kg of jet fuel (ICAO Carbon Emissions Calculator methodology).',
        'Speed reductions of up to about 10% absorb delay en route at equal or lower fuel than nominal (Delgado & Prats, 2012); 25% of the holding fuel per absorbed minute is kept as a conservative penalty.',
        'An extended arrival-management horizon of about 350 NM follows the cross-border arrival management (XMAN) concept used for London Heathrow.',
    ],
}


def stacks():
    return [{**s, 'xy': LONDON.to_xy(s['lat'], s['lon'])} for s in reference()['holding_fixes']]


def detect_holds(rec: Recording):
    """Holding episodes: windows with >=330 deg of accumulated turn inside 8 minutes."""
    vx, vy, _, prev = velocities(rec)
    track = np.degrees(np.arctan2(vx, vy))
    fixes = stacks()
    holds = []
    for a, idx in rec.tracks.items():
        idx = idx[rec.airborne[idx] & (rec.alt[idx] > MIN_HOLD_ALT_FT) & ~np.isnan(track[idx])]
        if len(idx) < 10:
            continue
        t = rec.t[idx]
        turn = np.zeros(len(idx))
        cont = np.r_[False, np.diff(t) <= 90]
        turn[1:] = [angle_diff(track[p], track[q]) for p, q in zip(idx[:-1], idx[1:])]
        turn[~cont] = 0.0
        cum = np.cumsum(turn)
        in_hold = np.zeros(len(idx), bool)
        j = 0
        for i in range(len(idx)):
            j = max(j, i)
            while j + 1 < len(idx) and t[j + 1] - t[i] <= HOLD_WINDOW_S:
                j += 1
            seg = cum[i:j + 1] - cum[i]
            hit = np.flatnonzero(np.abs(seg) >= HOLD_TURN_DEG)
            if len(hit):
                in_hold[i:i + hit[0] + 1] = True
        if not in_hold.any():
            continue
        k = np.flatnonzero(in_hold)
        start, end = idx[k[0]], idx[k[-1]]
        cx, cy = rec.x[idx[k]].mean(), rec.y[idx[k]].mean()
        best = min(fixes, key=lambda s: np.hypot(cx - s['xy'][0], cy - s['xy'][1]))
        dist = float(np.hypot(cx - best['xy'][0], cy - best['xy'][1]))
        first = rec.tracks[a][0]
        pre = idx[rec.t[idx] < rec.t[start]]
        speed = float(np.nanmean(np.hypot(vx[pre], vy[pre]) * 3600)) if len(pre) else float('nan')
        holds.append({
            'ac': a, 'callsign': label(rec, a), 'stack': best['name'] if dist <= STACK_RADIUS_NM else 'Other orbit',
            'serves': best['serves'] if dist <= STACK_RADIUS_NM else '',
            'distance_to_fix_nm': round(dist, 1), 'start': int(rec.t[start]), 'end': int(rec.t[end]),
            'minutes': round((rec.t[end] - rec.t[start]) / 60, 1),
            'turn_deg': round(float(abs(cum[k[-1]] - cum[k[0]]))),
            'mean_altitude_ft': int(np.nanmean(rec.alt[idx[k]])),
            'first_seen_s_before_hold': int(rec.t[start] - rec.t[first]),
            'first_seen_distance_nm': round(float(np.hypot(rec.x[first] - best['xy'][0], rec.y[first] - best['xy'][1])), 1),
            'approach_speed_kt': round(speed, 1) if np.isfinite(speed) else None,
        })
    return holds


def holding_counts(rec: Recording, holds):
    """Aircraft holding per stack in every frame (time series)."""
    names = sorted({h['stack'] for h in holds})
    series = {n: np.zeros(len(rec.frames), int) for n in names}
    for h in holds:
        series[h['stack']][(rec.frames >= h['start']) & (rec.frames <= h['end'])] += 1
    return series


def aman_estimate(holds):
    a = ASSUMPTIONS
    gain = 1 / (1 - a['max_cruise_speed_reduction']) - 1
    rows = []
    for h in holds:
        if h['stack'] == 'Other orbit':
            continue
        observed_cap = h['first_seen_s_before_hold'] / 60 * gain
        extended_cap = a['extended_horizon_nm'] / a['cruise_speed_kt'] * 60 * gain
        rows.append({**h, 'absorbable_observed_min': round(min(h['minutes'], observed_cap), 2),
                     'absorbable_extended_min': round(min(h['minutes'], extended_cap), 2)})
    return rows


def analyse(rec: Recording):
    holds = detect_holds(rec)
    rows = aman_estimate(holds)
    a = ASSUMPTIONS
    per_stack = defaultdict(lambda: {'holds': 0, 'minutes': 0.0, 'max_minutes': 0.0})
    for h in holds:
        s = per_stack[h['stack']]
        s['holds'] += 1
        s['minutes'] += h['minutes']
        s['max_minutes'] = max(s['max_minutes'], h['minutes'])
    stack_table = [{'stack': k, 'serves': next((h['serves'] for h in holds if h['stack'] == k), ''),
                    'holds': v['holds'], 'total_minutes': round(v['minutes'], 1),
                    'mean_minutes': round(v['minutes'] / v['holds'], 1), 'max_minutes': round(v['max_minutes'], 1)}
                   for k, v in sorted(per_stack.items(), key=lambda kv: -kv[1]['minutes'])]
    stack_minutes = sum(r['minutes'] for r in rows)
    fuel = stack_minutes * a['holding_fuel_kg_per_min']
    saving_share = 1 - a['linear_holding_fuel_share']
    observed = sum(r['absorbable_observed_min'] for r in rows)
    extended = sum(r['absorbable_extended_min'] for r in rows)
    series = holding_counts(rec, holds)
    step = max(1, len(rec.frames) // 90)
    return {
        'holds': sorted(holds, key=lambda h: h['start']),
        'stacks': stack_table,
        'total_holds': len(holds), 'stack_holds': len(rows),
        'stack_holding_minutes': round(stack_minutes, 1),
        'holding_fuel_kg': round(fuel), 'holding_co2_kg': round(fuel * a['co2_per_kg_fuel']),
        'holding_fuel_range_kg': [round(stack_minutes * v) for v in a['holding_fuel_range_kg_per_min']],
        'aman': {
            'absorbable_minutes_observed_horizon': round(observed, 1),
            'absorbable_minutes_extended_horizon': round(extended, 1),
            'share_absorbable_extended_pct': round(100 * extended / stack_minutes, 1) if stack_minutes else 0,
            'fuel_saved_kg_extended': round(extended * a['holding_fuel_kg_per_min'] * saving_share),
            'co2_saved_kg_extended': round(extended * a['holding_fuel_kg_per_min'] * saving_share * a['co2_per_kg_fuel']),
            'per_flight': [{k: r[k] for k in ('callsign', 'stack', 'minutes', 'absorbable_observed_min', 'absorbable_extended_min')} for r in rows],
        },
        'timeline': [{'t': int(rec.frames[i] - rec.frames[0]), **{k: int(v[i]) for k, v in series.items()}}
                     for i in range(0, len(rec.frames), step)],
        'assumptions': ASSUMPTIONS,
        'method': ('A hold is >=330 degrees of accumulated turn within 8 minutes above 4,000 ft. It is assigned to the '
                   f'nearest published stack within {STACK_RADIUS_NM} NM, otherwise reported as "Other orbit".'),
    }
