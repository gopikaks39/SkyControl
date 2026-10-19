"""Emergency injection into real recorded traffic.

A user picks a real aircraft at a moment of the London-Amsterdam recording and
declares a simulated emergency for it. SkyControl then:

1. selects candidate airports (runway length, medical support, reachability);
2. builds the emergency trajectory (direct to a 10 NM final, descent profile);
3. checks it against the *recorded* future positions of every other aircraft
   (in live use the learned trajectory predictor would supply these);
4. proposes a level change for each conflicting aircraft, re-checked against
   all other recorded traffic;
5. gives the emergency the first landing slot and computes the delay imposed
   on the real arrivals that followed;
6. drafts the instructions and coordination messages and decides the
   automation level.

The emergency itself is simulated; the surrounding traffic is real.
"""
from __future__ import annotations

import math
import time

import numpy as np

from ..core import automation, workflow
from ..core.comms import Clearance, phraseology
from ..core.geo import LONDON, haversine_nm
from .recording import Recording, label, reference, velocities

KINDS = {
    'low_fuel': {'title': 'Fuel emergency (MAYDAY FUEL)', 'severity': 'Critical', 'endurance_min': 25, 'min_runway_m': 2000},
    'medical': {'title': 'Medical emergency (PAN PAN)', 'severity': 'Critical', 'endurance_min': 120, 'min_runway_m': 1800, 'medical': True},
    'engine_failure': {'title': 'Engine failure (MAYDAY)', 'severity': 'Critical', 'endurance_min': 60, 'min_runway_m': 2400},
    'emergency_descent': {'title': 'Emergency descent (MAYDAY)', 'severity': 'Critical', 'endurance_min': 90, 'min_runway_m': 2000},
    'lost_comms': {'title': 'Radio failure (squawk 7600)', 'severity': 'High', 'endurance_min': 120, 'min_runway_m': 2000},
}
STEP_S = 10
HORIZON_S = 900
SEP_NM = 5.0
SEP_FT = 1000.0
RUNWAY_SPACING_S = 120      # behind an emergency (runway inspection, vacating)
FOLLOW_SPACING_S = 90       # minimum spacing between following arrivals
MIN_LEVEL_FT = 3000
MAX_LEVEL_FT = 41000


def _state(rec: Recording, ts, icao):
    vx, vy, vz, _ = velocities(rec)
    if icao not in rec.icao:
        raise ValueError('Aircraft not in the recording')
    a = rec.icao.index(icao)
    idx = rec.tracks[a]
    idx = idx[(rec.t[idx] <= ts) & rec.airborne[idx]]
    if not len(idx) or ts - rec.t[idx[-1]] > 60:
        raise ValueError('Aircraft is not airborne and observed at that time')
    i = idx[-1]
    speed = float(np.hypot(vx[i], vy[i]) * 3600) if np.isfinite(vx[i]) else float(rec.speed[i] or 300)
    return {'ac': a, 'obs': int(i), 'callsign': label(rec, a), 'icao': icao, 'lat': float(rec.lat[i]), 'lon': float(rec.lon[i]),
            'x': float(rec.x[i]), 'y': float(rec.y[i]), 'alt': float(rec.alt[i]), 'speed': max(180.0, min(speed, 520.0)),
            'heading': float(math.degrees(math.atan2(vx[i], vy[i])) % 360) if np.isfinite(vx[i]) else float(rec.heading[i] or 0)}


FT_PER_NM_DESCENT = 318        # 3-degree descent path
FINAL_NM = 10


def required_track_nm(state, airport):
    """Track distance needed to lose the altitude on a 3-degree path (plus a 10 NM final)."""
    return (state['alt'] - airport['elevation_ft']) / FT_PER_NM_DESCENT


def candidate_airports(state, kind):
    spec = KINDS[kind]
    reach_nm = state['speed'] * spec['endurance_min'] / 60
    rows = []
    for ap in reference()['airports']:
        d = haversine_nm(state['lat'], state['lon'], ap['lat'], ap['lon'])
        track = max(d, required_track_nm(state, ap))
        reasons, ok = [], True
        if ap['runway_m'] < spec['min_runway_m']:
            ok = False
            reasons.append(f"runway {ap['runway_m']} m < {spec['min_runway_m']} m")
        if spec.get('medical') and not ap['medical']:
            ok = False
            reasons.append('no medical support listed')
        if track > reach_nm:
            ok = False
            reasons.append(f'{track:.0f} NM track beyond assumed reach {reach_nm:.0f} NM')
        eta = track / max(220.0, state['speed'] * 0.85) * 60 + 3
        rows.append({'icao': ap['icao'], 'name': ap['name'], 'distance_nm': round(d, 1), 'track_nm': round(track, 1),
                     'eta_min': round(eta, 1), 'runway_m': ap['runway_m'], 'medical': ap['medical'], 'suitable': ok,
                     'reasons': reasons or ['meets runway, support and reach requirements'],
                     'score': round(eta + (0 if ap['major'] else 4), 2)})
    rows.sort(key=lambda r: (not r['suitable'], r['score']))
    return rows


def emergency_path(state, airport, kind, t0):
    """Sampled 4D path (local NM) to touchdown on a flyable descent profile.

    If the airport is too close to lose the altitude on a 3-degree path, a
    dog-leg is inserted so the track is long enough. An emergency descent
    first goes down at 6,000 ft/min to 10,000 ft.
    """
    ax, ay = LONDON.to_xy(airport['lat'], airport['lon'])
    rh = math.radians(airport['runway_heading'])
    fx, fy = ax - FINAL_NM * math.sin(rh), ay - FINAL_NM * math.cos(rh)      # final approach fix
    start = (state['x'], state['y'])
    direct = math.hypot(fx - start[0], fy - start[1])
    needed = required_track_nm(state, airport) - FINAL_NM
    waypoints = [start]
    if needed > direct:
        mx, my = (start[0] + fx) / 2, (start[1] + fy) / 2
        offset = math.sqrt(max(0.0, (needed / 2) ** 2 - (direct / 2) ** 2))
        ux, uy = (fx - start[0]) / max(direct, 1e-6), (fy - start[1]) / max(direct, 1e-6)
        waypoints.append((mx - uy * offset, my + ux * offset))                  # descent dog-leg
    waypoints += [(fx, fy), (ax, ay)]
    total = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(waypoints, waypoints[1:]))
    pts, t, flown, z = [], 0.0, 0.0, state['alt']
    for (sx, sy), (ex, ey) in zip(waypoints, waypoints[1:]):
        length = math.hypot(ex - sx, ey - sy)
        steps = max(1, int(length / (state['speed'] * STEP_S / 3600)))
        for k in range(steps):
            f = k / steps
            pts.append((t, sx + (ex - sx) * f, sy + (ey - sy) * f, z))
            spd = state['speed'] if z > 10000 else min(state['speed'], 250)
            ds = length / steps
            dt = ds / spd * 3600
            flown += ds
            profile = airport['elevation_ft'] + (total - flown) * FT_PER_NM_DESCENT
            if kind == 'emergency_descent' and z > 10000:
                z = max(10000.0, z - 6000 / 60 * dt)
            z = max(airport['elevation_ft'], min(z, profile))
            t += dt
    pts.append((t, ax, ay, airport['elevation_ft']))
    return [{'t': round(t0 + p[0], 1), 'x': p[1], 'y': p[2], 'altitude_ft': round(p[3])} for p in pts]


def traffic_at(rec: Recording, times, exclude):
    """Recorded positions of every other airborne aircraft at the given times (interpolated)."""
    out = {}
    for a, idx in rec.tracks.items():
        if a in exclude:
            continue
        idx = idx[rec.airborne[idx]]
        if len(idx) < 2:
            continue
        tt = rec.t[idx].astype(float)
        if tt[-1] < times[0] or tt[0] > times[-1]:
            continue
        inside = (times >= tt[0]) & (times <= tt[-1])
        if not inside.any():
            continue
        xs = np.interp(times, tt, rec.x[idx])
        ys = np.interp(times, tt, rec.y[idx])
        zs = np.interp(times, tt, rec.alt[idx])
        xs[~inside] = np.nan
        out[a] = (xs, ys, zs)
    return out


def _conflicts(path_t, ex, ey, ez, traffic):
    found = {}
    for a, (xs, ys, zs) in traffic.items():
        h = np.hypot(xs - ex, ys - ey)
        v = np.abs(zs - ez)
        hit = np.flatnonzero((h < SEP_NM) & (v < SEP_FT))
        if len(hit):
            found[a] = {'first_t': float(path_t[hit[0]]), 'min_nm': float(np.nanmin(np.where(v < SEP_FT, h, np.inf)))}
    return found


def plan(rec: Recording, ts, icao, kind):
    if kind not in KINDS:
        raise ValueError('Unknown emergency type')
    started = time.perf_counter()
    spec = KINDS[kind]
    ts = int(rec.frame_at(ts)[0])
    state = _state(rec, ts, icao)
    airports = candidate_airports(state, kind)
    chosen = next((r for r in airports if r['suitable']), None)
    if chosen is None:
        raise ValueError('No suitable airport within reach')
    airport = next(ap for ap in reference()['airports'] if ap['icao'] == chosen['icao'])
    if kind == 'lost_comms':
        # A silent aircraft is assumed to continue on its current track and level (its last clearance).
        h = math.radians(state['heading'])
        path = [{'t': ts + k, 'x': state['x'] + state['speed'] * k / 3600 * math.sin(h),
                 'y': state['y'] + state['speed'] * k / 3600 * math.cos(h), 'altitude_ft': state['alt']}
                for k in range(0, HORIZON_S + 1, STEP_S)]
    else:
        path = emergency_path(state, airport, kind, ts)
    pt = np.array([p['t'] for p in path], float)
    ex = np.array([p['x'] for p in path])
    ey = np.array([p['y'] for p in path])
    ez = np.array([p['altitude_ft'] for p in path], float)
    window = pt <= ts + HORIZON_S
    traffic = traffic_at(rec, pt[window], {state['ac']})
    conflicts = _conflicts(pt[window], ex[window], ey[window], ez[window], traffic)

    ax, ay = LONDON.to_xy(airport['lat'], airport['lon'])
    resolutions = []
    for a, c in sorted(conflicts.items(), key=lambda kv: kv[1]['first_t']):
        xs, ys, zs = traffic[a]
        k = int(np.searchsorted(pt[window], c['first_t']))
        alt_now = float(zs[min(k, len(zs) - 1)])
        near_field = math.hypot(xs[min(k, len(xs) - 1)] - ax, ys[min(k, len(ys) - 1)] - ay) < 12
        if near_field and alt_now < 4000 + airport['elevation_ft']:
            # Low-level traffic at the diversion airfield is handled by arrival sequencing, not level changes.
            resolutions.append({'callsign': label(rec, a), 'icao': rec.icao[a], 'time_to_conflict_s': round(c['first_t'] - ts),
                                'min_separation_nm': round(c['min_nm'], 2), 'resolved': True, 'phraseology': None,
                                'action': 'Arrival at the diversion airfield: resequenced behind the emergency'})
            continue
        start = pt[window] >= ts + 60
        chosen_level = None
        for dz in (1000, -1000, 2000, -2000, 3000):
            level = int(round((alt_now + dz) / 1000) * 1000)
            if not MIN_LEVEL_FT <= level <= MAX_LEVEL_FT:
                continue
            new_z = zs.copy()
            new_z[start] = level
            if np.any((np.hypot(xs - ex[window], ys - ey[window]) < SEP_NM) & (np.abs(new_z - ez[window]) < SEP_FT)):
                continue
            clash = any(np.any((np.hypot(xs - bx, ys - by) < SEP_NM) & (np.abs(new_z - bz) < SEP_FT) & start)
                        for b, (bx, by, bz) in traffic.items() if b != a)
            if not clash:
                chosen_level = level
                break
        if chosen_level is not None:
            text = f'{"Climb" if chosen_level > alt_now else "Descend"} to {chosen_level:,} ft for emergency traffic'
        else:
            text = 'No safe level change found: controller to vector manually'
        clearance = Clearance(label(rec, a), level=chosen_level) if chosen_level else None
        resolutions.append({'callsign': label(rec, a), 'icao': rec.icao[a], 'time_to_conflict_s': round(c['first_t'] - ts),
                            'min_separation_nm': round(c['min_nm'], 2), 'action': text, 'resolved': chosen_level is not None,
                            'phraseology': phraseology(clearance, alt_now) if clearance else None})

    # Arrival-sequence impact at the chosen airport (real arrivals after ts).
    arrivals = []
    for a, idx in rec.tracks.items():
        if a == state['ac']:
            continue
        idx = idx[(rec.t[idx] > ts) & rec.airborne[idx]]
        near = idx[(np.hypot(rec.x[idx] - ax, rec.y[idx] - ay) < 8) & (rec.alt[idx] < 3000 + airport['elevation_ft'])]
        if len(near):
            arrivals.append((float(rec.t[near[0]]), label(rec, a)))
    arrivals.sort()
    em_land = float(pt[-1])
    # Insert the emergency slot; following arrivals keep their original spacing (at most the
    # minimum spacing), so the delay ripples back and dissipates where the stream had gaps.
    slot, prev_eta, delays = em_land, em_land, []
    for eta, cs in arrivals:
        if eta < em_land - RUNWAY_SPACING_S:
            continue
        spacing = RUNWAY_SPACING_S if prev_eta == em_land else min(eta - prev_eta, FOLLOW_SPACING_S)
        new = max(eta, slot + spacing)
        if new - eta < 1:
            break
        delays.append({'callsign': cs, 'original_eta_s': round(eta - ts), 'delay_s': round(new - eta)})
        slot, prev_eta = new, eta

    severity = spec['severity']
    level, approver, reasons = automation.decide(severity=severity, confidence=0.9 if all(r['resolved'] for r in resolutions) else 0.65,
                                                 data_quality=0.95)
    em_clearance = Clearance(state['callsign'], level=10000 if kind == 'emergency_descent' else 3000 + airport['elevation_ft'] // 100 * 100,
                             direct=None, runway=str(round(airport['runway_heading'] / 10)).zfill(2))
    messages = [] if kind == 'lost_comms' else [{'to': state['callsign'], 'channel': 'voice', 'text': phraseology(em_clearance, state['alt']) + f", cleared direct {airport['name']}"}]
    messages += [{'to': r['callsign'], 'channel': 'voice', 'text': r['phraseology']} for r in resolutions if r['phraseology']]
    if kind == 'lost_comms':
        messages.append({'to': 'Adjacent sectors', 'channel': 'digital coordination',
                         'text': f"{state['callsign']} squawk 7600 at {state['alt']:,.0f} ft, protect current track and level"})
    else:
        messages.append({'to': f"{airport['name']} approach", 'channel': 'digital coordination',
                         'text': f"{state['callsign']} {spec['title']}, ETA {round((em_land - ts) / 60, 1)} min, priority landing, emergency services standby"})
    if delays:
        messages.append({'to': 'Arrival manager', 'channel': 'digital coordination',
                         'text': f"Resequence {len(delays)} arrival(s); max delay {max(d['delay_s'] for d in delays)} s"})
    compute_ms = round((time.perf_counter() - started) * 1000, 1)
    profile = {'detect_baseline_s': 10, 'detect_hybrid_s': 2, 'manual_tasks': ['checklist', 'alternate_search'],
               'coordination': 1 + int(bool(delays)), 'urgent_share': 1.0}
    flow = workflow.compare(profile, len(resolutions) + (0 if kind == 'lost_comms' else 1), approver is not None)
    lat_lon = lambda x, y: LONDON.to_latlon(x, y)
    steps = [
        {'phase': 'DETECT', 'detail': f"{state['callsign']} declares {spec['title']} at {state['alt']:,.0f} ft, {state['speed']:.0f} kt."},
        {'phase': 'ASSESS', 'detail': f"{sum(r['suitable'] for r in airports)} suitable airports; {len(traffic)} real aircraft in the next {HORIZON_S // 60} min."},
        {'phase': 'CONTEXT SWITCH', 'detail': f"{level}: " + ' '.join(reasons)},
        {'phase': 'PLAN', 'detail': (f"Protect the last acknowledged route for {HORIZON_S // 60} min; expected to continue to "
                                     f"{airport['name']} if contact is not restored." if kind == 'lost_comms' else
                                     f"Divert to {airport['name']} ({chosen['distance_nm']} NM, ETA {round((em_land - ts) / 60, 1)} min).")},
        {'phase': 'VERIFY', 'detail': f"{len(conflicts)} conflict(s) with recorded traffic on the emergency path; {sum(r['resolved'] for r in resolutions)} resolved by level changes."},
        {'phase': 'AUTHORISE', 'detail': f"{(approver or 'no one').capitalize()} approval required."},
        {'phase': 'COMMUNICATE', 'detail': f"{len(messages)} messages drafted (voice instructions verified on readback; coordination sent digitally)."},
        {'phase': 'SEQUENCE', 'detail': f"Emergency gets the first slot; {len(delays)} real arrival(s) delayed, total {sum(d['delay_s'] for d in delays)} s."},
    ]
    return {
        'kind': kind, 'title': spec['title'], 'severity': severity, 'time': ts, 'aircraft': state | {'ac': None},
        'airports': airports[:6], 'chosen_airport': chosen,
        'path': [{'t': p['t'], 'altitude_ft': p['altitude_ft'], **dict(zip(('lat', 'lon'), lat_lon(p['x'], p['y'])))} for p in path[::2]],
        'traffic_considered': len(traffic), 'conflicts': len(conflicts), 'resolutions': resolutions,
        'arrival_delays': delays, 'messages': messages, 'automation_level': level, 'approver': approver,
        'reasons': reasons, 'steps': steps, 'workflow': flow, 'compute_ms': compute_ms,
        'note': 'Simulated emergency on a real aircraft; surrounding traffic follows its recorded positions.',
    }


def batch(rec: Recording, n=60, seed=4):
    """Inject emergencies at random moments into random real aircraft (for statistics)."""
    rng = np.random.default_rng(seed)
    kinds = list(KINDS)
    frames = rec.frames[(rec.frames > rec.frames[0] + 120) & (rec.frames < rec.frames[-1] - 900)]
    results = []
    attempts = 0
    while len(results) < n and attempts < n * 6:
        attempts += 1
        ts = int(rng.choice(frames))
        idx = rec.frame_index[ts]
        idx = idx[rec.airborne[idx] & (rec.alt[idx] > 8000)]
        if not len(idx):
            continue
        i = int(rng.choice(idx))
        kind = kinds[len(results) % len(kinds)]
        try:
            r = plan(rec, ts, rec.icao[rec.ac[i]], kind)
        except ValueError:
            continue
        results.append({'kind': kind, 'callsign': r['aircraft']['callsign'], 'airport': r['chosen_airport']['icao'],
                        'distance_nm': r['chosen_airport']['distance_nm'], 'traffic': r['traffic_considered'],
                        'conflicts': r['conflicts'], 'resolved': sum(x['resolved'] for x in r['resolutions']),
                        'delayed_arrivals': len(r['arrival_delays']),
                        'total_delay_s': sum(d['delay_s'] for d in r['arrival_delays']),
                        'compute_ms': r['compute_ms'],
                        'baseline_time_s': r['workflow']['baseline']['time_to_all_instructions_s'],
                        'hybrid_time_s': r['workflow']['hybrid']['time_to_all_instructions_s'],
                        'baseline_transmissions': r['workflow']['baseline']['radio_transmissions'],
                        'hybrid_transmissions': r['workflow']['hybrid']['radio_transmissions']})
    return results
