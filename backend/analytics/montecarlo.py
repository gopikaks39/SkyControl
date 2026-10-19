"""Communication-error model: voice-only ATC versus SkyControl's hybrid channel.

Two parts:

1. Verifier evaluation (measured). A corpus of readbacks is generated from
   real callsigns in the recording with random clearances, phraseology
   variants and injected errors (wrong digit, swapped digits, omitted item,
   wrong aircraft answering), optionally passed through simulated
   speech-recognition noise. The SkyControl readback verifier is scored on it.

2. Sector-hour Monte Carlo (modelled). Clearances in a busy sector are
   simulated with the error rates below. The voice baseline relies on the
   controller's hearback. The hybrid sends eligible clearances by datalink
   and checks every voice readback with the verifier (detection rate taken
   from part 1). Similar-callsign exposure comes from the real recording.
   Rates are assumptions informed by published studies, so every result is
   reported with a sensitivity sweep, not as a single number.
"""
from __future__ import annotations

import random

import numpy as np

from ..core.comms import Clearance, callsign_similarity, phraseology, telephony, verify_readback

ASSUMPTIONS = {
    'clearances_per_sector_hour': 300,
    'readback_error_rate': 0.01,
    'readback_error_range': [0.005, 0.03],
    'hearback_miss_rate': 0.4,
    'hearback_miss_range': [0.2, 0.6],
    'callsign_confusion_rate_when_similar': 0.005,
    'datalink_share': 0.7,
    'datalink_residual_error': 0.0005,
    'datalink_residual_range': [0.0001, 0.002],
    'similar_callsign_alert_effectiveness': 0.7,
    'instruction_seconds': 5.0,
    'readback_seconds': 4.0,
    'correction_seconds': 8.0,
    'sources': [
        'Readback errors occur in the order of 1% of voice transmissions and a substantial share are not caught by the controller (Cardosi, 1993; Cardosi, Falzarano & Han, 1998).',
        'Callsign similarity is a recognised contributor to communication incidents (EUROCONTROL Call Sign Similarity programme).',
        'Datalink share and residual error are planning assumptions for routine clearances to equipped aircraft (CPDLC / Link 2000+).',
    ],
}

WAYPOINTS = ['LAM', 'BIG', 'OCK', 'BNN', 'TIMBA', 'WILLO', 'ABBOT', 'LOREL', 'DET', 'CLN', 'BPK', 'SAM']


def random_clearance(rng, callsign):
    c = Clearance(callsign)
    kinds = rng.sample(['level', 'heading', 'speed', 'direct', 'squawk', 'frequency'], rng.choice([1, 2, 2, 3]))
    for k in kinds:
        if k == 'level':
            c.level = rng.choice([rng.randrange(70, 380, 10) * 100, rng.randrange(3, 7) * 1000])
        elif k == 'heading':
            c.heading = rng.randrange(10, 361, 5)
        elif k == 'speed':
            c.speed = rng.choice([180, 200, 210, 220, 230, 250, 280])
        elif k == 'direct':
            c.direct = rng.choice(WAYPOINTS)
        elif k == 'squawk':
            c.squawk = ''.join(rng.choice('01234567') for _ in range(4))
        elif k == 'frequency':
            c.frequency = f"{rng.choice([118, 119, 120, 121, 124, 127, 128, 129, 132, 133, 134, 135])}.{rng.choice(['025', '05', '075', '1', '125', '175', '2', '225', '3', '35', '375', '4', '45', '5'])}".rstrip('0').rstrip('.')
    return c


def _mutate_digits(value, rng):
    s = str(value)
    pos = [i for i, ch in enumerate(s) if ch.isdigit()]
    if len(pos) >= 2 and rng.random() < 0.4:
        i, j = rng.sample(pos, 2)
        if s[i] != s[j]:
            lst = list(s)
            lst[i], lst[j] = lst[j], lst[i]
            return ''.join(lst)
    i = rng.choice(pos)
    choices = [d for d in '0123456789' if d != s[i]]
    return s[:i] + rng.choice(choices) + s[i + 1:]


def render_readback(c: Clearance, rng, style):
    """Pilot readback in one of several realistic styles."""
    body = phraseology(c).split(', ', 1)[1] if ', ' in phraseology(c) else ''
    body = body.replace('turn heading', 'heading').replace('proceed direct', 'direct').replace('contact ', '')
    spoken = telephony(c.callsign)
    if style == 'compact':
        parts = []
        for k, v in c.fields().items():
            parts.append({'level': lambda v: f'FL{v // 100}' if v > 6000 else f'{v} feet', 'heading': lambda v: f'heading {v:03d}',
                          'speed': lambda v: f'speed {v}', 'direct': lambda v: f'direct {v}', 'squawk': lambda v: f'squawk {v}',
                          'frequency': lambda v: f'{v}', 'qnh': lambda v: f'QNH {v}', 'runway': lambda v: f'runway {v}'}[k](v))
        return ', '.join(parts) + ', ' + c.callsign
    if style == 'callsign_first':
        return f'{spoken}, {body}'
    return f'{body}, {spoken}'


def asr_noise(text, rng, wer):
    """Simulated speech-to-text errors: drop or substitute words at the given word-error rate."""
    words = text.split()
    out = []
    for w in words:
        r = rng.random()
        if r < wer / 2:
            continue
        if r < wer:
            out.append(rng.choice(['uh', 'the', 'to', 'and', 'roger']))
            continue
        out.append(w)
    return ' '.join(out)


def build_corpus(callsigns, n=3000, seed=21, wer=0.0):
    rng = random.Random(seed)
    corpus = []
    pool = [c for c in callsigns if c[:3] in ('BAW', 'EZY', 'RYR', 'KLM', 'DLH', 'SHT', 'EXS', 'EIN', 'SWR', 'CFE') and len(c) >= 5]
    for _ in range(n):
        cs = rng.choice(pool)
        c = random_clearance(rng, cs)
        style = rng.choice(['spoken', 'callsign_first', 'compact'])
        error = rng.choices(['none', 'wrong_value', 'omitted', 'wrong_aircraft'], weights=[0.5, 0.25, 0.15, 0.10])[0]
        answered = c
        similar = None
        if error == 'wrong_value':
            key = rng.choice(list(c.fields()))
            value = getattr(c, key)
            if key in ('direct',):
                new = rng.choice([w for w in WAYPOINTS if w != value])
            elif key == 'frequency':
                new = _mutate_digits(value, rng)
            else:
                new = type(value)(_mutate_digits(value, rng))
            answered = Clearance(**{**c.__dict__, key: new})
        elif error == 'omitted' and len(c.fields()) > 1:
            key = rng.choice(list(c.fields()))
            answered = Clearance(**{**c.__dict__, key: None})
        elif error == 'omitted':
            error = 'none'
        elif error == 'wrong_aircraft':
            candidates = [o for o in pool if callsign_similarity(cs, o)[0] >= 0.7]
            if not candidates:
                error = 'none'
            else:
                similar = rng.choice(candidates)
                answered = Clearance(**{**c.__dict__, 'callsign': similar})
        text = render_readback(answered, rng, style)
        if wer:
            text = asr_noise(text, rng, wer)
        on_frequency = [cs] + ([similar] if similar else rng.sample(pool, 3))
        corpus.append({'clearance': c, 'readback': text, 'error': error, 'frequency': on_frequency})
    return corpus


def evaluate_verifier(corpus):
    """Score the verifier: any flag on an erroneous readback counts as detection.

    On correct readbacks a hard flag (MISMATCH / WRONG_AIRCRAFT) is a false
    alarm; a soft INCOMPLETE ("confirm") is counted separately because it costs
    a short exchange but cannot cause a wrong action.
    """
    by_type = {}
    for item in corpus:
        result = verify_readback(item['clearance'], item['readback'], item['frequency'])
        row = by_type.setdefault(item['error'], {'n': 0, 'flagged': 0, 'hard': 0, 'soft': 0})
        row['n'] += 1
        row['flagged'] += result['verdict'] != 'CORRECT'
        row['hard'] += result['severity'] == 'error'
        row['soft'] += result['severity'] == 'confirm'
    errors = [v for k, v in by_type.items() if k != 'none']
    detected = sum(v['flagged'] for v in errors)
    total_err = sum(v['n'] for v in errors)
    clean = by_type.get('none', {'n': 0, 'flagged': 0, 'hard': 0, 'soft': 0})
    return {
        'by_error_type': {k: {**v, 'rate': round(v['flagged'] / v['n'], 4)} for k, v in by_type.items()},
        'detection_rate': round(detected / total_err, 4) if total_err else None,
        'hard_false_alarm_rate': round(clean['hard'] / clean['n'], 4) if clean['n'] else None,
        'confirm_request_rate': round(clean['soft'] / clean['n'], 4) if clean['n'] else None,
        'corpus_size': len(corpus),
    }


def simulate_hour(rng, p, similar_exposure, detect_rate, hybrid, confirm_rate=0.0):
    n = rng.poisson(p['clearances_per_sector_hour'])
    datalink = rng.binomial(n, p['datalink_share']) if hybrid else 0
    voice = n - datalink
    rb_errors = rng.binomial(voice, p['readback_error_rate'])
    confusion = rng.binomial(voice, p['callsign_confusion_rate_when_similar'] * similar_exposure)
    if hybrid:
        confusion = rng.binomial(confusion, 1 - p['similar_callsign_alert_effectiveness'])
        missed = rng.binomial(rb_errors, p['hearback_miss_rate'] * (1 - detect_rate))
        missed_conf = rng.binomial(confusion, p['hearback_miss_rate'] * (1 - detect_rate))
        dl_err = rng.binomial(datalink, p['datalink_residual_error'])
    else:
        missed = rng.binomial(rb_errors, p['hearback_miss_rate'])
        missed_conf = rng.binomial(confusion, p['hearback_miss_rate'])
        dl_err = 0
    caught = rb_errors + confusion - missed - missed_conf
    confirms = rng.binomial(voice, confirm_rate) if hybrid else 0
    occupancy = voice * (p['instruction_seconds'] + p['readback_seconds']) + (caught + confirms) * p['correction_seconds']
    return missed + missed_conf + dl_err, occupancy / 60, voice


def monte_carlo(similar_exposure, detect_rate, params=None, hours=4000, seed=99, confirm_rate=0.0):
    p = {**ASSUMPTIONS, **(params or {})}
    rng = np.random.default_rng(seed)
    out = {}
    for name, hybrid in (('voice', False), ('hybrid', True)):
        sims = np.array([simulate_hour(rng, p, similar_exposure, detect_rate, hybrid, confirm_rate) for _ in range(hours)])
        out[name] = sims
    v, h = out['voice'], out['hybrid']
    per10k = lambda arr: arr[:, 0].sum() / max(1, len(arr)) / p['clearances_per_sector_hour'] * 10000
    boot = []
    r = np.random.default_rng(seed + 1)
    for _ in range(500):
        s = r.integers(0, hours, hours)
        boot.append(per10k(v[s]) - per10k(h[s]))
    return {
        'voice_undetected_per_10k': round(per10k(v), 2), 'hybrid_undetected_per_10k': round(per10k(h), 2),
        'reduction_per_10k_ci95': [round(float(np.quantile(boot, 0.025)), 2), round(float(np.quantile(boot, 0.975)), 2)],
        'relative_reduction_pct': round(100 * (1 - per10k(h) / per10k(v)), 1) if per10k(v) else None,
        'voice_frequency_min_per_hour': round(float(v[:, 1].mean()), 1),
        'hybrid_frequency_min_per_hour': round(float(h[:, 1].mean()), 1),
        'voice_transmissions_per_hour': round(float(v[:, 2].mean()) * 2, 1),
        'hybrid_transmissions_per_hour': round(float(h[:, 2].mean()) * 2, 1),
        'hours_simulated': hours,
    }


def analyse(callsigns, similar_share_pct, stats=None):
    clean = evaluate_verifier(build_corpus(callsigns, wer=0.0))
    noisy = evaluate_verifier(build_corpus(callsigns, wer=0.05, seed=22))
    exposure = similar_share_pct / 100
    detect = noisy['detection_rate'] or 0.0
    confirm = (noisy['confirm_request_rate'] or 0.0) + (noisy['hard_false_alarm_rate'] or 0.0)
    headline = monte_carlo(exposure, detect, confirm_rate=confirm)
    sweep = []
    for rb in (0.005, 0.01, 0.02, 0.03):
        for miss in (0.2, 0.4, 0.6):
            r = monte_carlo(exposure, detect, {'readback_error_rate': rb, 'hearback_miss_rate': miss}, hours=800, seed=7, confirm_rate=confirm)
            sweep.append({'readback_error_rate': rb, 'hearback_miss_rate': miss,
                          'voice_per_10k': r['voice_undetected_per_10k'], 'hybrid_per_10k': r['hybrid_undetected_per_10k'],
                          'relative_reduction_pct': r['relative_reduction_pct']})
    datalink_curve = []
    for share in (0.0, 0.25, 0.5, 0.7, 0.9):
        r = monte_carlo(exposure, detect, {'datalink_share': share}, hours=800, seed=8, confirm_rate=confirm)
        datalink_curve.append({'datalink_share': share, 'hybrid_per_10k': r['hybrid_undetected_per_10k'],
                               'frequency_min_per_hour': r['hybrid_frequency_min_per_hour']})
    return {
        'verifier_clean': clean, 'verifier_asr_5pct': noisy,
        'similar_callsign_exposure': exposure,
        'headline': headline, 'sensitivity': sweep, 'datalink_curve': datalink_curve,
        'assumptions': ASSUMPTIONS,
        'method': __doc__.strip().split('\n\n', 1)[1],
        'caveat': ('The verifier and the corpus generator were written by the same team, so the verifier scores are an '
                   'upper bound; field trials with real transcripts are required before any operational claim.'),
    }
