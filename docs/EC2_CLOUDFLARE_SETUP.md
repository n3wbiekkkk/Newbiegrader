# Cloudflare connection — verified isolated staging

## Executed checkpoint — 2026-10-19 (Asia/Bangkok)

The latest authorization permits staging setup, not production cutover. Official
Cloudflare skills and the Cloudflare MCP are installed/authenticated; see
`CODEX_MCP_SETUP.md`. Existing Newbiegrader production still uses JustRunMy.

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
