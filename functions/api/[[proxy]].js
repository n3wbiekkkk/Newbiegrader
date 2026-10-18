// Cloudflare Pages Function: same-origin /api proxy to the judge backend.
// File placement matters: functions/api/[[proxy]].js handles /api/*.
// Why proxy: keeps login cookies first-party, so auth works even when
// browsers block third-party cookies. Query strings are forwarded as-is.
// Redirects pass through untouched (Google login + finish flow need them).
const DEFAULT_BACKEND = "https://grader.n.onjrnm.vip";
const BODY_MAX = 1024 * 1024;

function backendOrigin(env) {
  const url = new URL(env?.BACKEND_ORIGIN || DEFAULT_BACKEND);
  if (url.protocol !== "https:" || url.username || url.password ||
      url.pathname !== "/" || url.search || url.hash) throw new Error("invalid origin");
  return url.origin;
}

async function boundedBody(request) {
  const declared = request.headers.get("content-length");
  if (declared !== null && (!/^\d+$/.test(declared) || Number(declared) > BODY_MAX)) {
    return { error: new Response("request body too large or invalid", { status: 413 }) };
  }
  if (!request.body) return { body: null };
  const reader = request.body.getReader();
  const chunks = [];
  let length = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      length += value.byteLength;
      if (length > BODY_MAX) {
        await reader.cancel();
        return { error: new Response("request body too large", { status: 413 }) };
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const body = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { body.set(chunk, offset); offset += chunk.byteLength; }
  return { body };
}

// Zero-account GETs whose body is identical for every visitor. The backend
// origin sits ~200ms away, so every proxied request pays a full round trip;
// caching these at the edge makes repeat page loads ~10x faster. Anything that
// carries a session (or is not a GET) always goes straight through: a logged-in
// admin sees hidden problems, and only the anonymous body is shareable.
const EDGE_CACHE_PATHS = new Set([
  "/api/problems", "/api/health", "/api/languages", "/api/version", "/api/stats",
]);
const EDGE_CACHE_TTL = 30;   // seconds; matches the server's own 20-30s caches
const AUTH_COOKIES = /(?:^|;\s*)(?:ng_session|ng_remember)=/;

function isAnonymousGet(request, pathname) {
  if (request.method !== "GET" || !EDGE_CACHE_PATHS.has(pathname)) return false;
  return !AUTH_COOKIES.test(request.headers.get("cookie") || "");
}

export async function onRequest(context) {
  const url = new URL(context.request.url);
  let backend;
  let service = null;
  try {
    const transport = context.env?.BACKEND_TRANSPORT || "https";
    if (transport === "service") {
      service = context.env?.BACKEND_SERVICE;
      if (typeof service?.fetch !== "function") throw new Error("missing service binding");
      // A service binding fixes the destination; this hostname is not resolved.
      backend = "https://newbiegrader-aws.internal";
    } else if (transport === "https") {
      backend = backendOrigin(context.env);
    } else {
      throw new Error("invalid transport");
    }
  }
  catch (e) { return new Response("backend configuration unavailable", { status: 503 }); }
  const target = backend + url.pathname + url.search;
  // Never forward hop-by-hop headers: content-length/connection from the
  // eyeball connection do not describe the backend connection (stale
  // content-length breaks POST submit on Workers).
  const HOP_BY_HOP = new Set(["connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
    "content-length", "host", "x-newbiegrader-proxy-key", "x-forwarded-for",
    "x-forwarded-proto", "x-real-ip", "cf-connecting-ip"]);
  const fwdHeaders = new Headers();
  context.request.headers.forEach((v, k) => {
    if (!HOP_BY_HOP.has(k.toLowerCase())) fwdHeaders.append(k, v);
  });
  // Cloudflare supplies this single client address; never forward a client XFF
  // chain. The backend still validates it against its immediate-peer policy.
  const clientIp = context.request.headers.get("cf-connecting-ip") || "";
  if (/^[0-9a-fA-F:.]+$/.test(clientIp)) fwdHeaders.set("x-forwarded-for", clientIp);
  fwdHeaders.set("x-forwarded-proto", "https");
  if (context.env?.BACKEND_PROXY_KEY) {
    fwdHeaders.set("x-newbiegrader-proxy-key", context.env.BACKEND_PROXY_KEY);
  }
  const init = { method: context.request.method, headers: fwdHeaders, redirect: "manual" };
  if (context.request.method !== "GET" && context.request.method !== "HEAD") {
    const bounded = await boundedBody(context.request);
    if (bounded.error) return bounded.error;
    init.body = bounded.body;
  }

  // Edge cache lookup. Best effort: if the runtime exposes no Cache API we
  // simply fall back to the direct proxy, never failing the request over it.
  let edgeCache = null;
  let cacheKey = null;
  if (isAnonymousGet(context.request, url.pathname)) {
    try {
      edgeCache = caches.default;
      const cacheUrl = new URL(url);
      cacheUrl.searchParams.set("__ng_origin", backend);
      cacheKey = new Request(cacheUrl.toString(), { method: "GET" });
      const hit = await edgeCache.match(cacheKey);
      if (hit) {
        const headers = new Headers(hit.headers);
        headers.set("x-ng-cache", "HIT");
        return new Response(hit.body, { status: hit.status, headers });
      }
    } catch (e) {
      edgeCache = null;
    }
  }

  let res;
  try { res = service ? await service.fetch(target, init) : await fetch(target, init); }
  catch (e) { return new Response("backend unavailable", { status: 502 }); }
  // Rebuild headers explicitly so multiple Set-Cookie headers survive.
  const headers = new Headers();
  res.headers.forEach((v, k) => {
    if (k.toLowerCase() !== "set-cookie") headers.append(k, v);
  });
  const getSetCookie = res.headers.getSetCookie
    ? res.headers.getSetCookie()
    : [];
  getSetCookie.forEach((c) => headers.append("set-cookie", c));

  // Only store a clean, cookieless 200 for the next anonymous visitor.
  if (edgeCache && res.status === 200 && getSetCookie.length === 0) {
    headers.set("cache-control",
      `public, max-age=${EDGE_CACHE_TTL}, s-maxage=${EDGE_CACHE_TTL}`);
    headers.set("x-ng-cache", "MISS");
    const stored = new Response(await res.arrayBuffer(), { status: 200, headers });
    context.waitUntil(edgeCache.put(cacheKey, stored.clone()).catch(() => {}));
    return stored;
  }
  return new Response(res.body, { status: res.status, headers });
}
