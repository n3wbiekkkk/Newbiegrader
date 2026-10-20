/* Synthetic detail cache/navigation tests, without a browser or dependencies. */
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");
const { test } = require("node:test");
const source = fs.readFileSync(path.join(__dirname, "../static/app.js"), "utf8");

function harness() {
  let now = 0;
  const requests = [], elements = new Map(), rendered = [];
  const context = vm.createContext({
    Date: { now: () => now },
    state: { detailCache: {}, jobResults: {}, user: null, problems: [] },
    document: { getElementById: () => null },
    apiGet: (url) => new Promise((resolve, reject) => requests.push({ url, resolve, reject })),
    $: (id) => {
      if (!elements.has(id)) elements.set(id, { classList: { add() {}, remove() {} } });
      return elements.get(id);
    },
    fi: {}, saveDraft() {}, setTaskTab() {}, draftFor: () => "", setDraftHint() {},
    shareEditor() {}, renderContestBanner() {}, renderResults() {},
    lastJobFor: () => null, refreshYourScore() {},
    fillTaskDetail: (p) => rendered.push(p),
  });
  vm.runInContext(`const DETAIL_CACHE_TTL = 60000; const _detailInflight = new Map();
    const _getCache = new Map(); const _getInflight = new Map(); let _getGen = 0;
    const _sampleInflight = new Map(); const _pdfPrefetched = new Set();`, context);
  vm.runInContext(source.slice(source.indexOf("function clearGetCache()"),
    source.indexOf("function apiPostJson")), context);
  vm.runInContext(source.slice(source.indexOf("function getProblemDetail("),
    source.indexOf("async function refreshYourScore(")), context);
  return { context, requests, rendered, advance: (ms) => { now += ms; } };
}

test("hover then navigation share one request, fresh revisits use no network", async () => {
  const h = harness();
  h.context.prefetchDetail("synthetic");
  const selected = h.context.selectProblem("synthetic");
  assert.equal(h.requests.length, 1);
  h.requests[0].resolve({ id: "synthetic" });
  await selected;
  assert.equal(h.rendered.length, 1);
  await h.context.selectProblem("synthetic");
  assert.equal(h.requests.length, 1);
  assert.equal(h.rendered.length, 2);
});

test("expired detail refreshes and request errors can retry", async () => {
  const h = harness();
  let pending = h.context.getProblemDetail("a/b");
  assert.equal(h.requests[0].url, "/api/problems/a%2Fb");
  h.requests[0].resolve({ id: "a/b" });
  await pending;
  h.advance(60001);
  pending = h.context.getProblemDetail("a/b");
  h.requests[1].reject(new Error("synthetic outage"));
  await assert.rejects(pending, /synthetic outage/);
  pending = h.context.getProblemDetail("a/b");
  h.requests[2].resolve({ id: "a/b", updated: true });
  assert.equal((await pending).updated, true);
});

test("identity change discards old cache, render and late prefetch responses", async () => {
  const h = harness();
  h.context.prefetchDetail("prefetched");
  const old = h.context.selectProblem("synthetic");
  h.context.clearGetCache();
  const current = h.context.selectProblem("synthetic");
  assert.equal(h.requests.length, 3);
  h.requests[0].resolve({ id: "prefetched", private: true });
  h.requests[1].resolve({ id: "synthetic", private: true });
  await old;
  assert.equal(h.rendered.length, 0);
  assert.equal(h.context.state.detailCache.prefetched, undefined);
  assert.equal(h.context.state.detailCache.synthetic, undefined);
  assert.equal(h.context.getProblemDetail("synthetic"),
    h.context.getProblemDetail("synthetic"), "old cleanup must not delete a new request");
  h.requests[2].resolve({ id: "synthetic", private: false });
  await current;
  assert.equal(h.rendered.length, 1);
  assert.equal(h.rendered[0].private, false);
});

test("late navigation response never replaces the currently selected problem", async () => {
  const h = harness();
  const first = h.context.selectProblem("first");
  const second = h.context.selectProblem("second");
  h.requests[1].resolve({ id: "second" });
  await second;
  h.requests[0].resolve({ id: "first" });
  await first;
  assert.deepEqual(h.rendered.map((p) => p.id), ["second"]);
});
