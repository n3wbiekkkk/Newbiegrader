# Documentation

Current production is Cloudflare Pages with a private tunnel to the homeserver API,
ten isolated workers on ubuntu-pc and two on the homeserver. The PC also hosts
private Homepage / Prometheus / Grafana monitoring for both machines. Supabase
retains metadata, identities, history and the durable queue. The engine remains
2.0.8 / Python 3.13.17. The fleet-reporting source fingerprint is
`15cd08f34384a26e6c8217102be4a2580b47d7810b16b40d6059ca026f511b12`; the [fleet qualification](releases/worker-fleet-2026-10-25.json)
records tests and deployment separately. Earlier release records retain their
historical scope. See [fleet observation and monitoring](WORKER_FLEET.md).

## Operating the current deployment

| Topic | Guide |
| --- | --- |
| Topology, catalog, services and allocations | [Production architecture](PRODUCTION_ARCHITECTURE.md) |
| Native installation, precompilation and boot recovery | [Host deployment](HOST_DEPLOYMENT.md) |
| Pages/Worker/VPC/tunnel transport and staging boundary | [Private Cloudflare transport](HOST_CLOUDFLARE_SETUP.md) |
| Encrypted backup coverage, restore and UID preservation | [Backup and recovery](HOST_BACKUP_RESTORE.md) |
| Observed worker counts, monitoring and per-machine responsibilities | [Worker fleet](WORKER_FLEET.md) |
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
