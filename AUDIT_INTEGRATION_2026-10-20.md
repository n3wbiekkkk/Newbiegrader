# Audit integration and release-readiness report — 2026-10-20

> **Historical integration snapshot.** This file records the state at `8a0cd24`.
> The authoritative, final evidence and gate status are in
> `RELEASE_VALIDATION_REPORT.md`; later compatibility, retention, A05, CI, and
> remediation work is not reflected below.

## Scope and safety

- Base: `origin/main` at `4a88796` (the fetched upstream baseline).
- Integration worktree: `/Users/phetpitaksukprasert/Developer/grader-security-integration`
- Local branch: `security/integrate-audit-fixes`, 11 commits ahead of `origin/main`.
- No push, merge, deploy, force-push, or shared-history rewrite, and no production/AWS/Cloudflare/Supabase change, was performed. One local unpushed commit message was amended before testing; its tree was unchanged.
- The shared main worktree and the old audit worktree were not modified, reset, cleaned, or stashed.
- `problems/` and `examples/` were copied only as gitignored local test fixtures.

Final HEAD: `8a0cd24`  
Production status: **not deployed**. This report is evidence for review, not a deployment record.

## Verdict

**Code-level integration: PASS for A01–A07 on the tests and Linux container checks below.**  
**Production readiness: CONDITIONALLY READY FOR MERGE REVIEW / CANARY — NOT YET DEPLOYED OR PROVEN ON THE PRODUCTION HOST.**

The remaining gates are outside this local branch: remote CI, a production-like Linux host run, schema application by the maintainer, and a canary with rollback. macOS-only results were not used as a production claim; a Linux/root critical gate was run separately.

## Findings, status, and commits

| ID | Finding at base `4a88796` | Final action | Commit(s) |
|---|---|---|---|
| A01 | Submission insert retried any error containing “column”, so a NOT NULL/integrity error silently dropped `tests_hash`, `grader_version`, `kind`, `contest_id`, and `job_id`. A contest submission could be persisted as practice data. | Retry only on explicit missing-column signals (`42703`, `PGRST204`, `undefined_column`, or “column” plus “does not exist”/“could not find”). Integrity, network, and timeout errors are not retried. | `a5bdc4b` |
| A02 | Cgroup-root invariant test read real `/proc/self/status` under a patched `sys.platform`; it errored off Linux and could pass vacuously as an unprivileged user via the capability branch. | Stub the supervisor capability read and assert the delegated-manager branch. | `5becf9b` |
| A03 | The non-root cgroup test depended on another module’s `SESSION_SECRET` import side effect. | Set an explicit synthetic `SESSION_SECRET` in the test environment. | `5becf9b` |
| A04 | Admin rejudge used the requester’s `REVEAL_ALL` policy; storage folded it to samples. Local mode retained the requester-privileged result. History and job polls replayed stale/static policy. Rejudge also failed open for contest-free rows and unknown contests. | Rejudge uses the submission owner’s policy; local records keep the redacted stored variant; terminal job polls and history reads re-evaluate the live owner policy; contest-free rejudges use live practice policy; unknown/unavailable contests fail closed to `REVEAL_NONE`. | `34387e3`, `3b6bccb`, `b097d4e`, `4a87f20`, `8a0cd24` |
| A05 | `build_limits` applied `RLIMIT_NPROC=64` on every platform. Off Linux there is no UID drop, so a shared login session at ≥64 processes made every compiler-style spawn fail `EAGAIN` (bogus CE). | Keep the process ceiling on Linux (where production drops to a sandbox UID); leave the host limit elsewhere. The Linux-pinned expectation remains 64. | `4a13bcd` |
| A06 | Stale test expected an admission-time 500 when Storage bytes were missing; the current design deliberately admits metadata and fails the claimed job on the worker. | Test now asserts the queued job ends `status=error` with “unavailable”, never a verdict. No production code change. | `6c816b3` |
| A07 | `spawn-fail` was scored as RE; compiler spawn failures became CE; supervisor handshake/pid/prctl failures escaped as exit 1; unexpected supervisor exceptions had no fail-closed mapping. | Emit `GRADER_SPAWN_FAILED`/127 for supervisor setup and Popen failures; map it to `spawn-fail`; raise `SandboxUnavailable` instead of a verdict; map compile spawn failures to `SandboxUnavailable`; add a top-level supervisor safety net. | `d424233`, `564b158` |

A01, A02/A03, A05, and A07 were still missing at the new base and were re-integrated from behavior and patch content, not by blindly picking old commits. A04’s original fix was present only as a patch reference; the new storage/queue architecture and additional read paths required a fresh, expanded implementation. A06 was a test-only correction.

## Confirmed regressions added

- A01: `tests/test_audit_integrity.py::SubmissionStoreRetry`
  - integrity error mentioning a column is not retried;
  - missing-column error still retries without traceability columns;
  - missing relation is not treated as a missing column.
- A04: `tests/test_contest_policy_audit.py` (16 tests, 10 new)
  - admin rejudge keeps the owner’s policy;
  - local rejudge job never hands the owner hidden data;
  - live hidden contest hides previously stored samples on history reads;
  - live hidden contest hides stored job feedback on polls;
  - live hidden contest hides a practice row whose problem later enters the contest;
  - admin owner keeps the documented admin policy;
  - admin viewing another user’s row uses the owner’s policy, not the viewer’s;
  - practice rejudge inside a live hidden contest uses `REVEAL_NONE`;
  - unknown contest fails closed;
  - practice rejudge outside a contest keeps `REVEAL_PRACTICE`.
- A05: `tests/test_judge_runner.py::test_shared_uid_keeps_its_host_process_ceiling_off_linux`
  - reproduced the real two-level compiler-style spawn failure: `BlockingIOError: [Errno 35] Resource temporarily unavailable`;
  - passes after the fix; Linux `NPROC=64` is still pinned separately.
- A06: `tests/test_problems_supabase.py::test_detail_and_sample_need_no_storage`
  - storage bytes gone: submission is accepted for admission, then the job ends as an error, never Accepted.
- A07: `tests/test_audit_integrity.py::SpawnFailureIsNeverAVerdict` (8 tests) and the redaction canary
  - marker/RC synchronization;
  - end-to-end unspawnable wrapper;
  - `run_one` mapping;
  - `judge_test` refusal;
  - supervisor pid-write and handshake failures;
  - compile marker and compile OSError, neither CE nor a verdict;
  - redaction canary asserts no user data leaks through an environment error.

Each fix was added after a focused failing regression where applicable, then the related module and full suites were rerun.

## Verification evidence

### Python / integration suites

| Environment | Result |
|---|---|
| macOS host (Python 3.12.15, macOS arm64) | **387 tests, OK, 18 skipped** |
| Linux container, unprivileged user (`python:3.11-slim`, Debian-based, aarch64 under Colima) | **387 tests, OK, 13 skipped** |
| Linux container, root, CI critical gate (`tools/run_critical_tests.py`, `GRADER_RUNNER_CHILD=1`, `GRADER_REQUIRE_NETNS=0`, `GRADER_ALLOW_UNISOLATED_JUDGE=1`) | **253 tests, 0 skips, `[CRITICAL-PASS]`** |

The Linux/root gate executed real kernel/privilege paths, including compiler UID drop, Landlock, seccomp/network filtering, per-job identity separation, file-access boundaries, resource setup, subreaper/deadline/descendant cleanup, queue, and the new A01/A04/A05/A07 regressions. It is not a substitute for the production host.

The gate ran with `GRADER_REQUIRE_NETNS=0` and `GRADER_ALLOW_UNISOLATED_JUDGE=1` because the Colima/Docker VM cannot supply the production namespace/privilege posture. It therefore does **not** prove strict network-namespace startup or host-level isolation; those remain production-host checks. The seccomp filtering itself was exercised.

### Skipped tests

macOS (18):
- `CriticalCompilerRoot`, `CriticalJobIdentity`, `CriticalNetworkExecution`, `CriticalResourceSetup` setUpClass suites;
- API UID/private-blob and compiler private-blob checks;
- resolved-parent/replaced-binary/replaced-workspace chmod checks;
- byte-ledger reuse/merge/symlink checks;
- `owner_death_terminates_the_owned_job`;
- `sandbox_preserves_memory_and_process_limits`;
- `strict_netns_refuses_without_namespace`;
- cancellation, hard-deadline, and orphan-descendant cleanup checks.

Linux unprivileged (13): the same root-only set minus the five Linux-runnable process/resource tests, which ran and passed.

All 13 Linux-unprivileged skips were executed and passed in the root critical container. They were **not** counted as passed on macOS; the container result is separately labeled.

### PostgreSQL queue, RLS, and auth

Local disposable PostgreSQL 17 container, database `newbiegrader_test`:

- schema applied twice (idempotence) — exit 0;
- `tests/queue_sql.sql` — exit 0;
- `tests/security_sql.sql` — exit 0;
- `tests/auth_sql.sql` — exit 0;
- `tests/queue_concurrency.py`:
  - 4 admissions, 8 claim clients, 4 distinct claims;
  - expired lease recovered;
  - stale finish rejected;
  - duplicate finish idempotent;
  - 0 submission rows.
- `tests/auth_concurrency.py`:
  - 8 budget clients, 1 allowed send;
  - 8 Google claim clients, 1 identity row;
  - auth version 1.

This validates the durable queue’s duplicate/lease/idempotency behavior and the auth budget/identity constraints against a real PostgreSQL instance, not the fake Supabase test double.

### Static and non-Python checks

- `python -m compileall -q ...` — OK.
- `node --check static/app.js` — OK.
- `node tools/check_frontend.js` — OK (159 IDs, 17 icons, 25 symbols).
- `node tools/check_styles.js` — OK (86 tokens, 46 dark overrides).
- `node --test tests/test_*.js` — 76/76 OK.
- `unittest` problem-authoring suite — 18/18 OK.
- `tools/plagiarism.py` self-test — 4/4 OK.
- `tools/validate_problem.py` — all 68 problem packages OK.

`pip-audit` was not rerun locally. `requirements.txt` was not changed; the repository CI `validate` job runs `pip-audit -r requirements.txt`.

## Adversarial second pass

Reviewed and tested alternate read/authorization paths, not only the original patch:

- **Alternate authorization:** job poll and history detail use the submission owner, never the requester; an admin viewing another user’s live-hidden row is restricted by the owner’s policy; admin owners retain the documented admin feedback policy.
- **Unredacted responses:** stored rows, local `_jobs` records, terminal polls, history detail, and environment-error text were checked. Environment errors remain generic (`execution environment unavailable` / `compiler could not be started`), not verdicts.
- **Stale cache/policy:** live disclosure decisions bypass the 20-second contest cache and fail closed to `REVEAL_NONE` on policy outage. Job/list caches and public filters were covered by the full contest suite.
- **Queue duplication:** real PostgreSQL concurrency proved one claim per job, lease recovery, stale-finish rejection, and idempotent repeat finish.
- **Partial writes:** A01 prevents integrity errors from triggering a provenance-dropping retry; queue finish is transactional/idempotent; failed judging does not create a submission row.
- **Races:** concurrent claims and finishes were exercised. A known operational limitation remains: two simultaneous admin rejudges of the same submission can race and the last completion wins; this is admin-triggered and does not bypass authorization.
- **Fallback/fail-open:** rejudge contest lookup and practice policy now fail closed; missing judge runner/compiler spawn never becomes CE/RE. A01’s legacy missing-column fallback remains intentionally limited to explicit missing-column errors.
- **New issues found in this pass and fixed:** stale contest policy on job polls/history; stale practice policy on rejudge; unknown-contest rejudge fallback; compile spawn failure classified CE; supervisor setup/handshake failures classified RE.

## Residual risks and open items

1. **A05 on non-root Linux:** the Linux ceiling is still `RLIMIT_NPROC=64`. It is correct for the production root + sandbox-UID model; a non-root Linux deployment with a shared judge UID can still hit compiler `EAGAIN`. The production runbook must confirm the root/identity-drop posture.
2. **A04 historical rows:** rows written before this fix are not migrated or deleted. Read paths now re-evaluate live policy, so a live `show_samples=false` contest hides stored samples; after the contest ends, stored sample feedback is ordinary history. A permanent purge requires a data-policy decision/migration.
3. **A04 policy read cost:** terminal job polls and history details now perform a fresh contest-policy read to avoid stale disclosure. Availability is fail-closed, but latency/DB load should be observed in canary.
4. **A01 legacy updates:** the insert retry has a pre-migration fallback; the rejudge update path does not. On a genuinely old schema a rejudge update can fail (no silent provenance loss), so legacy-schema support remains a compatibility decision.
5. **A07 marker spoofing:** a submission can print `GRADER_SPAWN_FAILED` and exit 127 to force a job-level error. This is self-denial, not an Accepted/score bypass.
6. **Production-host isolation is unproven:** the root critical gate ran in a Docker container on Colima, not the production EC2 kernel/systemd/cgroup delegation, and it used `GRADER_REQUIRE_NETNS=0`/`GRADER_ALLOW_UNISOLATED_JUDGE=1`. Strict netns posture remains a production-host check. The CI `critical-security` job and a production-like host smoke remain required.
7. **Out of A01–A07 scope:** prior residuals S04 (per-test descendant memory accounting), S10 (cross-device logout revocation), and S11 (anti-oracle feedback policy) remain open product/operations decisions.
8. **No production release identity:** no artifact was built, no schema applied, no AWS/Cloudflare/Supabase change, and no production smoke/load test was run.

## Non-executed release plan

1. Review and approve the 11 local commits on `security/integrate-audit-fixes`; push/PR only with authorization.
2. Run repository CI on the PR: `validate`, Python 3.11 tests, `pip-audit`, problem validation, JS tests, SQL jobs, and the root `critical-security` gate. Require 0 failures and 0 critical skips.
3. Build the release artifact and record the commit SHA, build hash, dependency audit, and configuration.
4. Stage on a production-like Linux host. Verify root + sandbox UID drop, cgroup delegation (`Delegate=cpu memory pids`, `DelegateSubgroup=manager`), Landlock/seccomp/netns posture, `NPROC=64` behavior, compiler isolation, and the UID ledger.
5. Apply the idempotent `supabase/schema.sql` changes through the maintainer’s SQL Editor; verify columns, queue RPCs, RLS, and Auth claims.
6. Canary one worker. Exercise Python/C++ AC/CE/WA/TLE, hidden redaction, a live `show_samples=false` admin rejudge, job polling, history detail, queue crash/lease recovery, and duplicate finish. Monitor `GRADER_SPAWN_FAILED`, job errors, lease expiry, and policy-read latency.
7. Rollback: remove `/etc/newbiegrader/worker-enabled` to disable the worker, restore the previous release SHA/service, and keep the forward-only schema; do not destructively roll back database changes.
8. Record post-deploy evidence before scaling workers. Do not declare production-ready until the host-level gate and canary pass.

## Commit map

```
8a0cd24 Backend: fail closed when rejudge policy lookup is unavailable
4a87f20 Backend: read stored feedback with the submission owner's contest policy
b097d4e Backend: re-evaluate live feedback policy on job polls
3b6bccb Backend: re-check live contest policy when reading stored feedback
564b158 Grader: close the remaining spawn-failure verdict paths
6c816b3 Tests: assert worker-side fail-closed for missing private bytes
5becf9b Tests: make critical cgroup invariants deterministic off-host
4a13bcd Grader: keep the host process ceiling off Linux
a5bdc4b Backend: retry submission insert only for missing-column errors
d424233 Grader: never score an infrastructure spawn failure
34387e3 Backend: store rejudge feedback at the submission's policy
```

Diff: 9 files, +596/−42 (production code in `server.py`, `grader.py`, `judge_runner.py`; regression tests in six test files).
