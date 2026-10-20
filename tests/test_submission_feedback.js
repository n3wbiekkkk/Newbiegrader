const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(require('node:path').join(__dirname, '../static/app.js'), 'utf8');
const context = vm.createContext({
  VERDICT_TH: { RE: 'runtime error' },
  esc: (s) => String(s).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;'),
  ioBlockHtml: (label, value) => `<section>${label}<pre>${context.esc(value)}</pre></section>`,
});
vm.runInContext(source.slice(source.indexOf('function diffHtml('), source.indexOf('/* ---------------- playground')), context);

for (const verdict of ['WA', 'RE', 'TLE', 'MLE', 'OLE']) {
  test(`${verdict} exposes public input, expected and partial actual output with safe escaping`, () => {
    const html = context.detailHtml({ verdict, input: 'PUBLIC_INPUT', expected: 'EXPECTED',
      actual: '<script>partial</script>', detail: '<img src=x>', diff: '-EXPECTED\n+wrong' });
    assert.match(html, /PUBLIC_INPUT/);
    assert.match(html, /EXPECTED/);
    assert.match(html, /&lt;script&gt;partial/);
    assert.doesNotMatch(html, /<script>|<img /);
    assert.match(html, /2,000/);
  });
}

test('hidden failures never render I/O, diff or untrusted diagnostic fields', () => {
  const html = context.detailHtml({ verdict: 'RE', hidden: true, input: 'SECRET_CANARY',
    expected: 'SECRET_CANARY', actual: 'SECRET_CANARY', diff: 'SECRET_CANARY', detail: 'SECRET_CANARY' });
  assert.doesNotMatch(html, /SECRET_CANARY/);
  assert.match(html, /ไม่เปิดเผย input\/output/);
});

test('old history without I/O does not pretend missing data is an empty result', () => {
  const html = context.detailHtml({ verdict: 'RE', detail: 'exit code 7' });
  assert.match(html, /exit code 7/);
  assert.doesNotMatch(html, /expected output|actual output|2,000/);
});

test('rendered result I/O copy buttons receive handlers, including history renders', () => {
  let bound = 0;
  const elements = new Map();
  context.$ = (id) => {
    if (!elements.has(id)) elements.set(id, { textContent: '', classList: { remove() {} },
      querySelectorAll: () => [] });
    return elements.get(id);
  };
  context.bindCopyButtons = (body) => { assert.equal(body, context.$('result-body')); bound++; };
  context.renderResults({verdict:'CE', passed:0, total:1, score:0, compile_error:'synthetic'}, null);
  assert.equal(bound, 1);
});

test('authorized practice failure labels do not pretend the case was a PDF sample', () => {
  const html = context.detailHtml({ verdict:'WA', practice_feedback:true, input:'practice',
    expected:'ok', actual:'wrong' });
  assert.match(html, /input \(เคสที่ผิด\)/);
  assert.doesNotMatch(html, /เคสสาธารณะ/);
});
