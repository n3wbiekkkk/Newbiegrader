// Private Pages service-binding bridge to a fixed VPC Service. No public route.
// Default is health-only. Full API access requires the separate cutover gate
// AND a server-side shared key from the Pages Function; never a browser key.
async function sameKey(provided, expected) {
  const encoder = new TextEncoder();
  const hashes = await Promise.all([provided, expected].map(value =>
    crypto.subtle.digest('SHA-256', encoder.encode(value))));
  return crypto.subtle.timingSafeEqual(hashes[0], hashes[1]);
}

function apiError(status, detail, extra = {}) {
  return Response.json({ detail }, { status, headers: { 'cache-control': 'no-store', ...extra } });
}

function canonicalPath(path) {
  try {
    for (let i = 0; i < 4; i++) {
      const decoded = decodeURIComponent(path);
      if (decoded === path) break;
      path = decoded;
    }
    if (/[\x00-\x1f\x7f%\\]/.test(path) || path.split('/').some(p => p === '.' || p === '..')) return null;
    return path.replace(/\/+/g, '/');
  }
  catch { return null; }
}

async function rateGuard(request, env, path) {
  const mode = env.ABUSE_PROTECTION || '0';
  if (mode === '0') return null;
  if (mode !== '1') return apiError(503, 'request protection unavailable');
  // Pages replaces client forwarding headers, then authenticates this private
  // binding. Cookies, URL arguments and a caller-supplied CF header are not keys.
  const ip = request.headers.get('x-forwarded-for') || 'internal-health';
  if (!/^[0-9a-fA-F:.]+$/.test(ip) && ip !== 'internal-health') {
    return apiError(400, 'invalid client address');
  }
  const bindings = ['API_RATE_LIMIT'];
  if (path.startsWith('/api/auth/')) bindings.push('AUTH_RATE_LIMIT');
  if (request.method === 'POST' && ['/api/submit', '/api/run'].includes(path)) {
    bindings.push('EXECUTION_RATE_LIMIT');
  }
  for (const name of bindings) {
    if (typeof env[name]?.limit !== 'function') return apiError(503, 'request protection unavailable');
    try {
      const result = await env[name].limit({ key: ip });
      if (!result.success) return apiError(429, 'too many requests, please wait', { 'retry-after': '60' });
    } catch { return apiError(503, 'request protection unavailable'); }
  }
  return null;
}

async function emailBotGuard(request, env, path) {
  const mode = env.TURNSTILE_ENABLED || '0';
  if (!['0', '1'].includes(mode)) return { response: apiError(503, 'bot verification unavailable') };
  if (mode === '0' || request.method !== 'POST' ||
      !['/api/auth/register', '/api/auth/email/request'].includes(path)) return {};
  if (typeof env.TURNSTILE_SECRET !== 'string' || !env.TURNSTILE_SECRET.trim()) {
    return { response: apiError(503, 'bot verification unavailable') };
  }
  let body;
  try {
    const reader = request.body?.getReader();
    if (!reader) return { response: apiError(400, 'invalid JSON') };
    const chunks = []; let length = 0;
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        length += value.byteLength;
        if (length > 16384) {
          await reader.cancel();
          return { response: apiError(413, 'request body too large') };
        }
        chunks.push(value);
      }
    } finally { reader.releaseLock(); }
    const bytes = new Uint8Array(length); let offset = 0;
    for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
    body = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes));
    if (!body || typeof body !== 'object' || Array.isArray(body)) throw new Error();
  } catch { return { response: apiError(400, 'invalid JSON') }; }
  const token = body['cf-turnstile-response'];
  const refused = () => ({ response: apiError(403, 'bot verification required; please try again',
    { 'x-newbiegrader-bot-check': 'failed' }) });
  if (typeof token !== 'string' || !token.trim() || token.length > 2048) return refused();
  try {
    const form = new URLSearchParams({ secret: env.TURNSTILE_SECRET, response: token });
    const ip = request.headers.get('x-forwarded-for');
    if (ip && /^[0-9a-fA-F:.]+$/.test(ip)) form.set('remoteip', ip);
    const response = await fetch('https://challenges.cloudflare.com/turnstile/v0/siteverify', {
      method: 'POST', headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: form, signal: AbortSignal.timeout(10000),
    });
    if (!response.ok) return { response: apiError(503, 'bot verification unavailable') };
    const result = await response.json();
    if (result?.['error-codes']?.includes('invalid-input-secret')) {
      return { response: apiError(503, 'bot verification unavailable') };
    }
    if (result.success !== true || result.action !== 'email_request' ||
        result.hostname !== 'newbiegrader.pages.dev') return refused();
  } catch { return { response: apiError(503, 'bot verification unavailable') }; }
  delete body['cf-turnstile-response'];
  return { body: JSON.stringify(body) };
}

// Health probes carry no browser identity and precede the application request.
// Never retry that request: an origin may have committed a POST before failing.
async function originReady(binding) {
  if (typeof binding?.fetch !== 'function') return false;
  try {
    const response = await binding.fetch(new Request('http://localhost/api/health', {
      headers: { 'x-forwarded-proto': 'https', 'cache-control': 'no-cache' },
      signal: AbortSignal.timeout(1500), redirect: 'manual',
    }));
    if (response.status !== 200) { await response.body?.cancel(); return false; }
    const reader = response.body?.getReader();
    if (!reader) return false;
    let text = ''; let size = 0;
    const decoder = new TextDecoder();
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        size += value.byteLength;
        if (size > 2048) { await reader.cancel(); return false; }
        text += decoder.decode(value, { stream: true });
      }
      text += decoder.decode();
    } finally { reader.releaseLock(); }
    const value = JSON.parse(text);
    return value?.ok === true && Number.isInteger(value.count) && value.count > 0;
  } catch { return false; }
}

async function selectOrigin(env) {
  // Preserve the single-origin setup until the optional primary is configured.
  if (!env.PRIMARY_API) return env.PRIVATE_API;
  if (await originReady(env.PRIMARY_API)) return env.PRIMARY_API;
  if (await originReady(env.PRIVATE_API)) return env.PRIVATE_API;
  return null;
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const health = url.pathname === '/api/health' && ['GET', 'HEAD'].includes(request.method);
    if (!health) {
      if (env.API_ENABLED !== '1') return new Response('not found', { status: 404 });
      if (typeof env.BACKEND_PROXY_KEY !== 'string' || env.BACKEND_PROXY_KEY.length < 32) {
        return new Response('origin configuration unavailable', { status: 503 });
      }
      if (!await sameKey(request.headers.get('x-newbiegrader-proxy-key') || '', env.BACKEND_PROXY_KEY)) {
        return new Response('forbidden', { status: 403 });
      }
      if (!url.pathname.startsWith('/api/')) return new Response('not found', { status: 404 });
    }
    const path = canonicalPath(url.pathname);
    if (!path) return apiError(400, 'invalid path');
    const limited = await rateGuard(request, env, path);
    if (limited) return limited;
    if (path === '/api/auth/bot-config' && request.method === 'GET') {
      if (!['0', '1'].includes(env.TURNSTILE_ENABLED || '0')) return apiError(503, 'bot verification unavailable');
      const enabled = env.TURNSTILE_ENABLED === '1';
      if (enabled && (!env.TURNSTILE_SITEKEY || !env.TURNSTILE_SECRET)) return apiError(503, 'bot verification unavailable');
      return Response.json({ enabled, sitekey: enabled ? env.TURNSTILE_SITEKEY : '' },
        { headers: { 'cache-control': 'no-store' } });
    }
    if (!env.PRIVATE_API) return new Response('origin unavailable', { status: 503 });
    const headers = new Headers(request.headers);
    for (const name of ['x-newbiegrader-proxy-key', 'x-newbiegrader-staging-key', 'cf-connecting-ip', 'x-real-ip',
      'connection', 'transfer-encoding', 'host']) headers.delete(name);
    if (health) {
      headers.delete('cookie');
      headers.delete('authorization');
      headers.delete('x-forwarded-for');
    }
    headers.set('x-forwarded-proto', 'https');
    const declared = request.headers.get('content-length');
    if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > 1024 * 1024)) {
      return new Response('request body too large or invalid', { status: 413 });
    }
    const verified = await emailBotGuard(request, env, path);
    if (verified.response) return verified.response;
    if (verified.body !== undefined) headers.delete('content-length');
    const origin = await selectOrigin(env);
    if (!origin) return new Response('origin unavailable', { status: 503 });
    try {
      // Binding configuration fixes the host/port. Client URLs cannot choose an
      // arbitrary destination. Nginx also enforces actual streamed body size.
      return await origin.fetch(new Request('http://localhost' + url.pathname + url.search, {
        method: request.method, headers,
        body: ['GET', 'HEAD'].includes(request.method) ? undefined : (verified.body ?? request.body),
        redirect: 'manual',
      }));
    } catch (error) {
      return new Response('origin unavailable', { status: 502 });
    }
  },
};
