"""Trajectory geometry for the scenario planner.

A route is a list of 4D points {x, y, altitude_ft, t} in a local NM frame,
flown with linear interpolation between points. Conflict checks are exact for
piecewise-linear motion (no sampling), so a verified plan has no separation
breach anywhere along its routes.
"""
from __future__ import annotations

import heapq
import math
from itertools import combinations

SEPARATION_NM = 5.0
SEPARATION_FT = 1000.0


def point(x, y, z, t):
    return {'x': round(x, 6), 'y': round(y, 6), 'altitude_ft': round(z, 2), 't': round(t, 4)}


def pos(route, t):
    """Interpolated state on a route at time t (holds the final point after arrival)."""
    for a, b in zip(route, route[1:]):
        if t <= b['t']:
            f = max(0.0, min(1.0, (t - a['t']) / (b['t'] - a['t'])))
            state = {k: a[k] + (b[k] - a[k]) * f for k in ('x', 'y', 'altitude_ft')}
            state['heading_deg'] = math.degrees(math.atan2(b['x'] - a['x'], b['y'] - a['y'])) % 360
            state['speed_kt'] = math.hypot(b['x'] - a['x'], b['y'] - a['y']) / (b['t'] - a['t']) * 3600
            state['vertical_rate_fpm'] = (b['altitude_ft'] - a['altitude_ft']) / (b['t'] - a['t']) * 60
            return state
    last = route[-1]
    return {'x': last['x'], 'y': last['y'], 'altitude_ft': last['altitude_ft'], 'heading_deg': 0.0,
            'speed_kt': 0.0, 'vertical_rate_fpm': 0.0}


def interval_conflict(route_a, route_b, h=SEPARATION_NM, v=SEPARATION_FT):
    """First time (s) at which two routes are inside h NM and v ft of each other, else None.

    Each pair of overlapping segments has constant relative velocity, so the
    horizontal condition is a quadratic and the vertical one is linear in time.
    Aircraft on the ground (altitude 0 on both ends of a segment) are ignored.
    """
    for a, b in zip(route_a, route_a[1:]):
        for c, d in zip(route_b, route_b[1:]):
            lo, hi = max(a['t'], c['t']), min(b['t'], d['t'])
            if hi - lo < 1e-7:
                continue
            if a['altitude_ft'] == b['altitude_ft'] == 0 or c['altitude_ft'] == d['altitude_ft'] == 0:
                continue
            pa, pb = pos([a, b], lo), pos([c, d], lo)

            def vel(p, q, k):
                return (q[k] - p[k]) / (q['t'] - p['t'])
            rx, ry = pa['x'] - pb['x'], pa['y'] - pb['y']
            rz = pa['altitude_ft'] - pb['altitude_ft']
            vx, vy = vel(a, b, 'x') - vel(c, d, 'x'), vel(a, b, 'y') - vel(c, d, 'y')
            vz = vel(a, b, 'altitude_ft') - vel(c, d, 'altitude_ft')
            A, B, C = vx * vx + vy * vy, 2 * (rx * vx + ry * vy), rx * rx + ry * ry - h * h
            left, right = 0.0, hi - lo
            if A < 1e-12:
                if C >= -1e-8:
                    continue
            else:
                disc = B * B - 4 * A * C
                if disc <= 0:
                    continue
                left = max(left, (-B - math.sqrt(disc)) / (2 * A))
                right = min(right, (-B + math.sqrt(disc)) / (2 * A))
            if abs(vz) < 1e-12:
                if abs(rz) >= v - 1e-7:
                    continue
            else:
                z1, z2 = (-v - rz) / vz, (v - rz) / vz
                left, right = max(left, min(z1, z2)), min(right, max(z1, z2))
            if right - left > 1e-6:
                return round(lo + max(0.0, left), 2)
    return None


def all_conflicts(aircraft, key):
    out = []
    for a, b in combinations(aircraft, 2):
        at = interval_conflict(a[key], b[key])
        if at is not None:
            out.append({'a': a['name'], 'b': b['name'], 'at': at})
    return out


def min_separation(route_a, route_b, step=2.0):
    """Sampled minimum horizontal distance (NM) while vertically within 1,000 ft (for reporting)."""
    t0 = max(route_a[0]['t'], route_b[0]['t'])
    t1 = min(route_a[-1]['t'], route_b[-1]['t'])
    best = math.inf
    t = t0
    while t <= t1:
        p, q = pos(route_a, t), pos(route_b, t)
        if abs(p['altitude_ft'] - q['altitude_ft']) < SEPARATION_FT and p['altitude_ft'] > 0 and q['altitude_ft'] > 0:
            best = min(best, math.hypot(p['x'] - q['x'], p['y'] - q['y']))
        t += step
    return None if best == math.inf else round(best, 2)


def dist(a, b):
    return math.hypot(a[0] - b[0], a[1] - b[1])


def segment_distance(a, b, c):
    """Distance from point c to segment ab."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    length = dx * dx + dy * dy
    f = max(0.0, min(1.0, ((c[0] - a[0]) * dx + (c[1] - a[1]) * dy) / length)) if length else 0.0
    return dist((a[0] + f * dx, a[1] + f * dy), c)


def avoid(start, end, obstacle, margin=2.0, nodes_on_ring=16):
    """Shortest route around a circular hazard: Dijkstra on a visibility graph.

    Candidate nodes lie on a ring (radius + margin) around the hazard; an edge
    exists when its segment keeps at least radius + 0.5 NM from the centre.
    """
    cx, cy, r = obstacle
    ring = [(cx + (r + margin) * math.cos(i * 2 * math.pi / nodes_on_ring),
             cy + (r + margin) * math.sin(i * 2 * math.pi / nodes_on_ring)) for i in range(nodes_on_ring)]
    nodes = [start, end] + ring
    graph = [[] for _ in nodes]
    for i, j in combinations(range(len(nodes)), 2):
        if segment_distance(nodes[i], nodes[j], (cx, cy)) >= r + 0.5:
            cost = dist(nodes[i], nodes[j])
            graph[i].append((j, cost))
            graph[j].append((i, cost))
    heap, seen = [(0.0, 0, [])], set()
    while heap:
        cost, i, path = heapq.heappop(heap)
        if i in seen:
            continue
        if i == 1:
            return [nodes[k] for k in path + [1]]
        seen.add(i)
        for j, c in graph[i]:
            if j not in seen:
                heapq.heappush(heap, (cost + c, j, path + [i]))
    raise ValueError('No hazard-free route exists')


def flying_route(coords, z, speed=210, start=20):
    p = [point(*coords[0], z, start)]
    for x, y in coords[1:]:
        prev = p[-1]
        t = prev['t'] + dist((prev['x'], prev['y']), (x, y)) / speed * 3600
        p.append(point(x, y, z, t))
    return p


def route_length(route):
    return sum(dist((p['x'], p['y']), (q['x'], q['y'])) for p, q in zip(route, route[1:]))
