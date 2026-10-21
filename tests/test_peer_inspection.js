const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');

function loadAppSection(context, start, end) {
  const from = source.indexOf(start);
  assert.notEqual(from, -1, `static/app.js: missing start boundary ${JSON.stringify(start)}`);
  const to = source.indexOf(end, from + start.length);
  assert.ok(to > from,
    `static/app.js: missing end boundary ${JSON.stringify(end)} after ${JSON.stringify(start)}`);
  vm.runInContext(source.slice(from, to), context, {
    filename: `static/app.js [${start} -> ${end}]`,
    lineOffset: source.slice(0, from).split('\n').length - 1,
  });
}

// Keep navigation, workspace selection and result rendering real. Only browser
// primitives and external reads are substituted: queued hashchange events are
// essential to reproducing the cached-problem race that the old harness hid.
function harness(initialRoute = '#/history') {
  const elements = new Map(), events = new Map(), queued = [], storage = new Map();
  const copied = [], entries = [initialRoute];
  let route = initialRoute, entry = 0;
  function element(id) {
    if (!elements.has(id)) {
      const classes = new Set(), attrs = new Map();
      elements.set(id, { id, innerHTML: '', textContent: '', value: '', dataset: {},
        classList: {
          add: (...values) => values.forEach((v) => classes.add(v)),
          remove: (...values) => values.forEach((v) => classes.delete(v)),
          contains: (value) => classes.has(value),
          toggle(value, force = !classes.has(value)) {
            if (force) classes.add(value); else classes.delete(value);
            return force;
          },
        },
        setAttribute: (key, value) => attrs.set(key, String(value)),
        getAttribute: (key) => attrs.get(key), hasAttribute: (key) => attrs.has(key),
        removeAttribute: (key) => attrs.delete(key),
        querySelectorAll: () => [], querySelector: () => null,
        focus() {}, scrollIntoView() { this.scrolled = true; },
      });
    }
    return elements.get(id);
  }
  const views = ['home', 'task', 'tasks', 'history', 'submission', 'login'].map((v) => element('view-' + v));
  function changeRoute(next, kind = 'push') {
    if (route === next) return;
    route = next;
    if (kind === 'push') { entries.splice(entry + 1); entries.push(next); entry++; }
    else if (kind === 'replace') entries[entry] = next;
    queued.push(() => events.get('hashchange')());
  }
  const location = {
    get hash() { return route; }, set hash(value) { changeRoute(value); },
    get href() { return 'http://local.invalid/' + route; },
    replace: (value) => changeRoute(value, 'replace'),
  };
  const document = {
    getElementById: element, addEventListener() {},
    querySelectorAll: (selector) => selector === '.view' ? views : [],
    querySelector(selector) {
      const active = selector.match(/^#(view-[\w-]+)\.active$/);
      if (active) return element(active[1]).classList.contains('active') ? element(active[1]) : null;
      return null;
    },
  };
  const context = vm.createContext({
    state: { current: null, taskTab: 'submit', user: { email: 'viewer@example.invalid' },
      problems: [{ id: 'synthetic', title: 'Synthetic problem' }],
      detailCache: { synthetic: { t: Date.now(), data: { id: 'synthetic' } } },
      jobResults: { synthetic: { result: { verdict: 'WA', score: 0, total: 1, passed: 0,
        counts: { WA: 1 }, results: [], code: 'MY_OWN_SOURCE' }, secs: null } },
    },
    _getGen: 1, _getCache: new Map(), _getInflight: new Map(), _detailInflight: new Map(),
    _sampleInflight: new Map(), _pdfPrefetched: new Set(), DETAIL_CACHE_TTL: 60000,
    document, location, history: { state: null,
      replaceState(value) { this.state = value; },
      back() { if (entry > 0) changeRoute(entries[--entry], 'traverse'); },
      forward() { if (entry < entries.length - 1) changeRoute(entries[++entry], 'traverse'); },
    },
    window: { scrollTo() {}, addEventListener: (name, fn) => events.set(name, fn) },
    navigator: { clipboard: { writeText: async (text) => copied.push(text) } },
    localStorage: { getItem: (key) => storage.get(key), setItem: (key, value) => storage.set(key, value) },
    performance: { now: () => 100 }, FormData: class { append() {} },
    $: element, fi: element('file-input'),
    saveDraft() {}, draftFor: () => 'MY_DRAFT', setDraftHint() {},
    setTaskTab: (tab) => { context.state.taskTab = tab; }, shareEditor() {},
    fillTaskDetail() {}, renderContestBanner() {}, refreshYourScore() {},
    lastJobFor: () => null, getProblemDetail: async () => ({ id: 'synthetic' }),
    stopContestTicker() {}, renderTasksTable() {}, renderHome() {},
    bindCopyButtons() {}, renderTopScores() {}, toast() {}, skel: () => 'loading',
    apiGet: async () => peer,
    apiGetCached: async () => ({ configured: true, submissions: [], peer_access: { allowed: false, reason: 'attempt' } }),
    rememberJob() {}, forgetJob() {}, fetchStats: async () => {},
    pollJob: async () => ({ status: 'done', result: { score: 100, accepted: true, results: [], code: 'NEW_OWN_SOURCE' } }),
  });
  function load(start, end) {
    loadAppSection(context, start, end);
  }
  load('function icon(', '/* Toasts:');
  load('function esc(', '/* ---------------- starter templates');
  load('function setTaskTab(tab)', 'function esc(');
  load('function ioBlockHtml(', 'function renderSample(');
  load('function clearGetCache(', 'function apiPostJson(');
  load('function show(view)', '/* ---------------- home');
  load('async function selectProblem(', 'async function refreshYourScore(');
  load('function jobStateText(', 'const VERDICT_TH =');
  load('const VERDICT_TH =', '/* ---------------- playground');
  load('function limitsMeta(', 'function renderRunResult(');
  load('function rowVerdictCode(', '/* ---------------- contests');
  load('async function loadTaskSubs(', 'function renderTopScores(');
  context.$('editor').value = 'MY_DRAFT';
  return { context, elements, copied,
    async flush() {
      while (queued.length) { queued.shift()(); await new Promise(setImmediate); }
      await new Promise(setImmediate);
    },
    async open(sid) { await context.viewSubmission(sid); await this.flush(); },
    async navigate(hash) { location.hash = hash; await this.flush(); },
    source: () => context.$('submission-body').innerHTML,
  };
}

const peer = { id: 'peer', problem: 'synthetic', verdict: 'REJECTED', passed: 0, total: 1, score: 0,
  created_at: '2026-10-20T03:00:00Z', name: 'Peer <Author>', language: 'python', filename: 'peer.py',
  code: 'print("<peer source>")\n# second line', counts: { WA: 1 }, peer_inspection: true,
  results: [{ verdict: 'WA', wall_s: 0.1, cpu_s: 0.05, peak_mb: 8, hidden: true }] };

test('section loader rejects missing or reversed boundaries before evaluating app code', () => {
  const context = vm.createContext({});
  assert.throws(() => loadAppSection(context, 'MISSING_START_BOUNDARY', 'const VERDICT_TH ='),
    /static\/app\.js: missing start boundary "MISSING_START_BOUNDARY"/);
  assert.throws(() => loadAppSection(context, 'const VERDICT_TH =', 'MISSING_END_BOUNDARY'),
    /static\/app\.js: missing end boundary "MISSING_END_BOUNDARY" after "const VERDICT_TH ="/);
  assert.throws(() => loadAppSection(context, 'const VERDICT_TH =', 'function jobStateText('),
    /static\/app\.js: missing end boundary "function jobStateText\(" after "const VERDICT_TH ="/);
});

test('cached task navigation cannot replace inspected peer with the viewer submission', async () => {
  const h = harness();
  await h.open('peer');
  assert.equal(h.context.location.hash, '#/submission/peer');
  assert.equal(h.context.$('view-submission').classList.contains('active'), true);
  assert.match(h.source(), /Peer &lt;Author&gt;/);
  assert.match(h.source(), /&lt;peer source&gt;/);
  assert.match(h.source(), /0\.1.*0\.05.*8/s);
  assert.doesNotMatch(h.source(), /MY_OWN_SOURCE/);
  assert.equal(h.context.$('editor').value, 'MY_DRAFT');
  assert.equal(h.context.state.current, null);
  assert.equal(h.context.state.jobResults.synthetic.result.code, 'MY_OWN_SOURCE');
});

test('direct routes and Back/Forward fetch the submission named by the URL', async () => {
  const h = harness('#/submission/peer%2Fone');
  h.context.apiGet = async (url) => ({ ...peer, code: url.endsWith('peer%2Fone') ? 'FIRST_SOURCE' : 'SECOND_SOURCE' });
  h.context.router(); await h.flush();
  assert.match(h.source(), /FIRST_SOURCE/);
  await h.open('second');
  assert.match(h.source(), /SECOND_SOURCE/);
  h.context.history.back(); await h.flush();
  assert.match(h.source(), /FIRST_SOURCE/);
  h.context.history.forward(); await h.flush();
  assert.match(h.source(), /SECOND_SOURCE/);
});

test('leaving inspection rejects late results even if the user returns to the same URL', async () => {
  const h = harness(), complete = [];
  h.context.apiGet = () => new Promise((resolve) => complete.push(resolve));
  await h.open('peer');
  await h.navigate('#/tasks');
  await h.open('peer');
  complete[0]({ ...peer, code: 'STALE_SOURCE' }); await h.flush();
  assert.doesNotMatch(h.source(), /STALE_SOURCE/);
  complete[1]({ ...peer, code: 'CURRENT_SOURCE' }); await h.flush();
  assert.match(h.source(), /CURRENT_SOURCE/);
});

test('latest inspection wins when responses arrive out of order', async () => {
  const h = harness(), complete = {};
  h.context.apiGet = (url) => new Promise((resolve) => { complete[url] = resolve; });
  await h.open('first'); await h.open('second');
  complete['/api/history/second']({ ...peer, code: 'SECOND_SOURCE' }); await h.flush();
  complete['/api/history/first']({ ...peer, code: 'FIRST_SOURCE' }); await h.flush();
  assert.match(h.source(), /SECOND_SOURCE/);
  assert.doesNotMatch(h.source(), /FIRST_SOURCE/);
});

test('a delayed task lookup cannot navigate over an opened inspection', async () => {
  const h = harness();
  let finishTask;
  h.context.apiGet = (url) => url.startsWith('/api/problems/')
    ? new Promise((resolve) => { finishTask = resolve; }) : Promise.resolve(peer);
  await h.navigate('#/task/contest-only');
  await h.open('peer');
  finishTask({ id: 'contest-only' }); await h.flush();
  assert.equal(h.context.$('view-submission').classList.contains('active'), true);
  assert.match(h.source(), /&lt;peer source&gt;/);
  assert.equal(h.context.$('editor').value, 'MY_DRAFT');
});

test('identity invalidation removes rendered source and rejects delayed account responses', async () => {
  const h = harness();
  await h.open('peer');
  h.context.clearGetCache();
  assert.doesNotMatch(h.source(), /peer source/);
  let finish;
  h.context.apiGet = () => new Promise((resolve) => { finish = resolve; });
  h.context.currentRouteRender()();
  h.context.clearGetCache();
  h.context.state.user = { email: 'different@example.invalid' };
  finish(peer); await h.flush();
  assert.doesNotMatch(h.source(), /peer source/);
});

test('a normal cache refresh during loading does not discard the requested inspection', async () => {
  const h = harness();
  let finish;
  h.context.apiGet = () => new Promise((resolve) => { finish = resolve; });
  await h.open('peer');
  assert.match(h.context.$('submission-status').textContent, /กำลังโหลด/);
  assert.equal(h.context.$('submission-body').getAttribute('aria-busy'), 'true');
  h.context.invalidateGetCache();
  finish(peer); await h.flush();
  assert.match(h.source(), /&lt;peer source&gt;/);
  assert.equal(h.context.$('submission-body').hasAttribute('aria-busy'), false);
});

test('an own submission finishing in the background preserves inspected source and viewport', async () => {
  const h = harness('#/task/synthetic');
  h.context.state.current = 'synthetic';
  h.context.apiPostForm = async () => ({ job_id: 'own-job' });
  let finish;
  h.context.pollJob = () => new Promise((resolve) => { finish = resolve; });
  const submitting = h.context.doSubmit();
  await new Promise(setImmediate);
  await h.open('peer');
  finish({ status: 'done', result: { score: 100, accepted: true, results: [], code: 'NEW_OWN_SOURCE' } });
  await submitting;
  assert.match(h.source(), /&lt;peer source&gt;/);
  assert.equal(h.context.state.jobResults.synthetic.result.code, 'NEW_OWN_SOURCE');
  assert.equal(h.context.$('result-body').scrolled, undefined);
  assert.equal(h.context.$('view-submission').classList.contains('active'), true);
});

test('peer inspection escapes source, copies the exact text and supports wrapping', async () => {
  const h = harness();
  h.context.apiGet = async () => ({ ...peer, code: '# <script>alert(1)</script>\nprint("&")' });
  await h.open('peer');
  assert.doesNotMatch(h.source(), /<script>/);
  assert.match(h.source(), /&lt;script&gt;/);
  assert.match(h.source(), /source-line-number/);
  await h.context.$('submission-copy').onclick();
  assert.deepEqual(h.copied, ['# <script>alert(1)</script>\nprint("&")']);
  h.context.$('submission-wrap').onclick();
  assert.equal(h.context.$('submission-wrap').getAttribute('aria-pressed'), 'true');
  assert.equal(h.context.$('submission-source').classList.contains('source-wrapped'), true);
});

test('peer CE source stays readable while private diagnostics and test I/O stay absent', async () => {
  const h = harness();
  h.context.apiGet = async () => ({ ...peer, verdict: 'CE', detail: 'PRIVATE_COMPILER_ERROR',
    results: [{ ...peer.results[0], input: 'PRIVATE_INPUT', expected: 'PRIVATE_EXPECTED', actual: 'PRIVATE_OUTPUT' }] });
  await h.open('peer');
  assert.match(h.source(), /Peer &lt;Author&gt;/);
  assert.match(h.source(), /&lt;peer source&gt;/);
  assert.doesNotMatch(h.source(), /PRIVATE_/);
});

test('C++ multiline comments remain highlighted on separately numbered source lines', async () => {
  const h = harness();
  h.context.apiGet = async () => ({ ...peer, language: 'cpp', code: '/* first\nsecond */\nint n = 3;' });
  await h.open('peer');
  assert.match(h.source(), /<span class="tk-c">second \*\/<\/span>/);
  assert.match(h.source(), /<span class="tk-k">int<\/span>/);
  assert.equal((h.source().match(/class="source-line-number"/g) || []).length, 3);
});

test('owners retain authorized failed-practice feedback in the dedicated inspection page', async () => {
  const h = harness();
  h.context.apiGet = async () => ({ ...peer, peer_inspection: false, results: [{ ...peer.results[0],
    hidden: false, practice_feedback: true, input: 'OWNER_INPUT', expected: 'OWNER_EXPECTED', actual: 'OWNER_OUTPUT' }] });
  await h.open('own');
  assert.match(h.source(), /OWNER_INPUT/);
  assert.match(h.source(), /OWNER_EXPECTED/);
  assert.match(h.source(), /OWNER_OUTPUT/);
});

test('per-problem submissions explain signed-in access and login or contest locks', async () => {
  const h = harness(), c = h.context;
  c.state.current = 'synthetic';
  c.state.jobResults = {}; // This viewer has no previous attempts.
  for (const [access, expected] of [
    [{ allowed: true, reason: '' }, /เข้าสู่ระบบแล้ว.*ทุกข้อที่เปิดอยู่/],
    [{ allowed: false, reason: 'login' }, /เข้าสู่ระบบ/],
    [{ allowed: false, reason: 'contest' }, /การแข่งขัน/],
  ]) {
    c.apiGetCached = async () => ({ configured: true, submissions: [{ id: 'peer', name: 'Peer',
      verdict: 'AC', accepted: true, language: 'python', created_at: '', passed: 1, total: 1, score: 100 }], peer_access: access });
    await c.loadTaskSubs();
    assert.match(c.$('task-all-body').innerHTML, expected);
    if (access.allowed) {
      const guidance = c.$('task-all-body').innerHTML.split('</p>')[0];
      assert.doesNotMatch(guidance, /CE|RE|AC|ตรวจเสร็จ/);
      await h.open('peer');
      assert.match(h.source(), /&lt;peer source&gt;/);
      assert.match(h.source(), /Peer &lt;Author&gt;/);
      assert.equal(Object.keys(c.state.jobResults).length, 0);
    }
  }
});

test('locked, unavailable and missing details clear prior code and explain the next step', async () => {
  const h = harness(), c = h.context;
  for (const [status, message, expected] of [
    [403, 'policy denied', /ยังดูโค้ดของเพื่อนไม่ได้/],
    [403, 'contest protection', /การแข่งขัน/],
    [401, 'login first', /เข้าสู่ระบบ/],
    [503, 'unavailable', /ลองอีกครั้ง/],
    [404, 'not found', /ไม่พบ/],
  ]) {
    c.apiGet = async () => peer;
    await h.open('allowed-' + status);
    c.apiGet = async () => { throw Object.assign(new Error(message), { status }); };
    await h.open('locked-' + status);
    assert.doesNotMatch(h.source(), /peer source/);
    assert.match(c.$('submission-status').textContent, expected);
    assert.equal(c.$('view-submission').classList.contains('active'), true);
  }
});
