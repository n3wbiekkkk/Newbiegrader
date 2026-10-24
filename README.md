<div align="center">

# Newbiegrader

**A public programming practice platform with Thai problem statements.**

Python 3 · C11 · C++17 · Automatic judging · Contests · Official solutions

<br>

[![License](https://img.shields.io/badge/license-AGPL--3.0--or--later-blue)](LICENSE)
![Python](https://img.shields.io/badge/python-3.13-3776AB?logo=python&logoColor=white)
![Problems](https://img.shields.io/badge/problems-100-brightgreen)
![Test cases](https://img.shields.io/badge/test%20cases-1814-brightgreen)
![Grader](https://img.shields.io/badge/grader-v2.0.8-informational)
![Frontend](https://img.shields.io/badge/frontend-no%20build%20step-orange)

[Start Practicing](https://newbiegrader.pages.dev) · [Documentation](docs/README.md) · [Report a Bug](https://github.com/n3wbiekkkk/Newbiegrader/issues) · [Discord](https://discord.gg/7NQDHFBpf6) · [Contributors](https://github.com/n3wbiekkkk/Newbiegrader/graphs/contributors)

</div>

---

## Contents

- [About](#about)
- [Features](#features)
- [Feedback and access](#feedback-and-access)
- [Verdicts](#verdicts)
- [Local development](#local-development)
- [Architecture](#architecture)
- [Contributing](#contributing)
- [Contributors](#contributors)
- [License](#license)

## About

Newbiegrader is an online judge for anyone who wants to practice competitive
programming in Thai. Choose a problem, write a solution in **Python 3**, **C11**
or **C++17**, and receive a verdict with execution time and memory measurements.

The catalog contains **100 problems and 1,814 test cases**, from basic
implementation and strings to graphs, data structures and dynamic programming.
Problems have five calibrated levels, grouped into easy, medium and hard.
Stable problem IDs preserve links and submission history; the
[catalog number map](docs/catalog/problem-numbers-2026-10-24.csv) records the
approved numbering.

Visit [Newbiegrader](https://newbiegrader.pages.dev) and create an account to
open the problem catalog, submit code, join contests and read solutions.
The landing page and account registration/recovery are available to guests.

## Features

| Feature | What you can do |
| --- | --- |
| Thai problem statements | Read statements and PDFs, inspect public examples, and choose a problem by topic or level. |
| Multiple catalog filters | Select several topics and difficulty bands together, search by title/ID/number, sort results, and remove individual filters. Choices persist in the browser. |
| Shared code editor | Write code with line numbers and indentation shortcuts, attach a source file, and keep the same code when switching between submission and trial-run tabs. |
| Trial runs | Run code against your own input without adding a scored submission to your history. |
| Asynchronous judging | Submit a solution and follow its queued/running state until the verdict is ready. |
| Official solution PDFs | Read the approach, correctness argument, complexity and complete **C++17 and Python 3** implementations. C++17 appears first. |
| Submission history | Review your results and inspect eligible completed submissions from other members, subject to visibility and contest rules. |
| Contests | Join timed rounds with registration, organizer announcements and frozen scoreboards. |
| Administration | Manage contests, inspect queue health, review problem reports, rejudge submissions and screen for code similarity. |
| Light and dark themes | Use the same interface on desktop and mobile, with keyboard navigation and a Ctrl/Command + K problem search. |

## Feedback and access

Problem statements, PDFs, samples, solutions and other member pages require
login. These checks are enforced by the API as well as the frontend.

- **Practice:** owners can inspect bounded input, expected output, actual output
  and diagnostics for failed cases. Accepted private cases expose measurements
  only.
- **Contests:** hidden test data stays private. Upcoming or running contests
  also restrict extra feedback through the practice path.
- **Solutions:** signed-in members can read available solutions without first
  solving the problem. Solutions for problems in upcoming or running contests
  are withheld until those contests end.
- **Peer submissions:** eligible completed submissions can be inspected by
  signed-in members without a prior attempt. Private test I/O and diagnostics
  are excluded, and current visibility/contest checks still apply.

See the [submission feedback policy](docs/submission-feedback-policy.md) and
[solution access rules](docs/making-solutions.md#member-access-and-protected-backend-files)
for the complete boundaries. Previously disclosed practice data must not be
reused as a secret contest suite.

## Verdicts

| Verdict | Meaning |
| :---: | --- |
| `AC` | Accepted: every test passed. |
| `WA` | Wrong answer. |
| `TLE` | Time limit exceeded. |
| `MLE` | Memory limit exceeded. |
| `OLE` | Output limit exceeded. |
| `RE` | Runtime error. |
| `CE` | Compilation error. |

## Local development

Use **Python 3.13**, **Node.js**, and **GCC/G++**. The frontend is plain HTML,
CSS and JavaScript; it has no bundler or build step.

```sh
git clone https://github.com/n3wbiekkkk/Newbiegrader.git
cd Newbiegrader
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
cp .env.example .env
```

Configure your own development environment in `.env`, then start the server:

```sh
python server.py
```

Open [localhost:8000](http://127.0.0.1:8000). Account and database features need
a configured development Supabase project; see the
[metadata and file-storage guide](docs/migration-supabase.md) and
[email setup](docs/EMAIL_VERIFICATION_SETUP.md). Keep credentials server-side
and use a separate development environment for experiments.

**A public clone does not contain the problem packages.** Statements, private
tests, reference solutions and editable solution sources are excluded from Git.
Maintainers transfer authoring packages separately through the
[private synchronization workflow](docs/making-solutions.md#sync-private-authoring-packages-between-development-machines).
A server starting successfully does not establish that judging is configured.

For frontend changes, run:

```sh
node --check static/app.js
node tools/check_frontend.js
node tools/check_styles.js
node --test tests/test_*.js
```

For Python/API changes, also run `python -m unittest discover -s tests -v`.
The [CI workflow](.github/workflows/ci.yml) defines the complete checks, including
Linux isolation and disposable PostgreSQL qualification. A frontend check or
an empty problem directory does not qualify a judge deployment.

## Architecture

| Component | Responsibility |
| --- | --- |
| `static/` | Vanilla frontend, served through Cloudflare Pages in production. |
| `functions/api/[[proxy]].js` | Same-origin edge API proxy. |
| `server.py` | FastAPI: identity, admission, visibility, feedback policy and API responses. |
| `grader.py` | Shared standard-library judging engine, checkers and language limits. |
| `judge_execution.py`, `judge_runner.py`, `worker.py` | Supervised jobs and dedicated judge workers. |
| `job_sandbox.py`, `job_resources.py` | Linux isolation, resource enforcement and descendant cleanup. |
| `problem_store.py`, `problems/` | Protected runtime files and private local authoring packages. |
| `supabase/` | Metadata, identities, history and durable queue schema. |
| `tools/`, `tests/` | Authoring, publication, validation and regression checks. |

Every submission uses the same judging engine. Submission requests return a job
ID for polling; full judging does not run inside the API request. Database queue
mode coordinates worker leases and commits completion/history together. Local
queue mode is single-process and best-effort, with no durable restart guarantee.

Production uses separate API and worker roles. The executor remains
credential-free, with per-job identities, cgroups, Landlock, seccomp and bounded
workspaces. Memory accounting preserves the difference between measured usage
and address-space safety limits.

Problem and solution PDFs are served through authenticated backend endpoints.
Private fixtures, references and author archives are excluded from static
hosting. See [backend file storage](docs/BACKEND_PROBLEM_FILES.md),
[security readiness](docs/SECURITY_READINESS.md),
[queue and capacity](docs/load-handling.md), and the
[documentation index](docs/README.md) for detailed guides.

## Contributing

Bug reports, problem proposals and pull requests are welcome. Describe the
behavior you are changing and the checks you ran. Please report security issues
through the [maintainer's profile](https://github.com/n3wbiekkkk), rather than a
public issue.

- **Problems:** use the [problem authoring workflow](docs/making-problems.md)
  and versioned templates in `tools/templates/problem/`.
- **Solutions:** use the [solution authoring workflow](docs/making-solutions.md)
  and `tools/solution_authoring.py`; qualify both C++17 and Python against the
  shipped cases before publication.
- **Frontend:** keep the vanilla stack, support both themes, and verify desktop
  and mobile behavior. Include screenshots for visual changes.
- **Backend:** preserve asynchronous judging, authorization, disclosure and
  sandbox boundaries. Add regression coverage for behavior changes.

Keep private packages, credentials, local configuration and operator archives
out of pull requests.

## Contributors

| Role | Contributor | Contributions |
| --- | --- | --- |
| Maintainer | [@n3wbiekkkk](https://github.com/n3wbiekkkk) | Judging engine, API, frontend, problem set and deployment. |
| Contributor | [@Piyaph4t](https://github.com/Piyaph4t) | Judge-worker separation and queue regression coverage. |
| Contributor | [@pxsit](https://github.com/pxsit) | Python 3.13 runtime upgrade and upgrade documentation. |

See the [full contributor history](https://github.com/n3wbiekkkk/Newbiegrader/graphs/contributors)
on GitHub.

## License

Copyright (C) 2026 Newbiegrader contributors. Source code: <https://github.com/n3wbiekkkk/Newbiegrader>.

### Code

This program is free software, released under the **GNU Affero General Public License v3.0 or later** (`AGPL-3.0-or-later`). The full license text is in [LICENSE](LICENSE).

Under AGPL §13, running a modified version for users over a network requires offering them the Corresponding Source. For this deployment, the source is available at <https://github.com/n3wbiekkkk/Newbiegrader>.

### Name and logo

The Newbiegrader name and logo are **not** covered by the code license. All rights reserved.

### Third-party typefaces

Statement PDFs embed typefaces that keep their own licenses and are not covered by the licenses above: Anuphan and Inconsolata under SIL OFL 1.1, Latin Modern Roman under the GUST Font License, and TH Sarabun New under GPL-2.0-or-later with the font-embedding exception (so the rendered PDFs are not covered by the GPL). See `tools/fonts/`.

No warranty is provided and no trademark rights are granted.
