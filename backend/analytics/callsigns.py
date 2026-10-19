"""Similar callsigns sharing airspace in the real recording.

Aircraft within 40 NM and 10,000 ft of each other are treated as likely to be
on the same sector frequency. Pairs with a similarity score of 0.7 or more
(see core.comms.callsign_similarity) are reported with how long they were
co-present. Today such pairs are usually caught by controller vigilance and
post-event reporting; SkyControl flags them live.
"""
from __future__ import annotations

from collections import defaultdict

import numpy as np

from ..core.comms import callsign_similarity
from .recording import Recording

SECTOR_NM = 40
SECTOR_FT = 10000
THRESHOLD = 0.7


def analyse(rec: Recording, duplicates=()):
    air = rec.airborne & ~np.isin(rec.ac, list(duplicates))
    pairs = defaultdict(lambda: {'frames': 0, 'min_nm': 1e9, 'first': None, 'last': None})
    involved_per_frame = []
    for ts, idx in rec.frame_index.items():
        idx = idx[air[idx]]
        names = [rec.obs_callsign[i] for i in idx]
        groups = defaultdict(list)
        for k, cs in enumerate(names):
            if len(cs) > 3:
                groups[cs[:3]].append(k)
        involved = set()
        for members in groups.values():
            for p in range(len(members)):
                for q in range(p + 1, len(members)):
                    i, j = idx[members[p]], idx[members[q]]
                    score, reason = callsign_similarity(names[members[p]], names[members[q]])
                    if score < THRESHOLD:
                        continue
                    d = float(np.hypot(rec.x[i] - rec.x[j], rec.y[i] - rec.y[j]))
                    if d > SECTOR_NM or abs(rec.alt[i] - rec.alt[j]) > SECTOR_FT:
                        continue
                    key = tuple(sorted((names[members[p]], names[members[q]])))
                    rec_pair = pairs[key]
                    rec_pair.update(score=score, reason=reason)
                    rec_pair['frames'] += 1
                    rec_pair['min_nm'] = min(rec_pair['min_nm'], d)
                    rec_pair['first'] = rec_pair['first'] or int(ts)
                    rec_pair['last'] = int(ts)
                    involved.update((key[0], key[1]))
        involved_per_frame.append(len(involved))
    rows = [{'a': a, 'b': b, 'score': p['score'], 'reason': p['reason'], 'frames': p['frames'],
             'co_present_min': round((p['last'] - p['first']) / 60, 1), 'closest_nm': round(p['min_nm'], 1)}
            for (a, b), p in pairs.items()]
    rows.sort(key=lambda r: (-r['score'], -r['frames']))
    callsigns_airborne = {cs for i, cs in enumerate(rec.obs_callsign) if air[i] and cs}
    involved = {r['a'] for r in rows} | {r['b'] for r in rows}
    return {
        'pairs': rows, 'pair_count': len(rows),
        'aircraft_involved': len(involved), 'aircraft_with_callsign': len(callsigns_airborne),
        'share_of_aircraft_pct': round(100 * len(involved) / len(callsigns_airborne), 1) if callsigns_airborne else 0,
        'mean_aircraft_at_risk_per_frame': round(float(np.mean(involved_per_frame)), 2),
        'method': __doc__.strip().split('\n\n')[1].replace('\n', ' '),
    }
