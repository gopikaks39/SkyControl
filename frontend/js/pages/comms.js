// Communication assistant: structured clearance, ICAO phraseology, readback verification and callsign similarity.
import { analysis, api, badge, esc, fmt, guard, head, panel, table } from '../core.js';

const FIELDS = [['callsign', 'Callsign', 'BAW425'], ['level', 'Level (ft)', '12000'], ['heading', 'Heading (°)', '270'],
  ['speed', 'Speed (kt)', ''], ['direct', 'Direct to', ''], ['squawk', 'Squawk', ''], ['frequency', 'Frequency', '133.175'],
  ['qnh', 'QNH (hPa)', ''], ['runway', 'Runway', '']];

export async function render(root) {
  root.innerHTML = '<div>' + head('AI support', 'Communication assistant',
    'Gap G1/G2: voice readback errors and similar callsigns. Compose a structured clearance, read it back as a pilot would (or speak it), and SkyControl compares every field before anyone acts on it.') +
    `<div class="grid-main"><div>
      ${panel('1 · Clearance', `<div class="form-grid three">${FIELDS.map(([k, l, v]) => `<label>${l}<input data-f="${k}" value="${v}"></label>`).join('')}</div>
        <label>Aircraft also on the frequency (comma separated)<input id="freq" value="BAW725, EZY12AB, RYR52ZT"></label>
        <div class="row"><button id="render">Show phraseology</button><span id="phr" class="mono"></span></div>`)}
      ${panel('2 · Pilot readback', `<label>Readback (typed, or a speech-to-text transcript)<textarea id="rb" rows="3">climb flight level one two zero, heading two seven zero, one three three decimal one seven five, Speedbird four two five</textarea></label>
        <div class="row"><span class="muted" style="font-size:12px">Try:</span>
          <button class="small" data-sample="ok">Correct</button><button class="small" data-sample="level">Wrong level</button>
          <button class="small" data-sample="aircraft">Wrong aircraft answers</button><button class="small" data-sample="partial">Partial readback</button>
          <button class="small" data-sample="noisy">Noisy transcript</button><button class="small" id="mic" hidden>🎙 Speak</button></div>
        <div class="row" style="margin-top:12px"><button class="primary" id="verify">Verify readback</button></div>
        <div id="result"></div>`)}
    </div><div>
      ${panel('Similar callsigns in the real recording', '<div id="similar"></div>', badge('REAL DATA', 'green'))}
      ${panel('Recent readback checks', '<div id="log"></div>')}
    </div></div></div>`;
  const page = root.firstElementChild;
  const get = () => {
    const c = {};
    page.querySelectorAll('[data-f]').forEach((el) => { if (el.value.trim()) c[el.dataset.f] = el.value.trim(); });
    return c;
  };
  const onFreq = () => page.querySelector('#freq').value.split(',').map((s) => s.trim()).filter(Boolean);
  const samples = {
    ok: 'climb flight level one two zero, heading two seven zero, one three three decimal one seven five, Speedbird four two five',
    level: 'climb flight level one four zero, heading two seven zero, one three three decimal one seven five, Speedbird four two five',
    aircraft: 'climb flight level one two zero, heading two seven zero, Speedbird seven two five',
    partial: 'flight level one two zero, Speedbird four two five',
    noisy: 'uh climb flight level one two, heading two seven zero, one three three decimal one seven five, Speedbird four two five',
  };

  async function loadLog() {
    const rows = await api('/comms/log');
    page.querySelector('#log').innerHTML = table(['When', 'Callsign', 'Verdict', 'By'], rows.slice(0, 12).map((r) => `<tr><td><small>${fmt.date(r.checked_at)}</small></td>
      <td class="callsign">${esc(r.callsign)}</td><td><span class="verdict ${r.verdict}">${r.verdict}</span></td><td>${esc(r.checked_by)}</td></tr>`).join(''), 'No checks yet');
  }

  page.addEventListener('click', async (e) => {
    if (e.target.dataset.sample) { page.querySelector('#rb').value = samples[e.target.dataset.sample]; return; }
    if (e.target.id === 'render') {
      const r = await guard(() => api('/comms/phraseology', 'POST', { clearance: get() }));
      if (r) page.querySelector('#phr').textContent = r.phraseology;
      return;
    }
    if (e.target.id === 'verify') {
      const r = await guard(() => api('/comms/verify', 'POST', { clearance: get(), readback: page.querySelector('#rb').value, on_frequency: onFreq() }));
      if (!r) return;
      page.querySelector('#phr').textContent = r.phraseology;
      page.querySelector('#result').innerHTML = `<div class="notice ${r.verdict === 'CORRECT' ? '' : r.severity === 'confirm' ? 'warn' : 'bad'}" style="margin-top:14px">
        <span class="verdict ${r.verdict}">${r.verdict}</span> ${esc(r.advice)}</div>
        ${table(['Item', 'Issued', 'Read back', 'Status'], r.items.map((i) => `<tr><td>${esc(i.field)}</td><td class="mono">${esc(i.issued)}</td>
          <td class="mono">${esc(i.read_back ?? '—')}</td><td>${badge(i.status, i.status === 'match' ? 'green' : i.status === 'mismatch' ? 'red' : 'orange')}</td></tr>`).join(''))}
        <p style="font-size:12px;margin-top:8px">Normalised transcript: <span class="mono">${esc(r.normalised_readback)}</span></p>
        ${r.similar_callsigns.length ? `<div class="notice warn">Similar callsign on frequency: ${r.similar_callsigns.map((p) => `<b>${esc(p.a)}</b>/<b>${esc(p.b)}</b> (${esc(p.reason)})`).join(', ')}. Use the full callsign and prefer datalink.</div>` : ''}`;
      loadLog();
    }
  });

  const Speech = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (Speech) {
    const mic = page.querySelector('#mic');
    mic.hidden = false;
    mic.addEventListener('click', () => {
      const rec = new Speech();
      rec.lang = 'en-GB';
      rec.onresult = (ev) => { page.querySelector('#rb').value = ev.results[0][0].transcript; };
      rec.onerror = () => mic.textContent = '🎙 Speech unavailable';
      rec.start();
      mic.textContent = '🎙 Listening…';
      rec.onend = () => { mic.textContent = '🎙 Speak'; };
    });
  }

  loadLog();
  const a = await analysis();
  const cs = a.callsigns;
  page.querySelector('#similar').innerHTML = `<p style="font-size:12px;margin-top:-4px">${cs.pair_count} similar pairs were airborne within 40 NM / 10,000 ft of each other
    (likely the same frequency), involving ${cs.share_of_aircraft_pct}% of aircraft.</p>` +
    table(['Pair', 'Why', 'Together', 'Closest'], cs.pairs.map((p) => `<tr><td><span class="callsign">${esc(p.a)}</span> / <span class="callsign">${esc(p.b)}</span></td>
      <td><small>${esc(p.reason)}</small></td><td class="num">${p.co_present_min} min</td><td class="num">${p.closest_nm} NM</td></tr>`).join('')) +
    `<div class="notice" style="margin-top:12px">Verifier accuracy (generated readbacks with 5% speech-recognition noise): <b>${fmt.pct(a.communication.verifier_asr_5pct.detection_rate * 100)}</b> of errors caught,
     <b>${fmt.pct(a.communication.verifier_asr_5pct.hard_false_alarm_rate * 100, 2)}</b> false errors, ${fmt.pct(a.communication.verifier_asr_5pct.confirm_request_rate * 100)} "please confirm" requests.</div>`;
}
