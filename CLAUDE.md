# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Overview

Newbiegrader is an online judge (Thai competitive-programming instruction) for Python 3, C11 and C++17 submissions. Backend is FastAPI + a stdlib-only judging engine; frontend is plain HTML/CSS/JS with no build step; DB/auth/durable queue is Supabase (Postgres). Production: Cloudflare Pages (frontend, `functions/api/[[proxy]].js` proxies `/api` to a private Worker → VPC service → named QUIC tunnel) + a native Ubuntu PC (systemd API plus four isolated `newbiegrader-worker@N` judge units under one cgroup slice). EC2 is retired. See `docs/PRODUCTION_ARCHITECTURE.md`, `docs/HOST_DEPLOYMENT.md` and `docs/HOST_CLOUDFLARE_SETUP.md`.

## Commands

CI (`.github/workflows/ci.yml`) is the source of truth. Locally:

```
pip install -r requirements.txt            # add httpx for tests
python server.py / container_entrypoint.py # run API (Docker CMD uses container_entrypoint.py); copy .env.example to .env
node --check static/app.js
node tools/check_frontend.js               # frontend id references
node tools/check_styles.js                 # no colour literals, dark-mode coverage
node --test tests/test_*.js                # frontend tests
python tools/validate_problem.py           # validate problem set
python -m unittest discover -s tests -v    # all Python tests (API e2e uses tests/fake_supabase.py)
python -m unittest tests.test_judge_limits # a single test module
python tools/run_critical_tests.py         # critical security canaries (CI runs as root on Linux with gcc/g++; any skip fails)
python tools/plagiarism.py                 # plagiarism self-test
```

SQL tests (`tests/*_sql.sql`, `queue_concurrency.py`, `auth_concurrency.py`) run against a disposable Postgres 17 after applying `supabase/schema.sql` twice (it must be idempotent/re-runnable; migrations are append-only).

## Architecture

- `grader.py` — the single judging engine (stdlib only). All verdicts must flow through its entry points; never duplicate judging logic in request handlers.
- `server.py` (~4.5k lines) — FastAPI app: auth (Google + email, `email_auth.py`; server-side session revocation on logout), Turnstile/edge abuse gating, job queue, quotas, contest/practice visibility policy, result redaction.
- `judge_execution.py` — credential-free job execution shared by the API and the isolated runner; stdlib + `grader` only, never imports the web app or database client.
- `database_client.py` — pooled HTTP/1.1 PostgREST transport for workers (avoids HTTP/2 GOAWAY); ambiguous RPC failures are never auto-replayed.
- `judge_runner.py`, `job_sandbox.py`, `job_resources.py` — supervised bounded execution (rlimits, privilege drop via private UIDs, Landlock, network namespace/syscall filter). Linux-specific; many tests need Linux/root (hence the env vars `GRADER_RUNNER_CHILD`, `GRADER_ALLOW_UNISOLATED_JUDGE`, `GRADER_REQUIRE_NETNS` in CI).
- `worker.py` — dedicated worker role (one judge job per unit, serial tests per job). `GRADER_QUEUE_MODE=database` gives durable leased queue (RPCs in `supabase/schema.sql`); default `local` is in-memory best-effort.
- `problem_store.py`, `backend_problem_files.py` — problem metadata from Supabase; PDFs, samples and private tests served from backend disk (`GRADER_FILE_STORAGE=local`). `problems/` is a local working copy and is not versioned.
- `static/` — frontend (`app.js`, `index.html`, `styles.css`, `config.js`, `turnstile.js`); deployed to Cloudflare Pages.
- `tools/` — problem authoring/validation/publishing, statement builds, load tests, host canaries. Authoring workflow: `docs/making-problems.md`, templates in `tools/templates/problem/`.
- `deploy/host/` — native PC deployment assets (systemd units, nginx, backup/health/alert timers, Discord presence, `requirements.lock`, verify scripts). `tools/host_*canary*.py` are the live-host canaries.
- `docs/releases/*.json` — scoped qualification/performance measurements; `docs/SESSION_REVOCATION.md`, `docs/PUBLIC_SECURITY.md`, `docs/SECURITY_READINESS.md` record the security posture.

## Key invariants

- Controlled feedback: every result passes through the practice/contest disclosure policy before reaching a client and before being stored (`docs/submission-feedback-policy.md`). Contest hidden tests never expose input/expected/actual; practice data once disclosed can't be re-secreted by reuse in a contest.
- Every recorded verdict is traceable to the test set and grader version (`grader.py` version, shown in README badge) that produced it — bump deliberately.
- Secrets come from host env, never files in the image; `.env` is gitignored.
- When adding a Python module that the server imports, also add it to the `COPY` line in `Dockerfile` and the `compileall` step in CI (which also compiles `tools` and `deploy/host`).
- Production dependencies are pinned and audited with `pip-audit`.
