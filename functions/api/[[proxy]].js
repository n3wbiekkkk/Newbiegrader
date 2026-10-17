// Cloudflare Pages Function: same-origin /api proxy to the judge backend.
// File placement matters: functions/api/[[proxy]].js handles /api/*.
// Why proxy: keeps login cookies first-party, so auth works even when
// browsers block third-party cookies. Query strings are forwarded as-is.
// Redirects pass through untouched (Google login + finish flow need them).
const BACKEND = "https://grader.n.onjrnm.vip";

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
  const target = BACKEND + url.pathname + url.search;
  // Never forward hop-by-hop headers: content-length/connection from the
  // eyeball connection do not describe the backend connection (stale
  // content-length breaks POST submit on Workers).
  const HOP_BY_HOP = new Set(["connection", "keep-alive", "proxy-authenticate",
    "proxy-authorization", "te", "trailer", "transfer-encoding", "upgrade",
    "content-length", "host"]);
  const fwdHeaders = new Headers();
  context.request.headers.forEach((v, k) => {
    if (!HOP_BY_HOP.has(k.toLowerCase())) fwdHeaders.append(k, v);
  });
  const init = { method: context.request.method, headers: fwdHeaders, redirect: "manual" };
  if (context.request.method !== "GET" && context.request.method !== "HEAD") {
    init.body = context.request.body;
    init.duplex = "half";   // required by Workers when forwarding a stream body
  }

  // Edge cache lookup. Best effort: if the runtime exposes no Cache API we
  // simply fall back to the direct proxy, never failing the request over it.
  let edgeCache = null;
  let cacheKey = null;
  if (isAnonymousGet(context.request, url.pathname)) {
    try {
      edgeCache = caches.default;
      cacheKey = new Request(url.toString(), { method: "GET" });
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

  const res = await fetch(target, init);
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
