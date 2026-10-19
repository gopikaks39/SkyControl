"""Statistical analysis, gap catalogue, AI model summaries, automation policy and communication assistant."""
from __future__ import annotations

import json

from fastapi import APIRouter, Body, HTTPException, Request
from fastapi.responses import Response

from ..analytics import pipeline
from ..auth import require
from ..core import automation, gaps
from ..core.comms import Clearance, callsign_similarity, phraseology, similar_pairs, verify_readback
from ..database import audit, connect, rows, utcnow

router = APIRouter(prefix='/api')

SECTIONS = ('overview', 'surveillance', 'prediction', 'conflicts', 'holding', 'hold_model', 'callsigns',
            'communication', 'anomaly', 'emergency_injection', 'scenarios')


@router.get('/analysis')
def analysis(request: Request):
    require(request)
    return pipeline.get()


@router.get('/analysis/export')
def export(request: Request):
    require(request)
    return Response(json.dumps(pipeline.get(), indent=1), media_type='application/json',
                    headers={'Content-Disposition': 'attachment; filename="skycontrol_analysis.json"'})


@router.get('/analysis/{section}')
def analysis_section(section: str, request: Request):
    require(request)
    if section not in SECTIONS:
        raise HTTPException(404, 'Unknown section')
    return pipeline.get()[section]


@router.get('/gaps')
def gap_catalogue(request: Request):
    require(request)
    return gaps.catalogue(pipeline.get())


@router.get('/models')
def models(request: Request):
    require(request)
    a = pipeline.get()
    return {
        'trajectory_predictor': a['prediction'], 'hold_predictor': a['hold_model'], 'anomaly_detector': a['anomaly'],
        'readback_verifier': {'clean': a['communication']['verifier_clean'], 'asr_5pct': a['communication']['verifier_asr_5pct'],
                              'caveat': a['communication']['caveat']},
        'automation_levels': automation.DESCRIPTIONS,
    }


@router.post('/automation/decide')
def decide(request: Request, body: dict = Body(...)):
    require(request)
    try:
        ctx = {
            'severity': body.get('severity', 'Low'), 'confidence': float(body.get('confidence', 0.95)),
            'data_quality': float(body.get('data_quality', 1.0)), 'workload': float(body.get('workload', 0.5)),
            'disagreement': bool(body.get('disagreement', False)), 'security': bool(body.get('security', False)),
            'novelty': float(body.get('novelty', 0.0)),
        }
    except (TypeError, ValueError):
        raise HTTPException(400, 'Numeric context values required')
    if ctx['severity'] not in ('Low', 'High', 'Critical'):
        raise HTTPException(400, 'severity must be Low, High or Critical')
    level, approver, reasons = automation.decide(**ctx)
    return {'level': level, 'approver': approver, 'reasons': reasons, 'description': automation.DESCRIPTIONS[level]}


# ---------------------------------------------------------------- communication assistant

def _clearance(body):
    c = body.get('clearance') or {}
    callsign = str(c.get('callsign') or '').strip().upper()
    if not callsign or len(callsign) > 10:
        raise HTTPException(400, 'Clearance callsign required')

    def num(key, lo, hi):
        if c.get(key) in (None, ''):
            return None
        try:
            v = int(float(c[key]))
        except (TypeError, ValueError):
            raise HTTPException(400, f'Invalid {key}')
        if not lo <= v <= hi:
            raise HTTPException(400, f'{key} out of range')
        return v
    squawk = str(c.get('squawk') or '').strip() or None
    if squawk and (len(squawk) != 4 or any(ch not in '01234567' for ch in squawk)):
        raise HTTPException(400, 'Squawk must be four octal digits')
    freq = str(c.get('frequency') or '').strip() or None
    if freq:
        try:
            if not 118 <= float(freq) < 137:
                raise ValueError
        except ValueError:
            raise HTTPException(400, 'Frequency must be 118.000-136.975')
    clearance = Clearance(callsign, level=num('level', 500, 45000), heading=num('heading', 1, 360), speed=num('speed', 100, 400),
                          direct=(str(c.get('direct') or '').strip().upper() or None), squawk=squawk, frequency=freq,
                          qnh=num('qnh', 900, 1100), runway=(str(c.get('runway') or '').strip().upper() or None))
    if not clearance.fields():
        raise HTTPException(400, 'Enter at least one clearance item')
    return clearance


@router.post('/comms/phraseology')
def render(request: Request, body: dict = Body(...)):
    require(request)
    c = _clearance(body)
    return {'phraseology': phraseology(c, body.get('current_level')), 'fields': c.fields()}


@router.post('/comms/verify', status_code=201)
def verify(request: Request, body: dict = Body(...)):
    u = require(request, mutation=True)
    c = _clearance(body)
    readback = str(body.get('readback') or '').strip()[:500]
    if not readback:
        raise HTTPException(400, 'Readback text required')
    on_frequency = [str(x).upper() for x in body.get('on_frequency', []) if str(x).strip()][:30]
    result = verify_readback(c, readback, on_frequency)
    warnings = [p for p in similar_pairs(on_frequency + [c.callsign], 0.7) if c.callsign in (p['a'], p['b'])]
    result['similar_callsigns'] = warnings
    text = phraseology(c, body.get('current_level'))
    with connect() as db:
        cur = db.execute('INSERT INTO comm_checks (callsign,clearance_json,phraseology,readback,verdict,result_json,checked_by,checked_at) '
                         'VALUES (?,?,?,?,?,?,?,?)', (c.callsign, json.dumps(c.fields()), text, readback, result['verdict'],
                                                      json.dumps(result), u['username'], utcnow()))
        audit(db, u['username'], 'comms.verify', 'comm_checks', cur.lastrowid, {'verdict': result['verdict']})
    return {'id': cur.lastrowid, 'phraseology': text, **result}


@router.get('/comms/log')
def comm_log(request: Request):
    require(request)
    with connect() as db:
        return rows(db.execute('SELECT id,callsign,phraseology,readback,verdict,checked_by,checked_at FROM comm_checks ORDER BY id DESC LIMIT 100'))


@router.post('/comms/similarity')
def similarity(request: Request, body: dict = Body(...)):
    require(request)
    names = [str(x).strip().upper() for x in body.get('callsigns', []) if str(x).strip()][:200]
    if len(names) == 2:
        score, reason = callsign_similarity(*names)
        return {'pairs': [{'a': names[0], 'b': names[1], 'score': score, 'reason': reason}]}
    return {'pairs': similar_pairs(names, float(body.get('threshold', 0.6)))}
