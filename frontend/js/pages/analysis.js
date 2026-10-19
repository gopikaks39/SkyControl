// Statistical analysis: real-data evidence, modelled comparisons and the scenario benchmark.
import { analysis, badge, esc, fmt, head, kpi, levelBadge, loading, panel, table } from '../core.js';
import { C, bars, doughnut, lines, scatter } from '../charts.js';

const TABS = [['summary', 'Summary'], ['conflicts', 'Conflict prediction'], ['surveillance', 'Surveillance integrity'], ['comms', 'Communication'],
  ['holding', 'Holding & AMAN'], ['emergency', 'Emergencies'], ['scenarios', 'Scenario benchmark'], ['dataset', 'Dataset']];

const pv = (p) => (p === null || p === undefined ? 'n/a' : p < 0.001 ? 'p < 0.001' : `p = ${p.toFixed(3)}`);
const ci = (c) => (c && c[0] !== null ? `[${c[0]}, ${c[1]}]` : '');
const tag = (kind) => ({ real: badge('MEASURED · REAL DATA', 'green'), model: badge('MODELLED', 'orange'), scen: badge('SCENARIO', 'violet'), mix: badge('REAL TRAFFIC + MODEL', 'blue') }[kind]);

export async function render(root) {
  root.innerHTML = '<div>' + head('Results', 'Statistical analysis',
    'How SkyControl complements and enhances today\'s ATC. Every result says whether it was measured on the real London–Amsterdam recording, modelled from stated assumptions, or demonstrated in a constructed scenario. Paired tests use the Wilcoxon signed-rank test with bootstrap 95% confidence intervals.',
    '<a href="/api/analysis/export"><button>Download all results (JSON)</button></a>') +
    `<div class="tabs" id="tabs">${TABS.map(([k, l], i) => `<button data-tab="${k}" class="${i ? '' : 'active'}">${l}</button>`).join('')}</div><div id="tab">${loading('Loading analysis (first start computes it from the recording, about a minute)…')}</div></div>`;
  const page = root.firstElementChild;
  const a = await analysis();
  const show = (k) => {
    page.querySelectorAll('#tabs button').forEach((b) => b.classList.toggle('active', b.dataset.tab === k));
    const box = page.querySelector('#tab');
    box.innerHTML = '';
    RENDER[k](box, a);
  };
  page.querySelector('#tabs').addEventListener('click', (e) => { if (e.target.dataset.tab) show(e.target.dataset.tab); });
  show('summary');
}

const RENDER = {
  summary(box, a) {
    const p = Object.fromEntries(a.prediction.horizons.map((h) => [h.horizon_s, h]));
    const m = Object.fromEntries(a.conflicts.methods.map((x) => [x.key, x]));
    const comm = a.communication.headline;
    const sc = a.scenarios;
    const rows = [
      ['Trajectory prediction, 5 min', `${p[300].baseline_mean} NM mean error (straight line)`, `${p[300].proposed_mean} NM (learned)`, `−${p[300].relative_improvement_pct}% · ${pv(p[300].wilcoxon_p_one_sided)} · n=${fmt.n(p[300].n)}`, 'real'],
      ['Trajectory prediction, 2 min', `${p[120].baseline_mean} NM`, `${p[120].proposed_mean} NM`, `−${p[120].relative_improvement_pct}% · ${pv(p[120].wilcoxon_p_one_sided)}`, 'real'],
      ['Medium-term conflict alerts', `${m.naive_probe.alerts_per_hour}/h (naive 5-min probe)`, `${m.intent_probe.alerts_per_hour}/h`, `−${a.conflicts.alert_reduction_vs_naive_probe_pct}% alerts; STCA-style 2-min net ${m.stca.alerts_per_hour}/h`, 'real'],
      ['Warning before real encounters', `${m.stca.mean_warning_s}s mean (2-min net)`, `${m.intent_probe.mean_warning_s}s (5-min probe)`, `n=${m.stca.encounters_evaluated} encounters (small sample)`, 'real'],
      ['Dropped-track position error', `${a.surveillance.coasting.frozen_mean_error_nm} NM (frozen)`, `${a.surveillance.coasting.coasted_mean_error_nm} NM (coasted)`, `−${a.surveillance.coasting.comparison.relative_improvement_pct}% · ${pv(a.surveillance.coasting.comparison.wilcoxon_p_one_sided)} · n=${a.surveillance.coasting.cases}`, 'real'],
      ['Duplicate (ghost) targets', 'Trusted as aircraft', `${a.surveillance.ghosts.pair_count} pairs merged`, `${a.surveillance.ghosts.share_of_observations_pct}% of observations`, 'real'],
      ['Similar callsigns sharing airspace', 'Vigilance only', `${a.callsigns.pair_count} pairs flagged live`, `${a.callsigns.share_of_aircraft_pct}% of aircraft involved`, 'real'],
      ['Undetected communication errors', `${comm.voice_undetected_per_10k} per 10k clearances`, `${comm.hybrid_undetected_per_10k}`, `−${comm.relative_reduction_pct}% · CI of reduction ${ci(comm.reduction_per_10k_ci95)}`, 'model'],
      ['Frequency occupancy', `${comm.voice_frequency_min_per_hour} min/h`, `${comm.hybrid_frequency_min_per_hour} min/h`, 'Datalink for routine clearances', 'model'],
      ['Emergency kinematic detection', `${a.anomaly.totals.rule}/${a.anomaly.injections_total} (fixed rule)`, `${a.anomaly.totals.hybrid}/${a.anomaly.injections_total} hybrid; ${a.anomaly.totals.clam} with CLAM`, 'Injected into real tracks', 'real'],
      ['Holding at low level', `${a.holding.stack_holding_minutes} aircraft-min`, `${a.holding.aman.absorbable_minutes_extended_horizon} min absorbable en route`, `~${fmt.n(a.holding.aman.fuel_saved_kg_extended)} kg fuel saved (assumptions)`, 'mix'],
      ['Emergency in real traffic', `${a.emergency_injection.workflow.baseline_mean}s to all instructions`, `${a.emergency_injection.workflow.proposed_mean}s`, `${a.emergency_injection.resolved_share_pct}% of conflicts auto-resolved · n=${a.emergency_injection.count}`, 'mix'],
      ['21 scenarios: safety checks', `${sc.totals.before.conflict_pairs} conflict pairs, ${sc.totals.before.runway_conflicts} runway, ${sc.totals.before.hazard_breaches} hazard`, `${sc.totals.after.conflict_pairs}, ${sc.totals.after.runway_conflicts}, ${sc.totals.after.hazard_breaches}`, `All plans verified: ${sc.all_valid}`, 'scen'],
      ['21 scenarios: controller workflow', `${sc.workflow_time.baseline_mean}s mean`, `${sc.workflow_time.proposed_mean}s`, `−${sc.workflow_time.relative_improvement_pct}% · ${sc.transmissions.baseline} → ${sc.transmissions.hybrid} transmissions`, 'model'],
    ];
    box.innerHTML = panel('Where SkyControl complements current ATC', table(['Measure', 'Conventional / baseline', 'With SkyControl', 'Effect and test', 'Evidence'],
      rows.map((r) => `<tr><td><b>${esc(r[0])}</b></td><td>${esc(r[1])}</td><td><b>${esc(r[2])}</b></td><td><small>${esc(r[3])}</small></td><td>${tag(r[4])}</td></tr>`).join(''))) +
      `<div class="notice">Interpretation. SkyControl does not need to beat ATC: in every row the controller and the existing safety nets stay in place.
       The measured gains come from information today's tools lack (learned traffic patterns, cleared levels from digital clearances, surveillance integrity) and from taking routine work off the voice frequency.
       Modelled rows depend on the stated assumptions, which are shown with sensitivity analyses in their tabs.</div>`;
  },

  conflicts(box, a) {
    const pr = a.prediction, cf = a.conflicts;
    box.innerHTML = `<div class="grid2">${panel('Trajectory prediction error on held-out real traffic', '<div class="chart-box"><canvas id="c1"></canvas></div>' +
      `<p style="font-size:12px">${esc(pr.method)}</p>` + table(['Horizon', 'Straight line', 'Learned', 'p95 line → learned', 'Improvement', 'Test'], pr.horizons.map((h) => `<tr><td>${h.horizon_s}s</td>
      <td class="num">${h.baseline_mean} NM</td><td class="num"><b>${h.proposed_mean} NM</b></td><td class="num">${h.baseline_p95} → ${h.proposed_p95}</td>
      <td class="num delta-good">−${h.relative_improvement_pct}%<br><small>CI ${ci(h.mean_improvement_ci95)}</small></td><td><small>${pv(h.wilcoxon_p_one_sided)}<br>n=${fmt.n(h.n)}</small></td></tr>`).join('')), tag('real'))}
      ${panel('5-minute error by altitude band', '<div class="chart-box"><canvas id="c2"></canvas></div><h4>What the model relies on (permutation importance, 5 min)</h4><div class="chart-box short"><canvas id="c3"></canvas></div>', tag('real'))}</div>
      <div class="grid2">${panel('Conflict alerting on the real recording', '<div class="chart-box"><canvas id="c4"></canvas></div>' + table(['Method', 'Look-ahead', 'Alerts/h', 'Nuisance', 'Alerted before encounter', 'Mean warning'],
        cf.methods.map((m) => `<tr><td><b>${esc(m.name)}</b></td><td class="num">${m.lookahead_s}s</td><td class="num">${m.alerts_per_hour}</td><td class="num">${m.nuisance_share_pct}%</td>
        <td class="num">${m.alerted_before_encounter}/${m.encounters_evaluated}</td><td class="num">${m.mean_warning_s}s</td></tr>`).join('')) +
        `<p style="font-size:12px">${esc(cf.truth_definition)} ${esc(cf.cleared_level_note)}</p><div class="notice">${esc(cf.interpretation)}</div>`, tag('real'))}
      ${panel('Real proximity encounters', `<p style="font-size:12px">${cf.encounter_pairs} pairs came inside the screening volume. Context: ${Object.entries(cf.encounter_contexts).map(([k, v]) => `${esc(k)} (${v})`).join(', ')}. Encounters are not necessarily losses of separation.</p>` +
        table(['Pair', 'Context', 'Closest', 'Vertical'], cf.encounters.map((e) => `<tr><td><span class="callsign">${esc(e.aircraft_a)}</span> / <span class="callsign">${esc(e.aircraft_b)}</span></td>
          <td><small>${esc(e.context)}</small></td><td class="num">${e.closest_nm} NM</td><td class="num">${e.vertical_ft} ft</td></tr>`).join('')) +
        (cf.warning_time_test ? `<p style="font-size:12px;margin-top:8px">Paired warning time (STCA-style vs SkyControl probe): +${cf.warning_time_test.mean_improvement}s mean, CI ${ci(cf.warning_time_test.mean_improvement_ci95)}, ${pv(cf.warning_time_test.wilcoxon_p_one_sided)}, n=${cf.warning_time_test.n}. Small sample: indicative only.</p>` : ''), tag('real'))}</div>`;
    bars(box.querySelector('#c1'), pr.horizons.map((h) => `${h.horizon_s}s`), [
      { label: 'Straight-line extrapolation', data: pr.horizons.map((h) => h.baseline_mean), color: C.base },
      { label: 'SkyControl learned predictor', data: pr.horizons.map((h) => h.proposed_mean), color: C.sky }], { y: 'mean error (NM)' });
    const bands = [...new Set(pr.by_altitude_band.filter((b) => b.horizon_s === 300).map((b) => b.band))];
    const b300 = pr.by_altitude_band.filter((b) => b.horizon_s === 300);
    bars(box.querySelector('#c2'), bands, [{ label: 'Straight line', data: b300.map((b) => b.baseline_mean), color: C.base },
      { label: 'Learned', data: b300.map((b) => b.proposed_mean), color: C.sky }], { y: 'mean error at 5 min (NM)' });
    bars(box.querySelector('#c3'), pr.feature_importance.map((f) => f.feature), [{ label: 'error increase when shuffled (NM)', data: pr.feature_importance.map((f) => f.error_increase_nm), color: C.violet }], { horizontal: true, legend: false });
    bars(box.querySelector('#c4'), cf.methods.map((m) => m.name.replace('SkyControl ', 'SC ')), [{ label: 'Alerts per hour', data: cf.methods.map((m) => m.alerts_per_hour),
      color: cf.methods.map((m) => (m.filtered ? C.sky : C.base)) }], { y: 'alerts per hour', legend: false });
  },

  surveillance(box, a) {
    const s = a.surveillance;
    box.innerHTML = `<div class="kpis">${kpi('Duplicate target pairs', s.ghosts.pair_count, `${s.ghosts.share_of_observations_pct}% of observations`, 'warn')}
      ${kpi('Track dropouts > 60 s', s.gaps.count, `${s.gaps.tracks_affected} of ${s.gaps.tracks_total} tracks`, 'warn')}
      ${kpi('Frozen position error', `${s.coasting.frozen_mean_error_nm} NM`, 'mean at reappearance', 'bad')}
      ${kpi('Coasted position error', `${s.coasting.coasted_mean_error_nm} NM`, `−${s.coasting.comparison.relative_improvement_pct}% · ${pv(s.coasting.comparison.wilcoxon_p_one_sided)}`, 'accent')}</div>
      <div class="grid2">${panel('Dropout length (real tracks)', '<div class="chart-box"><canvas id="s1"></canvas></div>', tag('real'))}
      ${panel('Position error after a dropout: frozen vs dead-reckoned', '<div class="chart-box"><canvas id="s2"></canvas></div>', tag('real'))}</div>` +
      panel('Duplicate (ghost) targets found in the recording', `<p style="font-size:12px">${esc(s.ghosts.method)}</p>` + table(['Real aircraft', 'Ghost', 'Address bit errors', 'Frames together', 'Min separation'],
        s.ghosts.pairs.map((g) => `<tr><td><span class="callsign">${esc(g.real_callsign)}</span> <small class="mono">${esc(g.real_icao)}</small></td><td><small class="mono">${esc(g.ghost_icao)}</small> ${esc(g.ghost_callsign)}</td>
        <td class="num">${g.address_bit_errors}</td><td class="num">${g.frames_together}</td><td class="num">${g.min_separation_nm} NM</td></tr>`).join('')), tag('real'));
    bars(box.querySelector('#s1'), s.gaps.histogram.map((h) => h.range), [{ label: 'dropouts', data: s.gaps.histogram.map((h) => h.count), color: C.amber }], { y: 'count', legend: false });
    scatter(box.querySelector('#s2'), [{ label: 'Frozen last position', data: s.coasting.scatter.map((p) => ({ x: p.gap_s, y: p.frozen_nm })), color: C.base },
      { label: 'Dead-reckoned coast', data: s.coasting.scatter.map((p) => ({ x: p.gap_s, y: p.coasted_nm })), color: C.sky }], { x: 'dropout length (s)', y: 'error at reappearance (NM)' });
  },

  comms(box, a) {
    const c = a.communication, h = c.headline;
    const rb = (v) => Object.entries(v.by_error_type).map(([k, x]) => `<tr><td>${esc(k)}</td><td class="num">${x.n}</td><td class="num">${(x.rate * 100).toFixed(1)}%</td></tr>`).join('');
    box.innerHTML = `<div class="kpis">${kpi('Undetected errors (voice)', h.voice_undetected_per_10k, 'per 10,000 clearances', 'bad')}${kpi('Undetected errors (hybrid)', h.hybrid_undetected_per_10k, `−${h.relative_reduction_pct}% · CI ${ci(h.reduction_per_10k_ci95)}`, 'accent')}
      ${kpi('Frequency occupancy', `${h.voice_frequency_min_per_hour} → ${h.hybrid_frequency_min_per_hour}`, 'minutes per busy hour')}${kpi('Transmissions per hour', `${h.voice_transmissions_per_hour} → ${h.hybrid_transmissions_per_hour}`, 'voice calls incl. readbacks')}</div>
      <div class="grid2">${panel('Readback verifier (measured on generated readbacks)', `<div class="grid2"><div><h4>Clean text</h4>${table(['Case', 'n', 'Flagged'], rb(c.verifier_clean))}
        <p style="font-size:12px">Detection ${(c.verifier_clean.detection_rate * 100).toFixed(1)}%, false errors ${(c.verifier_clean.hard_false_alarm_rate * 100).toFixed(2)}%</p></div>
        <div><h4>5% speech-recognition noise</h4>${table(['Case', 'n', 'Flagged'], rb(c.verifier_asr_5pct))}
        <p style="font-size:12px">Detection ${(c.verifier_asr_5pct.detection_rate * 100).toFixed(1)}%, false errors ${(c.verifier_asr_5pct.hard_false_alarm_rate * 100).toFixed(2)}%, confirm requests ${(c.verifier_asr_5pct.confirm_request_rate * 100).toFixed(1)}%</p></div></div>
        <div class="notice warn">${esc(c.caveat)}</div>`, tag('real'))}
      ${panel('Datalink share: errors vs frequency time (model)', '<div class="chart-box"><canvas id="m1"></canvas></div><p style="font-size:12px">More datalink frees the frequency; voice with automatic verification has the fewest undetected errors. The default 70% balances both.</p>', tag('model'))}</div>
      ${panel('Sensitivity: undetected errors per 10k clearances under different assumptions', table(['Readback error rate', 'Hearback miss rate', 'Voice only', 'Hybrid', 'Reduction'],
        c.sensitivity.map((s) => `<tr><td class="num">${(s.readback_error_rate * 100).toFixed(1)}%</td><td class="num">${(s.hearback_miss_rate * 100).toFixed(0)}%</td>
        <td class="num">${s.voice_per_10k}</td><td class="num"><b>${s.hybrid_per_10k}</b></td><td class="num delta-good">−${s.relative_reduction_pct}%</td></tr>`).join('')) +
        `<h4 style="margin-top:12px">Assumptions</h4><ul style="font-size:12px;color:var(--muted)">${c.assumptions.sources.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`, tag('model'))}`;
    const dl = c.datalink_curve;
    lines(box.querySelector('#m1'), dl.map((d) => `${Math.round(d.datalink_share * 100)}%`), [
      { label: 'Undetected errors per 10k', data: dl.map((d) => d.hybrid_per_10k), color: C.red, yAxisID: 'y' },
      { label: 'Frequency minutes per hour', data: dl.map((d) => d.frequency_min_per_hour), color: C.sky, yAxisID: 'y1' }],
    { x: 'share of clearances by datalink', y: 'errors per 10k', y1: 'minutes per hour' });
  },

  holding(box, a) {
    const h = a.holding, m = a.hold_model;
    const stacks = Object.keys(h.timeline[0] || {}).filter((k) => k !== 't');
    box.innerHTML = `<div class="kpis">${kpi('Holds observed', h.stack_holds, `${h.total_holds - h.stack_holds} other orbits`)}${kpi('Holding time', `${h.stack_holding_minutes} min`, 'aircraft-minutes in 90 min', 'warn')}
      ${kpi('Holding fuel', `${fmt.n(h.holding_fuel_kg)} kg`, `range ${fmt.n(h.holding_fuel_range_kg[0])}–${fmt.n(h.holding_fuel_range_kg[1])} kg`, 'bad')}
      ${kpi('Absorbable en route', `${h.aman.share_absorbable_extended_pct}%`, `${fmt.n(h.aman.fuel_saved_kg_extended)} kg fuel, ${fmt.n(h.aman.co2_saved_kg_extended)} kg CO₂`, 'accent')}</div>
      <div class="grid2">${panel('Aircraft holding per stack over time', '<div class="chart-box"><canvas id="h1"></canvas></div>', tag('real'))}
      ${panel('Holding minutes per stack', '<div class="chart-box"><canvas id="h2"></canvas></div>', tag('real'))}</div>
      <div class="grid2">${panel('Predicting the hold 30-80 NM before the stack', m.available ? `<div class="kpis" style="grid-template-columns:repeat(3,1fr)">${kpi('Test AUC', m.test_auc, `CI ${ci(m.test_auc_ci95)}`)}${kpi('Recall', m.recall, `precision ${m.precision}`)}${kpi('Warning', `${m.mean_lead_time_min} min`, 'before the hold')}</div>
        <p style="font-size:12px">${esc(m.method)} Samples ${m.samples} (${m.positives_total} holds); test ${m.test_samples} (${m.positives_test} holds). Small sample: indicative.</p>` +
        table(['Feature', 'Weight'], m.coefficients.map((c) => `<tr><td>${esc(c.feature)}</td><td class="num">${c.weight}</td></tr>`).join('')) : `<p>${esc(m.reason)}</p>`, tag('real'))}
      ${panel('Holds detected', table(['Callsign', 'Stack', 'Minutes', 'Mean altitude', 'Absorbable (350 NM)'], h.aman.per_flight.map((r) => `<tr><td class="callsign">${esc(r.callsign)}</td>
        <td>${badge(r.stack, 'orange')}</td><td class="num">${r.minutes}</td><td class="num">${fmt.n((h.holds.find((x) => x.callsign === r.callsign) || {}).mean_altitude_ft)} ft</td><td class="num">${r.absorbable_extended_min} min</td></tr>`).join('')) +
        `<ul style="font-size:12px;color:var(--muted)">${h.assumptions.sources.map((x) => `<li>${esc(x)}</li>`).join('')}</ul>`, tag('mix'))}</div>`;
    lines(box.querySelector('#h1'), h.timeline.map((r) => fmt.time(r.t)), stacks.map((s, i) => ({ label: s, data: h.timeline.map((r) => r[s]), color: C.series[i % 10], fill: true })), { y: 'aircraft holding', stacked: true });
    bars(box.querySelector('#h2'), h.stacks.map((s) => s.stack), [{ label: 'aircraft-minutes', data: h.stacks.map((s) => s.total_minutes), color: C.amber }], { legend: false, y: 'minutes' });
  },

  emergency(box, a) {
    const an = a.anomaly, inj = a.emergency_injection;
    box.innerHTML = `<div class="grid2">${panel('Detecting emergency-like behaviour in real tracks', '<div class="chart-box"><canvas id="e1"></canvas></div>' +
      `<p style="font-size:12px">${esc(an.method)} False alarms on normal test traffic: rule ${(an.false_alarm_rate_rule * 100).toFixed(2)}%, learned ${(an.false_alarm_rate_ml * 100).toFixed(1)}%, hybrid ${(an.false_alarm_rate_hybrid * 100).toFixed(2)}%.</p>
       <div class="notice warn">${esc(an.limitation)}</div>`, tag('real'))}
      ${panel('Emergencies injected into real traffic', `<div class="kpis" style="grid-template-columns:repeat(2,1fr)">${kpi('Injections', inj.count, `${inj.mean_traffic_considered} real aircraft considered each`)}
        ${kpi('Conflicts with real traffic', inj.mean_conflicts, `per emergency · ${inj.share_with_conflict_pct}% had at least one`, 'warn')}
        ${kpi('Resolved automatically', `${inj.resolved_share_pct}%`, 'verified level change', 'accent')}${kpi('Plan computation', `${inj.median_compute_ms} ms`, 'median')}</div>
        <div class="chart-box short"><canvas id="e2"></canvas></div>
        <p style="font-size:12px">Workflow time (modelled from real traffic counts): ${inj.workflow.baseline_mean}s conventional vs ${inj.workflow.proposed_mean}s hybrid, ${pv(inj.workflow.wilcoxon_p_one_sided)}.</p>`, tag('mix'))}</div>` +
      panel('Injection runs', table(['Type', 'Aircraft', 'Airport', 'Distance', 'Real traffic', 'Conflicts', 'Resolved', 'Delayed arrivals', 'ms'], inj.runs.map((r) => `<tr><td>${esc(r.kind)}</td>
        <td class="callsign">${esc(r.callsign)}</td><td>${esc(r.airport)}</td><td class="num">${r.distance_nm}</td><td class="num">${r.traffic}</td><td class="num">${r.conflicts}</td><td class="num">${r.resolved}</td>
        <td class="num">${r.delayed_arrivals}</td><td class="num">${r.compute_ms}</td></tr>`).join('')), tag('mix'));
    bars(box.querySelector('#e1'), an.detection.map((d) => d.kind.replace('_', ' ')), [
      { label: 'Fixed rule (|VS| > 4,000 fpm)', data: an.detection.map((d) => d.rule_detected), color: C.base },
      { label: 'Learned anomaly detector', data: an.detection.map((d) => d.ml_detected), color: C.violet },
      { label: 'SkyControl hybrid', data: an.detection.map((d) => d.hybrid_detected), color: C.sky },
      { label: 'CLAM (clearance record)', data: an.detection.map((d) => d.clam_detected), color: C.green }], { y: `detected of ${an.detection[0].injections}` });
    bars(box.querySelector('#e2'), ['Time to all instructions (s)', 'Radio transmissions'], [
      { label: 'Conventional', data: [inj.workflow.baseline_mean, inj.mean_baseline_transmissions], color: C.base },
      { label: 'SkyControl', data: [inj.workflow.proposed_mean, inj.mean_hybrid_transmissions], color: C.sky }]);
  },

  scenarios(box, a) {
    const s = a.scenarios;
    box.innerHTML = `<div class="kpis">${kpi('Scenarios', s.count, s.all_valid ? 'all plans verified' : 'some plans fail', 'accent')}
      ${kpi('Conflict pairs', `${s.totals.before.conflict_pairs} → ${s.totals.after.conflict_pairs}`, 'baseline → SkyControl')}
      ${kpi('Runway / hazard violations', `${s.totals.before.runway_conflicts + s.totals.before.hazard_breaches} → ${s.totals.after.runway_conflicts + s.totals.after.hazard_breaches}`, 'baseline → SkyControl')}
      ${kpi('Workflow time', `−${s.workflow_time.relative_improvement_pct}%`, `${s.workflow_time.baseline_mean}s → ${s.workflow_time.proposed_mean}s (modelled)`)}
      ${kpi('Controller actions', `${s.controller_actions.baseline} → ${s.controller_actions.hybrid}`, 'all scenarios')}</div>
      <div class="grid2">${panel('Time to all instructions per scenario (modelled)', '<div class="chart-box tall"><canvas id="w1"></canvas></div>', tag('model'))}
      ${panel('Automation level chosen', '<div class="chart-box tall"><canvas id="w2"></canvas></div>', tag('scen'))}</div>` +
      panel('Per-scenario results', table(['Scenario', 'Baseline', 'Conflicts', 'Runway', 'Hazard', 'Deadline', 'Level', 'Workflow'], s.cases.map((c) => `<tr><td><b>${esc(c.title)}</b><br><small class="muted">${esc(c.category)}</small></td>
        <td><small>${esc(c.baseline_label)}</small></td><td class="num">${c.before.conflict_pairs} → <b>${c.after.conflict_pairs}</b></td><td class="num">${c.before.runway_conflicts} → <b>${c.after.runway_conflicts}</b></td>
        <td class="num">${c.before.hazard_breaches} → <b>${c.after.hazard_breaches}</b></td><td class="num">${c.before.deadline_misses} → <b>${c.after.deadline_misses}</b></td>
        <td>${levelBadge(c.automation_level)}</td><td class="num">${c.workflow.baseline_time_s}s → <b>${c.workflow.hybrid_time_s}s</b></td></tr>`).join('')) + `<p style="font-size:12px">${esc(s.method)}</p>`, tag('scen'));
    bars(box.querySelector('#w1'), s.cases.map((c) => c.title), [{ label: 'Conventional', data: s.cases.map((c) => c.workflow.baseline_time_s), color: C.base },
      { label: 'SkyControl', data: s.cases.map((c) => c.workflow.hybrid_time_s), color: C.sky }], { horizontal: true, y: 'seconds' });
    const lv = Object.entries(s.automation_levels);
    doughnut(box.querySelector('#w2'), lv.map(([k]) => k), lv.map(([, v]) => v), lv.map(([k]) => ({ AUTO: C.green, CONSENT: C.blue, ADVISORY: C.amber, MANUAL: C.red }[k])));
  },

  dataset(box, a) {
    const o = a.overview;
    box.innerHTML = `<div class="kpis">${kpi('Aircraft', fmt.n(o.aircraft), 'distinct ICAO addresses')}${kpi('Position reports', fmt.n(o.observations_used), `${o.duplicates_removed} exact duplicates removed`)}
      ${kpi('Frames', o.frames, `median ${o.median_frame_interval_s}s apart`)}${kpi('Aircraft per frame', o.mean_aircraft_per_frame, `max ${o.max_aircraft_per_frame}`)}</div>
      <div class="grid2">${panel('Traffic in the recording', '<div class="chart-box"><canvas id="d1"></canvas></div>', tag('real'))}
      ${panel('Altitude distribution of airborne reports', '<div class="chart-box"><canvas id="d2"></canvas></div>', tag('real'))}</div>
      <div class="grid2">${panel('Most frequent operators', '<div class="chart-box"><canvas id="d3"></canvas></div>', tag('real'))}
      ${panel('Provenance and limitations', `<p><b>${esc(o.dataset_name)}</b> · ${esc(o.provider)} · ${esc(o.start_utc)} to ${esc(o.end_utc)}</p><p class="mono" style="word-break:break-all">SHA-256 ${esc(o.sha256)}</p>
        <ul style="font-size:12px;color:var(--muted)">${o.limitations.map((l) => `<li>${esc(l)}</li>`).join('')}</ul>`)}</div>`;
    lines(box.querySelector('#d1'), o.traffic_series.map((r) => fmt.time(r.t)), [{ label: 'aircraft', data: o.traffic_series.map((r) => r.aircraft), color: C.grey },
      { label: 'airborne', data: o.traffic_series.map((r) => r.airborne), color: C.sky, fill: true }], { y: 'aircraft', x: 'minutes:seconds from start' });
    bars(box.querySelector('#d2'), o.altitude_histogram.map((h) => h.band), [{ label: 'reports', data: o.altitude_histogram.map((h) => h.observations), color: C.blue }], { legend: false });
    bars(box.querySelector('#d3'), o.top_operators.map((x) => x.operator), [{ label: 'aircraft', data: o.top_operators.map((x) => x.aircraft), color: C.sky }], { legend: false });
  },
};
