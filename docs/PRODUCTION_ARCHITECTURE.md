# Current production architecture

Updated 2026-10-22 after migration to the native PC backend.

- **Frontend:** Cloudflare Pages, `https://newbiegrader.pages.dev`, vanilla SPA.
- **Transport:** same-origin Pages Function → private `newbiegrader-pc-production`
  Worker → VPC service `newbiegrader-pc-api` → named `newbiegrader-pc` QUIC tunnel
  → loopback Nginx port 8081 → FastAPI port 8000. The origin has no public HTTP
  listener and no retired-host fallback.
- **Backend:** Ubuntu 26.04 x86_64 PC, Intel i5-10400T (6 physical cores /
  12 threads), about 7.1 GiB RAM and SSD storage; dedicated Python 3.11 venv.
  API and judging use separate systemd services.
- **Judging:** exactly four `newbiegrader-worker@N.service` instances, one job
  per unit and serial tests within each job. Each has one CPU / 1 GiB, with an
  aggregate four-CPU / 4 GiB slice. Private workspace tmpfs, per-job cgroups,
  unique reserved UIDs, Landlock and seccomp remain mandatory. Per-problem limits
  and language memory allowances are unchanged; declared memory is capped at
  128 MiB and the overall submission deadline remains 240 seconds.
- **Database, identities and durable queue:** the existing Supabase project;
  no database migration or identity rewrite was needed to move hosts.
- **Files:** protected local public/private roots under
  `/var/lib/newbiegrader/problem-files/g1-4e9ba14273bc/`. Public files are
  root:newbiegrader-api with 0750 directories / 0440 files; private files are
  root:root with 0700 directories / 0400 files. No runtime cloud-file fallback.
- **Catalog:** 89 problems / 1,594 cases / 89 selected PDFs. Permanent slugs and
  submission history remain intact. The calibrated catalog number map is
  unchanged.
- **Backup:** the active PC runs the daily encrypted configuration/UID/table-row
  export to the private Supabase backup bucket. Protected file bytes have a
  separate verified encrypted off-host backup. The age private identity stays
  off-host. See the recovery guide for the exact coverage and limits.
- **Watchdog:** the PC checks API, all four workers, tunnel, queue, disk, backup
  age and journal every five minutes. Its existing bot token stays in root-only
  configuration; validation uses check-only mode without sending messages.

See [deployment](HOST_DEPLOYMENT.md), [private transport](HOST_CLOUDFLARE_SETUP.md),
[file storage](BACKEND_PROBLEM_FILES.md) and [backup/recovery](HOST_BACKUP_RESTORE.md).
Private release records retain measured test results and host configuration.
Application rollback uses a verified compatible release on this PC, retaining
current files and the newest append-only UID ledger.
