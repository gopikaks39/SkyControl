// Gap analysis: where today's ATC is weak, SkyControl's fix and the evidence.
import { api, badge, esc, head, panel, table } from '../core.js';
import { go } from '../main.js';

const TYPE = { 'measured on real data': 'green', scenario: 'violet' };

export async function render(root) {
  root.innerHTML = '<div>' + head('Overview', 'Gaps in today\'s ATC and how SkyControl closes them',
    'SkyControl is designed to complement current ATC and its existing automation (STCA, MTCD, CLAM, AMAN/XMAN, CPDLC), not to replace the controller. Each gap below lists how it is handled today, the fix, where to see it in this app, and the evidence with its type: measured on the real recording, modelled, or demonstrated in a scenario.') +
    '<div id="gaps" class="grid2"></div><div id="matrix"></div></div>';
  const page = root.firstElementChild;
  const gaps = await api('/gaps');
  page.querySelector('#gaps').innerHTML = gaps.map((g) => `<article class="gap">
    <div class="spread"><span class="id">${esc(g.id)}</span>${badge(g.category, 'blue')}</div>
    <h3>${esc(g.title)}</h3>
    <dl><dt>Today</dt><dd>${esc(g.today)}</dd><dt>Risk</dt><dd>${esc(g.risk)}</dd><dt>SkyControl</dt><dd><b>${esc(g.fix)}</b></dd>
      <dt>Relationship</dt><dd>${esc(g.relationship)}</dd><dt>See it in</dt><dd>${g.where.map((w) => badge(w, 'dark')).join(' ')}</dd></dl>
    <div style="margin-top:10px">${g.evidence.map((e) => `<div class="ev">${esc(e)}</div>`).join('')}</div>
    <div style="margin-top:8px">${badge(g.evidence_type.toUpperCase(), TYPE[g.evidence_type] || 'orange')}</div></article>`).join('');
  page.querySelector('#matrix').innerHTML = '<div style="height:18px"></div>' + panel('Capability matrix: conventional ATC vs with SkyControl', table(
    ['Capability', 'Conventional ATC', 'With SkyControl', 'Effect'], [
      ['Clearance delivery', 'Voice; hearback by the controller', 'Datalink for routine items; every voice readback machine-checked', 'Fewer undetected readback errors, less frequency time'],
      ['Callsign confusion', 'Vigilance; post-event reports', 'Live similarity alerts; logon-addressed datalink', 'Wrong-aircraft responses caught'],
      ['Conflict detection', '2-min STCA; MTCD in some centres', '5-min intent-aware probe with learned trajectories', 'Earlier warning at a similar alert rate'],
      ['Surveillance trust', 'Assumed', 'Duplicate merging, coasting with uncertainty, MANUAL switch on low integrity', 'No false alerts from ghosts; safer degraded mode'],
      ['Arrival delay', 'AMAN; stacks decided late', 'Hold prediction 30-80 NM out; linear holding', 'Delay moved from stacks to cruise'],
      ['Emergencies', 'Checklists, mental alternate selection, phone', 'Ranked alternates, path checked vs traffic, auto-resequencing, digital coordination', 'Faster, verified plan; human approval'],
      ['Automation trust', 'On/off tools', 'Explicit AUTO/CONSENT/ADVISORY/MANUAL with reasons', 'Humans know when not to trust the system'],
    ].map((r) => `<tr>${r.map((c, i) => `<td>${i === 0 ? `<b>${esc(c)}</b>` : esc(c)}</td>`).join('')}</tr>`).join('')));
  page.addEventListener('click', (e) => {
    const b = e.target.closest('.badge.dark');
    if (!b) return;
    const t = b.textContent;
    if (t.startsWith('Scenario')) go('lab'); else if (t.startsWith('3D')) go('airspace'); else if (t.startsWith('Communication')) go('comms');
    else if (t.startsWith('Statistical')) go('analysis'); else if (t.startsWith('AI')) go('models'); else if (t.startsWith('Runway')) go('runways');
  });
}
