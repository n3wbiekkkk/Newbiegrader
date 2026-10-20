# Release blocker progress — 2026-10-20

**Status: HOLD. Local release branch is green on the tested code paths, but
current-main integration and production isolation remain blocked. No push,
merge, deployment, force-push, history rewrite, or production mutation was
performed.**

## Tree and authorization boundary

- Worktree: `/Users/phetpitaksukprasert/Developer/grader-security-integration`
- Branch: `security/integrate-audit-fixes`
- Tested code HEAD: `0d27154` (`Backend: preserve submission provenance on
  legacy rejudge updates`)
- Merge base: `4a88796`
- `origin/main` now: `9033be8` (8 commits ahead of the merge base); this is no
  longer the former empty metadata commit.
- Branch relationship: 26 commits ahead / 8 behind `origin/main`.
- `git merge-tree` reports a conflict in `server.py`; schema changes auto-merge
  at the tree level. No merge or rebase was performed.
- Shared worktrees and other agents' changes were not reset, cleaned, stashed,
  or overwritten.
- Private `problems/` and `examples/` remain Git-ignored. Reference fixes are
  preserved in the private evidence directory, not force-added.

## Gate ledger

| Area | Status | Evidence / limitation |
|---|---|---|
| Repository safety | **PASS** | Branch/status reviewed; no push, merge, deploy, reset, clean, or stash |
| Four reference failures (default validator) | **PASS (private fixtures)** | Five focused trials and one full 68/68 local run; expected outputs, configs and tests unchanged |
| Strict problem packages | **FAIL / NOT VERIFIED** | Focused `--strict` reports 0/4 because `input_validator.py` is absent; legacy packages are not a strict-gate pass |
| A01 provenance / legacy retry | **PASS (branch)** | Insert and rejudge UPDATE paths preserve contest provenance; focused tests |
| A02/A03 test stabilization | **PASS (branch)** | Full macOS/Linux suites and 262-test root critical gate |
| A04 live contest feedback | **PASS (branch)** | 17/17 focused tests; synthetic remediation redaction test passed |
| A04 on current main | **FAIL / BLOCKED** | The branch's A04 regression suite fails 10/17 against `origin/main`; merge must preserve the A04 code |
| A05 UID/rlimits/Landlock/seccomp | **PASS (tested Linux)** | Root critical gate, including real drop, seccomp, Landlock and supervisor cleanup |
| A05 strict network namespace | **BLOCKED / NOT VERIFIED (production)** | Worker unit has `RestrictNamespaces=yes` and no `CAP_SYS_ADMIN`; worker env explicitly uses `GRADER_REQUIRE_NETNS=0`/`GRADER_ALLOW_UNISOLATED_JUDGE=1` |
| A05 aggregate cgroup/workspace | **NOT VERIFIED** | Present delegated-cgroup preflight is `HOST_BLOCKED`; synthetic code tests pass; no writable cgroup host available |
| A06 private-file failure | **PASS (branch)** | Full/critical suites pass |
| A07 spawn/infrastructure classification | **PASS (branch)** | Spawn/setup/handshake failures never become CE/RE/AC |
| Database schema, legacy upgrade, RLS/queue/auth | **PASS (disposable PostgreSQL 17)** | Clean + legacy migration, idempotent second apply, queue/security/auth SQL, concurrency |
| Local CI-equivalent checks | **PASS** | Compile, frontend/style, JS 76/76, authoring 18/18, plagiarism 4/4, Docker build, packaged dependency audit |
| Remote CI | **BLOCKED / NOT RUN** | No push or PR was authorized; remote GitHub jobs have not run |
| Production schema/PostgREST | **NOT VERIFIED / REQUIRES APPROVAL** | No production database was queried or changed |
| Production canary/rollback | **NOT VERIFIED / REQUIRES APPROVAL** | Existing scripts only syntax-checked; not executed on production |
| Production release identity | **NOT VERIFIED** | No production deployment or identity query was performed |
| Production readiness | **HOLD** | Local evidence is not a production proof |

## Completed in this pass

### Private reference repairs

The four default-validator failures were reference-efficiency problems, not
declared-limit failures. The following ignored references were replaced:

- `collatz_max`: bounded `array('i')` cache for values at or below `b`; do not
  cache arbitrarily large intermediate values.
- `exact_budget`: meet-in-the-middle over two halves; counts subsets and tracks
  the minimum item count without enumerating all `2^n` masks.
- `napprime`: one-query bytearray sieve plus C-level `sum`; no full prefix table
  for a single query.
- `parking_slots`: sorted initial-slot lists with a cursor and per-type released
  heaps; no `heapify` of all `N` slots.

No `config.json`, test input/output, checker, scoring rule, or time/memory limit
was changed. Byte-comparison against the private backup shows no test/config
changes. Private reference hashes and patches are in
`~/.local/share/newbiegrader-validation/problem-ref-evidence-20261020/`.

### A01 rejudge compatibility

`server.py` now applies the same explicit missing-column retry policy to
rejudge `UPDATE`s as to inserts. A contest row can never lose `contest_id`; a
practice row may use the legacy schema when `contest_id` itself is absent.
Focused tests cover contest/practice rejudge, non-missing errors and missing
relations. This closes the prior A01 rejudge compatibility residual.

### Current-main discovery

`origin/main` advanced during the release validation from an empty metadata
commit to real product changes:

- peer source inspection after qualifying attempts;
- database-backed realtime admins;
- admin all-submission history;
- frontend cache busting.

The branch's A04 regression suite against an archived `origin/main` tree fails
10/17. In particular, stored contest feedback is served with `REVEAL_SAMPLES`
instead of the live `show_samples=false` policy, and rejudge/sample-cache/job
paths regress. Current main also has a macOS `/proc/self/status` test error.
This is a merge/rebase blocker, not a local test flake. No automatic merge was
attempted.

## Open blockers / next actions

1. **Requires approval:** merge/rebase current main and manually resolve
   `server.py` conflict, preserving the A04 live-policy code and tests.
2. **Required after integration:** add `admins` to the migration preflight,
   verification, security SQL, and canary checks; current-main's schema adds
   that table.
3. **Requires approval:** verify a real EC2 worker with strict netns or confirm
   the documented seccomp posture as an accepted residual. The current unit
   intentionally denies `CLONE_NEWNET`.
4. **Requires approval:** run the delegated-cgroup/workspace canary and recover
   exercise on a disposable production-like host; local Docker cgroup mount is
   read-only and the preflight is `HOST_BLOCKED`.
5. **Requires approval:** apply the schema in a maintenance window, reload
   PostgREST, run the API/worker canary, and exercise rollback.
6. **Requires approval:** inspect and, only with a target-specific change
   ticket, remediate historical production feedback rows.
7. **Not actionable locally:** remote CI. Push/PR is prohibited until
   authorized.
8. **Legacy strict packages:** focused `--strict` remains 0/4 because the four
   packages lack `input_validator.py`; this is a separate authoring-contract
   gate and was not papered over.

## Evidence locations

- `/tmp/ng-validate-problems-final-after-a01-20261020.log` — full default
  validator, 68/68.
- `/tmp/ng-four-trials-20261020.log` — five focused validator trials.
- `/tmp/ng-macos-full-after-a01-20261020.log` — 396 tests, OK, 20 skipped.
- `/tmp/ng-linux-nonroot-full-after-a01-20261020.log` — 396 tests, OK, 14
  skipped.
- `/tmp/ng-critical-stock-after-a01-20261020.log` — 262 tests, OK, 0 skips
  (documented unisolated CI posture).
- `/tmp/ng-critical-strict-cap-after-a01-20261020.log` — 262 tests, OK, 0 skips
  in a disposable capable container; **not** production proof.
- `/tmp/ng-origin-main-full-20261020.log` and
  `/tmp/ng-origin-main-ours-a04-20261020.log` — current-main compatibility
  failures.
- `/tmp/ng-validate-four-strict-20261020.log` — focused strict-mode failures.
- `/tmp/ng-queue-sql-20261020.log`,
  `/tmp/ng-security-sql-20261020.log`, `/tmp/ng-auth-sql-20261020.log` —
  disposable PostgreSQL fixtures.
- `/tmp/ng-remediation-synthetic.log` — target-only historical redaction test.

No hidden test bytes, reference source, credentials, or production data are
included in these tracked documents.
