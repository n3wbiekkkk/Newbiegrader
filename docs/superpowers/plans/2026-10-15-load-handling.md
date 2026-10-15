# Load Handling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Safely absorb bursts, separate web responsiveness from judge compute, and enable coordinated workers.

**Architecture:** Supervised job subprocesses share resource admission. An opt-in PostgreSQL queue coordinates separate API/worker roles with fenced leases; local mode remains supported.

**Tech Stack:** Python 3.11 standard library, FastAPI, Supabase/PostgreSQL, vanilla JavaScript, unittest, Node.js.

**Spec:** `docs/superpowers/specs/2026-10-15-load-handling-design.md`

## Global Constraints

- One owner per judging file; no concurrent edits of server.py or grader.py.
- No production credentials in files/output; do not read .env or .git/config.
- Preserve sandbox limits, visibility checks, and result redaction.
- SQL changes are append-only, idempotent, service-role-only; maintainer applies migration.
- No commits by implementers; root commits only after independent review and checks.
- Work on feature branch improve-load-handling in the shared workspace, with disjoint file ownership. The user explicitly requested parallel agents and review before commit.

## Review Focus

- Timeout/cancellation with nested children, compilation, and excessive output must actually free capacity.
- Concurrent same-user submissions, playground plus submit, and nearly-full rejudges must obey admission.
- Two workers must not claim one job; expired attempts must not store or overwrite newer results.
- API-only mode must not run code; database outages must not silently fall back to local mode.
- Persisted and returned feedback must preserve contest and hidden-test policies across roles.

### Task 1: Supervised execution and bounded output

**Files:** `grader.py`, new `judge_runner.py`, new runner/grader tests.

**Interfaces:** Export `async run_isolated(kind: str, payload: dict, timeout: float) -> dict` from judge_runner.py. Kinds are `submission` and `playground`. Submission payload: problem (ID), ext, source, reveal, memory_cap_mb, judge_jobs. Playground adds stdin_data, time_limit, memory_mb; problem may be null. Raise TimeoutError on total timeout, propagate cancellation only after cleanup. Child reuses server.run_submission/server._run_playground; no duplicate judging logic.

- [ ] Add failing tests for hard timeout/cancellation and bounded stdout/stderr, including descendant cleanup where supported.
- [ ] Implement supervisor and safe sandbox launch; preserve grader API/CLI and resource limits.
- [ ] Run targeted tests and report files, evidence, and platform limits to root.

### Task 2: Admission, durable queue, roles, and API integration

**Files:** `server.py`, `supabase/schema.sql`, `tests/fake_supabase.py`, new queue/admission tests; existing API tests only when required.

**Interfaces:** Consume judge_runner.run_isolated as defined in Task 1. Define explicit GRADER_QUEUE_MODE=local|database and GRADER_ROLE=combined|api|worker. API-only playground uses a durable job but still awaits and returns its result. Worker-only entry point is coordinated with root. Expose actual effective capacity and queue mode in version/admin diagnostics.

- [ ] Add regression tests for atomic admission, shared claims, leases/fencing, authoritative status, database failure, role separation, and redaction.
- [ ] Implement conservative global capacity, atomic local admission, remaining-capacity rejudges, and supervised execution for all code paths.
- [ ] Append SQL admission/claim/heartbeat/finish RPCs and migration. Provide faithful fake RPC behavior with thread safety.
- [ ] Integrate database mode and roles; audit async handlers for synchronous database I/O.
- [ ] Run targeted and existing API tests; report operational configuration and migration requirements to root.

### Task 3: Polling and local load measurement

**Files:** `static/app.js`, `static/index.html`, new `tools/load_test.py`, focused polling/load tests if needed. Root owns README.md and agent.md.

- [ ] Implement bounded adaptive polling with jitter; preserve timeout, ownership, errors, and localStorage resume.
- [ ] Bump app asset version.
- [ ] Add opt-in load harness with loopback target by default, explicit authorization for remote targets, no embedded credentials, and useful latency/throughput/wait/error reporting.
- [ ] Run Node checks and harness checks; report usage and evidence.

### Task 4: Integration, rollout docs, verification, and review

**Files:** `Dockerfile`, `.env.example`, `.github/workflows/ci.yml`, `README.md`, `agent.md`, capacity/role entry point as needed.

- [ ] Integrate subprocess/queue interfaces and Docker copies/role entry point.
- [ ] Document migration, safe single-host configuration, separated roles, shared secret, and deployment sequence.
- [ ] Run compileall, all Node guards, all unittest tests, problem/reference validator, plagiarism self-test, and local load smoke test.
- [ ] Dispatch independent review of the complete uncommitted diff; fix important findings and verify fixes.
- [ ] Commit reviewed changes; report evidence, remaining platform limits, migration steps, and server-sizing recommendation. Infrastructure changes remain a separate decision.
