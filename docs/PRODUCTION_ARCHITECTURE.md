# Current production architecture

Updated 2026-10-25 after emergency recovery onto the homeserver.
Base application release: `97985ed0e1d0bb8e9f5cd7a62b8362a1a2a2d4b8`; the fleet-reporting revision is identified by the fingerprint below.
Documentation-only updates do not change that running application release.
Fleet-reporting source fingerprint: `15cd08f34384a26e6c8217102be4a2580b47d7810b16b40d6059ca026f511b12`; qualification and activation are recorded separately from historical releases. See the [25 October activation](releases/public-launch-qualification-2026-10-25.json). Historical qualification dates below retain their original scope.


- **Frontend:** Cloudflare Pages, `https://newbiegrader.pages.dev`, vanilla SPA.
- **Transport:** same-origin Pages Function → private `newbiegrader-pc-production`
  Worker → VPC service `newbiegrader-pc-api` → dedicated `newbiegrader-home-api` QUIC tunnel
  → loopback Nginx port 8081 → FastAPI port 8000. The origin has no public HTTP
  listener and no retired-host fallback. Worker/service labels retain their PC
  names for binding compatibility. The old PC tunnel is no longer this API's
  destination, so returning PC workers cannot introduce an older serving API.
- **Backend:** Ubuntu 24.04 homeserver (Ryzen 3 4300U, about 3.2 GiB RAM)
  serves FastAPI/Nginx and the private tunnel. The API retains one CPU / 320 MiB.
  Ubuntu 26.04 PC (i5-12400F, about 15 GiB RAM) supplies additional native workers
  and private monitoring. Both use dedicated Python 3.13.17; system Python is preserved.
- **Judging:** ten PC workers plus two homeserver workers, one job per unit,
  serial tests. Each has one CPU / 1 GiB, with aggregate 10-CPU / 10-GiB and
  two-CPU / 2-GiB slices respectively. Per-job cgroups, private numeric UIDs,
  bounded tmpfs, Landlock, seccomp, language memory allowances, the 128 MiB
  declared-memory cap and 240-second overall timeout are unchanged.
- **Admission:** twelve configured execution slots and up to 50 waiting jobs;
  one active job per ordinary account. Both hosts use the existing atomic
  database queue. Neither the backlog bound nor a short synthetic benchmark
  establishes a sustained simultaneous-user capacity. Optional fresh fleet
  observations report actual ready workers; stale/missing configured observation
  is unknown rather than a static total. Local allocation remains separately
  reported. See [worker fleet and monitoring](WORKER_FLEET.md).
- **Startup/feedback latency:** precompiled trusted runtime, a credential-free
  executor that avoids web/database imports, immediate next-job claim and a
  one-second scheduled polling cap for active/head-of-queue jobs. Synthetic
  17-case jobs take 2.82–3.03 seconds; public Python/C/C++ checks observed
  3.75–4.81 seconds from submit to result. Larger jobs retain their actual
  runtime; these are prior PC measurements, not homeserver capacity results.
  Homeserver HTTPS smoke checks completed in 5.73–7.35 seconds per 17-case job after the dedicated transport switch.
  See the [PC measurements](releases/pc-execution-performance-2026-10-22.json) and
  [homeserver recovery record](releases/homeserver-recovery-2026-10-25.json).
- **Availability:** boot-enabled Tailscale, API, tunnel and two local workers; the PC starts ten workers and monitor containers in Server Mode.
  The PC has passed Server/Desktop/Server reboots. An actual homeserver reboot has not been exercised during this recovery.
  Tailnet device-key expiry is managed separately in its
  admin console and must be reviewed for unattended operation.
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
- **Files:** protected local public/private roots under
  `/var/lib/newbiegrader/problem-files/emergency-20261025/`. Public files are
  root:newbiegrader-api with 0750 directories / 0440 files; private files are
  root:root with 0700 directories and no group/world file access. No runtime cloud-file fallback.
- **Catalog:** 100 problems / 1,814 cases / 100 selected statement PDFs. Permanent slugs and
  submission history remain intact. The current map is [2026-10-24](catalog/problem-numbers-2026-10-24.csv).
- **Backup:** the active homeserver runs the daily encrypted configuration/UID/table-row
  export to the private Supabase backup bucket. Ephemeral `web_sessions` rows are
  excluded; restore starts with no sessions and a fresh signing key. Protected
  file bytes have a
  separate verified encrypted off-host backup. The age private identity stays
  off-host. See the recovery guide for the exact coverage and limits.
- **Discord presence:** a separate unprivileged service checks the public HTTPS
  identity path, local API and both local workers every 30 seconds. It displays
  `Newbiegrader website` while online and goes invisible when those checks fail.
  Discord/network outages can delay or obscure status; it is an indicator rather
  than independent off-host monitoring. Alert routing stays in private configuration.
- **Watchdog:** the homeserver checks API, both workers, tunnel, queue, disk, backup
  age, journal and the public HTTPS anonymous-identity endpoint every five minutes.
  The public check traverses Pages, the private bridge and tunnel without a session.
  Its existing bot token stays in root-only
  configuration; validation uses check-only mode without sending messages.

See [deployment](HOST_DEPLOYMENT.md), [private transport](HOST_CLOUDFLARE_SETUP.md),
[file storage](BACKEND_PROBLEM_FILES.md) and [backup/recovery](HOST_BACKUP_RESTORE.md).
Private release records retain measured test results and host configuration.
Application rollback uses a verified compatible release on the active host, retaining
current files, the newest append-only UID ledger and the newly rotated signing
key. Never restore the retired signing key from saved configuration.
