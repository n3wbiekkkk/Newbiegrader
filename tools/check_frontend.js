#!/usr/bin/env node
// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 Newbiegrader contributors
// Static check: every DOM id referenced from static/app.js must actually be
// created somewhere (static/index.html markup or app.js template literals),
// and every icon referenced by icon("name") / href="#i-name" must have a
// matching <symbol id="i-name"> in static/index.html.
//
// Usage: node tools/check_frontend.js   (exit 1 + list on mismatch)

"use strict";

const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const APP_JS = path.join(ROOT, "static", "app.js");
const INDEX_HTML = path.join(ROOT, "static", "index.html");

function read(p) {
  if (!fs.existsSync(p)) {
    console.error(`missing file: ${p}`);
    process.exit(1);
  }
  return fs.readFileSync(p, "utf8");
}

const js = read(APP_JS);
const html = read(INDEX_HTML);

function matchAll(src, re) {
  const out = [];
  let m;
  re.lastIndex = 0;
  while ((m = re.exec(src)) !== null) out.push(m[1]);
  return out;
}

const uniq = (a) => [...new Set(a)];

// ---- ids referenced from app.js -------------------------------------------
const refHelper = matchAll(js, /\$\("([^"]+)"\)/g); // $("id")
const refDirect = matchAll(js, /getElementById\(\s*["']([^"']+)["']\s*\)/g);
const referencedIds = uniq([...refHelper, ...refDirect]);

// ---- ids that exist -------------------------------------------------------
// 1) declared in index.html markup
const htmlIds = matchAll(html, /\bid="([^"]+)"/g);
// 2) created dynamically by app.js template literals (e.g. innerHTML = `<input
//    id="set-display">`); such ids are never present in index.html.
const jsIds = matchAll(js, /\bid="([^"]+)"/g);
const knownIds = new Set([...htmlIds, ...jsIds]);

// ---- icons ----------------------------------------------------------------
const symbols = new Set(matchAll(html, /<symbol[^>]*\bid="(i-[^"]+)"/g));
const iconCalls = matchAll(js, /\bicon\(\s*["']([^"']+)["']\s*\)/g).map((n) => `i-${n}`);
const hrefRefs = [
  ...matchAll(js, /#(i-[A-Za-z0-9_-]+)/g),
  ...matchAll(html, /#(i-[A-Za-z0-9_-]+)/g),
];
const referencedIcons = uniq([...iconCalls, ...hrefRefs]);

// ---- report ---------------------------------------------------------------
const missingIds = referencedIds.filter((id) => !knownIds.has(id)).sort();
const missingIcons = referencedIcons.filter((name) => !symbols.has(name)).sort();

let failed = false;
if (missingIds.length) {
  failed = true;
  console.error(`missing ids referenced from static/app.js (${missingIds.length}):`);
  for (const id of missingIds) console.error(`  - ${id}`);
}
if (missingIcons.length) {
  failed = true;
  console.error(`missing <symbol> icons referenced in static/ (${missingIcons.length}):`);
  for (const name of missingIcons) console.error(`  - ${name}`);
}

if (failed) {
  console.error("check_frontend: FAIL");
  process.exit(1);
}

console.log(
  `check_frontend: OK (${referencedIds.length} ids referenced, ` +
    `${referencedIcons.length} icons referenced, ${symbols.size} symbols defined)`
);
