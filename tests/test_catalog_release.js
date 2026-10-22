const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const app = fs.readFileSync('static/app.js', 'utf8');

test('renumbered catalog does not reuse pre-migration browser cache', () => {
  const declaration = app.match(/const PROBLEMS_CACHE_KEY = "([^"]+)";/);
  assert.ok(declaration);
  const namespace = declaration[1].match(/^ng_problems_v(\d+)$/);
  assert.ok(namespace && Number(namespace[1]) >= 3);
  const html = fs.readFileSync('static/index.html', 'utf8');
  const asset = html.match(/src="\/app\.js\?v=(\d+)"/);
  assert.ok(asset && Number(asset[1]) >= 56);
});

test('numeric ordering respects migrated numbers and keeps input objects and slugs', () => {
  const start = app.indexOf('const DIFF_RANK =');
  const end = app.indexOf('\nfunction ', app.indexOf('function sortProblemList(', start) + 1);
  assert.ok(start >= 0 && end > start);
  const context = vm.createContext({ state: { filter: { sort: 'no' } } });
  vm.runInContext(app.slice(start, end), context);
  const input = [
    { id: 'synthetic_hard', no: 3, difficulty: 'hard' },
    { id: 'synthetic_easy', no: 1, difficulty: 'easy' },
    { id: 'synthetic_medium', no: 2, difficulty: 'medium' },
  ];
  const output = context.sortProblemList(input);
  assert.deepEqual(Array.from(output, p => p.id), ['synthetic_easy', 'synthetic_medium', 'synthetic_hard']);
  assert.deepEqual(input.map(p => p.no), [3, 1, 2]);
  assert.equal(output[0], input[1]);
});

test('a task token resolves by slug first and by current number second', () => {
  const resolveStart = app.indexOf('function resolveTaskToken(');
  const resolveEnd = app.indexOf('\nfunction ', resolveStart + 1);
  assert.ok(resolveStart >= 0 && resolveEnd > resolveStart);
  const context = vm.createContext({
    state: { problems: [{ id: 'count_even_odd', no: 2 }, { id: 'hanoi', no: 41 }] },
  });
  vm.runInContext(`${app.slice(resolveStart, resolveEnd)};globalThis.resolveTaskToken = resolveTaskToken;`, context);
  assert.equal(context.resolveTaskToken('hanoi'), 'hanoi');
  assert.equal(context.resolveTaskToken('41'), 'hanoi');
  // A retired number now names the problem that holds it today.
  assert.equal(context.resolveTaskToken('22'), null);
  assert.equal(context.resolveTaskToken('9999'), null);
});
