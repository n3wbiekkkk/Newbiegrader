# Newbiegrader

**An online judge for Thai competitive-programming instruction.**

[![CI](https://github.com/sphetpitak-sudo/gradernew/actions/workflows/ci.yml/badge.svg)](https://github.com/sphetpitak-sudo/gradernew/actions/workflows/ci.yml)
![License: AGPL-3.0-or-later](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue)

Newbiegrader runs submitted code under enforced time and memory limits, judges it against a test set
that is not disclosed to students, and operates as a complete web service with contests, submission
history, plagiarism analysis and administrative tooling.

## What it provides

- **Real limits, not estimates.** Wall-clock timeout plus `RLIMIT_CPU`; `RLIMIT_AS`/`RLIMIT_DATA` per
  test with sampled peak RSS deciding the verdict. Interpreted runtimes get a documented memory
  allowance (Python and Node ×2.5, Java ×3) so students are judged on their algorithm, not on the
  interpreter's object overhead; C, C++, Go and Rust are held to the declared limit.
  Verdicts: `AC`, `WA`, `TLE`, `MLE`, `OLE`, `RE`, `CE`.
- **Undisclosed tests.** Only the samples declared in `config.json` are shown; ten to eighteen hidden
  tests per problem decide the score. Hidden input, expected output and diffs never leave the server.
- **Asynchronous judging.** `POST /api/submit` returns `202` with a job id; workers drain a durable
  queue. A reload, a navigation or a restart does not lose a run or its verdict.
- **Contests, history, leaderboards.** Codeforces-style windows with registration, score freeze and
  score isolation from the global ranking; per-problem statistics; winnowing plagiarism detection.
- **A frontend that keeps the student's work.** Drafts autosaved per problem, Tab/Shift+Tab indentation,
  `Cmd/Ctrl+Enter` to submit, Thai verdict wording, WCAG AA contrast in both themes.

## Stack

FastAPI and Uvicorn on the server; a dependency-free Python standard-library judging engine
(`grader.py`); a vanilla HTML/CSS/JS frontend with **no build step**; Supabase (PostgreSQL) for
history, statistics and contests; judging in disposable child processes under `rlimit` isolation.

```mermaid
graph LR
  B["Browser<br/>static/ · vanilla JS hash SPA"] -->|"/api/*"| P["Edge proxy<br/>functions/api/[[proxy]].js"]
  P --> S["server.py<br/>FastAPI + session cookie"]
  S -->|"202 + job_id"| B
  S -->|"enqueue"| Q[("judge_jobs<br/>+ asyncio.Queue")]
  W["judge workers<br/>JUDGE_WORKERS tasks"] --> Q
  W --> G["grader.py<br/>prepare_command → judge_test"]
  G --> X["child process<br/>rlimits · setuid nobody · no network"]
  W --> DB[("Supabase<br/>service_role only")]
  S --> DB
```

## Getting started

```bash
pip3 install -r requirements.txt
python3 server.py                 # http://127.0.0.1:8000, serves the API and static/
```

Browsing problems and using the CLI need neither an account nor a database. A Supabase project (run
`supabase/schema.sql`) is required only for history, statistics, leaderboards and contests.

The judge also runs standalone:

```bash
python3 grader.py list
python3 grader.py run warpz examples/warpz_ref.py
python3 grader.py run mana_crystal examples/mana_crystal_ref.py --strict --stop-on-fail
```

## Verifying a change

```bash
python3 -m compileall -q grader.py server.py tools tests
node --check static/app.js && node tools/check_frontend.js && node tools/check_styles.js
python3 tools/validate_problem.py          # 47 problems: config, tests, samples, reference AC
python3 -m unittest discover -s tests -v   # 46 tests, no live server or database needed
```

The same sequence runs in CI on every push and pull request to `main`.

## Deployment

Backend: the `Dockerfile` image (`python:3.11-slim` with `gcc`/`g++`) on a Docker host —
`git push <backend-remote> HEAD:deploy`. Frontend: publish `static/` as-is; the bundled
`functions/api/[[proxy]].js` proxies `/api/*` to the backend under the same origin, so the session
cookie stays first-party. Bump the `?v=N` stamp whenever a versioned asset changes.

## Contributing

[`agent.md`](agent.md) is the contributor manual — architecture, workflows, the complete
environment-variable reference, and a catalogue of pitfalls. Read it before touching `grader.py`,
`server.py` or `app.js`.

Two invariants are non-negotiable:

1. **One judge only.** All judging passes through `grader.run_one`, `grader.judge_test` and
   `grader.prepare_command`; never inline judging into a request handler.
2. **Never disclose test data.** Everything carrying test data passes through `_redact_results()`, both
   on the response path and on the path to the database.

## License

Copyright (C) 2026 Newbiegrader contributors. This program is free software: you may redistribute it
and/or modify it under the terms of the **GNU Affero General Public License, version 3 or later**, as
published by the Free Software Foundation. The full text is in [`LICENSE`](LICENSE).

**Network use (AGPL section 13).** Operating a modified version and letting users interact with it over
a network requires offering those users the Corresponding Source of the running version. For this
deployment that source is <https://github.com/sphetpitak-sudo/gradernew>, linked from the footer of
every page; any other instance must make an equivalent offer.

**Third-party components.** Sarabun (bundled in `tools/fonts`, SIL Open Font License 1.1 —
`tools/fonts/OFL.txt`); Prompt and JetBrains Mono (loaded from the Google Fonts CDN, OFL 1.1); Python
and JavaScript dependencies are not vendored.

**Warranty.** Distributed in the hope that it will be useful, but without any warranty; without even
the implied warranty of merchantability or fitness for a particular purpose (licence sections 15–16).

**Trademarks.** The licence covers copyright only; it grants no rights in the project name, logo or
domains. Contributions are accepted on the understanding that they may be distributed under the same
licence.
