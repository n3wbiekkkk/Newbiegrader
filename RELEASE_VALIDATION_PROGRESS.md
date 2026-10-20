# Release validation progress — 2026-10-20

> Historical snapshot. See `RELEASE_BLOCKER_PROGRESS.md` for the current release
> ledger and `RELEASE_BLOCKER_REPORT.md` for the final evidence and gate matrix.
> In particular, `origin/main` has advanced since this snapshot and is no longer
> tree-identical.

## Baseline

- Repository: `/Users/phetpitaksukprasert/Developer/grader`
- Validation worktree: `/Users/phetpitaksukprasert/Developer/grader-security-integration`
- Branch: `security/integrate-audit-fixes`
- Final tested code HEAD: `06ad8a4`; this report and its evidence were committed locally after it
- Local commits only; no push, merge, deploy, force-push, or shared-history rewrite
- `origin/main` base: `4a88796`; fetched again during validation and unchanged
- Shared worktree: has unrelated uncommitted WIP; not modified
- Production: not deployed, migrated, or queried for row contents

## Release gates

- [x] Fetch origin and confirm current main compatibility baseline
- [x] Independently re-run and inspect A01–A07 evidence
- [x] A04 contest privacy / historical feedback audit
- [x] A05 Linux shared-UID analysis and production posture
- [x] Database schema/migration compatibility (A01)
- [x] Linux sandbox verification (containerized cgroups, seccomp, Landlock, UID)
- [x] Queue/worker recovery and duplicate/idempotency verification
- [x] Full final macOS regression: 392 tests, OK, 20 skipped
- [x] Full final unprivileged Linux regression: 392 tests, OK, 14 skipped
- [x] Root critical gate: 258 tests, 0 skips
- [x] Static/frontend/storage checks
- [x] Dependency audit: no known vulnerabilities
- [!] `validate_problem.py`: 64/68; four TLE-sensitive references, with
  baseline reproduction of the same class of failure. Not treated as a pass.
- [x] CI workflow supply-chain/permission review
- [ ] Strict host netns and production cgroup/systemd verification
- [ ] Remote CI and canary/rollback exercise

## Evidence captured

### A01 submission provenance

- Contest rows are never silently downgraded by the legacy retry. If
  `contest_id` is missing from the schema and the row has contest provenance,
  the insert is refused (job history write fails closed).
- Practice rows with no provenance still use the pre-migration fallback; the
  full macOS regression caught and now covers this case.
- Focused `test_audit_integrity`: 16/16 OK.
- `test_api_e2e.PreMigrationFallback`: 4/4 OK.
- Residual: the rejudge UPDATE path has no equivalent legacy missing-column
  retry. A genuinely old schema can fail a rejudge update; the job must be
  inspected, not silently downgraded.

### A04 contest disclosure

- Live reads of jobs and stored history re-evaluate the owner's contest policy;
  unknown or failed policy lookups fail closed.
- Sample bytes bypass the 20-second cache and use a fresh policy lookup.
- Admin-owner semantics are preserved; an admin viewing another user's row does
  not declassify it.
- Focused `test_contest_policy_audit`: 17/17 OK; the final root critical gate
  includes the same module.
- Synthetic history fixture: `feedback_history_inspection.sql` flagged three
  deliberately over-disclosed rows (`live-hidden`, `ended-hidden`,
  `missing-contest`).
- Synthetic remediation test: target-only redaction removed hidden input,
  preserved the current public sample, left a non-target row untouched, and
  rolled back. The template uses a deliberately false target query and defaults
  to `ROLLBACK`.
- Residual: historical rows are not purged automatically. During a live hidden
  contest, reads redact them; after the contest ends, owner practice history may
  intentionally become visible under the product policy.
- Residual: a genuinely absent `contests` table is treated as legacy “no
  contest policy”; this is intentional compatibility behavior and is covered by
  the pre-migration tests. It means the app cannot infer a contest that has no
  policy storage.

### A07 infrastructure classification

- Compile spawn failures, supervisor setup/handshake/pid-file failures, and
  unexpected supervisor exceptions map to environment errors, never CE/RE.
- Playground run and compile failures map to `execution environment
  unavailable`, never a verdict.
- Focused `test_audit_integrity`, `test_critical_compiler`, and
  `test_audit_integrity.SpawnFailureIsNeverAVerdict` passed.
- Final root critical gate: 258 tests, 0 skips.

### A05 isolation and process limits

- `RLIMIT_NPROC=64` is now installed only for Linux root before the unique
  setuid/setgid drop; production root posture is unchanged.
- Non-root Linux (shared service UID) no longer receives the misleading
  absolute process ceiling. Regression proves the ceiling is unchanged and
  compiler-style spawns work. The test runs the shared-UID branch synthetically
  under the root critical gate, so the gate has no skips.
- Final unprivileged Linux full suite: 392 tests, OK, 14 skipped.
- Final root gate exercises the real identity drop, cgroup setup, Landlock,
  seccomp network denial, and supervisor descendants: 258 tests, 0 skips.
- Residual: non-root runs are not a sandbox boundary; they warn and use rlimits
  only. Strict `CLONE_NEWNET` and host systemd cgroup delegation were not
  available in the disposable container, so `GRADER_REQUIRE_NETNS=0` and
  `GRADER_ALLOW_UNISOLATED_JUDGE=1` were used. This is **not** host/bare-metal
  proof.

### Queue, schema, and storage

- Disposable PostgreSQL 17: clean schema applied twice; queue/security/auth SQL
  all passed.
- Legacy-schema disposable upgrade: existing submission preserved, schema
  applied twice, traceability columns and queue RPCs present, preflight/verify
  clean.
- Queue concurrency: 4 admissions, 8 clients, 4 distinct claims, expired lease
  recovered, stale finish rejected, duplicate finish idempotent.
- Auth concurrency: 8 budget clients -> 1 allowed send; 8 Google claim
  clients -> 1 identity row.
- Completed `judge_queue_finish` now clears `source` and `payload`; a SQL
  regression asserts the terminal row retains neither. Local-mode status records
  clear source too.
- `schema_preflight.sql`, `schema_verify.sql`, and
  `feedback_history_inspection.sql` validated on clean, legacy, and synthetic
  databases. `feedback_history_remediation.sql` defaults to `ROLLBACK`.

### Static, frontend, authoring, dependencies

- `compileall` passed for Python sources/tools/deploy (the first invocation had
  a typo for a nonexistent `containing.py`; the corrected rerun passed).
- `node --check`, `check_frontend`, `check_styles` passed.
- JavaScript tests: 76/76.
- Authoring tests: 18/18.
- Plagiarism self-test: 4/4.
- `pip-audit==2.10.1 -r requirements.txt` under Python 3.12: no known
  vulnerabilities.
- `validate_problem.py`: 64/68. Failures are `collatz_max` (1004:TLE, direct
  reference about 1.04s against a 1.0s limit), `exact_budget` (four TLEs,
  direct reference about 1.21s), `napprime` (flaky at 0.5s), and
  `parking_slots` (1009:TLE, 6 MB input). A disposable `origin/main` archive
  reproduced `exact_budget`, `parking_slots`, and `napprime`; `collatz_max`
  also failed on one of two baseline runs. No problem limits/rules/tests were
  changed to make the gate green.
- CI workflow parses as YAML; top-level `contents: read`, SHA-pinned checkout
  and setup-python, `persist-credentials: false`, `pip-audit==2.10.1`, and the
  disposable legacy-schema job are present.

## Open items

1. Remote CI on a pull request, including the root security job.
2. Production-like Linux host with real systemd cgroup delegation, strict netns,
   and EC2 kernel behavior.
3. Maintainer application of the schema, PostgREST reload, canary, and rollback.
4. Production historical feedback decision/remediation; no production rows were
   inspected or changed.
5. `validate_problem.py` remains a non-green package/performance gate; the
   release owner must decide whether to fix the affected references/limits in a
   separate problem-authoring change.
6. No push, merge, deploy, force-push, or production mutation without explicit
   authorization.
