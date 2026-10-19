// 3D replay of the real London-Amsterdam recording with SkyControl's monitors and emergency injection.
import { api, badge, esc, fmt, guard, head, levelBadge, loading, onCleanup, panel, sevKind, state, table, toast } from '../core.js';
import { Airspace3D, altitudeColor } from '../scene3d.js';
import { coastlineXY, toXY } from '../geo.js';

let cache = null;          // tracks survive page changes

async function loadData() {
  if (cache) return cache;
  const [meta, raw] = await Promise.all([api('/airspace/meta'), api('/airspace/tracks')]);
  const tracks = raw.tracks.map((tr) => {
    const t = [], x = [], y = [], z = [];
    for (const [ts, lat, lon, alt] of tr.p) {
      const [px, py] = toXY(lat, lon);
      t.push(ts); x.push(px); y.push(py); z.push(alt);
    }
    return { id: tr.id, cs: tr.cs, dup: tr.dup, t, x, y, z };
  });
  cache = { meta, tracks, byId: new Map(tracks.map((t) => [t.id, t])) };
  return cache;
}

function sample(tr, now) {
  const { t } = tr;
  if (now < t[0] || now > t[t.length - 1]) return null;
  let lo = 0, hi = t.length - 1;
  while (hi - lo > 1) { const mid = (lo + hi) >> 1; if (t[mid] <= now) lo = mid; else hi = mid; }
  const gap = t[hi] - t[lo];
  if (gap > 120 && now - t[lo] > 60) return null;
  const f = gap ? (now - t[lo]) / gap : 0;
  const x = tr.x[lo] + (tr.x[hi] - tr.x[lo]) * f;
  const y = tr.y[lo] + (tr.y[hi] - tr.y[lo]) * f;
  const ground = tr.z[lo] < 0 || tr.z[hi] < 0;
  const ft = ground ? 0 : tr.z[lo] + (tr.z[hi] - tr.z[lo]) * f;
  const dx = tr.x[hi] - tr.x[lo], dy = tr.y[hi] - tr.y[lo];
  const heading = (Math.atan2(dx, dy) * 180 / Math.PI + 360) % 360;
  const speed = gap ? Math.hypot(dx, dy) / gap * 3600 : 0;
  return { x, y, ft, heading, speed, ground, idx: lo };
}

export async function render(root) {
  root.innerHTML = '<div>' + head('Airspace · real traffic', '3D replay of the London–Amsterdam recording',
    'Every aircraft is a real OpenSky observation (906 aircraft over 90 minutes). The overlays are what SkyControl\'s monitors would show at that moment. Click an aircraft to inspect it or to inject a simulated emergency and watch the hybrid response against the real surrounding traffic.',
    badge('REAL RECORDED DATA', 'green')) + `<div class="grid-main"><div>
      <section class="panel dark" style="padding:12px">
        <div class="viewport" id="vp"><div class="vp-overlay" id="layers"></div>
          <div class="vp-legend"><i style="background:#f5a25d"></i>low altitude <i style="background:#5fd0e6;margin-left:8px"></i>high<br>
          <i style="background:#ff5a5f"></i>predicted conflict / emergency<br><i style="background:#f2b245"></i>similar callsign
          <i style="background:#ff9d3c;margin-left:8px"></i>holding<br><i style="background:#a48cff"></i>duplicate (ghost) target</div>
          <div class="vp-hint">Drag to rotate · right-drag or shift-drag to pan · wheel to zoom · click an aircraft</div></div>
        <div class="controls-bar">
          <button class="primary small" id="play">❚❚ Pause</button>
          <select id="speed" style="width:auto"><option value="5">5×</option><option value="15" selected>15×</option><option value="30">30×</option><option value="60">60×</option><option value="1">1×</option></select>
          <input type="range" id="scrub" min="0" max="5400" step="1" value="0">
          <span class="timecode" id="tc">--:--:--</span>
          <button class="small" data-view="perspective">3D</button><button class="small" data-view="top">Top</button><button class="small" data-view="side">Side</button>
          <button class="small" id="focus-lhr">London</button>
        </div>
      </section>
      <div id="emergency"></div>
    </div><div><div id="selection"></div><div id="monitor">${loading('Loading recorded tracks…')}</div></div></div></div>`;
  const page = root.firstElementChild;
  const data = await loadData();
  const { meta, tracks } = data;
  const end = meta.frames[meta.frames.length - 1];
  const scrub = page.querySelector('#scrub');
  scrub.max = end;

  const view = new Airspace3D(page.querySelector('#vp'), { extent: 150, vScale: 1.1, aircraftScale: 2.0, grid: 10 });
  onCleanup(() => view.dispose());
  view.addCoastlines(coastlineXY());
  view.addAirports(meta.airports.map((a) => ({ ...a, ...Object.fromEntries([['x', toXY(a.lat, a.lon)[0]], ['y', toXY(a.lat, a.lon)[1]]]), heading: a.runway_heading, label: a.icao })));
  view.addFixes(meta.holding_fixes.map((f) => ({ name: f.name, x: toXY(f.lat, f.lon)[0], y: toXY(f.lat, f.lon)[1], altitude: 9000 })));
  const lhr = meta.airports.find((a) => a.icao === 'EGLL');
  const [lx, ly] = toXY(lhr.lat, lhr.lon);
  for (const r of [25, 50]) view.ring(lx, ly, r, 0x1f5562, 0.5);
  view.focus(lx + 20, ly, 6000, 220);

  const layers = { trails: true, labels: false, conflicts: true, similar: true, holding: true, ghosts: true, predictions: false };
  const names = { trails: 'Trails', labels: 'All labels', conflicts: 'Predicted conflicts', similar: 'Similar callsigns', holding: 'Holding', ghosts: 'Duplicates', predictions: '5-min predictions' };
  const drawLayers = () => {
    page.querySelector('#layers').innerHTML = Object.keys(layers).map((k) => `<button class="vp-chip ${layers[k] ? 'on' : ''}" data-layer="${k}">${names[k]}</button>`).join('');
  };
  drawLayers();

  let now = 1500, playing = true, speed = 15, selected = null, monitor = null, lastFetch = -999, fetching = false;
  let lastTrail = 0, predictions = null, lastPred = -999, emergencyPlan = null;
  scrub.value = now;

  const flags = () => {
    const f = { conflict: new Set(), similar: new Set(), hold: new Set() };
    if (!monitor) return f;
    monitor.predicted_conflicts.forEach((c) => { f.conflict.add(c.a_id); f.conflict.add(c.b_id); });
    monitor.similar_callsigns.forEach((s) => { f.similar.add(s.a); f.similar.add(s.b); });
    monitor.holding.forEach((h) => f.hold.add(h.callsign));
    return f;
  };

  const affected = () => new Set(emergencyPlan ? emergencyPlan.resolutions.map((r) => r.icao) : []);

  function drawAircraft() {
    const f = flags();
    const hit = affected();
    const emId = emergencyPlan && emergencyPlan.aircraft.icao;
    view.beginFrame();
    for (const tr of tracks) {
      const s = sample(tr, now);
      if (!s) continue;
      if (tr.dup && !layers.ghosts) continue;
      let color = altitudeColor(s.ft), cls = 'dim', label = layers.labels && tr.cs ? tr.cs : null;
      if (tr.dup) { color = 0xa48cff; cls = 'warn'; label = label || '(duplicate)'; }
      if (layers.holding && f.hold.has(tr.cs)) { color = 0xff9d3c; cls = 'warn'; label = `${tr.cs} HOLD`; }
      if (layers.similar && f.similar.has(tr.cs)) { color = 0xf2b245; cls = 'warn'; label = tr.cs; }
      if (layers.conflicts && f.conflict.has(tr.id)) { color = 0xff5a5f; cls = 'alert'; label = tr.cs || tr.id; }
      if (hit.has(tr.id)) { color = 0xffd166; cls = 'warn'; label = `${tr.cs} ↕`; }
      if (tr.id === emId) { color = 0xff3b3b; cls = 'alert'; label = `${tr.cs} MAYDAY`; }
      if (tr.id === selected) { color = 0x63f1e0; cls = 'sel'; label = `${tr.cs || tr.id} ${fmt.fl(s.ft)}`; }
      view.upsertAircraft(tr.id, { x: s.x, y: s.y, ft: s.ft, heading: s.heading, color, label, labelClass: cls, ghost: tr.dup });
    }
    view.endFrame();
  }

  function drawTrails() {
    if (!layers.trails) { view.setTrails([]); return; }
    const out = [];
    for (const tr of tracks) {
      if (now < tr.t[0] || now > tr.t[tr.t.length - 1] || (tr.dup && !layers.ghosts)) continue;
      const pts = [];
      for (let i = 0; i < tr.t.length && tr.t[i] <= now; i++) {
        if (tr.t[i] >= now - 150 && tr.z[i] >= 0) pts.push([tr.x[i], tr.y[i], tr.z[i]]);
      }
      const s = sample(tr, now);
      if (s && !s.ground) pts.push([s.x, s.y, s.ft]);
      if (pts.length > 1) out.push({ points: pts });
    }
    view.setTrails(out);
  }

  function drawPredictions() {
    if (!layers.predictions || !predictions) { view.removePath('pred-line'); view.removePath('pred-ml'); return; }
    const line = [], ml = [];
    for (const p of predictions.aircraft) {
      const tr = data.byId.get(p.id);
      const s = tr && sample(tr, now);
      if (!s) continue;
      const [ax, ay] = toXY(p.line[0], p.line[1]);
      const [bx, by] = toXY(p.learned[0], p.learned[1]);
      line.push([s.x, s.y, s.ft, ax, ay, s.ft]);
      ml.push([s.x, s.y, s.ft, bx, by, s.ft]);
    }
    view.setSegments('pred-line', line, { color: 0x8aa3a8, opacity: 0.35 });
    view.setSegments('pred-ml', ml, { color: 0x2ee6c9, opacity: 0.85 });
  }

  async function fetchMonitor(force = false) {
    if (fetching || (!force && Math.abs(now - lastFetch) < 20)) return;
    fetching = true;
    try {
      monitor = await api(`/airspace/frame?offset=${Math.round(now)}`);
      lastFetch = now;
      renderMonitor();
      if (layers.predictions && Math.abs(now - lastPred) > 30) {
        predictions = await api(`/airspace/predictions?offset=${Math.round(now)}&horizon=300`);
        lastPred = now;
        drawPredictions();
      }
    } catch (e) { /* keep animating */ } finally { fetching = false; }
  }

  function renderMonitor() {
    const m = monitor;
    page.querySelector('#monitor').innerHTML = panel(`Monitors at ${fmt.utc(m.time)}`, `
      <div class="kpis" style="grid-template-columns:repeat(3,1fr);margin-bottom:10px">
        <div class="kpi"><span>Airborne</span><strong>${m.airborne}</strong></div>
        <div class="kpi ${m.predicted_conflicts.length ? 'bad' : ''}"><span>Predicted (5 min)</span><strong>${m.predicted_conflicts.length}</strong></div>
        <div class="kpi ${m.holding.length ? 'warn' : ''}"><span>Holding</span><strong>${m.holding.length}</strong></div></div>
      <h4>Predicted conflicts (intent-aware probe)</h4>
      ${m.predicted_conflicts.length ? m.predicted_conflicts.slice(0, 6).map((c) => `<div class="msg"><span class="callsign">${esc(c.a)}</span> × <span class="callsign">${esc(c.b)}</span>
        <span class="muted">in ${c.in_seconds}s · now ${c.now_nm} NM / ${fmt.n(c.now_ft)} ft</span></div>`).join('') : '<p class="muted">None predicted in the next 5 minutes.</p>'}
      <h4>Similar callsigns sharing airspace</h4>
      ${m.similar_callsigns.length ? m.similar_callsigns.map((s) => `<div class="msg"><span class="callsign">${esc(s.a)}</span> / <span class="callsign">${esc(s.b)}</span> ${badge(s.reason, 'orange')} <span class="muted">${s.distance_nm} NM apart</span></div>`).join('') : '<p class="muted">None.</p>'}
      <h4>Holding</h4>${m.holding.length ? m.holding.map((h) => `${badge(h.stack, 'orange')} <span class="callsign">${esc(h.callsign)}</span> <small class="muted">${h.minutes_so_far} min</small>`).join(' ') : '<p class="muted">No aircraft holding.</p>'}
      <h4 style="margin-top:12px">Surveillance integrity</h4>
      <p style="font-size:12px">${m.duplicates.length} duplicate target(s) merged · ${m.coasting.length} track(s) coasting after a dropout
      ${m.coasting.slice(0, 4).map((c) => `<span class="callsign">${esc(c.callsign)}</span> (${c.stale_s}s)`).join(', ')}</p>
      <p style="font-size:11px">${esc(m.probe)}</p>`, badge('LIVE MONITOR', 'dark'));
  }

  function renderSelection() {
    const box = page.querySelector('#selection');
    const tr = selected && data.byId.get(selected);
    const s = tr && sample(tr, now);
    if (!tr || !s) { box.innerHTML = ''; return; }
    box.innerHTML = panel(`<span class="callsign">${esc(tr.cs || tr.id)}</span>`, `
      <div class="form-grid">
        <div><small class="muted">ICAO 24-bit</small><div class="mono">${esc(tr.id)}</div></div>
        <div><small class="muted">Altitude</small><div>${s.ground ? 'on ground' : fmt.ft(s.ft)}</div></div>
        <div><small class="muted">Ground speed (derived)</small><div>${fmt.n(s.speed)} kt</div></div>
        <div><small class="muted">Track</small><div>${fmt.n(s.heading)}°</div></div></div>
      ${tr.dup ? '<div class="notice warn">This track is a duplicate (ghost) of another aircraft and is merged by the integrity monitor.</div>' : ''}
      <label>Inject a simulated emergency on this real aircraft
        <select id="em-kind"><option value="low_fuel">Fuel emergency (MAYDAY FUEL)</option><option value="medical">Medical emergency (PAN PAN)</option>
        <option value="engine_failure">Engine failure (MAYDAY)</option><option value="emergency_descent">Emergency descent (MAYDAY)</option>
        <option value="lost_comms">Radio failure (squawk 7600)</option></select></label>
      <div class="row"><button class="primary" id="em-go" ${s.ground || tr.dup ? 'disabled' : ''}>Run hybrid emergency response</button>
      <button class="small" id="sel-clear">Clear</button></div>`, badge('SELECTED', 'blue'));
  }

  function renderEmergency() {
    const box = page.querySelector('#emergency');
    const r = emergencyPlan;
    if (!r) { box.innerHTML = ''; view.clearPaths('em-'); return; }
    const pts = r.path.map((p) => [...toXY(p.lat, p.lon), p.altitude_ft]);
    view.setPath('em-path', pts, { color: 0xff5a5f, opacity: 1 });
    const ap = meta.airports.find((a) => a.icao === r.chosen_airport.icao);
    const flow = r.workflow;
    const blocked = r.approver === 'supervisor' && state.user.role !== 'supervisor';
    box.innerHTML = panel(`${esc(r.title)} · <span class="callsign">${esc(r.aircraft.callsign)}</span>`, `
      <div class="notice">${esc(r.note)} Computed in ${r.compute_ms} ms.</div>
      <div class="grid2">
        <div><h4>Hybrid handling, step by step</h4><div class="pipeline">${r.steps.map((s, i) => `<div class="step done"><div class="node">${i + 1}</div>
          <div><div class="phase">${esc(s.phase)}</div><div class="detail" style="color:var(--ink)">${esc(s.detail)}</div></div></div>`).join('')}</div></div>
        <div>
          <h4>Candidate airports</h4>${table(['Airport', 'NM', 'ETA', 'Suitable'], r.airports.map((a) => `<tr><td>${esc(a.name)} <small class="muted">${esc(a.icao)}</small></td>
            <td class="num">${a.distance_nm}</td><td class="num">${a.eta_min} min</td><td>${a.suitable ? badge('yes', 'green') : `<small class="muted">${esc(a.reasons.join('; '))}</small>`}</td></tr>`).join(''))}
          <h4 style="margin-top:12px">Conflicts with real traffic → proposed resolutions</h4>
          ${table(['Aircraft', 'Conflict in', 'Proposal'], r.resolutions.map((x) => `<tr><td class="callsign">${esc(x.callsign)}</td><td class="num">${x.time_to_conflict_s}s</td>
            <td>${x.resolved ? esc(x.action) : `<span class="delta-bad">${esc(x.action)}</span>`}</td></tr>`).join(''), 'No conflicts with the recorded traffic')}
          ${r.arrival_delays.length ? `<p style="font-size:12px;margin-top:8px">Re-sequencing at ${esc(ap ? ap.name : '')}: ${r.arrival_delays.map((d) => `${esc(d.callsign)} +${d.delay_s}s`).join(', ')}</p>` : ''}
        </div></div>
      <h4>Messages drafted</h4>${r.messages.map((m) => `<div class="msg"><b>${esc(m.to)}</b> ${badge(m.channel, m.channel === 'voice' ? 'orange' : 'blue')}<div class="phr">${esc(m.text)}</div></div>`).join('')}
      <div class="compare" style="margin-top:12px">
        <div class="old"><h4>Conventional ATC (modelled)</h4><ol>${flow.baseline.steps.map((s) => `<li>${esc(s.step)} · ${s.seconds}s</li>`).join('')}</ol>
          <div class="tot">${flow.baseline.time_to_all_instructions_s}s</div><small>${flow.baseline.radio_transmissions} transmissions · ${flow.baseline.controller_actions} controller actions</small></div>
        <div class="new"><h4>SkyControl hybrid (modelled)</h4><ol>${flow.hybrid.steps.map((s) => `<li>${esc(s.step)} · ${s.seconds}s</li>`).join('')}</ol>
          <div class="tot">${flow.hybrid.time_to_all_instructions_s}s</div><small>${flow.hybrid.radio_transmissions} transmissions · ${flow.hybrid.controller_actions} controller actions</small></div></div>
      <div class="approval" style="margin-top:12px"><div class="spread"><div>Automation level ${levelBadge(r.automation_level)} · ${esc(r.reasons.join(' '))}<br>
        <small>${r.approver ? `Requires ${esc(r.approver)} approval. You are signed in as ${esc(state.user.role)}.` : 'No approval needed.'}</small></div>
        <div class="row"><button class="primary" data-review="approve" ${blocked ? 'disabled' : ''}>Approve plan</button><button data-review="reject" ${blocked ? 'disabled' : ''}>Reject</button><button id="em-close" class="small">Close</button></div></div></div>`,
    badge(r.severity, sevKind(r.severity)));
  }

  // ---------- events
  page.addEventListener('click', async (e) => {
    const layer = e.target.closest('[data-layer]');
    if (layer) {
      layers[layer.dataset.layer] = !layers[layer.dataset.layer];
      drawLayers(); drawTrails(); drawAircraft();
      if (layer.dataset.layer === 'predictions') { lastPred = -999; fetchMonitor(true); drawPredictions(); }
      return;
    }
    const v = e.target.closest('[data-view]');
    if (v) { view.view(v.dataset.view); return; }
    if (e.target.id === 'focus-lhr') { view.focus(lx, ly, 3000, 120); return; }
    if (e.target.id === 'play') {
      playing = !playing;
      e.target.textContent = playing ? '❚❚ Pause' : '▶ Play';
      return;
    }
    if (e.target.id === 'sel-clear') { selected = null; renderSelection(); drawAircraft(); return; }
    if (e.target.id === 'em-close') { emergencyPlan = null; renderEmergency(); drawAircraft(); return; }
    if (e.target.id === 'em-go') {
      e.target.disabled = true;
      const kind = page.querySelector('#em-kind').value;
      const r = await guard(() => api('/airspace/emergency', 'POST', { offset: Math.round(now), icao: selected, kind }));
      e.target.disabled = false;
      if (r) {
        emergencyPlan = r; playing = false;
        page.querySelector('#play').textContent = '▶ Play';
        renderEmergency(); drawAircraft();
        toast(`${r.title}: plan ready in ${r.compute_ms} ms (${r.conflicts} conflict(s) with real traffic).`);
        page.querySelector('#emergency').scrollIntoView({ behavior: 'smooth' });
      }
      return;
    }
    const rv = e.target.closest('[data-review]');
    if (rv && emergencyPlan) {
      const out = await guard(() => api(`/airspace/emergency/runs/${emergencyPlan.id}/review`, 'POST', { decision: rv.dataset.review }));
      if (out) toast(`Emergency plan ${out.status.toLowerCase()} and recorded in the audit log.`);
    }
  });
  page.querySelector('#speed').addEventListener('change', (e) => { speed = Number(e.target.value); });
  scrub.addEventListener('input', () => { now = Number(scrub.value); drawAircraft(); drawTrails(); fetchMonitor(true); });

  view.onSelect = (id) => { selected = id; renderSelection(); drawAircraft(); };
  let acc = 0;
  view.onTick = (dt) => {
    if (playing) {
      now += dt * speed;
      if (now > end) now = 0;
      acc += dt;
      if (acc > 0.05) { acc = 0; drawAircraft(); scrub.value = now; }
      if (performance.now() - lastTrail > 600) { lastTrail = performance.now(); drawTrails(); drawPredictions(); }
      fetchMonitor();
    }
    page.querySelector('#tc').textContent = fmt.utc(meta.start + now);
  };
  drawAircraft();
  drawTrails();
  fetchMonitor(true);
}
