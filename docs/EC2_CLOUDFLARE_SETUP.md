# Cloudflare connection — AWS production and isolated staging

## Latest production publication — 2026-10-19

Pages deployment `f826f65a-5f93-49f0-9ca5-4f2d286a2c85` serves app.js v52 and
the cache-privacy proxy. Existing production/preview configuration, service
bindings, keys, private AWS route and compatibility date were preserved. Actual
post-publication smoke passed 15/15 and asset/privacy checks 7/7. No Vercel or
JustRunMy route is used. See [deployment and rollback evidence](releases/PRODUCTION_CORRECTNESS_RELEASE_2026-10-19.md).
Earlier deployment IDs below belong to their historical checkpoints.

## Current production checkpoint (2026-10-19)

The operator approved cutover and explicitly stopping JustRunMy. Production
`https://newbiegrader.pages.dev` now follows:

```text
Pages /api Function (BACKEND_TRANSPORT=service)
  → BACKEND_SERVICE: private newbiegrader-aws-production Worker
  → PRIVATE_API: specific VPC Service
  → named outbound tunnel → 127.0.0.1:8081 Nginx → 127.0.0.1:8000 API
```

The production Worker has its **own** server-only key, public/preview URLs
disabled and `API_ENABLED=1`. The matching Pages secret is never frontend code.
Existing project/account, frontend URL, session secret and canonical Google
callback were preserved. No public EC2 FastAPI port, purchased domain, Elastic
IP, load balancer or paid plan was added. Both Pages fail-open flags are false;
Cloudflare rejected the initial attempt to set them unequally.

The existing VPC Service ID remains `01a15026-522c-77e3-b439-a71579b4be67`; its
HTTP port changed from 8082 to **8081**. The separate staging project/Worker and
its missing/wrong-key gate remain in place; **17/17** staging checks passed
against the new loopback destination. Never expose the staging key to browsers.

```sh
python3 deploy/ec2/smoke_https.py --production --expected-samesite none
```

Actual production run: **15/15** anonymous HTTPS checks passed, repeated after
an actual EC2 reboot. Production mode does not open the staging access file or
send that credential. Separate native-Chrome checks verified fresh Google OAuth
login, Python/C/C++ synthetic playground runs, asynchronous synthetic CE
submission/poll/history and a post-reboot authenticated run. No existing user's
source was executed. See `EC2_MIGRATION.md` for exact scope and failed attempts.

Production deployment at verification:
`dded0f35-2665-4211-a016-d4825916f0ed`; subsequent reviewed Git deployments may
replace it. The root-owned EC2 release and source fingerprint remain unchanged.
JustRunMy is stopped, not deleted. For rollback, fence AWS admission/consumer
and preserve durable jobs/UID reservations first; restore saved project config
as well as the selected Pages deployment. Neither auto-fallback nor two
simultaneous judge consumers is allowed.

The new production key/config and before/after Cloudflare metadata have a
verified encrypted local recovery archive. No secret value is included here.
VPC free-during-beta and trial-credit limitations remain; see cost notes below.
Historical approval and old-origin statements in the checkpoints below describe
their original observation time, not the current production route.

## Earlier checkpoint — gated API rehearsal (2026-10-19)

The separate staging Pages project now uses `BACKEND_STAGING_ONLY=1`. Non-health
API requests need `x-newbiegrader-staging-key`; missing/wrong keys return 403
**before cache/origin access**. Missing/short key or invalid mode returns 503.
The key is a Cloudflare Pages secret, never frontend configuration. Both this
header and the independent origin key are stripped before reaching FastAPI.

After proving that fence externally, the **private staging Worker** was deployed
with `API_ENABLED=1` and its shared-key secret, and its specific VPC Service now
targets **127.0.0.1:8082**, the new loopback `staging-api-nginx.conf` listener.
This is an operator-only rehearsal: production Pages is untouched, API admission
is still zero and the real judge consumer remains disabled. The earlier
health-only setup below is historical, not the current API exposure policy.

Actual command on the audit Mac:

```sh
python3 deploy/ec2/smoke_https.py --expected-samesite none
```

**17 checks passed** through Pages → private Worker → VPC → tunnel → Nginx → API:
anonymous identity/admin/job restrictions; unauthorized submit/run denial; 1 MiB
body bound; canonical manual Google redirect; Secure/HttpOnly/host-only session
cookie; Origin/Referer CSRF rejection; wrong OAuth state denial; canonical logout;
and both cookie deletions surviving both proxies. No Google token exchange,
email, authenticated job or account mutation occurred. The database queue still
contained the same 39 completed jobs and zero running/leased jobs afterward.

The first smoke attempt expected SameSite=Lax and failed. Comparing EC2 and
Pages cookie **attributes only** proved both used the copied legacy
`SESSION_SAMESITE=none`, Secure/HttpOnly; no cookie loss was found. The test now
accepts an explicit expected setting and the actual run used `none`. Do not
silently weaken cookie checks or claim an unexecuted complete Google/OTP login.

A temporary Nginx log recorded only the forwarded IP and **booleans** for key
presence; it never logged cookies, keys or URLs. Two real HTTPS requests proved
a single unchanged client IP despite forged XFF/X-Real-IP and origin-key headers,
and both access keys absent at Nginx. The temporary config/log was removed and
access logging disabled again. A combined probe including a forged
CF-Connecting-IP returned 403; its exact rejecting layer is UNVERIFIED, and that
probe is not counted as an origin spoofing test. Earlier immediate post-reload
probe transport errors are not counted as passes.

The host was actually rebooted after setup. Named-tunnel/API automatic recovery
and the same stable HTTPS hostname passed all **17 checks again**; the UID ledger
was preserved and the consumer remained disabled. Production Pages readback
still showed canonical deployment `ec40128a-991f-418b-916d-a1951180723d`,
compatibility date 2026-10-15, no origin variables and no service bindings.
Staging uses compatibility date 2026-10-18. No production project configuration
was changed; changing its binding/transport still requires final approval.

For staging rollback, first redeploy its private Worker with `API_ENABLED=0`,
then return its VPC Service to port 8080 if desired. Keep Pages explicitly in
service transport; never introduce legacy-origin retry/fallback. Production
cutover still needs the separate final approval and queue/backup gates.

## Earlier health-only checkpoint — 2026-10-19 (Asia/Bangkok)

The latest authorization permits staging setup, not production cutover. Official
Cloudflare skills and the Cloudflare MCP are installed/authenticated; see
`CODEX_MCP_SETUP.md`. This paragraph is superseded: production moved to AWS on
2026-10-19 and JustRunMy is retired, not an active production route.

Selected path:

```text
https://newbiegrader-aws-staging.pages.dev/api/health
  → Pages Function BACKEND_SERVICE binding
  → private Worker newbiegrader-aws-staging (no public route)
  → specific HTTP VPC Service 127.0.0.1:8080
  → named outbound Cloudflare Tunnel
  → loopback-only Nginx → FastAPI 127.0.0.1:8000
```

No purchased domain, control of pages.dev DNS, public FastAPI port, public HTTP
origin, Elastic IP, paid Worker plan or TLS verification bypass was required.
The internet transport is encrypted; HTTP exists only on the origin loopback
leg. A service binding fixes the Worker destination without public DNS routing.

### Platform choices and limits

- **Quick Tunnel:** temporary random hostname, no uptime guarantee; unsuitable
  as a permanent production origin. The temporary EC2 tunnel is now disabled.
- **Pages Functions:** preserve the existing frontend and same-origin cookies.
  Pages documents service bindings to Workers. This implementation uses that
  supported interface; it does not assume direct VPC bindings on Pages.
- **Private Worker + specific VPC Service + named Tunnel:** provides a stable
  Pages HTTPS entry without buying a domain. Both workers.dev and version-preview
  URLs are disabled. Only the specific loopback service is bound, not a network.
- **Cost limitation:** the account dashboard actually showed Workers **Free / $0
  current plan**. Workers VPC is free **during open beta**, not guaranteed free
  forever or covered by a production SLA. Free Workers currently allow 100,000
  requests/day, 10 ms CPU per invocation and 128 MiB memory; network wait is not
  CPU time. Pages Functions and the bridge consume platform request budgets;
  measure both before public launch and recheck pricing/status at cutover.

### Resources and configuration

- Separate direct-upload Pages project: `newbiegrader-aws-staging`, branch
  `aws-staging`. This is not the existing `newbiegrader` production project.
- Pages production/preview configuration: `BACKEND_TRANSPORT=service`,
  `BACKEND_SERVICE` bound to Worker `newbiegrader-aws-staging`, fail-open false,
  compatibility date `2026-10-18`.
- Private Worker: `API_ENABLED=0`, fixed `PRIVATE_API` VPC Service binding,
  `workers_dev=false`, `preview_urls=false`, observability disabled.
- Named tunnel: `newbiegrader-aws-staging`; VPC Service:
  `newbiegrader-aws-health-staging`, fixed IPv4 `127.0.0.1`, HTTP port 8080.
  Public ingress configuration is catch-all HTTP 404; no DNS route was created.
- EC2 `/etc/systemd/system/newbiegrader-tunnel.service` is enabled/active.
  Token: `/etc/newbiegrader/tunnel-token`, root:root 0600, parent 0700.
  `LoadCredential` supplies a per-service file, never an argv/environment token.
- Actual Wrangler config/logs and API evidence are private under
  `~/.local/share/newbiegrader-private/`, outside Git. The checked-in example
  contains placeholders only. Pin Wrangler 4.151.1 for reproducibility.

Cloudflare rejected the Bangkok date `2026-10-19` as future while its UTC date
was still October 18. The deployed compatibility date is therefore October 18;
the first rejected upload is not counted as a successful deployment.

### Verification evidence

From the audit Mac over outbound internet, `curl` with ordinary TLS certificate
validation exercised the complete Pages/service-binding/VPC/tunnel chain:

- GET `/api/health` → 200, `ok=true`, 68 problems.
- GET `/api/auth/me`, GET `/api/jobs/staging-canary`, POST `/api/submit` with
  `{}`, POST `/api/run` with `{}` → 404; no public execution was enabled.
- HEAD `/api/health` → 404, matching a direct EC2 loopback probe of the existing
  FastAPI GET-only route. It is not claimed as a successful HEAD health check.
- The named tunnel reports healthy / four connections. Its systemd restart and
  subsequent health probe use the same Pages hostname; see the migration log.
- Cloudflare readback confirms the production project's canonical deployment ID
  remains unchanged, the new staging service binding is selected, and the private
  Worker's public subdomain/preview flags are disabled.
- Python urllib returned 403 from the audit environment; these attempts are
  recorded as failures, not evidence of an application denial policy. Successful
  chain verification uses curl, not a TLS-disable or access-control bypass.

The full API is deliberately unavailable on this route. Browser login, OTP,
Google callback and submission persistence still require an approved controlled
cutover rehearsal. GET health alone does not prove those flows.

### Reproduce staging setup

Authenticate using the documented Codex/Cloudflare OAuth flow; preserve existing
settings and avoid pasting tokens into chat. The MCP scopes requested here cover
account/user read, Workers read/write/bind, Pages metadata/read/write, tunnel
read/write and connectivity directory read/bind/admin. No DNS/billing scope is
needed for this design. Use only the existing Free plan.

1. Reuse the named tunnel and specific VPC Service; inventory before creating
   anything. Install its token through SSH stdin to a root-only file and install
   the reviewed `newbiegrader-tunnel.service.example`. Never return a token from
   a tool invocation or put it in Git, arguments, logs or screenshots.
2. Copy `deploy/ec2/cloudflare/wrangler.jsonc.example` to a private directory,
   set the existing VPC Service ID and absolute source path. Keep health-only
   mode and public Worker URLs disabled. Run `wrangler deploy --dry-run`, then
   deploy that exact config. Never deploy the placeholder example verbatim.
3. Create/reuse the **separate staging** Pages project with these configuration
   fields in each intended deployment environment:

   ```json
   {
     "compatibility_date": "2026-10-18",
     "fail_open": false,
     "env_vars": {"BACKEND_TRANSPORT": {"type": "plain_text", "value": "service"}},
     "services": {"BACKEND_SERVICE": {"service": "newbiegrader-aws-staging", "environment": "production"}}
   }
   ```

4. From the repository root, upload explicitly to staging:

   ```sh
   npx --yes wrangler@4.151.1 pages deploy static --project-name newbiegrader-aws-staging --branch aws-staging --commit-dirty=true
   curl --fail --show-error https://newbiegrader-aws-staging.pages.dev/api/health
   ```

5. Recheck blocked API paths, named-tunnel restart, loopback listeners, absent
   `/etc/newbiegrader/worker-enabled`, and disabled admission. Do not call a
   production claim/admit RPC during this health-only verification.
6. Back up the new tunnel credential/unit with
   `python3 deploy/ec2/backup_state.py --include-tunnel`. This encrypts seven
   fixed files directly from SSH; no plaintext archive is written. Keep the
   private age identity offline. It is not a Supabase DB/Storage backup.

The Pages proxy selects service mode explicitly. Unset transport preserves the
existing HTTPS origin. Missing bindings/invalid mode fail closed with 503;
upstream errors return 502, with no retry/fallback to a different judge.

## Final cutover approval remains required

Complete every gate in `EC2_MIGRATION.md` first. Before asking for final approval,
prepare the full chain with synthetic identities and verify backup/restore,
queue fencing, canonical OAuth callbacks, cookies, CSRF, IP trust and rollback.
At the approved maintenance window:

- Pause old admission, drain its actual **local** queue, stop/fence its consumer,
  verify leases, and merge a final locked UID-ledger snapshot. A zero database
  queue does not establish that the old local queue is drained.
- Install the reviewed loopback production Nginx listener on port **8081**.
  Change the specific VPC Service target only after the API gate is tested.
- Create a random server-only shared key of at least 32 characters, install it
  as Worker and Pages `BACKEND_PROXY_KEY` secrets without printing it, then enable
  bridge API mode. Never give the key to browser code; the Pages proxy strips a
  client-supplied copy and the bridge removes it before forwarding to FastAPI.
- Add the service binding and `BACKEND_TRANSPORT=service` to the existing Pages
  project only with final approval and a reviewed redeployment. Preserve manual
  redirects, query strings and multiple Set-Cookie headers.
- Do not retry a failed request against JustRunMy automatically: that risks
  duplicate execution and split queue ownership. Keep its service available
  throughout verification and rollback.

## Rollback / removal

For this isolated staging deployment, disable the staging Pages service route or
stop `newbiegrader-tunnel.service`; existing production remains on JustRunMy.
After a future approved cutover: pause AWS admission, drain/fence its worker,
restore the original Pages HTTPS transport/origin and the old consumer according
to `EC2_MIGRATION.md`, then reopen admission after smoke tests. Never roll back
UID reservations or delete user rows/jobs. Delete Cloudflare resources only
when unused and after approval; preserve encrypted credentials during rollback.

## Official references

- [Cloudflare agent setup](https://developers.cloudflare.com/agent-setup/prompt.md)
- [Pages service bindings](https://developers.cloudflare.com/pages/functions/bindings/#service-bindings)
- [Workers VPC setup](https://developers.cloudflare.com/workers-vpc/get-started/)
- [Specific VPC Services and roles](https://developers.cloudflare.com/workers-vpc/configuration/vpc-services/)
- [VPC beta pricing](https://developers.cloudflare.com/workers-vpc/platform/pricing/)
- [Workers platform limits](https://developers.cloudflare.com/workers/platform/limits/)
- [Quick Tunnel limitations](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
