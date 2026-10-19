// Scenario lab: 21 exercises, each shown step by step with the conventional comparator side by side.
import { api, badge, esc, fmt, guard, head, levelBadge, loading, onCleanup, panel, sevKind, state, table, toast } from '../core.js';
import { Airspace3D } from '../scene3d.js';

const RUN_KEY = 'skycontrol_run';
const CATEGORY_ORDER = ['Communication', 'Separation', 'Surveillance', 'Automation', 'Emergency', 'Runway', 'Hazard', 'Capacity'];
const ICONS = { Communication: '✆', Separation: '⇄', Surveillance: '◎', Automation: '⌁', Emergency: '✚', Runway: '▤', Hazard: '☁', Capacity: '≋' };

function routePos(route, t) {
  for (let i = 1; i < route.length; i++) {
    const a = route[i - 1], b = route[i];
    if (t <= b.t) {
      const f = Math.max(0, Math.min(1, (t - a.t) / (b.t - a.t)));
      return { x: a.x + (b.x - a.x) * f, y: a.y + (b.y - a.y) * f, ft: a.altitude_ft + (b.altitude_ft - a.altitude_ft) * f,
        heading: (Math.atan2(b.x - a.x, b.y - a.y) * 180 / Math.PI + 360) % 360 };
    }
  }
  const l = route[route.length - 1];
  return { x: l.x, y: l.y, ft: l.altitude_ft, heading: 0 };
}

export async function render(root) {
  root.innerHTML = '<div>' + head('Scenario lab', 'Every scenario, handled step by step',
    'Each exercise runs twice over the same aircraft: the conventional comparator (left of every comparison) and SkyControl\'s verified plan. The run pauses at T+20 s for the human decision; the automation level decides who must approve.',
    '') + `<div id="lab-select">${loading()}</div><div id="lab-run"></div></div>`;
  const page = root.firstElementChild;
  const catalog = await api('/lab/catalog');
  let chosen = 'readback_error', run = null, view = null, lastPoll = 0, localTime = 0, showBaseline = true;

  const grouped = CATEGORY_ORDER.map((c) => [c, catalog.filter((s) => s.category === c)]).filter(([, l]) => l.length);
  let catalogOpen = true;
  const drawCatalog = () => {
    const src = page.querySelector('#src')?.value || 'recording';
    const current = catalog.find((s) => s.id === chosen);
    page.querySelector('#lab-select').innerHTML = panel(`Choose a scenario <small class="muted" style="font-weight:400">· selected: ${esc(current.title)}</small>`,
      catalogOpen ? grouped.map(([cat, list]) => `<div class="cat-title">${ICONS[cat]} ${esc(cat)}</div>
      <div class="catalog">${list.map((s) => `<button class="scen ${s.id === chosen ? 'sel' : ''}" data-scen="${s.id}">
        <div class="spread"><b>${esc(s.title)}</b>${badge(s.severity, sevKind(s.severity))}</div><small>${esc(s.description)}</small>
        <small style="color:#9a5a17">Gap: ${esc(s.gap)}</small></button>`).join('')}</div>`).join('') : '',
    `<button class="small" id="toggle-cat">${catalogOpen ? 'Hide catalogue' : 'Show all 21 scenarios'}</button>
     <select id="src" style="width:auto"><option value="recording" ${src === 'recording' ? 'selected' : ''}>Callsigns from the London recording</option>
     <option value="managed" ${src === 'managed' ? 'selected' : ''}>Managed classroom flights</option></select>
     <button class="primary" id="start">Start scenario</button>`);
  };
  drawCatalog();

  function ensureView() {
    const host = page.querySelector('#lab-vp');
    if (!host || view) return;
    view = new Airspace3D(host, { extent: 38, vScale: 0.5, aircraftScale: 0.9, grid: 5, rings: [10, 20, 30] });
    onCleanup(() => view && view.dispose());
    view.focus(0, 0, 8000, 85);
    drawStatic();
  }

  function drawStatic() {
    if (!view || !run) return;
    const sc = run.scene;
    view.addAirports((sc.airports || []).map((a) => ({ x: a.x, y: a.y, heading: 270, label: `${a.name}${a.closed ? ' (CLOSED)' : ''}`, closed: a.closed, runway_m: 3000 })));
    view.clearPaths('route-');
    run.aircraft.forEach((a, i) => {
      const resolved = a.resolved.map((p) => [p.x, p.y, p.altitude_ft]);
      view.setPath(`route-r-${i}`, resolved, { color: 0x2ee6c9, dashed: true, opacity: 0.75 });
      if (showBaseline) view.setPath(`route-b-${i}`, a.baseline.map((p) => [p.x, p.y, p.altitude_ft]), { color: 0xff9d6b, dashed: true, opacity: 0.45 });
    });
    (sc.objects || []).filter((o) => o.kind === 'prediction').forEach((o, i) => {
      view.setPath(`route-pred-${i}`, o.path.map(([x, y]) => [x, y, 16000]), { color: 0xa48cff, dashed: true, opacity: 0.9 });
    });
  }

  let lastTrailDraw = 0;
  function drawDynamic() {
    if (!view || !run) return;
    const t = localTime;
    const key = ['Approved', 'Overridden', 'Not required'].includes(run.approval) ? 'resolved' : 'baseline';
    view.setZones((run.scene.zones || []).filter((z) => !z.clear_at || t < z.clear_at).map((z) => ({ ...z, top: 36000 })));
    const markers = [];
    for (const o of run.scene.objects || []) {
      if (o.clear_at && t >= o.clear_at) continue;
      if (o.kind === 'ghost') {
        const owner = run.aircraft.find((a) => a.name === o.follows);
        const p = routePos(owner[key], t);
        markers.push({ x: p.x + o.dx, y: p.y + o.dy, ft: p.ft, kind: 'ghost', label: o.label });
      } else if (o.kind === 'radio') {
        const owner = run.aircraft.find((a) => a.name === o.flight);
        const p = routePos(owner[key], t);
        markers.push({ x: p.x, y: p.y, ft: p.ft + 1500, kind: 'radio', label: 'NORDO 7600' });
      } else if (o.kind !== 'prediction') {
        markers.push({ x: o.x, y: o.y, ft: 0, kind: o.kind, label: { vehicle: 'Vehicle on runway', birds: 'Bird flock', preceding: 'Preceding aircraft on runway' }[o.kind] });
      }
    }
    view.setMarkers(markers);
    view.beginFrame();
    run.aircraft.forEach((a) => {
      const p = routePos(a[key], t);
      const emergency = /emergency|MAYDAY|PAN|security|bird|fuel|engine|radio|reads back|overshoots|cleared FL/i.test(a.role || '');
      const done = t >= a[key][a[key].length - 1].t;
      view.upsertAircraft(a.name, { x: p.x, y: p.y, ft: p.ft, heading: p.heading, color: emergency ? 0xff5a5f : done ? 0x6f8f96 : 0xd8f5f0,
        label: `${a.name} ${fmt.fl(p.ft)}`, labelClass: emergency ? 'alert' : done ? 'dim' : '' });
    });
    view.endFrame();
    if (performance.now() - lastTrailDraw < 250) return;
    lastTrailDraw = performance.now();
    const trails = run.aircraft.map((a) => {
      const pts = [];
      for (let s = Math.max(0, t - 120); s <= t; s += 10) { const p = routePos(a[key], s); pts.push([p.x, p.y, p.ft]); }
      return { points: pts };
    });
    view.setTrails(trails);
  }

  function renderRun() {
    const d = run;
    const box = page.querySelector('#lab-run');
    if (!d) { box.innerHTML = ''; return; }
    const executing = ['Approved', 'Overridden', 'Not required'].includes(d.approval);
    const progress = Math.min(100, (localTime / d.duration) * 100);
    const flow = d.workflow;
    box.innerHTML = `<div class="grid-main"><div>
      <section class="panel dark" style="padding:12px">
        <div class="spread" style="padding:4px 4px 10px"><div><span class="eyebrow">Run #${d.id} · ${esc(d.category)}</span>
          <h2 style="margin:2px 0;color:#fff">${esc(d.title)} ${badge(d.severity, sevKind(d.severity))}</h2>
          <p style="margin:0">${esc(d.problem)}. Goal: ${esc(d.goal)}.</p></div>
          <div class="levels">Automation now ${levelBadge(d.current_level)}</div></div>
        <div class="viewport short" id="lab-vp"><div class="vp-overlay"><button class="vp-chip ${showBaseline ? 'on' : ''}" id="toggle-base">Comparator routes</button>
          <span class="vp-chip on">SkyControl routes</span></div>
          <div class="vp-legend"><i style="background:#2ee6c9"></i>SkyControl plan<br><i style="background:#ff9d6b"></i>${esc(d.baseline_label)}<br><i style="background:#ff5a5f"></i>aircraft with the problem</div>
          <div class="vp-hint">Drag to rotate · wheel to zoom</div></div>
        <div class="controls-bar">
          <button class="small" data-ctl="${d.playing ? 'pause' : 'play'}">${d.playing ? '❚❚ Pause' : '▶ Play'}</button>
          <button class="small" data-ctl="reset">↺ Reset</button>
          <select id="lab-speed" style="width:auto">${[1, 2, 5, 10, 16, 32, 64].map((s) => `<option ${s === d.speed ? 'selected' : ''} value="${s}">${s}×</option>`).join('')}</select>
          <div style="flex:1;min-width:200px" class="progress"><input type="range" id="lab-seek" min="0" max="${d.duration}" value="${Math.round(localTime)}"></div>
          <span class="timecode" id="lab-tc">T+${fmt.time(localTime)} / ${fmt.time(d.duration)}</span>
          <button class="small" data-view="perspective">3D</button><button class="small" data-view="top">Top</button>
        </div>
      </section>
      <div id="lab-approval">${approvalBox(d)}</div>
      ${panel('How SkyControl handles it, step by step', `<div class="pipeline">${d.steps.map((s, i) => `<div class="step ${s.status}"><div class="node">${s.status === 'done' ? '✓' : i + 1}</div>
        <div><div class="phase">${esc(s.phase)} · T+${fmt.time(s.t)} · ${esc(s.actor)}</div><div class="title">${esc(s.title)}</div><div class="detail">${esc(s.detail)}</div></div></div>`).join('')}</div>`,
        `<span id="lab-progress">${badge(Math.round(progress) + '% complete', 'dark')}</span>`)}
      ${panel('Conventional ATC vs SkyControl (workflow model)', `<div class="compare">
        <div class="old"><h4>Conventional · ${esc(d.baseline_label)}</h4><ol>${flow.baseline.steps.map((s) => `<li>${esc(s.step)} · ${s.seconds}s</li>`).join('')}</ol>
          <div class="tot">${flow.baseline.time_to_all_instructions_s}s</div><small>${flow.baseline.radio_transmissions} radio transmissions · ${flow.baseline.controller_actions} controller actions · ${flow.baseline.unverified_voice_clearances} unverified voice clearances</small></div>
        <div class="new"><h4>SkyControl hybrid</h4><ol>${flow.hybrid.steps.map((s) => `<li>${esc(s.step)} · ${s.seconds}s</li>`).join('')}</ol>
          <div class="tot">${flow.hybrid.time_to_all_instructions_s}s <small class="delta-good">−${flow.time_saving_pct}%</small></div><small>${flow.hybrid.radio_transmissions} radio transmissions · ${flow.hybrid.controller_actions} controller actions · every voice readback verified</small></div></div>
        <p style="font-size:11.5px;margin:10px 0 0">Times come from the task-time model (core/workflow.py); they are modelled, not measured.</p>`)}
    </div><div>
      ${panel('Outcome checks (before → after)', table(['Check', d.baseline_label, 'SkyControl'], d.checks.map((c) => `<tr><td>${esc(c.label)}</td>
        <td class="num ${c.before ? 'delta-bad' : ''}">${c.before} ${esc(c.unit)}</td><td class="num ${c.after ? 'delta-bad' : 'delta-good'}">${c.after} ${esc(c.unit)}</td></tr>`).join('')) +
        `<p style="font-size:12px;margin:10px 0 0"><b>Algorithm.</b> ${esc(d.algorithm)}</p>`, d.plan_valid ? badge('PLAN VERIFIED', 'green') : badge('PLAN FAILS CHECKS', 'red'))}
      ${panel('Context switches (automation level)', d.context_log.map((c) => `<div class="msg"><div class="spread">${levelBadge(c.level)}<small class="muted">T+${fmt.time(c.t)}</small></div>
        <div style="font-size:12px;margin-top:4px">${esc(c.reasons.join(' '))}</div></div>`).join(''))}
      ${panel('Message log and readback verification', d.messages.length ? d.messages.map(messageCard).join('') : '<p class="muted">No instructions needed: every aircraft keeps its route.</p>')}
      ${panel('Aircraft', table(['Callsign', 'Role', 'Action', 'Altitude'], (d.positions || []).map((p, i) => `<tr><td class="callsign">${esc(p.name)}</td>
        <td><small>${esc(p.role)}</small></td><td><small>${esc(d.aircraft[i].action)}</small></td><td class="num">${fmt.fl(p.altitude_ft)}</td></tr>`).join('')))}
      ${panel('Event log', `<div class="event-log">${d.events.slice().reverse().map((e) => `<div><b>T+${fmt.time(e.t)}</b>${esc(e.message)}</div>`).join('')}</div>`)}
      <p class="muted" style="font-size:11px">${esc(d.note)} Source: ${esc(d.source)}.</p>
    </div></div>`;
    if (view) { view.dispose(); view = null; }
    ensureView();
    lastTrailDraw = 0;
    drawDynamic();
  }

  function messageCard(m) {
    const v = m.verification || {};
    let extra = '';
    if (m.first_readback) {
      extra = `<div style="margin-top:6px"><small class="muted">First readback</small><div class="phr">${esc(m.first_readback)}</div>
        <span class="verdict ${m.first_verification.verdict}">${m.first_verification.verdict}</span> <small>${esc(m.first_verification.advice)}</small></div>`;
    }
    if (m.blocked_voice_readback) {
      extra += `<div style="margin-top:6px"><small class="muted">If the similar callsign had answered by voice</small><div class="phr">${esc(m.blocked_voice_readback)}</div>
        <span class="verdict ${m.blocked_verification.verdict}">${m.blocked_verification.verdict}</span> <small>${esc(m.blocked_verification.advice)}</small></div>`;
    }
    return `<div class="msg"><div class="spread"><span class="callsign">${esc(m.to)}</span>${badge(m.channel, m.channel === 'voice' ? 'orange' : 'blue')}</div>
      <div class="phr">${esc(m.phraseology)}</div>${extra}
      <div style="margin-top:6px"><small class="muted">${m.first_readback ? 'Corrected readback' : 'Readback'}</small> <span class="mono">${esc(m.readback)}</span>
      <span class="verdict ${v.verdict}">${esc(v.verdict)}</span></div></div>`;
  }

  function approvalBox(d) {
    const executing = ['Approved', 'Overridden', 'Not required'].includes(d.approval);
    if (executing) {
      return `<div class="approval ok"><b>${esc(d.approval === 'Not required' ? 'AUTO: no approval needed' : `${d.approval} by ${d.reviewed_by || ''}`)}</b> · outcome: ${esc(d.outcome)}</div>`;
    }
    const need = d.approver || 'controller';
    const canApprove = need !== 'supervisor' || state.user.role === 'supervisor';
    return `<div class="approval" style="margin:0 0 18px"><div class="spread"><div><b>${d.waiting ? 'Waiting for the human decision' : 'Approval gate at T+20 s'}</b>
      · requires <b>${esc(need)}</b> approval ${d.approval === 'Rejected' ? '(rejected; can be reconsidered)' : ''}<br>
      <small>You are signed in as <b>${esc(state.user.username)}</b> (${esc(state.user.role)}). ${canApprove ? '' : 'Switch account to a supervisor; this run is kept.'}</small></div>
      <div class="row"><button class="primary" data-ctl="approve" ${canApprove && d.plan_valid ? '' : 'disabled'}>Approve plan</button>
      <button data-ctl="reject">Reject</button><button data-ctl="override" ${state.user.role === 'supervisor' ? '' : 'disabled'}>Override with reason</button></div></div></div>`;
  }

  async function poll() {
    if (!run) return;
    try {
      run = await api(`/lab/runs/${run.id}`);
      localTime = run.time;
      lastPoll = performance.now();
      refreshLight();
    } catch (e) {
      if (e.status === 404 || e.status === 409) { localStorage.removeItem(RUN_KEY); run = null; renderRun(); }
    }
  }

  // Update only the parts that change every second, so the 3D view keeps its camera.
  function refreshLight() {
    const tc = page.querySelector('#lab-tc');
    if (!tc) return renderRun();
    tc.textContent = `T+${fmt.time(localTime)} / ${fmt.time(run.duration)}`;
    const prog = page.querySelector('#lab-progress');
    if (prog) prog.innerHTML = badge(Math.round(Math.min(100, (localTime / run.duration) * 100)) + '% complete', 'dark');
    page.querySelector('#lab-seek').value = Math.round(localTime);
    page.querySelector('#lab-approval').innerHTML = approvalBox(run);
    const steps = page.querySelectorAll('.step');
    run.steps.forEach((s, i) => {
      if (!steps[i]) return;
      steps[i].className = `step ${s.status}`;
      steps[i].querySelector('.node').textContent = s.status === 'done' ? '✓' : i + 1;
    });
    const log = page.querySelector('.event-log');
    if (log) log.innerHTML = run.events.slice().reverse().map((e) => `<div><b>T+${fmt.time(e.t)}</b>${esc(e.message)}</div>`).join('');
    const play = page.querySelector('[data-ctl="play"], [data-ctl="pause"]');
    if (play) { play.dataset.ctl = run.playing ? 'pause' : 'play'; play.textContent = run.playing ? '❚❚ Pause' : '▶ Play'; }
    const lv = page.querySelector('.levels');
    if (lv) lv.innerHTML = `Automation now ${levelBadge(run.current_level)}`;
  }

  async function control(action, extra = {}) {
    const r = await guard(() => api(`/lab/runs/${run.id}/control`, 'POST', { action, ...extra }));
    if (r) { run = r; localTime = r.time; lastPoll = performance.now(); refreshLight(); if (action === 'reset') renderRun(); }
  }

  page.addEventListener('click', async (e) => {
    const sc = e.target.closest('[data-scen]');
    if (sc) { chosen = sc.dataset.scen; drawCatalog(); return; }
    if (e.target.id === 'toggle-cat') { catalogOpen = !catalogOpen; drawCatalog(); return; }
    if (e.target.id === 'start') {
      e.target.disabled = true;
      const r = await guard(() => api('/lab/runs', 'POST', { scenario: chosen, source: page.querySelector('#src').value }));
      e.target.disabled = false;
      if (r) { run = r; localTime = 0; localStorage.setItem(RUN_KEY, r.id); catalogOpen = false; drawCatalog(); renderRun(); toast(`${r.title} started. It pauses at T+20 s for the human decision.`); page.querySelector('#lab-run').scrollIntoView({ behavior: 'smooth' }); }
      return;
    }
    if (e.target.id === 'toggle-base') { showBaseline = !showBaseline; e.target.classList.toggle('on', showBaseline); drawStatic(); return; }
    const vw = e.target.closest('[data-view]');
    if (vw && view) { view.view(vw.dataset.view); return; }
    const c = e.target.closest('[data-ctl]');
    if (!c || !run) return;
    const action = c.dataset.ctl;
    if (action === 'override') {
      const note = prompt('Reason for the supervisor override (recorded in the audit log):');
      if (note) control('override', { note });
    } else {
      await control(action);
      if (action === 'approve') toast('Plan approved: instructions are delivered and the aircraft start their manoeuvres.');
    }
  });
  page.addEventListener('change', (e) => {
    if (e.target.id === 'lab-speed') control('speed', { speed: Number(e.target.value) });
    if (e.target.id === 'lab-seek') control('seek', { time: Number(e.target.value) });
  });

  const saved = localStorage.getItem(RUN_KEY);
  if (saved) {
    try { run = await api(`/lab/runs/${saved}`); localTime = run.time; chosen = run.scenario; catalogOpen = false; drawCatalog(); renderRun(); } catch { localStorage.removeItem(RUN_KEY); }
  }
  const timer = setInterval(poll, 1000);
  let raf = 0;
  const animate = () => {
    if (run && view) {
      const executing = ['Approved', 'Overridden', 'Not required'].includes(run.approval);
      if (run.playing) {
        const elapsed = (performance.now() - lastPoll) / 1000;
        let t = run.time + elapsed * run.speed;
        t = Math.min(t, executing ? run.duration : run.gate);
        localTime = Math.max(localTime, t);
      }
      drawDynamic();
    }
    raf = requestAnimationFrame(animate);
  };
  animate();
  onCleanup(() => { clearInterval(timer); cancelAnimationFrame(raf); });
}
