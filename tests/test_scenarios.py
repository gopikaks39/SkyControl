"""All 21 scenarios: verified plans, a real problem in the comparator, the step pipeline and context switches."""
import pytest

from backend.core import scenarios
from backend.core.separation import all_conflicts

ROSTER = [{'callsign': c} for c in ('BAW425', 'BAW725', 'EZY12AB', 'RYR52ZT', 'KLM88U', 'DLH4PK', 'SHT13H', 'EIN38Y', 'CFE844', 'EXS32K', 'SWR9AM')]
PHASES = ['DETECT', 'ASSESS', 'CONTEXT SWITCH', 'PLAN', 'VERIFY', 'AUTHORISE', 'COMMUNICATE', 'EXECUTE', 'MONITOR', 'CLOSE']


def test_catalog_has_21_scenarios_with_gaps():
    cat = scenarios.catalog()
    assert len(cat) == 21
    assert all(s['gap'] and s['category'] for s in cat)


@pytest.mark.parametrize('key', list(scenarios.SPECS))
def test_every_plan_is_verified_and_conflict_free(key):
    d = scenarios.build(key, ROSTER, 'test')
    assert d['plan_valid'], key
    assert all_conflicts(d['aircraft'], 'resolved') == []
    assert len(d['aircraft']) == scenarios.SPECS[key].aircraft
    assert [s['phase'] for s in d['steps']] == PHASES
    assert d['workflow']['hybrid']['time_to_all_instructions_s'] <= d['workflow']['baseline']['time_to_all_instructions_s']
    # Routes must agree up to the approval gate so the replay can switch plans at approval time.
    for a in d['aircraft']:
        assert a['baseline'][0] == a['resolved'][0]


@pytest.mark.parametrize('key', [k for k in scenarios.SPECS if k != 'normal'])
def test_comparator_shows_the_problem(key):
    d = scenarios.build(key, ROSTER, 'test')
    assert any(c['before'] > c['after'] for c in d['checks']) or d['workflow']['time_saving_s'] > 0


def test_context_switch_levels():
    level = lambda k: scenarios.build(k, ROSTER, 'test')['automation_level']
    assert level('normal') == 'AUTO'
    assert level('hijack') == 'MANUAL'
    assert level('ai_disagreement') == 'MANUAL'
    assert level('sensor_dropout') == 'MANUAL'
    assert level('low_fuel') == 'ADVISORY'
    d = scenarios.build('sensor_dropout', ROSTER, 'test')
    assert [c['level'] for c in d['context_log']] == ['CONSENT', 'MANUAL', 'CONSENT']


def test_readback_error_messages_show_detection_and_correction():
    d = scenarios.build('readback_error', ROSTER, 'test')
    msg = d['messages'][0]
    assert msg['first_verification']['verdict'] == 'MISMATCH'
    assert msg['verification']['verdict'] == 'CORRECT'
    assert d['before']['conflict_pairs'] == 1 and d['after']['conflict_pairs'] == 0


def test_callsign_confusion_picks_similar_pair_and_flags_wrong_aircraft():
    d = scenarios.build('callsign_confusion', ROSTER, 'test')
    assert [a['name'] for a in d['aircraft'][:2]] == ['BAW425', 'BAW725']
    assert d['messages'][0]['blocked_verification']['verdict'] == 'WRONG_AIRCRAFT'


def test_low_fuel_meets_deadline_only_with_priority():
    d = scenarios.build('low_fuel', ROSTER, 'test')
    assert d['before']['deadline_misses'] == 1 and d['after']['deadline_misses'] == 0


def test_benchmark_rows():
    rows = scenarios.benchmark()
    assert len(rows) == 21 and all(r['valid'] for r in rows)
