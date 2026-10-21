#!/usr/bin/env node
/* Style guard for static/styles.css.
 *
 * The design system only works if it is the ONLY way to write colours:
 *  1. no colour literals outside the token blocks (:root and [data-theme="dark"])
 *  2. every var(--x) used actually exists
 *  3. every colour token has a dark-mode counterpart (unless it is a chip that
 *     reads fine on both themes, listed below)
 *  4. every var(--x) defined is used at least once
 *
 * Run from the repo root: node tools/check_styles.js
 */
const fs = require("fs");
const path = require("path");

const FILE = path.join(__dirname, "..", "static", "styles.css");
const css = fs.readFileSync(FILE, "utf8");
const lines = css.split("\n");

/* Tokens that are deliberately identical in both themes: opaque chips whose
 * foreground/background pair is already contrast-checked by hand. */
const THEME_INDEPENDENT = new Set([
  "--green-solid", "--yellow-solid", "--magenta-solid", "--red-solid",
  "--neutral-solid", "--badge-fg",
  "--rank1-bg", "--rank1-fg", "--rank1-line",
  "--rank2-bg", "--rank2-fg", "--rank2-line",
  "--rank3-bg", "--rank3-fg", "--rank3-line",
  "--google-accent",
]);

const problems = [];

/* ---- locate the two token blocks ---- */
function blockRange(selector) {
  const start = lines.findIndex((l) => l.trim().startsWith(selector));
  if (start === -1) return null;
  const depthFrom = lines.slice(start).join("\n").indexOf("{");
  let depth = 0, opened = false;
  for (let i = start; i < lines.length; i++) {
    for (const ch of lines[i]) {
      if (ch === "{") { depth++; opened = true; }
      else if (ch === "}") { depth--; }
    }
    if (opened && depth === 0) return { start, end: i };
  }
  return null;
}

const root = blockRange(":root");
const dark = blockRange('[data-theme="dark"]');
if (!root || !dark) {
  problems.push("could not find the :root and [data-theme=\"dark\"] token blocks");
}

function parseTokens(range) {
  const out = new Map();
  if (!range) return out;
  for (let i = range.start; i <= range.end; i++) {
    // several tokens share a line in the scale blocks, so scan every match
    for (const m of lines[i].matchAll(/(--[a-z0-9-]+)\s*:\s*([^;]+);/gi)) {
      out.set(m[1], m[2].trim());
    }
  }
  return out;
}

const rootTokens = parseTokens(root);
const darkTokens = parseTokens(dark);
const inTokens = (i) => (root && i >= root.start && i <= root.end) ||
  (dark && i >= dark.start && i <= dark.end);

/* ---- 1. colour literals only in the token blocks ---- */
const COLOUR = /#[0-9a-fA-F]{3,8}\b|\brgba?\([^)]*\)|\bhsla?\([^)]*\)/g;
lines.forEach((line, i) => {
  if (inTokens(i) || /^\s*(\/\*|\*)/.test(line)) return;
  const hits = line.match(COLOUR);
  if (hits) {
    problems.push(`line ${i + 1}: colour literal outside the token block: ${hits.join(", ")}`);
  }
});

/* ---- 2 + 4. var() references ---- */
const used = new Map();   // name -> first line
lines.forEach((line, i) => {
  if (/^\s*--[a-z0-9-]+\s*:/i.test(line)) return;      // a definition, not a use
  for (const m of line.matchAll(/var\(\s*(--[a-z0-9-]+)\s*\)/gi)) {
    if (!used.has(m[1])) used.set(m[1], i + 1);
  }
});
for (const [name, line] of used) {
  if (!rootTokens.has(name)) {
    problems.push(`line ${line}: var(${name}) is never defined`);
  }
}
for (const name of rootTokens.keys()) {
  if (!used.has(name)) {
    problems.push(`token ${name} is defined but never used`);
  }
}

/* ---- 3. dark-mode coverage ---- */
for (const [name, value] of rootTokens) {
  if (ROOT_IS_NOT_COLOUR(name, value)) continue;
  if (darkTokens.has(name) || THEME_INDEPENDENT.has(name)) continue;
  problems.push(`token ${name} (${value}) has no [data-theme="dark"] counterpart`);
}

function ROOT_IS_NOT_COLOUR(name, value) {
  if (name.startsWith("--fs-") || name.startsWith("--sp-") ||
      name.startsWith("--r-") || name.startsWith("--lh-")) return true;
  return !/#[0-9a-fA-F]{3,8}|rgba?\(/.test(value);
}

if (problems.length) {
  console.error(`check_styles: ${problems.length} problem(s) in static/styles.css`);
  problems.forEach((p) => console.error("  " + p));
  process.exit(1);
}
console.log(`check_styles: OK (${rootTokens.size} tokens, ${darkTokens.size} dark overrides)`);
