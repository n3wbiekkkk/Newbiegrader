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
    python3 tools/import_problems_supabase.py --renumber  # after renumbering locally

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


def _upload_object(client, bucket_name: str, path: str, data: bytes,
                   content_type: str) -> None:
    """PUT one object via plain HTTPS (stdlib, per-call timeout).

    storage3's SyncClient is not thread-safe (shared httpx state breaks under
    ThreadPoolExecutor), and it has no request timeout — a stuck upload would
    wedge the whole import. Direct POST mirrors its wire format
    (multipart `file` field + `x-upsert`), so behavior is identical.
    """
    import urllib.parse
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
    import uuid

    url = (getattr(client, "supabase_url", "") or os.environ.get("SUPABASE_URL", "")).rstrip("/")
    key = getattr(client, "supabase_key", "") or os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        raise RuntimeError("supabase upload needs SUPABASE_URL + SUPABASE_KEY")
    boundary = uuid.uuid4().hex
    filename = path.rsplit("/", maxsplit=1)[-1]
    head = (f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n").encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    object_url = f"{url}/storage/v1/object/{bucket_name}/{urllib.parse.quote(path, safe='')}"
    req = Request(object_url, data=head + bytes(data) + tail, method="POST", headers={
        "Authorization": f"Bearer {key}", "apikey": key, "x-upsert": "true",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    })
    try:
        with urlopen(req, timeout=60) as resp:
            resp.read()
    except HTTPError as e:
        raise RuntimeError(f"upload {path!r}: HTTP {e.code} {e.read()[:200]}")
    except URLError as e:
        raise RuntimeError(f"upload {path!r}: {e}")


def _upload_many(client, bucket_name: str, jobs: list, dry: bool) -> None:
    """Upload many objects concurrently (I/O-bound HTTPS). Bounded pool.

    storage3 handles are not shared across threads — each upload is an
    independent stdlib HTTPS call with its own 60s timeout. Any single
    failure aborts the import of that problem (fail closed); successful
    uploads are idempotent (upsert on stable paths) so a retry heals
    partial batches.
    """
    if dry or not jobs:
        return
    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=min(16, len(jobs))) as ex:
        list(ex.map(lambda j: _upload_object(client, bucket_name, j[0], j[1], j[2]),
                    jobs))


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
        jobs = []
        for tc in prob.tests:
            jobs.append((f"{slug}/tests/{tc.name}.in", tc.input.encode("utf-8"),
                         "text/plain; charset=utf-8"))
            jobs.append((f"{slug}/tests/{tc.name}.out", tc.expected.encode("utf-8"),
                         "text/plain; charset=utf-8"))
        if has_pdf:
            jobs.append((f"{slug}/statement.pdf", pdf_path.read_bytes(),
                         "application/pdf"))
        _upload_many(client, bucket_name, jobs, dry)
    except Exception as e:
        return "failed", f"storage upload: {e}"
    problem_store.invalidate_cache(slug)
    return status, f"tests={len(prob.tests)} hash={tests_hash}"


def _park_numbers(client) -> int:
    """Move every `problems.no` onto unique negatives to free the positive range.

    `no` carries a UNIQUE constraint (`no int unique not null`), so a full
    renumber (a permutation old -> new) cannot be written slug-by-slug while
    both ends still hold numbers: every target is momentarily occupied. Parking
    the current values on unique negative integers clears the range, then the
    normal import writes the canonical local numbers. Negatives are invisible
    to clients (the API sorts unnumbered rows last) and are replaced within the
    same run, so only a short window can see them.
    """
    res = client.table("problems").select("slug,no").execute()
    rows = getattr(res, "data", None) or []
    for i, row in enumerate(sorted(rows, key=lambda r: int(r.get("no") or 0)), start=1):
        client.table("problems").update({"no": -i}).eq("slug", row["slug"]).execute()
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import problems/ into Supabase (idempotent).")
    ap.add_argument("--problem", action="append", default=[], dest="problems",
                    help="slug to import (repeatable; default: all)")
    ap.add_argument("--bucket", default=os.environ.get("GRADER_PROBLEM_BUCKET", "judge-assets"),
                    help="private Storage bucket (default: %(default)s)")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate + report without writing Postgres or Storage")
    ap.add_argument("--renumber", action="store_true",
                    help="first park the existing DB numbers on negatives so a full "
                         "local renumber (tools/number_problems.py --renumber) can be "
                         "upserted without UNIQUE clashes")
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
    if args.renumber and client is not None and not args.dry_run:
        try:
            parked = _park_numbers(client)
        except Exception as e:
            print(f"renumber: could not park existing numbers: {e}", file=sys.stderr)
            return 1
        print(f"renumber: parked {parked} existing numbers before reassigning")
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
