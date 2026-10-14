/* Runtime config for split deployment.
 * Leave as "" (same origin). The static host proxies /api/* to the
 * backend (vercel.json for Vercel, _redirects for Cloudflare Pages),
 * so the browser never talks cross-origin — this keeps login working
 * even when third-party cookies are blocked.
 * Only set a backend URL if you serve the frontend from a host WITHOUT
 * the /api proxy (then also set GRADER_CORS_ORIGINS on the backend).
 */
window.GRADER_API_BASE = "";
