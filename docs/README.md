# Documentation

Current production is Cloudflare Pages with a private tunnel to the Ubuntu PC.
The PC runs four isolated workers and a separate API; Supabase retains metadata,
identities, history and the durable queue. The current verified application code
is `2ae8aedd40c4ff4ef0ef267ab7c78f8d2c44ef09` (2026-10-22). Documentation-only
updates can follow that release without changing the running application.

## Operating the current deployment

| Topic | Guide |
| --- | --- |
| Topology, catalog, services and allocations | [Production architecture](PRODUCTION_ARCHITECTURE.md) |
| Installation, four-worker activation, precompilation and boot recovery | [Host deployment](HOST_DEPLOYMENT.md) |
| Pages/Worker/VPC/tunnel transport and staging boundary | [Private Cloudflare transport](HOST_CLOUDFLARE_SETUP.md) |
| Encrypted backup coverage, restore and UID preservation | [Backup and recovery](HOST_BACKUP_RESTORE.md) |
| Queue bounds, scheduling, latency and load testing | [Load handling](load-handling.md) |
| Release validation and remaining accounting limits | [Security readiness](SECURITY_READINESS.md) |
| Routine release and recovery gates | [Release checklist](release/README.md) |

## Problems, files and user access

| Topic | Guide |
| --- | --- |
| Canonical authoring, sample synchronization, PDFs and approved numbering | [Making problems](making-problems.md) |
| Protected roots, hashes, permissions and publication | [Backend problem files](BACKEND_PROBLEM_FILES.md) |
| Metadata integration and current disk/DB mapping | [Problem metadata and file storage](migration-supabase.md) |
| Browsing, PDF versions and cache policy | [Problem loading](problem-loading.md) |
| Practice, contest and peer feedback boundaries | [Submission feedback](submission-feedback-policy.md) |
| Existing email identity setup and future SMTP configuration | [Email verification](EMAIL_VERIFICATION_SETUP.md) |
| Production dependencies and licenses | [Dependency licenses](DEPENDENCY_LICENSES.md) |

## Checkpoint records

- [PC migration qualification](releases/pc-host-qualification-2026-10-22.json)
  records the initial migration and recovery checks.
- [PC latency qualification](releases/pc-latency-2026-10-22.json) records the
  later runtime optimization, public HTTPS timings and 493-test Linux gate.
- [Earlier single-worker benchmark](releases/single-worker-benchmark.json) is
  historical synthetic evidence and does not describe current PC capacity.
- [Codex MCP setup](CODEX_MCP_SETUP.md) is a dated operator integration record;
  development MCP project scope does not identify the production environment.

Private audit/release reports retain their original checkpoint scope and remain
outside public Git. Consult current guides before acting on an old command.
No private problem fixtures, references, credentials, catalogs, session headers,
backups or operator handoff files belong in documentation commits.
