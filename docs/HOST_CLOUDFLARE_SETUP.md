# Private Cloudflare transport

Requests follow Pages Function → private Worker service binding → one VPC
Service → named tunnel → loopback Nginx (8081) → FastAPI (8000). No public origin
HTTP listener is required. Production uses `newbiegrader-pc-production` and the
`newbiegrader-pc` tunnel. A separate gated staging Pages project is used for
qualification; it is not a production dependency.

The bridge fixes its VPC destination and requires a server-side shared key for
all API paths except anonymous health. Pages strips incoming proxy/staging keys,
forwards the trusted client IP, and supplies its configured bridge key. Browser
code never receives either secret. Redirects and multiple Set-Cookie headers
survive both proxies. Private, authenticated and identity-varying responses are
not shared through the edge cache.

Use a separate project tunnel service; do not replace the PC's unrelated
`cloudflared.service`. The project unit uses `/usr/local/bin/cloudflared`, QUIC
and metrics at `127.0.0.1:20242`; the existing service retains port 20241. Workers
VPC requires QUIC (`quic` or `auto`) and outbound UDP 7844. Verify actual QUIC
connections rather than silently accepting an HTTP/2 fallback. See the
[Cloudflare tunnel requirements](https://developers.cloudflare.com/workers-vpc/configuration/tunnel/).

Store the tunnel token at `/etc/newbiegrader/tunnel-token`, root:root 0600. The
unit uses systemd `LoadCredential` and `--token-file`, so the token does not enter
argv or the process environment. Keep Worker routes and preview URLs disabled;
Pages calls it only through the service binding. Enable logs/traces without
logging cookies, authorization, shared keys or OAuth query strings.

For staging, set `BACKEND_STAGING_ONLY=1` and a separate `STAGING_ACCESS_KEY` on
the staging Pages project. Keep API admission off and all worker gates absent.
The smoke CLI verifies missing/wrong staging keys and production credential
separation. `--production` probes the canonical production URL without reading
or sending staging credentials.
