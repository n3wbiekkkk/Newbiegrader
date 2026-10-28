const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const { webcrypto, timingSafeEqual } = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '../deploy/host/cloudflare/worker.js'), 'utf8')
  .replace('export default', 'this.worker =');

function harness(vars = {}) {
  const calls = [];
  class CompatibleRequest extends Request {
    constructor(input, init = {}) { super(input, { ...init, duplex: 'half' }); }
  }
  const crypto = { subtle: { digest: webcrypto.subtle.digest.bind(webcrypto.subtle),
    timingSafeEqual: (a, b) => timingSafeEqual(Buffer.from(a), Buffer.from(b)) } };
  const context = vm.createContext({ URL, Request: CompatibleRequest, Response, Headers, TextEncoder, TextDecoder, AbortSignal, crypto });
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
  for (const value of [undefined, 1234, 'short']) {
    const noKey = harness({ API_ENABLED: '1', BACKEND_PROXY_KEY: value });
    assert.equal((await noKey.run('https://bridge.invalid/api/jobs/1')).status, 503);
    assert.equal(noKey.calls.length, 0);
  }
  const keyed = harness({ API_ENABLED: '1', BACKEND_PROXY_KEY: 'x'.repeat(64) });
  assert.equal((await keyed.run('https://bridge.invalid/api/jobs/1')).status, 403);
  assert.equal(keyed.calls.length, 0);
});

test('authorized bridge preserves API cookies/redirects and strips origin credentials', async () => {
  const key = 'x'.repeat(64);
  const h = harness({ API_ENABLED: '1', BACKEND_PROXY_KEY: key });
  const r = await h.run('https://bridge.invalid/api/auth/me?q=1', { headers: {
    'x-newbiegrader-proxy-key': key, cookie: 'ng_session=synthetic', 'x-forwarded-for': '192.0.2.1',
    'cf-connecting-ip': '198.51.100.1', 'x-newbiegrader-staging-key': 'synthetic-private-test-key',
  } });
  assert.equal(h.calls[0].url, 'http://localhost/api/auth/me?q=1');
  assert.equal(h.calls[0].redirect, 'manual');
  assert.equal(h.calls[0].headers.get('x-newbiegrader-proxy-key'), null);
  assert.equal(h.calls[0].headers.get('cf-connecting-ip'), null);
  assert.equal(h.calls[0].headers.get('x-newbiegrader-staging-key'), null);
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

test('healthy primary receives the request after an anonymous bounded probe', async () => {
  const calls = [];
  const primary = { fetch: async request => {
    calls.push(request);
    return request.url.endsWith('/api/health') ? Response.json({ ok: true, count: 100 }) : new Response('primary');
  } };
  const key = 'x'.repeat(64);
  const h = harness({ PRIMARY_API: primary, API_ENABLED: '1', BACKEND_PROXY_KEY: key });
  const response = await h.run('https://bridge.invalid/api/submit', {
    method: 'POST', body: 'one submission', headers: { cookie: 'private-cookie', 'x-newbiegrader-proxy-key': key },
  });
  assert.equal(await response.text(), 'primary');
  assert.equal(calls.length, 2);
  assert.equal(calls[0].headers.get('cookie'), null);
  assert.equal(calls[0].headers.get('x-newbiegrader-proxy-key'), null);
  assert.equal(calls[1].headers.get('cookie'), 'private-cookie');
  assert.equal(await calls[1].text(), 'one submission');
  assert.equal(h.calls.length, 0);
});

test('unhealthy primary selects a healthy backup before forwarding the POST once', async () => {
  for (const health of [() => { throw new Error('offline'); }, () => new Response('', { status: 503 }),
    () => Response.json({ ok: true, count: 0 }), () => new Response('x'.repeat(2049)),
    () => new Response('invalid json')]) {
    const calls = [];
    const key = 'x'.repeat(64);
    const h = harness({ PRIMARY_API: { fetch: health }, API_ENABLED: '1', BACKEND_PROXY_KEY: key,
      PRIVATE_API: { fetch: async request => {
        calls.push(request);
        return request.url.endsWith('/api/health') ? Response.json({ ok: true, count: 100 }) : new Response('backup');
      } } });
    const response = await h.run('https://bridge.invalid/api/submit', {
      method: 'POST', body: 'one submission', headers: { 'x-newbiegrader-proxy-key': key },
    });
    assert.equal(await response.text(), 'backup');
    assert.equal(calls.filter(r => r.method === 'POST').length, 1);
  }
});

test('a failed forwarded POST is never replayed at backup and probes recover on the next request', async () => {
  const calls = [];
  let healthy = true;
  const key = 'x'.repeat(64);
  const h = harness({ API_ENABLED: '1', BACKEND_PROXY_KEY: key, PRIMARY_API: { fetch: async request => {
    calls.push(request);
    if (request.url.endsWith('/api/health')) return Response.json({ ok: healthy, count: 100 });
    throw new Error('ambiguous committed POST');
  } }, PRIVATE_API: { fetch: async request => {
    calls.push(request);
    return request.url.endsWith('/api/health') ? Response.json({ ok: true, count: 100 }) : new Response('backup');
  } } });
  const init = () => ({ method: 'POST', body: 'one submission', headers: { 'x-newbiegrader-proxy-key': key } });
  assert.equal((await h.run('https://bridge.invalid/api/submit', init())).status, 502);
  assert.equal(calls.filter(r => r.method === 'POST').length, 1);
  healthy = false;
  assert.equal(await (await h.run('https://bridge.invalid/api/submit', init())).text(), 'backup');
  assert.equal(calls.filter(r => r.method === 'POST').length, 2);
  healthy = true;
  assert.equal((await h.run('https://bridge.invalid/api/submit', init())).status, 502);
  assert.equal(calls.filter(r => r.method === 'POST').length, 3);
});

test('both unavailable origins return 503 without forwarding application requests', async () => {
  const calls = [];
  const unavailable = { fetch: async request => { calls.push(request); return new Response('', { status: 503 }); } };
  const key = 'x'.repeat(64);
  const h = harness({ API_ENABLED: '1', BACKEND_PROXY_KEY: key, PRIMARY_API: unavailable, PRIVATE_API: unavailable });
  assert.equal((await h.run('https://bridge.invalid/api/submit', {
    method: 'POST', body: 'one submission', headers: { 'x-newbiegrader-proxy-key': key },
  })).status, 503);
  assert.equal(calls.filter(r => r.method === 'POST').length, 0);
});
