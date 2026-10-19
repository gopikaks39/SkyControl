"""Small, dependency-light statistics helpers with fixed random seeds."""
from __future__ import annotations

import math

import numpy as np
from scipy import stats as sps

SEED = 2026


def bootstrap_ci(values, fn=np.mean, n=2000, alpha=0.05, seed=SEED):
    values = np.asarray(values, dtype=float)
    if len(values) == 0:
        return [None, None]
    rng = np.random.default_rng(seed)
    samples = rng.integers(0, len(values), size=(n, len(values)))
    boot = np.array([fn(values[s]) for s in samples])
    return [round(float(np.quantile(boot, alpha / 2)), 4), round(float(np.quantile(boot, 1 - alpha / 2)), 4)]


def paired(baseline, proposed, baseline_name, proposed_name, unit='NM', higher_is_better=False):
    """Paired comparison of per-case values.

    By default values are errors (lower is better). With higher_is_better the
    improvement is proposed - baseline (e.g. warning time).
    """
    b = np.asarray(baseline, dtype=float)
    p = np.asarray(proposed, dtype=float)
    diff = p - b if higher_is_better else b - p
    try:
        w = sps.wilcoxon(p, b, alternative='greater') if higher_is_better else sps.wilcoxon(b, p, alternative='greater')
        p_value = float(w.pvalue)
    except ValueError:
        p_value = None
    mean_b, mean_p = float(b.mean()), float(p.mean())
    return {
        'n': int(len(b)), 'unit': unit,
        'baseline': baseline_name, 'proposed': proposed_name,
        'baseline_mean': round(mean_b, 3), 'proposed_mean': round(mean_p, 3),
        'baseline_median': round(float(np.median(b)), 3), 'proposed_median': round(float(np.median(p)), 3),
        'mean_improvement': round(float(diff.mean()), 3),
        'mean_improvement_ci95': bootstrap_ci(diff),
        'relative_improvement_pct': round(100 * float(diff.mean()) / abs(mean_b), 1) if mean_b else None,
        'share_of_cases_improved_pct': round(100 * float((diff > 0).mean()), 1),
        'wilcoxon_p_one_sided': p_value,
        'test': ('Wilcoxon signed-rank, one-sided (proposed ' + ('>' if higher_is_better else '<') +
                 ' baseline); bootstrap 95% CI of the mean paired improvement'),
    }


def wilson(successes, n, z=1.96):
    """Wilson score interval for a proportion."""
    if n == 0:
        return [None, None]
    phat = successes / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    return [round(centre - half, 4), round(centre + half, 4)]


def mean_ci(values):
    values = np.asarray(values, dtype=float)
    if len(values) < 2:
        return [None, None]
    se = values.std(ddof=1) / math.sqrt(len(values))
    return [round(float(values.mean() - 1.96 * se), 4), round(float(values.mean() + 1.96 * se), 4)]


def percentiles(values, qs=(50, 90, 95)):
    values = np.asarray(values, dtype=float)
    return {f'p{q}': round(float(np.percentile(values, q)), 3) for q in qs} if len(values) else {}
