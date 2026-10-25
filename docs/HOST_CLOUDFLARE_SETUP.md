# Private Cloudflare transport

Requests follow Pages Function → private Worker service binding → one VPC
Service → named tunnel → loopback Nginx (8081) → FastAPI (8000). No public origin
HTTP listener is required. Production uses `newbiegrader-pc-production` and the
dedicated `newbiegrader-home-api` tunnel on the homeserver. The existing Worker
and VPC service labels retain their PC names for binding compatibility. A separate gated staging Pages project is used for
qualification; it is not a production dependency.

As of 2026-10-25, the VPC service selects only the homeserver's own tunnel ID.
The PC's original tunnel is no longer the API destination: powering the PC back
on can restore its four database workers without routing public requests to its
older API release. The homeserver keeps two workers, for an approved six-worker
target; the actual six-worker fleet still requires live verification. No origin
listener was opened beyond loopback and the retired AWS route was untouched.

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

## API abuse protection

Production enables `ABUSE_PROTECTION=1` on the private bridge. Three Cloudflare
rate-limit bindings reject excess requests before they reach the PC:

| Binding | Requests per 60 seconds, per client IP |
| --- | ---: |
| `API_RATE_LIMIT` | 6,000 across API routes |
| `AUTH_RATE_LIMIT` | 600 across `/api/auth/` routes |
| `EXECUTION_RATE_LIMIT` | 600 across submit/run POSTs |

These deliberately generous network ceilings accommodate shared classroom IPs.
The database's stricter account quotas, one-active-job rule and 25-job queue cap
remain authoritative. Rate counts are approximate and local to a Cloudflare
location; they are not a worldwide admission budget or a guaranteed DDoS limit.
Use dedicated, stable rate-limit namespace IDs for this project. Missing bindings
or limiter failures fail closed with 503; exceeded limits return 429/Retry-After.
The bridge checks its shared key before accepting the IP supplied by Pages;
cookies and client-supplied forwarding headers cannot select a quota identity.

## Email-request bot verification

The existing private bridge also validates Turnstile before forwarding POSTs to
`/api/auth/email/request` and its `/api/auth/register` alias. It checks Siteverify
success, action `email_request`, and exact hostname `newbiegrader.pages.dev`.
Keep `TURNSTILE_SECRET` as a Worker secret. `TURNSTILE_SITEKEY` is public;
`TURNSTILE_ENABLED=1` requires both values. Never enable the gate before deploying
the frontend widget and verifying the destination configuration. Preserve existing
secret bindings when updating Worker code; secret values must not enter source,
command arguments or deployment output.

`GET /api/auth/bot-config` returns only the public sitekey and enabled flag with
`Cache-Control: no-store`. The widget loads when email signup/recovery needs it,
and resets after every request attempt. Expired, replayed, wrong-action and
wrong-host tokens are refused. Provider/network errors fail closed. Existing
password login, OTP verification, Google sign-in and judging handlers keep their
own authentication and authorization checks. No email is sent by the widget.

The Pages CSP allows the specific `https://challenges.cloudflare.com` script and
frame origin. It still denies inline scripts, plugins, injected base URLs and
cross-origin framing. Existing tabs with older auth JavaScript may need a reload
when the gate is first enabled.

See [rate-limit behavior](https://developers.cloudflare.com/workers/runtime-apis/bindings/rate-limit/)
and [mandatory Siteverify checks](https://developers.cloudflare.com/turnstile/get-started/server-side-validation/).
