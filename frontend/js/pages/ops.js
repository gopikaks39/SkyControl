// Operations pages: flights, runways, runway scheduling, priority queue and alerts.
import { api, badge, dialog, esc, fmt, guard, head, onCleanup, panel, sevKind, state, table } from '../core.js';

const STATUSES = ['Scheduled', 'In Air', 'Approach', 'Delayed', 'Emergency', 'Landed', 'Cancelled'];
const statusKind = (s) => ({ Emergency: 'red', Delayed: 'orange', Approach: 'blue', 'In Air': 'green', Cancelled: '', Landed: '' }[s] || '');

function flightFields(f = {}, runways = []) {
  return [
    { name: 'flight_number', label: 'Flight number', value: f.flight_number, required: true },
    { name: 'airline', label: 'Airline', value: f.airline, required: true },
    { name: 'origin', label: 'Origin', value: f.origin, required: true },
    { name: 'destination', label: 'Destination', value: f.destination, required: true },
    { name: 'flight_time', label: 'Time (UTC)', value: f.flight_time || '16:00', required: true },
    { name: 'status', label: 'Status', type: 'select', value: f.status || 'Scheduled', options: STATUSES },
    { name: 'priority', label: 'Priority', type: 'select', value: f.priority || 'Normal', options: ['Normal', 'High', 'Critical'] },
    { name: 'runway', label: 'Runway', type: 'select', value: f.runway || '', options: [['', '—'], ...runways.map((r) => r.runway_code)] },
    { name: 'fuel_pct', label: 'Reported fuel % (not ADS-B)', type: 'number', value: f.fuel_pct ?? '' },
    { name: 'altitude_ft', label: 'Altitude (ft)', type: 'number', value: f.altitude_ft ?? '' },
  ];
}

const clean = (o) => Object.fromEntries(Object.entries(o).map(([k, v]) => [k, v === '' ? null : ['fuel_pct', 'altitude_ft'].includes(k) ? Number(v) : v]));

export async function flights(root) {
  root.innerHTML = '<div>' + head('Operations', 'Flights', 'Managed classroom schedule (synthetic, using callsigns seen in the recording). Add, edit, search and cancel flights; every change is audited.',
    '<button class="primary" id="add">+ Add flight</button>') + '<div class="panel"><div class="row"><input id="q" placeholder="Search flight, airline or airport" style="max-width:320px"></div><div id="list" style="margin-top:12px"></div></div></div>';
  const page = root.firstElementChild;
  let runways = await api('/runways');
  const load = async () => {
    const q = page.querySelector('#q').value;
    const list = await api('/flights' + (q ? `?q=${encodeURIComponent(q)}` : ''));
    page.querySelector('#list').innerHTML = table(['Flight', 'Route', 'Time', 'Status', 'Priority', 'Runway', 'Fuel', 'Altitude', 'Source', ''], list.map((f) => `<tr>
      <td class="callsign">${esc(f.flight_number)}</td><td>${esc(f.origin)} → ${esc(f.destination)}<br><small class="muted">${esc(f.airline)}</small></td><td>${esc(f.flight_time)}</td>
      <td>${badge(f.status, statusKind(f.status))}</td><td>${badge(f.priority, sevKind(f.priority === 'Normal' ? 'Low' : f.priority))}</td><td>${esc(f.runway || '—')}</td>
      <td class="num">${f.fuel_pct ?? '—'}${f.fuel_pct !== null ? '%' : ''}</td><td class="num">${f.altitude_ft ? fmt.n(f.altitude_ft) : '—'}</td><td><small>${esc(f.source)}</small></td>
      <td><button class="small" data-edit="${f.id}">Edit</button> ${f.status !== 'Cancelled' ? `<button class="small danger" data-cancel="${f.id}">Cancel</button>` : ''}</td></tr>`).join(''));
    page._list = list;
  };
  page.addEventListener('input', (e) => { if (e.target.id === 'q') load(); });
  page.addEventListener('click', async (e) => {
    if (e.target.id === 'add') {
      const v = await dialog('Add flight', flightFields({}, runways), 'Create');
      if (v && await guard(() => api('/flights', 'POST', clean(v)), 'Flight created')) load();
    }
    if (e.target.dataset.edit) {
      const f = page._list.find((x) => x.id === Number(e.target.dataset.edit));
      const v = await dialog(`Edit ${f.flight_number}`, flightFields(f, runways));
      if (v && await guard(() => api(`/flights/${f.id}`, 'PUT', clean(v)), 'Flight updated')) load();
    }
    if (e.target.dataset.cancel && confirm('Cancel this flight? Its runway bookings are released.')) {
      if (await guard(() => api(`/flights/${e.target.dataset.cancel}/cancel`, 'POST'), 'Flight cancelled')) load();
    }
  });
  load();
}

export async function runways(root) {
  root.innerHTML = '<div>' + head('Operations', 'Runways', 'Teaching runways at the London airports. Allocation is blocked for occupied, closed or calendar-conflicting runways and the blocked request becomes an alert. Supervisors close and reopen runways.') + '<div id="rw" class="grid3"></div></div>';
  const page = root.firstElementChild;
  const load = async () => {
    const [rws, fl] = await Promise.all([api('/runways'), api('/flights')]);
    const active = fl.filter((f) => !['Cancelled', 'Landed'].includes(f.status));
    page.querySelector('#rw').innerHTML = rws.map((r) => `<section class="panel"><div class="spread"><h3>${esc(r.runway_code)}</h3>${badge(r.status, r.status === 'Available' ? 'green' : r.status === 'Closed' ? 'red' : 'orange')}</div>
      <div style="background:#2b3f48;color:#fff;font:600 22px var(--mono);letter-spacing:10px;text-align:center;padding:12px;border-top:3px dashed #9fb0b5;border-bottom:3px dashed #9fb0b5;border-radius:4px;margin:10px 0">${esc(r.runway_code.split(' ')[1] || r.runway_code)}</div>
      <p style="font-size:12px">${r.assigned_flight ? `Occupied by <b>${esc(r.assigned_flight)}</b> until ${fmt.date(r.occupied_until)}` : r.emergency_priority ? 'Preferred for emergencies' : 'No current occupant'}</p>
      ${r.status === 'Available' ? `<div class="row"><select data-flight="${r.id}" style="flex:1">${active.map((f) => `<option value="${f.id}">${esc(f.flight_number)} · ${esc(f.priority)}</option>`).join('')}</select><button class="small primary" data-alloc="${r.id}">Allocate</button></div>` : ''}
      <div class="row" style="margin-top:8px">${r.status === 'Occupied' ? `<button class="small" data-release="${r.id}">Release</button>` : ''}
      ${state.user.role === 'supervisor' && r.status !== 'Occupied' ? `<button class="small ${r.status === 'Closed' ? '' : 'danger'}" data-status="${r.id}" data-to="${r.status === 'Closed' ? 'Available' : 'Closed'}">${r.status === 'Closed' ? 'Reopen' : 'Close runway'}</button>` : ''}</div></section>`).join('');
  };
  page.addEventListener('click', async (e) => {
    const d = e.target.dataset;
    if (d.alloc && await guard(() => api(`/runways/${d.alloc}/allocate`, 'PUT', { flight_id: Number(page.querySelector(`[data-flight="${d.alloc}"]`).value) }), 'Runway allocated')) load();
    if (d.release && await guard(() => api(`/runways/${d.release}/release`, 'PUT'), 'Runway released')) load();
    if (d.status && await guard(() => api(`/runways/${d.status}/status`, 'PUT', { status: d.to }), `Runway ${d.to === 'Closed' ? 'closed' : 'reopened'}`)) load();
  });
  load();
}

export async function schedule(root) {
  root.innerHTML = '<div>' + head('Operations', 'Runway scheduling', 'UTC calendar with sequence-dependent 90–180 s buffers. Conflicting requests are blocked and SkyControl suggests the nearest feasible alternatives; nothing is booked without explicit confirmation.') +
    '<div class="grid-main"><div id="form"></div><div id="list"></div></div></div>';
  const page = root.firstElementChild;
  const [fl, rws] = await Promise.all([api('/flights'), api('/runways')]);
  const start = new Date(Date.now() + 15 * 60000);
  start.setSeconds(0, 0);
  const local = (d) => d.toISOString().slice(0, 16);
  page.querySelector('#form').innerHTML = panel('Request a slot', `<div class="form-grid">
    <label>Flight<select id="s-flight">${fl.filter((f) => !['Cancelled', 'Landed'].includes(f.status)).map((f) => `<option value="${f.id}">${esc(f.flight_number)}</option>`).join('')}</select></label>
    <label>Runway<select id="s-rwy">${rws.map((r) => `<option value="${r.id}">${esc(r.runway_code)} · ${esc(r.status)}</option>`).join('')}</select></label>
    <label>Operation<select id="s-op"><option>arrival</option><option>departure</option></select></label>
    <label>Start (UTC)<input id="s-start" type="datetime-local" value="${local(start)}"></label>
    <label>Duration (min)<input id="s-dur" type="number" value="4" min="2" max="120"></label></div>
    <div class="row"><button id="s-check">Check</button><button class="primary" id="s-book">Book</button></div><div id="s-out"></div>`);
  const req = () => {
    const s = new Date(page.querySelector('#s-start').value + ':00Z');
    const e = new Date(s.getTime() + Number(page.querySelector('#s-dur').value) * 60000);
    return { flight_id: Number(page.querySelector('#s-flight').value), runway_id: Number(page.querySelector('#s-rwy').value),
      operation: page.querySelector('#s-op').value, start_at: s.toISOString().replace('.000Z', '+00:00'), end_at: e.toISOString().replace('.000Z', '+00:00') };
  };
  const showAlt = (alts) => (alts && alts.length ? `<h4 style="margin-top:12px">Feasible alternatives</h4>${table(['Runway', 'Start', 'Delay'], alts.map((a) => `<tr><td>${esc(a.runway_code)}</td><td>${fmt.date(a.start_at)}</td><td class="num">${a.delay_minutes} min</td></tr>`).join(''))}` : '');
  const load = async () => {
    const b = await api('/schedule/bookings');
    page.querySelector('#list').innerHTML = panel('Booked slots', table(['Flight', 'Runway', 'Operation', 'Start', 'End', ''], b.slots.map((s) => `<tr><td class="callsign">${esc(s.flight_number)}</td>
      <td>${esc(s.runway_code)}</td><td>${esc(s.operation)}</td><td><small>${fmt.date(s.start_at)}</small></td><td><small>${fmt.date(s.end_at)}</small></td>
      <td><button class="small danger" data-cancel="${s.id}">Cancel</button></td></tr>`).join('')) + `<p style="font-size:11.5px">${esc(b.rules)}</p>`);
  };
  page.addEventListener('click', async (e) => {
    if (e.target.id === 's-check') {
      const r = await guard(() => api('/schedule/suggest', 'POST', req()));
      if (r) page.querySelector('#s-out').innerHTML = `<div class="notice ${r.feasible ? '' : 'warn'}">${r.feasible ? 'Slot is feasible.' : r.conflicts.map((c) => esc(c.message)).join('<br>')}</div>${r.feasible ? '' : showAlt(r.alternatives)}`;
    }
    if (e.target.id === 's-book') {
      try {
        await api('/schedule/bookings', 'POST', { ...req(), confirm: true });
        page.querySelector('#s-out').innerHTML = '<div class="notice">Booked.</div>';
        load();
      } catch (err) {
        page.querySelector('#s-out').innerHTML = `<div class="notice bad">${esc(err.message)}</div>${showAlt(err.details && err.details.alternatives)}`;
      }
    }
    if (e.target.dataset.cancel && await guard(() => api(`/schedule/bookings/${e.target.dataset.cancel}`, 'DELETE'), 'Booking cancelled')) load();
  });
  load();
}

export async function priority(root) {
  root.innerHTML = '<div>' + head('Operations', 'Priority queue', 'Active flights ordered by emergency status, priority, reported fuel and schedule. Reported fuel is controller-entered; ADS-B does not carry fuel.') + '<div id="pq" class="panel"></div></div>';
  const page = root.firstElementChild;
  const load = async () => {
    const list = await api('/priority-queue');
    page.querySelector('#pq').innerHTML = table(['#', 'Flight', 'Status', 'Priority', 'Fuel', 'Time', 'Destination'], list.map((f, i) => `<tr><td class="num"><b>${i + 1}</b></td><td class="callsign">${esc(f.flight_number)}</td>
      <td>${badge(f.status, statusKind(f.status))}</td><td>${badge(f.priority, sevKind(f.priority === 'Normal' ? 'Low' : f.priority))}</td><td class="num">${f.fuel_pct ?? '—'}</td><td>${esc(f.flight_time)}</td><td>${esc(f.destination)}</td></tr>`).join(''));
  };
  load();
  const t = setInterval(load, 5000);
  onCleanup(() => clearInterval(t));
}

export async function alerts(root) {
  root.innerHTML = '<div>' + head('Operations', 'Alerts', 'Alerts from operations, the scenario lab and emergency injections. Acknowledge or resolve them; every action is audited.',
    '<label style="margin:0"><input type="checkbox" id="all" style="width:auto"> include resolved</label>') + '<div id="al" class="panel"></div></div>';
  const page = root.firstElementChild;
  const load = async () => {
    const list = await api('/alerts' + (page.querySelector('#all').checked ? '?all=true' : ''));
    page.querySelector('#al').innerHTML = table(['When', 'Type', 'Severity', 'Message', 'Source', 'Status', ''], list.map((a) => `<tr><td><small>${fmt.date(a.created_at)}</small></td><td><b>${esc(a.type)}</b></td>
      <td>${badge(a.severity, sevKind(a.severity))}</td><td>${esc(a.message)}</td><td><small>${esc(a.source)}</small></td><td>${esc(a.status)}</td>
      <td>${a.status === 'Open' ? `<button class="small" data-op="acknowledge" data-id="${a.id}">Ack</button>` : ''} ${a.status !== 'Resolved' ? `<button class="small" data-op="resolve" data-id="${a.id}">Resolve</button>` : ''}</td></tr>`).join(''), 'No alerts');
  };
  page.addEventListener('click', async (e) => {
    if (e.target.dataset.op && await guard(() => api(`/alerts/${e.target.dataset.id}/${e.target.dataset.op}`, 'PUT'))) load();
  });
  page.addEventListener('change', (e) => { if (e.target.id === 'all') load(); });
  load();
}
