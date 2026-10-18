const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const code = fs.readFileSync(path.join(__dirname, '../functions/api/[[proxy]].js'), 'utf8')
  .replace('export async function onRequest', 'async function onRequest') + '\nthis.onRequest = onRequest;';

function harness() {
  const calls = [];
  const context = vm.createContext({ URL, Request, Response, Headers, Uint8Array,
    fetch: async (url, init) => { calls.push({ url, init }); return new Response('ok'); } });
  vm.runInContext(code, context);
  return { calls, run: (request, env = {}) => context.onRequest({ request, env, waitUntil() {} }) };
}

test('unset origin preserves existing production; approved HTTPS origin is selectable', async () => {
  const h = harness();
  await h.run(new Request('https://frontend.invalid/api/health'));
  await h.run(new Request('https://frontend.invalid/api/health?q=1'), { BACKEND_ORIGIN: 'https://staging.invalid' });
  assert.equal(h.calls[0].url, 'https://grader.n.onjrnm.vip/api/health');
  assert.equal(h.calls[1].url, 'https://staging.invalid/api/health?q=1');
});

test('invalid origin configurations fail closed without a fetch', async () => {
  for (const value of ['http://insecure.invalid', 'https://user:password@invalid.test', 'https://invalid.test/path', 'https://invalid.test/?secret=1']) {
    const h = harness();
    const r = await h.run(new Request('https://frontend.invalid/api/health'), { BACKEND_ORIGIN: value });
    assert.equal(r.status, 503);
    assert.equal(h.calls.length, 0);
  }
});

test('proxy replaces spoofed credentials and forwarding headers with trusted values', async () => {
  const h = harness();
  await h.run(new Request('https://frontend.invalid/api/health', { headers: {
    'x-newbiegrader-proxy-key': 'synthetic-attacker', 'x-forwarded-for': '198.51.100.99',
    'cf-connecting-ip': '192.0.2.10', 'x-real-ip': '198.51.100.99',
  } }), { BACKEND_PROXY_KEY: 'synthetic-origin-key' });
  const headers = h.calls[0].init.headers;
  assert.equal(headers.get('x-newbiegrader-proxy-key'), 'synthetic-origin-key');
  assert.equal(headers.get('x-forwarded-for'), '192.0.2.10');
  assert.equal(headers.get('x-real-ip'), null);
  assert.equal(headers.get('cf-connecting-ip'), null);
  const unset = harness();
  await unset.run(new Request('https://frontend.invalid/api/health', { headers: { 'x-newbiegrader-proxy-key': 'synthetic-attacker' } }));
  assert.equal(unset.calls[0].init.headers.get('x-newbiegrader-proxy-key'), null);
});

test('oversize declared and streamed bodies never reach backend', async () => {
  for (const declared of [false, true]) {
    const h = harness();
    const request = new Request('https://frontend.invalid/api/submit', {
      method: 'POST', body: new Uint8Array(1024 * 1024 + 1),
      headers: declared ? { 'content-length': String(1024 * 1024 + 1) } : {},
    });
    assert.equal((await h.run(request)).status, 413);
    assert.equal(h.calls.length, 0);
  }
});

test('bounded multipart body and OAuth redirects preserve their contracts', async () => {
  const h = harness();
  const body = '--synthetic\r\nfield=hello\r\n--synthetic--';
  await h.run(new Request('https://frontend.invalid/api/submit', { method: 'POST', body,
    headers: { 'content-type': 'multipart/form-data; boundary=synthetic', 'content-length': String(body.length) } }));
  assert.equal(new TextDecoder().decode(h.calls[0].init.body), body);
  assert.equal(h.calls[0].init.headers.get('content-type'), 'multipart/form-data; boundary=synthetic');
  assert.equal(h.calls[0].init.headers.get('content-length'), null);
  assert.equal(h.calls[0].init.redirect, 'manual');
});
