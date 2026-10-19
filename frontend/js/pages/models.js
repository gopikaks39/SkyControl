// AI models and the automation (context-switch) policy, with an interactive simulator.
import { api, badge, esc, fmt, head, levelBadge, panel, table } from '../core.js';

export async function render(root) {
  root.innerHTML = '<div>' + head('AI support', 'AI models and automation policy',
    'What each learned component does, what it was trained on, how it was tested and where it must not be trusted. The automation policy decides, case by case, whether SkyControl may act, propose, advise or step back to MANUAL.') +
    '<div id="sim"></div><div id="cards" class="grid2"></div></div>';
  const page = root.firstElementChild;
  const m = await api('/models');
  const p = m.trajectory_predictor, h = m.hold_predictor, a = m.anomaly_detector, v = m.readback_verifier;
  const card = (title, kind, body, limits) => `<section class="panel"><div class="panel-head"><h3>${title}</h3>${badge(kind, 'blue')}</div>${body}
    <div class="notice warn" style="margin-top:10px"><b>Limits.</b> ${esc(limits)}</div></section>`;
  page.querySelector('#cards').innerHTML = [
    card('Learned trajectory predictor', 'Gradient-boosted trees', `<p>${esc(p.method)}</p>${table(['Horizon', 'Straight line', 'Learned', 'Gain'],
      p.horizons.map((x) => `<tr><td>${x.horizon_s}s</td><td class="num">${x.baseline_mean} NM</td><td class="num"><b>${x.proposed_mean} NM</b></td><td class="num delta-good">−${x.relative_improvement_pct}%</td></tr>`).join(''))}
      <p style="font-size:12px;margin-top:8px">Features: ${p.features.map(esc).join(', ')}.</p>`,
      'Trained on 60 minutes of one region; it learns that region\'s routes and must be retrained elsewhere. Intent changes (new clearances) are not predictable from kinematics alone.'),
    card('Hold predictor', 'Logistic regression', h.available ? `<p>${esc(h.method)}</p><div class="row">${badge(`AUC ${h.test_auc} ${h.test_auc_ci95 ? `[${h.test_auc_ci95.join(', ')}]` : ''}`, 'green')}
      ${badge(`recall ${h.recall}`, 'blue')}${badge(`precision ${h.precision}`, 'blue')}${badge(`warning ${h.mean_lead_time_min} min`, 'violet')}</div>` : `<p>${esc(h.reason)}</p>`,
      'Small sample (one 90-minute recording); probabilities are indicative and must be validated on more days before use.'),
    card('Emergency anomaly detector', 'Isolation forest + rules + CLAM', `<p>${esc(a.method)}</p>${table(['Injected event', 'Rule', 'Learned', 'Hybrid', 'CLAM'],
      a.detection.map((d) => `<tr><td>${esc(d.kind)}</td><td class="num">${d.rule_detected}/${d.injections}</td><td class="num">${d.ml_detected}/${d.injections}</td>
      <td class="num"><b>${d.hybrid_detected}/${d.injections}</b></td><td class="num">${d.clam_detected}/${d.injections}</td></tr>`).join(''))}`, a.limitation),
    card('Readback verifier', 'Rule-based parser', `<p>Parses ICAO phraseology and speech-to-text transcripts (spoken digits, NATO letters, telephony designators) and compares each safety-related item with the structured clearance.
      Dropped digits become "confirm" requests instead of false errors.</p>${table(['Input', 'Errors caught', 'False errors', 'Confirm requests'], [['Clean text', v.clean], ['5% ASR noise', v.asr_5pct]].map(([n, x]) =>
      `<tr><td>${n}</td><td class="num">${(x.detection_rate * 100).toFixed(1)}%</td><td class="num">${(x.hard_false_alarm_rate * 100).toFixed(2)}%</td><td class="num">${(x.confirm_request_rate * 100).toFixed(1)}%</td></tr>`).join(''))}`, v.caveat),
  ].join('');

  const levels = Object.entries(m.automation_levels).map(([k, d]) => `<div class="msg">${levelBadge(k)} ${esc(d)}</div>`).join('');
  page.querySelector('#sim').innerHTML = panel('Context-switch simulator', `<div class="grid2"><div>
      <div class="form-grid">
        <label>Severity<select data-k="severity"><option>Low</option><option selected>High</option><option>Critical</option></select></label>
        <label>Plan / model confidence <b id="v-confidence">0.90</b><input type="range" data-k="confidence" min="0" max="1" step="0.01" value="0.9"></label>
        <label>Surveillance integrity <b id="v-data_quality">0.95</b><input type="range" data-k="data_quality" min="0" max="1" step="0.01" value="0.95"></label>
        <label>Controller workload <b id="v-workload">0.50</b><input type="range" data-k="workload" min="0" max="1" step="0.01" value="0.5"></label>
        <label>Anomaly / novelty score <b id="v-novelty">0.10</b><input type="range" data-k="novelty" min="0" max="1" step="0.01" value="0.1"></label>
        <div><label><input type="checkbox" data-k="disagreement" style="width:auto"> Learned model disagrees with the safety rule</label>
        <label><input type="checkbox" data-k="security" style="width:auto"> Security event</label></div></div></div>
      <div><div id="decision"></div><h4 style="margin-top:14px">The four levels</h4>${levels}</div></div>`, badge('INTERACTIVE', 'violet'));

  const decide = async () => {
    const body = {};
    page.querySelectorAll('[data-k]').forEach((el) => {
      body[el.dataset.k] = el.type === 'checkbox' ? el.checked : el.type === 'range' ? Number(el.value) : el.value;
      const label = page.querySelector(`#v-${el.dataset.k}`);
      if (label) label.textContent = Number(el.value).toFixed(2);
    });
    const r = await api('/automation/decide', 'POST', body);
    page.querySelector('#decision').innerHTML = `<div class="approval ${r.level === 'AUTO' || r.level === 'CONSENT' ? 'ok' : ''}">
      <div class="big-number">${levelBadge(r.level)}</div><p style="margin:8px 0 4px;color:var(--ink)">${esc(r.description)}</p>
      <small>${r.approver ? `Approval by: <b>${esc(r.approver)}</b>` : 'No approval needed; controller can veto.'}</small>
      <ul style="font-size:12.5px;margin:8px 0 0">${r.reasons.map((x) => `<li>${esc(x)}</li>`).join('')}</ul></div>`;
  };
  page.querySelector('#sim').addEventListener('input', decide);
  decide();
}
