const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync('static/app.js', 'utf8');

function harness() {
  const elements = new Map(), requests = [], insertedSources = [];
  const element = (id) => {
    if (!elements.has(id)) elements.set(id, {
      hidden: true, textContent: '',
      classList: { add() {}, remove() {}, toggle() {} },
      removeAttribute(name) { delete this[name]; },
      replaceWith(next) { elements.set(id, next); },
    });
    return elements.get(id);
  };
  const context = vm.createContext({
    state: { current: 'first', user: {}, taskTab: 'solution' }, API: '', $: element,
    document: { createElement() {
      const node = { classList: { add() {} },
        replaceWith(next) { insertedSources.push(next.src); elements.set(this.id, next); } };
      return node;
    } },
    apiGet(url) { return new Promise((resolve, reject) => requests.push({ url, resolve, reject })); },
  });
  vm.runInContext(source.slice(source.indexOf('function replaceSolutionFrame('),
    source.indexOf('document.querySelectorAll(".tab-btn").forEach((b) => {\n  b.onclick')), context);
  return { context, requests, element, insertedSources };
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

test('PDF loading and clearing discard the previous browsing context', async () => {
  const h = harness();
  const initial = h.element('solution-frame');
  const pending = h.context.loadSolution();
  const blank = h.element('solution-frame');
  assert.notEqual(blank, initial);
  h.requests[0].resolve({ available: true });
  await pending;
  const loaded = h.element('solution-frame');
  assert.notEqual(loaded, blank);
  assert.equal(loaded.src, '/api/problems/first/solution/pdf');
  assert.equal(h.insertedSources.at(-1), loaded.src);
  h.context.resetSolution();
  assert.notEqual(h.element('solution-frame'), loaded);
  assert.equal(h.element('solution-frame').src, undefined);
});
