const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const source = fs.readFileSync(path.join(__dirname, '../deploy/ec2/cloudflare/worker.js'), 'utf8')
  .replace('export default', 'this.worker =');

function harness(vars = {}) {
  const calls = [];
  class CompatibleRequest extends Request {
    constructor(input, init = {}) { super(input, { ...init, duplex: 'half' }); }
  }
  const context = vm.createContext({ URL, Request: CompatibleRequest, Response, Headers });
  vm.runInContext(source, context);
  const env = { PRIVATE_API: { fetch: async request => {
    calls.push(request);
    return new Response('synthetic', { status: 302, headers: {
      location: 'https://newbiegrader.pages.dev/', 'set-cookie': 'ng_session=synthetic; Secure; HttpOnly',
    } });
  } }, ...vars };
  return { calls, run: (url, init) => context.worker.fetch(new Request(url, init), env) };
}

test('VPC staging defaults to health only and drops identity headers', async () => {
  const h = harness();
  assert.equal((await h.run('https://bridge.invalid/api/submit', { method: 'POST' })).status, 404);
  assert.equal(h.calls.length, 0);
  await h.run('https://bridge.invalid/api/health', { headers: { cookie: 'ng_session=synthetic',
    authorization: 'synthetic', 'x-forwarded-for': '192.0.2.1' } });
  assert.equal(h.calls[0].headers.get('cookie'), null);
  assert.equal(h.calls[0].headers.get('authorization'), null);
  assert.equal(h.calls[0].headers.get('x-forwarded-for'), null);
});

test('API gate requires configuration and server-side key before forwarding', async () => {
  const noKey = harness({ API_ENABLED: '1' });
  assert.equal((await noKey.run('https://bridge.invalid/api/jobs/1')).status, 503);
  const keyed = harness({ API_ENABLED: '1', BACKEND_PROXY_KEY: 'x'.repeat(64) });
  assert.equal((await keyed.run('https://bridge.invalid/api/jobs/1')).status, 403);
  assert.equal(keyed.calls.length, 0);
});

test('authorized bridge preserves API cookies/redirects and strips origin credentials', async () => {
  const key = 'x'.repeat(64);
  const h = harness({ API_ENABLED: '1', BACKEND_PROXY_KEY: key });
  const r = await h.run('https://bridge.invalid/api/auth/me?q=1', { headers: {
    'x-newbiegrader-proxy-key': key, cookie: 'ng_session=synthetic', 'x-forwarded-for': '192.0.2.1',
    'cf-connecting-ip': '198.51.100.1',
  } });
  assert.equal(h.calls[0].url, 'http://localhost/api/auth/me?q=1');
  assert.equal(h.calls[0].redirect, 'manual');
  assert.equal(h.calls[0].headers.get('x-newbiegrader-proxy-key'), null);
  assert.equal(h.calls[0].headers.get('cf-connecting-ip'), null);
  assert.equal(h.calls[0].headers.get('cookie'), 'ng_session=synthetic');
  assert.equal(h.calls[0].headers.get('x-forwarded-for'), '192.0.2.1');
  assert.equal(r.status, 302);
  assert.match(r.headers.get('set-cookie'), /HttpOnly/);
});

test('client paths cannot select a different VPC destination', async () => {
  const key = 'x'.repeat(64);
  const h = harness({ API_ENABLED: '1', BACKEND_PROXY_KEY: key });
  assert.equal((await h.run('https://bridge.invalid/https://other.invalid', {
    headers: { 'x-newbiegrader-proxy-key': key },
  })).status, 404);
  assert.equal(h.calls.length, 0);
});

test('oversize body headers fail before private fetch', async () => {
  const key = 'x'.repeat(64);
  const h = harness({ API_ENABLED: '1', BACKEND_PROXY_KEY: key });
  const r = await h.run('https://bridge.invalid/api/submit', { method: 'POST', body: 'x', headers: {
    'x-newbiegrader-proxy-key': key, 'content-length': String(1024 * 1024 + 1),
  } });
  assert.equal(r.status, 413);
  assert.equal(h.calls.length, 0);
});

test('missing private binding and upstream failure return generic errors', async () => {
  assert.equal((await harness({ PRIVATE_API: null }).run('https://bridge.invalid/api/health')).status, 503);
  const h = harness({ PRIVATE_API: { fetch() { throw new Error('synthetic internal detail'); } } });
  const r = await h.run('https://bridge.invalid/api/health');
  assert.equal(r.status, 502);
  assert.equal(await r.text(), 'origin unavailable');
});
