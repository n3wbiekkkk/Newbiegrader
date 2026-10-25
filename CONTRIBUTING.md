# Contributing to Newbiegrader

Newbiegrader is an online judge for practicing competitive programming in Thai.
You can contribute bug reports, documentation, code, problem proposals and tests.

Keep discussions respectful and content suitable for students, including beginners
and minors. Start with a small, focused change; discuss larger features before
building them.

## Table of Contents

- [Ways to contribute](#ways-to-contribute)
- [Reporting security issues](#reporting-security-issues)
- [Reporting bugs](#reporting-bugs)
- [Suggesting features](#suggesting-features)
- [Development setup](#development-setup)
- [Project layout](#project-layout)
- [Design principles](#design-principles)
- [Coding guidelines](#coding-guidelines)
- [Database migrations](#database-migrations)
- [Contributing problems](#contributing-problems)
- [Submitting a pull request](#submitting-a-pull-request)
- [Licensing of contributions](#licensing-of-contributions)
- [Getting help](#getting-help)

## Ways to contribute

- **Report a bug** or unexpected verdict by opening an issue.
- **Suggest a feature** or improvement by opening an issue before you start building it.
- **Improve the documentation** in `docs/` or fix typos in the statements and UI text.
- **Fix a bug or implement a feature** through a pull request.
- **Author a problem** for the catalog (see [Contributing problems](#contributing-problems)).
- **Improve test coverage**, especially for the queue, worker and visibility policy.
- **Chat with the community** on [Discord](https://discord.gg/7NQDHFBpf6).

## Reporting security issues

**Do not open a public issue for a security problem.** This includes sandbox escapes, ways to read hidden tests or other users' data, authentication bypasses and anything that could be abused against the live service.

Follow [SECURITY.md](SECURITY.md) and report privately to
[newbiegrader.team@gmail.com](mailto:newbiegrader.team@gmail.com). Include a minimal
reproduction and the impact you observed. Coordinate production testing with the
maintainer first.

For background on what is already covered, see [`docs/SECURITY_READINESS.md`](docs/SECURITY_READINESS.md) and [`docs/PUBLIC_SECURITY.md`](docs/PUBLIC_SECURITY.md).

## Reporting bugs

Before opening an issue, search the [existing issues](https://github.com/n3wbiekkkk/Newbiegrader/issues) to avoid duplicates.

A good bug report includes:

- What you expected to happen and what happened instead.
- Steps to reproduce.
- The language used (Python 3, C11 or C++17), the problem ID, and the submission ID if the report is about a verdict.
- Browser and operating system for frontend problems.
- Relevant logs or screenshots.

> **Never include passwords, OTP codes, tokens or other personal data in a public issue.** Issues are visible to everyone.

If you believe a test set or time limit is wrong, report the problem ID and the submission ID. Please do not resubmit repeatedly while waiting for a response.

## Suggesting features

Open an issue describing the problem you want to solve, who benefits, and any alternatives you considered. For anything larger than a small fix, please wait for feedback from the maintainer before investing significant effort, so your work is not wasted on a change that conflicts with the project's direction or its [design principles](#design-principles).

## Development setup

### Prerequisites

- Python 3.13
- Node.js (for the frontend checks and the JavaScript tests)
- GCC/G++ (for C11 and C++17 judging)
- Git
- Docker (optional, for building the container image locally)
- A Supabase project, if you need to exercise the database, authentication or durable queue

### Getting started

```bash
# 1. Fork the repository on GitHub, then clone your fork
git clone https://github.com/<your-username>/Newbiegrader.git
cd Newbiegrader

# 2. Create and activate a virtual environment
python3.13 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
python -m pip install -r requirements.txt

# 4. Create your local configuration
cp .env.example .env
# Edit .env with your own values. Never commit it.
# 5. Start the development server
python server.py
```

Configuration is read from environment variables; `.env.example` lists the available options. Two settings you will meet early:

| Variable | Purpose |
|----------|---------|
| `GRADER_QUEUE_MODE` | `local` (default) runs one combined API/worker process with a best-effort in-memory queue. `database` uses the durable Supabase-backed queue with leases and requires applying `supabase/schema.sql` first. |
| `GRADER_PROBLEM_SOURCE` | `local` (default) loads authoring packages from `problems/`. `supabase` loads database metadata; it is separate from the location of file bytes. |

Production combines Supabase metadata with `GRADER_FILE_STORAGE=local` and
verified protected file roots. The example configuration also contains legacy
file-storage settings; do not use it as a production deployment recipe. Follow
the [backend file guide](docs/BACKEND_PROBLEM_FILES.md) for that boundary.

> **Important:** The `problems/` directory is a local working copy and is **not versioned** in this repository. Private test data and reference solutions are intentionally excluded. You will need to create your own local problems to test judging end to end (see [Contributing problems](#contributing-problems)).

For the production topology, see [`docs/PRODUCTION_ARCHITECTURE.md`](docs/PRODUCTION_ARCHITECTURE.md), [`docs/BACKEND_PROBLEM_FILES.md`](docs/BACKEND_PROBLEM_FILES.md) and [`docs/HOST_DEPLOYMENT.md`](docs/HOST_DEPLOYMENT.md).

### Running the tests

Tests live in `tests/`. The Python suite uses `unittest` (no `pytest` dependency is installed), and the frontend tests use the Node.js test runner. These are the same commands CI runs; [`.github/workflows/ci.yml`](.github/workflows/ci.yml) is the exact source of truth if they ever differ:

```bash
python -m compileall -q grader.py server.py judge_runner.py judge_execution.py worker.py container_entrypoint.py job_sandbox.py job_resources.py email_auth.py problem_store.py tools deploy/host
node --check static/app.js
node tools/check_frontend.js
node tools/check_styles.js
node --test tests/test_*.js
python -m unittest discover -s tests -v
python tools/plagiarism.py
python tools/validate_problem.py
```

`tools/validate_problem.py` validates your local `problems/` packages. A public
clone has no private catalog, so an empty or skipped run is not catalog
qualification. State which packages and references were actually available.

Choose checks that match the change:

| Change | Validation |
| --- | --- |
| Documentation | Check links, examples and consistency with the maintained specifications. |
| Frontend | Run the Node checks/tests and inspect both themes at mobile and desktop widths. |
| API, judging or identity | Run the Python suite and add regression coverage for changed behavior. |
| Schema or queue RPCs | Run the disposable PostgreSQL checks in CI, including privileges and concurrency. |
| Linux isolation | Require `tools/run_critical_tests.py` with zero skips and the native host qualification. |

PostgreSQL checks verify real SQL behavior; an in-memory substitute does not
replace them. Passing development tests on macOS does not qualify Linux isolation.

Report the checks you ran and any failures, skips or unavailable prerequisites
in the pull request.

## Project layout

| Path | Responsibility |
|------|----------------|
| `grader.py` | The single judging engine. Python standard library only. |
| `server.py` | FastAPI application: authentication, admission, job queue, quota and visibility policy, result redaction. |
| `judge_execution.py`, `judge_runner.py`, `worker.py` | Supervised, bounded execution and the dedicated worker role. |
| `job_sandbox.py`, `job_resources.py` | Sandbox and per-job resource handling. |
| `problem_store.py`, `backend_problem_files.py` | Problem metadata and backend file storage. |
| `database_client.py`, `email_auth.py` | Database access and email/OTP authentication. |
| `static/` | The web interface (plain HTML, CSS and JavaScript). |
| `functions/api/` | Cloudflare Pages functions. |
| `supabase/` | Database schema and migrations. |
| `deploy/host/` | Host deployment files. |
| `tools/` | Tooling, including problem templates in `tools/templates/problem/`. |
| `tests/` | Automated tests. |
| `docs/` | Project documentation and policies. |

## Design principles

Contributions are reviewed against these principles. Please read them before changing judging or result-handling code.

1. **One judging engine.** Every verdict flows through the same grader entry points. Do not duplicate judging logic in request handlers.
2. **Controlled feedback.** Every result must pass through the practice/contest disclosure policy before it reaches a client **and** before it is stored. Hidden contest tests must never leak through responses, history or persisted results. See [`docs/submission-feedback-policy.md`](docs/submission-feedback-policy.md).

Related expectations:

- **Strict and honest limits.** Time and memory limits are enforced and reported per test. Do not weaken sandbox restrictions to make a feature easier.
- **Asynchronous judging.** Submit returns a job ID and the client polls. Never
  automatically replay an ambiguous lease-claim request: the database may already
  have leased a job even when the response was lost. Admission retries require
  an explicit rejection that confirms no job was accepted.
- **Lightweight frontend.** The frontend is plain HTML, CSS and JavaScript, using the existing design tokens in both themes. Please do not introduce a bundler, transpiler or framework.
- **Standard library for the grader.** `grader.py` depends only on the Python standard library. Discuss with the maintainer before adding any dependency elsewhere.
- **Preserved boundaries.** Preserve session revocation, cookie/CSRF/origin checks, queue ownership and admission limits. Add regression coverage when you touch one of these boundaries.

## Coding guidelines

- Target **Python 3.13**.
- Follow the style of the surrounding code, and keep changes focused. Avoid unrelated reformatting in the same pull request.
- Add or update tests for any change in behaviour, especially around verdicts, queue handling, visibility rules and redaction.
- Never log or return credentials or other users' private data. Judge feedback
  follows the [disclosure policy](docs/submission-feedback-policy.md): eligible
  practice owners may receive bounded failed-case I/O and diagnostics; peers and
  contest responses have stricter allowlists.
- Never commit secrets, `.env` files, private test fixtures or reference solutions.
- Update affected `?v=` references after changing JavaScript or CSS, including
  standalone HTML pages as well as `static/index.html`.
- Verify UI changes in a real browser in both light and dark themes at desktop and mobile widths, and include screenshots in the pull request.
- Keep user-facing text accurate and consistent. The UI and policies are primarily Thai, so please preserve existing wording conventions.
- Update documentation in `docs/` when behaviour, configuration or operations change.
- Do not run load tests, send email or test changes against the live database or production service without the maintainer's authorization.

## Database migrations

Migrations in `supabase/` are **append-only and re-runnable**.

- Never edit a migration that has already been merged. Add a new one instead.
- Write migrations so that running them again is safe (for example, use `IF NOT EXISTS` and equivalent guards).
- Describe the schema change and any rollout considerations in your pull request. Production DDL is applied by the maintainer through the Supabase SQL Editor.

## Contributing problems

Start with the shared authoring workflow in [`docs/making-problems.md`](docs/making-problems.md) and the versioned templates in `tools/templates/problem/`. Official solutions follow [`docs/making-solutions.md`](docs/making-solutions.md) and `tools/solution_authoring.py`.

Key points:

- Each problem has a `level` from 1 to 5 reflecting the technique it actually requires; the easy/medium/hard badge is derived from it (1–2 easy, 3 medium, 4–5 hard).
- Problems use stable slug IDs. Do not change an existing problem's slug or renumber the catalog; renumbering follows an explicit operator-approved migration.
- **Never commit private tests, private fixtures or reference solutions** to this public repository. Share them with the maintainer privately so they can be published to protected backend storage.
- Statement PDFs embed third-party typefaces under their own licenses (see `tools/fonts/` and the License section of the README).
- Make sure your tests have been validated against a correct reference solution and against intentionally wrong, slow and memory-hungry ones, so that the verdicts are trustworthy.
- If you change a problem's tests or limits after it has been in use, discuss it with the maintainer first. A rejudge may be needed and contest scoring may be affected.

## Submitting a pull request

1. Fork the repository and create a branch from `main`:
   ```bash
   git checkout -b fix/short-description
   ```
2. Make your changes in small, logical commits with clear messages.
3. Run the tests and confirm they pass.
4. Push your branch and open a pull request against `main`.
5. In the description, explain **what** changed and **why**, link the related issue (for example `Closes #123`), and note any testing you did. Include screenshots for UI changes.
6. Be responsive to review feedback. The maintainer may ask for changes before merging.

Pull requests that touch judging, sandboxing, visibility/redaction, authentication or the queue receive extra scrutiny. Please explain the security and correctness implications in your description.

### Checklist

- [ ] Relevant checks pass; skips and unavailable prerequisites are explained
- [ ] Behavior changes have regression coverage
- [ ] No secrets, private tests or reference solutions included
- [ ] Documentation updated where needed
- [ ] Migrations (if any) are new files, append-only and re-runnable
- [ ] The change respects the design principles above

## Licensing of contributions

Newbiegrader's source code is released under the **GNU Affero General Public License v3.0 or later** (`AGPL-3.0-or-later`); see [`LICENSE`](LICENSE). By submitting a contribution, you confirm that you have the right to submit it and agree that it will be licensed under the same terms.

Note that the **Newbiegrader name and logo are not covered by the code license** and all rights in them are reserved. Please do not use them in a way that suggests your fork or modified version is the official project.

## Getting help

- Questions and discussion: [Discord](https://discord.gg/7NQDHFBpf6)
- Bugs and feature requests: [GitHub Issues](https://github.com/n3wbiekkkk/Newbiegrader/issues)
- Security and private matters: [newbiegrader.team@gmail.com](mailto:newbiegrader.team@gmail.com)

Thank you for helping make competitive programming easier to learn.
