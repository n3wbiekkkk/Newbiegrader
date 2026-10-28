# Current production architecture

Updated 2026-10-28 after the backend architecture rollout on all three hosts.
Running backend snapshot: `architecture-20261028-1bf56506a130` (grader 2.0.8 / Python 3.13.17).
Backend source fingerprint:
`1bf56506a13088f1cf6d73f12b95083bb4a6d8c1cedbfa0ee88ef2862fa20c76`.
See [architecture qualification](releases/backend-architecture-2026-10-28.json),
[earlier disclosure qualification](releases/submission-disclosure-2026-10-26.json)
and [primary/failover activation](releases/primary-failover-2026-10-27.json).
The transport and allocations below remain unchanged. Historical qualification
records retain their original scope.


- **Frontend:** Cloudflare Pages, `https://newbiegrader.pages.dev`, vanilla SPA.
- **Transport:** same-origin Pages Function → private `newbiegrader-pc-production`
  Worker → primary VPC service and its dedicated QUIC tunnel → loopback Nginx
  port 8081 → FastAPI port 8000. Before forwarding, an anonymous bounded health
  probe selects the primary; an unhealthy primary selects the separately bound
  homeserver. Both unavailable returns 503. A forwarded request is never replayed
  at the other origin, including an ambiguous POST. Recovery selects the primary
  again on subsequent requests. Worker routes and preview URLs remain disabled.
- **Backend:** the restored Ubuntu primary (i5-10400T, about 7.1 GiB RAM) serves
  the API and four native workers. The Ubuntu 24.04 homeserver (Ryzen 3 4300U,
  about 3.2 GiB RAM) retains a warm API, its own tunnel and two workers. Both APIs
  retain one CPU / 320 MiB and the same current signing key and cookie settings.
  The Ubuntu 26.04 auxiliary PC (i5-12400F, about 15 GiB RAM) retains its existing
  ten-worker allocation. All use dedicated Python 3.13.17; system Python is preserved.
- **Judging:** four primary, two homeserver and ten auxiliary-PC workers are
  configured. Each unit has one CPU / 1 GiB; aggregate slices remain four CPUs /
  4 GiB, two CPUs / 2 GiB and ten CPUs / 10 GiB respectively. Per-job cgroups,
  private numeric UIDs, bounded tmpfs, Landlock, seccomp, language allowances,
  the 128 MiB declared-memory cap and 240-second timeout are unchanged.
- **Admission:** the existing atomic database queue allows up to 50 waiting jobs
  and one active job per ordinary account. All sixteen workers were freshly observed ready after the
  [PC peer-relay correction](releases/worker-count-relay-2026-10-27.json). The
  initial six-worker report omitted PC observations because the primary could not
  read that peer directly. Sixteen ready workers are not a simultaneous-user
  capacity claim. Fresh observations report actual ready capacity separately
  from local allocation; stale observations are unknown. See [fleet monitoring](WORKER_FLEET.md).
- **Startup/feedback latency:** precompiled trusted runtime, a credential-free
  executor that avoids web/database imports, immediate next-job claim and a
  one-second scheduled polling cap for active/head-of-queue jobs. Synthetic
  17-case jobs take 2.82–3.03 seconds; public Python/C/C++ checks observed
  3.75–4.81 seconds from submit to result. Larger jobs retain their actual
  runtime; these are prior PC measurements, not homeserver capacity results.
  Homeserver HTTPS smoke checks completed in 5.73–7.35 seconds per 17-case job after the dedicated transport switch.
  See the [PC measurements](releases/pc-execution-performance-2026-10-22.json) and
  [homeserver recovery record](releases/homeserver-recovery-2026-10-25.json).
- **Availability:** both serving nodes keep boot-enabled APIs, tunnels and their
  selected workers. The auxiliary PC retains its Server/Desktop mode policy.
  Controlled shutdown of the primary API, tunnel and all four workers verified
  homeserver-only Python/C/C++ judging, existing session continuity and automatic
  return to the primary. A real reboot verified all nine selected units return automatically while
  sampled public requests used the homeserver; physical power loss during a
  running job was not exercised. Both nodes still depend on Cloudflare and the same Supabase project.
  Tailnet key expiry remains an operator responsibility. Tailscale SSH was tested,
  rejected by the primary tailnet's SSH policy and reverted; ordinary SSH was
  verified restored. Enabling it requires the tailnet owner's policy change.
- **Database, identities and durable queue:** the existing Supabase project;
  no database migration or identity rewrite was needed to move hosts.
  Worker PostgREST connections use pooled HTTP/1.1 with certificate verification;
  the API retains the pinned SDK's existing transport. Ambiguous claim failures
  are not automatically replayed.
- **Website sessions:** opaque cookies identify a hash-only server-side family.
  One database RPC checks revocation and current account identity per protected
  request. Logout revokes that browser family; other devices remain active.
  Password/account recovery invalidates prior versions. See
  [session lifecycle and recovery](SESSION_REVOCATION.md).
- **Public abuse controls:** the private Worker limits API, authentication and
  execution requests by trusted client IP, with shared classroom IPs in mind.
  Turnstile protects email-code requests before their existing handler; password
  login, OTP verification and judging keep their established authorization.
  Exact settings and approximate local-counter limits are in the
  [transport guide](HOST_CLOUDFLARE_SETUP.md).
- **Files:** protected local public/private roots use the verified
  `primary-20261026` generation on the primary and `emergency-20261025` on the
  homeserver. Both match 100 problems / 1,814 cases / 100 statement PDFs.
  Public roots are root:API-group 0750 / 0440; private roots are root:root
  0700 / 0400. No cloud-file fallback. Future releases and file publications must
  update and qualify both nodes before relying on failover; replication is not automatic.
- **Catalog:** 100 problems / 1,814 cases / 100 selected statement PDFs. Permanent slugs and
  submission history remain intact. The current map is [2026-10-24](catalog/problem-numbers-2026-10-24.csv).
- **Backup:** each host runs its encrypted daily configuration/UID/table-row
  export to the private backup bucket. Homeserver objects retain their existing
  root namespace; primary objects use `hosts/promma-server/`, with retention
  restricted to that namespace. Ephemeral `web_sessions` are excluded. Disaster
  restore starts with no sessions and a fresh signing key. Protected file bytes
  have a separate authenticated off-host archive; the age private identity stays
  off-host. Exporting tables is not a transactional hosted-service backup.
- **Discord presence:** a separate unprivileged service checks the public HTTPS
  identity path, local API and both local workers every 30 seconds. It displays
  `Newbiegrader website` while online and goes invisible when those checks fail.
  Discord/network outages can delay or obscure status; it is an indicator rather
  than independent off-host monitoring. Alert routing stays in private configuration.
- **Watchdog:** the homeserver retains the sole scheduled Discord watchdog and
  presence process. It checks its local services and the public HTTPS path, plus
  the primary's anonymous health over a private tailnet listener. A primary
  outage therefore alerts in the Newbiegrader route even while failover keeps
  public health green. Existing bot credentials and separate personal-service
  routing are preserved; validation used check-only mode. Monitoring itself is
  not redundant if the homeserver is unavailable.

See [deployment](HOST_DEPLOYMENT.md), [private transport](HOST_CLOUDFLARE_SETUP.md),
[file storage](BACKEND_PROBLEM_FILES.md) and [backup/recovery](HOST_BACKUP_RESTORE.md).
Private release records retain measured test results and host configuration.
Application rollback uses a verified compatible release on the active host, retaining
current files, the newest append-only UID ledger and the newly rotated signing
key. Never restore the retired signing key from saved configuration.
