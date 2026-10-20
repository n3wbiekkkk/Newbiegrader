# Main reconciliation report — 2026-10-20

**Status: READY FOR REVIEW (local reconciliation branch).**
**Production release and canary: NOT APPROVED / BLOCKED on the external gates below.**
No push, shared-branch merge, deployment, production database mutation, or remote
CI run has been performed.

## Identity and scope

| Item | Value |
|---|---|
| Original integration branch | `security/integrate-audit-fixes` at `901d7d6` |
| Isolated worktree | `/Users/phetpitaksukprasert/Developer/grader-main-reconciliation-20261020` |
| Reconciliation branch | `security/reconcile-main-20261020` |
| First main baseline | `9033be8` |
| Final fetched `origin/main` baseline | `b7200d2` (`Merge pull request #22 ...`) |
| Merge commits | `25068ce` (baseline `9033be8`), `ac03398` (later baseline `b7200d2`), `756b284` (peer-learning policy) |
| Schema verification commit | `5db116f` |
| Final publication commit | `[REPORT_COMMIT]` (report-only commit; code HEAD `756b284`) |

The branch was created from `901d7d6` and merged main locally. It was not
rebased and no history was rewritten. The original
`security/integrate-audit-fixes` branch remains at `901d7d6`.

The shared root worktree is on an unrelated `perf/local-mirror-two-workers`
branch with uncommitted work. It was not cleaned, reset, stashed, overwritten,
or integrated.

## Incoming main changes

The initial merge covered `ed743dc`, `499a39b`, `1324043`, `9163f68`, `5eacebf`,
`d02a303`, `a4c9035`, and `9033be8`. While local verification was running,
`origin/main` advanced to `b7200d2`; `3931fd4`, `3607cd1`, and `b7200d2` were
then merged separately. The final merge added `3931fd4`, `3607cd1`, `b7200d2`,
`f88a406`, `ad6e530`, and `756b284` (Thai verdict presentation + peer learning). All incoming changes are retained:

- PostgreSQL-backed `public.admins`, env-seed bootstrap, realtime cache refresh,
  and admin add/remove/list routes.
- Paginated all-user admin submission history with metadata-only rows.
- Peer inspection for completed qualifying attempts, including fresh contest
  policy reads, bounded pagination, and explicit fail-closed behavior.
- Admin overview recent rows carrying verdict fields needed by the Thai verdict UI.
- Asset cache-version changes, frontend peer-inspection controls, and Thai verdict
  labels/meanings with a verdict legend.
- Peer learning access for all signed-in students with qualifying-verdict rules.

The repository schema, legacy-upgrade checks, release preflight/verify scripts,
security SQL fixtures, and CI workflow were reviewed with the merge.

## Conflict resolution

The only conflict was in `server.py`'s `history_detail` authorization path.
Resolution:

- Preserve main's peer-inspection branch and its fresh contest/qualifying-attempt
  authorization.
- Preserve the security branch's owner/admin boundary.
- A non-owner administrator can inspect the row, but the response uses the
  submission owner's feedback policy; the administrator does not inherit
  `REVEAL_ALL` and cannot declassify live hidden or historical rows.
- The submission owner keeps the normal owner path.
- Unknown, deleted, or unavailable contest policy continues to fail closed to
  no feedback rather than falling back to samples.

There were no other textual conflicts. Incoming `admins` schema, admin routes,
admin tests, peer tests, static assets, and contest pagination were retained.

## A01–A07 integration status

All seven findings are present in the reconciled tree and have focused regression
coverage. None is removed or weakened by the main merge.

| ID | Status in reconciled tree | Evidence |
|---|---|---|
| A01 | Present | Retry only explicit missing-column errors; contest provenance is never downgraded to practice. `tests/test_audit_integrity.py` (20 tests including A07) passes. |
| A02 | Present | Cgroup supervisor capability test is deterministic and uses the delegated-manager path. Included in the Linux critical gate. |
| A03 | Present | Explicit synthetic `SESSION_SECRET` in the test environment. Included in the Linux critical gate. |
| A04 | Present and adapted | Owner policy applies to rejudge, history, and terminal job polls; live policy is re-evaluated; unknown contests fail closed. The 17-case A04 suite and 25-case incoming peer suite pass. |
| A05 | Present with production limitation | Linux keeps `RLIMIT_NPROC=64`; non-Linux keeps the host process ceiling. The Linux root critical gate passes; real production cgroup/workspace delegation remains unverified. |
| A06 | Present | Missing private storage bytes end the claimed job in `status=error`; no score or verdict is fabricated. |
| A07 | Present | Spawn/compiler/supervisor setup failures map to `SandboxUnavailable` or `spawn-fail`, never a scored verdict. Included in A01/A07 focused coverage and Linux critical gate. |

## A04 privacy case matrix (all 17)

All cases below ran on the final code HEAD and passed.

| # | Case | Result |
|---|---|---|
| 1 | `test_policy_outage_does_not_open_problem_or_sample_access` | PASS |
| 2 | `test_missing_registration_table_never_disables_the_gate` | PASS |
| 3 | `test_public_history_does_not_reveal_frozen_contest_scores` | PASS |
| 4 | `test_scoreboard_includes_results_after_the_old_5000_row_limit` | PASS |
| 5 | `test_contest_does_not_publish_unpublished_problem_metadata_or_scores` | PASS |
| 6 | `test_public_stats_filters_private_and_unknown_problem_ids_even_on_cache_hit` | PASS |
| 7 | `test_sample_route_does_not_trust_a_stale_contest_cache` | PASS |
| 8 | `test_admin_rejudge_keeps_the_submission_owner_feedback_policy` | PASS |
| 9 | `test_live_contest_hides_stored_sample_feedback_on_history_read` | PASS |
| 10 | `test_admin_rejudge_practice_in_live_hidden_contest_uses_none` | PASS |
| 11 | `test_admin_rejudge_unknown_contest_fails_closed` | PASS |
| 12 | `test_admin_rejudge_practice_outside_contest_keeps_practice_feedback` | PASS |
| 13 | `test_admin_owner_keeps_admin_feedback_policy_on_contest_reads` | PASS |
| 14 | `test_admin_viewing_another_users_contest_row_uses_owner_policy` | PASS |
| 15 | `test_live_contest_hides_practice_history_for_newly_hidden_problem` | PASS |
| 16 | `test_live_contest_hides_stored_job_feedback_on_poll` | PASS |
| 17 | `test_rejudge_job_never_hands_the_owner_hidden_test_data` | PASS |

The separate incoming peer-inspection suite also passed **25/25**. It checks
qualifying-verdict rules, lower database response caps, historical pagination,
viewer/problem scoping, upcoming/running/ended contest policy, stale-cache
bypass, policy outages, malformed pages, and hidden-test I/O redaction.

## Verification matrix

### Host and tests

| Check | Command / environment | Result |
|---|---|---|
| macOS full suite | Python `3.12.15`, macOS arm64, `unittest discover -s tests -v`, private fixtures mounted read-only | **404 tests, OK, 39 skips** |
| A04 focused | `test_contest_policy_audit.py` | **17/17 PASS** |
| Incoming peer focused | `test_critical_peer_inspection.py` | **25/25 PASS** |
| Admin focused | `test_admin_management.py` | **12/12 PASS** |
| A01/A07 focused | `test_audit_integrity.py` | **20/20 PASS** |
| Linux root critical | Python 3.11 container, `GRADER_REQUIRE_NETNS=0`, `GRADER_ALLOW_UNISOLATED_JUDGE=1` | **287 tests, OK, 0 skips** |
| Linux strict capable container | Python 3.11, `--cap-add=SYS_ADMIN`, `GRADER_REQUIRE_NETNS=1`, `GRADER_ALLOW_UNISOLATED_JUDGE=0` | **287 tests, OK, 0 skips**; `netns_available=True` probe |
| Linux non-root full | Python 3.11, UID 65534, private fixtures read-only | **433 tests, OK, 14 skips** |
| JavaScript | `node --check`, frontend/style guards, `node --test tests/test_*.js` | **84/84 PASS** |
| Problem validator | default `tools/validate_problem.py` | **68/68 problems OK** |
| Compile | `compileall` on engine, server, tools | **PASS** |
| Plagiarism self-test | `tools/plagiarism.py` | **4/4 PASS** |
| Dependency audit | `pip-audit -r requirements.txt`; current Docker image packages | **No known vulnerabilities** |
| Docker build | current reconciliation `Dockerfile` build (`newbiegrader-reconcile:20261020-latest`) | **PASS**; image plagiarism **4/4**, image dependency audit clean |
| Diff hygiene | `git diff --check` | **PASS** |

### Disposable PostgreSQL 17

All checks ran against disposable local containers only. No production database
was connected to.

| Check | Result |
|---|---|
| Apply current `supabase/schema.sql` twice | **PASS** |
| Apply legacy schema, then current schema twice, then `legacy_schema_verify.sql` | **PASS** |
| `tests/queue_sql.sql` | **PASS** |
| `tests/security_sql.sql` including `admins` | **PASS** |
| `tests/auth_sql.sql` | **PASS** |
| `docs/release/schema_verify.sql` including `admins` | **PASS** |
| `docs/release/schema_preflight.sql` | **0 blocking rows** |
| Queue concurrency and lease recovery | **PASS** |
| Auth budget/Google identity concurrency | **PASS** |

The release preflight, verify, and security fixtures now require
`public.admins`; the table must be present, RLS-protected, browser-inaccessible,
and service-role manageable before this backend is deployed.

## Sandbox, isolation, and resource posture

Verified locally:

- Linux root critical gate: **287 tests, 0 skips**.
- Strict-capable disposable container: **287 tests, 0 skips**; the network
  namespace was actually available (`netns_available=True`).
- Spawn/compiler/supervisor failures are classified as sandbox failures, not
  accepted/wrong-answer verdicts.
- Linux process ceiling remains `RLIMIT_NPROC=64`; no unisolated judging was
  enabled to make tests pass.

Not verified / not claimable from this workstation:

- The production systemd worker has `RestrictNamespaces=yes`, excludes
  `CAP_SYS_ADMIN`, and sets `GRADER_REQUIRE_NETNS=0` plus
  `GRADER_ALLOW_UNISOLATED_JUDGE=1`. Production strict network-namespace
  isolation is therefore **NOT VERIFIED**.
- `tools/check_job_resource_host.py` reports `HOST_BLOCKED` on macOS: Linux
  cgroup v2 delegation and aggregate workspace enforcement are **NOT VERIFIED**.
- The test container proves code paths, not that the EC2 host can delegate
  cgroups or create namespaces under the deployed service unit.
- No production-like host capacity, queue lease, compiler toolchain, or
  long-running worker soak was exercised.

Residual sandbox limits: per-process rlimits, privilege drop, Landlock, and an
inherited network syscall filter are not a substitute for a verified network
namespace and cgroup aggregate limit. The production service unit must be
validated before canary; no `NOT VERIFIED` item is recorded as passing.

## Adversarial review and fixes

**Findings:** [AUDIT_FINDINGS]

The review explicitly checked every output channel that can carry feedback:
public history, owner history, admin history, peer inspection, terminal job
polls, sample routes, scoreboards/stats, and admin rejudge storage. A non-owner
administrator is constrained to the owner's policy and cannot use admin
privilege to declassify hidden test data. Peer inspection exposes source and
verdict/resource evidence only after a qualifying attempt and only when the
contest policy permits it; it never returns hidden inputs, expected outputs, or
actual outputs.

## Remaining blockers and release gate

These are outside a local branch and prevent a production/canary claim:

1. **Remote CI and review:** push/PR, workflow run, and human review have not
   happened. Push/PR requires explicit authorization.
2. **Production-like Linux host:** verify systemd cgroup delegation, workspace
   limits, namespace behavior, compiler/runtime availability, and queue
   recovery under the deployed units.
3. **Database release:** maintainer review and application of the additive schema,
   PostgREST cache reload, then preflight/verify against the approved environment.
4. **Canary and rollback:** deploy a canary with queue mode staged, exercise one
   claimed job, verify redaction and resource limits, and rehearse rollback.
5. **Historical feedback remediation:** production inspection and any cleanup
   require privacy approval; no production rows were read or changed.
6. **Host capacity/soak:** verify worker counts, queue bounds, memory ceilings,
   and timeouts on the real host rather than deriving confidence from macOS.
7. **Strict problem publication:** the separate strict authoring gate remains
   **0/4** for four legacy packages lacking trusted `input_validator.py` files.
   This does not change runtime judging correctness, but those packages cannot be
   claimed strict-publishable.
8. **Credential hygiene:** a deploy remote was observed with embedded credentials
   during inspection; rotation is a separate authorized security action. No
   credential value was copied into this report or used.

## Commits and proposed PR

Local commits, in order:

- `901d7d6` — original security integration branch baseline.
- `25068ce` — merge of `9033be8` into the reconciliation branch.
- `5db116f` — release preflight/verify and security SQL coverage for `admins`.
- `ac03398` — merge of `b7200d2` (Thai verdict presentation).
- `756b284` — merge of `f88a406` (peer learning policy).
- `[REPORT_COMMIT]` — this report.

Proposed PR (not created):

- Target `main` from `security/reconcile-main-20261020`.
- Explain the two main merges, the `server.py` owner-policy conflict resolution,
  the `admins` schema/release checks, and the A01–A07/A04 evidence.
- Require remote CI, the full critical gate on a disposable Linux runner, schema
  preflight/verify, and reviewer approval of the production sandbox posture.
- Do not auto-deploy, apply production SQL, or run a canary as part of the PR.

## Decision

**READY FOR REVIEW** for the local reconciliation branch, with the local code,
privacy, database-schema, and focused sandbox evidence above.

**NOT READY FOR CANARY** and **production release remains BLOCKED** until the
production-like Linux/cgroup/network-namespace checks, schema application,
canary/rollback, remote CI, and privacy approvals are completed. Local tests do
not prove production readiness, and no production data or deployment was touched.

## Evidence boundary

This report records local execution only. Exact command logs are available in
the local `/tmp/ng-reconcile-*` files used during this run; they are not part of
the repository and contain no production data or secrets. Hidden fixture
contents, reference source, credentials, and production rows are intentionally
not reproduced here.