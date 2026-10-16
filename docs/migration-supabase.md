# Problem storage migration: local `problems/` → Supabase

Status: remote path implemented and feature-flagged; local files remain the
default and are never deleted. Cutover is one environment variable after a
verified import.

## What moved where

| Local artifact | Supabase location | Visibility |
| --- | --- | --- |
| `problems/<slug>/config.json` | `problems` row (`slug`, `no`, `title`, `time_limit`, `memory_limit`, `checker`, `tolerance`, `difficulty`, `tags`, `samples`, `hidden`) | metadata readable only via API; RLS limits direct reads to published, non-hidden rows |
| `problems/<slug>/statement.md` | `problems.statement_md` | public for published problems |
| `statement.pdf` | Storage `judge-assets/<slug>/statement.pdf` (row keeps `statement_pdf_path`) | private bucket; streamed by the API with server credentials |
| `tests/<name>.in/.out` where `<name>` ∈ `config.samples` | `problems.samples_data` (`[{name,input,expected}]`) | public samples only, served via `/api/problems/{pid}/sample/{name}` |
| `tests/<name>.in/.out` where `<name>` ∉ `samples` (1001+) | Storage `judge-assets/<slug>/tests/<name>.in|.out`; row keeps a **manifest only** (`hidden_tests: [{name,sha256,size_in,size_out}]` — never contents) | private; downloaded server-side with the service-role key |
| `examples/<id>_ref.*` | **not migrated** — remain local tooling for test generation/validation | private to the repo |

Integrity: `problems.tests_hash` stores `grader.tests_hash(...)`. The loader
recomputes the hash after downloading and **refuses to judge on mismatch**
(fail closed) — a tampered row or partial upload can never become Accepted.

## Migrations

`supabase/schema.sql` (append-only, re-runnable) gained the 2026-10-16 block:

- `problems` table (slug PK, unique `no`, RLS on).
- Policy `problems_public_read`: `select` for `anon/authenticated` only where
  `is_published and not hidden`. All writes are `service_role`-only.
- Private Storage bucket `judge-assets` created when the `storage` schema
  exists (guarded, so the plain-Postgres CI job still applies the file twice).
  No anon/authenticated policy is created on `storage.objects` for this bucket.

Apply in Supabase SQL Editor → paste `supabase/schema.sql` → run (idempotent).

## Import

```sh
SUPABASE_URL=... SUPABASE_KEY=...   # service_role key, server-side only
python3 tools/import_problems_supabase.py --dry-run   # no writes, summary only
python3 tools/import_problems_supabase.py             # all 62 problems
python3 tools/import_problems_supabase.py --problem hanoi
```

- Upserts Postgres rows (`on_conflict slug`), uploads every test file and the PDF
  to `judge-assets` (upsert on the same deterministic paths).
- Unchanged problems (same `tests_hash`) are reported `skipped`; storage objects
  are still reconciled, so a partial/interrupted import heals on re-run.
- Refuses to create duplicate problem numbers (`no` conflicts fail, never
  silently overwritten). Local files are never modified or deleted.
- Exit code ≠ 0 when anything failed; summary lists created / updated /
  skipped / failed.

## Runtime switch (cutover)

```
GRADER_PROBLEM_SOURCE=supabase       # default: local (unchanged behavior)
GRADER_PROBLEM_BUCKET=judge-assets   # optional override
GRADER_PROBLEM_CACHE_TTL=30          # metadata TTL seconds, 0 disables
```

- Boot in supabase mode WITHOUT Supabase credentials refuses to start (no
  silent local fallback). `GET /api/version -> system.problem_source` shows the
  active source at runtime.
- Problem rows are TTL-cached and versioned by `tests_hash`; hidden test bytes
  are cached per problem and only re-fetched when the hash/`updated_at` changes
  — no per-submission download of every hidden test.
- The isolated runner (`judge_runner --job`) receives the fully-resolved problem
  (tests included) through the trusted server-side job payload; it never talks
  to Supabase and never reads client-supplied paths.
- Failure semantics: unknown problem → 404 / job error; missing or corrupt
  assets, storage outage, DB error, hash mismatch → explicit 500 / job error
  (`problem store unavailable`). Judging never proceeds with an empty test
  suite, and an unavailable hidden test can never yield Accepted.
- Unpublished problems (`is_published = false`) are admin-only everywhere,
  including inside contests. Unpublish by setting the column in Supabase;
  workers re-check before executing and refuse unpublished problems.

Rollback: set `GRADER_PROBLEM_SOURCE=local` and restart. Local directories were
kept intact, so old behavior resumes immediately; history/queue tables are
unaffected.

## Safety invariants (implemented + tested)

1. Samples/hidden split preserved: only `samples` list members are public.
2. Hidden test contents exist only in the private bucket and the judged job
   payload; DB rows store names/sizes/sha256 only.
3. RLS: no public policy grants beyond published/non-hidden `select`.
4. No public URLs are created for any bucket object; PDFs stream through the API.
5. Engine untouched: verdicts come from `grader.judge_test` via
   `server.run_submission` exactly as before (verdict-parity test asserts the
   same `tests_hash` and AC for reference solutions on both sources).
6. `visual` truth preservation: no changes to grader.py judging logic beyond
   carrying `is_published` through `Problem` (default `True` locally).

## Environment summary

| Variable | Required for | Secret? |
| --- | --- | --- |
| `SUPABASE_URL`, `SUPABASE_KEY` (service_role) | import, supabase source, history | yes (server only) |
| `GRADER_PROBLEM_SOURCE` | cutover flag (`local` default) | no |
| `GRADER_PROBLEM_BUCKET`, `GRADER_PROBLEM_CACHE_TTL` | tuning | no |

Never expose `SUPABASE_KEY` to the frontend; the Cloudflare proxy and browser
bundle need nothing new.

## Verification performed

- `python3 tools/import_problems_supabase.py --dry-run` → 62/62 clean.
- New suite `tests/test_problems_supabase.py` (17 tests): import idempotency,
  duplicate-number refusal, malformed row, hash-mismatch, missing asset,
  storage outage (all fail closed), unpublished visibility, hidden-redaction,
  verdict parity (AC/WA/CE on fake Supabase), RLS/policy assertions on the SQL.
- Full repo checks: compileall + frontend checks + existing unittest suites
  (see PR/commit notes for the run log).

Remote (live Supabase) verification is pending valid credentials — apply the
schema, run the import, then judge the reference submissions once before
flipping `GRADER_PROBLEM_SOURCE`.
