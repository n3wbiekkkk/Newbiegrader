// Private Pages service-binding bridge to a fixed VPC Service. No public route.
// Default is health-only. Full API access requires the separate cutover gate
// AND a server-side shared key from the Pages Function; never a browser key.
async function sameKey(provided, expected) {
  const encoder = new TextEncoder();
  const hashes = await Promise.all([provided, expected].map(value =>
    crypto.subtle.digest('SHA-256', encoder.encode(value))));
  return crypto.subtle.timingSafeEqual(hashes[0], hashes[1]);
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
    try {
      // Binding configuration fixes the host/port. Client URLs cannot choose an
      // arbitrary destination. Nginx also enforces actual streamed body size.
      return await env.PRIVATE_API.fetch(new Request('http://localhost' + url.pathname + url.search, {
        method: request.method, headers,
        body: ['GET', 'HEAD'].includes(request.method) ? undefined : request.body,
        redirect: 'manual',
      }));
    } catch (error) {
      return new Response('origin unavailable', { status: 502 });
    }
  },
};
