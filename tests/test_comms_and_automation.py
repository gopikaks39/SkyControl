"""Readback verification, phraseology, callsign similarity, automation policy and separation geometry."""
from backend.core import automation
from backend.core.comms import Clearance, callsign_similarity, parse_readback, phraseology, similar_pairs, verify_readback
from backend.core.separation import avoid, interval_conflict, point, segment_distance

C = Clearance('BAW425', level=12000, heading=270, speed=220, squawk='4521', frequency='133.175')


def test_correct_spoken_and_compact_readbacks():
    spoken = 'Speedbird four two five, climb flight level one two zero, heading two seven zero, speed two two zero, squawk four five two one, one three three decimal one seven five'
    assert verify_readback(C, spoken, ['BAW725'])['verdict'] == 'CORRECT'
    assert verify_readback(C, 'FL120, heading 270, speed 220, squawk 4521, 133.175, BAW425')['verdict'] == 'CORRECT'


def test_wrong_value_wrong_aircraft_and_missing_items():
    assert verify_readback(C, 'climb flight level one four zero heading two seven zero speed two two zero squawk four five two one one three three decimal one seven five speedbird four two five')['verdict'] == 'MISMATCH'
    r = verify_readback(C, 'climb flight level one two zero, Speedbird seven two five', ['BAW725'])
    assert r['verdict'] == 'WRONG_AIRCRAFT' and r['answering_callsign'] == 'BAW725'
    r = verify_readback(C, 'flight level one two zero, Speedbird four two five')
    assert r['verdict'] == 'INCOMPLETE' and r['severity'] == 'confirm'


def test_dropped_digit_is_unclear_not_wrong():
    r = verify_readback(Clearance('BAW425', heading=270), 'heading two seven, Speedbird four two five')
    assert r['items'][0]['status'] == 'unclear' and r['severity'] == 'confirm'


def test_nato_letters_feet_and_runway():
    c = Clearance('EZY12AB', level=6000, qnh=1013, runway='27L')
    assert verify_readback(c, 'descend six thousand feet QNH one zero one three runway two seven left easy one two alpha bravo')['verdict'] == 'CORRECT'
    assert parse_readback('altitude 4000 feet')['level'] == 4000


def test_phraseology():
    assert phraseology(Clearance('BAW425', level=12000), 10000) == 'Speedbird four two five, climb flight level one two zero'
    assert phraseology(Clearance('EZY12AB', level=5000, runway='27R'), 8000) == 'Easy one two alpha bravo, descend five thousand feet, runway two seven right'


def test_callsign_similarity_rules():
    assert callsign_similarity('BAW425', 'BAW725') == (0.9, 'one character differs')
    assert callsign_similarity('BAW425', 'BAW452')[1] == 'same characters in a different order'
    assert callsign_similarity('EZY123', 'RYR123')[1] == 'same flight number, different operator'
    assert callsign_similarity('BAW425', 'KLM88U') == (0.0, None)
    assert [p['b'] for p in similar_pairs(['BAW425', 'BAW725', 'KLM88U'], 0.7)] == ['BAW725']


def test_automation_policy():
    assert automation.decide('Low', 0.95, 0.95)[0] == 'AUTO'
    assert automation.decide('High', 0.9)[0] == 'CONSENT'
    assert automation.decide('High', 0.8)[0] == 'ADVISORY'
    assert automation.decide('Critical', 0.9)[:2] == ('ADVISORY', 'supervisor')
    assert automation.decide('Critical', 0.5)[0] == 'MANUAL'
    assert automation.decide('Low', data_quality=0.4)[0] == 'MANUAL'
    assert automation.decide('Low', disagreement=True)[0] == 'MANUAL'
    assert automation.decide('High', security=True)[:2] == ('MANUAL', 'supervisor')


def test_interval_conflict_geometry():
    a = [point(-20, 0, 10000, 0), point(20, 0, 10000, 600)]
    b = [point(0, -20, 10000, 0), point(0, 20, 10000, 600)]
    assert interval_conflict(a, b) is not None
    b_high = [point(0, -20, 11000, 0), point(0, 20, 11000, 600)]
    assert interval_conflict(a, b_high) is None


def test_visibility_graph_avoids_hazard():
    route = avoid((-24, 0), (24, 0), (0, 0, 6))
    assert len(route) > 2
    assert all(segment_distance(p, q, (0, 0)) >= 6.5 for p, q in zip(route, route[1:]))


def test_comms_api_stores_checks(api, controller):
    r = api.post('/api/comms/verify', json={'clearance': {'callsign': 'BAW425', 'level': 12000}, 'readback': 'climb FL140 Speedbird 425',
                                             'on_frequency': ['BAW725']}, headers=controller)
    assert r.status_code == 201 and r.json()['verdict'] == 'MISMATCH'
    assert r.json()['similar_callsigns'][0]['b'] == 'BAW725'
    assert api.get('/api/comms/log', headers=controller).json()[0]['verdict'] == 'MISMATCH'
    assert api.post('/api/comms/verify', json={'clearance': {'callsign': 'BAW425', 'squawk': '9999'}, 'readback': 'x'}, headers=controller).status_code == 400
    assert api.post('/api/automation/decide', json={'severity': 'Critical', 'confidence': 0.9}, headers=controller).json()['level'] == 'ADVISORY'
