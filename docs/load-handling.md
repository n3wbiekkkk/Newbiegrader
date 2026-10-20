# Load handling and rollout

The frontend stays static and FastAPI remains the API. Judge work now runs in supervised subprocesses; compilation, submissions, playground runs, and rejudges share host execution slots. Tests within a submission run serially. Output streams are bounded during collection, and timeout/cancellation waits for process cleanup before returning a slot.

## Queue modes and roles

`GRADER_QUEUE_MODE=local` with `GRADER_ROLE=combined` is the compatible default. Run one Uvicorn process in this mode. The process owns admission, the local queue, and workers; Supabase job rows support recovery when configured. Missing legacy schema can still degrade to memory in local mode. This mode is not a coordinated multi-instance queue.

`GRADER_QUEUE_MODE=database` requires the appended queue migration in `supabase/schema.sql`. Admission, per-account quotas, job claims, heartbeats, completion fencing, and history persistence use service-role-only RPCs. A database failure rejects new work rather than silently accepting a local-only job. Status reads use shared database state. Students take priority over queued bulk rejudges; rejudge admission cannot exceed the queue's remaining space.

Roles in database mode:

| Role | Command | Responsibility |
|---|---|---|
| `combined` | `python server.py` or Uvicorn | HTTP API and judge consumers |
| `api` | `uvicorn server:app --host 0.0.0.0 --port 8000` | HTTP only; playground requests also delegate to workers |
| `worker` | `python worker.py` | Judge consumers without an HTTP listener |

The Docker entrypoint selects the command from `GRADER_ROLE` and uses `PORT` for HTTP. Separate roles require database mode and an explicit stable `SESSION_SECRET`. All API replicas must share that secret. Each deployment needs the same problem packages, engine version, and appropriate Supabase environment. Keep the service-role key server-side.

## Host capacity

Defaults derive from cgroup CPU/RAM limits. The scheduler reserves interpreter/API memory and budgets each active job for its supervisor plus the larger compiler/test address-space ceiling, including the enabled languages’ memory multipliers and virtual headroom. It caps requested worker count to both CPU and memory capacity. `GRADER_JUDGE_JOBS` no longer enables concurrent tests: effective test parallelism is one. Large worker/memory overrides cannot override the host safety calculation. Inspect `/api/version` for effective values.

For a 512 MB host, the corrected default declared cap is **85 MB**, not 256 MB:
170 MB API reserve + 340 MB per job fits within 512 MB. Python's threshold is
212.5 MB and its RLIMIT_AS is 276 MB; compiler RLIMIT_AS remains 256 MB. These are
per-process limits and a scheduler estimate, **not a hard aggregate process-tree
limit**. Output buffers, cached problem data and descendants can exceed estimates.
Per-job cgroup memory/pids/CPU and workspace bounds remain public-launch gates.

OS file locks coordinate processes that share `GRADER_CAPACITY_DIR` (default: `newbiegrader-capacity` under the system temporary directory). Processes sharing one machine allocation must use the same directory and matching capacity settings. Containers sharing one CPU/RAM allocation need a shared writable mount at that directory. Independent hosts have independent slot budgets and coordinate job ownership through PostgreSQL. Container CPU/RAM limits must reflect the resources actually reserved for each container.

Keep one judge execution on the documented 0.5 vCPU/512 MB server. For a first capacity trial, use **2 vCPU/2 GB** with `GRADER_MEMORY_CAP_MB=512`, leave worker count automatic, and keep serial tests. For larger contest bursts, trial **4 vCPU/4 GB** with the same per-test cap after measuring. These are starting configurations, not measured production capacity guarantees. Increasing queue depth accommodates a backlog; adding usable CPU/RAM increases judging capacity.

## Browsing latency and compile warmup

The API serves the problem catalog from an in-process snapshot. A TTL refresh
runs on a daemon thread and leaves the current snapshot readable while the
Supabase query is in flight. The refresh selects the lean metadata columns
(without `statement_md`); unchanged rows keep their cached statement, while a
changed or no-PDF row fetches its statement once on detail. No refresh downloads
problem files.

Public detail responses are `private, max-age=60`, samples are
`private, max-age=300`, and PDFs are `private, max-age=600`. Contest-hidden or
admin-visible responses are shortened to 30 seconds. All remain `Vary: Cookie`;
there is no shared/CDN cache of authenticated responses. The frontend also starts
the PDF frame from the list's `has_pdf` flag and prefetches the PDF/samples after
detail render, so repeated opens are served from the browser cache.

Build the optional C++ PCH as root after a compiler/toolchain update:

```sh
sudo python3 tools/build_cxx_pch.py
```

The default destination is `/usr/local/lib/newbiegrader/pch/cxx`, which is
readable by the Landlocked compile sandbox. The grader adds `-I` only when
`bits/stdc++.h.gch` exists; a missing or rejected PCH falls back to a normal
compile. Rebuild the PCH whenever `g++` or its headers change, and remove it if
the toolchain becomes incompatible.

## Rollout order

1. Complete the [Linux validation checklist](linux-validation-todo.md). Windows checks and embedded PostgreSQL assertions have been run locally; they do not validate the production Linux sandbox.
2. Trial the new revision against a disposable database and test accounts. Build the image, run all checks, and exercise both local and database modes.
3. For a local-to-database transition, stop admissions, drain jobs if practical, and stop all old local-mode processes. Have the maintainer apply the complete idempotent `supabase/schema.sql` in Supabase SQL Editor. Do not run a mixed local/database fleet. Legacy running rows without ownership receive an expired lease so database workers can reclaim them; live leased ownership is left alone.
4. Start one combined instance in database mode, verify health/version, admission, judging, history, ownership, and redaction, then add dedicated workers or API instances as needed. API-only mode requires an available worker fleet.
5. Deploy the backend before frontend changes that depend on it. Verify effective limits and watch queue wait, errors, memory, and throughput. Upgrade paid infrastructure only after choosing an allocation and budget.

To roll back queue mode, stop every database consumer and resolve/drain in-flight jobs first. Do not enable local recovery while database workers are alive.

## Measuring load

`tools/load_test.py` uses the standard library and requires explicit `--execute --test-installation`. Its default target is loopback; remote installations require `--allow-remote`. Use a disposable test database and accounts, never production credentials. Existing test accounts can be supplied through `NG_LOAD_ACCOUNTS`; `--register` creates throwaway accounts on the test installation.

```sh
python tools/load_test.py --execute --test-installation --register \
  --target http://127.0.0.1:8094 --users 4 --bursts 2 \
  --job-timeout 90 --playground-every 3
```

The JSON report includes API latency percentiles, admitted/completed attempts, throughput, HTTP/error counts, and submission queue/service durations. Timings use server timestamps where available and label polling estimates otherwise. Read completion counts alongside latency; quick rejected requests do not establish judging throughput. Use host/container monitoring for peak RSS, throttling, and OOM events.

The committed CI workflow includes normal Python/Node checks plus a disposable PostgreSQL job that applies the migration twice and exercises real SQL admission, quotas, leases, fencing, priority, and completion behavior. Running CI remotely and Linux deployment validation remain separate from local checks.
