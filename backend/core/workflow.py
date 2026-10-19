"""Controller workflow model: conventional voice ATC versus SkyControl hybrid.

For every scenario we count the tasks a controller must perform and the
radio transmissions needed, then add up a timeline with the task durations
below. The numbers are modelled, not measured: they make the comparison
transparent and repeatable, and every duration can be changed here.

Conventional workflow: the controller detects the situation (safety-net alert,
crew call or visual scan), decides, looks up checklists or alternates, phones
adjacent units and issues every instruction by voice, one after another, with
a readback each time.

SkyControl workflow: detection by the probes and monitors, plan computed and
verified automatically, a single review/approval, urgent instructions by voice
with automatic readback verification, non-urgent ones by datalink (in parallel,
off the frequency), and coordination by digital message.
"""
from __future__ import annotations

TIMES = {
    'voice_instruction_s': 5.0,
    'readback_s': 4.0,
    'correction_s': 8.0,
    'phone_coordination_s': 25.0,
    'digital_coordination_s': 3.0,
    'checklist_s': 30.0,
    'alternate_search_s': 60.0,
    'controller_decision_s': 15.0,
    'review_s': 10.0,
    'datalink_response_s': 30.0,
    'plan_compute_s': 1.0,
    'readback_error_rate': 0.01,
}

TIME_SOURCES = [
    'Voice instruction and readback durations of a few seconds each follow analyses of controller-pilot transmissions (Cardosi, 1993).',
    'CPDLC pilot response times of tens of seconds are why urgent instructions stay on voice (EUROCONTROL Link 2000+ operational experience).',
    'Decision, checklist, alternate-search and telephone coordination times are modelling assumptions for a teaching exercise.',
]

TASK_LABELS = {
    'checklist': ('Look up emergency checklist / airport data', 'checklist_s'),
    'alternate_search': ('Find a suitable alternate airport', 'alternate_search_s'),
    'phone': ('Telephone coordination with an adjacent unit', 'phone_coordination_s'),
}


def compare(profile, instructions, approval_required):
    """Timeline totals for both workflows.

    profile: dict with detect_baseline_s, detect_hybrid_s, manual_tasks (list),
             coordination (int), urgent_share (0-1)
    instructions: number of aircraft that need an instruction under SkyControl
                  (profile['extra_baseline'] adds conventional-only instructions)
    """
    T = TIMES
    urgent = round(instructions * profile.get('urgent_share', 1.0))
    routine = instructions - urgent
    tasks = profile.get('manual_tasks', [])
    coordination = profile.get('coordination', 0)
    hybrid_instructions = instructions
    # Instructions only the conventional workflow needs (needless avoidance, cancel and re-issue ...).
    instructions = instructions + profile.get('extra_baseline', 0)

    pair = T['voice_instruction_s'] + T['readback_s']
    expected_corrections = instructions * T['readback_error_rate']
    base_steps = [('Detect', profile['detect_baseline_s']), ('Decide', T['controller_decision_s'])]
    base_steps += [(TASK_LABELS[k][0], T[TASK_LABELS[k][1]]) for k in tasks]
    base_steps += [('Telephone coordination', T['phone_coordination_s'])] * coordination
    base_steps += [('Voice instructions + readbacks', instructions * pair + expected_corrections * T['correction_s'])]
    baseline = {
        'time_to_all_instructions_s': round(sum(d for _, d in base_steps), 1),
        'radio_transmissions': round(2 * instructions + expected_corrections, 2),
        'frequency_seconds': round(instructions * pair + expected_corrections * T['correction_s'], 1),
        'controller_actions': 1 + len(tasks) + coordination + instructions,
        'unverified_voice_clearances': instructions,
        'steps': [{'step': s, 'seconds': round(d, 1)} for s, d in base_steps],
    }

    hyb_steps = [('Detect (probe/monitor)', profile['detect_hybrid_s']), ('Plan + verify (automatic)', T['plan_compute_s'])]
    if approval_required:
        hyb_steps.append(('Review and approve', T['review_s']))
    if coordination:
        hyb_steps.append(('Digital coordination', T['digital_coordination_s']))
    voice_time = urgent * pair
    datalink_time = T['datalink_response_s'] if routine else 0.0
    hyb_steps.append(('Urgent voice (verified) | routine datalink in parallel', max(voice_time, datalink_time)))
    hybrid = {
        'time_to_all_instructions_s': round(sum(d for _, d in hyb_steps), 1),
        'radio_transmissions': 2 * urgent,
        'frequency_seconds': round(voice_time, 1),
        'controller_actions': (1 if approval_required else 0) + urgent,
        'unverified_voice_clearances': 0,
        'steps': [{'step': s, 'seconds': round(d, 1)} for s, d in hyb_steps],
    }
    saving = baseline['time_to_all_instructions_s'] - hybrid['time_to_all_instructions_s']
    return {
        'baseline': baseline, 'hybrid': hybrid, 'instructions': hybrid_instructions,
        'baseline_instructions': instructions,
        'urgent_voice': urgent, 'routine_datalink': routine,
        'time_saving_s': round(saving, 1),
        'time_saving_pct': round(100 * saving / baseline['time_to_all_instructions_s'], 1) if baseline['time_to_all_instructions_s'] else 0,
        'transmission_reduction_pct': round(100 * (1 - hybrid['radio_transmissions'] / baseline['radio_transmissions']), 1) if baseline['radio_transmissions'] else 0,
    }
