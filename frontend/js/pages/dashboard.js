// Command centre: live KPIs, headline real-data results and the gap-to-fix summary.
import { analysis, api, badge, esc, fmt, head, kpi, loading, onCleanup, panel, sevKind, state, table } from '../core.js';
import { go } from '../main.js';

export async function render(root) {
  root.innerHTML = '<div>' + head('Command centre', `Good ${new Date().getUTCHours() < 12 ? 'morning' : 'afternoon'}, ${esc(state.user.full_name || state.user.username)}`,
    'Live operations status, the strongest results from the real London-Amsterdam recording, and where SkyControl complements today\'s ATC.') +
    '<div id="dash-kpis"></div><div class="grid-main"><div id="dash-results">' + loading('Loading real-data results (first start analyses the recording, about a minute)…') +
    '</div><div id="dash-side"></div></div></div>';
  const page = root.firstElementChild;

  const refresh = async () => {
    const d = await api('/dashboard');
    page.querySelector('#dash-kpis').innerHTML = `<div class="kpis">
      ${kpi('Active flights', d.active_flights, `${d.delayed_flights} delayed`, 'accent')}
      ${kpi('Emergencies', d.emergencies, 'flights in emergency status', d.emergencies ? 'bad' : '')}
      ${kpi('Open alerts', d.open_alerts, `${d.priority_alerts} high / critical`, d.priority_alerts ? 'warn' : '')}
      ${kpi('Approvals waiting', d.pending_approvals, 'scenario plans at the gate', d.pending_approvals ? 'warn' : '')}
      ${kpi('Runways in use', `${d.runways_in_use}/${d.runways_total}`, 'teaching runways')}
      ${kpi('Failed logins (24 h)', d.failed_logins_24h, 'all recorded', d.failed_logins_24h ? 'warn' : '')}
    </div>`;
    const alerts = await api('/alerts');
    page.querySelector('#dash-side').innerHTML = panel('Open alerts', alerts.length ? alerts.slice(0, 8).map((a) =>
      `<div class="msg"><div class="spread"><b>${esc(a.type)}</b>${badge(a.severity, sevKind(a.severity))}</div>
       <div class="muted" style="font-size:12px">${esc(a.message)}</div><small class="muted">${esc(a.source)} · ${fmt.date(a.created_at)}</small></div>`).join('')
      : '<div class="empty">No open alerts</div>', '<button class="small" data-go="alerts">All alerts</button>') +
      panel('Quick start for the demonstration', `<ol style="margin:0;padding-left:18px;line-height:1.9;font-size:13px">
        <li><a href="#" data-go="airspace">Replay real traffic in 3D</a> and inject an emergency.</li>
        <li><a href="#" data-go="lab">Run a scenario</a> and follow the 10 handling steps.</li>
        <li><a href="#" data-go="comms">Check a readback</a> with a wrong flight level.</li>
        <li><a href="#" data-go="analysis">Open the statistics</a> that compare with today\'s ATC.</li>
        <li><a href="#" data-go="security">Show the login-attempt log</a> (supervisor).</li></ol>`);
  };
  await refresh();
  const timer = setInterval(() => refresh().catch(() => {}), 8000);
  onCleanup(() => clearInterval(timer));

  page.addEventListener('click', (e) => {
    const t = e.target.closest('[data-go]');
    if (t) { e.preventDefault(); go(t.dataset.go); }
  });

  const a = await analysis();
  const p300 = a.prediction.horizons.find((h) => h.horizon_s === 300);
  const conf = Object.fromEntries(a.conflicts.methods.map((m) => [m.key, m]));
  const comm = a.communication.headline;
  const inj = a.emergency_injection;
  const card = (title, value, text, page) => `<div class="kpi accent" style="cursor:pointer" data-go="${page}"><span>${title}</span>
    <strong>${value}</strong><span>${text}</span></div>`;
  page.querySelector('#dash-results').innerHTML = panel('Headline results', `
    <p style="margin-top:-4px">Measured on the real recording (${fmt.n(a.overview.aircraft)} aircraft, ${fmt.n(a.overview.observations_used)} position reports,
      ${esc(a.overview.start_utc)} to ${esc(a.overview.end_utc)}) unless marked as modelled.</p>
    <div class="kpis" style="margin:0">
      ${card('5-min trajectory error', `−${fmt.n(p300.relative_improvement_pct, 1)}%`, `${fmt.n(p300.baseline_mean, 2)} → ${fmt.n(p300.proposed_mean, 2)} NM on held-out traffic`, 'analysis')}
      ${card('Conflict alerts per hour', `${fmt.n(conf.intent_probe.alerts_per_hour)}`, `vs ${fmt.n(conf.naive_probe.alerts_per_hour)} for a naive 5-min probe (−${fmt.n(a.conflicts.alert_reduction_vs_naive_probe_pct, 0)}%)`, 'analysis')}
      ${card('Dropped-track position error', `${fmt.n(a.surveillance.coasting.coasted_mean_error_nm, 2)} NM`, `vs ${fmt.n(a.surveillance.coasting.frozen_mean_error_nm, 2)} NM frozen (${a.surveillance.coasting.cases} real dropouts)`, 'analysis')}
      ${card('Undetected comm errors', `−${fmt.n(comm.relative_reduction_pct, 0)}%`, `${comm.voice_undetected_per_10k} → ${comm.hybrid_undetected_per_10k} per 10k clearances (modelled)`, 'comms')}
      ${card('Real holding observed', `${fmt.n(a.holding.stack_holding_minutes)} min`, `${a.holding.stack_holds} holds; ~${fmt.n(a.holding.aman.share_absorbable_extended_pct, 0)}% absorbable by speed control`, 'analysis')}
      ${card('Emergencies in real traffic', `${fmt.n(inj.resolved_share_pct, 0)}% auto-resolved`, `${inj.count} injections, ${fmt.n(inj.mean_conflicts, 1)} conflicts each, ${fmt.n(inj.median_compute_ms)} ms to plan`, 'airspace')}
    </div>`, `${badge('REAL DATA', 'green')}`) +
    panel('Gaps in today\'s ATC and what SkyControl adds', table(['Gap', 'Today', 'SkyControl', 'Relationship'],
      (await api('/gaps')).map((g) => `<tr><td><b>${esc(g.id)}</b> ${esc(g.title)}</td><td class="muted">${esc(g.today)}</td><td>${esc(g.fix)}</td><td>${esc(g.relationship)}</td></tr>`).join('')),
      '<button class="small" data-go="gaps">Details and evidence</button>');
}
