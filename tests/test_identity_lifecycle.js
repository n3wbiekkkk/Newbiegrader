/* Shared-device identity transitions; actual application functions, synthetic DOM/API. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
function deferred() {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}
function harness() {
  const nodes = new Map(), storage = new Map(), remembered = [], rendered = [], messages = [];
  function node(id) {
    if (!nodes.has(id)) {
      let html = '';
      nodes.set(id, { value: '', disabled: false, title: '',
        get innerHTML() { return html; }, set innerHTML(v) { html = v; },
        get textContent() { return html; }, set textContent(v) { html = v; },
        classList: { add() {}, remove() {}, toggle() {} }, scrollIntoView() {}, querySelectorAll: () => [] });
    }
    return nodes.get(id);
  }
  const c = vm.createContext({
    state: { user: { email: 'a@example.invalid' }, current: 'p', lang: 'python',
      taskTab: 'submit', jobResults: {}, problems: [], authReady: false, is_admin: false },
    $: node, performance, FormData, location: { hash: '#/task/p' },
    document: { querySelector: s => s === '#view-task.active' ? {} : null },
    PROBLEMS_CACHE_KEY: 'synthetic-problems', fi: { value: '' },
    localStorage: { getItem: k => storage.get(k) || null, setItem: (k,v) => storage.set(k,v), removeItem: k => storage.delete(k) },
    setEditorValue: v => { node('editor').value = v; },
    invalidateGetCache() {}, resetSolution() {}, clearSubmissionInspection() {},
    setDraftHint() {}, esc: String, setJudgeStatus() {}, jobStateText: () => '', waitedText: () => '',
    API: '', badge: () => '', shortTime: String, contestCardHtml: () => '', window: { confirm: () => true },
    renderResults: r => { rendered.push(r); node('result-body').innerHTML = r.marker; },
    toast: message => messages.push(message), fetchStats: async () => {}, renderTasksTable() {}, refreshYourScore() {},
    setAdminsStatus: message => { node('admins-status').textContent = message; },
    renderPlagiarism: data => { node('plag-body').innerHTML = data.marker; },
    problemRowsForIdentity: x => x, setLang() {}, setDashCount() {}, skel: () => '',
  });
  function load(start, end) {
    const a = source.indexOf(start), b = source.indexOf(end, a + start.length);
    assert.ok(a >= 0 && b > a, start);
    vm.runInContext(source.slice(a,b), c);
  }
  load('const DRAFT_KEY', 'function lastLang()');
  load('function clearGetCache()', 'function invalidateGetCache()');
  load('function resetPlayground()', 'async function doRun()');
  load('function clearSignedOutWorkspace()', '$("logout-btn").onclick = signOut;');
  load('async function refreshMe()', 'async function restoreInitialSession()');
  load('async function doSubmit()', '/* The verdict label');
  load('const polling = new Set();', 'function jobStateText(');
  load('async function loadAdmins()', 'async function addAdminByEmail(');
  load('async function loadAdminReports()', '/* ---------------- password auth');
  load('async function loadAdminContests()', '/* rejudge:');
  load('async function addAdminByEmail(', 'async function removeAdmin(');
  load('$("plag-btn").onclick = async () => {', '$("plag-threshold").oninput');
  load('$("file-load").onclick = async () => {', '$("template-btn").onclick');
  const remember = c.rememberJob;
  c.rememberJob = (p,j) => { remembered.push(j); remember(p,j); };
  node('editor').value = 'SYNTHETIC_A_SOURCE';
  function switchAfterLogout() {
    c.clearSignedOutWorkspace();
    c.state.user = { email: 'b@example.invalid' };
    c.state.current = 'p';
    node('submit-btn').disabled = true;
  }
  return { c, node, storage, remembered, rendered, messages, switchAfterLogout };
}

for (const outcome of ['resolve','reject']) {
  test(`late scored ${outcome} cannot paint, cache, remember or unlock B's work`, async () => {
    const h = harness(), done = deferred(), polled = deferred();
    h.c.submitWithQueueRetry = async () => ({ job_id: 'synthetic-A-job' });
    h.c.pollJob = () => { polled.resolve(); return done.promise; };
    const pending = h.c.doSubmit();
    await polled.promise;
    h.switchAfterLogout();
    h.c.rememberJob('p','synthetic-B-job');
    if (outcome === 'resolve') done.resolve({ status: 'done', result: { marker: 'PRIVATE_A_RESULT', score: 100 } });
    else done.reject(new Error('PRIVATE_A_ERROR'));
    await pending;
    assert.equal(h.rendered.length, 0);
    assert.equal(h.c.state.jobResults.p, undefined);
    assert.equal(h.c.lastJobFor('p').id, 'synthetic-B-job');
    assert.equal(h.node('submit-btn').disabled, true);
    assert.doesNotMatch(h.node('result-body').innerHTML, /PRIVATE_A/);
  });
}

for (const outcome of ['resolve','reject']) {
  test(`late admin action ${outcome} cannot show private notifications for B`, async () => {
    const h = harness(), reply = deferred();
    h.node('admin-add-email').value = 'private-target@example.invalid';
    h.c.apiPostJson = () => reply.promise;
    const pending = h.c.addAdminByEmail({ preventDefault() {} });
    h.switchAfterLogout(); h.node('admin-add-btn').disabled = true;
    if (outcome === 'resolve') reply.resolve({ email: 'private-target@example.invalid' });
    else reply.reject(new Error('PRIVATE_A_ERROR'));
    await pending;
    assert.equal(h.messages.length, 0);
    assert.equal(h.node('admins-status').textContent, '');
    assert.equal(h.node('admin-add-btn').disabled, true);
  });
  test(`late plagiarism ${outcome} cannot paint previous admin results`, async () => {
    const h = harness(), reply = deferred();
    h.node('plag-problem').value = 'p'; h.c.apiGet = () => reply.promise;
    const pending = h.node('plag-btn').onclick();
    h.switchAfterLogout();
    if (outcome === 'resolve') reply.resolve({ marker: 'PRIVATE_A_COMPARISON' });
    else reply.reject(new Error('PRIVATE_A_ERROR'));
    await pending;
    assert.equal(h.node('plag-body').innerHTML, '');
    assert.equal(h.node('plag-status').textContent, '');
  });
}

test('late admission response does not remember or poll a previous identity job', async () => {
  const h = harness(), admitted = deferred();
  h.c.submitWithQueueRetry = () => admitted.promise;
  h.c.pollJob = () => { throw new Error('must not poll under another identity'); };
  const pending = h.c.doSubmit();
  h.switchAfterLogout();
  admitted.resolve({ job_id: 'synthetic-A-job' });
  await pending;
  assert.equal(h.remembered.length, 0);
  assert.equal(h.node('submit-btn').disabled, true);
});

for (const outcome of ['resolve','reject']) {
  test(`late resumed ${outcome} cannot affect B's result or remembered job`, async () => {
    const h = harness(), done = deferred();
    h.c.pollJob = () => done.promise;
    const pending = h.c.resumeJob('p','synthetic-A-job');
    h.switchAfterLogout(); h.c.rememberJob('p','synthetic-B-job');
    if (outcome === 'resolve') done.resolve({ status: 'done', result: { marker: 'PRIVATE_A_RESULT' } });
    else done.reject(Object.assign(new Error('PRIVATE_A_ERROR'), { keepJob: true }));
    await pending;
    assert.equal(h.rendered.length, 0);
    assert.equal(h.c.state.jobResults.p, undefined);
    assert.equal(h.c.lastJobFor('p').id, 'synthetic-B-job');
  });
}

test('direct account switch clears the editor and isolates draft/job namespaces', async () => {
  const h = harness(); h.c.saveDraft(); h.c.rememberJob('p','A-job');
  h.c.apiGet = async () => ({ user: { email: 'b@example.invalid' }, profile: {}, is_admin: false });
  await h.c.refreshMe();
  assert.equal(h.node('editor').value, '');
  assert.equal(h.c.draftFor('p'), '');
  assert.equal(h.c.lastJobFor('p'), null);
  h.node('editor').value = 'SYNTHETIC_B_SOURCE'; h.c.saveDraft();
  h.c.apiGet = async () => ({ user: { email: 'a@example.invalid' }, profile: {}, is_admin: false });
  await h.c.refreshMe();
  assert.equal(h.c.draftFor('p'), '');
  assert.equal(h.c.lastJobFor('p'), null);
  assert.ok(![...h.storage.values()].join('').includes('SYNTHETIC_B_SOURCE'));
});

test('same account reload retains its namespaced draft and never imports legacy data', async () => {
  const h = harness(); h.c.saveDraft();
  h.storage.set('ng_draft_v1', JSON.stringify({ p: { code: 'LEGACY_PRIVATE_SOURCE' } }));
  h.c.state.user = null;
  h.c.apiGet = async () => ({ user: { email: 'a@example.invalid' }, profile: {}, is_admin: false });
  await h.c.refreshMe();
  assert.equal(h.c.draftFor('p'), 'SYNTHETIC_A_SOURCE');
  assert.equal(h.storage.has('ng_draft_v1'), false);
});

test('explicit logout removes its stored workspace and clears displayed member/admin data', () => {
  const h = harness(); h.c.saveDraft();
  h.node('admin-add-btn').disabled = true;
  h.node('ct-title').value = 'PRIVATE_CONTEST_TITLE';
  h.node('toast-stack').textContent = 'PRIVATE_NOTIFICATION';
  h.node('admin-candidates').innerHTML = 'PRIVATE_EMAIL';
  h.node('hist-body').innerHTML = 'PRIVATE_HISTORY';
  h.c.clearSignedOutWorkspace();
  assert.equal(h.c.state.user, null);
  assert.equal(h.node('editor').value, '');
  assert.equal(h.node('admin-candidates').innerHTML, '');
  assert.equal(h.node('hist-body').innerHTML, '');
  assert.equal(h.node('admin-add-btn').disabled, false);
  assert.equal(h.node('ct-title').value, '');
  assert.equal(h.node('toast-stack').textContent, '');
  h.c.state.user = { email: 'a@example.invalid' };
  assert.equal(h.c.draftFor('p'), '');
});

for (const outcome of ['resolve', 'reject']) {
  for (const action of ['close report', 'delete contest']) {
    test(`late ${action} ${outcome} cannot notify or refresh the next account`, async () => {
      const h = harness(), reply = deferred();
      const button = { dataset: { close: 'private-report', delContest: 'private-round' } };
      const report = action === 'close report';
      h.node(report ? 'admin-reports' : 'ct-list').querySelectorAll = selector =>
        selector === (report ? '[data-close]' : '[data-del-contest]') ? [button] : [];
      h.c.apiGet = async () => report
        ? { configured: true, reports: [{ status: 'open', id: 'private-report' }] }
        : { configured: true, contests: [{ id: 'private-round' }] };
      if (report) await h.c.loadAdminReports(); else await h.c.loadAdminContests();
      h.c.fetch = h.c.apiDelete = () => reply.promise;
      const pending = button.onclick();
      h.switchAfterLogout();
      h.c.apiGet = h.c.refreshProblems = () => { throw new Error('old action refreshed B'); };
      if (outcome === 'resolve') reply.resolve({ ok: true });
      else reply.reject(new Error('PRIVATE_A_ERROR'));
      await pending;
      assert.equal(h.messages.length, 0);
      assert.equal(h.node('admin-reports').innerHTML, '');
      assert.equal(h.node('ct-list').innerHTML, '');
    });
  }
}

test('an old asynchronous file read cannot overwrite the next account editor', async () => {
  const h = harness(), read = deferred();
  h.c.state.file = { text: () => read.promise };
  const pending = h.node('file-load').onclick();
  h.switchAfterLogout(); h.node('editor').value = 'B_SOURCE';
  read.resolve('PRIVATE_A_FILE');
  await pending;
  assert.equal(h.node('editor').value, 'B_SOURCE');
});

for (const outcome of ['resolve','reject']) {
  test(`late admin ${outcome} cannot refill private lists after logout`, async () => {
    const h = harness(), reply = deferred();
    h.c.state.is_admin = true;
    h.c.apiGet = () => reply.promise;
    const pending = h.c.loadAdmins();
    h.switchAfterLogout();
    if (outcome === 'resolve') reply.resolve({ admins: [], candidates: [{ email: 'PRIVATE_A_EMAIL' }] });
    else reply.reject(new Error('PRIVATE_A_ERROR'));
    await pending;
    assert.equal(h.node('admin-candidates').innerHTML, '');
    assert.equal(h.node('admins-list').innerHTML, '');
  });
}
