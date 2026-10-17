<div align="center">

# Newbiegrader

**An online judge for Thai competitive-programming instruction.**

Strict limits · Undisclosed tests · Asynchronous judging · Contests · Teacher tooling

<br>

[![License](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)
![Problems](https://img.shields.io/badge/problems-62-brightgreen)
![Test cases](https://img.shields.io/badge/test%20cases-908-brightgreen)
![Grader](https://img.shields.io/badge/grader-v2.0.0-informational)
![Frontend](https://img.shields.io/badge/frontend-no%20build%20step-orange)

[Live Demo](https://newbiegrader.pages.dev) · [Report a Bug](../../issues) · [Discord](https://discord.gg/7NQDHFBpf6) · [Documentation](docs)

</div>

---

## Table of Contents

- [About](#about)
- [Features](#features)
- [Verdicts](#verdicts)
- [Architecture](#architecture)
- [Design Principles](#design-principles)
- [Stack](#stack)
- [Contributing](#contributing)
- [Team](#team)
- [License](#license)

## About

Newbiegrader is a web-based programming judge designed for teaching competitive programming in Thai. Students submit solutions in **Python 3**, **C (C11)** or **C++ (C++17)** and receive automatic verdicts under real time and memory limits, the same way they would on a professional contest platform.

The test data behind each problem is never disclosed. Only the public samples from the problem statement are shown, so students learn to reason about correctness instead of fitting their code to known answers.

<div align="center">

| 62 | 908 | v2.0.0 | 3 |
| :---: | :---: | :---: | :---: |
| problems | test cases | grader engine | languages |

</div>

Every problem ships with a reference solution, and every recorded verdict can be traced to the exact test set and grader version that produced it.

## Features

### Strict and honest limits
Wall-clock timeouts, measured peak memory and process isolation (resource limits, privilege drop and a network namespace where available). Each test reports its own time and memory usage.

### Undisclosed tests
Hidden tests return only a verdict and resource figures. Inputs, expected outputs and diffs are served solely for tests declared public, and all test data is redacted before it is returned to a client or persisted.

### Asynchronous judging
Submissions are accepted immediately and placed in a durable queue. Page reloads, navigation and server restarts never lose a submission.

### Contests
Timed Codeforces-style rounds with registration, frozen scoreboards and organizer announcements. Contest-only problems stay out of the public task list, and contest scores never leak into the global leaderboard.

### Teacher tooling
Submission history, per-problem statistics, plagiarism screening, one-click rejudging, problem reporting and an admin overview with queue monitoring.

### Lightweight frontend
Plain HTML, CSS and JavaScript. No bundler, no transpiler and no framework.

## Verdicts

| Verdict | Meaning |
| :---: | --- |
| `AC` | Accepted. Every test passed. |
| `WA` | Wrong answer. |
| `TLE` | Time limit exceeded. |
| `MLE` | Memory limit exceeded. |
| `OLE` | Output limit exceeded. |
| `RE` | Runtime error. |
| `CE` | Compilation error. |

## Architecture

| Component | Responsibility |
| --- | --- |
| `grader.py` | The single judging engine, built on the Python standard library only |
| `server.py` | FastAPI application: authentication, job queue, quota and visibility policy, result redaction |
| `judge_runner.py` · `worker.py` | Supervised bounded execution and the dedicated worker role |
| `static/` | The web interface |
| `problems/` | Local working copy of the problem set (configuration, statement, tests). Not versioned here — the source of truth is Supabase |
| `supabase/` | Database schema with append-only, re-runnable migrations |

Host capacity is read from the container at startup, and worker counts, memory ceilings, queue bounds and timeouts are derived from it automatically.

## Design Principles

1. **One judging engine.** Every verdict flows through the same grader entry points, and no judging logic is duplicated in request handlers.
2. **No test-data disclosure.** Every payload carrying test data passes through result redaction before it reaches a client and before it is stored.

## Stack

| Layer | Technology |
| --- | --- |
| Judging engine | Python (standard library only) |
| API | FastAPI |
| Database | PostgreSQL via Supabase |
| Frontend | HTML, CSS and JavaScript on Cloudflare Pages |
| Backend runtime | Docker |

## Contributing

Contributions are welcome. You can suggest features or report bugs by opening an issue, chat with the community on [Discord](https://discord.gg/7NQDHFBpf6), or submit a pull request with a clear description of the change. Please report security issues through the maintainer's profile rather than a public issue.

## Team

| Role | Person | Scope |
| --- | --- | --- |
| Maintainer | [@n3wbiekkkk](https://github.com/n3wbiekkkk) | Judging engine, API, frontend, problem set, deployment |
| Contributor | [@Piyaph4t](https://github.com/Piyaph4t) | Judge-worker split, queue test coverage |

## License

This program is free software, released under the [GNU Affero General Public License v3.0 or later](LICENSE).

Under AGPL §13, running a modified version for users over a network requires offering them the Corresponding Source. For this deployment, the source is available at <https://github.com/n3wbiekkkk/Newbiegrader>.

Statement-PDF typefaces (Sarabun and Prompt) are bundled under SIL OFL 1.1. No warranty is provided and no trademark rights are granted.
