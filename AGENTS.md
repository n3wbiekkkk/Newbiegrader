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
