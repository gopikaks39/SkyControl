# Gap analysis: where today's ATC is weak and what SkyControl adds

SkyControl does not try to replace controllers or the automation they already use (STCA, MTCD, CLAM, AMAN/XMAN, CPDLC).
It targets gaps that remain between those tools and the people who use them, and every fix is evaluated on the real
London-Amsterdam OpenSky recording (906 aircraft, 90 minutes) or, where real data cannot answer the question, with a
stated model and a sensitivity analysis. The numbers below are generated from the cached analysis (`/api/analysis`).

| Gap | Category | Evidence type |
|---|---|---|
| G1 Voice readback and hearback errors | Human communication | measured component + modelled system |
| G2 Similar callsigns on the same frequency | Human communication | measured on real data |
| G3 Short look-ahead and nuisance conflict alerts | Separation | measured on real data |
| G4 Untrusted surveillance: duplicates and dropouts | Surveillance | measured on real data |
| G5 Arrival delay absorbed in low-level holding | Efficiency | measured on real data + modelled saving |
| G6 Emergency handling depends on one controller's memory and phone calls | Emergency | real traffic + modelled workflow |
| G7 Level busts seen late | Separation | measured on real tracks with injected events |
| G8 Automation that cannot say when it should not be trusted | Automation | scenario |
| G9 Runway safety and closures | Runway | scenario |

## G1. Voice readback and hearback errors

**Today.** Voice R/T. The controller must hear and catch a wrong readback; CPDLC exists only for some en-route clearances.

**Risk.** A wrong level, heading or frequency is flown when the controller misses the wrong readback.

**SkyControl fix.** Structured clearances, datalink for routine items, and automatic readback verification of every voice readback (typed or speech-to-text).

**Relationship to current ATC.** Complements CPDLC; adds a second check behind the controller's hearback.

**Where to see it.** Communication assistant, Scenario: Readback error

**Evidence.**

* Verifier on 3,000 generated readbacks with 5% speech-recognition noise: 98.0% of errors caught, 0.22% false errors.
* Sector-hour Monte Carlo (modelled): undetected errors 40.55 to 3.59 per 10,000 clearances (91.1% fewer); frequency occupancy 45.1 to 16.9 min/h.

## G2. Similar callsigns on the same frequency

**Today.** Planning-stage deconfliction of airline flight numbers and controller vigilance; incidents found afterwards in reports.

**Risk.** The wrong aircraft takes an instruction meant for another.

**SkyControl fix.** Live similarity scoring of every pair sharing airspace, label warnings, logon-addressed datalink and WRONG_AIRCRAFT readback detection.

**Relationship to current ATC.** Extends airline callsign-deconfliction into the tactical phase.

**Where to see it.** 3D airspace (similar-callsign layer), Communication assistant, Scenario: Callsign confusion

**Evidence.**

* Real recording: 10 similar pairs co-present within 40 NM / 10,000 ft, involving 2.2% of aircraft (e.g. BAW425/BAW725 holding together at OCK).

## G3. Short look-ahead and nuisance conflict alerts

**Today.** STCA warns about 2 minutes ahead with straight-line extrapolation; MTCD where deployed relies on flight-plan intent.

**Risk.** Late warnings, and alert fatigue when most alerts are for aircraft already cleared to safe levels.

**SkyControl fix.** Intent-aware 5-minute probe: learned trajectory prediction, cleared levels from digital clearances, duplicate-target merging and hysteresis.

**Relationship to current ATC.** Complements STCA (the safety net stays); extends MTCD with learned trajectories.

**Where to see it.** 3D airspace (predicted conflicts), Statistical analysis, Scenario: Converging traffic

**Evidence.**

* Real recording, 5-min prediction error on held-out traffic: 6.845 NM to 4.482 NM (34.5% better).
* Alerts per hour: naive 5-min probe 522.7, SkyControl probe 145.3 (72.2% fewer), close to the 2-min safety net (148.7) while looking 2.5x further ahead.

## G4. Untrusted surveillance: duplicates and dropouts

**Today.** Tracker quality is assumed; a frozen or duplicated track can look valid on the display.

**Risk.** False alerts from ghost targets, needless instructions, and decisions based on stale positions.

**SkyControl fix.** Integrity monitor: address bit-error and co-location rules for duplicates, dead-reckoned coasting with uncertainty, and an automatic switch to MANUAL when integrity is low.

**Relationship to current ATC.** Adds an integrity layer in front of existing safety nets.

**Where to see it.** 3D airspace (duplicates, coasting), Scenarios: Ghost target, Surveillance gap

**Evidence.**

* Real recording: 21 duplicate-target pairs; 234 dropouts longer than 60 s.
* Coasting error at reappearance: frozen 6.24 NM vs dead-reckoned 1.48 NM.

## G5. Arrival delay absorbed in low-level holding

**Today.** AMAN/XMAN sequence arrivals, but much delay is still taken in stacks decided near the TMA boundary.

**Risk.** Fuel burn and CO2 at low level, and workload in the stacks.

**SkyControl fix.** Hold prediction while aircraft are 30-80 NM out, and speed advisories (linear holding) over an extended horizon.

**Relationship to current ATC.** Extends AMAN with a learned hold prediction.

**Where to see it.** 3D airspace (holding layer), Statistical analysis, Scenario: Traffic overload

**Evidence.**

* Real recording: 27 holds, 268.2 aircraft-minutes in 90 min (about 10728 kg fuel at 40 kg/min).
* Absorbable by 10% speed control over 350 NM (modelled): 49.0%. Hold predictor test AUC 0.759 (small sample), mean warning 11.5 min before the hold.

## G6. Emergency handling depends on one controller's memory and phone calls

**Today.** Checklists, mental selection of alternates, telephone coordination, then voice instructions one aircraft at a time.

**Risk.** Slow, error-prone handling while other traffic still needs service.

**SkyControl fix.** Emergency assistant: suitable-airport ranking, emergency path checked against real traffic, automatic level-change proposals, re-sequencing and digital coordination.

**Relationship to current ATC.** Supports the controller; decisions stay with the controller and supervisor.

**Where to see it.** 3D airspace (inject emergency), Scenarios: Fuel, Medical, Engine failure, Emergency descent

**Evidence.**

* 60 emergencies injected into real traffic: 2.73 conflicts with real aircraft per case on average, 91.5% resolved by a verified level change, plan computed in 90.0 ms (median).
* Modelled time to all instructions: 190.842 s conventional vs 47.8 s hybrid.

## G7. Level busts seen late

**Today.** CLAM exists where the cleared level is entered in the system; otherwise STCA sees the bust only when traffic is close.

**Risk.** Loss of separation after an altitude deviation.

**SkyControl fix.** Cleared levels come from the digital clearance record, so adherence is checked continuously with a 300 ft tolerance.

**Relationship to current ATC.** Extends CLAM by guaranteeing the cleared level is always known.

**Where to see it.** Scenario: Level bust, AI models (anomaly + CLAM)

**Evidence.**

* Injected emergencies in real tracks: rule 27, learned detector 50, hybrid 52, CLAM with clearance record 81 of 81 detected.

## G8. Automation that cannot say when it should not be trusted

**Today.** Tools are on or off; confidence and data quality are not shown; automation bias is a known risk.

**Risk.** A confident but wrong prediction is followed, or a good tool is ignored.

**SkyControl fix.** Adaptive automation with explicit context switches (AUTO / CONSENT / ADVISORY / MANUAL) driven by severity, confidence, data quality, disagreement and security.

**Relationship to current ATC.** Governs every SkyControl function; humans keep authority.

**Where to see it.** Every scenario (context-switch step), AI models (policy simulator), Scenario: AI disagreement

**Evidence.**

* Scenario: the learned model predicted a turn away; the rule-based check disagreed, automation dropped to MANUAL and the conservative plan avoided the conflict the model would have caused.

## G9. Runway safety and closures

**Today.** Runway status lights and ground radar at major airports; re-planning after a closure is manual.

**Risk.** Incursions, and slow re-sequencing after a closure or go-around.

**SkyControl fix.** Runway-occupancy-aware sequencing that blocks closed or occupied runways and re-plans every arrival with conflict-free slots.

**Relationship to current ATC.** Complements ground surveillance with planning support.

**Where to see it.** Runway operations, Scenarios: Runway incursion, Runway closure, Go-around

**Evidence.**

* Scenario benchmark: runway conflicts and closure violations removed in every runway scenario.

## How to read the evidence

* **Measured on real data**: computed from the recorded positions; learned models are always tested on data they did not see (temporal split or cross-fitting).
* **Modelled**: depends on stated assumptions (communication error rates, task times, fuel burn). Each modelled result has a sensitivity sweep.
* **Scenario**: a constructed exercise that demonstrates behaviour; it is not a statistical result.

Paired comparisons use the one-sided Wilcoxon signed-rank test and a bootstrap 95% confidence interval of the mean paired improvement. Small samples (for example the 8 real encounters) are reported as indicative.
