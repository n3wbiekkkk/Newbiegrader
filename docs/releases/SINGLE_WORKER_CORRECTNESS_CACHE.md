# Single-worker correctness/cache release review

2026-10-19. Branch `fix/single-worker-correctness-cache`, base `25523f7`.
Implementation commits: `de34407` (backend), `837366c` (frontend/proxy).
Status: reviewed, locally tested, committed for review; **not pushed or deployed**.
The original dirty `perf/local-mirror-two-workers` tree remains untouched.

## Release boundary

This release contains correctness/cache work and synthetic regressions only.
It includes neither the local mirror module/flags nor host-slot/instance support,
worker templates, cgroup/systemd changes, environment changes, database migrations
or dependency changes. Keep the existing singleton worker, Supabase source and
Cloudflare private route. Engine `grader.py`, `judge_runner.py`, isolation and
feedback policies are unchanged. The separate EC2 concurrency experiment did
not pass its near-limit promotion gate; this release does not enable worker2.

## Reviewed changes and evidence

| Area | Status / reference | Correction and regression |
| --- | --- | --- |
| Admitted test version | High / CONFIRMED integrity gap; `server.py:1172` | Revalidate each claimed suite, compare the admission hash and return an infrastructure error before executing a changed version. Version mismatch/source failure tests assert no runner/verdict. |
| Admission I/O | CONFIRMED improvement; `server.py:3040` | Authorize with metadata and the required test hash. No hidden test download in admission. Synthetic test guards both full loaders; missing hash rejects before admission. |
| Lost admission response | Medium / CONFIRMED pre-existing defect; `server.py:953`, `server.py:3104` | Successful admission/status retrieval could fail on an additional diagnostics RPC. Advisory queue count now becomes JSON null when unavailable; admission/quota/lease/auth RPCs remain fail closed. Explicit diagnostics-outage test failed before the correction and passes after it. |
| Unknown queue count | CONFIRMED UI correction; `static/app.js:2109` | Null/missing/invalid count shows generic queued text, not first-in-line. Known numeric counts preserve existing behavior. Asset app.js advances to v52. |
| Problem cache/catalog | Medium / CONFIRMED; `problem_store.py:84`, `problem_store.py:364` | Include updated_at in invalidation/cache checks; paginate a bounded catalog instead of truncating at 1000. 1201-row and same-test-hash metadata-update regressions. |
| Contest reads | CONFIRMED optimization; `server.py:3576`, `server.py:3679` | Batched per-user registration, complete participant pagination, one detail registration check, published-problem filtering and freeze/tie parity. Zero/one/200/1200 contests, 6001 registrations, capped pages and empty-filter cases run. |
| Cache privacy | CONFIRMED policy/race defects; `functions/api/[[proxy]].js:60`, `functions/api/[[proxy]].js:162`, `static/app.js:623`, `static/app.js:945` | Credentials skip shared cache; origin privacy/Vary/Set-Cookie respected; policy namespace excludes old entries; contests never shared. Browser cache generation/promise/view ownership guards account switching, refresh and pending verdicts. Current-identity problem filtering removes late admin rows. Actual exploitation of prior edge behavior was not demonstrated. |
| API startup | CONFIRMED conditional availability defect; `server.py::validate_runtime` | API role can start with zero derived judge slots; worker/combined roles still refuse. Diagnostics still required. Not an observed production outage. |

WeakMap indexing preserves first duplicates and string/numeric ID distinction.
All existing problem changes replace arrays; future in-place ID mutation would
need index invalidation. Intl/escaping parity regressions run. Reused formatters
pick up an OS timezone change after reload. Lazy admin and parallel announcement
requests retain backend permissions and navigation/identity guards.

Cloudflare behavior was reviewed against the official
[Cache API documentation](https://developers.cloudflare.com/workers/runtime-apis/cache/).
Proxy tests use Node's VM with mocked platform objects, not a deployed Workers
runtime. Actual Cloudflare rollout/runtime smoke is still required.

## Verification executed on this exact implementation

Host: macOS Apple Silicon. Tests: Docker Linux ARM64, root, Python 3.11,
GCC/G++, 2 CPUs / 1536 MiB, network disabled, synthetic fixtures only.

- Python: **284 run, 281 pass, 3 module skips, zero failure/error**.
- Critical gate: **204/204 pass; zero skips**.
- JavaScript: **76/76 pass; zero skips** (Node 24.15 on macOS).
- Python compileall, JavaScript syntax, DOM/icon and design-token guards pass.
- Docker build, packaged imports, packaged plagiarism self-test and pip check pass.
- git diff --check and candidate secret-pattern scan pass. Pattern scans are not
  proof that every possible credential is absent. No AGENTS.md/agent.md, env,
  private keys, real hidden tests or production data were added.

Skipped modules: `test_api_e2e`, `test_judge_limits`, `test_problems_supabase`
require the private problems directory. The validator explicitly reports no
problems and skips; its exit zero is **not** verification of 68 actual packages.
Critical synthetic compiler/API/redaction/queue/auth checks run independently.
No production OAuth login, user submission, database permission or data mutation
was performed during this release review. Existing SQL schema/RPCs are unchanged;
this round did not rerun the separate disposable PostgreSQL suite.

Reproduce on a sanitized Linux/root checkout with Python 3.11/GCC:

```sh
python -m unittest discover -s tests -v
python tools/run_critical_tests.py
python -m compileall -q grader.py server.py problem_store.py tools deploy/ec2
node --check static/app.js
node --test tests/test_*.js
node tools/check_frontend.js
node tools/check_styles.js
python tools/validate_problem.py
python tools/plagiarism.py
```

## Measurements and limitations

[Recorded synthetic results](single-worker-benchmark.json): 50 in-process samples,
200 contests/registrations and 2000 scoreboard rows, FakeSupabase, **zero network
latency**. Contest list: 4 queries cold / 3 warm (original 202 / 201). Empty list:
one query. Cold admission: 4 table queries / zero Storage downloads (original
5 / 2). These are workload-specific query counts, not production latency claims.

Latest cold admission p50/p95 is 1.144/3.046 ms. That p95 is worse than the earlier
pre-DeepSeek synthetic 1.363 ms; the change has not established a wall-latency win.
Correctness and measured reduction in private test I/O justify the correction,
not a microbenchmark speedup claim. Respecting private origin cache headers may
also slow a first anonymous browse. Real Cloudflare/API/Supabase layer timing,
Google OAuth, one-worker admission/poll/history smoke and production error-rate
verification remain rollout gates. Passing tests do not prove sandbox security;
S04 and the two-worker verdict fairness finding are still open.

## Host resize update

The user confirmed **t3.small / 2 GiB**, matching the refreshed Console
observation at 15.135.225.193. Services/health passed in the resize review;
instance selection is resolved. Native judge qualification of the resized host
remains pending; see [2-GiB readiness](TWO_GIB_HOST_READINESS.md). Treat the older
host observations below as historical, not current hardware proof. No instance
or service was changed by this review.

## Production preparation: separate approval required

Read-only inventory still found API, the singleton worker and tunnel active,
current backend release `6cba18c68366993fed7fc7572c87368bbb773ea9`. No service was
changed in this review. `server.py` and `problem_store.py` at that production Git
base match repository base 25523f7; the selected backend diff is therefore direct.
Intervening repository history also contains frontend/backup/docs changes:
review the **full** 6cba18c-to-release file list before a deployment, not merely
the two new implementation commits. No backup/service/tunnel configuration is
authorized for incidental activation. No backup Python service was present in
the inspected loaded service inventory; this is not proof no external job exists.

Approval must name the final reviewed commit/artifact and separately cover:

1. Push/merge/Pages publication, if wanted. Do not push main automatically:
   Cloudflare Pages auto-deploys it. Confirm preview protection before any branch
   publication that might create a publicly reachable preview.
2. EC2 application rollout: record current release and active service/env state;
   verify backup/restore, pause admission, freshly drain queue/leases, stop the
   singleton after cleanup, install the reviewed artifact without changing
   service budgets/topology/data source, restart and verify one worker.
3. Backend first, then the approved frontend/proxy artifact. Preserve route,
   OAuth/SMTP/secrets and database schema. Validate real approved login plus own
   synthetic submit/poll/history and contest feedback concealment; confirm v52.
4. Reopen admission only after acceptance checks; observe queue/errors/resources.

No production approval is inferred from approval to review/prepare this release.
No additional maintenance or rollout was performed in this review.

## Rollback

Before deployment, record the actual previous backend path and exact previous
Pages deployment ID. On an approved rollback: pause and drain, let runner cleanup
finish, restore the recorded old current symlink and restart only API/singleton,
then roll Pages back to its recorded deployment through the existing route.
Keep Supabase rows/objects, protected configuration and the newer UID ledger.
Do not restore an older ledger, delete queue jobs, revive JustRunMy, enable
worker2, change problem limits or rotate secrets as part of this rollback.
Verify health, ownership/privacy and one-worker completion before reopening.
This review did not execute a production deployment or application rollback.

Local reviewed commits can be reverted on a separate review branch in reverse
order with git revert; preserve the original dirty optimization worktree.
