#!/usr/bin/env python3
"""Problem repository: local problems/ directory or Supabase (Postgres + Storage).

Supabase is storage, not execution: this module only resolves problem metadata
and test bytes. Compilation/execution stay in grader.py / judge_runner.py.

Sources (explicit, no silent fallback):
  GRADER_PROBLEM_SOURCE=local    (default) read problems/ from disk via grader.load_problem
  GRADER_PROBLEM_SOURCE=supabase read Postgres `problems` + private Storage bucket
    `judge-assets` with the service_role key (server-side only).

Postgres holds queryable metadata + PUBLIC statement/samples.
Storage holds hidden test files + statement PDFs (private bucket, no public URLs).
Hidden test contents never appear in public rows: the `problems` row keeps only
a manifest [{name, sha256, size_in, size_out}] for hidden tests.

Caching: Problems are immutable for a given tests_hash, so fetched Problems are
cached by slug and invalidated when the row's tests_hash/updated_at changes.
Bounded LRU (MAX_CACHED_PROBLEMS) + TTL (CACHE_TTL_S). This avoids downloading
every hidden test file on every submission.
"""
from __future__ import annotations

import hashlib
import os
import sys
import time
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import grader  # noqa: E402


class ProblemNotFound(Exception):
    pass


class ProblemUnavailable(Exception):
    """Database/storage failure, missing assets, or misconfiguration.

    Callers must surface this as a job-level error / 500, never as Accepted
    and never as an empty successful test suite.
    """


def problem_source() -> str:
    return (os.environ.get("GRADER_PROBLEM_SOURCE", "local").strip().lower() or "local")


def problem_bucket() -> str:
    return (os.environ.get("GRADER_PROBLEM_BUCKET", "judge-assets").strip() or "judge-assets")


def cache_ttl_s() -> float:
    try:
        return max(0.0, float(os.environ.get("GRADER_PROBLEM_CACHE_TTL", "30") or "30"))
    except ValueError:
        return 30.0


MAX_CACHED_PROBLEMS = 200
MAX_CACHED_PDFS = 50
PDF_CACHE_TTL_S = 300.0

# slug -> (Problem, tests_hash, updated_at, fetched_monotonic)
_PROBLEMS_CACHE: "OrderedDict[str, tuple]" = OrderedDict()
# slug -> (bytes, fetched_monotonic, (updated_at, statement_pdf_path))
_PDF_CACHE: "OrderedDict[str, tuple]" = OrderedDict()


def invalidate_cache(slug: Optional[str] = None) -> None:
    if slug is None:
        _PROBLEMS_CACHE.clear()
        _PDF_CACHE.clear()
    else:
        _PROBLEMS_CACHE.pop(slug, None)
        _PDF_CACHE.pop(slug, None)


def invalidate_stale(hashmap: Dict[str, str], extra: Optional[dict] = None) -> list:
    """Drop cached full problems whose version changed (or row vanished).

    The next access lazy-reloads them (row + Storage). Returns dropped slugs.
    Used by the metadata-only TTL refresh so unchanged problems are never
    re-downloaded.
    """
    dropped = []
    for slug, entry in list(_PROBLEMS_CACHE.items()):
        if hashmap.get(slug) != entry[1]:
            _PROBLEMS_CACHE.pop(slug, None)
            _PDF_CACHE.pop(slug, None)
            dropped.append(slug)
    # PDFs can change without any test change, including when no full problem
    # has ever been cached. Check their independent metadata version too.
    if extra is not None:
        for slug, entry in list(_PDF_CACHE.items()):
            if slug not in extra or entry[2] != _pdf_version(extra[slug]):
                _PDF_CACHE.pop(slug, None)
    return dropped


def _cache_get(slug: str):
    entry = _PROBLEMS_CACHE.get(slug)
    if entry is None:
        return None
    _PROBLEMS_CACHE.move_to_end(slug)
    return entry


def _cache_put(slug: str, entry: tuple) -> None:
    _PROBLEMS_CACHE[slug] = entry
    _PROBLEMS_CACHE.move_to_end(slug)
    while len(_PROBLEMS_CACHE) > MAX_CACHED_PROBLEMS:
        _PROBLEMS_CACHE.popitem(last=False)


def _pdf_get(slug: str) -> Optional[bytes]:
    entry = _PDF_CACHE.get(slug)
    if entry is None:
        return None
    data, at, _version = entry
    if time.monotonic() - at > PDF_CACHE_TTL_S:
        _PDF_CACHE.pop(slug, None)
        return None
    _PDF_CACHE.move_to_end(slug)
    return data


def _pdf_version(row: dict) -> tuple:
    return (str(row.get("updated_at") or ""),
            str(row.get("statement_pdf_path") or ""))


def _pdf_put(slug: str, data: bytes, row: dict) -> None:
    _PDF_CACHE[slug] = (data, time.monotonic(), _pdf_version(row))
    _PDF_CACHE.move_to_end(slug)
    while len(_PDF_CACHE) > MAX_CACHED_PDFS:
        _PDF_CACHE.popitem(last=False)


def _require_source(value: str) -> str:
    v = (value or "").strip().lower() or "local"
    if v not in ("local", "supabase"):
        raise ProblemUnavailable(f"unknown GRADER_PROBLEM_SOURCE={value!r} (want local|supabase)")
    return v


def _local_all() -> Dict[str, grader.Problem]:
    out: Dict[str, grader.Problem] = {}
    if not grader.PROBLEMS_DIR.is_dir():
        return out
    for pdir in sorted(grader.PROBLEMS_DIR.iterdir()):
        if not pdir.is_dir():
            continue
        try:
            p = grader.load_problem(pdir.name)
        except SystemExit as e:
            print(f"[problems] skip {pdir.name}: {e}", file=sys.stderr)
            continue
        out[p.pid] = p
    return out


def _row_to_problem(row: dict, tests: List[grader.TestCase]) -> grader.Problem:
    tags = row.get("tags") or []
    samples = row.get("samples") or []
    return grader.Problem(
        pid=str(row.get("slug") or row.get("id") or ""),
        title=str(row.get("title") or ""),
        time_limit=float(row.get("time_limit") or 1.0),
        memory_limit=int(row.get("memory_limit") or 256),
        checker=str(row.get("checker") or "token"),
        tolerance=float(row.get("tolerance") or 1e-6),
        description=str(row.get("statement_md") or row.get("statement") or ""),
        tests=list(tests),
        difficulty=str(row.get("difficulty") or ""),
        tags=[str(t) for t in tags] if isinstance(tags, list) else [],
        samples=[str(s) for s in samples] if isinstance(samples, list) else [],
        hidden=bool(row.get("hidden", False)),
        no=int(row.get("no") or 0),
        is_published=bool(row.get("is_published", True)),
    )


def load_metadata_only(client=None) -> Dict[str, grader.Problem]:
    """Fetch problem metadata only — no hidden test downloads.

    Returns Problems whose `tests` list contains public samples only.
    Callers that need to judge must reload the full problem via
    `load_problem_supabase` (or `get_problem`) before judging, otherwise
    hidden tests are missing and judging must fail closed.
    """
    return load_snapshot(client)[0]


def load_tests_hash_map(client=None) -> Dict[str, str]:
    """อ่าน {slug: tests_hash} จากตาราง problems โดยไม่ดาวน์โหลดไฟล์เทสต์

    ใช้เติม _TESTS_HASH_CACHE ตอน boot ในโหมด supabase ได้ทันที
    โดยไม่ต้องรอโหลดเทสต์ลับจาก Storage
    """
    return load_snapshot(client)[1]


def load_snapshot(client=None) -> tuple:
    """One SELECT *: (meta, hashes, extra). No Storage access.

    meta[slug] = Problem with samples-only tests (fast browsing);
    hashes[slug] = tests_hash; extra[slug] = {"tests": total count,
    "has_pdf": bool}. Powers boot/refresh/detail/version without downloads.
    """
    client = client if client is not None else _supabase_client()
    rows = _fetch_all_rows(client)
    meta: Dict[str, grader.Problem] = {}
    hashes: Dict[str, str] = {}
    extra: Dict[str, dict] = {}
    for row in rows:
        slug = str(row.get("slug") or "")
        if not slug:
            continue
        samples_data = row.get("samples_data") or []
        tests: List[grader.TestCase] = []
        try:
            for entry in samples_data:
                tests.append(grader.TestCase(
                    name=str(entry["name"]),
                    input=str(entry.get("input", "")),
                    expected=str(entry.get("expected", "")),
                ))
        except (TypeError, KeyError, AttributeError) as e:
            print(f"[problems] skip {slug}: corrupt samples_data ({e})",
                  file=sys.stderr)
            continue
        tests.sort(key=lambda t: t.name)
        prob = _row_to_problem(row, tests)
        if not prob.pid:
            continue
        meta[slug] = prob
        th = str(row.get("tests_hash") or "")
        if th:
            hashes[slug] = th
        total = row.get("tests_count") or 0
        try:
            total = int(total)
        except (TypeError, ValueError):
            total = 0
        if total <= 0:
            hidden_manifest = row.get("hidden_tests") or []
            total = len(hidden_manifest) + len(prob.samples)
        extra[slug] = {"tests": total,
                       "has_pdf": bool(row.get("statement_pdf_path")),
                       "updated_at": row.get("updated_at"),
                       "statement_pdf_path": row.get("statement_pdf_path")}
    return meta, hashes, extra


def fetch_row(slug: str, client=None) -> dict:
    """Fetch one problems row (metadata + samples_data + manifest).

    Never touches hidden test bytes. Raises ProblemNotFound / ProblemUnavailable.
    """
    return _fetch_row(client if client is not None else _supabase_client(), slug)


def load_meta(slug: str, client=None) -> tuple:
    """Metadata-only single problem + its row. No Storage access (fast browsing)."""
    row = fetch_row(slug, client)
    samples_data = row.get("samples_data") or []
    tests: List[grader.TestCase] = []
    try:
        for entry in samples_data:
            tests.append(grader.TestCase(
                name=str(entry["name"]),
                input=str(entry.get("input", "")),
                expected=str(entry.get("expected", "")),
            ))
    except (TypeError, KeyError, AttributeError) as e:
        raise ProblemUnavailable(f"problem {slug!r} has corrupt samples_data: {e}")
    tests.sort(key=lambda t: t.name)
    prob = _row_to_problem(row, tests)
    if not prob.pid:
        raise ProblemUnavailable(f"problem row for {slug!r} is missing slug")
    return prob, row


def serialize_problem(prob: grader.Problem) -> dict:
    """Embed a fully-resolved problem for the isolated judge subprocess.

    Trusted server-side channel only (payload stdin of judge_runner --job),
    never client-supplied. Lets the runner judge without disk or Supabase.
    """
    return {
        "pid": prob.pid, "title": prob.title,
        "time_limit": prob.time_limit, "memory_limit": prob.memory_limit,
        "checker": prob.checker, "tolerance": prob.tolerance,
        "description": prob.description,
        "tests": [{"name": t.name, "input": t.input, "expected": t.expected}
                  for t in prob.tests],
        "difficulty": prob.difficulty, "tags": list(prob.tags),
        "samples": list(prob.samples), "hidden": bool(prob.hidden),
        "no": int(prob.no), "is_published": bool(getattr(prob, "is_published", True)),
    }


def deserialize_problem(data: dict) -> grader.Problem:
    try:
        pid = str(data["pid"])
        tests = [grader.TestCase(name=str(t["name"]), input=str(t.get("input", "")),
                                 expected=str(t.get("expected", "")))
                 for t in (data.get("tests") or [])]
    except (KeyError, TypeError, AttributeError) as e:
        raise ProblemUnavailable(f"invalid embedded problem payload: {e}")
    if not pid or not tests:
        # Never judge an empty suite as success.
        raise ProblemUnavailable("embedded problem has no tests (refusing to judge)")
    return grader.Problem(
        pid=pid, title=str(data.get("title") or pid),
        time_limit=float(data.get("time_limit") or 1.0),
        memory_limit=int(data.get("memory_limit") or 256),
        checker=str(data.get("checker") or "token"),
        tolerance=float(data.get("tolerance") or 1e-6),
        description=str(data.get("description") or ""),
        tests=tests,
        difficulty=str(data.get("difficulty") or ""),
        tags=list(data.get("tags") or []),
        samples=list(data.get("samples") or []),
        hidden=bool(data.get("hidden", False)),
        no=int(data.get("no") or 0),
        is_published=bool(data.get("is_published", True)),
    )


def _supabase_client():
    url = (os.environ.get("SUPABASE_URL", "") or "").strip()
    key = (os.environ.get("SUPABASE_KEY", "") or "").strip()
    if not url or not key:
        raise ProblemUnavailable("supabase problem source needs SUPABASE_URL + SUPABASE_KEY")
    try:
        from supabase import create_client
    except ImportError as e:
        raise ProblemUnavailable(f"supabase lib not installed: {e}")
    try:
        return create_client(url, key)
    except Exception as e:
        raise ProblemUnavailable(f"cannot create supabase client: {e}")


def _fetch_row(client, slug: str) -> dict:
    try:
        res = client.table("problems").select("*").eq("slug", slug).limit(1).execute()
    except Exception as e:
        raise ProblemUnavailable(f"problem lookup failed for {slug!r}: {e}")
    rows = getattr(res, "data", None) or []
    if not rows:
        raise ProblemNotFound(f"unknown problem: {slug}")
    return dict(rows[0])


def _fetch_all_rows(client) -> List[dict]:
    try:
        res = client.table("problems").select("*").order("no").limit(1000).execute()
    except Exception as e:
        raise ProblemUnavailable(f"problem listing failed: {e}")
    return [dict(r) for r in (getattr(res, "data", None) or [])]


def _download(client, bucket: str, path: str) -> bytes:
    """Download an object from private Storage with a hard timeout.

    Uses urllib (stdlib) instead of storage3 because storage3's SyncClient has
    no request timeout — a slow or unreachable Storage endpoint hangs the worker
    thread forever, which wedges the whole server (only 1 worker on small hosts).
    In tests (FakeSupabase), use the in-memory storage directly.
    """
    # FakeSupabase (tests): in-memory storage, no HTTP needed.
    if getattr(client, "tables", None) is not None:
        try:
            return client.storage.from_(bucket).download(path)
        except Exception as e:
            raise ProblemUnavailable(f"storage download failed for {path!r}: {e}")

    from urllib.request import Request, urlopen
    from urllib.error import URLError, HTTPError
    import urllib.parse

    url = getattr(client, "supabase_url", "") or os.environ.get("SUPABASE_URL", "")
    key = getattr(client, "supabase_key", "") or os.environ.get("SUPABASE_KEY", "")
    if not url or not key:
        raise ProblemUnavailable("supabase download needs SUPABASE_URL + SUPABASE_KEY")
    url = url.rstrip("/")
    object_url = f"{url}/storage/v1/object/{bucket}/{urllib.parse.quote(path, safe='')}"
    req = Request(
        object_url,
        headers={
            "Authorization": f"Bearer {key}",
            "apikey": key,
        },
    )
    try:
        with urlopen(req, timeout=30) as resp:
            data = resp.read()
    except HTTPError as e:
        body = e.read()
        raise ProblemUnavailable(
            f"storage download failed for {path!r}: HTTP {e.code} {body[:200]}"
        )
    except URLError as e:
        raise ProblemUnavailable(
            f"storage download failed for {path!r}: {e}"
        )
    except Exception as e:
        raise ProblemUnavailable(f"storage download failed for {path!r}: {e}")

    if isinstance(data, str):
        data = data.encode("utf-8")
    if not isinstance(data, (bytes, bytearray, memoryview)):
        raise ProblemUnavailable(f"storage download returned unexpected type for {path!r}")
    return bytes(data)


def load_problem_supabase(slug: str, client=None) -> grader.Problem:
    """Load one problem (metadata from Postgres, hidden tests from Storage).

    Samples come from the row's samples_data; hidden tests are downloaded from
    the private bucket. Any missing asset or failure raises ProblemUnavailable
    (never an empty suite).
    """
    client = client if client is not None else _supabase_client()
    bucket = problem_bucket()
    row = _fetch_row(client, slug)
    # TTL fast path: same version still cached.
    cached = _cache_get(slug)
    ttl = cache_ttl_s()
    if cached is not None:
        _prob, _hash, _updated, _at = cached
        if ttl > 0 and time.monotonic() - _at < ttl and _hash == (row.get("tests_hash") or ""):
            return _prob
    samples_data = row.get("samples_data") or []
    sample_map: Dict[str, Tuple[str, str]] = {}
    try:
        for entry in samples_data:
            sample_map[str(entry["name"])] = (str(entry.get("input", "")),
                                              str(entry.get("expected", "")))
    except (TypeError, KeyError, AttributeError) as e:
        raise ProblemUnavailable(f"problem {slug!r} has corrupt samples_data: {e}")
    hidden_manifest = row.get("hidden_tests") or []
    try:
        hidden_names = [str(e["name"]) if isinstance(e, dict) else str(e)
                        for e in hidden_manifest]
    except (TypeError, AttributeError) as e:
        raise ProblemUnavailable(f"problem {slug!r} has corrupt hidden_tests manifest: {e}")
    tests: List[grader.TestCase] = []
    for entry in samples_data:
        try:
            tests.append(grader.TestCase(name=str(entry["name"]),
                                         input=str(entry.get("input", "")),
                                         expected=str(entry.get("expected", ""))))
        except (TypeError, KeyError, AttributeError) as e:
            raise ProblemUnavailable(f"problem {slug!r} has corrupt sample {entry!r}: {e}")
    wanted = [n for n in hidden_names if n not in sample_map]
    if wanted:
        # I/O-bound: fetch hidden files concurrently (one HTTPS request per
        # file). Bounded pool; any single failure aborts the whole load
        # (fail closed — the caller never sees a partial suite).
        from concurrent.futures import ThreadPoolExecutor

        def _fetch_one(name: str) -> grader.TestCase:
            raw_in = _download(client, bucket, f"{slug}/tests/{name}.in")
            raw_out = _download(client, bucket, f"{slug}/tests/{name}.out")
            try:
                return grader.TestCase(name=name,
                                       input=raw_in.decode("utf-8"),
                                       expected=raw_out.decode("utf-8"))
            except UnicodeDecodeError as e:
                raise ProblemUnavailable(
                    f"problem {slug!r} test {name!r} is not UTF-8: {e}")

        with ThreadPoolExecutor(max_workers=min(8, len(wanted))) as ex:
            tests.extend(list(ex.map(_fetch_one, wanted)))
    if not tests:
        raise ProblemUnavailable(f"problem {slug!r} has no tests (refusing to judge)")
    tests.sort(key=lambda t: t.name)
    prob = _row_to_problem(row, tests)
    if not prob.pid:
        raise ProblemUnavailable(f"problem row for {slug!r} is missing slug")
    # Verify the assembled suite matches the stored hash when present; a
    # mismatch means the row and Storage disagree (partial import / corruption).
    stored_hash = str(row.get("tests_hash") or "")
    if stored_hash:
        actual = grader.tests_hash(prob)
        if actual != stored_hash:
            raise ProblemUnavailable(
                f"problem {slug!r} hash mismatch (row {stored_hash} != assembled {actual}): "
                "re-run tools/import_problems_supabase.py")
    _cache_put(slug, (prob, stored_hash, str(row.get("updated_at") or ""), time.monotonic()))
    return prob


def load_all_supabase(client=None) -> Dict[str, grader.Problem]:
    client = client if client is not None else _supabase_client()
    rows = _fetch_all_rows(client)
    out: Dict[str, grader.Problem] = {}
    for row in rows:
        slug = str(row.get("slug") or "")
        if not slug:
            continue
        try:
            out[slug] = load_problem_supabase(slug, client=client)
        except (ProblemNotFound, ProblemUnavailable) as e:
            print(f"[problems] skip {slug}: {e}", file=sys.stderr)
            continue
    return out


def load_all(source: Optional[str] = None, client=None) -> Dict[str, grader.Problem]:
    src = _require_source(source if source is not None else problem_source())
    if src == "local":
        return _local_all()
    return load_all_supabase(client=client)


def get_problem(slug: str, source: Optional[str] = None, client=None) -> grader.Problem:
    src = _require_source(source if source is not None else problem_source())
    if src == "local":
        try:
            return grader.load_problem(slug)
        except SystemExit as e:
            raise ProblemNotFound(str(e))
    # Supabase: TTL cache first. Fresh cache wins without a row fetch; version
    # revalidation happens on TTL expiry via load_problem_supabase.
    ttl = cache_ttl_s()
    cached = _cache_get(slug)
    if cached is not None and ttl > 0 and time.monotonic() - cached[3] < ttl:
        return cached[0]
    return load_problem_supabase(slug, client=client)


def has_statement_pdf(slug: str, source: Optional[str] = None, client=None) -> bool:
    src = _require_source(source if source is not None else problem_source())
    if src == "local":
        return (grader.PROBLEMS_DIR / slug / "statement.pdf").is_file()
    cli = client if client is not None else _supabase_client()
    if _pdf_get(slug) is not None:
        return True
    try:
        row = _fetch_row(cli, slug)
    except (ProblemNotFound, ProblemUnavailable):
        return False
    return bool(row.get("statement_pdf_path"))


def get_statement_pdf(slug: str, source: Optional[str] = None, client=None) -> bytes:
    src = _require_source(source if source is not None else problem_source())
    if src == "local":
        f = grader.PROBLEMS_DIR / slug / "statement.pdf"
        if not f.is_file():
            raise ProblemNotFound(f"no PDF statement for {slug}")
        return f.read_bytes()
    cached = _pdf_get(slug)
    if cached is not None:
        return cached
    cli = client if client is not None else _supabase_client()
    row = _fetch_row(cli, slug)
    pdf_path = row.get("statement_pdf_path") or f"{slug}/statement.pdf"
    data = _download(cli, problem_bucket(), str(pdf_path))
    if not data.startswith(b"%PDF"):
        raise ProblemUnavailable(f"problem {slug!r} PDF looks corrupt (missing %PDF header)")
    _pdf_put(slug, data, row)
    return data


def manifest_for_problem(prob: grader.Problem) -> Tuple[list, list]:
    """Split a local Problem into public samples_data + hidden manifest.

    Used by the import script so the DB row and Storage contents stay in sync
    with the loader semantics (samples = public, everything else = hidden).
    """
    sample_set = set(prob.samples)
    samples_data = [{"name": t.name, "input": t.input, "expected": t.expected}
                    for t in prob.tests if t.name in sample_set]
    hidden = []
    for t in prob.tests:
        if t.name in sample_set:
            continue
        raw_in = t.input.encode("utf-8", "replace")
        raw_out = t.expected.encode("utf-8", "replace")
        digest = hashlib.sha256(raw_in + b"\x00" + raw_out).hexdigest()[:16]
        hidden.append({"name": t.name, "sha256": digest,
                       "size_in": len(raw_in),
                       "size_out": len(raw_out)})
    hidden.sort(key=lambda e: e["name"])
    return samples_data, hidden
