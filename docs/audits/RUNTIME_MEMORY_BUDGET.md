# S04 runtime budget correction — 2026-10-18

Base: `9cffd13`; branch `fix/p0-runtime-memory-budget`.
**Historical implementation checkpoint; scheduling correction is now deployed.**
Current host blocker and follow-up: [S04_HOST_HANDOFF.md](S04_HOST_HANDOFF.md).
**High · CONFIRMED accounting flaw · partially corrected.**
Production OOM is LIKELY, not reproduced. Aggregate containment remains OPEN.

## Evidence and smallest correction

- `server.py:174` (`_derive_capacity`), `grader.py:742` (`mem_limit_mb`),
  `grader.py:748` (`enforced_memory_mb`), `judge_runner.py:347` (compiler ceiling).
- The old scheduler reported 320 MB/job for declared cap 256 MB. Python actually
  receives threshold 640 MB and RLIMIT_AS 704 MB, before supervisor overhead.
  Four new synthetic arithmetic tests ran before the fix and failed in 20
  assertions/subtests, including `320 not greater than or equal to 768`.
- Budget the maximum enforced address-space ceiling across **enabled** API
  languages, the compiler's `max(256, cap)` ceiling and the existing 64 MB
  supervisor allowance. Binary-search the largest declared cap that fits the
  available budget. Preserve language allowances/headroom, CPU clamp, serial
  tests and refusal to start a worker when no slot fits.
- 512 MB example: 170 MB API reserve, declared cap **85 MB**, Python threshold
  **212.5 MB**, Python RLIMIT_AS **276 MB**, compiler ceiling **256 MB**,
  per-job estimate **340 MB**, one worker. This is a planned effective-limit
  change, not a change to problem PDFs or declared metadata. The existing API/UI
  reports the effective capped limit. Engine version bumped to **2.0.3**.
- `tests/test_critical_memory_budget.py:16` checks actual ceilings rather than
  declared cap only; covers override matrices, insufficient RAM and enabled
  language changes. `tests/test_host_limits.py:82` now invokes the real function
  instead of repeating the obsolete cap=RAM/2 arithmetic.

## Verification

- Disposable Linux arm64/root, kernel 6.8, Python 3.11, Landlock ABI 4, network
  disabled; no real user workloads or OOM/fork-bomb payloads.
- Critical: **123 passed, zero skips** (24.396 s), including the four new tests.
- Full suite: **263 passed, zero skips** (95.736 s), including the updated
  preexisting host-capacity test.
- All **68** trusted private reference solutions passed **1,178/1,178** fixtures
  through `server.run_submission` with the derived **85 MB** cap and per-job
  UID/Landlock enabled. The disposable validation container had 1 GiB total RAM
  for the trusted driver; this does not prove 512 MB host stability under load.
- Production read-only GET from audit Mac still reports 0.5 CPU, 512 MB,
  cap 256 MB, 320 MB/job, local queue/combined role/Supabase source, engine 2.0.0.
  Mac public IP/network category is unknown. No production configuration changed.
- Evidence: `~/.local/share/newbiegrader-validation/submission-feedback-kc67osyx/`:
  `capacity-before.log`, `capacity-critical.log`, `capacity-full.log`,
  `capacity-full-final.log`, `web-references-85mb.log`.

## Remaining risk / release gate

This is scheduling arithmetic, **not hard process-tree enforcement**. RLIMIT_AS
is per-process address space, not aggregate RSS. Compiler and runtime descendants,
stream buffers, cached problem bytes and supervisor memory can exceed estimates;
64 MB is an existing allowance, not a measured worst-case bound. Parent-only RSS
sampling remains; the swallowed rlimit failures described at this historical
checkpoint were subsequently fixed and deployed (`b1531ba`). Per-job cgroup memory/pids/CPU and
workspace bounds require a reviewed host configuration; no added capabilities,
privileged mode, network relaxation or namespace bypass was introduced.

The existing 512 MB deployment cannot promise every 256 MB compact-language
solution will run. The corrected effective cap is disclosed, and references
passed; other valid larger programs may need more RAM. Retain the current
architecture and provision a measured budget rather than restoring unsafe math.

Deploy only after reviewing the isolation prerequisites in JOB_ISOLATION.md and
staging/host compatibility. Reverting this commit restores under-budgeting and
is not a secure public-launch fallback. Do not reset the UID ledger on rollback.
