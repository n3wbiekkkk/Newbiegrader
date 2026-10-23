const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../static/turnstile.js'), 'utf8');

function harness(options = {}) {
  const nodes = new Map(), calls = [], renders = [];
  let resets = 0;
  function node(id) {
    if (!nodes.has(id)) {
      const values = new Set(['hidden']);
      nodes.set(id, { textContent: '', classList: {
        add: v => values.add(v), contains: v => values.has(v),
        toggle: (v, on) => on ? values.add(v) : values.delete(v),
      } });
    }
    return nodes.get(id);
  }
  const window = { GRADER_API_BASE: '', turnstile: {
    render(target, settings) { renders.push({ target, settings }); return 'synthetic-widget-id'; },
    reset(id) { assert.equal(id, 'synthetic-widget-id'); resets++; },
  } };
  const context = vm.createContext({ window, location: { hostname: options.hostname || 'newbiegrader.pages.dev' },
    document: { getElementById: node, createElement: () => ({}), head: { appendChild() {} } },
    AbortSignal, setTimeout, clearTimeout,
    fetch: async (url, init) => {
      calls.push({ url, init });
      if (options.networkError) throw new Error('synthetic network error');
      return { ok: options.status === undefined || options.status === 200,
        status: options.status || 200,
        json: async () => options.config || { enabled: true, sitekey: 'public-test-sitekey' } };
    } });
  vm.runInContext(source, context);
  return { bot: window.GraderBotVerification, node, calls, renders, resets: () => resets };
}

test('widget loads lazily and validates public config before rendering', async () => {
  const h = harness();
  await h.bot.prepare(false);
  assert.equal(h.calls.length, 0);
  await h.bot.prepare(true);
  assert.equal(h.calls[0].url, '/api/auth/bot-config');
  assert.equal(h.calls[0].init.cache, 'no-store');
  assert.equal(h.renders[0].settings.action, 'email_request');
  assert.equal(h.renders[0].settings.sitekey, 'public-test-sitekey');
  assert.equal(h.node('auth-bot-row').classList.contains('hidden'), false);
});

test('each request consumes the available token and reset requires a new callback', async () => {
  const h = harness(); await h.bot.prepare(true);
  const callbacks = h.renders[0].settings;
  callbacks.callback('first-synthetic-token');
  assert.equal(await h.bot.token(), 'first-synthetic-token');
  h.bot.reset(); assert.equal(h.resets(), 1);
  callbacks.callback('second-synthetic-token');
  assert.equal(await h.bot.token(), 'second-synthetic-token');
  callbacks['expired-callback']();
  assert.match(h.node('auth-bot-status').textContent, /อีกครั้ง/);
});

test('provider failure and malformed or missing production config never disable protection', async () => {
  for (const options of [{ networkError: true }, { status: 404 }, { status: 503 },
    { config: { enabled: true, sitekey: '' } }, { config: { enabled: 'false' } }]) {
    const h = harness(options);
    await assert.rejects(h.bot.token());
    assert.equal(h.renders.length, 0);
  }
});

test('explicitly disabled config and local development 404 do not create a widget', async () => {
  for (const options of [{ config: { enabled: false } }, { hostname: 'localhost', status: 404 }]) {
    const h = harness(options);
    assert.equal(await h.bot.token(), null);
    assert.equal(h.renders.length, 0);
    assert.equal(h.node('auth-bot-row').classList.contains('hidden'), true);
  }
});

test('a tab opened before activation fetches the enabled configuration before submitting', async () => {
  const options = { config: { enabled: false } };
  const h = harness(options);
  assert.equal(await h.bot.token(), null);
  options.config = { enabled: true, sitekey: 'public-test-sitekey' };
  await h.bot.prepare(true);
  assert.equal(h.renders.length, 1);
  h.renders[0].settings.callback('fresh-synthetic-token');
  assert.equal(await h.bot.token(), 'fresh-synthetic-token');
});
