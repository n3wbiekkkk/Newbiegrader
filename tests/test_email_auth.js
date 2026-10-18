/* Synthetic DOM and responses: never sends an email or uses a real account. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const code = source.slice(source.indexOf('let authMode = "login";'), source.indexOf('/* A versioned notice'));

function harness(replies) {
  const nodes = new Map();
  const calls = [];
  let refreshed = 0;
  function node(id) {
    if (!nodes.has(id)) {
      const classes = new Set();
      nodes.set(id, { value: '', textContent: '', style: {}, checked: false,
        classList: { add: (v) => classes.add(v), remove: (v) => classes.delete(v),
          contains: (v) => classes.has(v),
          toggle: (v, on) => on ? classes.add(v) : classes.delete(v) }, focus() {} });
    }
    return nodes.get(id);
  }
  const context = vm.createContext({ $: node, document: { querySelectorAll: () => [] },
    API: '', location: { hash: '#/login' }, refreshMe: async () => { refreshed++; },
    fetch: async (url, init) => {
      calls.push({ url, payload: JSON.parse(init.body), init });
      const next = replies.shift();
      if (typeof next === 'function') return next();
      return { ok: next.status < 400, status: next.status,
        headers: { get: (k) => (next.headers || {})[k] || null }, json: async () => next.body || {} };
    } });
  vm.runInContext(code, context);
  node('auth-email').value = '  PROOF@example.invalid  ';
  return { node, context, calls, refreshed: () => refreshed };
}

test('signup requests proof without sending or retaining a preselected password', async () => {
  const h = harness([{ status: 202, body: { verification_required: true } }]);
  h.context.setAuthMode('register');
  h.node('auth-pass').value = 'synthetic-preselected';
  await h.context.doPasswordAuth();
  assert.equal(h.calls[0].url, '/api/auth/email/request');
  assert.deepEqual(h.calls[0].payload, { email: 'proof@example.invalid' });
  assert.equal(h.node('auth-pass').value, '');
  assert.equal(h.node('auth-email').readOnly, true);
  assert.equal(h.node('row-auth-code').classList.contains('hidden'), false);
  assert.equal(h.node('auth-err').classList.contains('bad'), false);
  assert.equal(h.refreshed(), 0);
  assert.equal(h.context.location.hash, '#/login');
});

test('verification posts code and newly chosen password; clears both after success', async () => {
  const h = harness([{ status: 202, body: { verification_required: true } }, { status: 200 }]);
  h.context.setAuthMode('register');
  await h.context.doPasswordAuth();
  h.node('auth-code').value = '123456';
  h.node('auth-pass').value = 'synthetic-new-password';
  h.node('auth-remember').checked = true;
  await h.context.doPasswordAuth();
  assert.equal(h.calls[1].url, '/api/auth/email/verify');
  assert.equal(h.calls[1].payload.code, '123456');
  assert.equal(h.calls[1].payload.password, 'synthetic-new-password');
  assert.equal(h.calls[1].payload.remember, true);
  assert.equal(h.calls[1].init.credentials, 'include');
  assert.equal(h.node('auth-code').value, '');
  assert.equal(h.node('auth-pass').value, '');
  assert.equal(h.refreshed(), 1);
  assert.equal(h.context.location.hash, '#/tasks');
});

test('legacy login moves to proof setup without sending an unsolicited email', async () => {
  const h = harness([{ status: 403, headers: { 'X-Email-Verification-Required': 'true' } }]);
  h.node('auth-pass').value = 'synthetic-old';
  await h.context.doPasswordAuth();
  assert.equal(h.calls.length, 1);
  assert.equal(h.node('auth-pass').value, '');
  assert.match(h.node('auth-go').textContent, /ส่งรหัส/);
  assert.equal(h.refreshed(), 0);
});

test('resend uses only the bound email and preserves the challenge on rate limit', async () => {
  const h = harness([{ status: 202, body: { verification_required: true } },
    { status: 429, headers: { 'Retry-After': '59' } }]);
  h.context.setAuthMode('register');
  await h.context.doPasswordAuth();
  h.node('auth-email').value = 'other@example.invalid';
  await h.context.doPasswordAuth(true);
  assert.deepEqual(h.calls[1].payload, { email: 'proof@example.invalid' });
  assert.match(h.node('auth-err').textContent, /59/);
  assert.equal(h.refreshed(), 0);
  assert.equal(h.node('auth-resend').disabled, false);
});

test('concurrent clicks issue one request and busy tabs cannot change the flow', async () => {
  let resolve;
  const pending = new Promise((r) => { resolve = r; });
  const h = harness([() => pending]);
  h.context.setAuthMode('register');
  const first = h.context.doPasswordAuth();
  h.context.setAuthMode('login');
  await h.context.doPasswordAuth();
  assert.equal(h.calls.length, 1);
  resolve({ ok: true, status: 202, json: async () => ({ verification_required: true }) });
  await first;
  assert.equal(h.node('auth-pass').autocomplete, 'new-password');
});

test('provider outage and malformed code do not navigate or authenticate', async () => {
  const h = harness([{ status: 503 }, { status: 202, body: { verification_required: true } }]);
  h.context.setAuthMode('register');
  await h.context.doPasswordAuth();
  assert.equal(h.refreshed(), 0);
  assert.equal(h.node('auth-go').disabled, false);
  await h.context.doPasswordAuth();
  h.node('auth-pass').value = 'synthetic-new-password';
  h.node('auth-code').value = '<script>';
  await h.context.doPasswordAuth();
  assert.equal(h.calls.length, 2);
  assert.match(h.node('auth-err').textContent, /6/);
});
