const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync('static/app.js', 'utf8');

function harness() {
  const elements = new Map(), requests = [];
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      hidden: true, textContent: '',
      classList: { add() {}, remove() {}, toggle() {} },
      removeAttribute(name) { delete this[name]; },
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    state: { current: 'first', user: {}, taskTab: 'solution' }, API: '', $: element,
    apiGet(url) { return new Promise((resolve, reject) => requests.push({ url, resolve, reject })); },
  });
  vm.runInContext(source.slice(source.indexOf('function resetSolution()'),
    source.indexOf('document.querySelectorAll(".tab-btn").forEach((b) => {\n  b.onclick')), context);
  return { context, requests, element };
}

test('solution loads only after selection and uses authenticated backend URLs', async () => {
  const h = harness();
  assert.equal(h.requests.length, 0);
  const pending = h.context.loadSolution();
  assert.equal(h.requests[0].url, '/api/problems/first/solution');
  h.requests[0].resolve({ available: true });
  await pending;
  assert.equal(h.element('solution-frame').src, '/api/problems/first/solution/pdf');
  assert.equal(h.element('solution-open').href, '/api/problems/first/solution/pdf');
});

test('navigation, identity change and tab departure reject late responses', async () => {
  for (const change of [c => { c.state.current = 'second'; },
    c => { c.state.user = {}; }, c => { c.state.taskTab = 'submit'; }, c => c.resetSolution()]) {
    const h = harness(), pending = h.context.loadSolution();
    change(h.context);
    h.requests[0].resolve({ available: true });
    await pending;
    assert.equal(h.element('solution-frame').src, undefined);
  }
});

test('policy denial, missing files and outages show useful states and can retry', async () => {
  for (const [status, text] of [[403, 'การแข่งขัน'], [404, 'ยังไม่มีเฉลย'], [503, 'ลองอีกครั้ง']]) {
    const h = harness(), pending = h.context.loadSolution();
    h.requests[0].reject(Object.assign(new Error('denied'), { status }));
    await pending;
    assert.ok(h.element('solution-status').textContent.includes(text));
    assert.equal(h.element('solution-frame').src, undefined);
  }
});

test('leaving the solution removes already displayed bytes and links', async () => {
  const h = harness(), pending = h.context.loadSolution();
  h.requests[0].resolve({ available: true });
  await pending;
  h.context.resetSolution();
  assert.equal(h.element('solution-frame').src, undefined);
  assert.equal(h.element('solution-open').href, undefined);
});
