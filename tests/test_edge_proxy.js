const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const { webcrypto, timingSafeEqual } = require('node:crypto');
const code = fs.readFileSync(path.join(__dirname, '../functions/api/[[proxy]].js'), 'utf8')
  .replace('export async function onRequest', 'async function onRequest') + '\nthis.onRequest = onRequest;';

function harness(options = {}) {
  const calls = [];
  const crypto = { subtle: { digest: webcrypto.subtle.digest.bind(webcrypto.subtle),
    timingSafeEqual: (a, b) => timingSafeEqual(Buffer.from(a), Buffer.from(b)) } };
  const context = vm.createContext({ URL, Request, Response, Headers, Uint8Array, TextEncoder, crypto,
    caches: options.cache ? { default: options.cache } : undefined,
    fetch: async (url, init) => { calls.push({ url, init }); return options.response ? options.response() : new Response('ok'); } });
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

test('service transport uses only the bound Worker with sanitized headers', async () => {
  const h = harness();
  const bound = [];
  const result = await h.run(new Request('https://frontend.invalid/api/health?q=1', {
    headers: { 'cf-connecting-ip': '192.0.2.7', 'x-forwarded-for': '198.51.100.1' },
  }), { BACKEND_TRANSPORT: 'service', BACKEND_SERVICE: { fetch: async (url, init) => {
    bound.push({ url, init }); return new Response('bound');
  } } });
  assert.equal(await result.text(), 'bound');
  assert.equal(h.calls.length, 0);
  assert.equal(bound[0].url, 'https://newbiegrader-backend.internal/api/health?q=1');
  assert.equal(bound[0].init.headers.get('x-forwarded-for'), '192.0.2.7');
  assert.equal(bound[0].init.redirect, 'manual');
});

test('missing service binding or invalid transport fails closed without legacy fallback', async () => {
  for (const env of [{ BACKEND_TRANSPORT: 'service' }, { BACKEND_TRANSPORT: 'invalid' }]) {
    const h = harness();
    assert.equal((await h.run(new Request('https://frontend.invalid/api/health'), env)).status, 503);
    assert.equal(h.calls.length, 0);
  }
});

test('a binding alone does not switch the existing production transport', async () => {
  const h = harness();
  await h.run(new Request('https://frontend.invalid/api/health'), {
    BACKEND_SERVICE: { fetch() { throw new Error('must explicitly opt in'); } },
  });
  assert.equal(h.calls[0].url, 'https://grader.n.onjrnm.vip/api/health');
});

test('a failed service returns generic 502 and never retries the old judge', async () => {
  const h = harness();
  const result = await h.run(new Request('https://frontend.invalid/api/health'), {
    BACKEND_TRANSPORT: 'service', BACKEND_SERVICE: { fetch() { throw new Error('synthetic internal detail'); } },
  });
  assert.equal(result.status, 502);
  assert.equal(await result.text(), 'backend unavailable');
  assert.equal(h.calls.length, 0);
});

test('staging API requires its separate access key before any origin or cache access', async () => {
  const key = 's'.repeat(64);
  for (const provided of ['', 'wrong', 's'.repeat(63), 's'.repeat(63) + 'x']) {
    const h = harness();
    const r = await h.run(new Request('https://staging.invalid/api/auth/me', {
      headers: { 'x-newbiegrader-staging-key': provided },
    }), { BACKEND_STAGING_ONLY: '1', STAGING_ACCESS_KEY: key });
    assert.equal(r.status, 403);
    assert.equal(r.headers.get('cache-control'), 'no-store');
    assert.equal(h.calls.length, 0);
  }
});

test('staging gate fails closed when its flag or secret is misconfigured', async () => {
  for (const env of [{ BACKEND_STAGING_ONLY: 'invalid' },
    { BACKEND_STAGING_ONLY: '1' }, { BACKEND_STAGING_ONLY: '1', STAGING_ACCESS_KEY: 'short' }]) {
    const h = harness();
    assert.equal((await h.run(new Request('https://staging.invalid/api/health'), env)).status, 503);
    assert.equal(h.calls.length, 0);
  }
});

test('authorized staging requests strip the test key and preserve the independent origin key', async () => {
  const h = harness();
  await h.run(new Request('https://staging.invalid/api/auth/me', {
    headers: { 'x-newbiegrader-staging-key': 's'.repeat(64) },
  }), { BACKEND_STAGING_ONLY: '1', STAGING_ACCESS_KEY: 's'.repeat(64),
    BACKEND_PROXY_KEY: 'p'.repeat(64) });
  assert.equal(h.calls[0].init.headers.get('x-newbiegrader-staging-key'), null);
  assert.equal(h.calls[0].init.headers.get('x-newbiegrader-proxy-key'), 'p'.repeat(64));
});

test('staging exposes only GET and HEAD health without the test key', async () => {
  const h = harness();
  const env = { BACKEND_STAGING_ONLY: '1', STAGING_ACCESS_KEY: 's'.repeat(64) };
  for (const method of ['GET', 'HEAD']) {
    await h.run(new Request('https://staging.invalid/api/health', { method }), env);
  }
  assert.equal(h.calls.length, 2);
  assert.equal((await h.run(new Request('https://staging.invalid/api/health', { method: 'POST' }), env)).status, 403);
  assert.equal(h.calls.length, 2);
});


test('edge never looks up authenticated requests or contest listings', async () => {
  for (const [path, headers] of [
    ['/api/problems', {authorization: 'Bearer synthetic'}],
    ['/api/problems', {cookie: 'ng_session=synthetic'}],
    ['/api/problems', {cookie: 'another_auth=synthetic'}],
    ['/api/contests', {}],
  ]) {
    let lookups = 0, writes = 0;
    const h = harness({cache: {match() { lookups++; }, put() { writes++; }}});
    await h.run(new Request('https://frontend.invalid' + path, {headers}));
    assert.equal(lookups, 0); assert.equal(writes, 0); assert.equal(h.calls.length, 1);
  }
});

test('edge respects origin privacy, Vary and Set-Cookie directives', async () => {
  for (const headers of [ {'cache-control': 'private, max-age=20'},
    {'cache-control': 'no-store'}, {'cache-control': 'public, no-cache'},
    {'vary': 'Cookie'}, {'vary': 'Authorization'}, {'vary': '*'},
    {'set-cookie': 'ng_session=synthetic; HttpOnly'} ]) {
    let writes = 0;
    const h = harness({cache: {match() {}, put() { writes++; }},
      response: () => new Response('private synthetic', {headers})});
    const r = await h.run(new Request('https://frontend.invalid/api/problems'));
    assert.equal(writes, 0, JSON.stringify(headers));
    assert.notEqual(r.headers.get('x-ng-cache'), 'MISS');
  }
});

test('shareable edge keys retain query and origin and use new policy namespace', async () => {
  const stored = [];
  const h = harness({cache: {match() {}, async put(key, value) {stored.push({key, value});}},
    response: () => new Response('public', {headers: {'cache-control': 'public, max-age=10'}})});
  await h.run(new Request('https://frontend.invalid/api/languages?q=one'));
  await h.run(new Request('https://frontend.invalid/api/languages?q=two'));
  assert.equal(stored.length, 2);
  const urls = stored.map(s => new URL(s.key.url));
  assert.equal(urls[0].searchParams.get('q'), 'one');
  assert.equal(urls[1].searchParams.get('q'), 'two');
  assert.equal(urls[0].searchParams.get('__ng_policy'), '2');
  assert.equal(urls[0].searchParams.get('__ng_origin'), 'https://grader.n.onjrnm.vip');
});
