// Data & provenance: dataset register, OpenSky snapshots, import and live capture.
import { api, badge, esc, fmt, guard, head, panel, table, toast } from '../core.js';

export async function render(root) {
  root.innerHTML = '<div>' + head('Data & security', 'Data and provenance',
    'Every dataset SkyControl uses, whether it is real, its period and its checksum. The London–Amsterdam OpenSky recording is the primary dataset; scenario trajectories are constructed and labelled as such.') +
    '<div id="ds"></div><div class="grid2"><div id="snaps"></div><div id="io"></div></div></div>';
  const page = root.firstElementChild;
  const [ds, snaps, health] = await Promise.all([api('/data/datasets'), api('/data/snapshots'), api('/data/feed-health')]);
  page.querySelector('#ds').innerHTML = panel('Dataset register', table(['Dataset', 'Type', 'Provider', 'Period', 'Records', 'Real?', 'SHA-256', 'Notes'], ds.map((d) => `<tr>
    <td><b>${esc(d.name)}</b></td><td>${esc(d.kind)}</td><td>${esc(d.provider)}</td><td><small>${esc(d.period)}</small></td><td class="num">${d.records ? fmt.n(d.records) : '—'}</td>
    <td>${d.is_real ? badge('REAL', 'green') : badge('CONSTRUCTED', 'orange')}</td><td><small class="mono">${esc((d.sha256 || '—').slice(0, 16))}…</small></td><td><small>${esc(d.notes)}</small></td></tr>`).join('')));
  page.querySelector('#snaps').innerHTML = panel('OpenSky snapshots (state vectors)', table(['#', 'Observed', 'Type', 'Aircraft', 'Provider'], snaps.map((s) => `<tr><td>${s.id}</td>
    <td><small>${fmt.date(s.observed_at)}</small></td><td>${badge(s.dataset_type, s.dataset_type === 'live' ? 'green' : 'blue')}</td><td class="num">${s.aircraft_count}</td><td><small>${esc(s.provider)}</small></td></tr>`).join('')) +
    `<p style="font-size:12px">Feed status: <b>${esc(health.status)}</b>${health.last_attempt_failed ? ' · last live attempt failed (no data fabricated)' : ''}</p>`);
  page.querySelector('#io').innerHTML = panel('Capture or import', `<p style="font-size:13px">Request a live OpenSky capture of the London–Amsterdam box (needs internet access to opensky-network.org; optional API credentials in <code>.env</code>).
    Failures are logged and never replaced with invented data.</p><button class="primary" id="cap">Capture live snapshot</button>
    <h4 style="margin-top:18px">Import an OpenSky <code>/states/all</code> JSON response</h4><input type="file" id="file" accept=".json">
    <p style="font-size:12px;margin-top:10px">Record your own multi-frame dataset with <code>python scripts/record_opensky.py --minutes 90</code>; it writes the same format as the bundled recording.</p>`);
  page.addEventListener('click', async (e) => {
    if (e.target.id === 'cap') {
      e.target.disabled = true;
      const r = await guard(() => api('/data/capture', 'POST', {}));
      e.target.disabled = false;
      if (r) { toast(`Captured ${r.aircraft_count} aircraft`); render(root); }
    }
  });
  page.addEventListener('change', async (e) => {
    if (e.target.id !== 'file' || !e.target.files[0]) return;
    try {
      const body = JSON.parse(await e.target.files[0].text());
      const r = await guard(() => api('/data/import', 'POST', body));
      if (r) { toast(`Imported ${r.aircraft_count} aircraft`); render(root); }
    } catch { toast('That file is not valid JSON', true); }
  });
}
