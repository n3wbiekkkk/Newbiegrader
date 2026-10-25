/* Synthetic account deletion: no real account or provider is contacted. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const email = 'learner@example.invalid';

function harness() {
  const elements = new Map(), calls = [], messages = [];
  const node = id => {
    if (!elements.has(id)) {
      const classes = new Set(['hidden']);
      elements.set(id, { value: '', disabled: false, textContent: '', innerHTML: '', attrs: {},
        classList: { add: x => classes.add(x), remove: x => classes.delete(x), contains: x => classes.has(x),
          toggle(x, force) { if (force) classes.add(x); else classes.delete(x); } },
        setAttribute(key, value) { this.attrs[key] = value; }, focus() { this.focused = true; } });
    }
    return elements.get(id);
  };
  const c = vm.createContext({
    $: node, state: { user: { email }, current: 'synthetic', jobResults: {}, lang: 'python' }, _getGen: 0,
    document: { querySelectorAll: () => [] }, window: { matchMedia: () => ({ matches: true }) },
    API: '', PROBLEMS_CACHE_KEY: 'synthetic-cache', fi: { value: 'synthetic.py' }, location: { hash: '#/settings' },
    localStorage: { removeItem() {} },
    apiFetch: async (url, opts) => { calls.push({ url, opts }); return { ok: true, profile: JSON.parse(opts.body) }; },
    apiGet: async () => ({ configured: true, profile: { email, name: 'Learner' } }),
    clearGetCache() { c._getGen++; }, clearLocalWorkspace: () => calls.push('workspace'),
    setEditorValue: value => { node('editor').value = value; }, setDraftHint() {},
    refreshMe: async () => {}, loadPublicHome: async () => {}, renderHome() {},
    toast: message => messages.push(message), esc: value => String(value), skel: () => 'loading', setLang: value => { c.state.lang = value; },
    emptyStateHtml: () => 'sign in',
  });
  vm.runInContext(source.slice(source.indexOf('function clearSignedOutWorkspace()'),
    source.indexOf('$("logout-btn").onclick = signOut;')), c);
  vm.runInContext(source.slice(source.indexOf('async function renderSettings()'),
    source.indexOf('/* ---------------- admin tools')), c);
  const render = () => c.renderAccountDeletion();
  const enter = value => { node('account-delete-email').value = value; node('account-delete-email').oninput(); };
  const submit = () => node('account-delete-form').onsubmit({ preventDefault() {} });
  render();
  return { c, node, calls, messages, render, enter, submit };
}

test('guests have no deletion controls and stale handlers cannot submit', async () => {
  const h = harness();
  h.c.state.user = null;
  h.render();
  assert.ok(h.node('settings-deletion').classList.contains('hidden'));
  h.node('account-delete-email').value = email;
  await h.submit();
  assert.equal(h.calls.length, 0);
});

test('confirmation is progressive, exact, and cancel clears it without a request', async () => {
  const h = harness();
  assert.ok(h.node('account-delete-form').classList.contains('hidden'));
  h.node('account-delete-open').onclick();
  assert.equal(h.node('account-delete-open').attrs['aria-expanded'], 'true');
  assert.ok(h.node('account-delete-email').focused);
  h.enter(email.toUpperCase());
  assert.ok(h.node('account-delete-confirm').disabled);
  await h.submit();
  h.enter(email);
  assert.equal(h.node('account-delete-confirm').disabled, false);
  h.node('account-delete-cancel').onclick();
  assert.equal(h.node('account-delete-email').value, '');
  assert.ok(h.node('account-delete-form').classList.contains('hidden'));
  assert.equal(h.calls.length, 0);
});

test('admin must remove privileges and cannot bypass disabled UI by submitting', async () => {
  const h = harness();
  h.c.state.is_admin = true;
  h.render();
  assert.equal(h.node('account-delete-admin').classList.contains('hidden'), false);
  assert.ok(h.node('account-delete-open').disabled);
  h.enter(email);
  await h.submit();
  assert.equal(h.calls.length, 0);
});

test('pending deletion cannot be double submitted, cancelled, or replayed after render', async () => {
  const h = harness();
  let resolve;
  h.c.apiFetch = (url, opts) => { h.calls.push({ url, opts }); return new Promise(r => { resolve = r; }); };
  h.enter(email);
  const pending = h.submit();
  assert.ok(h.node('account-delete-confirm').disabled);
  assert.ok(h.node('account-delete-cancel').disabled);
  assert.equal(h.node('account-delete-form').attrs['aria-busy'], 'true');
  h.render();
  h.node('account-delete-email').value = email;
  await h.submit();
  assert.equal(h.calls.length, 1);
  resolve({ ok: true });
  await pending;
  const { url, opts } = h.calls[0];
  assert.equal(url, '/api/profile');
  assert.equal(opts.method, 'DELETE');
  assert.equal(opts.credentials, 'include');
  assert.deepEqual(JSON.parse(opts.body), { confirmation: email });
});

test('success clears private drafts, caches, identity and chrome before returning home', async () => {
  const h = harness();
  h.node('editor').value = 'PRIVATE_DRAFT';
  h.enter(email);
  await h.submit();
  assert.equal(h.c.state.user, null);
  assert.equal(h.c.state.current, null);
  assert.equal(h.c._getGen, 1);
  assert.equal(h.node('editor').value, '');
  assert.ok(h.calls.includes('workspace'));
  assert.ok(h.node('user-chip').classList.contains('hidden'));
  assert.equal(h.c.location.hash, '#/');
  assert.match(h.messages[0], /ลบบัญชีแล้ว/);
});

test('busy conflict preserves account and draft, and allows retry after jobs finish', async () => {
  const h = harness();
  h.c.apiFetch = async () => { throw Object.assign(new Error('ยังมีงานตรวจอยู่ กรุณารอให้งานจบก่อนลบบัญชี'), { status: 409 }); };
  h.node('editor').value = 'PRIVATE_DRAFT';
  h.enter(email);
  await h.submit();
  assert.equal(h.c.state.user.email, email);
  assert.equal(h.node('editor').value, 'PRIVATE_DRAFT');
  assert.match(h.node('account-delete-status').textContent, /รอให้งานจบ/);
  assert.equal(h.node('account-delete-confirm').disabled, false);
  assert.equal(h.messages.length, 0);
});

for (const kind of ['network', 503, 'malformed']) {
  test(`uncertain ${kind} never claims success, retries, or clears workspace`, async () => {
    const h = harness();
    let requests = 0;
    h.c.apiFetch = async () => {
      requests++;
      if (kind === 'malformed') return {};
      throw Object.assign(new Error('synthetic failure'), kind === 'network' ? {} : { status: kind });
    };
    h.enter(email);
    await h.submit();
    await h.submit();
    h.render();
    assert.ok(h.node('account-delete-open').disabled);
    assert.match(h.node('account-delete-status').textContent, /ยังยืนยัน/);
    assert.equal(h.node('account-delete-help').classList.contains('hidden'), false);
    assert.equal(requests, 1);
    assert.equal(h.messages.length, 0);
    assert.equal(h.calls.length, 0);
    assert.equal(h.c.state.user.email, email);
  });
}

test('late deletion response cannot clear another login or claim its deletion', async () => {
  const h = harness();
  let resolve;
  h.c.apiFetch = () => new Promise(r => { resolve = r; });
  h.enter(email);
  const pending = h.submit();
  h.c.state.user = { email: 'another@example.invalid' };
  h.c._getGen++;
  resolve({ ok: true });
  await pending;
  assert.equal(h.c.state.user.email, 'another@example.invalid');
  assert.equal(h.c.location.hash, '#/settings');
  assert.equal(h.messages.length, 0);
});

test('late profile response cannot restore erased account details', async () => {
  const h = harness();
  let resolve;
  h.c.apiGet = () => new Promise(r => { resolve = r; });
  const pending = h.c.renderSettings();
  h.c.clearSignedOutWorkspace();
  h.node('settings-body').innerHTML = '';
  resolve({ configured: true, profile: { email, name: 'PRIVATE_NAME' } });
  await pending;
  assert.equal(h.node('settings-body').innerHTML, '');
});

test('profile save requires changes, uses one credentialed PUT and updates visible name', async () => {
  const h = harness();
  await h.c.renderSettings();
  assert.ok(h.node('settings-save').disabled);
  h.node('set-display').value = 'New learner';
  h.node('set-display').oninput();
  assert.equal(h.node('settings-save').disabled, false);
  assert.match(h.node('settings-status').textContent, /ยังไม่ได้บันทึก/);
  await h.node('settings-profile-form').onsubmit({ preventDefault() {} });
  assert.equal(h.calls[0].opts.method, 'PUT');
  assert.equal(h.calls[0].opts.credentials, 'include');
  assert.equal(h.node('user-chip').textContent, 'New learner');
  assert.ok(h.node('settings-save').disabled);
  assert.equal(h.c.state.settingsDraft.dirty, false);
  assert.equal(h.node('settings-status').textContent, 'บันทึกแล้ว');
});

test('failed profile save retains edits across rendering and discard restores the saved values', async () => {
  const h = harness();
  h.c.apiFetch = async () => { throw new Error('synthetic failure'); };
  await h.c.renderSettings();
  h.node('set-display').value = 'Unsaved learner';
  h.node('set-lang').value = 'cpp';
  h.node('set-display').oninput();
  await h.node('settings-profile-form').onsubmit({ preventDefault() {} });
  assert.equal(h.node('set-display').value, 'Unsaved learner');
  assert.match(h.node('settings-status').textContent, /ไม่สำเร็จ/);
  await h.c.renderSettings();
  assert.equal(h.node('set-display').value, 'Unsaved learner');
  assert.equal(h.node('set-lang').value, 'cpp');
  h.node('settings-discard').onclick();
  assert.equal(h.node('set-display').value, '');
  assert.equal(h.node('set-lang').value, 'python');
  assert.ok(h.node('settings-save').disabled);
});

test('profile save cannot double submit, and a late response cannot paint another account', async () => {
  const h = harness();
  await h.c.renderSettings();
  let resolve, requests = 0;
  h.c.apiFetch = () => { requests++; return new Promise(r => { resolve = r; }); };
  h.node('set-display').value = 'Private name';
  h.node('set-display').oninput();
  const first = h.node('settings-profile-form').onsubmit({ preventDefault() {} });
  assert.ok(h.node('set-display').disabled);
  await h.node('settings-profile-form').onsubmit({ preventDefault() {} });
  assert.equal(requests, 1);
  h.c.state.user = { email: 'another@example.invalid' };
  h.c._getGen++;
  h.node('user-chip').textContent = 'Another';
  resolve({ ok: true, profile: { display_name: 'Private name' } });
  await first;
  assert.equal(h.node('user-chip').textContent, 'Another');
  assert.equal(h.messages.length, 0);
});

test('profile load failure offers retry and does not wipe an unsaved draft', async () => {
  const h = harness();
  await h.c.renderSettings();
  h.node('set-display').value = 'Keep this name';
  h.node('set-display').oninput();
  h.c.apiGet = async () => { throw new Error('synthetic unavailable'); };
  await h.c.renderSettings();
  assert.match(h.node('settings-body').innerHTML, /ลองโหลดใหม่/);
  assert.equal(h.c.state.settingsDraft.displayName, 'Keep this name');
  assert.equal(h.node('settings-body').attrs['aria-busy'], 'false');
});
