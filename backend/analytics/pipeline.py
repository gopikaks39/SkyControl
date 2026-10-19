"""Run every real-data analysis once and cache the results.

The cache key combines the dataset SHA-256 and ANALYTICS_VERSION, so results
are rebuilt automatically when the recording or the analysis code changes.
Trained models are pickled next to the JSON for the live replay endpoints.

Run manually with:  python -m backend.analytics.pipeline
"""
from __future__ import annotations

import json
import pickle
import threading
import time
from collections import Counter

import numpy as np

from ..config import ANALYTICS_VERSION, CACHE_DIR
from ..core import scenarios
from . import anomaly, callsigns, conflicts, emergency, hold_model, holding, montecarlo, prediction, recording, stats, surveillance

_lock = threading.Lock()
_memory = {}


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if not np.isfinite(o) else float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, set):
        return sorted(o)
    raise TypeError(type(o).__name__)


def overview(rec):
    counts = [int(len(rec.frame_index[int(t)])) for t in rec.frames]
    airborne_counts = [int(rec.airborne[rec.frame_index[int(t)]].sum()) for t in rec.frames]
    alt = rec.alt[rec.airborne]
    bands = [0, 5000, 10000, 20000, 30000, 40000, 60000]
    hist = [{'band': f'{bands[i] // 1000}-{bands[i + 1] // 1000}k ft', 'observations': int(((alt >= bands[i]) & (alt < bands[i + 1])).sum())}
            for i in range(len(bands) - 1)]
    operators = Counter(cs[:3] for cs in rec.callsign if len(cs) > 3 and cs[:3].isalpha())
    step = max(1, len(rec.frames) // 120)
    return {
        'dataset_name': rec.meta.get('dataset_name'), 'provider': rec.meta.get('source_provider'),
        'start_utc': rec.meta.get('start_utc'), 'end_utc': rec.meta.get('end_utc'),
        'sha256': rec.sha256, 'bounding_box': rec.meta.get('bounding_box'),
        'observations_source': rec.meta.get('observation_count'), 'observations_used': int(len(rec.t)),
        'duplicates_removed': rec.duplicates_removed, 'aircraft': rec.n_aircraft, 'frames': int(len(rec.frames)),
        'median_frame_interval_s': float(np.median(np.diff(rec.frames))),
        'mean_aircraft_per_frame': round(float(np.mean(counts)), 1), 'max_aircraft_per_frame': int(max(counts)),
        'airborne_share_pct': round(100 * float(rec.airborne.mean()), 1),
        'traffic_series': [{'t': int(rec.frames[i] - rec.frames[0]), 'aircraft': counts[i], 'airborne': airborne_counts[i]}
                           for i in range(0, len(rec.frames), step)],
        'altitude_histogram': hist,
        'top_operators': [{'operator': k, 'aircraft': v} for k, v in operators.most_common(12)],
        'limitations': rec.meta.get('limitations', []),
    }


def summarise_injections(rows):
    def mean(k):
        return round(float(np.mean([r[k] for r in rows])), 2) if rows else None
    base = [r['baseline_time_s'] for r in rows]
    hyb = [r['hybrid_time_s'] for r in rows]
    conflicts = sum(r['conflicts'] for r in rows)
    return {
        'runs': rows, 'count': len(rows),
        'mean_traffic_considered': mean('traffic'), 'mean_conflicts': mean('conflicts'),
        'share_with_conflict_pct': round(100 * sum(r['conflicts'] > 0 for r in rows) / len(rows), 1) if rows else None,
        'conflicts_total': conflicts, 'resolved_total': sum(r['resolved'] for r in rows),
        'resolved_share_pct': round(100 * sum(r['resolved'] for r in rows) / conflicts, 1) if conflicts else None,
        'mean_delayed_arrivals': mean('delayed_arrivals'), 'mean_total_delay_s': mean('total_delay_s'),
        'median_compute_ms': round(float(np.median([r['compute_ms'] for r in rows])), 1) if rows else None,
        'workflow': stats.paired(base, hyb, 'Conventional workflow (modelled)', 'SkyControl hybrid (modelled)', unit='s') if len(rows) > 5 else None,
        'mean_baseline_transmissions': mean('baseline_transmissions'), 'mean_hybrid_transmissions': mean('hybrid_transmissions'),
    }


def summarise_scenarios(rows):
    keys = ('conflict_pairs', 'runway_conflicts', 'hazard_breaches', 'deadline_misses', 'total_route_nm')
    base_t = [r['workflow']['baseline_time_s'] for r in rows]
    hyb_t = [r['workflow']['hybrid_time_s'] for r in rows]
    levels = Counter(r['automation_level'] for r in rows)
    return {
        'cases': rows, 'count': len(rows), 'all_valid': all(r['valid'] for r in rows),
        'totals': {side: {k: round(sum(r[side][k] for r in rows), 1) for k in keys} for side in ('before', 'after')},
        'workflow_time': stats.paired(base_t, hyb_t, 'Conventional workflow (modelled)', 'SkyControl hybrid (modelled)', unit='s'),
        'transmissions': {'baseline': round(sum(r['workflow']['baseline_transmissions'] for r in rows), 1),
                          'hybrid': round(sum(r['workflow']['hybrid_transmissions'] for r in rows), 1)},
        'controller_actions': {'baseline': sum(r['workflow']['baseline_actions'] for r in rows),
                               'hybrid': sum(r['workflow']['hybrid_actions'] for r in rows)},
        'automation_levels': dict(levels),
        'method': ('21 constructed scenarios, one deterministic run each. Before = the comparator named per case; after = '
                   'SkyControl plan. Conflicts use the exact segment test (5 NM / 1,000 ft); runway spacing 120 s. '
                   'Workflow figures come from the task-time model in core/workflow.py and are modelled, not measured.'),
    }


def build(verbose=False):
    t0 = time.time()
    log = (lambda m: print(f'[analytics {time.time() - t0:5.1f}s] {m}', flush=True)) if verbose else (lambda m: None)
    rec = recording.load()
    log(f'loaded {len(rec.t)} observations, {rec.n_aircraft} aircraft')
    result = {'version': ANALYTICS_VERSION, 'dataset_sha256': rec.sha256, 'overview': overview(rec)}
    result['surveillance'], duplicates = surveillance.analyse(rec, stats)
    log('surveillance integrity')
    predictor, result['prediction'] = prediction.train_and_evaluate(rec, stats)
    log('trajectory predictor')
    learned = prediction.cross_fitted(rec)
    result['conflicts'] = conflicts.analyse(rec, duplicates, stats, learned)
    log('conflict alerting')
    result['holding'] = holding.analyse(rec)
    result['hold_model'] = hold_model.analyse(rec, result['holding']['holds'], stats)
    log('holding and hold prediction')
    result['callsigns'] = callsigns.analyse(rec, duplicates)
    result['communication'] = montecarlo.analyse([c for c in rec.callsign if c], result['callsigns']['share_of_aircraft_pct'])
    log('callsigns and communication model')
    result['anomaly'] = anomaly.analyse(rec, stats)
    log('anomaly detection')
    result['emergency_injection'] = summarise_injections(emergency.batch(rec, 60))
    log('emergency injections into real traffic')
    result['scenarios'] = summarise_scenarios(scenarios.benchmark())
    log('scenario benchmark')
    result['duplicates'] = [rec.icao[a] for a in sorted(duplicates)]
    result['built_seconds'] = round(time.time() - t0, 1)
    return result, predictor


def _paths(sha):
    stem = f'analysis_v{ANALYTICS_VERSION}_{sha[:12]}'
    return CACHE_DIR / f'{stem}.json', CACHE_DIR / f'{stem}_predictor.pkl'


def get(verbose=False):
    """Cached analysis results (building them on first use)."""
    with _lock:
        if 'result' in _memory:
            return _memory['result']
        rec = recording.load()
        json_path, model_path = _paths(rec.sha256)
        if json_path.exists() and model_path.exists():
            _memory['result'] = json.loads(json_path.read_text())
            return _memory['result']
        result, predictor = build(verbose)
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        json_path.write_text(json.dumps(result, default=_json_default))
        with open(model_path, 'wb') as fp:
            pickle.dump(predictor, fp)
        _memory['result'] = json.loads(json_path.read_text())
        return _memory['result']


def predictor():
    """Trajectory predictor trained on the first 60 minutes (for live replay)."""
    if 'predictor' not in _memory:
        get()
        _, model_path = _paths(recording.load().sha256)
        with open(model_path, 'rb') as fp:
            _memory['predictor'] = pickle.load(fp)
    return _memory['predictor']


if __name__ == '__main__':
    out = get(verbose=True)
    print('cached analysis for', out['overview']['dataset_name'], 'in', out.get('built_seconds'), 's')
