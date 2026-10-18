# Newbiegrader security audit — 2026-10-18

## Decision and evidence boundary

**Not ready for unrestricted public execution.** The confirmed S01 database
exposure was closed after explicit approval; cross-job isolation failures remain.
Other local fixes in this branch are not
production fixes until reviewed and released. Passing tests do not establish
sandbox security. No rewrite is recommended.

- Baseline: `3014da34992cebcf7b5d00c303944accf12852da`.
- Branch: `audit/production-hardening-2026-10-18`.
- `review.diff` was already untracked and was not inspected or changed.
  Local ignored `AGENTS.md` is excluded from commits.
- Host: macOS Apple Silicon. Execution tests: disposable Docker Linux arm64,
  Python 3.11, root, default container capabilities, network disabled, explicit
  development isolation flags. Synthetic attacks never touched user workloads.
- Database tests: disposable PostgreSQL 17 with Supabase-like default grants.
  Initial production Supabase access was **read-only**, through the configured
  MCP, project `qblnlfzjublfnnsasgpe`. Following explicit approval, S01 permission
  DDL was applied at 2026-10-18 02:18 UTC. No application rows, secrets or deployment
  were changed; migration history was recorded by Supabase.
- All public HTTP GETs in this audit originated from the audit Mac's current
  network. Public IP/network classification was not established. Backend
  reachability from this vantage is confirmed; unrestricted Internet
  reachability and access from a different trust zone are **UNVERIFIED**.
- GET `/api/health` and `/api/version` at 2026-10-18 01:58–02:00 UTC returned 200.
  Version fingerprint was
  `09707c5593b52d88f8a1ccb5f9f6145ab371877271bbb9126d98e025ae9f2e12`.
  Reported configuration: `combined`, queue `local`, problem source `supabase`,
  0.5 CPU, 512 MB, one worker, one test at a time, declared cap 256 MB.
  These responses do not disclose effective kernel isolation or dependency versions.

Status vocabulary: **CONFIRMED** = code plus a recorded observation or regression;
**LIKELY** = supported consequence not induced; **UNVERIFIED** = missing runtime
evidence; **NOT AN ISSUE** = a specific allegation contradicted within tested scope.

## Inventory and trust boundaries

| Boundary | Reviewed implementation | Untrusted input / protection |
| --- | --- | --- |
| Browser → Pages → API | `static/app.js`, `static/index.html`, `static/_headers`, `functions/api/[[proxy]].js` | HTML/Markdown rendering, cookies, forms, query values, forwarded headers, edge cache |
| Identity → API policy | `server.py:1550`, `server.py:1627`, `server.py:1743`, `server.py:1901`, `server.py:2335` | Google code/state/profile, password/email, signed sessions, admin email, proxy chain |
| API → service-role database | `server.py:541`, `server.py:2972`, `supabase/schema.sql` | Ownership and contest checks must precede privileged reads; RLS is not an API authorization layer for service_role |
| Database/Storage → trusted runner | `problem_store.py:371`, `problem_store.py:425`, `judge_runner.py:299` | Metadata, private test bytes, serialized problem; whole-suite hash verified |
| Queue → worker | `server.py:758`, `server.py:969`, `server.py:1043`, `supabase/schema.sql:280` | Source/payload, leases, attempt fencing, completion transaction |
| Trusted root → compiler/runtime | `grader.py:469`, `grader.py:496`, `grader.py:779`, `grader.py:959` | Source, compiler diagnostics, executable/workspace paths, process tree |
| Admin → operational tools | `server.py:3652`, `server.py:3754`, `tools/`, Dockerfile, CI | Rejudge, plagiarism, imports and statement tooling; privileged offline code is trusted, not sandboxed user input |

Also reviewed checkers, problem loaders, all API route declarations, reports,
profiles, contest announcements/registration, frontend sinks/API calls, queue SQL,
worker entry point, requirements, Docker packaging, CI and existing tests.
No compose file or repository-defined privileged/capability deployment was found.
Operational docs disagree with current project reference, host capacity and
problem counts; deployed facts above take precedence.

## Findings

### S01 — Anonymous aggregate views bypass protected table RLS

**High · CONFIRMED in production · FIXED and verified in production after approval.**

- References: view definitions `supabase/schema.sql:182`; remediation
  `supabase/schema.sql:480`; regression `tests/security_sql.sql:1`.
  Short evidence: `create or replace view leaderboard_scores as select user_email...`;
  view `reloptions` was null and `anon`/`authenticated` had SELECT.
- Read-only production transaction under `SET LOCAL ROLE anon` saw **0**
  submissions/users/reports, but **18** leaderboard rows and **13** stats rows.
  Only counts and catalog metadata were retrieved, not emails/source/row contents.
- Root cause: default owner-rights views bypass underlying RLS. Exposure includes
  identity/email, problem, best score, accepted state and activity timestamp in
  the leaderboard view; aggregate counts in problem_stats. Write grants do not
  prove these aggregate views are writable. Removing a UI/API page does not
  remove Data API permissions.
- Minimal fix: invoker views plus revoke public relation privileges; retain
  backend service-role access. The SPA has no direct Supabase client dependency.
- Verification: original schema fails the new SQL assertion with simulated
  Supabase grants; updated schema applies twice and passes service-role/ACL/RLS
  checks in PostgreSQL 17. See production review SQL and rollback in
  [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).
- Approved follow-up: migration `20261018021803_server_only_data_api_permissions`
  applied successfully. Both views now have `security_invoker=true`; all 12
  scoped relations deny table/column privileges to anon/authenticated. Actual
  role-based SELECT attempts on both views and problems raise insufficient_privilege;
  service_role still reads 18 leaderboard rows, 13 stats rows and 68 problems.
  The two Security Definer View advisor errors disappeared. API health/problems/
  stats/contests return 200 from the audit Mac. Before/after ACL evidence was
  saved locally; no application row contents were retrieved.
- Remaining risk: this closes S01, not the backend stats visibility bug S12 or
  other local fixes awaiting release. Future schema/column grants need the gate.
  Direct REST exploitation requires a project anon/publishable key or an
  authenticated token; its external availability was not tested. The confirmed
  observation is production **role authorization**, not a keyless REST request.
  Catalog inspection found no explicit column ACLs (`pg_attribute.attacl`), so
  table revocation closes the observed grants; new column grants need review.
  Future tables/views and column-level grants require the same gate.

### S02 — Root permission preparation follows user-controlled symlinks

**High · CONFIRMED synthetic exploitation · FIXED locally.**

- References: `grader.py:935`, `grader.py:959`, `_run_cwd` in `grader.py`;
  `tests/test_critical_paths.py:17`, `:33`, `:48`.
  Baseline did `os.chmod(cwd, 0o755)` / chmod executable by path.
- Synthetic first test replaced its executable with a symlink to a root-owned
  0600 canary. Before the next test, root changed the target to 0755; the sandbox
  then read it. A synthetic symlinked workspace changed a root directory from
  0700 to 0755. Python source alias resolution also selected a privileged parent.
- Impact: disclose or alter permissions of files root can chmod. No host escape
  or arbitrary root command execution was demonstrated. Unlike the earlier F1,
  the current compiler already drops UID before executing the toolchain.
- Fix: `O_NOFOLLOW`/directory fd validation and `fchmod`; refuse unsafe paths as
  job errors; do not chmod root-owned hardlink executable targets; use lexical
  Python source parent rather than resolve an attacker-selected alias.
- Verification: all three regressions failed before their fixes and pass on
  Linux/root. C, C++/STL and normal Python tests also run in the critical suite.
- Remaining risk: shared UID/filesystem (S03), ancestor paths and host mounts are
  not isolated by fd-safe chmod. No claim of complete filesystem isolation.

### S03 — All jobs share a writable sandbox identity and filesystem

**High · CONFIRMED in disposable Linux · OPEN; production overlap UNVERIFIED.**

- References: `grader.py:452`, `grader.py:469`, `grader.py:779`.
  Evidence: one `nobody`/`nogroup` identity; workspace mode 0700, source 0600,
  owned by that same identity for every job. No job mount or PID namespace.
- Safe verification: a synthetic playground program read **and overwrote** a
  second synthetic job's source in a different workspace. Both booleans true;
  no victim/user source was used. Directory mode 0700 cannot separate equal UIDs.
- Impact: source theft/tampering, false verdicts, contest cheating and corruption
  of plagiarism evidence while workspaces coexist. Shared UID also permits
  signals/ptrace subject to kernel restrictions. One worker reduces concurrency,
  but does not establish a filesystem security boundary.
- Minimum remediation: allocated per-job identities with safe lifecycle/reuse,
  or an actual per-job filesystem boundary exposing only needed toolchain and
  workspace. Keep the current engine/API. Test simultaneous synthetic jobs for
  read/write/signal denial before allowing concurrency.
- Regression status: successful bounded diagnostic, no isolation fix claimed.
  Existing compiler-private canary tests cannot detect same-UID victim access.
- Related: RLIMIT_NPROC=64 counts the shared UID, not one submission. Cross-job
  fork/setuid failures and innocent RE/job errors are **LIKELY** under contention;
  no fork bomb was run. Per-job pids/cgroup accounting and identities are required.

### S04 — Resource budget excludes descendants and Python allowance

**High · CONFIRMED accounting flaws; production OOM LIKELY · OPEN.**

- References: `grader.py:655`, `grader.py:744`, `grader.py:779`,
  `server.py:173` (`_derive_capacity`), `server.py:2392` (`_effective`).
  Short evidence: sampler reads `/proc/<main>/status`; memory rlimits apply
  per-process; Python RSS allowance is 2.5× plus 64 MB virtual headroom.
- Bounded test with two children: declared 64 MB, Python threshold 160 MB,
  reported parent 21.9 MB, aggregate 181.6 MB, return code 0, over-limit false.
  No OOM/fork bomb was induced. RLIMIT_AS is an **address-space ceiling, not RSS**.
- Production reports a 256 MB cap on a 512 MB container: Python threshold is
  640 MB and virtual ceiling 704 MB, while scheduler budget is 320 MB/job plus
  170 MB reserve. A single program can outgrow the container before user-space
  RSS enforcement fires. Actual production OOM/restart is not proven.
- FSIZE=64 MB limits one file, not total workspace size. No job filesystem quota
  or job cgroup controller is configured in the repository. Failed setrlimit
  calls are also swallowed, so effective limits need host verification.
- Minimum fix: budget actual language/runtime ceilings, compile memory and API
  reserve; enforce descendant memory/pids/CPU and workspace bytes in a per-job
  kernel boundary. A tree sampler alone is not a hard aggregate limit.
- Regression status: diagnostic demonstrates missing accounting; containment
  remains open. Existing threshold tests pass but exercise principally one process.

### S05 — Password signup can pre-hijack a future Google identity

**High · CONFIRMED synthetic flow · OPEN; Google verification partially fixed.**

- References: `server.py:1901` (signup), `server.py:1937` (password login),
  `server.py:1550` (Google profile), `server.py:3013` (email ownership check).
  Evidence: signup immediately sets `session.user.email` without proof;
  both login methods authorize the same plain email.
- Reproduction starts with **no users row**: attacker registers a synthetic
  victim email; victim's first mocked Google OAuth succeeds; victim creates a
  synthetic private submission; attacker can still password-login and read it
  through owner-gated history. All four observed conditions were true.
  This did not involve a live Google account or production write.
- Impact: identity impersonation, private source access, contest identity and
  multi-account quota bypass. Reserved admin email signup is already blocked;
  this is not a proven admin takeover.
- Partial fix: Google must return `email_verified is True`; added regression
  rejects false, absent and string values. This **does not fix pre-hijacking**.
- Minimum complete fix: prove email ownership before issuing a password identity;
  store verified provider/subject identity and require proof for account linking.
  Plan existing account/session migration before changing ownership semantics.
  Do not silently auto-link accounts by email or strand current users.
- Regression: `tests/test_auth_retention_audit.py:29` passes for provider checking.
  Full identity remediation and migration are not implemented in this patch.

### S06 — Contest policy errors and registration fallback fail open

**High · CONFIRMED synthetic · FIXED locally.**

- References: `server.py:2313`, `server.py:1418`, `server.py:3294`;
  `tests/test_contest_policy_audit.py:32`, `:40`.
- Before: cold/expired cache failure produced empty hidden sets; missing
  registration table returned false once then true on subsequent checks.
  Partial contest pagination errors returned only the earlier pages.
- Impact: expose contest-only metadata/samples or allow unregistered submissions
  during a database outage/schema mismatch.
- Fix: transient policy failures return 503, partial/over-budget scans fail,
  registration lookup never becomes an allow-all gate. A genuinely absent legacy
  contests table is treated as no contests; it cannot contain protected contests.
- Verification: synthetic outage and repeated missing-table checks failed before
  and pass after. Normal contest lifecycle tests remain in the full suite.
- Remaining risk: bounded 20 s policy cache; registration-table failure flag needs
  process restart after schema repair; production migration/availability unknown.

### S07 — Body parsing before bounds, with vulnerable parser versions

**High · CONFIRMED repository/test dependency exposure · FIXED locally;
production installed versions UNVERIFIED.**

- References: `requirements.txt:1`, `server.py:262`, `server.py:2801`,
  `functions/api/[[proxy]].js:35`; `tests/test_request_boundaries.py:14`, `:33`.
  Before: FastAPI multipart parser ran before the 256 KB source check;
  JSON endpoints had no raw body cap; proxy streamed arbitrary body sizes.
- Baseline resolved Starlette 0.46.2 and python-multipart 0.0.20. `pip-audit`
  reported **13 distinct advisory IDs in these two packages** (26 records due
  to duplicate dependency entries), including parser CPU/memory denial of service.
  Not every advisory is applicable: arbitrary upload-write configuration is not
  enabled here. No arbitrary file write/RCE or production version is asserted.
- Fix: tested FastAPI 0.143.3, Starlette 1.8.0, multipart 0.0.32; pure ASGI 1 MiB
  raw API write-body cap before parsing (actual chunk bytes, not just header).
  Invalid/non-object JSON returns 400. CI now audits pinned requirements.
- Verification: chunked oversize and declared-size requests return 413 before
  parser; valid requests unchanged. Updated requirements audit reports no known
  vulnerabilities. Full tests include form/file APIs and authentication.
- Residual: slow clients, total concurrent connections and host ingress limits
  still need operational controls; a per-request cap is not a global memory cap.
  TestClient emits an httpx deprecation warning; tests still execute, no silencing.

### S08 — Anonymous submit resolves hidden test storage before login

**Medium · CONFIRMED synthetic · FIXED locally.**

- References: `server.py:2801`, `_problem_or_404` at `server.py:2223`;
  `tests/test_request_boundaries.py:52`.
- Baseline anonymous request returned 401 **after** invoking full problem lookup.
  In Supabase mode it can start private Storage downloads and occupy worker threads.
  This demonstrates unnecessary work, not a returned hidden input.
- Fix: authenticate first, resolve metadata, authorize visibility, then load full
  tests. Regression asserts both lookup and metadata refresh are never called
  for an anonymous submit. Remaining rate-limit and Storage byte-budget risks
  are documented separately; ordinary public statements remain accessible.

### S09 — OAuth handoff secrets in access targets; process-local replay state

**Medium · CONFIRMED logging path/config; production log retention UNVERIFIED ·
PARTIALLY FIXED locally.**

- References: `server.py:65`, `server.py:1601`, `server.py:1627`,
  `container_entrypoint.py:27`; `tests/test_auth_retention_audit.py:18`, `:65`.
- Handoff bearer lasts 300 s and travels in `/api/auth/finish?token=...`;
  Uvicorn defaults to access logging full request targets. A synthetic LogRecord
  contained its synthetic bearer before filtering. No real logs/tokens were read.
- Impact: a log reader can attempt first use within the short validity window.
  Replay dictionary is process-local: another replica/restart can accept a used
  valid token. Current single-process deployment reduces, but does not eliminate,
  restart/rollout replay. Cross-replica production exploitation not attempted.
- Fix: remove auth query strings from Uvicorn access records, serialize JTI use
  with a lock, expire stale entries and refuse at capacity instead of evicting
  valid replay entries. Tests check no synthetic credentials in formatted records
  and exactly one success among 32 concurrent handoffs.
- Remaining minimum fix: redact auth query values at every reverse proxy/log
  collector; use shared atomic replay state before replicas. Filter covers this
  Uvicorn format, not arbitrary third-party logs or redirect Location headers.

### S10 — Stolen signed cookies survive browser logout

**Low–Medium · CONFIRMED stateless design · OPEN.**

- References: `server.py:1541` (SessionMiddleware), `server.py:1698` (logout),
  remember-token helpers in `server.py:1502`.
  Short evidence: logout clears session/browser cookies; no server revocation row.
- Signed session contains readable JSON, not encryption or an opaque hashed
  session token. Session age 30 days, opt-in remember age 365 days. Cookies have
  HttpOnly, Secure by default, SameSite=Lax, Path=/, no Domain.
- Impact requires possession of a valid stolen cookie; browser logout cannot
  revoke a copied cookie. This is separate from the handoff access-log finding.
- Verification: existing cookie tests prove browser deletion, tamper rejection
  and flags, not server revocation. Code review confirms no revocation lookup.
- Minimum fix: server-side session version/revocation for account changes and
  incident response; choose shorter lifetime if acceptable. Session-secret
  rotation is a global emergency logout, requiring operator approval.
- Residual: identity trust (S05) and upstream TLS/cookie configuration.

### S11 — Verdict/time feedback remains a hidden-data oracle

**Medium · CONFIRMED feedback surface; extent of extraction UNVERIFIED · OPEN.**

- References: `server.py:608`, `server.py:1336`, `server.py:2404`;
  `grader.py:1058`. Engine and storage suppress hidden stderr/WA contents, while
  verdict and resource figures remain visible per test. Reveal modes are
  `none`, `samples` (default), `all` (admin response); stored results never gain
  admin-only hidden diagnostics.
- An adaptive program can make success/failure depend on a predicate of stdin.
  Repeated submissions may distinguish hidden inputs without returning stderr.
  No mathematical extraction bound or full dataset recovery is claimed.
- Minimum mitigation: explicit per-identity **per-problem query budget** during
  contests, coarser feedback where policy permits, and anomaly review. Identity
  verification must precede treating account quotas as robust (S05).
- Regression: existing hidden stderr/WA canaries run on API/job/history/storage
  boundaries; no real hidden-input attack was run. Anti-oracle policy is not
  added as an unrelated product feature in this patch.

## Additional finding from final boundary review

### S12 — Public stats bypass problem visibility even after closing Data API

**Medium · CONFIRMED synthetic · FIXED locally.**

- References: `server.py:3199`, `server.py:3211`;
  `tests/test_contest_policy_audit.py:79` stats-cache regression.
  Evidence: `/api/stats` returned all service-role aggregates with no publication
  or contest visibility filter, including a synthetic unpublished/deleted slug.
- Cause: an anonymous endpoint exposed the internal aggregate cache directly.
  Revoking anon SQL privileges alone cannot fix a privileged backend response.
- Impact: private problem identifiers and practice statistics remain discoverable
  through the API. No hidden test bytes or source were returned in this test.
- Fix: refresh metadata, enforce current public visibility on every response,
  including cache hits, and exclude unknown/deleted problem IDs. Legitimate
  published stats are retained; policy failures refuse access.
- Verification: regression failed before fix, checks both hidden denial and
  visible success against the same cached aggregate object.
- Remaining risk: documented metadata/policy/edge cache staleness. Existing edge
  responses can retain previously public data for their TTL; revocation requiring
  immediate erasure needs approved cache invalidation.

## Additional boundary checks

- **NOT AN ISSUE in tested Linux/root scope:** current compiler/assembler/linker
  run after setgroups → setgid → setuid with no_new_privs; failures refuse exec.
  Root-private 0600 include/incbin canaries are denied. Current F1 is not direct
  compiler RCE. Public/world-readable mounted files can still be read (S03).
- **UNVERIFIED production network isolation:** `server.py:723`/`:758` demands
  strict namespace mode or explicit unisolated acknowledgement on Linux/root.
  Both flags default false. Strict failure refuses worker boot and execution;
  acknowledged mode permits execution without netns. Compiler intentionally
  uses `network=False`; runtime calls `unshare(CLONE_NEWNET)` before UID drop.
  Direct unshare requires CAP_SYS_ADMIN in the relevant user namespace. The repo
  does not grant it or privileged mode; do not add broad capabilities as a fix.
  A healthy combined role does not prove which external configuration is used.
- **Supabase hidden path:** `problem_store.py:371`/`:425` downloads bytes into
  memory/LRU, not a hidden-test disk cache; expected values remain in the trusted
  root runner, while executed user code is a separate UID/process. Linux `/proc`
  mem/environ access depends on credential/ptrace/hidepid rules. In the disposable
  packaged Linux image, UID 65534 received PermissionError opening both parent
  `mem` and `environ`, with ptrace_scope=1 (no contents read). This is not production
  kernel evidence. Actual host ptrace/mount rules remain unverified.
- **Local hidden path:** `grader.py:276` reads `problems/<id>/tests/*`. Such files
  leak directly if mounted readable by the shared UID. Production currently
  reports Supabase, and Dockerfile:12 does not copy problems, examples or `.env`.
  Host macOS file modes are not production evidence. Actual production mounts,
  secret files/owners/modes and `/app/.env` presence remain UNVERIFIED.
- Service-role credentials reside in the trusted backend/worker process. The
  isolated judge subprocess receives `_runner_env` (`judge_runner.py:281`), an
  allowlist with RUNNER_CHILD set; it does not inherit service-role/OAuth/session
  credentials or load `.env`. Compiler/runtime use `judge_env` (`grader.py:880`)
  too. Trusted configuration names include SUPABASE_KEY, SESSION_SECRET and
  GOOGLE_CLIENT_SECRET.
  Neither env-value dumping nor production secret-file reads were performed.
- **NOT AN ISSUE within covered boundaries:** ID-based history/job ownership,
  admin-only rejudge/reports/plagiarism, CSRF rejection when both Origin and
  Referer are missing with a session cookie, forwarded-header rejection for
  untrusted peers, atomic local admission and database queue fencing. These
  checks **depend on trustworthy authenticated identity** (S05); passing them
  does not repair pre-hijacking.
- Production queue RPC EXECUTE was denied for anon/authenticated. RLS enabled
  with no policies on server-only tables is intentional deny-default. Reports
  RLS was already enabled in production, although absent in the old repo schema.
  Private `judge-assets` bucket metadata was verified; object ACL drift still
  needs ongoing checks.
- Password review: PBKDF2-HMAC-SHA256, 210,000 iterations, random 16-byte salt,
  constant-time hash comparison (`server.py:1861`). Password login uses a dummy
  derivation for unknown accounts; signup still returns an explicit 409 for an
  existing address, so timing mitigation does not prevent registration
  enumeration. Limits are in-memory per IP/account; replica-wide enforcement is
  unverified. Email normalization is strip/lower in both login flows/admin checks,
  not an ownership proof or a complete Unicode/canonical-email identity policy.
- No confirmed frontend XSS, SQL injection or command-shell construction was
  found in reviewed paths. This is limited negative evidence, not proof of absence.
  The Pages static header file lacks the API's CSP/security headers (P2).

## Reproducible searches and external sources

Run from the repository root; exit 1 from a grep with no matches is expected.

```sh
rg -n 'shell\s*=\s*True|os\.system\(|os\.popen\(|create_subprocess_shell' grader.py server.py judge_runner.py problem_store.py worker.py container_entrypoint.py
# No matches in the audited execution/API modules. Popen uses argument lists.
rg -n 'createClient|supabase' static --glob '*.js' --glob '*.html'
# Only two UI setup-hint strings (app.js:2303,2523); no Supabase client construction.
rg -n 'content-length|body|MAX|limit|413' 'functions/api/[[proxy]].js'
# Streaming/header handling only; full file read found no explicit body-size guard.
rg -n 'seccomp|chroot|pivot_root|CLONE_NEW|setuid|setgid|setgroups|prctl|RLIMIT_' grader.py judge_runner.py Dockerfile container_entrypoint.py
git log --all --oneline -S'service_role'
git log --all --oneline -- '*.env' '.env*'
# History searches emit commit metadata, never matching file contents.
# These searches are not a complete historical secret scan.
```

Owner-rights/invoker behavior is documented by
[Supabase RLS](https://supabase.com/docs/guides/database/postgres/row-level-security)
and [view advisor](https://supabase.github.io/splinter/0010_security_definer_view/).
Applicable parser advisories include maintainer reports for
[multipart headers](https://github.com/Kludex/python-multipart/security/advisories/GHSA-pp6c-gr5w-3c5g),
[Starlette form limits](https://github.com/Kludex/starlette/security/advisories/GHSA-82w8-qh3p-5jfq)
and [file rollover](https://github.com/Kludex/starlette/security/advisories/GHSA-2c2j-9gv5-cj73).
