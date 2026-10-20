# Release blocker report — 2026-10-20

## Verdict

**Release branch code-level A01–A07: PASS in the tested macOS, Linux-container,
and disposable PostgreSQL environments.**

**Current-main compatibility: FAIL / BLOCKED.** `origin/main` advanced from the
former empty metadata commit to eight real product commits. The branch's A04
regression suite fails 10 of 17 checks against current main, and a local
`git merge-tree` reports a `server.py` conflict. No merge or rebase was
performed.

**Production readiness: HOLD / NOT VERIFIED.** The available environment does
not provide a writable delegated cgroup host or a strict production network
namespace. Remote CI, production schema application, canary, rollback, and
production release identity were not exercised. Nothing was pushed, merged,
deployed, or changed in AWS, Cloudflare, Supabase, or another production system.

This report supersedes the earlier `RELEASE_VALIDATION_REPORT.md` status of
64/68 and the A01 rejudge residual for the **release branch**. It does not
supersede that report's production limitations; those remain open.

## Scope and safety boundary

- Worktree: `/Users/phetpitaksukprasert/Developer/grader-security-integration`
- Branch: `security/integrate-audit-fixes`
- Tested code HEAD: `0d27154`
- Merge base: `4a88796`
- `origin/main`: `9033be8`; current relationship: **26 ahead / 8 behind**
- The branch contains only local commits. No push, pull request, merge,
  deployment, force-push, shared-history rewrite, reset, clean, or stash was
  performed.
- Private `problems/` and `examples/` remain Git-ignored. No hidden fixtures or
  reference source were force-added or published. No credentials or production
  rows are included here.
- Other worktrees and agents' work were not modified.

## Gate summary

| Gate | Status | Basis |
|---|---|---|
| Repository safety and authorization boundary | **PASS** | Clean branch/status review; no remote or production mutation |
| Full default problem validator | **PASS (private fixtures)** | 68/68; five focused trials plus full run |
| Strict problem packages | **FAIL** | Focused `--strict`: 0/4 because the four legacy packages lack `input_validator.py` |
| A01 provenance and legacy retry | **PASS (branch)** | Insert/rejudge UPDATE compatibility tests |
| A02/A03 test stabilization | **PASS (branch)** | Full suites and 262-test root critical gate |
| A04 live contest/feedback policy | **PASS (branch)** | 17/17 focused tests and synthetic remediation test |
| A04 on current main | **FAIL / BLOCKED** | 10/17 branch A04 regressions fail against `origin/main` |
| A05 UID, rlimits, Landlock, seccomp | **PASS (tested Linux)** | Root critical gate including real sandbox execution |
| A05 strict network namespace | **BLOCKED / NOT VERIFIED (production)** | Worker unit denies namespace creation and has no `CAP_SYS_ADMIN` |
| A05 aggregate cgroups/workspace | **NOT VERIFIED** | Local preflight `HOST_BLOCKED`; synthetic tests only |
| A06 private-file failure classification | **PASS (branch)** | Full/critical suites |
| A07 spawn/infrastructure classification | **PASS (branch)** | Focused and root tests |
| Database schema, RLS, queue, auth | **PASS (disposable PostgreSQL)** | Clean/legacy apply, SQL fixtures, concurrency |
| Local CI-equivalent checks | **PASS** | Static, frontend, JS, authoring, plagiarism, dependency and image checks |
| Remote CI | **NOT RUN** | No authorized push/PR |
| Production schema/PostgREST | **REQUIRES APPROVAL** | Not applied |
| Production canary/rollback | **REQUIRES APPROVAL** | Not exercised |
| Production release identity | **NOT VERIFIED** | Not queried |
| Production readiness | **BLOCKED / NOT VERIFIED** | Local evidence is not production proof |

## 1. Four default-validator failures

The four failures were inefficient private reference solutions, not rules or
limits that needed weakening:

| Problem | New reference approach | Config/tests changed? |
|---|---|---|
| `collatz_max` | Cache only values `<= b` in a compact `array('i')`; do not retain arbitrarily large intermediate values | No |
| `exact_budget` | Meet-in-the-middle over two halves; count subsets and track minimum item count | No |
| `napprime` | One-query bytearray sieve plus C-level `sum`; no full prefix table | No |
| `parking_slots` | Sorted initial-slot lists with cursors plus per-type released-slot heaps; no full-slot heapify | No |

Verification:

- Each replacement matches all shipped expected outputs.
- Independent small-case oracles passed:
  - 300 bounded Collatz intervals plus boundary cases;
  - 250 Exact Budget brute-force cases;
  - 200 prime-count intervals;
  - 150 random valid Parking command sequences.
- Full default validator: **68/68 problems OK**, including all four.
- Five focused trials all passed.
- The private original configs/tests were byte-compared with backups: unchanged.
- Strict mode is not claimed: `validate_problem.py ... --strict` reports **0/4**
  because the legacy packages have no `input_validator.py`. That is a separate
  authoring-contract gate and was not papered over.

### Controlled timing and peak RSS

Measured directly in a disposable Linux arm64 container with Python 3.11,
network disabled, output discarded. The “old” values are the backed-up original
references; limits are unchanged.

| Problem | New wall (median / range) | Old wall | New peak RSS | Old peak RSS | Declared limit |
|---|---:|---:|---:|---:|---:|
| `collatz_max` | 0.113 s (0.112–0.121) | 0.212–0.219 s | 10.5 MB | 90.6 MB | 1.0 s / 64 MB |
| `exact_budget` | 0.005 s | 0.258–0.262 s | 10.4 MB | 10.4 MB | 1.0 s / 64 MB |
| `napprime` | 0.009 s | 0.028 s | 10.4 MB | 18.9 MB | 0.5 s / 32 MB |
| `parking_slots` | 0.203–0.204 s | 0.292–0.293 s | 111.8 MB | 113.0 MB | 1.0 s / 256 MB |

Judged validator slowest times over five focused trials were 0.228–0.286 s
(Collatz), 0.136–0.156 s (Exact Budget), 0.135–0.179 s (Napprime), and
0.309–0.394 s (Parking). The old failures were therefore a real reference
efficiency/memory problem, not a reason to change limits.

Private evidence (reference source and patches must stay private):
`~/.local/share/newbiegrader-validation/problem-ref-evidence-20261020/`.

## 2. A01–A07 revalidation

| ID | Branch status | Evidence and residual |
|---|---|---|
| A01 | **PASS** | Inserts and rejudge UPDATEs retry only explicit missing-column errors; contest provenance is preserved; practice rows can use the legacy fallback; integrity/relation errors are not retried. Four new rejudge tests plus the existing insert/E2E tests pass. The prior rejudge UPDATE residual is closed on this branch. |
| A02/A03 | **PASS** | Critical cgroup tests are deterministic off-host; non-root tests supply synthetic session state. Full suites and the 262-test root critical gate pass. |
| A04 | **PASS (branch)** | Live history/job reads re-evaluate owner policy; sample route bypasses stale TTL; unknown/failed policy fails closed; rejudge and admin-owner semantics are preserved. 17/17 focused tests pass. |
| A05 | **PASS (code) / BLOCKED (production)** | Root identity drop, Landlock, seccomp, supervisor cleanup and compiler paths pass; non-root Linux preserves the shared-UID ceiling and is explicitly rlimits-only. Strict netns and delegated cgroup enforcement are not available in the supplied host. |
| A06 | **PASS** | Missing private bytes fail the claimed job as an environment error, never a verdict; full/critical regressions pass. |
| A07 | **PASS** | Compile/supervisor spawn, setup, handshake and pid failures map to environment errors, never CE/RE/AC; playground follows the same fail-closed mapping. |
| Historical A04 remediation | **PASS (synthetic) / REQUIRES APPROVAL (production)** | Target-only redaction preserved current public sample fields, removed hidden input/output/diff/diagnostic fields, marked non-public results hidden, retained the backup row, and passed post-update assertions on a disposable database. The production row set was never inspected or changed. |

### Current-main compatibility failure

The former note that `origin/main` was tree-identical is obsolete. Current main
now contains peer source inspection, database-backed admins, admin history and
frontend cache changes. On an archived `origin/main` tree:

- Full macOS discovery: **320 tests, 1 error, 22 skipped**. The error is a
  `/proc/self/status` access in `test_critical_global_cgroup_root_is_never_modified`
  on macOS.
- Running this branch's A04 regression suite against current main:
  **17 run, 10 failures**.
- Failure categories include: stored contest feedback served with
  `REVEAL_SAMPLES` instead of the live hidden-contest policy; job-result
  redaction; sample-route stale-cache protection; admin-viewing-another-owner
  policy; and rejudge owner-policy checks.
- `git merge-tree` reports a content conflict in `server.py`; the schema changes
  auto-merge at tree level, but current main also adds an `admins` table that
  the branch's release preflight/verify/security SQL does not yet require.

**Conclusion:** current main must not be merged blindly. A reviewed resolution
must preserve the branch's A04 live-policy code and tests while integrating peer
inspection and admin management. This requires maintainer authorization.

## 3. Linux, isolation, and cgroup posture

### Tested code paths

| Environment | Command posture | Result |
|---|---|---|
| macOS arm64, Python 3.12.15 | Full `unittest` discovery | **396 tests, OK, 20 skipped** |
| Linux arm64 container, unprivileged UID 65534 | Full `unittest` discovery | **396 tests, OK, 14 skipped** |
| Linux arm64 root, documented CI posture | `GRADER_REQUIRE_NETNS=0`, `GRADER_ALLOW_UNISOLATED_JUDGE=1` | **262 tests, OK, 0 skips** |
| Linux arm64 root, disposable `--cap-add=SYS_ADMIN` | `GRADER_REQUIRE_NETNS=1`, `GRADER_ALLOW_UNISOLATED_JUDGE=0`, network-none container | **262 tests, OK, 0 skips** |

The last row proves the strict code path in a disposable capable container; it
is **not** evidence that the production host can create namespaces. Without the
capability, the focused strict runner tests pass because the runner refuses
execution; unrelated strict-environment tests correctly receive sandbox
refusals. No test was weakened to accept an unisolated result.

### Production restrictions

`deploy/ec2/newbiegrader-worker.service` and the canary unit contain:

- `RestrictNamespaces=yes`
- a capability bounding set that excludes `CAP_SYS_ADMIN`
- `GRADER_REQUIRE_NETNS=0`
- `GRADER_ALLOW_UNISOLATED_JUDGE=1`

The production mitigation is mandatory seccomp socket denial, not a network
namespace. A strict namespace requirement therefore conflicts with the current
unit by design. Removing `RestrictNamespaces=yes` or granting `CAP_SYS_ADMIN`
would be a security-architecture change requiring explicit approval; it was not
performed. If the documented seccomp posture is accepted, the strict-netns gate
should be recorded as an accepted residual rather than silently marked PASS.

### Aggregate cgroup/workspace status

`tools/check_job_resource_host.py` inside the supplied container returns
`HOST_BLOCKED` with a read-only cgroup mount, no enabled delegated controllers,
and an unreadable/populated parent; `GRADER_REQUIRE_JOB_CGROUP=1` cannot be
satisfied there. Synthetic `job_resources` tests pass, but no real per-job
memory/pids/CPU/workspace enforcement was demonstrated. `job_resources` expects
the configured root plus its `manager` subgroup and a dedicated
`<=128 MiB/4096-inode` tmpfs; that must be verified on the actual worker host.

`GRADER_ALLOW_UNISOLATED_JUDGE=1` and `GRADER_REQUIRE_NETNS=0` remain in the
production example environment. Non-root Linux execution is rlimits-only, not a
sandbox boundary.

### Exact operator verification (do not run against production without approval)

```sh
# 1. Read-only host preflight; exit 2 = HOST_BLOCKED, exit 0 = candidate only.
cd /opt/newbiegrader/current
python tools/check_job_resource_host.py \
  --cgroup-root "${GRADER_JOB_CGROUP_ROOT:-/sys/fs/cgroup}"

# 2. Inspect the actual unit properties; do not print environment secrets.
systemctl show newbiegrader-worker.service \
  -p Delegate -p DelegateSubgroup -p RestrictNamespaces \
  -p CapabilityBoundingSet -p MemoryMax -p CPUQuota -p TasksMax

# 3. Read-only strict-netns capability probe under the worker's environment.
python - <<'PY'
import grader
print("netns_available", grader.netns_available())
PY

# 4. Approved synthetic unit checks only, with the real worker disabled.
test ! -e /etc/newbiegrader/worker-enabled
deploy/ec2/verify-worker.sh
# deploy/ec2/verify-recovery.sh   # destructive canary restart; approval required
```

`deploy/ec2/verify-worker.sh` runs `worker.py --check` and must not claim jobs.
`deploy/ec2/newbiegrader-canary.service` and `deploy/ec2/verify-recovery.sh` are
the synthetic cgroup/workspace/recovery canaries; they require a disposable
production-like host and change approval. They were syntax-checked only.

## 4. Database, queue, and privacy fixtures

Disposable PostgreSQL 17 (local containers; no cloud resources):

- Clean database: `supabase/schema.sql` applied twice; schema verification,
  security SQL, auth SQL and queue SQL all passed.
- Legacy schema: existing history row preserved through two schema applications;
  traceability columns, queue RPCs and defaults verified.
- `schema_preflight.sql` on the clean database returned no missing tables,
  columns, functions, RLS gaps, browser grants or unsafe views.
- Queue concurrency: 4 admissions, 8 claim clients, 4 distinct claims, expired
  lease recovered, stale finish rejected, duplicate finish idempotent, no
  unintended submission rows.
- Auth concurrency: 8 budget clients -> 1 allowed send; 8 Google claim clients
  -> 1 identity row, version 1.
- Terminal `judge_queue_finish` clears `source` and `payload`; completed jobs do
  not retain user source.
- `feedback_history_remediation.sql` target-only synthetic test committed a
  redaction, preserved the public sample and metadata, removed hidden fields,
  added `hidden: true`, and retained the backup row. The tracked template still
  defaults to `ROLLBACK` and was also verified as a no-op.

The tracked release SQL was not applied to production. PostgREST schema-cache
reload was not run. Current-main's new `admins` table must be added to the
release preflight/verify/security checks when that code is integrated.

## 5. CI, static, frontend, and packaging

Passed locally:

- Python byte-compilation for application, tools and deployment modules.
- `node --check static/app.js`; DOM/icon check; style-token/dark-mode check.
- Vanilla JavaScript tests: **76/76**.
- Problem-authoring tests: **18/18**.
- Plagiarism self-test: **4/4**.
- `pip-audit==2.10.1 -r requirements.txt`: **No known vulnerabilities found**.
- Docker image build, packaged plagiarism self-test, and packaged-image
  dependency audit: no known vulnerabilities.
- `.github/workflows/ci.yml` YAML parse and SHA-pinned action check passed.
- Deployment shell and canary Python syntax checks passed.

Remote CI has not run. Local checks cannot prove the GitHub `critical-security`
job (currently configured with `GRADER_REQUIRE_NETNS=0` and
`GRADER_ALLOW_UNISOLATED_JUDGE=1`) or the queue-sql service environment.

## 6. Required approvals and next safe actions

1. **Merge/rebase approval:** integrate `origin/main` with a reviewed
   `server.py` conflict resolution that preserves A04; add current-main tests
   and the `admins` schema checks.
2. **Security approval:** decide whether to keep the documented seccomp posture
   or redesign the worker host for strict network namespaces and a real
   delegated cgroup v2 subtree.
3. **Production approval:** run read-only schema preflight, back up, apply the
   additive schema, notify PostgREST, run the API/worker canary, and exercise
   rollback in a maintenance window.
4. **Privacy approval:** inspect historical production feedback with
   `feedback_history_inspection.sql`; use only target-specific remediation with
   the reviewed backup and rollback template.
5. **Release approval:** push/PR, remote CI, immutable-image deployment, and
   production identity/canary checks.
6. **Separate authoring work:** add trusted `input_validator.py` files and
   perform strict package publication checks for legacy problems; do not
   describe the current 68/68 default run or the 0/4 strict run as a strict
   release pass.

## 7. Evidence and limitations

Local logs are under `/tmp/ng-*20261020.log`; the private reference evidence is
under `~/.local/share/newbiegrader-validation/problem-ref-evidence-20261020/`.
The logs contain test names and aggregate results, not hidden fixture bytes.

This report intentionally does not claim:

- that macOS results prove Linux kernel isolation;
- that a capable disposable container proves the EC2 unit;
- that synthetic cgroup tests prove per-job enforcement;
- that local PostgreSQL proves production schema/PostgREST state;
- that local CI proves remote CI;
- that the branch is current-main compatible;
- that production is ready for release.
