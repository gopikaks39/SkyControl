"""Adaptive automation: when SkyControl may act, propose, or must step back.

Gap addressed: today's ATC automation is either on or off. Safety nets alert
but never explain how confident they are, and nothing tells the controller
when the automation itself should not be trusted (degraded surveillance, a
model outside its experience, a security event). SkyControl makes the level
of automation an explicit, logged decision that can change during an event
(a "context switch"), following the levels-of-automation idea of
Parasuraman, Sheridan & Wickens (2000).

Levels, from most to least automated:

AUTO      routine, low-risk, high-confidence actions are executed digitally;
          the controller monitors and can veto.
CONSENT   the system proposes a verified plan; one click from the
          controller executes it.
ADVISORY  the system shows ranked options with evidence; the controller (a
          supervisor for critical events) decides.
MANUAL    the automation steps back to information only; the human is in
          command and the system records and monitors.
"""
from __future__ import annotations

LEVELS = ('MANUAL', 'ADVISORY', 'CONSENT', 'AUTO')
DESCRIPTIONS = {
    'AUTO': 'Executes routine digital clearances; controller monitors and can veto.',
    'CONSENT': 'Proposes a verified plan; one controller click executes it.',
    'ADVISORY': 'Shows ranked options and evidence; the human decides.',
    'MANUAL': 'Information only; the controller is in command.',
}


def decide(severity='Low', confidence=0.95, data_quality=1.0, workload=0.5, disagreement=False,
           security=False, novelty=0.0):
    """Return (level, approver, reasons) for the current context.

    severity: Low | High | Critical
    confidence: 0-1 agreement between the planner's checks and the learned models
    data_quality: 0-1 surveillance integrity (freshness, duplicates, gaps)
    workload: 0-1 controller workload estimate (aircraft and open alerts on frequency)
    disagreement: learned model and deterministic safety rule disagree
    security: unlawful interference or other security event
    novelty: 0-1 anomaly score; high means the situation is unlike the training data
    """
    reasons = []
    if security:
        reasons.append('Security event: decisions stay with the human chain of command.')
        return 'MANUAL', 'supervisor', reasons
    if data_quality < 0.6:
        reasons.append(f'Surveillance integrity {data_quality:.0%} is below 60%: automation cannot be trusted.')
        return 'MANUAL', 'controller', reasons
    if disagreement:
        reasons.append('The learned model disagrees with the deterministic safety rule; the rule wins and a human decides.')
        return 'MANUAL', 'controller', reasons
    if novelty > 0.8:
        reasons.append('Situation is outside the learned traffic patterns (high anomaly score).')
        return 'ADVISORY', 'supervisor' if severity == 'Critical' else 'controller', reasons

    if severity == 'Critical':
        if confidence < 0.7:
            reasons.append(f'Critical event with low plan confidence ({confidence:.0%}).')
            return 'MANUAL', 'supervisor', reasons
        reasons.append('Critical event: the plan is verified but a supervisor must authorise it.')
        return 'ADVISORY', 'supervisor', reasons
    if severity == 'High':
        if confidence >= 0.85:
            reasons.append(f'High-severity event with a verified plan (confidence {confidence:.0%}).')
            level = 'CONSENT'
        else:
            reasons.append(f'Plan confidence {confidence:.0%} is below 85%.')
            level = 'ADVISORY'
        return level, 'controller', reasons
    if confidence >= 0.9 and data_quality >= 0.9:
        reasons.append('Routine traffic, high confidence and clean data.')
        if workload > 0.7:
            reasons.append('High controller workload: routine actions are delegated (adaptive automation).')
        return 'AUTO', None, reasons
    reasons.append('Routine traffic but confidence or data quality is not high enough for AUTO.')
    return 'CONSENT', 'controller', reasons


def requires_approval(level):
    return level != 'AUTO'


def approver_for(level, severity):
    if level == 'AUTO':
        return None
    if severity == 'Critical' or level == 'MANUAL' and severity != 'Low':
        return 'supervisor'
    return 'controller'
