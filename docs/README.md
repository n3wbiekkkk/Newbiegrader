# Documentation

Current production is Cloudflare Pages with a private tunnel to a temporary Ubuntu
homeserver running two isolated workers and a separate API while the main PC is off.
The approved return target is PC four + homeserver two workers; that six-worker
fleet has not yet been verified live. Supabase retains metadata,
identities, history and the durable queue. The current verified application code
is `97985ed0e1d0bb8e9f5cd7a62b8362a1a2a2d4b8` (2026-10-25), grader 2.0.8 / Python 3.13.17. Documentation-only
updates can follow that release without changing the running application.
Current source fingerprint: `1ebfe1d7fc64156c913b56fbdd4282a7cf8598b1b9c7135396c0cdfdb9ba2ce2`. See the [25 October activation](releases/public-launch-qualification-2026-10-25.json). Historical qualification dates below retain their original scope.


## Operating the current deployment

| Topic | Guide |
| --- | --- |
| Topology, catalog, services and allocations | [Production architecture](PRODUCTION_ARCHITECTURE.md) |
| Installation, four-worker activation, precompilation and boot recovery | [Host deployment](HOST_DEPLOYMENT.md) |
| Pages/Worker/VPC/tunnel transport and staging boundary | [Private Cloudflare transport](HOST_CLOUDFLARE_SETUP.md) |
| Encrypted backup coverage, restore and UID preservation | [Backup and recovery](HOST_BACKUP_RESTORE.md) |
| Queue bounds, scheduling, latency and load testing | [Load handling](load-handling.md) |
| Public website security scope and accepted limitations | [Public security](PUBLIC_SECURITY.md) |
| Release validation and remaining accounting limits | [Security readiness](SECURITY_READINESS.md) |
| Session revocation, signing-key rotation and recovery | [Website sessions](SESSION_REVOCATION.md) |
| Account export, deletion, retention and activation gates | [Account data](ACCOUNT_DATA.md) |
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

- [Homeserver recovery](releases/homeserver-recovery-2026-10-25.json) records
  the unchanged 2.0.8 backend, two bounded workers, 613 full / 380 critical Linux
  tests with zero skips, 22 native file/verdict checks and real three-language
  HTTPS jobs. Existing homeserver app data was preserved.
- [Public-launch qualification](releases/public-launch-qualification-2026-10-25.json)
  records real signup, bounded email delivery, retention, offline restore and
  the qualified source and subsequent two-worker backend activation.

- [Account lifecycle and queue activation](releases/account-lifecycle-2026-10-24.json)
  records the live backend, three-language HTTPS jobs, export/deletion/session
  checks, daily maintenance, and the public-readiness gates still incomplete.

- [Public-readiness candidate](releases/public-readiness-candidate-2026-10-24.json)
  records local/Linux/SQL qualification and the explicit gates still pending.
  It is not the running production release.

- [Session revocation qualification](releases/session-revocation-2026-10-23.json)
  records the earlier session-revocation checkpoint, copied-cookie denial, SQL concurrency,
  real HTTPS jobs and recovery with no restored sessions.
- [Earlier public readiness](releases/public-readiness-2026-10-23.json) records
  worker transport, Turnstile and Discord presence qualification.
- [Public website security qualification](releases/public-security-2026-10-22.json)
  records the earlier security release, actual HTTPS checks and operator decisions.
- [PC migration qualification](releases/pc-host-qualification-2026-10-22.json)
  records the initial migration and recovery checks.
- [PC latency qualification](releases/pc-latency-2026-10-22.json) records the
  later runtime optimization, public HTTPS timings and 493-test Linux gate.
- [Credential-free execution qualification](releases/pc-execution-performance-2026-10-22.json)
  records the earlier execution release, roughly 20% shorter synthetic jobs,
  public before/after timings and the 497-test Linux gate.
- [Earlier single-worker benchmark](releases/single-worker-benchmark.json) is
  historical synthetic evidence and does not describe current PC capacity.
- [Codex MCP setup](CODEX_MCP_SETUP.md) is a dated operator integration record;
  development MCP project scope does not identify the production environment.

Private audit/release reports retain their original checkpoint scope and remain
outside public Git. Consult current guides before acting on an old command.
No private problem fixtures, references, credentials, catalogs, session headers,
backups or operator handoff files belong in documentation commits.
