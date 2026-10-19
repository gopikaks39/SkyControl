// Security & audit: login-attempt log (every wrong attempt is stored), user management, audit trail, password change.
import { api, badge, dialog, esc, fmt, guard, head, kpi, panel, state, table } from '../core.js';
import { doughnut, C } from '../charts.js';

export async function render(root) {
  const sup = state.user.role === 'supervisor';
  root.innerHTML = '<div>' + head('Data & security', 'Security and audit',
    'Passwords are stored as salted PBKDF2 hashes (310,000 iterations). Sessions are opaque, HTTP-only and CSRF-protected. Every login attempt is stored with time, IP, browser and reason; seven failures lock a username for 15 minutes.',
    '<button id="pwd">Change my password</button>') +
    (sup ? '<div id="kp"></div><div class="grid-main"><div id="attempts"></div><div><div id="reasons"></div><div id="users"></div></div></div><div id="audit"></div>'
      : '<div class="notice warn">The login-attempt log, user management and the audit trail are visible to supervisors. Use “Switch account” to sign in as a supervisor.</div>') + '</div>';
  const page = root.firstElementChild;
  page.addEventListener('click', async (e) => {
    if (e.target.id === 'pwd') {
      const v = await dialog('Change password', [{ name: 'current', label: 'Current password', type: 'password', required: true },
        { name: 'password', label: 'New password (12+, letters and digits)', type: 'password', required: true }], 'Change');
      if (v) await guard(() => api('/auth/password', 'POST', v), 'Password changed; other sessions signed out');
    }
    if (e.target.id === 'add-user') {
      const v = await dialog('Create user', [{ name: 'username', label: 'Username', required: true }, { name: 'full_name', label: 'Full name' },
        { name: 'role', label: 'Role', type: 'select', value: 'controller', options: ['controller', 'supervisor'] },
        { name: 'password', label: 'Initial password (12+, letters and digits)', type: 'password', required: true }], 'Create');
      if (v && await guard(() => api('/auth/users', 'POST', v), 'User created')) loadUsers();
    }
    if (e.target.dataset.active) {
      if (await guard(() => api(`/auth/users/${e.target.dataset.active}/active`, 'PUT', { active: e.target.dataset.to === '1' }), 'User updated')) loadUsers();
    }
    if (e.target.id === 'failed-only') loadAttempts();
  });
  if (!sup) return;

  async function loadAttempts() {
    const failedOnly = page.querySelector('#failed-only')?.checked;
    const r = await api('/auth/attempts?limit=300' + (failedOnly ? '&failed_only=true' : ''));
    const failed = r.summary.filter((s) => s.reason !== 'success').reduce((n, s) => n + s.count, 0);
    const ok = r.summary.filter((s) => s.reason === 'success').reduce((n, s) => n + s.count, 0);
    page.querySelector('#kp').innerHTML = `<div class="kpis">${kpi('Successful logins', ok, 'all time', 'accent')}${kpi('Failed attempts', failed, 'stored with reason and IP', failed ? 'bad' : '')}
      ${kpi('Lockouts', (r.summary.find((s) => s.reason === 'locked_out') || { count: 0 }).count, 'attempts refused while locked', 'warn')}${kpi('Distinct usernames tried', new Set(r.attempts.map((a) => a.username)).size, 'in the latest 300 attempts')}</div>`;
    page.querySelector('#attempts').innerHTML = panel('Login attempts', table(['When (UTC)', 'Username tried', 'Result', 'Reason', 'IP', 'Browser'], r.attempts.map((a) => `<tr>
      <td><small>${fmt.date(a.created_at)}</small></td><td class="mono">${esc(a.username || '(blank)')}</td><td>${a.successful ? badge('SUCCESS', 'green') : badge('FAILED', 'red')}</td>
      <td>${esc(a.reason.replace(/_/g, ' '))}</td><td class="mono">${esc(a.ip)}</td><td><small>${esc((a.user_agent || '').slice(0, 48))}</small></td></tr>`).join('')),
      '<label style="margin:0"><input type="checkbox" id="failed-only" style="width:auto"> failed only</label>');
    if (failedOnly) page.querySelector('#failed-only').checked = true;
    page.querySelector('#reasons').innerHTML = panel('Attempt outcomes', '<div class="chart-box short"><canvas id="rc"></canvas></div>');
    const colors = { success: C.green, wrong_password: C.red, unknown_username: C.amber, locked_out: C.violet, account_disabled: C.grey, ip_rate_limited: C.blue, missing_username: C.base };
    doughnut(page.querySelector('#rc'), r.summary.map((s) => s.reason.replace(/_/g, ' ')), r.summary.map((s) => s.count), r.summary.map((s) => colors[s.reason] || C.grey));
  }

  async function loadUsers() {
    const users = await api('/auth/users');
    page.querySelector('#users').innerHTML = panel('Users', table(['User', 'Role', 'Status', ''], users.map((u) => `<tr><td><b>${esc(u.username)}</b><br><small class="muted">${esc(u.full_name)}</small></td>
      <td>${badge(u.role, u.role === 'supervisor' ? 'violet' : 'blue')}</td><td>${u.active ? badge('active', 'green') : badge('disabled', 'red')}</td>
      <td>${u.username !== state.user.username ? `<button class="small" data-active="${u.id}" data-to="${u.active ? 0 : 1}">${u.active ? 'Disable' : 'Enable'}</button>` : ''}</td></tr>`).join('')), '<button class="small primary" id="add-user">+ User</button>');
  }

  async function loadAudit() {
    const items = await api('/audit?limit=200');
    page.querySelector('#audit').innerHTML = panel('Audit trail', table(['When (UTC)', 'Actor', 'Action', 'Entity', 'Details'], items.map((a) => `<tr><td><small>${fmt.date(a.created_at)}</small></td>
      <td>${esc(a.actor)}</td><td class="mono">${esc(a.action)}</td><td>${esc(a.entity)} ${esc(a.entity_id)}</td><td><small class="mono">${esc((a.details || '').slice(0, 120))}</small></td></tr>`).join('')));
  }
  await Promise.all([loadAttempts(), loadUsers(), loadAudit()]);
}
