# Production performance quick wins — 2026-10-19

Status: deployed and verified on production.

## Scope

This release reduces the user-visible cost of opening a problem, reading its
statement/samples, and receiving a verdict. It does not change the database
schema, authentication, queue ownership rules, result redaction, file-storage
layout, or API routes.

| Item | Value |
|---|---|
| Backend release | `/opt/newbiegrader/releases/7f3efd784460bb698451b93342739601f3b01f37` |
| Backend Git commit | `7f3efd7` (`perf/quick-wins`) |
| Frontend Git commit | `3c3f140` (`perf/quick-wins`) |
| Production Pages deployment | `cb670741-0215-4ac5-b8f7-cc3fcb902269` |
| Previous production Pages deployment | `86672f4e-d8e7-4657-8665-a3e1c9610f31` (`dc01694`) |
| Previous backend release | `/opt/newbiegrader/releases/609bbf1f49c510d914c440763bb2304a45db376e` |
| Api version build fingerprint | `9a4f860ad21d8677eb9b7df48cf9f4eae6cdcc669cf67a942d44f2f8cb5854e0` |
| Frontend asset | `app.js?v=54`, SHA-256 `f73f5ce09393867d8aa5f72b67974561e895c3a785abdc476fea9306526bf321` |
| C++ PCH | `/usr/local/lib/newbiegrader/pch/cxx/bits/stdc++.h.gch`, 101,404,797 bytes, SHA-256 `1d5898747830c761eae5089fce531a468ab8345e4f2de0ab18d3a381bc09ec93` |

`origin/main` remains `dc01694`. No existing branch was rewritten, reset,
deleted, or force-pushed. The work was committed only to
`perf/quick-wins` and published to `origin/perf/quick-wins`.

## Changes

### Catalog and detail

- The catalog refresh is stale-while-revalidate: a daemon thread loads the new
  snapshot while the current snapshot remains readable. Requests no longer wait
  for the periodic Supabase query.
- Refreshes select the lean snapshot columns. `statement_md` is no longer part
  of the periodic 68-row read.
- Unchanged problems keep their cached statement while a refresh is applied.
  A changed or no-PDF problem lazily fetches its statement once on detail.
- `/api/problems` now includes `has_pdf`; the frontend uses it to start the PDF
  frame immediately and to schedule a hover prefetch.
- Browser-private cache headers: detail `private, max-age=60`, public sample
  `private, max-age=300`, PDF `private, max-age=600`; hidden/admin responses
  are shortened to 30 seconds. All retain `Vary: Cookie` and no shared cache
  stores authenticated responses.

### Frontend

- Problem-list cache key was bumped to `ng_problems_v2`, so a list cached before
  this release cannot hide the new `has_pdf` field for up to an hour.
- Hover/focus on a problem card prefetches the detail and (after 180 ms) the PDF.
  Clicking starts the PDF iframe from `has_pdf` without waiting for detail.
- Public samples are fetched in parallel after detail render, with in-flight
  dedupe and a prefetch hook.
- Job polling starts at 700 ms (600 ms floor), backs off to a 4 s cap, and keeps
  the four-minute stop. Database worker idle polling now caps at 1 s instead of
  2 s.
- Cache generations clear samples/PDF prefetch state on identity changes, so a
  late response cannot repopulate another user's view.

### C++ compile warmup

`tools/build_cxx_pch.py` builds and verifies a precompiled `bits/stdc++.h` under
`/usr/local/lib/newbiegrader/pch/cxx`. The default location is inside `/usr`
because the Landlocked compile sandbox already has read access there. The grader
adds `-I` only when the `.gch` exists; a missing or incompatible PCH falls back
to the normal compile. The builder verifies the PCH with the same `-I`, `-O2`,
`-std=c++17`, `-Wall -Wextra` flags, and installs the tree world-readable for
the unprivileged compile sandbox.

On the production host, three synthetic C++ compilations measured:

| Mode | Seconds |
|---|---|
| PCH (three runs) | 0.595, 0.576, 0.571 |
| No PCH (three runs) | 1.759, 1.859, 2.033 |

## Verification

- `python3 -m unittest discover -s tests`: 263 tests, 21 skipped. Three
  environment-only errors remain on the macOS/Python 3.9 operator host:
  `/proc/self/status` cgroup test, and two existing `Path | None` imports under
  Python 3.9. No product-test failure remained.
- `node --test tests/*.js`: 0 failures.
- `node tools/check_frontend.js`: OK (159 ids, 17 icons, 25 symbols).
- `node tools/check_styles.js`: OK (86 tokens, 46 dark overrides).
- Candidate API canary on loopback port 8099: 68 problems, 68 `has_pdf`, detail
  `private, max-age=60`, sample `private, max-age=300`, PDF
  `private, max-age=600`.
- Production HTTPS smoke: **15/15 passed** before and after reopening admission.
- Production `/api/version`: `problem_source=supabase`,
  `problem_file_storage=local`, 68 problems.
- Playwright production check: `app.js?v=54`, 68-row `ng_problems_v2` cache with
  `has_pdf`, hover started detail + PDF prefetch, the optimistic PDF frame
  appeared before detail completion, all three samples prefetched, no console
  errors.
- Conditional PDF request with `If-None-Match` returned `304` with the expected
  private cache header.
- One synthetic C++ job using `#include <bits/stdc++.h>` was admitted through the
  same `judge_queue_admit` RPC as the API:
  `cbde78c8-bff8-4339-a93b-5ae8f78159b3`. Result: `done`, attempt 1, verdict
  `REJECTED`, 0/13 passed, exactly one linked submission
  (`ead7519e-6c9a-41ce-944b-871694dd2a47`). The intentional wrong output
  prevented a synthetic user from affecting accepted-solver statistics.
- Final queue: 54 done, 0 error, 0 queued, 0 running. Exactly one API process and
  one worker process; both services `active`, `NRestarts=0`; no worker error or
  OOM lines since deployment; 15 GiB free.
- Hidden sample names and anonymous execution checks remain covered by the
  production HTTPS smoke. No real user login or authenticated HTTP submit was
  performed; the synthetic job exercised the durable queue/worker path directly.

## Observed latency

These are operator-network observations, not a controlled load test. The
backend's Supabase query cost is unchanged (roughly 330–435 ms through Pages for
detail/sample). The main user-visible improvement comes from not serializing the
PDF behind detail, browser-private reuse, and prefetch.

| Probe | Before | After |
|---|---|---|
| `/api/problems` via Pages (warm) | 344–415 ms | 337–449 ms |
| Problem detail via Pages | 330–375 ms | 336–435 ms |
| Public sample via Pages | 326–386 ms | 331–435 ms |
| PDF via Pages, first load | 471–677 ms | 388–705 ms |
| C++ compile `-O2` (no PCH) | about 1.55–2.03 s | unchanged |
| C++ compile with PCH | not enabled | about 0.57–0.60 s |

The Playwright run showed the PDF iframe starting from the list's `has_pdf` flag
before the detail response completed, and a second problem open was served from
the in-memory detail cache with no new detail request.

## Rollback

Backend rollback is an atomic symlink switch, then restart both services:

```sh
sudo ln -sfn /opt/newbiegrader/releases/609bbf1f49c510d914c440763bb2304a45db376e \
  /opt/newbiegrader/current
sudo systemctl restart newbiegrader-api newbiegrader-worker
```

Pause admission (`GRADER_ACCEPT_JOBS=0`, restart the API) before a rollback if
jobs may be active, and inspect/drain the durable queue first. Do not delete the
new release, the PCH, jobs, submissions, or problem files as part of a rollback.

The previous frontend is production deployment
`86672f4e-d8e7-4657-8665-a3e1c9610f31` (`dc01694`, `app.js?v=52`). If a Pages
rollback is needed, deploy the `static/` tree from `origin/main` through the same
Pages project; do not rewrite branches. Removing
`/usr/local/lib/newbiegrader/pch/cxx` is safe but not required: the grader
detects the missing PCH and falls back to a normal compile.
