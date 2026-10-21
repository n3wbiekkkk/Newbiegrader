// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Newbiegrader contributors
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

const source = fs.readFileSync(path.join(__dirname, '../static/app.js'), 'utf8');
const start = source.indexOf('const VERDICT_TH =');
const end = source.indexOf('/* Colour');
assert.ok(start >= 0 && end > start, 'verdict label block is present');

const context = vm.createContext({
  esc: (value) => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;'),
});
vm.runInContext(source.slice(start, end), context);

for (const code of ['AC', 'WA', 'TLE', 'MLE', 'OLE', 'RE', 'CE']) {
  test(`${code} badge uses the English abbreviation only`, () => {
    const html = context.badgeVerdict(code);
    assert.match(html, new RegExp(`>\\s*${code}\\s*<`));
    assert.match(html, new RegExp(`title="${code}"`));
    assert.doesNotMatch(html, /ผ่าน|คำตอบ|เวลาเกิน|หน่วยความจำ|ผลลัพธ์|ผิดพลาด|คอมไพล์/);
  });
}

test('the Thai verdict legend and full meanings are gone', () => {
  assert.doesNotMatch(source, /VERDICT_MEANING_TH|verdictLegend/);
});
