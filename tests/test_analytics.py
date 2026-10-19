"""Real-data analytics on the bundled London-Amsterdam OpenSky recording."""
from backend.analytics import emergency, surveillance
from backend.core import gaps


def test_recording_loads_and_deduplicates(recording):
    assert recording.n_aircraft == 906
    assert len(recording.frames) == 353
    assert recording.duplicates_removed == 708
    assert recording.meta['is_real_recorded_data'] is True


def test_known_duplicate_target_is_found(recording):
    rows, ghosts = surveillance.find_ghosts(recording)
    pairs = {(r['real_icao'], r['ghost_icao']) for r in rows} | {(r['ghost_icao'], r['real_icao']) for r in rows}
    assert ('4cafc1', '4caf41') in pairs or ('4caf41', '4cafc1') in pairs


def test_coasting_beats_frozen_display(analysis):
    c = analysis['surveillance']['coasting']
    assert c['coasted_mean_error_nm'] < c['frozen_mean_error_nm']
    assert c['comparison']['wilcoxon_p_one_sided'] < 0.001


def test_learned_predictor_beats_straight_line_on_held_out_data(analysis):
    for h in analysis['prediction']['horizons']:
        assert h['proposed_mean'] < h['baseline_mean']
        assert h['wilcoxon_p_one_sided'] < 0.001


def test_intent_aware_probe_reduces_alerts(analysis):
    m = {x['key']: x for x in analysis['conflicts']['methods']}
    assert m['intent_probe']['alert_episodes'] < m['naive_probe']['alert_episodes']
    assert m['intent_probe']['alerts_per_hour'] <= m['stca']['alerts_per_hour'] * 1.05
    assert m['intent_probe']['alerted_before_encounter'] >= m['stca']['alerted_before_encounter']


def test_holding_and_callsigns(analysis):
    stacks = {s['stack'] for s in analysis['holding']['stacks']}
    assert {'LAM', 'BIG', 'OCK'} <= stacks
    pairs = {(p['a'], p['b']) for p in analysis['callsigns']['pairs']}
    assert ('BAW425', 'BAW725') in pairs


def test_communication_model_and_verifier(analysis):
    c = analysis['communication']
    assert c['verifier_clean']['detection_rate'] > 0.9 and c['verifier_clean']['hard_false_alarm_rate'] < 0.01
    assert c['headline']['hybrid_undetected_per_10k'] < c['headline']['voice_undetected_per_10k']
    assert all(s['hybrid_per_10k'] < s['voice_per_10k'] for s in c['sensitivity'])


def test_anomaly_hybrid_detects_more_than_rule(analysis):
    t = analysis['anomaly']['totals']
    assert t['hybrid'] > t['rule'] and t['clam'] >= t['hybrid']


def test_emergency_injection_on_real_traffic(recording):
    ts = int(recording.frames[0]) + 2400
    idx = recording.frame_at(ts)[1]
    airborne = [i for i in idx if recording.airborne[i] and recording.alt[i] > 20000]
    icao = recording.icao[recording.ac[airborne[0]]]
    r = emergency.plan(recording, ts, icao, 'engine_failure')
    assert r['chosen_airport']['suitable'] and r['chosen_airport']['runway_m'] >= 2400
    assert r['path'][-1]['altitude_ft'] < 1000
    assert r['automation_level'] in ('ADVISORY', 'MANUAL') and r['approver'] == 'supervisor'
    assert all(x['phraseology'] is None or 'thousand' in x['phraseology'] or 'flight level' in x['phraseology'] for x in r['resolutions'])


def test_gap_catalogue_is_filled_from_results(analysis):
    cat = gaps.catalogue(analysis)
    assert [g['id'] for g in cat] == [f'G{i}' for i in range(1, 10)]
    assert all('n/a' not in e for g in cat for e in g['evidence'])


def test_analysis_and_airspace_api(api, controller, analysis):
    assert api.get('/api/analysis/overview', headers=controller).json()['aircraft'] == 906
    frame = api.get('/api/airspace/frame?offset=2400', headers=controller).json()
    assert frame['airborne'] > 100 and 'predicted_conflicts' in frame
    tracks = api.get('/api/airspace/tracks', headers=controller).json()
    assert len(tracks['tracks']) == 906
    assert len(api.get('/api/gaps', headers=controller).json()) == 9
    assert api.get('/api/models', headers=controller).status_code == 200


def test_emergency_api_requires_supervisor_review(api, controller, supervisor, recording, analysis):
    ts = 2400
    idx = recording.frame_at(int(recording.frames[0]) + ts)[1]
    icao = next(recording.icao[recording.ac[i]] for i in idx if recording.airborne[i] and recording.alt[i] > 20000)
    r = api.post('/api/airspace/emergency', json={'offset': ts, 'icao': icao, 'kind': 'medical'}, headers=controller)
    assert r.status_code == 201
    run = r.json()
    assert run['approver'] == 'supervisor' and run['steps'][0]['phase'] == 'DETECT'
    assert api.post(f"/api/airspace/emergency/runs/{run['id']}/review", json={'decision': 'approve'}, headers=controller).status_code == 403
    assert api.post(f"/api/airspace/emergency/runs/{run['id']}/review", json={'decision': 'approve'}, headers=supervisor).json()['status'] == 'Approved'
    assert api.post('/api/airspace/emergency', json={'offset': ts, 'icao': 'zzzzzz', 'kind': 'medical'}, headers=controller).status_code == 400
    assert api.get('/api/airspace/emergency/runs', headers=controller).json()[0]['status'] == 'Approved'
    preds = api.get('/api/airspace/predictions?offset=2400&horizon=300', headers=controller).json()
    assert len(preds['aircraft']) > 50
