// Shared client state and helpers: API calls with CSRF, HTML helpers, toast and dialog.
export const state = { user: null, csrf: '', page: 'dashboard', analysis: null, cleanup: [] };

export const $ = (s, root = document) => root.querySelector(s);
export const $$ = (s, root = document) => [...root.querySelectorAll(s)];
export const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

export class ApiError extends Error {
  constructor(message, status, details) { super(message); this.status = status; this.details = details; }
}

export async function api(path, method = 'GET', body) {
  const res = await fetch('/api' + path, {
    method,
    headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf },
    body: body === undefined ? undefined : JSON.stringify(body),
    credentials: 'same-origin',
  });
  let data = null;
  try { data = await res.json(); } catch { data = {}; }
  if (!res.ok) {
    if (res.status === 401 && state.user && path !== '/auth/login') window.dispatchEvent(new Event('skycontrol:signed-out'));
    throw new ApiError(data.error || 'Request failed', res.status, data.details);
  }
  return data;
}

export function toast(message, bad = false) {
  const t = $('#toast');
  t.textContent = message;
  t.className = 'toast' + (bad ? ' bad' : '');
  t.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => (t.hidden = true), 6000);
}

export async function guard(fn, okMessage) {
  try {
    const out = await fn();
    if (okMessage) toast(okMessage);
    return out;
  } catch (e) {
    toast(e.message, true);
    return null;
  }
}

export const fmt = {
  n: (v, d = 0) => (v === null || v === undefined || Number.isNaN(v) ? '–' : Number(v).toLocaleString(undefined, { maximumFractionDigits: d, minimumFractionDigits: d })),
  pct: (v, d = 1) => (v === null || v === undefined ? '–' : `${Number(v).toFixed(d)}%`),
  ft: (v) => (v === null || v === undefined ? '–' : `${Math.round(v).toLocaleString()} ft`),
  fl: (v) => (v > 6000 ? `FL${Math.round(v / 100)}` : `${Math.round(v).toLocaleString()} ft`),
  time: (s) => { s = Math.max(0, Math.round(s)); return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`; },
  utc: (unix) => new Date(unix * 1000).toISOString().slice(11, 19) + ' UTC',
  date: (iso) => (iso ? iso.replace('T', ' ').replace('+00:00', ' UTC').slice(0, 23) : '–'),
  p: (v) => (v === null || v === undefined ? '–' : v < 0.001 ? '< 0.001' : v.toFixed(3)),
};

export const badge = (text, kind = '') => `<span class="badge ${kind}">${esc(text)}</span>`;
export const levelBadge = (level) => `<span class="badge lvl-${esc(level)}">${esc(level)}</span>`;
export const sevKind = (s) => ({ Critical: 'red', High: 'orange', Medium: 'blue', Low: 'green' }[s] || '');

export function head(eyebrow, title, description, extra = '') {
  return `<div class="page-head"><div><span class="eyebrow">${esc(eyebrow)}</span><h1>${title}</h1><p>${description}</p></div>${extra}</div>`;
}

export function panel(title, body, extra = '', cls = '') {
  return `<section class="panel ${cls}"><div class="panel-head"><h3>${title}</h3><div class="row">${extra}</div></div>${body}</section>`;
}

export function kpi(label, value, note = '', cls = '') {
  return `<div class="kpi ${cls}"><span>${esc(label)}</span><strong>${value}</strong><span>${note}</span></div>`;
}

export function table(headers, rowsHtml, empty = 'No records yet') {
  const body = rowsHtml && rowsHtml.length ? rowsHtml : `<tr><td colspan="${headers.length}" class="empty">${esc(empty)}</td></tr>`;
  return `<div class="table-wrap"><table><thead><tr>${headers.map((h) => `<th>${h}</th>`).join('')}</tr></thead><tbody>${body}</tbody></table></div>`;
}

export const loading = (text = 'Loading…') => `<div class="loading"><span class="spinner"></span> ${esc(text)}</div>`;

export function onCleanup(fn) { state.cleanup.push(fn); }

// Modal form. fields: [{name, label, type, value, options, required}]; resolves to an object or null.
export function dialog(title, fields, okText = 'Save', intro = '') {
  const dlg = $('#dialog');
  const body = fields.map((f) => {
    const value = esc(f.value ?? '');
    if (f.type === 'select') {
      return `<label>${esc(f.label)}<select name="${f.name}">${f.options.map((o) => {
        const [v, t] = Array.isArray(o) ? o : [o, o];
        return `<option value="${esc(v)}" ${String(v) === String(f.value) ? 'selected' : ''}>${esc(t)}</option>`;
      }).join('')}</select></label>`;
    }
    if (f.type === 'textarea') return `<label>${esc(f.label)}<textarea name="${f.name}" rows="3">${value}</textarea></label>`;
    return `<label>${esc(f.label)}<input name="${f.name}" type="${f.type || 'text'}" value="${value}" ${f.required ? 'required' : ''} ${f.step ? `step="${f.step}"` : ''}></label>`;
  }).join('');
  $('#dialog-body').innerHTML = `<h2>${esc(title)}</h2>${intro ? `<p>${intro}</p>` : ''}<div class="form-grid">${body}</div>`;
  $('#dialog-ok').textContent = okText;
  dlg.showModal();
  return new Promise((resolve) => {
    const done = (ok) => {
      $('#dialog-ok').onclick = $('#dialog-cancel').onclick = null;
      if (!ok) { dlg.close(); resolve(null); return; }
      const out = {};
      $$('[name]', $('#dialog-body')).forEach((el) => { out[el.name] = el.value; });
      dlg.close();
      resolve(out);
    };
    $('#dialog-ok').onclick = (e) => { e.preventDefault(); if ($('#dialog-form').reportValidity()) done(true); };
    $('#dialog-cancel').onclick = () => done(false);
  });
}

export async function analysis() {
  if (!state.analysis) state.analysis = await api('/analysis');
  return state.analysis;
}
