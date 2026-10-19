"""Gap analysis: where today's ATC is weak and what SkyControl adds.

Each entry names the gap, how it is handled today (including the automation
that already exists, such as STCA, MTCD, CLAM, AMAN and CPDLC), SkyControl's
fix, where it can be seen in the app, and the evidence: a measured result on
the real London recording, a modelled result, or a scenario. The relationship
field states whether SkyControl replaces nothing (it never does), complements
an existing tool, or extends it.
"""
from __future__ import annotations


def _get(d, path, default=None):
    for key in path.split('.'):
        if not isinstance(d, dict) or key not in d:
            return default
        d = d[key]
    return d


def catalogue(analysis=None):
    a = analysis or {}
    comm = _get(a, 'communication.headline', {})
    verifier = _get(a, 'communication.verifier_asr_5pct', {})
    pred300 = next((h for h in _get(a, 'prediction.horizons', []) if h.get('horizon_s') == 300), {})
    conf = _get(a, 'conflicts', {})
    methods = {m['key']: m for m in conf.get('methods', [])}
    surv = _get(a, 'surveillance', {})
    hold = _get(a, 'holding', {})
    hm = _get(a, 'hold_model', {})
    an = _get(a, 'anomaly', {})
    cs = _get(a, 'callsigns', {})
    inj = _get(a, 'emergency_injection', {})
    fmt = lambda v, suffix='': f'{v}{suffix}' if v is not None else 'n/a'
    return [
        {
            'id': 'G1', 'title': 'Voice readback and hearback errors', 'category': 'Human communication',
            'today': 'Voice R/T. The controller must hear and catch a wrong readback; CPDLC exists only for some en-route clearances.',
            'risk': 'A wrong level, heading or frequency is flown when the controller misses the wrong readback.',
            'fix': 'Structured clearances, datalink for routine items, and automatic readback verification of every voice readback (typed or speech-to-text).',
            'where': ['Communication assistant', 'Scenario: Readback error'],
            'relationship': 'Complements CPDLC; adds a second check behind the controller\'s hearback.',
            'evidence': [
                f"Verifier on 3,000 generated readbacks with 5% speech-recognition noise: {fmt(round(100 * verifier.get('detection_rate', 0), 1) if verifier else None, '%')} of errors caught, "
                f"{fmt(round(100 * verifier.get('hard_false_alarm_rate', 0), 2) if verifier else None, '%')} false errors.",
                f"Sector-hour Monte Carlo (modelled): undetected errors {fmt(comm.get('voice_undetected_per_10k'))} to {fmt(comm.get('hybrid_undetected_per_10k'))} per 10,000 clearances "
                f"({fmt(comm.get('relative_reduction_pct'), '%')} fewer); frequency occupancy {fmt(comm.get('voice_frequency_min_per_hour'))} to {fmt(comm.get('hybrid_frequency_min_per_hour'))} min/h.",
            ],
            'evidence_type': 'measured component + modelled system',
        },
        {
            'id': 'G2', 'title': 'Similar callsigns on the same frequency', 'category': 'Human communication',
            'today': 'Planning-stage deconfliction of airline flight numbers and controller vigilance; incidents found afterwards in reports.',
            'risk': 'The wrong aircraft takes an instruction meant for another.',
            'fix': 'Live similarity scoring of every pair sharing airspace, label warnings, logon-addressed datalink and WRONG_AIRCRAFT readback detection.',
            'where': ['3D airspace (similar-callsign layer)', 'Communication assistant', 'Scenario: Callsign confusion'],
            'relationship': 'Extends airline callsign-deconfliction into the tactical phase.',
            'evidence': [f"Real recording: {fmt(cs.get('pair_count'))} similar pairs co-present within 40 NM / 10,000 ft, involving "
                         f"{fmt(cs.get('share_of_aircraft_pct'), '%')} of aircraft (e.g. BAW425/BAW725 holding together at OCK)."],
            'evidence_type': 'measured on real data',
        },
        {
            'id': 'G3', 'title': 'Short look-ahead and nuisance conflict alerts', 'category': 'Separation',
            'today': 'STCA warns about 2 minutes ahead with straight-line extrapolation; MTCD where deployed relies on flight-plan intent.',
            'risk': 'Late warnings, and alert fatigue when most alerts are for aircraft already cleared to safe levels.',
            'fix': 'Intent-aware 5-minute probe: learned trajectory prediction, cleared levels from digital clearances, duplicate-target merging and hysteresis.',
            'where': ['3D airspace (predicted conflicts)', 'Statistical analysis', 'Scenario: Converging traffic'],
            'relationship': 'Complements STCA (the safety net stays); extends MTCD with learned trajectories.',
            'evidence': [
                f"Real recording, 5-min prediction error on held-out traffic: {fmt(pred300.get('baseline_mean'))} NM to {fmt(pred300.get('proposed_mean'))} NM ({fmt(pred300.get('relative_improvement_pct'), '%')} better).",
                f"Alerts per hour: naive 5-min probe {fmt(_get(methods, 'naive_probe.alerts_per_hour'))}, SkyControl probe {fmt(_get(methods, 'intent_probe.alerts_per_hour'))} "
                f"({fmt(conf.get('alert_reduction_vs_naive_probe_pct'), '%')} fewer), close to the 2-min safety net ({fmt(_get(methods, 'stca.alerts_per_hour'))}) while looking 2.5x further ahead.",
            ],
            'evidence_type': 'measured on real data',
        },
        {
            'id': 'G4', 'title': 'Untrusted surveillance: duplicates and dropouts', 'category': 'Surveillance',
            'today': 'Tracker quality is assumed; a frozen or duplicated track can look valid on the display.',
            'risk': 'False alerts from ghost targets, needless instructions, and decisions based on stale positions.',
            'fix': 'Integrity monitor: address bit-error and co-location rules for duplicates, dead-reckoned coasting with uncertainty, and an automatic switch to MANUAL when integrity is low.',
            'where': ['3D airspace (duplicates, coasting)', 'Scenarios: Ghost target, Surveillance gap'],
            'relationship': 'Adds an integrity layer in front of existing safety nets.',
            'evidence': [
                f"Real recording: {fmt(_get(surv, 'ghosts.pair_count'))} duplicate-target pairs; {fmt(_get(surv, 'gaps.count'))} dropouts longer than 60 s.",
                f"Coasting error at reappearance: frozen {fmt(_get(surv, 'coasting.frozen_mean_error_nm'))} NM vs dead-reckoned {fmt(_get(surv, 'coasting.coasted_mean_error_nm'))} NM.",
            ],
            'evidence_type': 'measured on real data',
        },
        {
            'id': 'G5', 'title': 'Arrival delay absorbed in low-level holding', 'category': 'Efficiency',
            'today': 'AMAN/XMAN sequence arrivals, but much delay is still taken in stacks decided near the TMA boundary.',
            'risk': 'Fuel burn and CO2 at low level, and workload in the stacks.',
            'fix': 'Hold prediction while aircraft are 30-80 NM out, and speed advisories (linear holding) over an extended horizon.',
            'where': ['3D airspace (holding layer)', 'Statistical analysis', 'Scenario: Traffic overload'],
            'relationship': 'Extends AMAN with a learned hold prediction.',
            'evidence': [
                f"Real recording: {fmt(hold.get('stack_holds'))} holds, {fmt(hold.get('stack_holding_minutes'))} aircraft-minutes in 90 min "
                f"(about {fmt(hold.get('holding_fuel_kg'))} kg fuel at 40 kg/min).",
                f"Absorbable by 10% speed control over 350 NM (modelled): {fmt(_get(hold, 'aman.share_absorbable_extended_pct'), '%')}. "
                f"Hold predictor test AUC {fmt(hm.get('test_auc'))} (small sample), mean warning {fmt(hm.get('mean_lead_time_min'))} min before the hold.",
            ],
            'evidence_type': 'measured on real data + modelled saving',
        },
        {
            'id': 'G6', 'title': 'Emergency handling depends on one controller\'s memory and phone calls', 'category': 'Emergency',
            'today': 'Checklists, mental selection of alternates, telephone coordination, then voice instructions one aircraft at a time.',
            'risk': 'Slow, error-prone handling while other traffic still needs service.',
            'fix': 'Emergency assistant: suitable-airport ranking, emergency path checked against real traffic, automatic level-change proposals, re-sequencing and digital coordination.',
            'where': ['3D airspace (inject emergency)', 'Scenarios: Fuel, Medical, Engine failure, Emergency descent'],
            'relationship': 'Supports the controller; decisions stay with the controller and supervisor.',
            'evidence': [
                f"{fmt(inj.get('count'))} emergencies injected into real traffic: {fmt(inj.get('mean_conflicts'))} conflicts with real aircraft per case on average, "
                f"{fmt(inj.get('resolved_share_pct'), '%')} resolved by a verified level change, plan computed in {fmt(inj.get('median_compute_ms'))} ms (median).",
                f"Modelled time to all instructions: {fmt(_get(inj, 'workflow.baseline_mean'))} s conventional vs {fmt(_get(inj, 'workflow.proposed_mean'))} s hybrid.",
            ],
            'evidence_type': 'real traffic + modelled workflow',
        },
        {
            'id': 'G7', 'title': 'Level busts seen late', 'category': 'Separation',
            'today': 'CLAM exists where the cleared level is entered in the system; otherwise STCA sees the bust only when traffic is close.',
            'risk': 'Loss of separation after an altitude deviation.',
            'fix': 'Cleared levels come from the digital clearance record, so adherence is checked continuously with a 300 ft tolerance.',
            'where': ['Scenario: Level bust', 'AI models (anomaly + CLAM)'],
            'relationship': 'Extends CLAM by guaranteeing the cleared level is always known.',
            'evidence': [f"Injected emergencies in real tracks: rule {fmt(_get(an, 'totals.rule'))}, learned detector {fmt(_get(an, 'totals.ml'))}, "
                         f"hybrid {fmt(_get(an, 'totals.hybrid'))}, CLAM with clearance record {fmt(_get(an, 'totals.clam'))} of {fmt(an.get('injections_total'))} detected."],
            'evidence_type': 'measured on real tracks with injected events',
        },
        {
            'id': 'G8', 'title': 'Automation that cannot say when it should not be trusted', 'category': 'Automation',
            'today': 'Tools are on or off; confidence and data quality are not shown; automation bias is a known risk.',
            'risk': 'A confident but wrong prediction is followed, or a good tool is ignored.',
            'fix': 'Adaptive automation with explicit context switches (AUTO / CONSENT / ADVISORY / MANUAL) driven by severity, confidence, data quality, disagreement and security.',
            'where': ['Every scenario (context-switch step)', 'AI models (policy simulator)', 'Scenario: AI disagreement'],
            'relationship': 'Governs every SkyControl function; humans keep authority.',
            'evidence': ['Scenario: the learned model predicted a turn away; the rule-based check disagreed, automation dropped to MANUAL and the conservative plan avoided the conflict the model would have caused.'],
            'evidence_type': 'scenario',
        },
        {
            'id': 'G9', 'title': 'Runway safety and closures', 'category': 'Runway',
            'today': 'Runway status lights and ground radar at major airports; re-planning after a closure is manual.',
            'risk': 'Incursions, and slow re-sequencing after a closure or go-around.',
            'fix': 'Runway-occupancy-aware sequencing that blocks closed or occupied runways and re-plans every arrival with conflict-free slots.',
            'where': ['Runway operations', 'Scenarios: Runway incursion, Runway closure, Go-around'],
            'relationship': 'Complements ground surveillance with planning support.',
            'evidence': ['Scenario benchmark: runway conflicts and closure violations removed in every runway scenario.'],
            'evidence_type': 'scenario',
        },
    ]
