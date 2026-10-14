// Cloudflare Pages Function: same-origin /api proxy to the judge backend.
// File placement matters: functions/api/[[proxy]].js handles /api/*.
// Why proxy: keeps login cookies first-party, so auth works even when
// browsers block third-party cookies. Query strings are forwarded as-is.
// Redirects pass through untouched (Google login + finish flow need them).
const BACKEND = "https://newbiegrader-api.onrender.com";

export async function onRequest(context) {
  const url = new URL(context.request.url);
  const target = BACKEND + url.pathname + url.search;
  const init = {
    method: context.request.method,
    headers: context.request.headers,
    redirect: "manual",
  };
  if (context.request.method !== "GET" && context.request.method !== "HEAD") {
    init.body = context.request.body;
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
  return new Response(res.body, { status: res.status, headers });
}
