const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');
const { webcrypto, timingSafeEqual } = require('node:crypto');
const source = fs.readFileSync(path.join(__dirname, '../deploy/host/cloudflare/worker.js'), 'utf8')
  .replace('export default', 'this.worker =');
const key = 'synthetic-bridge-key-'.repeat(4);

function harness(options = {}) {
  const origins = [], verifications = [], limits = [];
  class StreamRequest extends Request {
    constructor(input, init = {}) { super(input, { ...init, duplex: 'half' }); }
  }
  const crypto = { subtle: { digest: webcrypto.subtle.digest.bind(webcrypto.subtle),
    timingSafeEqual: (a, b) => timingSafeEqual(Buffer.from(a), Buffer.from(b)) } };
  const env = { API_ENABLED: '1', BACKEND_PROXY_KEY: key, ABUSE_PROTECTION: '1',
    TURNSTILE_ENABLED: '1', TURNSTILE_SECRET: 'synthetic-turnstile-secret', TURNSTILE_SITEKEY: 'public-test-sitekey',
    PRIVATE_API: { fetch: async request => {
      origins.push({ url: request.url, body: request.body ? await request.text() : null,
        headers: Object.fromEntries(request.headers) });
      return Response.json({ forwarded: true });
    } } };
  for (const name of ['API_RATE_LIMIT', 'AUTH_RATE_LIMIT', 'EXECUTION_RATE_LIMIT']) {
    env[name] = { limit: async ({ key }) => {
      limits.push({ name, key });
      if (options.limitThrows) throw new Error('synthetic limiter outage');
      return { success: name !== options.denied };
    } };
  }
  Object.assign(env, options.env);
  const context = vm.createContext({ URL, Request: StreamRequest, Response, Headers,
    TextEncoder, TextDecoder, Uint8Array, URLSearchParams, AbortSignal, crypto,
    fetch: async (url, init) => {
      verifications.push({ url, init, body: Object.fromEntries(init.body) });
      if (options.verifyThrows) throw new Error('synthetic provider outage');
      return options.verify ? options.verify() : Response.json({ success: true,
        action: 'email_request', hostname: 'newbiegrader.pages.dev' });
    } });
  vm.runInContext(source, context);
  return { env, origins, verifications, limits, run: (pathname, body, headers = {}) =>
    context.worker.fetch(new Request('https://bridge.invalid' + pathname, {
      method: body === undefined ? 'GET' : 'POST',
      headers: { 'x-newbiegrader-proxy-key': key, 'x-forwarded-for': '192.0.2.25',
        'Content-Type': 'application/json', ...headers },
      body: body === undefined ? undefined : typeof body === 'string' ? body : JSON.stringify(body),
    }), env) };
}

test('edge quotas use trusted client address across cookies and canonical paths', async () => {
  const h = harness({ env: { TURNSTILE_ENABLED: '0' } });
  await h.run('/api/%2561uth/email/request', { email: 'synthetic@example.invalid' }, { cookie: 'forged=1' });
  assert.deepEqual(h.limits.map(x => x.name), ['API_RATE_LIMIT', 'AUTH_RATE_LIMIT']);
  assert.ok(h.limits.every(x => x.key === '192.0.2.25'));
  await h.run('/api//submit', {});
  assert.equal(h.limits.at(-1).name, 'EXECUTION_RATE_LIMIT');
});

test('rate rejection and missing or failing limiters never contact origin', async () => {
  for (const options of [{ denied: 'AUTH_RATE_LIMIT' }, { limitThrows: true },
    { env: { API_RATE_LIMIT: null } }, { env: { ABUSE_PROTECTION: 'invalid' } }]) {
    const h = harness(options);
    const r = await h.run('/api/auth/email/request', {});
    assert.equal(r.status, options.denied ? 429 : 503);
    if (r.status === 429) assert.equal(r.headers.get('retry-after'), '60');
    assert.equal(h.origins.length, 0);
    assert.equal(h.verifications.length, 0);
  }
});

test('bot config exposes only public sitekey and never caches identity or secrets', async () => {
  const h = harness(); const r = await h.run('/api/auth/bot-config');
  assert.deepEqual(await r.json(), { enabled: true, sitekey: 'public-test-sitekey' });
  assert.equal(r.headers.get('cache-control'), 'no-store');
  assert.equal(h.origins.length, 0);
  h.env.TURNSTILE_SECRET = '';
  assert.equal((await h.run('/api/auth/bot-config')).status, 503);
});

test('missing malformed and oversize tokens fail before verification or original handler', async () => {
  for (const token of [undefined, null, 5, '', ' ', 'x'.repeat(2049)]) {
    const h = harness();
    const r = await h.run('/api/auth/email/request', { email: 'synthetic@example.invalid', 'cf-turnstile-response': token });
    assert.equal(r.status, 403); assert.equal(h.origins.length, 0); assert.equal(h.verifications.length, 0);
  }
});

test('token success additionally requires exact production hostname and action', async () => {
  for (const reply of [{ success: false }, { success: true, action: 'other', hostname: 'newbiegrader.pages.dev' },
    { success: true, action: 'email_request', hostname: 'localhost' },
    { success: true, action: 'email_request', hostname: 'newbiegrader.pages.dev.attacker.invalid' }]) {
    const h = harness({ verify: () => Response.json(reply) });
    assert.equal((await h.run('/api/auth/email/request', { 'cf-turnstile-response': 'synthetic' })).status, 403);
    assert.equal(h.origins.length, 0);
  }
});

test('canonical verification preserves original fields but removes redeemed token', async () => {
  const h = harness();
  const r = await h.run('/api/auth/email/request', { email: 'student@example.invalid', 'cf-turnstile-response': 'synthetic' });
  assert.equal(r.status, 200);
  assert.equal(h.verifications[0].url, 'https://challenges.cloudflare.com/turnstile/v0/siteverify');
  assert.deepEqual(h.verifications[0].body, { secret: 'synthetic-turnstile-secret', response: 'synthetic', remoteip: '192.0.2.25' });
  assert.deepEqual(JSON.parse(h.origins[0].body), { email: 'student@example.invalid' });
  assert.equal(h.origins[0].headers['x-newbiegrader-proxy-key'], undefined);
  assert.equal(h.origins[0].headers['turnstile_secret'], undefined);
});

test('provider errors, invalid secret, non-JSON and timeout fail closed without replay', async () => {
  for (const options of [{ verifyThrows: true }, { verify: () => new Response('bad gateway', { status: 502 }) },
    { verify: () => new Response('not JSON') },
    { verify: () => Response.json({ success: false, 'error-codes': ['invalid-input-secret'] }) }]) {
    const h = harness(options);
    assert.equal((await h.run('/api/auth/register', { 'cf-turnstile-response': 'synthetic' })).status, 503);
    assert.equal(h.verifications.length, 1); assert.equal(h.origins.length, 0);
  }
});

test('replayed token is rejected by siteverify and never reaches original handler twice', async () => {
  let used = false;
  const h = harness({ verify: () => {
    const reply = used ? { success: false, 'error-codes': ['timeout-or-duplicate'] } :
      { success: true, action: 'email_request', hostname: 'newbiegrader.pages.dev' };
    used = true; return Response.json(reply);
  } });
  const payload = { 'cf-turnstile-response': 'synthetic' };
  assert.equal((await h.run('/api/auth/register', payload)).status, 200);
  assert.equal((await h.run('/api/auth/register', payload)).status, 403);
  assert.equal(h.origins.length, 1);
});

test('email payload bound and invalid JSON fail without contacting provider', async () => {
  for (const [body, status] of [['[1]', 400], ['not JSON', 400], ['x'.repeat(16385), 413]]) {
    const h = harness();
    assert.equal((await h.run('/api/auth/register', body)).status, status);
    assert.equal(h.verifications.length, 0); assert.equal(h.origins.length, 0);
  }
});

test('password login, verification and job polling retain their existing handlers', async () => {
  const h = harness();
  await h.run('/api/auth/password', { password: 'synthetic-only' });
  await h.run('/api/auth/email/verify', { code: 'synthetic-only' });
  await h.run('/api/jobs/synthetic');
  assert.equal(h.origins.length, 3); assert.equal(h.verifications.length, 0);
});
