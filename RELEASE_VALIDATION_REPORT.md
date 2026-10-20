# Release validation report — 2026-10-20

## Verdict

**Code-level integration: PASS for A01–A07 on the tested environments.** The
focused regressions, full macOS suite, unprivileged Linux suite, root critical
gate, database fixtures, static/frontend checks, and dependency audit are clean.
One independent package gate is **not clean**: `tools/validate_problem.py`
reports 64/68 because four reference solutions are TLE-sensitive on this host.
A disposable `origin/main` comparison reproduced the same class of failures, so
this is recorded as a pre-existing package/performance limitation, not silently
treated as a pass. No problem limits or statements were changed.

**Production readiness: NOT DEMONSTRATED. HOLD before deployment.** This report
does not claim that macOS results or a containerized Linux run prove the
production host. Remote CI, a production-like Linux host smoke, the maintainer’s
schema application, and a canary/rollback exercise remain outstanding. Nothing
was pushed, merged, deployed, or changed in AWS, Cloudflare, Supabase, or the
shared worktree.

## Baseline and scope

- Repository: `/Users/phetpitaksukprasert/Developer/grader`
- Validation worktree:
  `/Users/phetpitaksukprasert/Developer/grader-security-integration`
- Branch: `security/integrate-audit-fixes`
- Base: `origin/main` `4a88796` (fetched again during validation; unchanged)
- Final tested code HEAD: `06ad8a4` (this report and its evidence were committed locally after it)
- Base comparison archive: disposable `origin/main` checkout at `4a88796`
- Local commits only, no push, merge, force-push, or shared-history rewrite.
- The shared main worktree and older audit worktree were left untouched.
- `problems/` and `examples/` were copied only as gitignored local test fixtures;
  hidden tests and source are not included in this report.

## Integrated changes

| ID | Change | Status |
|---|---|---|
| A01 | Missing-column retry cannot downgrade a contest submission; practice rows still use the legacy fallback. Rejudge UPDATE fallback remains a compatibility limitation. | Verified by focused tests and pre-migration E2E |
| A02/A03 | Critical cgroup test is deterministic off-host; non-root test supplies its own synthetic session secret. | Test-only; root gate and full suites pass |
| A04 | Rejudge policy follows the submission owner; live history/job reads re-evaluate policy; unknown/failed policy fails closed; sample bytes bypass the stale policy cache. | Verified by focused tests, root gate, and synthetic history fixtures |
| A05 | `RLIMIT_NPROC=64` applies only to the Linux root/unique UID drop model; shared-UID non-root runs keep the host ceiling. | Verified by root and unprivileged Linux regressions |
| A06 | Missing private bytes fail the claimed job as an error, never a verdict. | Test-only correction; full suites pass |
| A07 | Compile/supervisor spawn and setup failures map to environment errors, never CE/RE; playground uses the same fail-closed mapping. | Verified by focused/root tests |
| Retention | Completed database jobs clear source and payload; local terminal jobs clear source. | PostgreSQL SQL regression added |

## Verification evidence

### Python suites

| Environment | Command | Result |
|---|---|---|
| macOS arm64, Python 3.12.15 | `python -m unittest discover -s tests -v` | **392 tests, OK, 20 skipped** |
| Linux container, unprivileged UID 65534 | same suite in `python:3.11-slim` (Debian aarch64 under Colima) | **392 tests, OK, 14 skipped** |
| Linux container, root critical canaries | `python tools/run_critical_tests.py` with `GRADER_RUNNER_CHILD=1`, `GRADER_REQUIRE_NETNS=0`, `GRADER_ALLOW_UNISOLATED_JUDGE=1` | **258 tests, OK, 0 skips** |
| PostgreSQL 17 | schema/queue/security/auth/concurrency and legacy upgrade fixtures | **PASS** (details below) |

The macOS skips are listed in `RELEASE_VALIDATION_PROGRESS.md`; they are not
counted as passes. The root gate is reported separately and is the only local
evidence for the real Linux UID/GID, cgroup, Landlock, seccomp, and supervisor
paths. The unprivileged Linux run is not a sandbox-boundary proof.

### A01 regressions

- `tests/test_audit_integrity.py::SubmissionStoreRetry`: **16/16 OK**.
  - integrity error mentioning a column is not retried;
  - missing non-contest column retries while preserving a contest row’s
    `contest_id`;
  - missing `contest_id` on a contest row refuses the fallback;
  - missing `contest_id` on a practice row still stores;
  - missing relation is not mistaken for a missing column.
- `tests/test_api_e2e.py::PreMigrationFallback`: **4/4 OK**. The old schema
  stores a practice submission and the aggregate fallback works.
- Residual: the rejudge UPDATE path has no legacy missing-column retry. That is
  fail-safe (no silent provenance downgrade), but a genuinely old schema may
  fail a rejudge update.

### A04 contest disclosure and history

- `tests/test_contest_policy_audit.py`: focused suite passed; the earlier run
  was **17/17 OK**, and the final root gate includes the same module.
- Covered paths: admin rejudge owner policy, local job record redaction, live
  history redaction, live job-poll redaction, practice rows made contest-only,
  admin-owner behavior, admin viewer of another owner, missing contest,
  practice rejudge, stale 20-second sample cache, and sample route fail-closed.
- Synthetic history fixture (`newbiegrader_history_audit`):
  `feedback_history_inspection.sql` flagged three deliberately over-disclosed
  rows: `ended-hidden`, `live-hidden`, and `missing-contest` (one result object
  each). It also listed the live-hidden row and the missing-contest row in the
  targeted follow-up sections.
- `feedback_history_remediation.sql` synthetic test: target-only redaction
  preserved the current public sample, removed hidden input fields, set
  `hidden: true`, left a non-target row unchanged, and rolled back. The template
  requires explicit target IDs and defaults to `ROLLBACK`.
- Residual: historical rows are not purged automatically. Live reads redact
  them during hidden contests; after a contest ends, owner-visible practice
  history may intentionally become visible under the product policy. The
  maintainer must decide whether/how to apply remediation to production rows.

### A05 process and UID posture

- Root critical regressions cover: compiler and runtime UID/GID drop, no root
  inheritance, per-job identity ledger, Landlock, seccomp network filter,
  cgroup setup, subreaper/descendant cleanup, and supervisor ownership.
- Non-root Linux regression proves `RLIMIT_NPROC` is left at the host ceiling
  when the sandbox shares the service UID. Compiler-style two-level spawns work.
- Root Linux regression proves the `NPROC=64` installation before identity drop;
  the root gate executes it.
- **Limitation:** the container uses `GRADER_REQUIRE_NETNS=0` and
  `GRADER_ALLOW_UNISOLATED_JUDGE=1`; strict network-namespace startup and the
  production systemd cgroup delegation are not verified. Non-root execution is
  explicitly rlimits-only, not a sandbox.

### A07 infrastructure classification

- `SpawnFailureIsNeverAVerdict` covers marker/RC synchronization, end-to-end
  unspawnable wrapper, `run_one` mapping, and `judge_test` refusal.
- Focused `test_critical_compiler` covers compile marker and compile `OSError`.
- Playground spawn failure returns `execution environment unavailable`, not a
  verdict.
- Root gate includes the compiler/supervisor fail-closed paths.
- Residual: a submission can print `GRADER_SPAWN_FAILED` and exit 127 to force a
  job-level error (self-denial, not an Accepted/score bypass).

### Database, queue, and auth

Disposable PostgreSQL 17 (`ng-pg`), no cloud resources:

- `supabase/schema.sql` applied twice on a clean database: exit 0.
- `tests/queue_sql.sql`: exit 0; completed jobs no longer retain source or
  payload.
- `tests/security_sql.sql`: exit 0.
- `tests/auth_sql.sql`: exit 0.
- Legacy fixture (`tests/legacy_schema.sql`): existing row preserved, schema
  applied twice, `tests/legacy_schema_verify.sql` passed, preflight/verify clean.
- Queue concurrency: 4 admissions, 8 clients, 4 distinct claims, expired lease
  recovered, stale finish rejected, duplicate finish idempotent.
- Auth concurrency: 8 budget clients -> 1 allowed send; 8 Google claim clients
  -> 1 identity row.

### Static, frontend, authoring, dependencies

- Python `compileall`: OK.
- `node --check static/app.js`: OK.
- `node tools/check_frontend.js`: OK (159 ids, 17 icons, 25 symbols).
- `node tools/check_styles.js`: OK (86 tokens, 46 dark overrides).
- `node --test tests/test_*.js`: **76/76 OK**.
- Authoring tests: **18/18 OK**.
- Plagiarism self-test: **4/4 OK**.
- `pip-audit==2.10.1 -r requirements.txt` under Python 3.12: **no known
  vulnerabilities**.
- `tools/validate_problem.py`: **64/68, not clean**. Failures:
  `collatz_max` (1004:TLE; direct reference about 1.04s against a 1.0s limit),
  `exact_budget` (four TLEs; direct reference about 1.21s), `napprime`
  (flaky at 0.5s), and `parking_slots` (1009:TLE; large 6 MB input).
  A disposable `origin/main` archive reproduced `exact_budget`,
  `parking_slots`, and `napprime` failures; `collatz_max` also failed on one of
  two baseline runs. Problem rules, limits, and tests were deliberately not
  changed to make this gate green.
- Package validation is therefore a **known pre-existing performance/TLE
  issue**, not evidence that this integration changed the problem corpus.
- CI YAML parses; top-level `permissions: contents: read`, SHA-pinned checkout
  and setup-python, `persist-credentials: false`, dependency audit, and the
  disposable legacy-schema job are present. Remote CI was not run.

## Unverified production gates

1. Remote CI on a pull request, including the root `critical-security` job.
2. Production-like Linux host with real systemd cgroup delegation
   (`Delegate=cpu memory pids`, `DelegateSubgroup=manager`), strict netns, and
   EC2 kernel behavior.
3. Maintainer application of the idempotent schema, PostgREST cache reload
   (`select pg_notify('pgrst', 'reload schema')`), and migration verification.
4. Canary deployment with one worker and rollback exercise.
5. Production release identity, artifact hash, and current deployed SHA.
6. Production data inspection/remediation decision; no production queries or
   row mutations were performed.

## Canary plan (not executed)

1. Build from the reviewed commit; record SHA, image digest, dependency audit,
   and configuration.
2. Apply `docs/release/schema_preflight.sql`; stop on any missing table/column,
   RLS gap, or unexpected grant.
3. Apply `supabase/schema.sql` with `ON_ERROR_STOP=1`; notify PostgREST; run
   `docs/release/schema_verify.sql`.
4. Start one API instance with the worker disabled; exercise practice and
   contest submissions, history redaction, and the sample route.
5. Run `worker.py --check`; enable one worker. Exercise Python/C++ AC/WA/TLE/CE,
   a live `show_samples=false` contest, admin rejudge, job polling, lease
   recovery, and duplicate finish.
6. Monitor job errors, `GRADER_SPAWN_FAILED`, lease expiry, queue depth, and
   policy-read latency. Expand only after the canary and host isolation checks
   pass.

## Rollback plan

- Disable new claims first (remove the worker-enabled marker / stop the worker
  service) and keep the previous application image available.
- Schema changes are additive; do not drop columns, tables, functions, or
  policies as an ad-hoc rollback. Restore the pre-change snapshot only under the
  approved backup/restore procedure.
- Stop, inspect, and let leases expire before restarting a stuck worker. Never
  delete a `running` job without recording its lease and source state.
- Deploy the previous immutable image. No force-push or shared-history rewrite
  is part of rollback.

## Reproduction commands

```sh
# Focused
PYTHONPATH=.:tests <venv>/bin/python -m unittest test_audit_integrity -v
PYTHONPATH=.:tests <venv>/bin/python -m unittest test_contest_policy_audit -v
PYTHONPATH=.:tests <venv>/bin/python -m unittest test_judge_runner -v

# Full macOS
PYTHONPATH=.:tests <venv>/bin/python -m unittest discover -s tests -v

# Full unprivileged Linux
docker run --rm --name ng-linux-user-final \
  -v "$PWD:/workspace:ro" -w /workspace --user 65534:65534 \
  -e HOME=/tmp -e TMPDIR=/tmp -e PYTHONDONTWRITEBYTECODE=1 \
  -e GRADER_RUNNER_CHILD=1 -e GRADER_PROBLEM_SOURCE=local \
  -e SESSION_SECRET=synthetic-linux-user-secret \
  newbiegrader-audit-tests:20261018 \
  python -m unittest discover -s tests -v

# Root critical gate
docker run --rm --name ng-linux-root \
  -v "$PWD:/workspace:ro" -w /workspace \
  -e PYTHONDONTWRITEBYTECODE=1 -e GRADER_RUNNER_CHILD=1 \
  -e SESSION_SECRET=synthetic-critical-root-secret \
  -e GRADER_REQUIRE_NETNS=0 -e GRADER_ALLOW_UNISOLATED_JUDGE=1 \
  newbiegrader-audit-tests:20261018 python tools/run_critical_tests.py

# Database (disposable only)
psql -X -v ON_ERROR_STOP=1 -f supabase/schema.sql
psql -X -v ON_ERROR_STOP=1 -f supabase/schema.sql
psql -X -v ON_ERROR_STOP=1 -f tests/queue_sql.sql
psql -X -v ON_ERROR_STOP=1 -f tests/security_sql.sql
psql -X -v ON_ERROR_STOP=1 -f tests/auth_sql.sql
```

## Commit map

```text
34387e3 Backend: store rejudge feedback at the submission's policy
d424233 Grader: never score an infrastructure spawn failure
a5bdc4b Backend: retry submission insert only for missing-column errors
4a13bcd Grader: keep the host process ceiling off Linux
5becf9b Tests: make critical cgroup invariants deterministic off-host
6c816b3 Tests: assert worker-side fail-closed for missing private bytes
564b158 Grader: close the remaining spawn-failure verdict paths
3b6bccb Backend: re-check live contest policy when reading stored feedback
b097d4e Backend: re-evaluate live feedback policy on job polls
4a87f20 Backend: read stored feedback with the submission owner's contest policy
8a0cd24 Backend: fail closed when rejudge policy lookup is unavailable
7a5cddf Security: fail closed on live sample and playground spawn policy
ef45b2e Tests: pin kernel memory ceiling check to Linux
01c7fd4 Backend: preserve contest provenance in legacy submission retry
d1e63bd CI: pin actions and verify legacy schema upgrade
59113ad Docs: add release schema and feedback-history checks
9b6c8a9 Security: clear completed judge job source and payload
a64b0f8 Backend: keep practice legacy fallback after protecting contest provenance
705ba3e Grader: scope the process ceiling to the Linux root identity model
f4281fa Docs: add target-specific feedback remediation guidance
d6983f1 Docs: trust current samples when auditing historical feedback
06ad8a4 Tests: exercise the shared-UID branch without a critical skip
1ec0a38 Docs: make the historical remediation template a true no-op
```

## Honest limitations

- macOS and a Dockerized Linux container are not the production EC2 host.
- The unprivileged Linux suite skips root-only tests (14 skips); those are
  executed and reported separately in the 258/0 root gate, not counted as
  macOS/container passes.
- The full macOS/Linux suites ran against the final production code; the last
  test-only decorator adjustment was separately exercised without skips by the
  root gate.
- Historical feedback remediation was validated only against synthetic rows.
- The problem validator is not green: four reference solutions are TLE-sensitive
  on this host, including failures reproduced from `origin/main`. This is a
  release-owner decision, not something this worktree hid by editing limits.
- No remote CI, production schema application, canary, or production smoke was
  run. The maintainer retains the deployment and data-policy decision.
