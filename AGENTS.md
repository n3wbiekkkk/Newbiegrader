# Repository Guidelines

## Project Structure & Module Organization

Newbiegrader is a Thai competitive-programming judge. `grader.py` contains the standard-library judging engine; `server.py` provides the FastAPI API and asynchronous job queue. Reuse the engine rather than duplicating judging logic.

- `static/`: vanilla HTML, JavaScript, CSS, configuration, and image assets; no frontend build step.
- `functions/api/[[proxy]].js`: edge proxy for separately hosted frontends.
- `problems/<id>/`: `config.json`, statements, and paired `tests/01.in` / `01.out` fixtures.
- `examples/`: reference solutions, usually `<id>_ref.py`.
- `tests/`: API and host-capacity tests plus an in-memory Supabase substitute.
- `tools/`: problem validators, frontend guards, and statement tooling.
- `supabase/schema.sql`: database schema and append-only migrations.

Read `README.md` for the specification and `agent.md` for operational details.

## Problem Authoring Contract (all AI agents)

Before creating or editing a problem, read `docs/making-problems.md`. It is the
canonical authoring workflow; use the versioned templates in
`tools/templates/problem/` rather than inventing another structure or PDF style.

- Scaffold new problems with `python tools/problem_authoring.py new ...`.
- Explicitly define input/output separators, row lengths, bounds and ordering.
  Implement `input_validator.py` for every new problem; check negative examples
  as well as every shipped input. This is a trusted local author tool only.
- `tests/` is the source of truth for public sample bytes. Run
  `python tools/problem_authoring.py sync-samples <id> --write`; do not retype
  sample data or copy hidden cases into statements. Preserve unrelated prose.
- Use only `tools/make_statement_tex.py` to build PDFs. Inspect every rendered
  page. Keep the generated `statement.build.json` beside the private PDF.
- Before publishing a new problem, require
  `python tools/validate_problem.py <id> --strict` and use
  `tools/import_problems_supabase.py --problem <id> --strict --dry-run`.
  A missing package, unfinished template, format mismatch or warning is a failure.
- Existing packages can be checked in compatibility mode; do not change their
  rules, permanent IDs, limits, tests or outputs to make strict checks pass.
- Do not claim that these checks prove the story, algorithm or test coverage
  correct. Review the specification and use independent small-case checks and
  deliberately wrong solutions. Keep secrets, hidden tests and references private.

## Build, Test, and Development Commands

Use Python 3.11, Node.js for frontend checks, and GCC/G++ for C/C++ submissions. Run from the repository root:

```sh
python -m pip install -r requirements.txt
python server.py                         # Serve UI/API at localhost:8000
python grader.py run hanoi examples/hanoi_ref.py
python -m unittest discover -s tests -v   # Automated suite
python tools/validate_problem.py          # Validate all packages and references
python tools/plagiarism.py                # Plagiarism self-test
python -m compileall -q grader.py server.py tools
node --check static/app.js
node tools/check_frontend.js              # DOM IDs and icon references
node tools/check_styles.js                # Design tokens and theme coverage
```

## Coding Style & Naming Conventions

Follow existing formatting: four-space Python indentation and two-space JavaScript/CSS indentation. Use Python `snake_case`, class `PascalCase`, and JavaScript `camelCase`. Keep problem IDs in `snake_case` and preserve permanent `config.json` numbers. Use CSS design tokens and support both themes. Bump asset `?v=` values in `static/index.html` after JS/CSS changes. No general formatter is configured.

## Testing Guidelines

Tests use `unittest` and FastAPI `TestClient`, with fake Supabase storage; no live database is required. Name files `test_*.py` and methods `test_*`. Add regression coverage for changed behavior, especially permissions, hidden-test redaction, queues, and contests. No numeric coverage threshold is configured. Run the CI checks above before committing; restart the server after problem changes.

## Commit & Pull Request Guidelines

History uses concise, descriptive subjects, sometimes prefixed by an area: `Frontend: refresh problem visibility`. Follow that pattern. Pull requests should explain the change, link relevant issues, report validation results, and include screenshots for UI changes.

## Security & Configuration

Use `.env.example` for local configuration; keep secrets and Supabase service-role keys server-side. Preserve sandbox limits, visibility checks, and result redaction. Append idempotent schema changes and have the maintainer apply them through Supabase SQL Editor.
