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
    python3 tools/import_problems_supabase.py --numbers-only  # catalog order only

Exit code 0 only when nothing failed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
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


def _upload_many(client, bucket_name: str, jobs: list, dry: bool, public_samples=()) -> None:
    """Upload many objects concurrently (I/O-bound HTTPS). Bounded pool.

    storage3 handles are not shared across threads — each upload is an
    independent stdlib HTTPS call with its own 60s timeout. Any single
    failure aborts the import of that problem (fail closed); successful
    uploads are idempotent (upsert on stable paths) so a retry heals
    partial batches.
    """
    if dry or not jobs:
        return
    if problem_store.backend_problem_files.backend() == "local":
        problem_store.backend_problem_files.publish(bucket_name, jobs, public_samples)
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
    # Publish all file bytes before switching authoritative metadata.
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
        _upload_many(client, bucket_name, jobs, dry, public_samples={
            f"{slug}/tests/{name}.{suffix}" for name in prob.samples for suffix in ("in", "out")})
    except Exception as e:
        return "failed", f"storage upload: {e}"
    if problem_store.backend_problem_files.backend() == "local":
        row["samples_data"] = []  # canonical sample bytes live only in backend files
    row["updated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        client.table("problems").upsert(row, on_conflict="slug").execute()
    except Exception as e:
        return "failed", f"db upsert: {e}"
    problem_store.invalidate_cache(slug)
    return status, f"tests={len(prob.tests)} hash={tests_hash}"


def import_numbers_only(client, slugs: list[str], dry: bool) -> tuple[int, int, list[str]]:
    """Publish only the catalog position and the difficulty band.

    A renumbering changes where a problem sits in the list, not the problem:
    the tests, the samples, the statement and the PDF are byte-identical, so
    this mode never touches a file. The `no` column is UNIQUE, so every
    existing number is first parked on a negative value; the final numbers are
    then written in one pass.
    """
    local: dict[str, int] = {}
    bands: dict[str, str] = {}
    for slug in slugs:
        try:
            prob = grader.load_problem(slug)
        except SystemExit as e:
            return 0, 0, [f"{slug}: loader: {e}"]
        if prob.no <= 0:
            return 0, 0, [f"{slug}: no number in config.json"]
        local[slug] = prob.no
        bands[slug] = prob.difficulty or ""
    if len(set(local.values())) != len(local):
        return 0, 0, ["duplicate numbers in the local catalog"]

    res = client.table("problems").select("slug,no").execute()
    rows = getattr(res, "data", None) or []
    remote = {str(r.get("slug")): int(r.get("no") or 0) for r in rows}
    if set(remote) != set(local):
        missing = sorted(set(local) - set(remote))
        extra = sorted(set(remote) - set(local))
        return 0, 0, [f"catalog differs from the database (missing {missing}, unknown {extra})"]

    moved = [slug for slug, no in local.items() if remote.get(slug) != no]
    if not moved:
        return 0, 0, []
    if dry:
        return len(moved), 0, []
    try:
        _park_numbers(client)
        # Every row is parked, so every row has to be written back: a slug whose
        # number did not change still holds its negative parking value.
        for slug in local:
            client.table("problems").update(
                {"no": local[slug], "difficulty": bands[slug],
                 "updated_at": dt.datetime.now(dt.timezone.utc).isoformat()}
            ).eq("slug", slug).execute()
    except Exception as e:
        return 0, len(moved), [f"numbers-only update failed: {e}"]
    return len(moved), 0, []


def import_statement_one(client, bucket_name: str, slug: str, dry: bool) -> tuple[str, str]:
    """Update public prose/PDF only; never upsert tests or publication flags.

    Upload to a content-addressed private path before switching the row, so a
    failed upload cannot pair a new statement with a missing/partial PDF. Old
    assets remain available for rollback. An updated_at guard rejects races.
    """
    try:
        pdir = grader.PROBLEMS_DIR / slug
        cfg = json.loads((pdir / "config.json").read_text(encoding="utf-8"))
        md = (pdir / "statement.md").read_text(encoding="utf-8")
        pdf = (pdir / "statement.pdf").read_bytes()
        if not md.strip() or not pdf.startswith(b"%PDF-"):
            return "failed", "empty statement or invalid PDF"
        rows = client.table("problems").select(
            "slug,no,title,time_limit,memory_limit,statement_md,statement_pdf_path,updated_at"
        ).eq("slug", slug).limit(1).execute().data or []
        if not rows:
            return "failed", "statement-only update requires an existing problem"
        row = rows[0]
        for key in ("no", "title", "time_limit", "memory_limit"):
            if cfg.get(key) != row.get(key):
                return "failed", f"local/remote {key} mismatch; no metadata changed"
        if not row.get("updated_at"):
            return "failed", "missing version; cannot safely update statement"
        digest = hashlib.sha256(pdf).hexdigest()
        path = f"{slug}/statements/{digest}.pdf"
        if row.get("statement_md") == md and row.get("statement_pdf_path") == path:
            return "skipped", "statement and PDF unchanged"
        if dry:
            return "updated", f"statement-only pdf={len(pdf)} bytes"
        _upload_many(client, bucket_name, [(path, pdf, "application/pdf")], dry=False)
        result = client.table("problems").update({
            "statement_md": md, "statement_pdf_path": path,
            "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        }).eq("slug", slug).eq("updated_at", row["updated_at"]).execute()
        if not result.data:
            return "failed", "problem changed during upload; retry after review"
        problem_store.invalidate_cache(slug)
        return "updated", f"statement-only pdf={len(pdf)} bytes sha256={digest}"
    except Exception as e:
        return "failed", f"statement update: {type(e).__name__}"


def _park_numbers(client) -> int:
    """Move every `problems.no` onto unique negatives to free the positive range.

    `no` carries a UNIQUE constraint (`no int unique not null`), so a full
    renumber (a permutation old -> new) cannot be written slug-by-slug while
    both ends still hold numbers: every target is momentarily occupied. Parking
    the current values on unique negative integers clears the range, then the
    normal import writes the canonical local numbers. Negatives are invisible
    to clients (the API sorts unnumbered rows last) and are replaced within the
    same run, so only a short window can see them.

    The parking values start below the lowest number already in the table, so
    a table that still holds negatives from an interrupted run is parked
    safely instead of colliding with them.
    """
    res = client.table("problems").select("slug,no").execute()
    rows = getattr(res, "data", None) or []
    if not rows:
        return 0
    used = {int(r.get("no") or 0) for r in rows}
    # Below zero and below everything already in use, so a table that still
    # holds negatives from an interrupted run is parked safely.
    nxt = min(min(used), 0) - 1
    for row in sorted(rows, key=lambda r: int(r.get("no") or 0)):
        value = nxt
        while value in used:
            value -= 1
        client.table("problems").update({"no": value}).eq("slug", row["slug"]).execute()
        used.add(value)
        nxt = value - 1
    return len(rows)


def _prune_storage(client, bucket_name: str, slug: str, dry: bool) -> list[str]:
    """Delete Storage objects under `<slug>/tests/` that no longer exist locally.

    Uploads are upserts, so a problem whose test set shrank (or was renamed)
    leaves stale objects behind. They are never referenced again (the row stores
    an explicit manifest), but they waste space and confuse audits. Only files
    inside the problem's own `tests/` folder are considered; everything else is
    left untouched. Returns the object paths removed (or that would be removed).
    """
    pdir = grader.PROBLEMS_DIR / slug
    tdir = pdir / "tests"
    expected = {f"{slug}/tests/{p.name}" for p in tdir.glob("*.in")}
    expected |= {f"{slug}/tests/{p.name}" for p in tdir.glob("*.out")}
    try:
        listed = client.storage.from_(bucket_name).list(f"{slug}/tests")
    except Exception as e:
        print(f"prune {slug}: could not list: {e}", file=sys.stderr)
        return []
    # Real Supabase returns the object's basename; the test double returns the
    # full path. Normalise on the basename so both agree.
    stale = []
    for obj in (listed or []):
        name = str(obj.get("name", "")).rsplit("/", 1)[-1]
        path = f"{slug}/tests/{name}"
        if name and path not in expected:
            stale.append(path)
    stale.sort()
    if stale and not dry:
        client.storage.from_(bucket_name).remove(stale)
    return stale


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Import problems/ into Supabase (idempotent).")
    ap.add_argument("--problem", action="append", default=[], dest="problems",
                    help="slug to import (repeatable; default: all)")
    ap.add_argument("--bucket", default=os.environ.get("GRADER_PROBLEM_BUCKET", "judge-assets"),
                    help="private Storage bucket (default: %(default)s)")
    ap.add_argument("--dry-run", action="store_true",
                    help="validate + report without writing Postgres or Storage")
    ap.add_argument("--strict", action="store_true",
                    help="run strict local authoring validation before any remote access or writes")
    ap.add_argument("--statements-only", action="store_true",
                    help="update existing prose/PDF only; preserve tests, IDs and visibility")
    ap.add_argument("--renumber", action="store_true",
                    help="first park the existing DB numbers on negatives so a full "
                         "local renumber (tools/number_problems.py --renumber) can be "
                         "upserted without UNIQUE clashes")
    ap.add_argument("--prune", action="store_true",
                    help="also delete Storage test objects for this problem that no "
                         "longer exist locally (stale after a shrinking test set)")
    ap.add_argument("--numbers-only", action="store_true",
                    help="publish only the catalog number and the difficulty band; "
                         "never touch tests, samples, statements or visibility")
    args = ap.parse_args(argv)
    if args.numbers_only and (args.statements_only or args.prune or args.renumber):
        ap.error("--numbers-only cannot be combined with --statements-only/--prune/--renumber")
    if not args.dry_run and not args.numbers_only and \
            problem_store.backend_problem_files.backend() != "local":
        ap.error("production file publishing requires GRADER_FILE_STORAGE=local and private backend roots")
    if args.prune and problem_store.backend_problem_files.backend() == "local":
        ap.error("local immutable file versions cannot be pruned by this tool")
    if args.statements_only and (args.renumber or args.prune):
        ap.error("--statements-only cannot renumber or prune assets")
    slugs = _local_slugs(args.problems)
    if not slugs:
        print("no problems to import")
        return 1 if args.strict else 0
    if args.strict:
        from tools.validate_problem import main as validate
        if validate(["--strict", *slugs]) != 0:
            print("strict preflight failed; no remote operations performed", file=sys.stderr)
            return 1
    # Even legacy packages cannot publish statement examples that disagree
    # with the declared public fixtures. This check is offline and read-only.
    from tools.validate_problem import public_sample_errors
    from tools.statement_build import check_build
    for slug in slugs:
        try:
            prob = grader.load_problem(slug)
            errors = public_sample_errors({"samples": prob.samples}, prob.description, prob.tests)
            pdir = grader.PROBLEMS_DIR / slug
            cfg = json.loads((pdir / "config.json").read_text(encoding="utf-8"))
            errors.extend(check_build(pdir, cfg, prob.description, required=args.strict))
        except (SystemExit, OSError, ValueError):
            errors = ["cannot load local problem package"]
        if errors:
            print(f"{slug}: public sample preflight failed: " + "; ".join(errors), file=sys.stderr)
            return 1
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
    elif not args.dry_run or args.statements_only:
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
    if args.statements_only and client is None:
        print("statement-only updates require reachable remote metadata", file=sys.stderr)
        return 2
    if args.numbers_only:
        if client is None:
            print("numbers-only updates require reachable remote metadata", file=sys.stderr)
            return 2
        moved, failed, errors = import_numbers_only(client, slugs, dry=args.dry_run)
        for error in errors:
            print(f"x numbers-only: {error}", file=sys.stderr)
        if errors:
            return 1
        mode = "DRY-RUN " if args.dry_run else ""
        print(f"{mode}numbers-only: {moved} of {len(slugs)} problems would move "
              f"to their new number" if args.dry_run else
              f"numbers-only: moved {moved} of {len(slugs)} problems to their new number")
        if failed:
            return 1
        return 0
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
        importer = import_statement_one if args.statements_only else import_one
        status, detail = importer(client, args.bucket, slug, dry=args.dry_run) \
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
    if args.prune and client is not None:
        removed = 0
        for slug in slugs:
            stale = _prune_storage(client, args.bucket, slug, args.dry_run)
            if stale:
                removed += len(stale)
                verb = "stale" if args.dry_run else "removed"
                names = ", ".join(s.rsplit("/", 1)[-1] for s in stale)
                print(f"p {slug:<24} {verb} {len(stale)}: {names}")
        print(f"prune: {removed} stale object(s) "
              f"{'would be removed' if args.dry_run else 'removed'}")
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
