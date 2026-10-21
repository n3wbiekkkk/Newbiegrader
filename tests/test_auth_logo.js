// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Newbiegrader contributors
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');

const root = path.join(__dirname, '..');
const html = fs.readFileSync(path.join(root, 'static/index.html'), 'utf8');
const css = fs.readFileSync(path.join(root, 'static/styles.css'), 'utf8');

test('shared login/register Google button has a local decorative brand image', () => {
  const button = html.match(/<button\b[^>]*id="google-btn"[^>]*>([\s\S]*?)<\/button>/);
  assert.ok(button);
  assert.match(button[1], /<img\b[^>]*class="google-logo"[^>]*src="\/google-g\.png"/);
  assert.match(button[1], /width="20" height="20" alt="" aria-hidden="true"/);
  assert.match(button[1], /<span>Continue with Google<\/span>/);
  assert.doesNotMatch(button[1], /<svg|<use|https?:\/\//);
  const png = fs.readFileSync(path.join(root, 'static/google-g.png'));
  assert.deepEqual(png.subarray(0, 8), Buffer.from([137, 80, 78, 71, 13, 10, 26, 10]));
  assert.ok(png.length < 64 * 1024, 'sign-in icon must stay small');
});

test('logo keeps its colors and proportions without theme-specific filters', () => {
  const rule = css.match(/\.google-logo\s*\{([^}]+)\}/);
  assert.ok(rule);
  assert.match(rule[1], /object-fit:\s*contain/);
  assert.match(rule[1], /flex:\s*0 0 20px/);
  assert.doesNotMatch(rule[1], /filter|opacity|mix-blend-mode/);
});
