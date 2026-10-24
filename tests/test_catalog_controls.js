/* Catalog controls use synthetic DOM nodes; no accounts or backend required. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync('static/app.js', 'utf8');

function loadFilterValues(context) {
  const start = source.indexOf('function filterValues(');
  vm.runInContext(source.slice(start, source.indexOf('function syncDifficultyFilters(', start)), context);
}

test('multiple topics toggle independently without closing the selection panel', () => {
  let renders = 0;
  const context = vm.createContext({
    state: { filter: { tag: [] } }, renderTagList() {},
    renderTasksTable() { renders++; }, document: { querySelector: () => ({}) },
  });
  loadFilterValues(context);
  vm.runInContext(source.slice(source.indexOf('function setTagFilter('), source.indexOf('function setStatusFilter(')), context);
  context.setTagFilter('Math'); context.setTagFilter('String');
  assert.deepEqual(Array.from(context.state.filter.tag), ['Math', 'String']);
  context.setTagFilter('Math');
  assert.deepEqual(Array.from(context.state.filter.tag), ['String']);
  assert.equal(renders, 3);
});

for (const key of ['q', 'all']) {
  test(`clearing ${key === 'all' ? 'all filters retains the sort order' : 'a search retains difficulty, topic and status'}`, () => {
    let rendered = 0, focused = false, cancelled = false;
    const fields = { q: { value: 'prime', focus() { focused = true; } }, 'f-diff': { value: 'medium' },
      'catalog-active-filters': { querySelector: () => null } };
    const context = vm.createContext({
      state: { filter: { q: 'prime', diff: 'medium', tag: 'Math', status: 'tried', sort: 'title' }, _qTimer: 10 },
      $: id => fields[id],
      document: { querySelectorAll: () => [] },
      clearTimeout: () => { cancelled = true; },
      renderTagList() {}, renderTasksTable() { rendered++; },
    });
    const start = source.indexOf('function clearCatalogFilter(');
    vm.runInContext(source.slice(start, source.indexOf('function renderCatalogFilters(', start)), context);
    context.clearCatalogFilter(key);
    assert.equal(context.state.filter.q, '');
    assert.equal(context.state.filter.sort, 'title');
    if (key === 'all') {
      assert.deepEqual(Array.from(context.state.filter.diff), []);
      assert.deepEqual(Array.from(context.state.filter.tag), []);
    } else {
      assert.equal(context.state.filter.diff, 'medium');
      assert.equal(context.state.filter.tag, 'Math');
    }
    assert.equal(context.state.filter.status, key === 'all' ? 'all' : 'tried');
    assert.equal(rendered, 1);
    assert.equal(cancelled, true);
    assert.equal(focused, true);
  });
}

test('levels and topics use OR within a group and AND between groups, including legacy saved values', () => {
  const context = vm.createContext({
    state: { filter: { q: '', diff: ['easy', 'medium'], tag: ['Math', 'String'], status: 'all', sort: 'no' }, myBest: {},
      problems: [
        { id: 'one', no: 1, title: 'One', difficulty: 'easy', tags: ['Math'] },
        { id: 'two', no: 2, title: 'Two', difficulty: 'medium', tags: ['String'] },
        { id: 'three', no: 3, title: 'Three', difficulty: 'hard', tags: ['Math'] },
        { id: 'four', no: 4, title: 'Four', difficulty: 'medium', tags: ['Graph'] },
      ] },
  });
  const start = source.indexOf('function filterValues(');
  vm.runInContext(source.slice(start, source.indexOf('function taskScoreHtml(', start)), context);
  const ids = () => Array.from(context.filteredProblems(), p => p.id);
  assert.deepEqual(ids(), ['one', 'two']);
  context.state.filter.diff = 'medium'; context.state.filter.tag = 'String';
  assert.deepEqual(ids(), ['two']);
  context.state.filter.diff = []; context.state.filter.tag = [];
  assert.deepEqual(ids(), ['one', 'two', 'three', 'four']);
});

test('removing one selected topic keeps every other selection', () => {
  const context = vm.createContext({
    state: { filter: { q: '', diff: ['easy', 'medium'], tag: ['Math', 'String'], status: 'all', sort: 'no' } },
    $: () => ({ querySelector: () => null, focus() {} }), document: { querySelectorAll: () => [] },
    clearTimeout() {}, renderTagList() {}, renderTasksTable() {},
  });
  loadFilterValues(context);
  const start = source.indexOf('function clearCatalogFilter(');
  vm.runInContext(source.slice(start, source.indexOf('function renderCatalogFilters(', start)), context);
  context.clearCatalogFilter('tag', 'Math');
  assert.deepEqual(Array.from(context.state.filter.tag), ['String']);
  assert.deepEqual(Array.from(context.state.filter.diff), ['easy', 'medium']);
});
