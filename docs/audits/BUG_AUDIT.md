# Newbiegrader correctness and reliability audit — 2026-10-18

Scope, baseline and trust boundaries are in [SECURITY_AUDIT.md](SECURITY_AUDIT.md).
Line references refer to this branch, not the earlier audit's F1–F12 numbering.
Corrections are local pending release. The subsequent authorized feedback branch
push and private problem fixes are recorded in [SUBMISSION_FEEDBACK.md](SUBMISSION_FEEDBACK.md);
no backend deployment or problem-data publication is implied by that push.

## B01 — Public history bypasses the contest freeze

**Medium · CONFIRMED · FIXED locally.**

- Files: `server.py:2987`, `server.py:3418`;
  `tests/test_contest_policy_audit.py:45`.
- Evidence: synthetic running contest, public problem, freeze already active;
  scoreboard returned no rows, while anonymous history returned the new score 100.
- Cause: feed filtered hidden problem IDs but ignored contest freeze timestamps.
- Impact: students could inspect frozen results through a different endpoint.
- Fix: public feed shares freeze predicate with scoreboard. Own `mine=true`
  history and admin access retain their intended privileges; malformed frozen
  timestamps do not disclose results.
- Verification: regression failed before fix and passes after. Existing history
  ownership, live/ended contest and scoreboard tests remain in the full suite.
- Remaining risk: offset pagination/public feed can return fewer than requested
  rows after filtering; no stable cross-request snapshot is promised.

## B02 — Scoreboard silently drops results beyond 5,000

**Medium · CONFIRMED · FIXED locally.**

- Files: `server.py:3432`; `tests/test_contest_policy_audit.py:60`;
  fake query pagination in `tests/fake_supabase.py:75`.
- Evidence: 5,001 synthetic submissions; only the final row scored 100. Old board
  showed 0 points, corrected board shows 100.
- Cause: `.limit(5000)` without pagination; Supabase max-row configuration could
  truncate still earlier (actual production row cap is UNVERIFIED).
- Fix: ordered 500-row pages, exact count, bounded total query budget; incomplete
  or over-budget scans return an error rather than a plausible partial ranking.
- Regression: passes. FakeSupabase now models ranges and multiple sort keys so
  pagination actually executes in tests.
- Remaining risk: independent queries are not one database snapshot during
  concurrent writes. At 50,000 results a board can return 503; use a reviewed SQL
  aggregate/snapshot query before that scale instead of raising the cap blindly.

## B03 — Contest metadata ignores unpublished problem flag

**Medium · CONFIRMED · FIXED locally.**

- Files: `server.py:3281` (`_contest_public`), `server.py:3487` (`contest_detail`);
  `tests/test_contest_policy_audit.py:66`.
- Evidence: a started synthetic contest included an unpublished problem;
  `_visible_to` denied its page, but contest public metadata returned its slug.
- Cause: started-window check was used without the publication check.
- Impact: premature slug/title/limit disclosure and hidden per-problem scores;
  this finding does not establish disclosure of test bytes.
- Fix: non-admin contest lists/details exclude unpublished/unknown problems;
  scoreboard aggregates only the problem IDs visible in that response.
- Regression: failed before fix, passes after; ordinary started contests remain
  visible. Admin unpublished metadata remains available.
- Remaining risk: metadata cache TTL and database-direct bypass (S01).

## B04 — Stored source is truncated below the accepted source size

**Medium · CONFIRMED · FIXED locally.**

- Files: `server.py:1273`; `tests/test_audit_integrity.py:15`.
- Evidence: source of 210,017 bytes accepted by the 256 KiB guard became 200,000
  characters in persisted `submissions.code`; trailing executable code was lost.
- Cause: unrelated persistence slice `[:200000]`.
- Impact: source/history mismatch, incorrect rejudge and unreliable plagiarism
  comparison. This is separate from cross-job tampering in S03.
- Fix: persist the full source that already passed the input size check.
- Regression: failed before fix, passes after. Stored data volume rises only to
  the already documented accepted bound.
- Remaining risk: historical truncated records cannot be repaired without an
  independently retained original; do not automatically rejudge those as faithful copies.

## B05 — Executed-suite provenance can be empty or stale

**Medium · CONFIRMED · FIXED locally.**

- Files: `server.py:2410`, `server.py:1273`;
  `tests/test_audit_integrity.py:21`, `:29`.
- Evidence: a real isolated synthetic runner returned Accepted with empty
  `tests_hash`; persistence could use the latest metadata cache instead of the
  suite passed to the runner.
- Cause: runner's global problem/hash cache is not the parent's metadata cache;
  persistence recomputed from mutable global state.
- Fix: compute the hash from the actual immutable Problem passed for judging,
  include it for CE/final results, prefer that executed hash when persisting.
- Regression: all three provenance tests failed before their corrections and
  pass after, including the actual isolated process path.
- Remaining risk: preexisting rows may have absent/wrong provenance, and the
  job's admission hash can differ from its result if tests changed while queued.
  Result/history hash now identifies execution; admission metadata is not an
  immutable promise to use that version. Source digest/version pinning is future work.

## B06 — Handoff replay cache causes valid OAuth logins to fail

**Medium · CONFIRMED · FIXED locally.**

- Files: `server.py:1633`; `tests/test_auth_retention_audit.py:43`, `:65`.
- Evidence: 10,001 recent synthetic JTIs plus a valid new token failed login.
  `next` query parameter shadows the builtin used in `next(iter(cache))`.
- Fix: expire old tokens under a lock; no builtin-name call, no valid-entry
  eviction; explicit fail-closed capacity 20,000. Concurrent use consumes once.
- Regression: old code returned no session; corrected flow accepts the new
  token, rejects its replay and handles concurrent attempts/capacity as specified.
- Remaining risk: shared replay storage across processes/restarts (S09).

## B07 — Terminal jobs retain source and ignore TTL below 5,001 entries

**Medium · CONFIRMED retention; eventual memory pressure LIKELY · PARTIALLY FIXED.**

- Files: `server.py:909`, `server.py:917`, `server.py:1049`;
  `tests/test_auth_retention_audit.py:55`, `:79`.
- Evidence: completed local jobs retained source and playground input; expired
  entries were only pruned after map length exceeded 5,000. At the accepted
  source bound, source copies alone could exceed 1 GiB before that threshold.
  No memory flood/OOM was run.
- Fix: release source/payload after terminal persistence construction; prune on
  insertion/completion, preserve queued/running jobs, initialize missing job
  monotonic timestamp before cleanup.
- Regression: both tests failed before fix. An intermediate test run caught
  immediate pruning of direct synthetic jobs without timestamps; corrected and
  rerun rather than weakening the existing hidden-redaction tests.
- Remaining risk: a quiet process prunes on activity rather than a periodic timer;
  terminal result bytes within the TTL and database source/results retention are
  still not byte-budgeted. There is no automatic deletion of user database rows.

## B08 — Local queue fallback contradicts durable-queue guarantee

**High reliability · CONFIRMED mode/config and fallback; actual data loss UNVERIFIED · OPEN.**

- Files: `server.py:975` (`_create_job`), `server.py:542` (`_store_submission`),
  `server.py:1014` (`_recover_jobs`); README asynchronous-judging guarantee.
- Evidence: live version reports `queue_mode=local`. Job insert exceptions fall
  back to memory; history insert errors return no ID; completion can still mark
  an in-memory job done. Recovery only sees persisted records and a bounded
  initial set. No production crash/data-loss experiment was performed.
- Cause: best-effort local persistence and nontransactional history/completion,
  while documentation describes an unconditional durable queue.
- Impact: an accepted request can disappear on restart/outage; a verdict may
  have no durable history. Separate local replicas can reset each other's work.
- Minimum fix: review/cut over the **existing** coordinated database queue after
  SQL migration/rollback rehearsal; require successful durable admission for
  public submissions. This is configuration/rollout work, not an engine rewrite.
- Verification: queue admission/lease/fencing/idempotent finish tests and real
  PostgreSQL RPC checks pass; those tests do not certify local mode as durable.
- Remaining risk: production rollout, DB timeout/pool capacity and backup recovery
  require operator evidence and approval.

## Operations / packaging findings

### O01 — Repository Docker image omits plagiarism implementation

**Medium · CONFIRMED packaging · FIXED locally.**

- Files: `Dockerfile:12`, `Dockerfile:14`, `server.py:3754`;
  CI packaged-image self-test in `.github/workflows/ci.yml`.
- Cause/evidence: server loads `tools/plagiarism.py` dynamically; original image
  copied backend modules/static only, so that path was absent and endpoint would
  return 501. Full-repository bind-mounted tests masked packaging omission.
- Impact: organizer plagiarism checks unavailable from a repo-built image.
- Fix: copy just this stdlib module. Built a clean image context without `.env`,
  private problem packages or examples; packaged self-test passes 4/4.
- Remaining risk: running production image contents are UNVERIFIED; score/source
  integrity still depends on S03, S05 and B04. This is not a sandbox vulnerability.

### O02 — HTTP-only healthcheck does not support worker-only role or custom port

**Medium · CONFIRMED configuration mismatch; production impact UNVERIFIED · OPEN.**

- Files: `Dockerfile:26`, `container_entrypoint.py:12`, `container_entrypoint.py:18`,
  `worker.py:11`.
- Evidence: worker role intentionally has no HTTP listener; healthcheck always
  requests port 8000 even though HTTP entrypoint accepts PORT. Current live role
  is combined; no claim it is currently restarting from this issue.
- Impact: false unhealthy status; host-dependent restart loops or failed rollouts
  for supported worker/custom-port deployments.
- Minimum fix: role-specific liveness/heartbeat check and configured port; test
  stopped worker and stuck heartbeat actually fail. Do not return success merely
  because the role string is worker.
- Verification: code/config comparison, not a live worker deployment experiment.
  Healthcheck replacement is not included in this patch.

### O03 — Operational assumptions and recovery evidence are incomplete

**Medium · CONFIRMED documentation drift; backup/deployment controls UNVERIFIED · OPEN.**

- Files: `agent.md:62`, `agent.md:64`, README feature guarantees,
  `Dockerfile:1`, `.github/workflows/ci.yml:1`.
- Evidence: old docs reference a different Supabase project/host capacity/counts;
  live read-only metadata reports Supabase source, 512 MB, local queue, 68 problems.
  Floating base image/apt toolchain and partial Python pins do not reproduce an
  identical compiler/runtime image. GitHub Actions tags are not immutable SHAs.
- Impact: wrong capacity choices, incorrect incident instructions, irreproducible
  verdict/runtime behavior. No restore test, retention policy, alert delivery,
  host mount/capability inspection or managed-backup inventory was provided.
- Minimum fix: record actual environment names/roles without values, image digest
  and compiler versions; rehearse restore in a disposable project, pin release
  artifacts, rehearse stop-admission/drain/recovery. Acceptance checklist is in
  [PRODUCTION_READINESS.md](PRODUCTION_READINESS.md).
- Regression status: current audit gates improved, operational rehearsal not run.
- Remaining risk: upstream outages, stale authorizations during metadata refresh
  failure (`server.py:2142` keeps stale cache), bounded-count rather than bounded-byte
  problem/PDF caches (`problem_store.py:65`), and unbounded Storage response reads
  (`problem_store.py:403`). These are review targets with trusted-data prerequisites;
  no corrupt-storage DoS was executed.

### O04 — Base-image installer packages escape requirements-only scanning

**Low · CONFIRMED image inventory; API exploitability UNVERIFIED · FIXED locally.**

- Files: `Dockerfile:9`, `.github/workflows/ci.yml` packaged-image check.
- Evidence: initial built-image inventory additionally reported 7 distinct
  advisory IDs in pip 24.0 and setuptools 79.0.1, absent from requirements.txt.
  These are installation/packaging paths, not established HTTP attack paths;
  some have Python-version/macOS prerequisites inapplicable to this Linux image.
- Fix: pin updated pip 26.2.1/setuptools 84.0.0 before dependency installation;
  scan actual packaged versions in CI in addition to requirement resolution.
- Verification: final image inventory audit and runtime checks recorded in
  PRODUCTION_READINESS.md. No production dependency versions were inspected.
- Remaining risk: `pip-audit` does not scan OS/kernel packages, and a clean scan
  cannot establish absence of undisclosed vulnerabilities.

## Verification commands

Use an isolated copy without `.env` or deployment credentials. Full tests rely on
the maintainer's trusted offline problem packages; critical tests do not.

```sh
python -m unittest discover -s tests -v
python tools/run_critical_tests.py  # Linux/root; any skip is a failure
node --check static/app.js
node tools/check_frontend.js
node tools/check_styles.js
node --test tests/test_*.js
python tools/validate_problem.py --jobs 1
python tools/plagiarism.py
python -m compileall -q grader.py server.py judge_runner.py worker.py container_entrypoint.py problem_store.py tools tests
python -m pip_audit -r requirements.txt
```

A passing fake database test is not proof of PostgREST/RLS behavior. Run
`tests/queue_sql.sql` and `tests/security_sql.sql` against a disposable PostgreSQL
database with Supabase-like grants, as CI now does. Never seed production with
these fixtures. See final recorded counts in the production-readiness report.

## B09 / B10 — Problem correctness and submission diagnostics follow-up

See [SUBMISSION_FEEDBACK.md](SUBMISSION_FEEDBACK.md) for evidence, file:line,
regressions, remaining risk and release/rollback requirements for the KAI-GAI
reference/specification mismatch (Medium) and unbound result copy controls / I/O
alignment (Low). Both are CONFIRMED, corrected locally and not deployed.
