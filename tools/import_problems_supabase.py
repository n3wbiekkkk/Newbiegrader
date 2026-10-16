#!/usr/bin/env python3
"""Import local problems/ packages into Supabase (Postgres + private Storage).

Reads the existing on-disk format (config.json + statement.md + tests/*.in/.out
+ statement.pdf) and upserts:

  Postgres `problems` row: metadata + statement_md + samples_data (PUBLIC only)
    + hidden_tests manifest (names/hashes/sizes, NO contents)
  Storage `judge-assets` (PRIVATE): <slug>/tests/<name>.in(.out) for EVERY test
    + <slug>/statement.pdf when present. Never a public URL.

Idempotent: stable slug PK, deterministic object paths, upserts. Re-running
with unchanged files reports `skipped`. Local directories are never modified
or deleted.

  SUPABASE_URL=... SUPABASE_KEY=... \\  (service_role key, server-side only)
    python3 tools/import_problems_supabase.py --dry-run
    python3 tools/import_problems_supabase.py --problem hanoi --problem thai_time
    python3 tools/import_problems_supabase.py  # all problems

Exit code 0 only when nothing failed.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import grader  # noqa: E402
import problem_store  # noqa: E402


def _client():
    url = (os.environ.get("SUPABASE_URL", "") or "").strip()
    key = (os.environ.get("SUPABASE_KEY", "") or "").strip()
    if not url or not key:
        print("SUPABASE_URL and SUPABASE_KEY (service_role) must be set", file=sys.stderr)
        raise SystemExit(2)
    try:
        from supabase import create_client
    except ImportError:
        print("supabase lib not installed (pip install -r requirements.txt)", file=sys.stderr)
        raise SystemExit(2)
    return create_client(url, key)


def _local_slugs(only: list[str]) -> list[str]:
    if only:
        return sorted(dict.fromkeys(only))
    return sorted(p.name for p in grader.PROBLEMS_DIR.iterdir() if p.is_dir())


def _upload(bucket, path: str, data: bytes, content_type: str, dry: bool) -> None:
    if dry:
        return
    try:
        bucket.upload(path, data, {"upsert": "true", "content-type": content_type})
    except Exception as first:
        # Storage returns 409/duplicate without upsert on some versions; retry update.
        try:
            bucket.update(path, data, {"content-type": content_type})
        except Exception:
            raise first


def import_one(client, bucket_name: str, slug: str, dry: bool) -> tuple[str, str]:
    """Returns (status, detail). status in created|updated|skipped|failed."""
    try:
        prob = grader.load_problem(slug)
    except SystemExit as e:
        return "failed", f"loader: {e}"
    if not prob.tests:
        return "failed", "no tests"
    samples_data, hidden_manifest = problem_store.manifest_for_problem(prob)
    tests_hash = grader.tests_hash(prob)
    pdf_path = grader.PROBLEMS_DIR / slug / "statement.pdf"
    has_pdf = pdf_path.is_file()
    row = {
        "slug": prob.pid, "no": prob.no, "title": prob.title,
        "time_limit": prob.time_limit, "memory_limit": prob.memory_limit,
        "checker": prob.checker, "tolerance": prob.tolerance,
        "difficulty": prob.difficulty or "", "tags": prob.tags,
        "samples": prob.samples, "samples_data": samples_data,
        "statement_md": prob.description,
        "tests_hash": tests_hash, "tests_count": len(prob.tests),
        "hidden_tests": hidden_manifest,
        "hidden": bool(prob.hidden), "is_published": True,
        "statement_pdf_path": f"{slug}/statement.pdf" if has_pdf else None,
    }
    # Remote state for idempotence + conflict detection.
    try:
        res = client.table("problems").select(
            "slug,no,title,tests_hash,updated_at").eq("slug", slug).limit(1).execute()
        existing = (getattr(res, "data", None) or [None])[0]
    except Exception as e:
        return "failed", f"db read: {e}"
    if existing and existing.get("tests_hash") == tests_hash and \
            existing.get("title") == prob.title and int(existing.get("no") or 0) == prob.no:
        # Same version: still ensure Storage objects exist (partial upload recovery).
        status = "skipped"
    else:
        status = "updated" if existing else "created"
    if existing and not dry:
        # Duplicate `no` across slugs must not be created silently.
        try:
            clash = client.table("problems").select("slug").eq("no", prob.no).execute()
            others = [r.get("slug") for r in (getattr(clash, "data", None) or [])
                      if r.get("slug") != slug]
        except Exception as e:
            return "failed", f"db no-check: {e}"
        if others:
            return "failed", f"config.no {prob.no} already used by {others} (fix with tools/number_problems.py)"
    if dry:
        detail = f"tests={len(prob.tests)} samples={len(samples_data)} hidden={len(hidden_manifest)} pdf={'yes' if has_pdf else 'no'}"
        return status, detail
    # Write Postgres row first (upsert on slug PK), then Storage objects.
    try:
        client.table("problems").upsert(row, on_conflict="slug").execute()
    except Exception as e:
        return "failed", f"db upsert: {e}"
    try:
        bucket = client.storage.from_(bucket_name)
        for tc in prob.tests:
            _upload(bucket, f"{slug}/tests/{tc.name}.in",
                    tc.input.encode("utf-8"), "text/plain; charset=utf-8", dry)
            _upload(bucket, f"{slug}/tests/{tc.name}.out",
                    tc.expected.encode("utf-8"), "text/plain; charset=utf-8", dry)
        if has_pdf:
            _upload(bucket, f"{slug}/statement.pdf", pdf_path.read_bytes(),
                    "application/pdf", dry)
    except Exception as e:
        return "failed", f"storage upload: {e}"
    problem_store.invalidate_cache(slug)
    return status, f"tests={len(prob.tests)} hash={tests_hash}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import problems/ into Supabase (idempotent).")
    ap.add_argument("--problem", action="append", default=[], dest="problems",
                    help="slug to import (repeatable; default: all)")
    ap.add_argument("--bucket", default=os.environ.get("GRADER_PROBLEM_BUCKET", "judge-assets"),
                    help="private Storage bucket (default: %(default)s)")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate + report without writing Postgres or Storage")
    args = ap.parse_args(argv)
    slugs = _local_slugs(args.problems)
    if not slugs:
        print("no problems to import")
        return 0
    client = None
    if (os.environ.get("SUPABASE_URL", "") or "").strip() and \
            (os.environ.get("SUPABASE_KEY", "") or "").strip():
        try:
            client = _client()
        except SystemExit:
            raise
        except Exception as e:
            print(f"warning: supabase unavailable, offline dry check only ({e})",
                  file=sys.stderr)
            client = None
    elif not args.dry_run:
        _client()  # prints the missing-env error + exits 2
    if client is not None:
        # Fail fast when the migration has not been applied.
        try:
            client.table("problems").select("slug").limit(1).execute()
        except Exception as e:
            if args.dry_run:
                print(f"warning: problems table not readable ({e}); offline check only",
                      file=sys.stderr)
                client = None
            else:
                print(f"problems table not readable ({e}); run supabase/schema.sql first",
                      file=sys.stderr)
                return 1
    counts = {"created": 0, "updated": 0, "skipped": 0, "failed": 0}
    failures: list[str] = []
    for slug in slugs:
        status, detail = import_one(client, args.bucket, slug, dry=args.dry_run) \
            if client is not None else _dry_only(slug)
        counts[status] = counts.get(status, 0) + 1
        mark = {"created": "+", "updated": "~", "skipped": "=", "failed": "x"}[status]
        print(f"{mark} {slug:<24} {status:<8} {detail}")
        if status == "failed":
            failures.append(slug)
    print("-" * 64)
    mode = "DRY-RUN " if args.dry_run else ""
    print(f"{mode}{len(slugs)} problems: "
          f"{counts.get('created',0)} created, {counts.get('updated',0)} updated, "
          f"{counts.get('skipped',0)} skipped, {counts.get('failed',0)} failed")
    if failures:
        print("failed: " + ", ".join(failures))
        return 1
    return 0


def _dry_only(slug: str) -> tuple[str, str]:
    try:
        prob = grader.load_problem(slug)
    except SystemExit as e:
        return "failed", f"loader: {e}"
    samples_data, hidden_manifest = problem_store.manifest_for_problem(prob)
    has_pdf = (grader.PROBLEMS_DIR / slug / "statement.pdf").is_file()
    return "skipped", (f"tests={len(prob.tests)} samples={len(samples_data)} "
                       f"hidden={len(hidden_manifest)} pdf={'yes' if has_pdf else 'no'}")


if __name__ == "__main__":
    raise SystemExit(main())
