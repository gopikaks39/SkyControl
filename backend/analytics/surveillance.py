"""Surveillance-integrity analyses on the real recording.

Gap addressed: controller displays and safety nets trust each surveillance
track. The recording contains (a) duplicate "ghost" targets, the same aircraft
reported under two ICAO addresses that differ by one or two bits, and (b) track
dropouts where an aircraft is not updated for a minute or more. A naive alerting
tool treats a ghost as a second aircraft and freezes a dropped track at its last
position. SkyControl's integrity monitor merges ghosts and coasts dropped tracks
with a dead-reckoned position plus an uncertainty radius.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from .recording import Recording, label, velocities

GHOST_DISTANCE_NM = 1.0
GHOST_VERTICAL_FT = 300.0
GHOST_MAX_BIT_ERRORS = 2
COLOCATED_NM = 0.5
SAME_CALLSIGN_NM = 5.0
COLOCATED_FT = 100.0
COAST_GAP_S = 60


def address_bit_errors(a: str, b: str) -> int:
    try:
        return bin(int(a, 16) ^ int(b, 16)).count('1')
    except ValueError:
        return 24


def find_ghosts(rec: Recording):
    """Return ghost pairs and the set of aircraft indices judged to be ghosts.

    A pair is a duplicate when both targets are co-located (<1 NM, <300 ft) in
    the same frame and either their 24-bit addresses differ by at most two bits
    or they broadcast the same callsign. The weaker track (missing callsign,
    then fewer observations) is the ghost.
    """
    air = rec.airborne
    pairs = defaultdict(lambda: {'frames': 0, 'min_nm': 99.0, 'first': None, 'last': None})
    for ts, idx in rec.frame_index.items():
        idx = idx[air[idx]]
        if len(idx) < 2:
            continue
        dx = rec.x[idx][:, None] - rec.x[idx][None, :]
        dy = rec.y[idx][:, None] - rec.y[idx][None, :]
        dz = np.abs(rec.alt[idx][:, None] - rec.alt[idx][None, :])
        h = np.hypot(dx, dy)
        ii, jj = np.nonzero(np.triu((h < SAME_CALLSIGN_NM) & (dz < GHOST_VERTICAL_FT), 1))
        for i, j in zip(ii, jj):
            a, b = int(rec.ac[idx[i]]), int(rec.ac[idx[j]])
            bits = address_bit_errors(rec.icao[a], rec.icao[b])
            same_callsign = bool(rec.callsign[a]) and rec.callsign[a] == rec.callsign[b]
            # An anonymous target sitting on another aircraft (<0.5 NM, <=100 ft) is a duplicate whatever
            # the addresses say. Two different callsigns that close are a formation, not a duplicate.
            anonymous = not rec.callsign[a] or not rec.callsign[b]
            colocated = anonymous and h[i, j] < COLOCATED_NM and dz[i, j] <= COLOCATED_FT
            bit_error = bits <= GHOST_MAX_BIT_ERRORS and h[i, j] < GHOST_DISTANCE_NM
            if not (same_callsign or bit_error or colocated):
                continue
            key = (min(a, b), max(a, b))
            p = pairs[key]
            p['frames'] += 1
            p['min_nm'] = min(p['min_nm'], float(h[i, j]))
            p['first'] = p['first'] or int(ts)
            p['last'] = int(ts)
            p['bits'] = bits
            p['same_callsign'] = same_callsign
            p['colocated'] = p.get('colocated', False) or colocated

    ghosts, rows = set(), []
    for (a, b), p in pairs.items():
        if p['frames'] < 2 and not p.get('colocated'):
            continue
        score = lambda k: (bool(rec.callsign[k]), len(rec.tracks[k]))
        ghost, real = (a, b) if score(a) < score(b) else (b, a)
        ghosts.add(ghost)
        rows.append({
            'real_icao': rec.icao[real], 'real_callsign': label(rec, real),
            'ghost_icao': rec.icao[ghost], 'ghost_callsign': rec.callsign[ghost] or '(none)',
            'address_bit_errors': p['bits'], 'same_callsign': p['same_callsign'],
            'frames_together': p['frames'], 'min_separation_nm': round(p['min_nm'], 2),
            'duration_s': p['last'] - p['first'],
        })
    rows.sort(key=lambda r: -r['frames_together'])
    return rows, ghosts


def track_gaps(rec: Recording):
    """Dropouts longer than COAST_GAP_S between consecutive airborne updates."""
    gaps = []
    for a, idx in rec.tracks.items():
        if len(idx) < 2:
            continue
        dt = np.diff(rec.t[idx])
        for k in np.flatnonzero(dt > COAST_GAP_S):
            i, j = idx[k], idx[k + 1]
            if rec.ground[i] or rec.ground[j]:
                continue
            gaps.append((a, int(i), int(j), int(dt[k])))
    return gaps


def coasting_accuracy(rec: Recording, gaps):
    """Compare a frozen display position with dead-reckoned coasting.

    For each dropout we take the last velocity before the gap, predict the
    position at the moment the track reappears, and measure the error against
    the real reappearance position.
    """
    vx, vy, _, prev = velocities(rec)
    frozen, coasted, durations = [], [], []
    for a, i, j, dt in gaps:
        if np.isnan(vx[i]) or dt > 600:
            continue
        truth = np.array([rec.x[j], rec.y[j]])
        frozen.append(float(np.hypot(*(truth - [rec.x[i], rec.y[i]]))))
        pred = np.array([rec.x[i] + vx[i] * dt, rec.y[i] + vy[i] * dt])
        coasted.append(float(np.hypot(*(truth - pred))))
        durations.append(dt)
    return np.array(frozen), np.array(coasted), np.array(durations)


def analyse(rec: Recording, stats):
    ghost_rows, ghosts = find_ghosts(rec)
    gaps = track_gaps(rec)
    frozen, coasted, durations = coasting_accuracy(rec, gaps)
    ghost_obs = int(np.isin(rec.ac, list(ghosts)).sum()) if ghosts else 0
    hist_edges = [60, 90, 120, 180, 300, 600, 10 ** 6]
    gap_durations = np.array([g[3] for g in gaps])
    hist = [{'range': f'{lo}-{hi}s' if hi < 10 ** 6 else f'>{lo}s',
             'count': int(((gap_durations > lo) & (gap_durations <= hi)).sum())}
            for lo, hi in zip(hist_edges, hist_edges[1:])]
    comparison = stats.paired(frozen, coasted, 'Frozen last position', 'Dead-reckoned coast') if len(frozen) > 5 else None
    return {
        'ghosts': {
            'pairs': ghost_rows[:40], 'pair_count': len(ghost_rows), 'ghost_tracks': len(ghosts),
            'ghost_observations': ghost_obs,
            'share_of_observations_pct': round(100 * ghost_obs / len(rec.t), 2),
            'method': ('Targets within 300 ft vertically that either share a callsign (within 5 NM), have 24-bit '
                       'addresses differing by at most 2 bits (within 1 NM, 2+ frames), or are anonymous and sit '
                       'within 0.5 NM / 100 ft of another aircraft. '
                       'Different callsigns flying that close are treated as a formation, not a duplicate.'),
        },
        'gaps': {
            'count': len(gaps), 'tracks_affected': len({g[0] for g in gaps}),
            'tracks_total': rec.n_aircraft, 'histogram': hist,
            'median_gap_s': float(np.median(gap_durations)) if len(gaps) else 0,
        },
        'coasting': {
            'cases': int(len(frozen)),
            'frozen_mean_error_nm': round(float(frozen.mean()), 2) if len(frozen) else None,
            'coasted_mean_error_nm': round(float(coasted.mean()), 2) if len(coasted) else None,
            'frozen_median_error_nm': round(float(np.median(frozen)), 2) if len(frozen) else None,
            'coasted_median_error_nm': round(float(np.median(coasted)), 2) if len(coasted) else None,
            'comparison': comparison,
            'scatter': [{'gap_s': int(d), 'frozen_nm': round(float(f), 2), 'coasted_nm': round(float(c), 2)}
                        for d, f, c in list(zip(durations, frozen, coasted))[:400]],
        },
    }, ghosts
