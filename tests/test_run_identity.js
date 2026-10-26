/* Synthetic browser DOM and delayed responses; no real account or API. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');

function harness() {
  const nodes = new Map(), pending = [];
  const node = id => {
    if (!nodes.has(id)) nodes.set(id, { value: '', innerHTML: '', textContent: '', disabled: false,
      classList: { add() {}, remove() {} } });
    return nodes.get(id);
  };
  const c = vm.createContext({
    $: node, state: { user: { email: 'a@example.invalid' }, lang: 'python', current: 'p' },
    FormData, performance, PROBLEMS_CACHE_KEY: 'synthetic', fi: { value: '' },
    localStorage: { removeItem() {} }, clearLocalWorkspace() {}, setDraftHint() {},
    setEditorValue: value => { node('editor').value = value; },
    invalidateGetCache() {}, resetSolution() {}, clearSubmissionInspection() {},
    esc: x => String(x),
    apiPostForm: () => new Promise((resolve, reject) => pending.push({ resolve, reject })),
    renderRunResult: d => { node('run-result').innerHTML = d.stdout; },
  });
  vm.runInContext(source.slice(source.indexOf('function clearGetCache()'),
    source.indexOf('function invalidateGetCache()')), c);
  vm.runInContext(source.slice(source.indexOf('function clearSignedOutWorkspace()'),
    source.indexOf('$("logout-btn").onclick = signOut;')), c);
  const reset = source.indexOf('function resetPlayground()');
  if (reset >= 0) vm.runInContext(source.slice(reset, source.indexOf('async function doRun()')), c);
  vm.runInContext(source.slice(source.indexOf('async function doRun()'),
    source.indexOf('function limitsMeta(')), c);
  node('editor').value = 'print(1)';
  return { c, node, pending };
}

test('logout clears rendered run output, status and custom input', () => {
  const h = harness();
  h.node('run-result').innerHTML = 'PRIVATE_A_OUTPUT';
  h.node('run-status').textContent = 'PRIVATE_A_STATUS';
  h.node('run-input').value = 'PRIVATE_A_INPUT';
  h.c.clearSignedOutWorkspace();
  assert.equal(h.node('run-result').innerHTML, '');
  assert.equal(h.node('run-status').textContent, '');
  assert.equal(h.node('run-input').value, '');
});

for (const outcome of ['resolve', 'reject']) {
  test(`late run ${outcome} cannot paint or unlock another account's pending run`, async () => {
    const h = harness();
    const old = h.c.doRun();
    h.c.clearSignedOutWorkspace();
    h.c.state.user = { email: 'b@example.invalid' };
    h.node('editor').value = 'print(2)';
    const current = h.c.doRun();
    if (outcome === 'resolve') h.pending[0].resolve({ stdout: 'PRIVATE_A_OUTPUT' });
    else h.pending[0].reject(new Error('PRIVATE_A_ERROR'));
    await old;
    assert.ok(!h.node('run-result').innerHTML.includes('PRIVATE_A'));
    assert.ok(!h.node('run-status').textContent.includes('PRIVATE_A'));
    assert.equal(h.node('run-btn').disabled, true);
    h.pending[1].resolve({ stdout: 'B_OUTPUT' });
    await current;
    assert.equal(h.node('run-result').innerHTML, 'B_OUTPUT');
    assert.equal(h.node('run-btn').disabled, false);
  });
}

test('identity invalidation clears output and cancels late rendering even for same email', async () => {
  const h = harness();
  const run = h.c.doRun();
  h.c.clearGetCache();
  h.c.state.user = { email: 'a@example.invalid' };
  h.pending[0].resolve({ stdout: 'OLD_SESSION_OUTPUT' });
  await run;
  assert.equal(h.node('run-result').innerHTML, '');
});

test('ordinary cache expiry and same-account profile refresh preserve a legitimate run', async () => {
  const h = harness();
  const run = h.c.doRun();
  h.c.invalidateGetCache();
  h.c.state.user = { email: 'a@example.invalid', name: 'Updated' };
  h.pending[0].resolve({ stdout: 'CURRENT_OUTPUT' });
  await run;
  assert.equal(h.node('run-result').innerHTML, 'CURRENT_OUTPUT');
  assert.equal(h.node('run-btn').disabled, false);
});
