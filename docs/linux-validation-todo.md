# Linux validation to do

Status: **pending**. The user deferred Linux execution on 2026-10-15 because WSL on this workstation is broken. Windows tests and embedded PostgreSQL checks do not establish Linux sandbox or process-tree behavior. Run these checks on a disposable Linux host before production rollout; record the date, host allocation, commit, commands, and results below.

## Automated checks

- [ ] Use Python 3.11, Node.js, GCC/G++, and the pinned requirements. Run `python -m unittest discover -s tests -v`; Linux/POSIX tests must execute rather than skip.
- [ ] Run `python tools/validate_problem.py` with its default single worker, `python tools/plagiarism.py`, and `python -m compileall -q grader.py server.py judge_runner.py worker.py container_entrypoint.py tools`.
- [ ] Run `node --check static/app.js`, `node tools/check_frontend.js`, `node tools/check_styles.js`, and `node --test tests/test_job_polling.js`.
- [ ] Build the production Dockerfile and run the runner regressions as root inside the image, mounting `tests/` into `/app/tests` read-only. Verify submissions actually drop privileges to `nobody` and cannot read protected problem files.
- [ ] Run the PostgreSQL CI job against a disposable PostgreSQL database. Apply `supabase/schema.sql` twice, then `tests/queue_sql.sql`; verify the browser roles cannot execute queue RPCs. CI configuration is committed but has not been run remotely by this session.

## Process cleanup and resource limits

- [ ] Confirm total timeout and repeated cancellation kill and reap all descendants, including `setsid`, double-forked children, and children whose immediate parent has already exited. Check for surviving processes and zombies before capacity is reused.
- [ ] Terminate an API/worker process during a job, including an abrupt kill. Confirm supervisor parent-death handling and reaping; restart and verify leases recover jobs without overlapping surviving execution.
- [ ] Test infinite stdout, infinite stderr, compiler diagnostics, a program that never reads stdin, and a descendant that keeps pipe descriptors open. Memory must stay bounded and cleanup must complete.
- [ ] Verify signal exits retain existing RE/MLE classification, and confirm RLIMIT_AS/DATA, CPU, file size, process count, core dump, and file descriptor restrictions still apply through the standalone sandbox launcher.
- [ ] Test a C/C++ compilation that exceeds its memory/time budget. Confirm the compiler and its children terminate and the next job can run.
- [ ] Confirm best-effort network namespace behavior on the actual host and preserve protected problem-directory permissions. Do not interpret a host refusing network namespaces as verified network isolation.

## Queue and role integration

- [ ] With two API instances and two worker processes using a disposable database, submit simultaneous requests from one account and from different accounts. Verify per-user admission, shared quotas, queue maximum, and one accepted completion per job attempt.
- [ ] Test worker crash, database interruption, lease expiry, and stale completion while another worker owns the job. Status polling must not alter a running worker's ownership token.
- [ ] Verify API-only mode never compiles or executes code, including `/api/run`; it must delegate playground jobs to workers and return their output without creating submission history.
- [ ] Verify same-host processes share the capacity directory; containers sharing one CPU/RAM allocation need a shared mount and matching limits. Mix playground, submissions, and rejudges and confirm the configured execution cap is respected.
- [ ] Run contest/ownership/redaction checks across API and worker roles; no hidden-test input, expected output, or diff may appear in persisted student feedback.

## Load and sizing

- [ ] Run `tools/load_test.py --help`, then use explicit execution flags against a disposable test installation. Include Python and C++ bursts, mixed playground runs, near-full queues, and rejudges.
- [ ] Record API p95 latency, queue wait, service time, completed jobs/minute, peak RSS, CPU throttling, OOM events, and timeout/error counts on the proposed server allocation.
- [ ] Compare the current 0.5 vCPU/512 MB allocation with 2 vCPU/2 GB, and consider 4 vCPU/4 GB only if queue wait remains unacceptable. Use the effective limits reported by `/api/version`; a larger queue does not increase throughput.

## Results

Pending user-run Linux validation.

### Disposable-container results 2026-10-15 (not a substitute for prod-host run)

Env: Docker `python:3.11-slim` (+gcc, procps, FastAPI deps), Linux 6.8
aarch64, root; prod `Dockerfile` also built and probed. No secrets mounted.
Engine files identical to working tree (P0-6 touches only
server.py/tests/test_api_e2e.py/tools/load_test.py).

- `test_judge_runner` (14 tests incl. 2 new strict-mode tests): 14/14 OK,
  both with stock caps and with `--cap-add=SYS_ADMIN`.
- Probes: uid/gid drop to 65534 + empty groups OK; protected files
  (`0700`/`0600`, prod image layout) unreadable as `nobody` OK; TLE/MLE/
  rlimits/descendant-reaping/env-scrub/cleanup OK; AC/WA/TLE/MLE/OLE/RE
  verdict matrix OK under strict mode with working netns.
- Network: `unshare(CLONE_NEWNET)` fails EPERM on stock Docker and judged
  code keeps egress (DNS + TCP OPEN) — see F-1. Fixed by code: strict
  mode (`GRADER_REQUIRE_NETNS=1`) refuses before exec (exit 126, canary
  absent); with caps, egress is denied and verdicts stay correct.
- Same-uid tmpdirs: sibling read of 0644-in-0755 by absolute path
  succeeds — isolation rests on unguessable tmp names (see F-2).
- Pre-existing macOS-only failures (RLIMIT_AS, subreaper supervision)
  do not occur on Linux; they are platform artifacts, not regressions.

### Strict boot-contract results 2026-10-15 (same disposable env)

- `validate_runtime` on Linux+root refuses boot with `GRADER_REQUIRE_NETNS`
  missing, `=0`, and `=1`-without-namespace (explicit RuntimeError, no
  workers spawned); boots with `GRADER_ALLOW_UNISOLATED_JUDGE=1`, with
  `GRADER_ROLE=api` (exempt, never executes), and with `=1` where the
  namespace probe passes.
- Committed `IsolationPosture` matrix (7 tests) pins the contract on all
  platforms; the namespace probe itself is covered by real runs, never
  mocked green.
