"""Scenario Lab engine: 21 finite, verifiable ATC exercises.

Every scenario produces two complete plans for the same aircraft:

* baseline  - what happens under the conventional comparator named in
              `baseline_label` (unchanged routes, first-come-first-served,
              an undetected readback error, trusting a wrong prediction ...);
* resolved  - SkyControl's plan, checked against every other route with the
              exact piecewise-linear conflict test in core.separation.

On top of the trajectories each scenario carries the step-by-step handling
pipeline (detect -> assess -> context switch -> plan -> verify -> authorise ->
communicate -> execute -> monitor -> close), the automation-level log, the
message log with readback verification, and the workflow comparison.

Coordinates are a local NM frame (x east, y north); times in seconds.
These are teaching exercises, not operational procedures.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from . import automation, workflow
from .comms import Clearance, callsign_similarity, phraseology, telephony, verify_readback
from .separation import (all_conflicts, avoid, dist, flying_route, interval_conflict, point, pos,
                         route_length, segment_distance)

GATE = 20
PRIMARY = (8, 0)
ALTERNATE = (10, 16)


@dataclass
class Spec:
    title: str
    category: str
    severity: str
    aircraft: int
    problem: str
    goal: str
    gap: str
    profile: dict = field(default_factory=dict)
    context: dict = field(default_factory=dict)


def _p(detect_b, detect_h, tasks=(), coordination=0, urgent=1.0, extra_baseline=0):
    return {'detect_baseline_s': detect_b, 'detect_hybrid_s': detect_h, 'manual_tasks': list(tasks),
            'coordination': coordination, 'urgent_share': urgent, 'extra_baseline': extra_baseline}


SPECS = {
    'normal': Spec('Normal approach', 'Capacity', 'Low', 3, 'Three normal arrivals approach from different directions',
                   'Complete three arrivals and runway vacations', 'Routine workload: every clearance is a voice transmission',
                   _p(10, 1, urgent=0.0), {'confidence': 0.97}),
    'collision': Spec('Converging traffic', 'Separation', 'Critical', 6, 'Six aircraft converge on one crossing point',
                      'Deconflict all crossing routes', 'Short look-ahead safety nets warn late; resolution is manual and serial',
                      _p(60, 2, urgent=1.0), {'confidence': 0.93}),
    'high_density': Spec('Traffic overload', 'Capacity', 'High', 10, 'Ten arrivals compete for the same runway window',
                         'Land every aircraft in a conflict-free sequence', 'Holding decided late at the stack; heavy voice workload',
                         _p(30, 2, coordination=1, urgent=0.3), {'confidence': 0.9, 'workload': 0.9}),
    'low_fuel': Spec('Fuel emergency', 'Emergency', 'Critical', 4, 'A low-fuel arrival is last in the original queue',
                     'Land the priority flight before its simulated fuel deadline', 'Emergency priority is negotiated by voice while traffic keeps calling',
                     _p(15, 2, tasks=('checklist',), coordination=1, urgent=0.75), {'confidence': 0.92}),
    'medical': Spec('Medical priority', 'Emergency', 'Critical', 3, 'A medical emergency needs an equipped destination',
                    'Give the medical flight the first feasible arrival slot', 'Medical services and sequencing are coordinated by telephone',
                    _p(15, 2, tasks=('checklist',), coordination=2, urgent=0.67), {'confidence': 0.92}),
    'engine_failure': Spec('Engine failure', 'Emergency', 'Critical', 2, 'An engine-out aircraft cannot reach its original destination',
                           'Choose a reachable alternate and complete landing', 'Reachable alternates are worked out mentally under time pressure',
                           _p(15, 2, tasks=('checklist', 'alternate_search'), coordination=1), {'confidence': 0.88}),
    'emergency_descent': Spec('Emergency descent', 'Emergency', 'Critical', 4, 'Cabin depressurisation: an aircraft descends from FL350 to FL100',
                              'Clear all traffic below out of the descent path', 'Traffic below is moved reactively after the crew starts descending',
                              _p(20, 3, tasks=('checklist',), coordination=1), {'confidence': 0.9}),
    'bird_strike': Spec('Bird strike', 'Emergency', 'High', 3, 'A departing aircraft encounters a flock near the runway',
                        'Return the affected aircraft after dispersal and runway inspection', 'Runway inspection and return are coordinated by phone',
                        _p(20, 3, tasks=('checklist',), coordination=2, urgent=0.67), {'confidence': 0.9}),
    'runway_incursion': Spec('Runway incursion', 'Runway', 'Critical', 3, 'A vehicle occupies the arrival runway',
                             'Clear the vehicle, go around, and resequence arrivals', 'Incursions are often seen late, by eye',
                             _p(25, 2, coordination=1), {'confidence': 0.91}),
    'runway_closed': Spec('Runway closure', 'Runway', 'High', 4, 'The destination runway closes',
                          'Reallocate every arrival to the alternate runway', 'Every arrival must be re-cleared individually by voice',
                          _p(10, 1, tasks=('alternate_search',), coordination=2, urgent=0.25), {'confidence': 0.92}),
    'go_around': Spec('Go-around', 'Runway', 'High', 3, 'The preceding aircraft is still on the runway',
                      'Fly a missed approach and return to land after runway clearance', 'Re-sequencing after a go-around adds voice workload at the busiest moment',
                      _p(10, 2, urgent=0.67), {'confidence': 0.92}),
    'diversion': Spec('Diversion', 'Capacity', 'High', 3, 'The planned airport is unavailable',
                      'Select the nearest suitable open alternate and sequence landings', 'Alternate capacity is checked by telephone',
                      _p(15, 2, tasks=('alternate_search',), coordination=2, urgent=0.34), {'confidence': 0.9}),
    'weather': Spec('Severe weather', 'Hazard', 'High', 5, 'Five routes cross a storm cell',
                    'Route every flight around the storm boundary', 'Deviations are requested one by one on a congested frequency',
                    _p(30, 2, coordination=1, urgent=0.4), {'confidence': 0.9}),
    'lost_comms': Spec('Radio failure', 'Communication', 'High', 4, 'One converging flight cannot acknowledge new instructions',
                       'Keep its route fixed and move the other flights clear', 'A silent aircraft is noticed only when it fails to answer',
                       _p(45, 10, coordination=1, urgent=1.0), {'confidence': 0.9}),
    'readback_error': Spec('Readback error', 'Communication', 'High', 3, 'A pilot reads back FL140 instead of the cleared FL120',
                           'Catch the wrong readback before the aircraft climbs into traffic', 'Hearback relies on the controller noticing a wrong number',
                           _p(120, 1, urgent=1.0), {'confidence': 0.95}),
    'callsign_confusion': Spec('Callsign confusion', 'Communication', 'High', 3, 'BAW-style similar callsigns share the frequency and the wrong aircraft takes the descent',
                               'Deliver the descent to the right aircraft only', 'Similar callsigns are managed by vigilance and after-the-fact reports',
                               _p(90, 1, urgent=1.0, extra_baseline=2), {'confidence': 0.94}),
    'level_bust': Spec('Level bust', 'Separation', 'Critical', 3, 'A climbing aircraft fails to level off at its cleared FL110',
                       'Detect the deviation early and return the aircraft to FL110', 'Without the cleared level, safety nets see the bust only when traffic is close',
                       _p(110, 12, urgent=1.0, extra_baseline=1), {'confidence': 0.93}),
    'ghost_target': Spec('Ghost target', 'Surveillance', 'High', 3, 'A duplicate radar target appears on top of a real aircraft',
                         'Recognise the duplicate and avoid an unnecessary avoidance manoeuvre', 'Duplicate targets trigger false alerts and needless instructions',
                         _p(5, 1, urgent=1.0, extra_baseline=1), {'confidence': 0.9, 'data_quality': 0.7}),
    'sensor_dropout': Spec('Surveillance gap', 'Surveillance', 'High', 3, 'A missing position report creates an uncertain sector',
                           'Protect the sector until the simulated feed recovers', 'A frozen track looks valid until someone notices',
                           _p(60, 5, coordination=1, urgent=0.67), {'confidence': 0.85, 'data_quality': 0.4}),
    'ai_disagreement': Spec('AI disagreement', 'Automation', 'High', 3, 'The learned model predicts a turn away; the safety rule predicts a conflict',
                            'Hand the decision to the controller and apply the conservative plan', 'Automation bias: trusting a confident but wrong prediction',
                            _p(30, 2, urgent=1.0), {'confidence': 0.6, 'disagreement': True}),
    'hijack': Spec('Security signal', 'Emergency', 'Critical', 3, 'An aircraft reports a security signal',
                   'Keep other traffic outside the protected corridor', 'Security coordination competes with normal traffic for the controller',
                   _p(10, 2, tasks=('checklist',), coordination=2, urgent=0.67), {'confidence': 0.9, 'security': True}),
}

CATALOG_ORDER = list(SPECS)


# ---------------------------------------------------------------------------
# Route builders
# ---------------------------------------------------------------------------

def arrivals_route(anchor, z, loops, airport, missed=False):
    """Hold loops keep aircraft moving; final approach and taxi finish at the assigned field."""
    x, y = anchor
    ax, ay = airport
    p = [point(x - 1, y, z, 0), point(x, y, z, GATE)]
    if missed:
        fix, threshold = (ax - 10, ay), (ax - 1.5, ay)
        t = p[-1]['t'] + max(dist((x, y), fix) / 180 * 3600, abs(z - 3000) / 1200 * 60, 60)
        p.append(point(*fix, 3000, t))
        t += dist(fix, threshold) / 150 * 3600
        p.append(point(*threshold, 500, t))                          # decision point: go around
        t += dist(threshold, (ax + 5, ay + 2)) / 160 * 3600
        p.append(point(ax + 5, ay + 2, 3000, t))                     # climb-out
        t += dist((ax + 5, ay + 2), (ax - 2, ay + 7)) / 180 * 3600
        p.append(point(ax - 2, ay + 7, 4000, t))                     # downwind
        t += dist((ax - 2, ay + 7), (x, y)) / 180 * 3600
        p.append(point(x, y, z, t))
    for _ in range(loops):
        t = p[-1]['t']
        p += [point(x + 2, y, z, t + 40), point(x + 2, y + 2, z, t + 80), point(x, y + 2, z, t + 120), point(x, y, z, t + 160)]
    fix = (ax - 10, ay)
    prev = p[-1]
    leg = max(dist((x, y), fix) / 180 * 3600, abs(z - 3000) / 1200 * 60, 60)
    p.append(point(*fix, 3000, prev['t'] + leg))
    landing = p[-1]['t'] + 200
    p.append(point(ax, ay, 0, landing))
    p.append(point(ax + 0.25, ay + 0.25, 0, landing + 45))
    return p, landing


def crossing_route(start, end, z0, t_end, level=None, at=None, rate_fpm=1500):
    """Straight crossing; optional level change starting at time `at`."""
    route = [point(*start, z0, 0)]
    if level is None or level == z0:
        route.append(point(*end, z0, t_end))
        return route
    def xy(t):
        f = t / t_end
        return start[0] + (end[0] - start[0]) * f, start[1] + (end[1] - start[1]) * f
    at = at if at is not None else GATE
    reach = at + abs(level - z0) / rate_fpm * 60
    route.append(point(*xy(at), z0, at))
    route.append(point(*xy(min(reach, t_end - 1)), level, min(reach, t_end - 1)))
    route.append(point(*end, level, t_end))
    return route


def _aircraft(names, source):
    return [{'name': n, 'baseline': [], 'resolved': [], 'action': '', 'role': 'traffic', 'fuel_pct': None,
             'source': source, 'clearance': None, 'channel': 'none'} for n in names]


# ---------------------------------------------------------------------------
# Scenario families
# ---------------------------------------------------------------------------

def _crossing(key, a):
    """collision / lost_comms: greedy flight-level assignment with all-pairs verification."""
    n = len(a)
    scene = {'airports': [], 'zones': [], 'objects': []}
    events = []
    assigned = []
    for i, f in enumerate(a):
        angle = 2 * math.pi * i / n + (0.23 if key == 'lost_comms' else 0)
        sx, sy = 24 * math.cos(angle), 24 * math.sin(angle)
        f['baseline'] = [point(sx, sy, 12000, 0), point(-sx, -sy, 12000, 720)]
        if key == 'lost_comms' and i == 0:
            f['resolved'] = list(f['baseline'])
            f['action'] = 'No new manoeuvre: protect the last acknowledged route until radio contact returns'
            f['role'] = 'radio failure (squawk 7600)'
            assigned.append(f)
            continue
        for level in range(12000, 23001, 1000):
            candidate = crossing_route((sx, sy), (-sx, -sy), 12000, 720, level, GATE)
            if not any(interval_conflict(candidate, o['resolved']) is not None for o in assigned):
                f['resolved'] = candidate
                if level == 12000:
                    f['action'] = 'Maintain 12,000 ft and continue across the sector'
                else:
                    f['action'] = f'Climb to FL{level // 100}; keep assigned heading'
                    f['clearance'] = Clearance(f['name'], level=level)
                    f['channel'] = 'voice'
                assigned.append(f)
                break
        else:
            raise ValueError('No conflict-free level assignment found')
    if key == 'lost_comms':
        scene['objects'] = [{'kind': 'radio', 'flight': a[0]['name'], 'clear_at': 550}]
        events.append({'t': 550, 'message': 'Backup-radio contact established; the protected route stayed unchanged'})
        algorithm = ('NORDO intent model: the silent aircraft keeps its last acknowledged route (ICAO radio-failure '
                     'procedure). Greedy flight-level assignment moves every other aircraft, each verified against all '
                     'previously assigned routes with the exact segment test.')
        baseline = 'Unchanged crossing routes; silence noticed late'
    else:
        scene['zones'] = [{'kind': 'conflict', 'x': 0, 'y': 0, 'radius': 5, 'clear_at': 550}]
        algorithm = ('Greedy flight-level assignment with continuous all-pairs trajectory checks (1,500 ft/min climb). '
                     'The first route stays fixed; each other aircraft takes the lowest conflict-free level.')
        baseline = 'Unchanged crossing routes (2-minute safety net only)'
    return {'scene': scene, 'events': events, 'algorithm': algorithm, 'baseline_label': baseline}


def _hazard(key, a):
    """weather / sensor_dropout / hijack: Dijkstra visibility-graph routing around a protected circle."""
    radius = 6 if key == 'weather' else 8
    kind = {'weather': 'weather', 'sensor_dropout': 'uncertainty', 'hijack': 'protected'}[key]
    obstacle = {'kind': kind, 'x': 0, 'y': 0, 'radius': radius}
    scene = {'airports': [], 'zones': [obstacle], 'objects': []}
    events = []
    for i, f in enumerate(a):
        sy = -12 + i * 24 / max(1, len(a) - 1)
        start, end = (-24, sy), (24, -sy / 2)
        z = 8000 + i * 1500
        prefix = [point(start[0] - 1, start[1], z, 0)]
        f['baseline'] = prefix + flying_route([start, end], z)
        bypass = avoid(start, end, (0, 0, radius))
        f['resolved'] = prefix + flying_route(bypass, z)
        changed = len(bypass) > 2
        side = 'southern' if bypass[1][1] < 0 else 'northern'
        f['action'] = f'Fly the {side} bypass; maintain {z:,} ft' if changed else f'Route already clear; maintain {z:,} ft'
        if changed:
            f['clearance'] = Clearance(f['name'], heading=int(round(math.degrees(math.atan2(bypass[1][0] - start[0], bypass[1][1] - start[1])) % 360 / 5) * 5) or 360)
            f['channel'] = 'datalink' if key == 'weather' and i % 2 else 'voice'
    if key == 'hijack':
        a[0]['role'] = 'security (squawk 7500)'
        a[0]['action'] = 'Security aircraft: no instruction beyond acknowledging; other traffic is kept clear'
        a[0]['resolved'] = list(a[0]['baseline'])
        a[0]['clearance'] = None
        events.append({'t': 650, 'message': 'Security coordination complete; corridor protected until traffic exits'})
    if key == 'sensor_dropout':
        obstacle['clear_at'] = 600
        events.append({'t': 600, 'message': 'Surveillance restored; the protected uncertainty sector is released'})
    algorithm = ('Dijkstra shortest path on a 16-node visibility graph around the buffered hazard. Every segment keeps '
                 'the exclusion radius; altitude layers separate the participating flights.')
    baseline = 'Original routes through the affected sector'
    return {'scene': scene, 'events': events, 'algorithm': algorithm, 'baseline_label': baseline, 'obstacle': obstacle}


ARRIVAL_SCENARIOS = ('normal', 'high_density', 'low_fuel', 'medical', 'engine_failure', 'bird_strike',
                     'runway_incursion', 'runway_closed', 'go_around', 'diversion')


def _arrivals(key, a):
    """Priority-aware runway sequencing with holding-circuit search."""
    scene = {'airports': [{'id': 'A', 'name': 'Primary', 'x': PRIMARY[0], 'y': PRIMARY[1]},
                          {'id': 'B', 'name': 'Alternate', 'x': ALTERNATE[0], 'y': ALTERNATE[1]}],
             'zones': [], 'objects': []}
    events = []
    n = len(a)
    airport, field_id, closed = PRIMARY, 'A', 0
    anchors = [(-24 + 8 * (i % 3), -18 + 12 * (i // 3)) for i in range(n)]
    if key == 'engine_failure':
        anchors, airport, field_id = [(17, 26), (-20, -10)], ALTERNATE, 'B'
    if key in ('runway_closed', 'diversion'):
        airport, field_id, closed = ALTERNATE, 'B', 10 ** 6
    if key in ('runway_incursion', 'go_around', 'bird_strike'):
        closed = 600 if key == 'bird_strike' else 500
    if key == 'bird_strike':
        anchors = [(-8, 7), (-24, -12), (-21, 18)]
    if key in ('runway_incursion', 'go_around'):
        anchors = [(-6, 0), (-22, -14), (-22, 14)]
    if key == 'normal':
        anchors = [(-26, -18), (-19, 20), (-28, 5)]
    emergency = n - 1 if key in ('low_fuel', 'medical') else 0 if key in ('bird_strike', 'engine_failure') else None
    order = list(range(n))
    if emergency is not None:
        order.remove(emergency)
        order.insert(0, emergency)
    fcfs = key in ('low_fuel', 'medical', 'normal', 'high_density')
    for i, f in enumerate(a):
        z = 7000 if key == 'engine_failure' and i == 0 else 6000 + i * 1500
        baseline, eta = arrivals_route(anchors[i], z, i if fcfs else 0, PRIMARY)
        f.update(baseline=baseline, baseline_landing=eta, baseline_field='A',
                 earliest=arrivals_route(anchors[i], z, 0, airport)[1], altitude=z)
        if key == 'low_fuel' and i == emergency:
            f['deadline'] = f['earliest'] + 100
            f['fuel_pct'] = 12
            f['role'] = 'fuel emergency (MAYDAY FUEL)'
        if key == 'medical' and i == emergency:
            f['role'] = 'medical emergency (PAN PAN)'
        if key == 'engine_failure' and i == 0:
            f['role'] = 'engine failure (MAYDAY)'
        if key == 'bird_strike' and i == 0:
            f['role'] = 'bird strike, returning'

    accepted, slots = [], []
    for rank, i in enumerate(order):
        f = a[i]
        z = f['altitude']
        missed = i == 0 and key in ('runway_incursion', 'go_around', 'bird_strike')
        for loops in range(36):
            route, eta = arrivals_route(anchors[i], z, loops, airport, missed)
            if key == 'engine_failure' and i == 0:
                if loops:
                    break
                eta = GATE + z / 1000 * 60
                route = [point(anchors[i][0] - 1, anchors[i][1], z, 0), point(*anchors[i], z, GATE),
                         point(*airport, 0, eta), point(airport[0] + 0.25, airport[1] + 0.25, 0, eta + 45)]
            if field_id == 'A' and eta < closed:
                continue
            if slots and eta < max(slots) + 120:
                continue
            if any(interval_conflict(route, o['resolved']) is not None for o in accepted):
                continue
            f.update(resolved=route, resolved_landing=eta, resolved_field=field_id, slot=rank + 1, hold_loops=loops)
            slots.append(eta)
            accepted.append(f)
            break
        else:
            raise ValueError('No feasible arrival plan found within the planning horizon')
        where = 'Primary' if field_id == 'A' else 'Alternate'
        f['action'] = (f'Arrival {rank + 1}: ' + ('fly missed approach, then ' if missed else '') +
                       (f'hold {loops} circuit(s), then ' if loops else '') +
                       f'land at {where} at T+{eta / 60:.1f} min; vacate 45 s later')
        f['clearance'] = Clearance(f['name'], level=3000, runway='27')
        f['channel'] = 'voice' if (rank == 0 and emergency is not None) or missed or key in ('runway_incursion', 'go_around') else 'datalink'
        events += [{'t': round(eta, 2), 'message': f"{f['name']} touches down at {where}"},
                   {'t': round(eta + 45, 2), 'message': f"{f['name']} vacates the runway; arrival complete"}]

    if fcfs:
        # Feasible first-come-first-served comparator with the same checks and search budget.
        previous, slots = [], []
        for i, f in enumerate(a):
            for loops in range(36):
                route, eta = arrivals_route(anchors[i], f['altitude'], loops, airport)
                if slots and eta < max(slots) + 120:
                    continue
                if any(interval_conflict(route, o['baseline']) is not None for o in previous):
                    continue
                f.update(baseline=route, baseline_landing=eta, baseline_field=field_id)
                previous.append(f)
                slots.append(eta)
                break
            else:
                raise ValueError('FCFS comparator exceeded its search budget')

    if key == 'bird_strike':
        scene['objects'] = [{'kind': 'birds', 'x': -8, 'y': 7, 'clear_at': 450}]
        events += [{'t': 450, 'message': 'Wildlife team disperses the flock'}, {'t': 600, 'message': 'Runway inspection complete; Primary reopens'}]
    if key == 'runway_incursion':
        scene['objects'] = [{'kind': 'vehicle', 'x': PRIMARY[0], 'y': PRIMARY[1], 'clear_at': 400}]
        events += [{'t': 400, 'message': 'Vehicle leaves the runway'}, {'t': 500, 'message': 'Runway inspection complete; arrivals released'}]
    if key == 'go_around':
        scene['objects'] = [{'kind': 'preceding', 'x': PRIMARY[0], 'y': PRIMARY[1], 'clear_at': 460}]
        events.append({'t': 500, 'message': 'Preceding aircraft vacates; runway released'})
    if key in ('runway_closed', 'diversion'):
        scene['airports'][0]['closed'] = True
    if key == 'engine_failure':
        f = a[0]
        radius = f['altitude'] / 6076.12 * 17
        scene['zones'] = [{'kind': 'glide', 'x': anchors[0][0], 'y': anchors[0][1], 'radius': round(radius, 2)}]
        f['action'] = 'Engine-out diversion: Alternate is inside the assumed 17:1 glide envelope. ' + f['action']

    algorithm = ('Priority-aware runway scheduling: emergency first, then original order. Holding circuits are added until '
                 'each trajectory has no all-pairs separation breach and arrivals are at least 120 s apart.')
    if key == 'engine_failure':
        algorithm = ('Reachability: nearest open airport inside the 17:1 glide range from the current altitude, then a '
                     'conflict-free approach slot. Wind and type performance are not modelled.')
    if key in ('runway_closed', 'diversion'):
        algorithm = 'Closed runway removed from feasible destinations; every flight re-planned to Alternate with conflict-free slots.'
    baseline = ('First-come-first-served without emergency priority' if key in ('low_fuel', 'medical')
                else 'First-come-first-served, voice-only' if key in ('normal', 'high_density')
                else 'Uncoordinated requested arrivals')
    return {'scene': scene, 'events': events, 'algorithm': algorithm, 'baseline_label': baseline,
            'closed': closed, 'closed_field': 'A', 'anchors': anchors, 'emergency': emergency}


def _readback(key, a):
    """readback_error: verifier catches FL140 read back for a cleared FL120."""
    scene = {'airports': [], 'zones': [], 'objects': []}
    ac, opposite, trail = a
    ac['role'] = 'cleared FL120, reads back FL140'
    ac['baseline'] = crossing_route((-26, 0), (26, 0), 10000, 720, 14000, at=70)
    ac['resolved'] = crossing_route((-26, 0), (26, 0), 10000, 720, 12000, at=70)
    opposite['baseline'] = opposite['resolved'] = [point(26, 1, 14000, 0), point(-26, 1, 14000, 720)]
    trail['baseline'] = trail['resolved'] = [point(-36, -1, 10000, 0), point(16, -1, 10000, 720)]
    ac['clearance'] = Clearance(ac['name'], level=12000)
    ac['channel'] = 'voice'
    ac['action'] = 'Climb FL120 (wrong readback "FL140" detected and corrected before the climb)'
    opposite['action'] = 'Maintain FL140'
    trail['action'] = 'Maintain FL100'
    wrong = phraseology(Clearance(ac['name'], level=14000), 10000).split(', ', 1)[1] + ', ' + telephony(ac['name'])
    events = [{'t': 62, 'message': f'Readback heard: "{wrong}"'},
              {'t': 64, 'message': 'Verifier: MISMATCH level FL140 vs cleared FL120'},
              {'t': 68, 'message': f'Controller: "{telephony(ac["name"])}, negative, climb FL120"'}]
    return {'scene': scene, 'events': events, 'baseline_label': 'Voice readback, error not caught by hearback',
            'algorithm': 'Readback verification: the pilot transcript is parsed into fields and compared with the structured clearance; a mismatch is flagged before the climb starts.',
            'wrong_readback': wrong}


def _callsign(key, a):
    """callsign_confusion: the similar callsign takes an instruction meant for another aircraft."""
    scene = {'airports': [], 'zones': [], 'objects': []}
    target, similar, crossing = a
    target['baseline'] = [point(-24, -8, 13000, 0), point(24, -8, 13000, 720)]
    target['resolved'] = crossing_route((-24, -8), (24, -8), 13000, 720, 10000, at=60)
    similar['baseline'] = crossing_route((-24, 6), (24, 6), 11000, 720, 10000, at=60)
    similar['resolved'] = [point(-24, 6, 11000, 0), point(24, 6, 11000, 720)]
    crossing['baseline'] = crossing['resolved'] = [point(0, 30, 10000, 0), point(0, -30, 10000, 900)]
    target['clearance'] = Clearance(target['name'], level=10000)
    target['channel'] = 'datalink'
    target['action'] = 'Descend FL100 (sent by datalink to the logged-on aircraft; similar callsign warned)'
    target['role'] = 'intended receiver'
    similar['role'] = 'similar callsign on frequency'
    similar['action'] = 'Maintain FL110 (confusion alert shown on its label)'
    crossing['action'] = 'Maintain FL100'
    wrong = 'descend flight level one zero zero, ' + telephony(similar['name'])
    events = [{'t': 8, 'message': f"Callsign similarity alert: {target['name']} / {similar['name']} ({callsign_similarity(target['name'], similar['name'])[1]})"}]
    return {'scene': scene, 'events': events, 'baseline_label': 'Voice instruction taken by the similar callsign',
            'algorithm': 'Callsign-similarity scoring of every pair on frequency, logon-addressed datalink for the instruction, and WRONG_AIRCRAFT detection if another callsign reads it back.',
            'wrong_readback': wrong, 'extra_checks': [{'label': 'Instruction executed by the wrong aircraft', 'before': 1, 'after': 0, 'unit': 'flights'}]}


def _level_bust(key, a):
    """level_bust: cleared-level adherence monitoring catches an overshoot within seconds."""
    scene = {'airports': [], 'zones': [], 'objects': []}
    climber, opposite, other = a
    climber['baseline'] = [point(-26, 0, 9000, 0), point(-26 + 52 * 60 / 720, 0, 9000, 60),
                           point(-26 + 52 * 220 / 720, 0, 12000, 220), point(26, 0, 12000, 720)]
    x = lambda t: -26 + 52 * t / 720
    climber['resolved'] = [point(-26, 0, 9000, 0), point(x(60), 0, 9000, 60), point(x(140), 0, 11000, 140),
                           point(x(152), 0, 11300, 152), point(x(170), 0, 11450, 170), point(x(200), 0, 11000, 200),
                           point(26, 0, 11000, 720)]
    climber['baseline'][2:2] = [point(x(140), 0, 11000, 140), point(x(152), 0, 11300, 152)]
    opposite['baseline'] = opposite['resolved'] = [point(26, 1, 12000, 0), point(-26, 1, 12000, 720)]
    other['baseline'] = other['resolved'] = [point(-5, -26, 15000, 0), point(5, 26, 15000, 720)]
    climber['clearance'] = Clearance(climber['name'], level=11000)
    climber['channel'] = 'voice'
    climber['role'] = 'cleared FL110, overshoots'
    climber['action'] = 'Stop climb, descend immediately FL110 (CLAM alert at FL113)'
    opposite['action'] = 'Maintain FL120; traffic information passed'
    other['action'] = 'Maintain FL150'
    events = [{'t': 152, 'message': 'CLAM: passing FL113, 300 ft above cleared FL110'},
              {'t': 160, 'message': f'Controller: "{telephony(climber["name"])}, stop climb, descend immediately FL110"'},
              {'t': 200, 'message': 'Aircraft back at FL110; conformance restored'}]
    return {'scene': scene, 'events': events, 'baseline_label': 'Cleared level unknown to the system; STCA warns at 2 minutes',
            'algorithm': 'Cleared-level adherence monitoring (CLAM): the digital clearance record gives the cleared level, so a 300 ft deviation alerts at once instead of when traffic is close.'}


def _emergency_descent(key, a):
    """emergency_descent: fixed emergency path, greedy avoidance for traffic below."""
    scene = {'airports': [], 'zones': [], 'objects': []}
    em = a[0]
    em['role'] = 'emergency descent (MAYDAY)'
    speed, rate = 430, 6000                       # high-speed descent, ft/min
    t_level = GATE + (35000 - 10000) / rate * 60  # reaches FL100
    run = speed * (t_level - GATE) / 3600         # NM flown during the descent
    start = (-26 + speed * GATE / 3600, 0)
    em['baseline'] = [point(-26, 0, 35000, 0), point(*start, 35000, GATE), point(start[0] + run, 0, 10000, t_level),
                      point(26, 0, 10000, t_level + (26 - start[0] - run) / 300 * 3600)]
    # SkyControl plan: 45-degree right turn off the airway during the descent, published to all traffic.
    off = (start[0] + run * math.sin(math.radians(135)), start[1] + run * math.cos(math.radians(135)))
    em['resolved'] = [point(-26, 0, 35000, 0), point(*start, 35000, GATE), point(*off, 10000, t_level),
                      point(26, off[1], 10000, t_level + (26 - off[0]) / 300 * 3600)]
    em['action'] = 'Descend to FL100 with a 45-degree right turn off the airway; squawk 7700'
    traffic = [((-20.5, 0.5), (25.5, 0.5), 30000, 'same airway ahead'),
               ((-2.7, -0.5), (-48.7, -0.5), 24000, 'opposite direction'),
               ((20, off[1]), (-26, off[1]), 10000, 'crossing at the descent level')]
    accepted = [em]
    for f, (s, e, z, role) in zip(a[1:], traffic):
        f['role'] = role
        f['baseline'] = [point(*s, z, 0), point(*e, z, 720)]
        options = [(None, 0), (z + 2000, 0), (z - 2000, 0), (None, 30), (None, -30), (z + 4000, 0)]
        for level, heading_offset in options:
            h = math.atan2(e[0] - s[0], e[1] - s[1]) + math.radians(heading_offset)
            if heading_offset:
                mid_t = GATE + 40
                p0 = pos(f['baseline'], mid_t)
                end = (p0['x'] + 60 * math.sin(h), p0['y'] + 60 * math.cos(h))
                cand = [point(*s, z, 0), point(p0['x'], p0['y'], z, mid_t), point(*end, z, mid_t + 60 / 420 * 3600)]
                text = f'Turn {"right" if heading_offset > 0 else "left"} {abs(heading_offset)} degrees for emergency traffic'
            elif level:
                cand = crossing_route(s, e, z, 720, level, GATE + 10, rate_fpm=2000)
                text = f'{"Climb" if level > z else "Descend"} FL{level // 100} for emergency traffic'
            else:
                cand = f['baseline']
                text = f'Maintain FL{z // 100}; emergency traffic passes clear'
            if not any(interval_conflict(cand, o['resolved']) is not None for o in accepted):
                f['resolved'] = cand
                f['action'] = text
                if cand is not f['baseline']:
                    f['clearance'] = Clearance(f['name'], level=level) if level else \
                        Clearance(f['name'], heading=int(round(math.degrees(h) % 360 / 5) * 5) or 360)
                    f['channel'] = 'voice'
                accepted.append(f)
                break
        else:
            raise ValueError('No avoidance option found for emergency descent')
    mid = ((start[0] + off[0]) / 2, (start[1] + off[1]) / 2)
    scene['zones'] = [{'kind': 'protected', 'x': round(mid[0], 2), 'y': round(mid[1], 2), 'radius': 8, 'clear_at': round(t_level + 30)}]
    events = [{'t': 5, 'message': f"{em['name']}: MAYDAY, emergency descent (cabin pressure)"},
              {'t': round(t_level), 'message': f"{em['name']} levels at FL100 clear of the airway"}]
    return {'scene': scene, 'events': events, 'baseline_label': 'Crew descends straight ahead on the airway; traffic moved reactively',
            'algorithm': ('Emergency path fixed first (45-degree turn off the airway, 6,000 ft/min). Each aircraft then tries '
                          'maintain, +/-2,000 ft and +/-30 degree turns, accepting the first option with no conflict '
                          'against every accepted route.')}


def _ghost(key, a):
    """ghost_target: a duplicate target triggers a false alert and a needless climb in the baseline."""
    scene = {'airports': [], 'zones': [], 'objects': []}
    real, above, other = a
    real['baseline'] = crossing_route((-26, 0), (26, 0), 20000, 720, 21000, at=GATE + 10)
    real['resolved'] = [point(-26, 0, 20000, 0), point(26, 0, 20000, 720)]
    above['baseline'] = above['resolved'] = [point(20, -20, 21000, 0), point(-20, 20, 21000, 720)]
    other['baseline'] = other['resolved'] = [point(-20, -24, 17000, 0), point(20, 24, 17000, 720)]
    real['action'] = 'Maintain FL200: the alert partner is a duplicate of this aircraft and is suppressed'
    above['action'] = 'Maintain FL210'
    other['action'] = 'Maintain FL170'
    ghost_icao = 'duplicate (1-bit address error)'
    scene['objects'] = [{'kind': 'ghost', 'follows': real['name'], 'dx': 0.3, 'dy': 0.2, 'label': '(no callsign)', 'clear_at': 400}]
    events = [{'t': 3, 'message': f"Naive alert: {real['name']} vs unidentified target 0.4 NM, same level"},
              {'t': 6, 'message': f"Integrity monitor: unidentified target is a duplicate of {real['name']} ({ghost_icao}); alert suppressed"}]
    return {'scene': scene, 'events': events, 'baseline_label': 'Every target trusted; avoidance issued for the false alert',
            'algorithm': 'Surveillance integrity monitor: co-located targets with 24-bit addresses differing by <=2 bits (or one anonymous) are merged; the same rules find duplicate pairs in the real London recording (see Statistical analysis).',
            'extra_checks': [{'label': 'Unnecessary avoidance instructions', 'before': 1, 'after': 0, 'unit': 'instructions'}]}


def _ai_disagreement(key, a):
    """ai_disagreement: the learned model is confident but wrong; the safety rule wins."""
    scene = {'airports': [], 'zones': [], 'objects': []}
    own, turner, other = a
    turner['baseline'] = turner['resolved'] = [point(12, -24, 16000, 0), point(0, 0, 16000, 360), point(-12, 24, 16000, 720)]
    own['baseline'] = [point(-26, 0, 16000, 0), point(26, 0, 16000, 720)]
    own['resolved'] = crossing_route((-26, 0), (26, 0), 16000, 720, 18000, at=GATE + 10)
    other['baseline'] = other['resolved'] = [point(26, 12, 20000, 0), point(-26, 12, 20000, 720)]
    own['clearance'] = Clearance(own['name'], level=18000)
    own['channel'] = 'voice'
    own['action'] = 'Climb FL180 (conservative plan chosen by the controller in MANUAL mode)'
    turner['role'] = 'manoeuvring; model expected a turn away'
    turner['action'] = 'Maintain FL160'
    other['action'] = 'Maintain FL200'
    scene['objects'] = [{'kind': 'prediction', 'flight': turner['name'], 'path': [[12, -24], [4, -8], [10, 4], [20, 10]], 'label': 'learned prediction (turn away)'}]
    events = [{'t': 4, 'message': 'Learned predictor: 0.18 conflict probability (expects turn away)'},
              {'t': 5, 'message': 'Safety rule (straight line): conflict in 5.8 min at the crossing'},
              {'t': 6, 'message': 'Context switch to MANUAL: model and rule disagree'},
              {'t': 360, 'message': f"{turner['name']} did not turn: the learned prediction was wrong; separation kept by the conservative plan"}]
    return {'scene': scene, 'events': events, 'baseline_label': 'Trust the learned model (automation bias)',
            'algorithm': 'Disagreement detector: when the learned prediction and the deterministic straight-line rule disagree, automation drops to MANUAL and the conservative (rule-based) resolution is offered.'}


BUILDERS = {**{k: _crossing for k in ('collision', 'lost_comms')},
            **{k: _hazard for k in ('weather', 'sensor_dropout', 'hijack')},
            **{k: _arrivals for k in ARRIVAL_SCENARIOS},
            'readback_error': _readback, 'callsign_confusion': _callsign, 'level_bust': _level_bust,
            'emergency_descent': _emergency_descent, 'ghost_target': _ghost, 'ai_disagreement': _ai_disagreement}


# ---------------------------------------------------------------------------
# Metrics, steps and assembly
# ---------------------------------------------------------------------------

def metrics(a, key, closed_until=0, closed_field='A', obstacle=None):
    conf = all_conflicts(a, key)
    landings, overlap, hazards, late = [], 0, 0, 0
    for f in a:
        land, fld = f.get(key + '_landing'), f.get(key + '_field')
        if land is not None:
            overlap += sum(1 for o in landings if fld == o['field'] and abs(land - o['t']) < 120 - 1e-6)
            landings.append({'t': land, 'field': fld})
            if fld == closed_field and land < closed_until:
                hazards += 1
            if f.get('deadline') and land > f['deadline']:
                late += 1
        if obstacle and f.get('role', '').startswith('security') is False:
            centre, radius = (obstacle['x'], obstacle['y']), obstacle['radius']
            if any(segment_distance((p['x'], p['y']), (q['x'], q['y']), centre) < radius - 0.01 for p, q in zip(f[key], f[key][1:])):
                hazards += 1
    delays = [max(0, f.get(key + '_landing', 0) - f.get('earliest', 0)) for f in a if f.get(key + '_landing') is not None]
    return {'conflict_pairs': len(conf), 'conflicts': conf, 'runway_conflicts': overlap, 'hazard_breaches': hazards,
            'deadline_misses': late, 'landings': len(landings),
            'mean_delay_seconds': round(sum(delays) / len(delays), 1) if delays else 0,
            'total_route_nm': round(sum(route_length(f[key]) for f in a), 1)}


def pick_names(flights, wanted, key):
    labels = []
    for f in flights:
        label = (f.get('callsign') or f.get('flight_number') or '').strip()
        if label and label not in labels:
            labels.append(label)
    if len(labels) < wanted:
        raise ValueError(f'{key} needs {wanted} named flights; this source has {len(labels)}.')
    if key == 'callsign_confusion':
        best = None
        for i, x in enumerate(labels):
            for y in labels[i + 1:]:
                score, _ = callsign_similarity(x, y)
                if score >= 0.9 and (best is None or score > best[0]):
                    best = (score, x, y)
        if best:
            rest = [n for n in labels if n not in best[1:]]
            return [best[1], best[2]] + rest[:wanted - 2]
        base = labels[0]
        twin = base[:-1] + ('7' if base[-1] != '7' else '8')
        return [base, twin] + labels[1:wanted - 1]
    offset = CATALOG_ORDER.index(key) * 3 % len(labels)
    return (labels[offset:] + labels[:offset])[:wanted]


def _messages(a, plan):
    """Clearance log with phraseology, channel and readback verification for voice."""
    out = []
    on_freq = [f['name'] for f in a]
    for f in a:
        c = f.get('clearance')
        if not c:
            continue
        text = phraseology(c, f['baseline'][0]['altitude_ft'])
        msg = {'to': f['name'], 'channel': f['channel'], 'clearance': c.fields(), 'phraseology': text}
        if f['channel'] == 'voice':
            readback = text.split(', ', 1)[1] + ', ' + telephony(c.callsign) if ', ' in text else text
            if plan.get('wrong_readback') and f is a[0]:
                msg['first_readback'] = plan['wrong_readback']
                msg['first_verification'] = verify_readback(c, plan['wrong_readback'], on_freq)
            msg['readback'] = readback
            msg['verification'] = verify_readback(c, readback, on_freq)
        else:
            msg['readback'] = 'WILCO (datalink)'
            msg['verification'] = {'verdict': 'CORRECT', 'advice': 'Datalink acknowledgement from the logged-on aircraft.'}
        if plan.get('wrong_readback') and f is a[0] and f['channel'] == 'datalink':
            msg['blocked_voice_readback'] = plan['wrong_readback']
            msg['blocked_verification'] = verify_readback(c, plan['wrong_readback'], on_freq)
        out.append(msg)
    return out


def _context_log(key, spec, level, reasons):
    log = [{'t': 6, 'level': level, 'reasons': reasons}]
    if key == 'sensor_dropout':
        log = [{'t': 6, 'level': 'CONSENT', 'reasons': ['Routine traffic before the dropout.']},
               {'t': 10, 'level': 'MANUAL', 'reasons': reasons},
               {'t': 600, 'level': 'CONSENT', 'reasons': ['Surveillance restored; integrity back above 90%.']}]
    if key == 'ai_disagreement':
        log = [{'t': 3, 'level': 'CONSENT', 'reasons': ['Learned predictor reports low risk with 82% confidence.']},
               {'t': 6, 'level': 'MANUAL', 'reasons': reasons}]
    if key == 'ghost_target':
        log = [{'t': 3, 'level': 'ADVISORY', 'reasons': ['Conflict alert raised; surveillance integrity check running.']},
               {'t': 6, 'level': level, 'reasons': reasons + ['Duplicate confirmed and merged; data quality restored to 95%.']}]
    return log


def _steps(key, spec, d, plan, level, approver, reasons):
    """The ten-phase handling pipeline shown in the Scenario Lab."""
    a = d['aircraft']
    changed = [f for f in a if f.get('clearance')]
    before, after = d['before'], d['after']
    detect_text = {
        'collision': 'Medium-term probe (5-minute look-ahead, intent-aware) predicts converging tracks before the 2-minute safety net would alert.',
        'readback_error': 'Readback verifier parses the pilot transcript and compares every field with the structured clearance.',
        'callsign_confusion': 'Callsign-similarity monitor scores every pair on the frequency.',
        'level_bust': 'Cleared-level adherence monitor compares Mode S altitude with the digital clearance record.',
        'ghost_target': 'Naive alert between a real aircraft and an unidentified target; integrity monitor checks address bit-errors and co-location.',
        'sensor_dropout': 'Track-integrity monitor: no position update for 60 s; the track is coasted with a growing uncertainty circle.',
        'ai_disagreement': 'Learned trajectory predictor and straight-line safety rule are both evaluated for every pair.',
        'emergency_descent': 'Anomaly detector flags a 6,000 ft/min descent; MAYDAY confirmed by the crew.',
        'lost_comms': 'Communication monitor: no acknowledgement within 30 s and squawk 7600.',
        'hijack': 'Squawk 7500 received; security workflow opened.',
    }.get(key, f'{spec.problem}. Detected by the {spec.category.lower()} monitor.')
    level_text = f"{level}: {automation.DESCRIPTIONS[level]}"
    voice = [m for m in d['messages'] if m['channel'] == 'voice']
    datalink = [m for m in d['messages'] if m['channel'] == 'datalink']
    communicate = f'{len(voice)} voice instruction(s) with automatic readback verification, {len(datalink)} by datalink.'
    if key == 'readback_error':
        communicate = 'Clearance FL120 by voice. Readback "FL140" flagged MISMATCH by the verifier within 2 s; correction issued and the second readback verified CORRECT.'
    if key == 'callsign_confusion':
        communicate = f"Descent sent by datalink to {a[0]['name']} (logon-addressed). If {a[1]['name']} answers by voice the verifier returns WRONG_AIRCRAFT."
    monitor = 'Conformance monitoring of every route; events logged as they occur.'
    if key == 'level_bust':
        monitor = 'CLAM watches the cleared level continuously; the deviation is caught at 300 ft, not at 2 minutes to impact.'
    if key in ARRIVAL_SCENARIOS:
        monitor = 'Arrival sequence monitored: landing order, 120 s runway spacing and closure times.'
    steps = [
        {'t': 0, 'phase': 'DETECT', 'actor': 'SkyControl', 'title': 'Situation detected', 'detail': detect_text},
        {'t': 3, 'phase': 'ASSESS', 'actor': 'SkyControl', 'title': f'Severity {spec.severity}',
         'detail': f"{len(a)} aircraft involved. Before mitigation: {before['conflict_pairs']} conflict pair(s), "
                   f"{before['runway_conflicts']} runway conflict(s), {before['hazard_breaches']} hazard breach(es), "
                   f"{before['deadline_misses']} deadline miss(es)."},
        {'t': 6, 'phase': 'CONTEXT SWITCH', 'actor': 'Automation policy', 'title': level_text, 'detail': ' '.join(reasons)},
        {'t': 9, 'phase': 'PLAN', 'actor': 'Planner', 'title': f'{len(changed)} instruction(s) planned', 'detail': d['algorithm']},
        {'t': 12, 'phase': 'VERIFY', 'actor': 'Safety checker', 'title': 'Plan verified' if d['plan_valid'] else 'Plan fails checks',
         'detail': f"After mitigation: {after['conflict_pairs']} conflict pairs, {after['runway_conflicts']} runway conflicts, "
                   f"{after['hazard_breaches']} hazard breaches, {after['deadline_misses']} deadline misses (exact all-pairs segment test, 5 NM / 1,000 ft)."},
        {'t': GATE, 'phase': 'AUTHORISE', 'actor': (approver or 'none').capitalize(),
         'title': 'No approval needed (AUTO)' if not approver else f'Waiting for {approver} approval',
         'detail': 'Routine plan executed automatically; the controller can veto.' if not approver else
                   f'The exercise pauses at T+{GATE}s until a {approver} approves, rejects or overrides with a reason.'},
        {'t': GATE + 2, 'phase': 'COMMUNICATE', 'actor': 'Controller + datalink', 'title': 'Instructions delivered', 'detail': communicate},
        {'t': GATE + 10, 'phase': 'EXECUTE', 'actor': 'Aircraft', 'title': 'Manoeuvres under way',
         'detail': '; '.join(f"{f['name']}: {f['action']}" for f in a[:4]) + (' ...' if len(a) > 4 else '')},
        {'t': max(GATE + 30, d['duration'] * 0.5), 'phase': 'MONITOR', 'actor': 'SkyControl', 'title': 'Conformance monitoring', 'detail': monitor},
        {'t': d['duration'], 'phase': 'CLOSE', 'actor': 'SkyControl', 'title': 'Outcome recorded',
         'detail': 'All aircraft reached their terminal state; alert resolved and audit trail written.'},
    ]
    return steps


def build(key, flights, source):
    if key not in SPECS:
        raise ValueError('Unknown scenario')
    spec = SPECS[key]
    names = pick_names(flights, spec.aircraft, key)
    a = _aircraft(names, source)
    plan = BUILDERS[key](key, a)
    for f in a:
        f.setdefault('baseline_field', None)
    closed = plan.get('closed', 0)
    obstacle = plan.get('obstacle')
    before = metrics(a, 'baseline', closed, plan.get('closed_field', 'A'), obstacle)
    after = metrics(a, 'resolved', closed, plan.get('closed_field', 'A'), obstacle)
    if key == 'engine_failure':
        radius = a[0]['altitude'] / 6076.12 * 17
        anchor = plan['anchors'][0]
        before['hazard_breaches'] += int(dist(anchor, PRIMARY) > radius)
    checks = [
        {'label': 'Aircraft conflicts', 'before': before['conflict_pairs'], 'after': after['conflict_pairs'], 'unit': 'pairs'},
        {'label': 'Runway conflicts', 'before': before['runway_conflicts'], 'after': after['runway_conflicts'], 'unit': 'pairs'},
        {'label': 'Hazard / closure violations', 'before': before['hazard_breaches'], 'after': after['hazard_breaches'], 'unit': 'flights'},
        {'label': 'Fuel deadline misses', 'before': before['deadline_misses'], 'after': after['deadline_misses'], 'unit': 'flights'},
    ] + plan.get('extra_checks', [])
    valid = not any(after[k] for k in ('conflict_pairs', 'runway_conflicts', 'hazard_breaches', 'deadline_misses'))
    ctx = {'severity': spec.severity, **spec.context}
    level, approver, reasons = automation.decide(**ctx)
    duration = math.ceil(max(f['resolved'][-1]['t'] for f in a)) + 5
    d = {
        'engine_version': 7, 'scenario': key, 'title': spec.title, 'category': spec.category, 'severity': spec.severity,
        'aircraft': a, 'scene': plan['scene'], 'problem': spec.problem, 'goal': spec.goal, 'gap': spec.gap,
        'algorithm': plan['algorithm'], 'baseline_label': plan['baseline_label'],
        'before': before, 'after': after, 'checks': checks, 'plan_valid': valid, 'source': source,
        'time': 0, 'duration': duration, 'playing': True, 'speed': 16, 'gate': GATE,
        'automation_level': level, 'approver': approver,
        'approval': 'Not required' if approver is None else 'Pending',
        'events': [{'t': 0, 'message': spec.problem}], 'planned_events': sorted(plan['events'], key=lambda e: e['t']),
        'outcome': 'Awaiting execution',
        'note': 'Constructed exercise using recorded flight identities. Results apply to this simplified model, not to operational ATC.',
    }
    for f in a:
        if f.get('clearance') is not None:
            f['clearance_text'] = phraseology(f['clearance'], f['baseline'][0]['altitude_ft'])
    d['messages'] = _messages(a, plan)
    for f in a:
        f['clearance'] = f['clearance'].fields() if f.get('clearance') is not None else None
    d['context_log'] = _context_log(key, spec, level, reasons)
    d['steps'] = _steps(key, spec, d, plan, level, approver, reasons)
    instructions = sum(1 for f in a if f.get('clearance'))
    d['workflow'] = workflow.compare(spec.profile, instructions, approver is not None)
    return d


def catalog():
    return [{'id': k, 'title': s.title, 'category': s.category, 'severity': s.severity, 'aircraft_count': s.aircraft,
             'description': s.problem, 'gap': s.gap} for k, s in SPECS.items()]


def benchmark(roster=None):
    """Run every scenario once on fixed identities: before/after checks and workflow totals."""
    roster = roster or [{'callsign': c} for c in ('BAW425', 'BAW725', 'EZY12AB', 'RYR52ZT', 'KLM88U', 'DLH4PK',
                                                  'SHT13H', 'EIN38Y', 'CFE844', 'EXS32K', 'SWR9AM')]
    rows = []
    for key in SPECS:
        d = build(key, roster, 'Benchmark identities; constructed trajectories')
        rows.append({'scenario': key, 'title': d['title'], 'category': d['category'], 'severity': d['severity'],
                     'aircraft': len(d['aircraft']), 'baseline_label': d['baseline_label'],
                     'before': {k: v for k, v in d['before'].items() if k != 'conflicts'},
                     'after': {k: v for k, v in d['after'].items() if k != 'conflicts'},
                     'checks': d['checks'], 'valid': d['plan_valid'], 'automation_level': d['automation_level'],
                     'workflow': {k: d['workflow'][k] for k in ('time_saving_s', 'time_saving_pct', 'transmission_reduction_pct', 'instructions')} |
                                 {'baseline_time_s': d['workflow']['baseline']['time_to_all_instructions_s'],
                                  'hybrid_time_s': d['workflow']['hybrid']['time_to_all_instructions_s'],
                                  'baseline_transmissions': d['workflow']['baseline']['radio_transmissions'],
                                  'hybrid_transmissions': d['workflow']['hybrid']['radio_transmissions'],
                                  'baseline_actions': d['workflow']['baseline']['controller_actions'],
                                  'hybrid_actions': d['workflow']['hybrid']['controller_actions']}})
    return rows
