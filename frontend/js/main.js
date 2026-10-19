// App shell: login, navigation and page routing.
import { $, $$, api, esc, state, toast } from './core.js';

const PAGES = [
  ['Overview', [['dashboard', '◈', 'Command centre'], ['gaps', '⚑', 'ATC gaps & fixes']]],
  ['Airspace', [['airspace', '◎', '3D airspace (real traffic)'], ['lab', '◇', 'Scenario lab']]],
  ['AI support', [['comms', '✆', 'Communication assistant'], ['models', '⌁', 'AI models & automation']]],
  ['Results', [['analysis', '▥', 'Statistical analysis']]],
  ['Operations', [['flights', '✈', 'Flights'], ['runways', '▤', 'Runways'], ['schedule', '◷', 'Runway scheduling'],
    ['priority', '≋', 'Priority queue'], ['alerts', '⚠', 'Alerts']]],
  ['Data & security', [['data', '▦', 'Data & provenance'], ['security', '⛨', 'Security & audit']]],
];
const LABELS = Object.fromEntries(PAGES.flatMap(([, items]) => items.map(([id, , label]) => [id, label])));

const loaders = {
  dashboard: () => import('./pages/dashboard.js'),
  gaps: () => import('./pages/gaps.js'),
  airspace: () => import('./pages/airspace.js'),
  lab: () => import('./pages/lab.js'),
  comms: () => import('./pages/comms.js'),
  models: () => import('./pages/models.js'),
  analysis: () => import('./pages/analysis.js'),
  flights: () => import('./pages/ops.js').then((m) => ({ render: m.flights })),
  runways: () => import('./pages/ops.js').then((m) => ({ render: m.runways })),
  schedule: () => import('./pages/ops.js').then((m) => ({ render: m.schedule })),
  priority: () => import('./pages/ops.js').then((m) => ({ render: m.priority })),
  alerts: () => import('./pages/ops.js').then((m) => ({ render: m.alerts })),
  data: () => import('./pages/data.js'),
  security: () => import('./pages/security.js'),
};

function showLogin(message) {
  $('#shell').hidden = true;
  $('#login').hidden = false;
  if (message) {
    $('#login-error').textContent = message;
    $('#login-error').hidden = false;
  }
}

async function enter() {
  $('#login').hidden = true;
  $('#shell').hidden = false;
  $('#identity').innerHTML = `<b>${esc(state.user.username)}</b> · ${esc(state.user.role)}`;
  $('#avatar').textContent = state.user.username[0].toUpperCase();
  $('#nav').innerHTML = PAGES.map(([group, items]) => `<div class="group">${esc(group.toUpperCase())}</div>` +
    items.map(([id, icon, label]) => `<button data-page="${id}"><span class="ic">${icon}</span>${esc(label)}</button>`).join('')).join('');
  const hash = location.hash.slice(1);
  go(loaders[hash] ? hash : 'dashboard');
  watchAnalytics();
}

async function watchAnalytics() {
  const status = $('#analytics-status');
  for (let i = 0; i < 120 && state.user; i++) {
    try {
      const h = await fetch('/api/health').then((r) => r.json());
      if (h.analytics_ready) { status.textContent = 'Real-data analysis ready'; return; }
      status.textContent = h.analytics_error ? 'Analysis error: ' + h.analytics_error : 'Analysing the recording…';
    } catch { /* retry */ }
    await new Promise((r) => setTimeout(r, 3000));
  }
}

export async function go(page) {
  state.cleanup.splice(0).forEach((fn) => { try { fn(); } catch { /* ignore */ } });
  state.page = page;
  location.hash = page;
  $$('#nav button').forEach((b) => b.classList.toggle('active', b.dataset.page === page));
  $('#crumb').textContent = LABELS[page] || page;
  const content = $('#content');
  content.innerHTML = '<div class="loading"><span class="spinner"></span> Loading…</div>';
  try {
    const mod = await loaders[page]();
    await mod.render(content);
  } catch (e) {
    content.innerHTML = `<div class="notice bad">Could not load this page: ${esc(e.message)}</div>`;
    console.error(e);
  }
}

$('#nav').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-page]');
  if (b) go(b.dataset.page);
});

$('#login-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  const form = new FormData(e.target);
  const btn = e.target.querySelector('button');
  btn.disabled = true;
  $('#login-error').hidden = true;
  try {
    const r = await api('/auth/login', 'POST', { username: form.get('username'), password: form.get('password') });
    state.user = r.user;
    state.csrf = r.csrf;
    e.target.reset();
    enter();
  } catch (err) {
    const left = err.details && err.details.attempts_remaining;
    const msg = err.status === 401 ? `${err.message}.${left !== undefined && left !== null ? ` ${left} attempt(s) left before a 15-minute lock.` : ''}` : err.message;
    showLogin(msg + ' This attempt has been recorded.');
    $('#login-form').classList.remove('shake');
    void $('#login-form').offsetWidth;
    $('#login-form').classList.add('shake');
  } finally {
    btn.disabled = false;
  }
});

$('#logout').addEventListener('click', async () => {
  try { await api('/auth/logout', 'POST'); } catch { /* session may be gone */ }
  state.user = null;
  state.analysis = null;
  state.cleanup.splice(0).forEach((fn) => fn());
  showLogin();
  toast('Signed out. The current scenario run is kept.');
});

window.addEventListener('skycontrol:signed-out', () => { state.user = null; showLogin('Your session ended. Please sign in again.'); });

setInterval(() => { $('#clock').textContent = new Date().toISOString().slice(11, 19) + ' UTC'; }, 1000);

(async () => {
  try {
    const me = await api('/auth/me');
    state.user = me.user;
    state.csrf = me.csrf;
    enter();
  } catch {
    showLogin();
  }
})();
