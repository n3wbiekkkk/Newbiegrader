const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');

function harness() {
  const elements = new Map();
  const context = vm.createContext({
    state: { current: 'synthetic', user: { email: 'viewer@example.invalid' }, detailCache: {} },
    _getGen: 1, VERDICT_TH: { AC: 'AC', WA: 'WA', CE: 'CE', RE: 'RE' },
    esc: (s) => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
    $: (id) => {
      if (!elements.has(id)) elements.set(id, { innerHTML: '', textContent: '', value: 'MY_DRAFT',
        classList: { remove() {}, add() {} }, querySelectorAll: () => [] });
      return elements.get(id);
    },
    document: { querySelector: () => ({ scrollIntoView() {} }) },
    show() {}, setTaskTab() {}, setJudgeStatus() {},
    openTask: (pid) => { context.state.current = pid; }, selectProblem: async () => {},
    icon: () => '', scoreCls: () => '', badgeVerdict: (v) => `<b>${v}</b>`,
    verdictSummary: () => '', verdictLegend: () => '', limitsMeta: () => '',
    detailHtml: () => '', highlightCode: (code) => context.esc(code),
    bindCopyButtons() {}, renderTopScores() {}, skel: () => '',
    apiGetCached: async () => ({ configured: true, submissions: [], peer_access: { allowed: true, reason: '' } }),
  });
  vm.runInContext(source.slice(source.indexOf('function renderResults('), source.indexOf('function detailHtml(')), context);
  vm.runInContext(source.slice(source.indexOf('function rowVerdictCode('), source.indexOf('/* ---------------- contests')), context);
  vm.runInContext(source.slice(source.indexOf('async function loadTaskSubs('), source.indexOf('function renderTopScores(')), context);
  return { context, elements };
}

const peer = { problem: 'synthetic', verdict: 'REJECTED', passed: 0, total: 1, score: 0,
  name: 'Peer <Author>', language: 'python', filename: 'peer.py', code: '<peer source>',
  counts: { WA: 1 }, peer_inspection: true,
  results: [{ verdict: 'WA', wall_s: 0.1, cpu_s: 0.05, peak_mb: 8, hidden: true }] };

test('eligible peer details render author, source and per-test measurements without replacing draft', async () => {
  const { context: c } = harness();
  c.apiGet = async () => peer;
  c.detailHtml = () => '';
  await c.viewSubmission('peer');
  const html = c.$('result-body').innerHTML;
  assert.match(html, /Peer &lt;Author&gt;/);
  assert.match(html, /&lt;peer source&gt;/);
  assert.match(html, /0\.1s.*0\.05s.*8MB/s);
  assert.equal(c.$('editor').value, 'MY_DRAFT');
});

test('CE peer target still shows author and source without private compiler output', async () => {
  const { context: c } = harness();
  c.apiGet = async () => ({ ...peer, verdict: 'CE', results: [] });
  await c.viewSubmission('peer');
  assert.match(c.$('result-body').innerHTML, /Peer &lt;Author&gt;/);
  assert.match(c.$('result-body').innerHTML, /&lt;peer source&gt;/);
});

test('late detail response after identity invalidation cannot render source', async () => {
  const { context: c } = harness();
  let finish;
  c.apiGet = () => new Promise((resolve) => { finish = resolve; });
  const pending = c.viewSubmission('peer');
  c._getGen++;
  c.state.user = { email: 'different@example.invalid' };
  finish(peer);
  await pending;
  assert.doesNotMatch(c.$('result-body').innerHTML, /peer source/);
});

test('identity change while selecting another problem cannot render delayed peer source', async () => {
  const { context: c } = harness();
  let finish;
  c.apiGet = async () => ({ ...peer, problem: 'another' });
  c.selectProblem = () => new Promise((resolve) => { finish = resolve; });
  const pending = c.viewSubmission('peer');
  await new Promise(setImmediate);
  c._getGen++;
  finish();
  await pending;
  assert.doesNotMatch(c.$('result-body').innerHTML, /peer source/);
});

test('latest inspection wins when responses arrive out of order', async () => {
  const { context: c } = harness();
  const complete = {};
  c.detailHtml = () => '';
  c.apiGet = (url) => new Promise((resolve) => { complete[url] = resolve; });
  const first = c.viewSubmission('first');
  const second = c.viewSubmission('second');
  complete['/api/history/second']({ ...peer, code: 'SECOND_SOURCE' });
  await second;
  complete['/api/history/first']({ ...peer, code: 'FIRST_SOURCE' });
  await first;
  assert.match(c.$('result-body').innerHTML, /SECOND_SOURCE/);
  assert.doesNotMatch(c.$('result-body').innerHTML, /FIRST_SOURCE/);
});

test('per-problem submissions explain login, contest and hidden locks', async () => {
  const { context: c } = harness();
  for (const [reason, expected] of [['login', /เข้าสู่ระบบ/], ['contest', /การแข่งขัน/],
    ['hidden', /ยังไม่เปิด/], ['unavailable', /ลองอีกครั้ง/]]) {
    c.apiGetCached = async () => ({ configured: true, submissions: [{ id: 'peer', name: 'Peer',
      verdict: 'AC', created_at: '', passed: 1, total: 1, score: 100 }], peer_access: { allowed: false, reason } });
    await c.loadTaskSubs();
    assert.match(c.$('task-all-body').innerHTML, expected);
  }
});

test('403 detail lock explains contest protection and incomplete submissions', async () => {
  const { context: c } = harness();
  c.apiGet = async () => { throw Object.assign(new Error('peer inspection locked: contest protection'), { status: 403 }); };
  await c.viewSubmission('peer');
  assert.match(c.$('result-body').innerHTML, /การแข่งขัน/);
  c.apiGet = async () => { throw Object.assign(new Error('peer inspection locked: incomplete submission'), { status: 403 }); };
  await c.viewSubmission('peer');
  assert.match(c.$('result-body').innerHTML, /ตรวจไม่เสร็จ/);
});

test('identity invalidation clears a previously displayed peer source', () => {
  const { context: c } = harness();
  c._getCache = new Map(); c._getInflight = new Map(); c._detailInflight = new Map();
  c._sampleInflight = new Map(); c._pdfPrefetched = new Set();
  vm.runInContext(source.slice(source.indexOf('function clearGetCache('), source.indexOf('function apiPostJson(')), c);
  c.$('result-body').innerHTML = 'PREVIOUS_PEER_SOURCE';
  c.state.inspectedSubmission = true;
  c.clearGetCache();
  assert.doesNotMatch(c.$('result-body').innerHTML, /PREVIOUS_PEER_SOURCE/);
});
