<div align="center">

# Newbiegrader

**An online judge for Thai competitive-programming instruction.**

Strict limits · Undisclosed tests · Asynchronous judging · Contests · Teacher tooling

<br>

[![License](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue)](LICENSE)
![Python](https://img.shields.io/badge/python-3.11-3776AB?logo=python&logoColor=white)
![Problems](https://img.shields.io/badge/problems-68-brightgreen)
![Test cases](https://img.shields.io/badge/test%20cases-1178-brightgreen)
![Grader](https://img.shields.io/badge/grader-v2.0.7-informational)
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

Practice submissions show input, expected output and actual output for failed cases to their owner. Contest submissions keep hidden tests private; upcoming/running contest problems also withhold extra feedback through the practice path. Previously disclosed practice data cannot be made secret again by reusing it in a contest. See the [feedback policy](docs/submission-feedback-policy.md).

<div align="center">

| 68 | 1,178 | v2.0.7 | 3 |
| :---: | :---: | :---: | :---: |
| problems | test cases | grader engine | languages |

</div>

Every problem ships with a reference solution, and every recorded verdict can be traced to the exact test set and grader version that produced it.

## Features

### Strict and honest limits
Wall-clock timeouts, measured peak memory and process isolation (resource limits, privilege drop and a network namespace where available). Each test reports its own time and memory usage.

### Undisclosed tests
Contest hidden tests return verdicts and resource figures. In practice, an owner can inspect input, expected output and actual output for failed cases. Upcoming/running contest problems withhold that extra practice feedback. The same policy applies to responses, history and persisted results.

### Asynchronous judging
Submissions return a job ID for polling. With `GRADER_QUEUE_MODE=database`, admission is durable and completion/history commit together under a worker lease. The default `local` mode uses an in-memory queue with best-effort persistence; it cannot guarantee recovery after a restart or database outage. Database workers back off while idle and during outages to reduce unnecessary RPC traffic.

### Contests
Timed Codeforces-style rounds with registration, frozen scoreboards and organizer announcements. Contest-only problems stay out of the public task list. Practice statistics exclude contest submissions.

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

Host capacity is read from the service or container at startup, and worker counts, memory ceilings, queue bounds and timeouts are derived from it automatically. Current production is Cloudflare Pages + AWS EC2 t3.small with one worker; Vercel and JustRunMy are not used. See [current architecture](docs/PRODUCTION_ARCHITECTURE.md), the [latest deployment/rollback record](docs/releases/PRODUCTION_CORRECTNESS_RELEASE_2026-10-19.md), and the [EC2 runbook](docs/EC2_MIGRATION.md).

## Design Principles

1. **One judging engine.** Every verdict flows through the same grader entry points, and no judging logic is duplicated in request handlers.
2. **Controlled feedback.** Every result passes through the practice/contest disclosure policy before it reaches a client and before it is stored.

## Stack

| Layer | Technology |
| --- | --- |
| Judging engine | Python (standard library only) |
| API | FastAPI |
| Database | PostgreSQL via Supabase |
| Frontend | HTML, CSS and JavaScript on Cloudflare Pages |
| Production backend | AWS EC2 / Ubuntu, Python 3.11 and separate systemd API/worker services |
| Local packaging | Docker |

## Contributing

For problem authors, start with the [shared authoring workflow](docs/making-problems.md) and versioned templates in `tools/templates/problem/`.

Contributions are welcome. You can suggest features or report bugs by opening an issue, chat with the community on [Discord](https://discord.gg/7NQDHFBpf6), or submit a pull request with a clear description of the change. Please report security issues through the maintainer's profile rather than a public issue.

## Team

| Role | Person | Scope |
| --- | --- | --- |
| Maintainer | [@n3wbiekkkk](https://github.com/n3wbiekkkk) | Judging engine, API, frontend, problem set, deployment |
| Contributor | [@Piyaph4t](https://github.com/Piyaph4t) | Judge-worker split, queue test coverage |

## License

This program is free software, released under the [GNU Affero General Public License v3.0 or later](LICENSE).

Under AGPL §13, running a modified version for users over a network requires offering them the Corresponding Source. For this deployment, the source is available at <https://github.com/n3wbiekkkk/Newbiegrader>.

Statement-PDF typefaces (Sarabun, Prompt and Anuphan) are bundled under SIL OFL 1.1. No warranty is provided and no trademark rights are granted.
