#!/usr/bin/env python3
"""Web server for the brutal CP grader.

Stack: FastAPI + Uvicorn (backend) + vanilla HTML/CSS/JS (frontend, no build step).
Judging logic is reused directly from grader.py (no subprocess, no duplication).

Run:
    python3 server.py                  # http://127.0.0.1:8000
    python3 server.py --port 8080
"""
from __future__ import annotations

import asyncio
import collections
import concurrent.futures
import datetime as dt
import hashlib
import hmac
import json
import os
import re
import secrets
import sys
import tempfile
import time
import traceback
import uuid
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlencode
from urllib.request import Request as URLRequest
from urllib.request import urlopen

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from starlette.responses import RedirectResponse
from itsdangerous import URLSafeTimedSerializer

try:
    from supabase import create_client
    _has_supabase_lib = True
except ImportError:  # optional dep: history disabled without it
    create_client = None
    _has_supabase_lib = False

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import grader  # noqa: E402  (CLI grader module, import-safe: guarded by __main__)

STATIC_DIR = ROOT / "static"


def _load_dotenv() -> None:
    """Local-dev convenience only: load ROOT/.env into env (never commit it).
    Real env vars always win. Production uses host env vars, no .env file."""
    try:
        with open(ROOT / ".env", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
    except FileNotFoundError:
        pass
    except Exception as e:
        print(f"[web] warning: cannot read .env: {e}", file=sys.stderr)


_load_dotenv()

LANGS: Dict[str, Dict[str, object]] = {
    "python": {"name": "Python 3", "ext": ".py", "accept": [".py"]},
    "c": {"name": "C (C11)", "ext": ".c", "accept": [".c"]},
    "cpp": {"name": "C++ (C++17)", "ext": ".cpp", "accept": [".cpp", ".cc", ".cxx"]},
}
EXT2LANG = {".py": "python", ".c": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp"}

MAX_CODE_BYTES = 256 * 1024   # 256 KB source cap
DETAIL_HEAD = 4000            # max chars of detail/diff sent to frontend

# ---- capacity, derived from the host/container this runs in ----
# Prod is a fractional vCPU container (0.5 CPU / 0.5 GB): judging two submissions
# at once, or running 4 tests of one submission in parallel, oversubscribes the
# core and produces wall-clock TLEs that have nothing to do with the student's
# code. Everything below is auto-derived from cgroup limits (see grader.cpu_quota
# / grader.ram_limit_mb) and overridable by env when the host changes.
CPU_QUOTA = grader.CPU_QUOTA
RAM_MB = grader.RAM_MB


def _env_int(name: str, auto: int) -> int:
    """`0`/unset = auto (host derived); any positive value wins."""
    raw = os.environ.get(name, "").strip()
    if raw:
        try:
            val = int(raw)
            if val > 0:
                return val
        except ValueError:
            print(f"[web] warning: bad {name}={raw!r}, using auto", file=sys.stderr)
    return auto


JUDGE_JOBS = _env_int("GRADER_JUDGE_JOBS", 4 if CPU_QUOTA >= 2 else 1)
JUDGE_WORKERS = _env_int("GRADER_JUDGE_WORKERS", 2 if CPU_QUOTA >= 2 else 1)
# Per-test memory ceiling. A problem may declare 512 MB, but letting a 512 MB
# process loose in a 512 MB container OOM-kills the judge server itself, so the
# effective limit is capped to half the container (reported as limits.capped).
MEMORY_CAP_MB = _env_int("GRADER_MEMORY_CAP_MB", max(64, int(RAM_MB * 0.5)))
QUEUE_MAX = _env_int("GRADER_QUEUE_MAX", 25)
# Worst case per submission = compile + every test at its limit, serially.
OVERALL_TIMEOUT = float(os.environ.get("GRADER_OVERALL_TIMEOUT", "") or 0) or (
    90.0 if CPU_QUOTA >= 2 else 240.0)

print(f"[web] host: cpu={CPU_QUOTA:g} core(s), ram={RAM_MB}MB -> "
      f"workers={JUDGE_WORKERS}, tests/submission={JUDGE_JOBS}, "
      f"memory_cap={MEMORY_CAP_MB}MB, queue_max={QUEUE_MAX}, "
      f"overall_timeout={OVERALL_TIMEOUT:g}s, "
      f"sample_interval={grader.SAMPLE_INTERVAL * 1000:g}ms, "
      f"compile_timeout={grader.COMPILE_TIMEOUT:g}s", file=sys.stderr)

# ---- async judging (B9) ----
# The HTTP path never judges inline: it queues a job and the client polls
# /api/jobs/{id}. Workers live in the same process (one container deploy), each
# running a job in a thread so uvicorn's loop stays responsive. Concurrency and
# limits are host derived — see the capacity block above.
JOB_TTL_S = 3600              # in-memory job records kept this long (no-DB mode)
JOB_MAX_AGE_S = 24 * 3600     # queued jobs older than this are dropped, not run
REJUDGE_MAX = 200             # cap per /api/admin/rejudge call

# ---- /api/run (custom input playground) ----
RUN_INPUT_MAX = 64 * 1024     # max bytes of user-supplied stdin
RUN_OUTPUT_MAX = 64 * 1024    # max bytes echoed back
RUN_TIMEOUT_MAX = 5.0         # hard cap for playground runs
RUN_BUDGET = 30.0             # total CPU-seconds a single /api/run may spend

# ---- per-user quotas (fair-use; "N/WINDOW_SECONDS", 0 = off) ----
def _parse_quota(raw: str, default: tuple) -> tuple:
    try:
        n, w = raw.split("/", 1)
        n_i, w_i = int(n), int(w)
        if n_i <= 0 or w_i <= 0:
            return (0, 0)  # disabled
        return (n_i, w_i)
    except ValueError:
        return default

SUBMIT_QUOTA = _parse_quota(os.environ.get("GRADER_SUBMIT_QUOTA", "60/600"), (60, 600))
RUN_QUOTA = _parse_quota(os.environ.get("GRADER_RUN_QUOTA", "120/600"), (120, 600))

@asynccontextmanager
async def _lifespan(_app: "FastAPI"):
    """Start judge workers and recover jobs left behind by a restart."""
    workers = [asyncio.create_task(_judge_worker(i)) for i in range(JUDGE_WORKERS)]
    try:
        await _recover_jobs()
    except Exception as e:  # never block startup on a DB hiccup
        print(f"[web] job recovery failed: {e}", file=sys.stderr)
    try:
        yield
    finally:
        for w in workers:
            w.cancel()
        await asyncio.gather(*workers, return_exceptions=True)


app = FastAPI(title="Newbiegrader API", version="2.0.0", lifespan=_lifespan)
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.middleware("http")
async def _security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
        "font-src https://fonts.gstatic.com; img-src 'self' data: https:; "
        "frame-src 'self'; frame-ancestors 'self'; "
        "form-action 'self' https://accounts.google.com")
    return resp


# Tiny in-memory cache for slow aggregate endpoints (Supabase RTT dominates).
# Invalidated on every stored submission.
_cache: dict = {}
CACHE_TTL = {"stats": 30, "leaderboard": 60}


def _cached(key: str, ttl: int, build):
    now = time.monotonic()
    hit = _cache.get(key)
    if hit and now - hit[0] < ttl:
        return hit[1]
    val = build()  # raises HTTPException on DB error: never cached
    _cache[key] = (now, val)
    return val


def _bust_cache() -> None:
    _cache.pop("stats", None)
    # leaderboard keys carry the limit ("leaderboard:50") — clear them all,
    # otherwise scores stay stale for the full 60s TTL after every submit.
    for k in [k for k in _cache if k.startswith("leaderboard")]:
        _cache.pop(k, None)

# Split deployment: same-origin via frontend /api proxy (Cloudflare Pages
# Function or legacy vercel.json), so the browser never talks cross-origin.
# GRADER_CORS_ORIGINS stays empty in prod (e.g. https://gradernew.pages.dev
# needs no CORS). Set it only when serving the frontend from a host WITHOUT
# the /api proxy, e.g. GRADER_CORS_ORIGINS=https://gradernew.pages.dev
# Empty (default) = same-origin only, no CORS headers.
_cors_origins = [o.strip() for o in
                 os.environ.get("GRADER_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
        allow_credentials=True,  # kept for non-proxied hosts; proxied prod is same-origin
    )

# ---- Supabase (optional): submission history + stats ----
# Server-side only. SUPABASE_KEY must be the service_role key (never the
# anon key, never exposed to the frontend). Unset = history disabled.
_sb = None
_sb_url = os.environ.get("SUPABASE_URL", "").strip()
_sb_key = os.environ.get("SUPABASE_KEY", "").strip()
if _sb_url and _sb_key:
    if not _has_supabase_lib:
        print("[web] supabase lib not installed, history disabled", file=sys.stderr)
    else:
        try:
            _sb = create_client(_sb_url, _sb_key)
        except Exception as e:
            print(f"[web] supabase disabled: {e}", file=sys.stderr)
            _sb = None


def _db_err(e: Exception) -> HTTPException:
    """Log the real DB error server-side, return a generic 500 to clients."""
    print(f"[web] database error: {e}", file=sys.stderr)
    return HTTPException(status_code=500, detail="database error")


async def _store_submission(row: dict, target_id: Optional[str] = None) -> Optional[str]:
    """Persist one submission (insert, or update when rejudging).

    Never fails the judging response: returns the row id, or None when history is
    disabled / the write failed.
    """
    if _sb is None:
        return None

    def _write():
        if target_id:
            return _sb.table("submissions").update(row).eq("id", target_id).execute()
        try:
            return _sb.table("submissions").insert(row).execute()
        except Exception as first:
            # Pre-2026-10 database: the extra traceability columns do not exist
            # yet. Drop them rather than losing the submission.
            slim = {k: v for k, v in row.items() if k not in _NEW_SUB_COLS}
            if len(slim) == len(row):
                raise
            print(f"[web] submissions insert retried without {_NEW_SUB_COLS[0]}.. "
                  f"({first}); run supabase/schema.sql to add them", file=sys.stderr)
            return _sb.table("submissions").insert(slim).execute()

    try:
        res = await asyncio.wait_for(asyncio.to_thread(_write), timeout=15)
        _bust_cache()  # aggregates changed: drop cached stats/leaderboard
        data = getattr(res, "data", None) or []
        if data:
            return data[0].get("id") or target_id
        return target_id
    except Exception as e:
        print(f"[web] supabase write failed: {e}", file=sys.stderr)
        return None


# ---- feedback policy: which test data may be shown to whom ----
# Public samples (config.json `samples`) are the only test data a normal user
# ever sees. Hidden test input/expected never leave the server: results are
# redacted BEFORE they are returned and BEFORE they are stored, so a history row
# can never leak them either.
REVEAL_ALL = "all"          # admin: full detail
REVEAL_SAMPLES = "samples"  # default for everyone: samples only
REVEAL_NONE = "none"        # live contest with show_samples = false


def _redact_results(results: List[dict], reveal: str) -> List[dict]:
    """Strip test data from per-test results the caller is not allowed to see."""
    out: List[dict] = []
    for r in results:
        item = dict(r)
        public = bool(item.pop("public", False))
        if reveal == REVEAL_ALL or (public and reveal != REVEAL_NONE):
            out.append(item)
            continue
        for k in ("diff", "input", "expected", "actual"):
            item.pop(k, None)
        item["hidden"] = True
        out.append(item)
    return out


def _iso_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


# ---- per-user fair-use quota (sliding window, in memory) ----
_quota_hits: Dict[str, collections.deque] = {}


def _quota_check(kind: str, key: str, quota: tuple) -> None:
    limit, window = quota
    if limit <= 0 or not key:
        return  # disabled
    now = time.monotonic()
    key = f"{kind}:{key}"
    dq = _quota_hits.get(key)
    if dq is None:
        dq = _quota_hits[key] = collections.deque()
        if len(_quota_hits) > 20000:  # bound memory on a public host
            _quota_hits.clear()
            dq = _quota_hits[key] = collections.deque()
    while dq and now - dq[0] > window:
        dq.popleft()
    if len(dq) >= limit:
        retry = max(1, int(window - (now - dq[0])) + 1)
        raise HTTPException(
            status_code=429,
            detail=f"quota exceeded ({limit} per {window}s) — retry in {retry}s",
            headers={"Retry-After": str(retry)})
    dq.append(now)


# ---- judge job queue (B9) ----
# Every submission/rejudge becomes a job: the HTTP handler only enqueues, a
# worker thread-pool runs it, and the client polls /api/jobs/{id}. With Supabase
# the jobs table is the durable queue (restart-safe); without it the queue is
# in-memory and the API still behaves the same.
_jobs: Dict[str, dict] = {}
# The queue belongs to one event loop at a time. It is created on first use
# inside the running loop (asyncio.Queue binds to a loop on Python 3.9), and if
# we are later called from a different loop the pending job ids are carried over
# into a fresh queue instead of being stranded (bites the test suite, where each
# TestClient runs its own loop, and uvicorn's reloader).
_job_queue: Optional["asyncio.Queue[str]"] = None
_job_loop: Optional[object] = None
_active_jobs: Dict[str, set] = {}       # user_email -> {job ids} queued/running


def _queue() -> "asyncio.Queue[str]":
    """The job queue, (re)bound to the running loop. Safe to call from a worker
    thread (sync endpoints): with no running loop it returns the existing queue
    instead of raising."""
    global _job_queue, _job_loop
    try:
        loop: Optional[object] = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if _job_queue is None:
        _job_queue = asyncio.Queue()
        _job_loop = loop
        return _job_queue
    if loop is not None and _job_loop is not loop:
        old = _job_queue
        _job_queue = asyncio.Queue()
        _job_loop = loop
        while not old.empty():
            try:
                _job_queue.put_nowait(old.get_nowait())
            except Exception:
                break
    return _job_queue


def _queue_depth() -> int:
    """Queued job count without needing an event loop (sync endpoints)."""
    q = _job_queue
    return q.qsize() if q is not None else 0


# Columns added by the 2026-10 migration; if the migration was not run yet, the
# insert is retried without them instead of losing the submission.
_NEW_SUB_COLS = ("tests_hash", "grader_version", "kind", "contest_id", "job_id")


def _prune_jobs() -> None:
    cut = time.monotonic() - JOB_TTL_S
    stale = [k for k, j in _jobs.items()
             if j.get("created_monotonic", 0) < cut and j.get("status") in ("done", "error")]
    for k in stale:
        _jobs.pop(k, None)


def _remember_job(row: dict) -> dict:
    job = _jobs.get(row["id"]) or {}
    job.update(row)
    job.setdefault("created_monotonic", time.monotonic())
    _jobs[row["id"]] = job
    if len(_jobs) > 5000:
        _prune_jobs()
    return job


async def _load_job(jid: str) -> Optional[dict]:
    if _sb is None:
        return None
    try:
        res = await asyncio.to_thread(
            lambda: _sb.table("judge_jobs").select("*").eq("id", jid).limit(1).execute())
    except Exception as e:
        print(f"[web] job lookup failed: {e}", file=sys.stderr)
        return None
    rows = res.data or []
    if not rows:
        return None
    row = dict(rows[0])
    if row.get("status") == "done" and isinstance(row.get("result"), dict):
        job = _remember_job(row)
        job["result"] = row["result"]
        return job
    return _remember_job(row)


async def _update_job_db(jid: str, patch: dict) -> None:
    if _sb is None:
        return
    try:
        await asyncio.to_thread(
            lambda: _sb.table("judge_jobs").update(patch).eq("id", jid).execute())
    except Exception as e:
        print(f"[web] judge_jobs update failed: {e}", file=sys.stderr)


async def _create_job(row: dict, track_active: bool = True) -> dict:
    """Insert the job (DB first for durability), then hand it to a worker."""
    jid = str(uuid.uuid4())
    row = {**row, "id": jid, "status": "queued", "result": None, "error": ""}
    if _sb is not None:
        try:
            await asyncio.to_thread(lambda: _sb.table("judge_jobs").insert(row).execute())
        except Exception as e:
            # No judge_jobs table (migration not run) — degrade to memory-only
            # queueing instead of refusing the submission.
            print(f"[web] judge_jobs insert failed ({e}); queueing in memory", file=sys.stderr)
    job = _remember_job(row)
    if track_active and row.get("user_email"):
        _active_jobs.setdefault(row["user_email"], set()).add(jid)
    await _queue().put(jid)
    return job


async def _recover_jobs() -> None:
    """On boot: requeue jobs orphaned by a crash, and remember queued ones."""
    if _sb is None:
        return
    await asyncio.to_thread(
        lambda: _sb.table("judge_jobs").update({"status": "queued"}).eq(
            "status", "running").execute())
    res = await asyncio.to_thread(
        lambda: _sb.table("judge_jobs").select("*").eq("status", "queued")
        .order("created_at").limit(REJUDGE_MAX).execute())
    rows = res.data or []
    dropped = 0
    for row in rows:
        try:
            created = dt.datetime.fromisoformat(str(row.get("created_at")).replace("Z", "+00:00"))
            age = (dt.datetime.now(dt.timezone.utc) - created).total_seconds()
        except Exception:
            age = 0
        if age > JOB_MAX_AGE_S:
            dropped += 1
            await _update_job_db(row["id"], {"status": "error", "error": "stale job dropped",
                                             "finished_at": _iso_now()})
            continue
        _remember_job(row)
        if row.get("user_email"):
            _active_jobs.setdefault(row["user_email"], set()).add(row["id"])
        await _queue().put(row["id"])
    if rows:
        print(f"[web] recovered {len(rows) - dropped} queued job(s), dropped {dropped} stale",
              file=sys.stderr)


async def _finish_job(jid: str, *, result: Optional[dict] = None, stored: Optional[dict] = None,
                      error: str = "") -> None:
    job = _jobs.get(jid) or {"id": jid}
    job["status"] = "error" if error else "done"
    job["error"] = error
    if result is not None:
        job["result"] = result
    job["finished_at"] = _iso_now()
    _jobs[jid] = job
    email = job.get("user_email") or ""
    if email in _active_jobs:
        _active_jobs[email].discard(jid)
        if not _active_jobs[email]:
            _active_jobs.pop(email, None)
    await _update_job_db(jid, {"status": job["status"], "error": error,
                               "finished_at": job["finished_at"],
                               "result": stored if stored is not None else result})


async def _judge_worker(idx: int) -> None:
    while True:
        jid = await _queue().get()
        try:
            job = _jobs.get(jid) or await _load_job(jid)
            if job and job.get("status") != "done":
                await _run_job(job)
        except asyncio.CancelledError:
            raise
        except Exception:
            traceback.print_exc()
            await _finish_job(jid, error="worker crashed")
        finally:
            _queue().task_done()


async def _run_job(job: dict) -> None:
    jid = job["id"]
    prob = PROBLEMS.get(job.get("problem", ""))
    if prob is None:
        await _finish_job(jid, error=f"unknown problem: {job.get('problem')}")
        return
    ext = str(LANGS.get(job.get("language", ""), {}).get("ext") or ".py")
    job["status"] = "running"
    job["started_at"] = _iso_now()
    _jobs[jid] = job
    await _update_job_db(jid, {"status": "running", "started_at": job["started_at"]})
    reveal = job.get("reveal") or REVEAL_SAMPLES
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(run_submission, prob, ext, job.get("source", ""), reveal),
            timeout=OVERALL_TIMEOUT)
    except asyncio.TimeoutError:
        await _finish_job(jid, error="judging timed out (server overloaded?)")
        return
    except Exception as e:
        traceback.print_exc()
        await _finish_job(jid, error=f"internal judging error: {e}")
        return
    if "error" in result:
        await _finish_job(jid, error=str(result["error"]))
        return
    stored = dict(result)
    sid = None
    if _sb is not None:
        row = _submission_row(job, result)
        sid = await _store_submission(row, target_id=job.get("target_id"))
    result["id"] = sid
    result["job_id"] = jid
    result["name"] = job.get("name", "")
    stored["id"] = sid
    await _finish_job(jid, result=result, stored=stored)


def _submission_row(job: dict, result: dict) -> dict:
    """DB row for one judged submission. Hidden test data is already stripped
    from `result` by run_submission (stored at REVEAL_SAMPLES level)."""
    prob = PROBLEMS.get(job.get("problem", ""))
    return {
        "problem": job.get("problem", ""), "language": job.get("language", ""),
        "filename": job.get("filename"), "name": job.get("name", ""),
        "user_email": job.get("user_email", ""),
        "verdict": result.get("verdict", ""), "accepted": result.get("accepted", False),
        "passed": result.get("passed", 0), "total": result.get("total", 0),
        "score": result.get("score", 0), "counts": result.get("counts", {}),
        "results": result.get("results", []),
        "code": (job.get("source") or "")[:200000],
        "detail": (result.get("compile_error", "") or "")[:4000],
        "tests_hash": grader.tests_hash(prob) if prob else "",
        "grader_version": grader.GRADER_VERSION,
        "kind": job.get("kind", "submit"),
        "contest_id": job.get("contest_id"),
        "job_id": job.get("id"),
    }


# ---- contest policy (B7) ----
def _contest_window(contest: dict) -> str:
    """'upcoming' | 'running' | 'ended' (UTC now vs the contest window)."""
    now = dt.datetime.now(dt.timezone.utc)
    try:
        start = dt.datetime.fromisoformat(str(contest.get("starts_at")).replace("Z", "+00:00"))
        end = dt.datetime.fromisoformat(str(contest.get("ends_at")).replace("Z", "+00:00"))
    except Exception:
        return "ended"
    if now < start:
        return "upcoming"
    if now > end:
        return "ended"
    return "running"


def _contest_or_404(cid: str) -> dict:
    if _sb is None:
        raise HTTPException(status_code=404, detail="contests not configured")
    try:
        res = _sb.table("contests").select("*").eq("id", cid).limit(1).execute()
    except Exception as e:
        raise _db_err(e)
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="unknown contest")
    return dict(rows[0])


def _reveal_for(contest: Optional[dict], email: str) -> str:
    if _is_admin(email):
        return REVEAL_ALL
    if contest and _contest_window(contest) == "running" and contest.get("show_samples") is False:
        return REVEAL_NONE
    return REVEAL_SAMPLES


# ---- Google login (OAuth 2.0 code flow, session cookie) ----
# Env: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET (from Google Auth Platform),
#   GOOGLE_REDIRECT_URI (must match the Authorised redirect URI exactly),
#   FRONTEND_URL (where to send the user after login),
#   SESSION_SECRET (random string; sessions reset on restart if unset),
#   SESSION_SAMESITE (lax: same-origin proxy prod and local http),
#   SESSION_SECURE (true in prod, false for local http).
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    "https://gradernew.pages.dev/api/auth/callback").strip()
FRONTEND_URL = os.environ.get(
    "FRONTEND_URL", "https://gradernew.pages.dev").rstrip("/")

ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get(
    "ADMIN_EMAILS", "sphetpitak@gmail.com").split(",") if e.strip()}


def _is_admin(email: str) -> bool:
    return bool(email) and email.lower() in ADMIN_EMAILS


REPORT_KINDS = ("statement", "tests", "other")
REPORT_STATUS = ("open", "closed")

_session_secret = os.environ.get("SESSION_SECRET", "").strip()
if not _session_secret:
    _session_secret = secrets.token_hex(32)
    print("[web] WARNING: SESSION_SECRET not set, sessions die on restart", file=sys.stderr)
_login_signer = URLSafeTimedSerializer(_session_secret, salt="login-once")
app.add_middleware(
    SessionMiddleware,
    secret_key=_session_secret,
    session_cookie="ng_session",
    max_age=30 * 24 * 3600,
    same_site=os.environ.get("SESSION_SAMESITE", "lax"),
    https_only=os.environ.get("SESSION_SECURE", "true").lower() != "false",
)


def _google_userinfo(code: str) -> dict:
    """Exchange code for tokens, return verified Google profile (blocking)."""
    token_body = urlencode({
        "client_id": GOOGLE_CLIENT_ID, "client_secret": GOOGLE_CLIENT_SECRET,
        "code": code, "grant_type": "authorization_code",
        "redirect_uri": GOOGLE_REDIRECT_URI,
    }).encode()
    req = URLRequest("https://oauth2.googleapis.com/token", data=token_body,
                     headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urlopen(req, timeout=15) as r:
        tok = json.load(r)
    access = tok.get("access_token")
    if not access:
        raise RuntimeError(f"token exchange failed: {str(tok)[:200]}")
    req2 = URLRequest("https://www.googleapis.com/oauth2/v3/userinfo",
                      headers={"Authorization": f"Bearer {access}"})
    with urlopen(req2, timeout=15) as r2:
        info = json.load(r2)
    if not info.get("email"):
        raise RuntimeError("google did not return an email")
    return info


@app.get("/api/auth/login")
def auth_login(request: Request, next: str = "#/"):
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(status_code=500, detail="google oauth not configured")
    if not next.startswith("#/"):
        next = "#/"
    state = secrets.token_urlsafe(16)
    request.session["oauth_state"] = state
    request.session["oauth_next"] = next
    q = urlencode({
        "client_id": GOOGLE_CLIENT_ID, "redirect_uri": GOOGLE_REDIRECT_URI,
        "response_type": "code", "scope": "openid email profile",
        "state": state, "prompt": "select_account",
    })
    return RedirectResponse("https://accounts.google.com/o/oauth2/v2/auth?" + q,
                            status_code=307)


@app.get("/api/auth/callback")
async def auth_callback(request: Request, code: str = "", state: str = "", error: str = ""):
    if error or not code or not state or state != request.session.get("oauth_state"):
        return RedirectResponse(FRONTEND_URL + "/#/?login=failed", status_code=307)
    request.session.pop("oauth_state", None)
    try:
        info = await asyncio.to_thread(_google_userinfo, code)
    except Exception as e:
        print(f"[web] oauth exchange failed: {e}", file=sys.stderr)
        return RedirectResponse(FRONTEND_URL + "/#/?login=failed", status_code=307)
    request.session["user"] = {
        "email": info["email"],
        "name": info.get("name") or info["email"],
        "picture": info.get("picture", ""),
    }
    next_url = request.session.pop("oauth_next", "#/")
    if not isinstance(next_url, str) or not next_url.startswith("#/"):
        next_url = "#/"
    # Hand the session to the frontend origin via one-time token, so the
    # session cookie is set first-party (works even when browsers block
    # third-party cookies). /api/auth/finish is proxied by the frontend host.
    token = _login_signer.dumps({"user": request.session["user"]})
    request.session.clear()
    return RedirectResponse(
        FRONTEND_URL + "/api/auth/finish?" + urlencode({"token": token, "next": next_url}),
        status_code=307)


@app.get("/api/auth/finish")
def auth_finish(request: Request, token: str = "", next: str = "#/"):
    try:
        data = _login_signer.loads(token, max_age=300)
        user = data.get("user") or {}
        if not user.get("email"):
            raise ValueError("no email")
    except Exception:
        return RedirectResponse(FRONTEND_URL + "/#/?login=failed", status_code=307)
    if not next.startswith("#/"):
        next = "#/"
    request.session["user"] = {
        "email": user["email"],
        "name": user.get("name") or user["email"],
        "picture": user.get("picture", ""),
    }
    return RedirectResponse(FRONTEND_URL + "/#/" + next.lstrip("#/"), status_code=307)


@app.get("/api/auth/me")
def auth_me(request: Request) -> dict:
    user = request.session.get("user") or None
    email = (user or {}).get("email", "")
    # Bundle profile in the same round trip (saves a sequential request).
    profile = {"display_name": "", "default_language": ""}
    if user and _sb is not None:
        try:
            res = _sb.table("profiles").select(
                "display_name,default_language").eq("user_email", email).limit(1).execute()
            rows = res.data or []
            if rows:
                profile["display_name"] = rows[0].get("display_name", "") or ""
                profile["default_language"] = rows[0].get("default_language", "") or ""
        except Exception:
            pass
    return {"user": user, "is_admin": _is_admin(email), "profile": profile,
            "profile_configured": _sb is not None}


@app.post("/api/auth/logout")
def auth_logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


# ---- password login (no Google needed) ----
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PW_MIN, PW_MAX = 8, 128
# Two buckets, because the proxy chain hides the real client IP: everything that
# comes through the frontend host arrives with the same source address (Cloudflare
# rewrites it), so an IP-only limit would be SHARED BY EVERY USER on the site —
# 20 logins and the whole class sees "too many attempts". Brute force is therefore
# limited per account (the thing being protected), and the IP bucket stays loose
# as a flood guard for direct callers.
LOGIN_WINDOW_S = 300          # per-IP flood guard window
LOGIN_MAX_TRIES = 200         # per IP per window
ACCOUNT_WINDOW_S = 900        # per-account window
ACCOUNT_MAX_TRIES = 8         # wrong credentials per account per window
_login_tries: Dict[str, list] = {}
_account_tries: Dict[str, list] = {}


def _client_ip(request: Request) -> str:
    # Trust order: Cloudflare's overwritten header first, else the LAST
    # X-Forwarded-For entry (trusted proxies append the real client IP at the
    # end; attacker-supplied values are prepended and must be ignored), else
    # the direct peer. Never use the FIRST XFF entry: it is spoofable and
    # would let attackers bypass the login rate limit by rotating it.
    cf = request.headers.get("cf-connecting-ip", "").strip()
    if cf:
        return cf[:64]
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[-1].strip()[:64]
    return ((request.client.host if request.client else "?") or "?")[:64]


def _recent(store: Dict[str, list], key: str, window: int) -> list:
    now = time.monotonic()
    hits = [t for t in store.get(key, []) if now - t < window]
    store[key] = hits
    return hits


def _check_rate_limit(request: Request, email: str = "") -> None:
    ip = _client_ip(request)
    if len(_recent(_login_tries, ip, LOGIN_WINDOW_S)) >= LOGIN_MAX_TRIES:
        raise HTTPException(status_code=429,
                            detail="too many attempts from this network, try later",
                            headers={"Retry-After": "60"})
    _login_tries[ip].append(time.monotonic())
    if len(_login_tries) > 10000:
        _login_tries.clear()
    email = (email or "").strip().lower()
    if not email:
        return
    hits = _recent(_account_tries, email, ACCOUNT_WINDOW_S)
    if len(hits) >= ACCOUNT_MAX_TRIES:
        retry = max(1, int(ACCOUNT_WINDOW_S - (time.monotonic() - hits[0])) + 1)
        raise HTTPException(
            status_code=429,
            detail="too many attempts for this account, please wait a few minutes",
            headers={"Retry-After": str(retry)})
    hits.append(time.monotonic())
    if len(_account_tries) > 10000:
        _account_tries.clear()


def _clear_account_attempts(email: str) -> None:
    """A correct password resets the account's counter (typos are not attacks)."""
    _account_tries.pop((email or "").strip().lower(), None)


PBKDF2_ITERS = 210_000


def _hash_password(pw: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt, PBKDF2_ITERS)
    return f"pbkdf2${PBKDF2_ITERS}${salt.hex()}${dk.hex()}"


def _verify_password(pw: str, stored: str) -> bool:
    try:
        _, iters, salt_hex, dk_hex = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", pw.encode(),
                                 bytes.fromhex(salt_hex), int(iters))
        return hmac.compare_digest(dk.hex(), dk_hex)
    except Exception:
        return False


def _require_users_table() -> None:
    if _sb is None:
        raise HTTPException(status_code=404, detail="accounts not configured")


@app.post("/api/auth/register")
async def auth_register(request: Request) -> dict:
    _require_users_table()
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))
    name = str(body.get("name", "")).strip()[:50] or email.split("@")[0]
    _check_rate_limit(request, email)
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="bad email")
    if not (PW_MIN <= len(password) <= PW_MAX):
        raise HTTPException(status_code=400, detail="password must be 8-128 characters")
    try:
        exists = _sb.table("users").select("email").eq("email", email).limit(1).execute()
    except Exception as e:
        raise _db_err(e)
    if exists.data:
        raise HTTPException(status_code=409, detail="email already registered")
    pw_hash = await asyncio.to_thread(_hash_password, password)
    try:
        _sb.table("users").insert(
            {"email": email, "name": name, "password_hash": pw_hash}).execute()
    except Exception as e:
        raise _db_err(e)
    request.session["user"] = {"email": email, "name": name, "picture": "",
                               "provider": "password"}
    return {"ok": True, "user": request.session["user"]}


@app.post("/api/auth/password")
async def auth_password(request: Request) -> dict:
    _require_users_table()
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))
    _check_rate_limit(request, email)
    try:
        res = _sb.table("users").select("email,name,password_hash").eq(
            "email", email).limit(1).execute()
    except Exception as e:
        raise _db_err(e)
    rows = res.data or []
    user = rows[0] if rows else None
    ok = await asyncio.to_thread(_verify_password, password,
                                 (user or {}).get("password_hash", ""))
    if not user or not ok:
        raise HTTPException(status_code=401, detail="wrong email or password")
    _clear_account_attempts(email)
    request.session["user"] = {"email": user["email"],
                               "name": user.get("name") or user["email"],
                               "picture": "", "provider": "password"}
    return {"ok": True, "user": request.session["user"]}


def _profile_display_name(email: str, fallback: str) -> str:
    """Display name from profiles table, else Google name (blocking)."""
    if _sb is not None and email:
        try:
            res = _sb.table("profiles").select("display_name").eq(
                "user_email", email).limit(1).execute()
            rows = res.data or []
            if rows and (rows[0].get("display_name") or "").strip():
                return rows[0]["display_name"].strip()[:50]
        except Exception as e:
            print(f"[web] profile lookup failed: {e}", file=sys.stderr)
    return (fallback or "")[:50]


@app.get("/api/profile")
def get_profile(request: Request) -> dict:
    user = request.session.get("user") or {}
    if not user.get("email"):
        raise HTTPException(status_code=401, detail="login required")
    base = {"email": user["email"], "name": user.get("name", ""),
            "display_name": "", "default_language": ""}
    if _sb is None:
        return {"configured": False, "profile": base}
    try:
        res = _sb.table("profiles").select("*").eq(
            "user_email", user["email"]).limit(1).execute()
        rows = res.data or []
        if rows:
            base["display_name"] = rows[0].get("display_name", "") or ""
            base["default_language"] = rows[0].get("default_language", "") or ""
        return {"configured": True, "profile": base}
    except Exception as e:
        raise _db_err(e)


@app.put("/api/profile")
async def update_profile(request: Request) -> dict:
    user = request.session.get("user") or {}
    if not user.get("email"):
        raise HTTPException(status_code=401, detail="login required")
    if _sb is None:
        raise HTTPException(status_code=404, detail="profile not configured")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    display_name = str(body.get("display_name", "")).strip()[:50]
    default_language = str(body.get("default_language", "")).strip()
    if default_language and default_language not in LANGS:
        raise HTTPException(status_code=400, detail="bad default_language")
    row = {"user_email": user["email"], "display_name": display_name,
           "default_language": default_language}
    try:
        _sb.table("profiles").upsert(row, on_conflict="user_email").execute()
    except Exception as e:
        raise _db_err(e)
    return {"ok": True, "profile": {"email": user["email"], **row}}

# Preload problems at startup (fail fast on broken tests, skip with warning).
PROBLEMS: Dict[str, grader.Problem] = {}
if grader.PROBLEMS_DIR.is_dir():
    for _pdir in sorted(grader.PROBLEMS_DIR.iterdir()):
        if not _pdir.is_dir():
            continue
        try:
            _p = grader.load_problem(_pdir.name)
            PROBLEMS[_p.pid] = _p
        except SystemExit as e:
            print(f"[web] skip problem {_pdir.name}: {e}", file=sys.stderr)


def _problem_or_404(pid: str) -> grader.Problem:
    p = PROBLEMS.get(pid)
    if p is None:
        raise HTTPException(status_code=404, detail=f"unknown problem: {pid}")
    return p


# ---- problem visibility (contest-only sets) ----
# A problem can be kept out of the public Task list in two ways:
#   * config.json -> "hidden": true                (always private to contests/admin)
#   * listed in a contest with hide_from_tasks      (set from the admin form)
# Hidden problems stay reachable through their contest page (that is how students
# open them), through the admin panel, and are gated everywhere else.
_contest_pid_cache: Dict[str, object] = {"at": 0.0, "all": set(), "hide": set()}


def _contest_problem_sets() -> tuple:
    """(pids listed in any contest, pids a contest hides from Tasks)."""
    now = time.monotonic()
    if _contest_pid_cache["at"] and now - float(_contest_pid_cache["at"]) < 20:
        return _contest_pid_cache["all"], _contest_pid_cache["hide"]
    all_pids: set = set()
    hidden: set = set()
    if _sb is not None:
        try:
            for row in _contest_rows():
                pids = {str(x) for x in (row.get("problems") or [])}
                all_pids |= pids
                if row.get("hide_from_tasks", True):
                    hidden |= pids
        except Exception as e:
            print(f"[web] contest problem lookup failed: {e}", file=sys.stderr)
    _contest_pid_cache.update({"at": now, "all": all_pids, "hide": hidden})
    return all_pids, hidden


def _hidden_pids() -> set:
    listed, hidden_by_contest = _contest_problem_sets()
    return hidden_by_contest | {pid for pid, p in PROBLEMS.items() if p.hidden}


def _visible_to(pid: str, email: str) -> bool:
    """Public Task entry, or reachable because the problem belongs to a contest."""
    if pid not in PROBLEMS:
        return False
    if _is_admin(email):
        return True
    if pid not in _hidden_pids():
        return True
    listed, _ = _contest_problem_sets()
    return pid in listed


def _visible_problem_or_404(pid: str, email: str) -> grader.Problem:
    p = _problem_or_404(pid)
    if not _visible_to(pid, email):
        raise HTTPException(status_code=404, detail=f"unknown problem: {pid}")
    return p


def _host_limits() -> dict:
    return {"cpu_quota": CPU_QUOTA, "host_memory_mb": RAM_MB,
            "judge_workers": JUDGE_WORKERS, "judge_jobs": JUDGE_JOBS,
            "memory_cap_mb": MEMORY_CAP_MB, "queue_max": QUEUE_MAX,
            "overall_timeout_s": OVERALL_TIMEOUT,
            "sample_interval_ms": round(grader.SAMPLE_INTERVAL * 1000, 2),
            "compile_timeout_s": grader.COMPILE_TIMEOUT}


def _effective(prob: Optional[grader.Problem], time_limit: float,
               memory_mb: int) -> tuple[float, int, dict]:
    """Clamp a problem's declared limits to what this host can actually give."""
    eff = min(memory_mb, MEMORY_CAP_MB)
    limits = {
        "time_s": time_limit, "memory_mb": eff, "declared_mb": memory_mb,
        "capped": eff < memory_mb, "host_memory_mb": RAM_MB,
        "host_cpu": CPU_QUOTA, "problem": prob.pid if prob else "",
    }
    return time_limit, eff, limits


def run_submission(prob: grader.Problem, ext: str, source: str,
                   reveal: str = REVEAL_SAMPLES) -> dict:
    """Judge one submission (runs inside a worker thread, never inline in the loop).

    `reveal` decides how much test data the returned payload carries; the result
    that gets persisted is always reduced to REVEAL_SAMPLES by the caller.
    """
    samples = grader.sample_names(prob)
    limits = _effective(prob, prob.time_limit, prob.memory_limit)[2]
    if limits["capped"]:
        # Judge against the host-appropriate ceiling, keep the declared value
        # in the response so nobody wonders why 512 MB became 256 MB.
        capped = replace(prob, memory_limit=limits["memory_mb"])
    else:
        capped = prob
    with tempfile.TemporaryDirectory(prefix="websub_") as tmp:
        workdir = Path(tmp)
        src = workdir / ("solution" + ext)
        src.write_text(source, encoding="utf-8")
        try:  # sandbox runs the child as `nobody`: it must traverse/read these
            os.chmod(workdir, 0o755)
            os.chmod(src, 0o644)
        except OSError:
            pass
        try:
            cmd, _disp, warnings = grader.prepare_command(src, workdir)
        except grader.CompileError as e:
            return {
                "problem": prob.pid, "verdict": "CE", "accepted": False,
                "passed": 0, "total": len(prob.tests), "score": 0,
                "counts": {"CE": len(prob.tests)},
                "build_warnings": "", "compile_error": str(e)[:4000],
                "limits": limits, "memory_capped": limits["capped"],
                "checker": prob.checker, "results": [], "samples": len(samples),
                "tests_hash": grader.tests_hash(prob),
                "grader_version": grader.GRADER_VERSION,
            }
        except SystemExit as e:
            return {"error": str(e)}

        results: List[dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=JUDGE_JOBS) as ex:
            futs = [ex.submit(grader.judge_test, cmd, tc, capped, False, False)
                    for tc in prob.tests]
            for tc, f in zip(prob.tests, futs):
                v, wall, cpu, mem, detail, actual = f.result()
                item = {
                    "test": tc.name, "verdict": v,
                    "wall_s": round(wall, 4), "cpu_s": round(cpu, 4),
                    "peak_mb": round(mem, 2),
                    "public": tc.name in samples,
                }
                if v == "WA":
                    item["diff"] = grader.show_diff(tc.expected, actual)[:DETAIL_HEAD]
                    item["input"] = tc.input[:2000]
                    item["expected"] = tc.expected[:2000]
                    item["actual"] = actual[:2000]
                elif detail:
                    item["detail"] = detail[:DETAIL_HEAD]
                results.append(item)

        passed = sum(1 for r in results if r["verdict"] == "AC")
        total = len(prob.tests)
        counts: Dict[str, int] = {}
        for r in results:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        return {
            "problem": prob.pid, "accepted": passed == total,
            "verdict": "AC" if passed == total else "REJECTED",
            "passed": passed, "total": total,
            "score": (100 * passed // total) if total else 0,
            "counts": counts, "build_warnings": (warnings or "")[:2000],
            "compile_error": "",
            "limits": limits, "memory_capped": limits["capped"],
            "checker": prob.checker,
            "results": _redact_results(results, reveal),
            "samples": len(samples), "hidden_tests": total - len(samples),
            "tests_hash": grader.tests_hash(prob),
            "grader_version": grader.GRADER_VERSION,
        }


def _run_playground(prob: Optional[grader.Problem], ext: str, source: str,
                    stdin_data: str, time_limit: float, memory_mb: int) -> dict:
    """One-shot run with user-supplied stdin. Never touches history."""
    with tempfile.TemporaryDirectory(prefix="webrun_") as tmp:
        workdir = Path(tmp)
        src = workdir / ("solution" + ext)
        src.write_text(source, encoding="utf-8")
        try:
            os.chmod(workdir, 0o755)
            os.chmod(src, 0o644)
        except OSError:
            pass
        started = time.perf_counter()
        try:
            cmd, _disp, warnings = grader.prepare_command(src, workdir)
        except grader.CompileError as e:
            return {"verdict": "CE", "stdout": "", "stderr": str(e)[:4000],
                    "wall_s": round(time.perf_counter() - started, 4),
                    "cpu_s": 0.0, "peak_mb": 0.0, "reason": "compile-error",
                    "build_warnings": "",
                    "limits": _effective(prob, time_limit, memory_mb)[2],
                    "memory_capped": memory_mb > MEMORY_CAP_MB}
        except SystemExit as e:
            return {"error": str(e)}
        _tl, eff_mem, limits = _effective(prob, time_limit, memory_mb)
        res = grader.run_one(cmd, stdin_data, time_limit, eff_mem)
        reason = res.get("reason", "")
        if reason == "timeout":
            verdict = "TLE"
        elif reason == "ole":
            verdict = "OLE"
        elif reason in ("oom", "sigkill"):
            verdict = "MLE"
        elif reason.startswith("signal:") or reason == "spawn-fail":
            verdict = "RE"
        elif res.get("returncode"):
            verdict = "RE"
        else:
            verdict = "OK"
        out = res.get("stdout") or ""
        err = res.get("stderr") or ""
        truncated = len(out.encode("utf-8", "ignore")) > RUN_OUTPUT_MAX
        return {
            "verdict": verdict, "reason": reason,
            "stdout": out[:RUN_OUTPUT_MAX], "stderr": err[:RUN_OUTPUT_MAX],
            "truncated": truncated,
            "wall_s": round(res.get("wall", 0.0), 4), "cpu_s": round(res.get("cpu", 0.0), 4),
            "peak_mb": round(res.get("peak_mb", 0.0), 2),
            "build_warnings": (warnings or "")[:2000],
            "limits": limits,
            "memory_capped": limits["capped"],
        }


@app.get("/api/health")
def health(request: Request) -> dict:
    email = (request.session.get("user") or {}).get("email", "")
    if _is_admin(email):
        ids = sorted(PROBLEMS.keys())
    else:
        hidden = _hidden_pids()
        ids = sorted(pid for pid in PROBLEMS if pid not in hidden)
    return {"ok": True, "problems": ids, "count": len(ids)}


@app.get("/api/languages")
def languages() -> dict:
    return {"languages": [
        {"id": lid, "name": info["name"], "ext": info["ext"]}
        for lid, info in LANGS.items()
    ]}


@app.get("/api/problems")
def list_problems(request: Request) -> dict:
    order = {"easy": 0, "medium": 1, "hard": 2}
    email = (request.session.get("user") or {}).get("email", "")
    admin = _is_admin(email)
    hidden = _hidden_pids()
    listed, contest_hidden = _contest_problem_sets()
    ranked = sorted(PROBLEMS.values(),
                    key=lambda p: (order.get((p.difficulty or "").lower(), 99), p.pid))
    out = []
    for p in ranked:
        is_hidden = p.pid in hidden
        if is_hidden and not admin:
            continue  # contest-only problem: reachable from its contest page, not Tasks
        item = {
            "id": p.pid, "title": p.title, "time_limit": p.time_limit,
            "memory_limit": p.memory_limit, "checker": p.checker,
            "difficulty": p.difficulty, "tags": p.tags,
            "tests": len(p.tests), "samples": len(p.samples),
        }
        if admin:
            item["hidden"] = is_hidden
            item["contest_only"] = p.pid in listed
            item["config_hidden"] = p.hidden
            item["contest_hidden"] = p.pid in contest_hidden
        out.append(item)
    return {"problems": out}


@app.get("/api/problems/{pid}")
def problem_detail(request: Request, pid: str) -> dict:
    email = (request.session.get("user") or {}).get("email", "")
    p = _visible_problem_or_404(pid, email)
    listed, contest_hidden = _contest_problem_sets()
    body = {"id": p.pid, "title": p.title, "time_limit": p.time_limit,
            "memory_limit": p.memory_limit, "checker": p.checker,
            "difficulty": p.difficulty, "tags": p.tags,
            "notice": p.notice,
            "tests": len(p.tests), "statement": p.description,
            "samples": list(p.samples),
            "hidden_tests": len(p.tests) - len(p.samples),
            "tests_hash": grader.tests_hash(p),
            "has_pdf": (grader.PROBLEMS_DIR / p.pid / "statement.pdf").is_file()}
    if _is_admin(email):
        body["hidden"] = p.pid in _hidden_pids()
        body["contest_only"] = p.pid in listed
        body["config_hidden"] = p.hidden
        body["contest_hidden"] = p.pid in contest_hidden
    return body


@app.get("/api/problems/{pid}/sample/{name}")
def problem_sample(request: Request, pid: str, name: str) -> dict:
    """Public sample test data (statement examples) — hidden tests are never served."""
    email = (request.session.get("user") or {}).get("email", "")
    p = _visible_problem_or_404(pid, email)
    if name not in grader.sample_names(p):
        raise HTTPException(status_code=404,
                            detail="not a public sample (hidden tests are not served)")
    for tc in p.tests:
        if tc.name == name:
            return {"problem": p.pid, "test": tc.name,
                    "input": tc.input, "output": tc.expected}
    raise HTTPException(status_code=404, detail="sample not found")


@app.get("/api/problems/{pid}/pdf")
def problem_pdf(request: Request, pid: str):
    email = (request.session.get("user") or {}).get("email", "")
    p = _visible_problem_or_404(pid, email)
    f = grader.PROBLEMS_DIR / p.pid / "statement.pdf"
    if not f.is_file():
        raise HTTPException(status_code=404, detail="no PDF statement for this problem")
    return FileResponse(str(f), media_type="application/pdf", filename=f"{p.pid}.pdf",
                        content_disposition_type="inline")


async def _read_source(language: str, code: str,
                       file: Optional[UploadFile]) -> tuple[str, Optional[str]]:
    """Validate language + code/file input. Returns (source, filename)."""
    if language not in LANGS:
        raise HTTPException(status_code=400,
                            detail=f"unsupported language: {language} (choose python/c/cpp)")
    source: Optional[str] = None
    filename: Optional[str] = None
    if file is not None and file.filename:
        filename = file.filename
        raw = await file.read()
        if len(raw) > MAX_CODE_BYTES:
            raise HTTPException(status_code=413,
                                detail=f"file too large ({len(raw)} bytes, max {MAX_CODE_BYTES})")
        if not raw.strip():
            raise HTTPException(status_code=400, detail="uploaded file is empty")
        try:
            source = raw.decode("utf-8")
        except UnicodeDecodeError:
            raise HTTPException(status_code=400, detail="file is not valid UTF-8 text")
        ext = Path(filename).suffix.lower()
        if EXT2LANG.get(ext) != language:
            raise HTTPException(
                status_code=400,
                detail=f"file extension '{ext or '(none)'}' does not match language '{language}'")
    elif code and code.strip():
        raw = code.encode("utf-8")
        if len(raw) > MAX_CODE_BYTES:
            raise HTTPException(status_code=413,
                                detail=f"code too large ({len(raw)} bytes, max {MAX_CODE_BYTES})")
        source = code
    else:
        raise HTTPException(status_code=400,
                            detail="submit code as text (code field) or attach a file (file field)")
    return source, filename


@app.post("/api/submit", status_code=202)
async def submit(
    request: Request,
    problem: str = Form(...),
    language: str = Form(...),
    code: str = Form(""),
    file: Optional[UploadFile] = File(None),
    name: str = Form(""),
    contest: str = Form(""),
):
    prob = _problem_or_404(problem)
    user = request.session.get("user") or {}
    if not user.get("email"):
        raise HTTPException(status_code=401, detail="login first")
    email = user["email"]
    if not _visible_to(problem, email):
        raise HTTPException(status_code=404, detail=f"unknown problem: {problem}")

    contest_obj: Optional[dict] = None
    if contest:
        contest_obj = _contest_or_404(contest)
        listed = [str(x) for x in (contest_obj.get("problems") or [])]
        if prob.pid not in listed:
            raise HTTPException(status_code=400, detail="problem is not part of this contest")
        if _contest_window(contest_obj) != "running" and not _is_admin(email):
            raise HTTPException(status_code=403, detail="contest is not running")

    _quota_check("submit", email, SUBMIT_QUOTA)
    if _active_jobs.get(email):
        raise HTTPException(status_code=409,
                            detail="you already have a submission judging, please wait")
    if _queue_depth() >= QUEUE_MAX:
        # One worker on a fractional core: letting the queue grow unbounded means
        # everybody waits minutes. Shed load instead.
        raise HTTPException(
            status_code=503,
            detail=f"judge queue is full ({QUEUE_MAX} jobs) — try again in a moment",
            headers={"Retry-After": "30"})

    source, filename = await _read_source(language, code, file)
    display = await asyncio.to_thread(
        _profile_display_name, email, user.get("name") or email)

    job = await _create_job({
        "kind": "submit", "user_email": email, "name": display[:50],
        "problem": prob.pid, "language": language, "filename": filename,
        "contest_id": contest_obj["id"] if contest_obj else None,
        "source": source, "reveal": _reveal_for(contest_obj, email),
        "tests_hash": grader.tests_hash(prob),
        "grader_version": grader.GRADER_VERSION,
    })
    return {
        "job_id": job["id"], "status": "queued", "problem": prob.pid,
        "samples": len(prob.samples),
        "hidden_tests": len(prob.tests) - len(prob.samples),
        "queued_ahead": _queue().qsize(),
    }


@app.get("/api/jobs/{jid}")
async def job_status(request: Request, jid: str) -> dict:
    user = request.session.get("user") or {}
    if not user.get("email"):
        raise HTTPException(status_code=401, detail="login required")
    job = _jobs.get(jid) or await _load_job(jid)
    if job is None:
        raise HTTPException(status_code=404, detail="unknown job")
    if job.get("user_email") != user["email"] and not _is_admin(user["email"]):
        raise HTTPException(status_code=403, detail="not your job")
    status = job.get("status", "queued")
    return {
        "id": jid, "status": status, "problem": job.get("problem", ""),
        "kind": job.get("kind", "submit"), "error": job.get("error", "") or "",
        "queued_ahead": _queue().qsize() if status == "queued" else 0,
        "result": job.get("result") if status == "done" else None,
    }


@app.get("/api/version")
def version(request: Request) -> dict:
    """Which judging semantics + test set a verdict comes from."""
    email = (request.session.get("user") or {}).get("email", "")
    admin = _is_admin(email)
    hidden = _hidden_pids()
    tests = {pid: {"hash": grader.tests_hash(p), "tests": len(p.tests),
                   "samples": list(p.samples)}
             for pid, p in sorted(PROBLEMS.items())
             if admin or pid not in hidden}
    body = {
        "version": grader.GRADER_VERSION,
        "problems": len(tests),
        "languages": sorted(LANGS.keys()),
        "system": _host_limits(),
        "tests": tests,
    }
    if admin:
        body["hidden_problems"] = sorted(hidden)
        body["problems_total"] = len(PROBLEMS)
    return body


@app.post("/api/run")
async def run_custom(
    request: Request,
    language: str = Form(...),
    code: str = Form(""),
    file: Optional[UploadFile] = File(None),
    input: str = Form(""),
    problem: str = Form(""),
    time_limit: float = Form(0.0),
):
    """Playground: run the code once against user-supplied stdin. Not recorded."""
    user = request.session.get("user") or {}
    if not user.get("email"):
        raise HTTPException(status_code=401, detail="login first")
    _quota_check("run", user["email"], RUN_QUOTA)
    prob = None
    if problem:
        prob = _visible_problem_or_404(problem, user["email"])
    source, _filename = await _read_source(language, code, file)
    if len(input.encode("utf-8")) > RUN_INPUT_MAX:
        raise HTTPException(status_code=413,
                            detail=f"input too large (max {RUN_INPUT_MAX} bytes)")
    tl = time_limit if 0 < time_limit <= RUN_TIMEOUT_MAX else (
        min(prob.time_limit, RUN_TIMEOUT_MAX) if prob else min(2.0, RUN_TIMEOUT_MAX))
    mem = prob.memory_limit if prob else 256
    ext = str(LANGS[language]["ext"])
    try:
        result = await asyncio.wait_for(
            asyncio.to_thread(_run_playground, prob, ext, source, input, tl, mem),
            timeout=tl + RUN_BUDGET)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="run timed out")
    except Exception:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="internal run error")
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    return result


@app.get("/api/history")
def history(request: Request, problem: Optional[str] = None, limit: int = 20,
            mine: bool = False) -> dict:
    if _sb is None:
        return {"configured": False, "submissions": []}
    limit = max(1, min(limit, 100))
    u = request.session.get("user") or {}
    email = u.get("email", "")
    try:
        q = _sb.table("submissions").select(
            "id,created_at,problem,language,name,filename,verdict,accepted,passed,total,score,counts"
        ).order("created_at", desc=True).limit(limit)
        if problem:
            q = q.eq("problem", problem)
        if mine:
            if not email:
                raise HTTPException(status_code=401, detail="login required")
            q = q.eq("user_email", email)
        res = q.execute()
    except HTTPException:
        raise
    except Exception as e:
        raise _db_err(e)
    rows = res.data or []
    if not mine and not _is_admin(email):
        # The public feed must not advertise contest-only problems.
        hidden = _hidden_pids()
        rows = [r for r in rows if (r.get("problem") or "") not in hidden]
    return {"configured": True, "submissions": rows}


@app.get("/api/history/{sid}")
def history_detail(request: Request, sid: str) -> dict:
    user = request.session.get("user") or {}
    email = user.get("email") or ""
    if not email:
        raise HTTPException(status_code=401, detail="login required")
    if _sb is None:
        raise HTTPException(status_code=404, detail="history not configured")
    try:
        res = _sb.table("submissions").select("*").eq("id", sid).limit(1).execute()
    except Exception as e:
        raise _db_err(e)
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="submission not found")
    row = dict(rows[0])
    # Your own submissions, or any submission if you are an admin. Nobody else:
    # a row carries the author's source code.
    if row.get("user_email") != email and not _is_admin(email):
        raise HTTPException(status_code=403, detail="not your submission")
    row.pop("user_email", None)  # never expose login emails publicly
    return row


@app.post("/api/report")
async def create_report(request: Request) -> dict:
    user = request.session.get("user") or {}
    if not user.get("email"):
        raise HTTPException(status_code=401, detail="login required")
    if _sb is None:
        raise HTTPException(status_code=404, detail="report not configured")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    problem = str(body.get("problem", "")).strip()
    if problem not in PROBLEMS:
        raise HTTPException(status_code=400, detail="unknown problem")
    kind = str(body.get("kind", "")).strip()
    if kind not in REPORT_KINDS:
        raise HTTPException(status_code=400, detail="bad kind")
    message = str(body.get("message", "")).strip()
    if not (1 <= len(message) <= 1000):
        raise HTTPException(status_code=400, detail="message must be 1-1000 characters")
    name = await asyncio.to_thread(
        _profile_display_name, user.get("email", ""),
        user.get("name") or user.get("email", ""))
    try:
        res = _sb.table("reports").insert({
            "problem": problem, "kind": kind, "message": message,
            "user_email": user["email"], "name": name, "status": "open",
        }).execute()
    except Exception as e:
        raise _db_err(e)
    rows = res.data or []
    return {"ok": True, "id": rows[0]["id"] if rows else None}


@app.get("/api/reports")
def list_reports(request: Request, mine: bool = False, all: bool = False,
                 problem: Optional[str] = None, limit: int = 50) -> dict:
    user = request.session.get("user") or {}
    if not user.get("email"):
        raise HTTPException(status_code=401, detail="login required")
    if _sb is None:
        return {"configured": False, "reports": []}
    limit = max(1, min(limit, 100))
    want_all = bool(all) and _is_admin(user["email"])
    if all and not want_all:
        raise HTTPException(status_code=403, detail="admin only")
    try:
        cols = ("id,created_at,problem,kind,message,status,name" +
                (",user_email" if want_all else ""))
        q = _sb.table("reports").select(cols).order(
            "created_at", desc=True).limit(limit)
        if problem:
            q = q.eq("problem", problem)
        if not want_all:
            q = q.eq("user_email", user["email"])
        res = q.execute()
    except HTTPException:
        raise
    except Exception as e:
        raise _db_err(e)
    return {"configured": True, "reports": res.data or []}


@app.put("/api/reports/{rid}")
async def set_report_status(request: Request, rid: str) -> dict:
    user = request.session.get("user") or {}
    if not _is_admin(user.get("email", "")):
        raise HTTPException(status_code=403, detail="admin only")
    if _sb is None:
        raise HTTPException(status_code=404, detail="report not configured")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    status = str(body.get("status", "")).strip()
    if status not in REPORT_STATUS:
        raise HTTPException(status_code=400, detail="bad status")
    try:
        _sb.table("reports").update({"status": status}).eq("id", rid).execute()
    except Exception as e:
        raise _db_err(e)
    return {"ok": True}


_boot_time = time.monotonic()


@app.get("/api/admin/overview")
def admin_overview(request: Request) -> dict:
    user = request.session.get("user") or {}
    if not _is_admin(user.get("email", "")):
        raise HTTPException(status_code=403, detail="admin only")
    if _sb is None:
        raise HTTPException(status_code=404, detail="supabase not configured")
    try:
        n_users = (_sb.table("users").select("email", count="exact").limit(1)
                   .execute().count) or 0
        subs = _sb.table("submissions").select(
            "id,created_at,problem,name,language,verdict,accepted,score").order(
            "created_at", desc=True).limit(500).execute().data or []
        reps = _sb.table("reports").select("status", count="exact").limit(1).execute()
        rep_open = _sb.table("reports").select("id", count="exact").eq(
            "status", "open").limit(1).execute().count or 0
    except Exception as e:
        raise _db_err(e)
    per_problem: dict = {}
    for r in subs:
        p = per_problem.setdefault(r["problem"],
                                   {"subs": 0, "accepted": 0, "best": 0})
        p["subs"] += 1
        if r.get("accepted"):
            p["accepted"] += 1
        p["best"] = max(p["best"], r.get("score") or 0)
    hidden = sorted(_hidden_pids())
    listed, contest_hidden = _contest_problem_sets()
    return {
        "problems": len(PROBLEMS),
        "problems_public": len(PROBLEMS) - len(hidden),
        "problems_contest_only": [
            {"id": pid, "title": PROBLEMS[pid].title,
             "config_hidden": PROBLEMS[pid].hidden,
             "contest_hidden": pid in contest_hidden,
             "in_contest": pid in listed}
            for pid in hidden if pid in PROBLEMS
        ],
        "users": n_users,
        "submissions": len(subs),
        "accepted": sum(1 for r in subs if r.get("accepted")),
        "reports_open": rep_open,
        "reports_total": (reps.count if reps else 0) or 0,
        "jobs": {
            "queued": sum(1 for j in _jobs.values() if j.get("status") == "queued"),
            "running": sum(1 for j in _jobs.values() if j.get("status") == "running"),
            "queue_depth": _queue_depth(),
            "workers": JUDGE_WORKERS,
        },
        "per_problem": per_problem,
        "recent": [{k: r.get(k) for k in
                    ("id", "created_at", "problem", "name", "language",
                     "verdict", "score")} for r in subs[:10]],
        "system": {"uptime_s": int(time.monotonic() - _boot_time),
                   "problems_loaded": sorted(PROBLEMS.keys())},
    }


@app.get("/api/leaderboard")
def leaderboard(limit: int = 50) -> dict:
    if _sb is None:
        return {"configured": False, "top": []}
    limit = max(1, min(limit, 100))
    return _cached(f"leaderboard:{limit}", CACHE_TTL["leaderboard"],
                   lambda: _build_leaderboard(limit))


def _leaderboard_names(emails: List[str], from_view: Dict[str, str]) -> Dict[str, str]:
    """Resolve a display name per email.

    Priority: Settings display_name > newest submission name (the view carries an
    all-time one; a bounded scan fills gaps for views created before the `name`
    column existed) > account email local part. Never "?" unless we truly have
    nothing (no email), because a board full of "?" looks broken.
    """
    names: Dict[str, str] = {}
    for email, name in (from_view or {}).items():
        if email and (name or "").strip():
            names[email] = name.strip()[:50]
    try:  # newest non-empty submission name per user (bounded, newest first)
        res = _sb.table("submissions").select("user_email,name").order(
            "created_at", desc=True).limit(2000).execute()
        for r in res.data or []:
            u = r.get("user_email") or ""
            n = (r.get("name") or "").strip()
            if u and n and u not in names:
                names[u] = n[:50]
    except Exception as e:
        print(f"[web] leaderboard name scan failed: {e}", file=sys.stderr)
    try:  # Settings display name wins over anything stored on submissions
        for i in range(0, len(emails), 200):
            chunk = emails[i:i + 200]
            if not chunk:
                continue
            pres = _sb.table("profiles").select(
                "user_email,display_name").in_("user_email", chunk).execute()
            for p in pres.data or []:
                dn = (p.get("display_name") or "").strip()
                if dn:
                    names[p["user_email"]] = dn[:50]
    except Exception as e:
        print(f"[web] leaderboard profile lookup failed: {e}", file=sys.stderr)
    for email in emails:
        if not names.get(email) and email:
            names[email] = email.split("@")[0][:50]   # local part only, no domain
    return names


def _build_leaderboard(limit: int) -> dict:
    """All-time best score per user per problem.

    Uses the `leaderboard_scores` view (supabase/schema.sql) so no submission
    ever falls out of the window; falls back to a bounded row scan when the view
    has not been created yet.
    """
    best: Dict[str, Dict[str, int]] = {}
    acc: Dict[str, set] = {}
    view_names: Dict[str, str] = {}
    view_seen: Dict[str, str] = {}
    rows: List[dict] = []
    # The view gained columns over time (name/last_at): try the richest select
    # first so an un-migrated database still works without a redeploy.
    view_error: Optional[Exception] = None
    for cols in ("user_email,problem,best,accepted,name,last_at",
                 "user_email,problem,best,accepted,name",
                 "user_email,problem,best,accepted"):
        try:
            res = _sb.table("leaderboard_scores").select(cols).limit(20000).execute()
            rows = res.data or []
            view_error = None
            break
        except Exception as e:
            view_error = e
    if view_error is not None or (rows and "best" not in rows[0]):
        print(f"[web] leaderboard_scores view unavailable ({view_error}); "
              "falling back to a 2000-row scan — run supabase/schema.sql", file=sys.stderr)
        try:
            res = _sb.table("submissions").select(
                "problem,user_email,name,accepted,score,created_at").order(
                "created_at", desc=True).limit(2000).execute()
        except Exception as e2:
            raise _db_err(e2)
        rows = res.data or []
    for r in rows:
        u = r.get("user_email") or ""
        if not u:
            continue
        p = r.get("problem") or ""
        if "best" in r:                      # view row
            best.setdefault(u, {})[p] = int(r.get("best") or 0)
            if r.get("accepted"):
                acc.setdefault(u, set()).add(p)
            n = (r.get("name") or "").strip()
            at = str(r.get("last_at") or "")
            if n and at >= view_seen.get(u, ""):
                view_seen[u] = at
                view_names[u] = n[:50]
        else:                                # raw submissions row (newest first)
            cur = best.setdefault(u, {})
            cur[p] = max(cur.get(p, 0), r.get("score") or 0)
            if r.get("accepted"):
                acc.setdefault(u, set()).add(p)
            n = (r.get("name") or "").strip()
            if n and not view_names.get(u):
                view_names[u] = n[:50]
    if not best:
        return {"configured": True, "top": []}
    names = _leaderboard_names(list(best.keys()), view_names)
    top = sorted(
        ({"name": names.get(u) or "?", "solved": len(acc.get(u, ())),
          "points": sum(v.values())} for u, v in best.items()),
        key=lambda t: (-t["points"], -t["solved"], t["name"]))
    return {"configured": True, "top": top[:limit]}


@app.get("/api/stats")
def stats() -> dict:
    if _sb is None:
        return {"configured": False, "stats": {}}
    return _cached("stats", CACHE_TTL["stats"], _build_stats)


def _build_stats() -> dict:
    """Per-problem aggregates from the `problem_stats` view (all-time), with a
    bounded fallback scan when the view has not been created yet."""
    try:
        res = _sb.table("problem_stats").select(
            "problem,subs,accepted,best,total_score,solvers").limit(1000).execute()
        rows = res.data or []
    except Exception as e:
        print(f"[web] problem_stats view unavailable ({e}); falling back to a 500-row "
              "scan — run supabase/schema.sql", file=sys.stderr)
        try:
            res = _sb.table("submissions").select(
                "problem,accepted,score,user_email").order(
                "created_at", desc=True).limit(500).execute()
        except Exception as e2:
            raise _db_err(e2)
        agg: dict = {}
        for r in res.data or []:
            p = agg.setdefault(r["problem"], {"subs": 0, "accepted": 0, "best": 0,
                                              "total_score": 0, "solvers": set()})
            p["subs"] += 1
            if r["accepted"]:
                p["accepted"] += 1
                if r.get("user_email"):
                    p["solvers"].add(r["user_email"])
            p["best"] = max(p["best"], r["score"] or 0)
            p["total_score"] += r["score"] or 0
        rows = [{"problem": k, "subs": v["subs"], "accepted": v["accepted"],
                 "best": v["best"], "total_score": v["total_score"],
                 "solvers": len(v["solvers"])} for k, v in agg.items()]
    out = {}
    for r in rows:
        subs = r.get("subs") or 0
        out[r["problem"]] = {
            "subs": subs, "accepted": r.get("accepted") or 0,
            "best": r.get("best") or 0, "solvers": r.get("solvers") or 0,
            "avg": round((r.get("total_score") or 0) / subs, 1) if subs else 0.0,
        }
    return {"configured": True, "stats": out}


# ---- contests (B7) ----
CONTEST_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{1,39}$")


def _norm_ts(value: str, field: str) -> str:
    try:
        parsed = dt.datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    except Exception:
        raise HTTPException(status_code=400, detail=f"{field} must be ISO-8601 (e.g. 2026-11-01T09:00:00Z)")
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).isoformat()


def _contest_public(row: dict) -> dict:
    return {
        "id": row.get("id", ""), "title": row.get("title", ""),
        "starts_at": row.get("starts_at"), "ends_at": row.get("ends_at"),
        "freeze_minutes": row.get("freeze_minutes") or 0,
        "show_samples": row.get("show_samples", True),
        "hide_from_tasks": row.get("hide_from_tasks", True),
        "status": _contest_window(row),
        "problems": [str(x) for x in (row.get("problems") or [])],
    }


def _contest_rows() -> List[dict]:
    res = _sb.table("contests").select("*").order("starts_at", desc=True).limit(200).execute()
    return res.data or []


@app.get("/api/contests")
def list_contests() -> dict:
    if _sb is None:
        return {"configured": False, "contests": []}
    try:
        return {"configured": True, "contests": [_contest_public(r) for r in _contest_rows()]}
    except Exception as e:
        # Read-only listing: degrade instead of 500 while the contests table is
        # missing (schema migration not run yet).
        print(f"[web] contests listing failed: {e}", file=sys.stderr)
        return {"configured": False, "contests": [],
                "hint": "contests table missing - run supabase/schema.sql"}


@app.post("/api/contests")
async def upsert_contest(request: Request) -> dict:
    user = request.session.get("user") or {}
    if not _is_admin(user.get("email", "")):
        raise HTTPException(status_code=403, detail="admin only")
    if _sb is None:
        raise HTTPException(status_code=404, detail="contests not configured")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    cid = str(body.get("id", "")).strip().lower()
    if not CONTEST_ID_RE.match(cid):
        raise HTTPException(status_code=400,
                            detail="id must be 2-40 chars: a-z 0-9 _ -")
    title = str(body.get("title", "")).strip()[:120] or cid
    starts = _norm_ts(body.get("starts_at", ""), "starts_at")
    ends = _norm_ts(body.get("ends_at", ""), "ends_at")
    if ends <= starts:
        raise HTTPException(status_code=400, detail="ends_at must be after starts_at")
    problems = [str(p) for p in (body.get("problems") or [])]
    unknown = [p for p in problems if p not in PROBLEMS]
    if not problems or unknown:
        raise HTTPException(status_code=400,
                            detail=f"problems must be a non-empty list of problem ids (unknown: {unknown})")
    try:
        freeze = max(0, min(int(body.get("freeze_minutes") or 0), 24 * 60))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="freeze_minutes must be a number")
    row = {
        "id": cid, "title": title, "starts_at": starts, "ends_at": ends,
        "problems": problems, "freeze_minutes": freeze,
        "show_samples": bool(body.get("show_samples", True)),
        "hide_from_tasks": bool(body.get("hide_from_tasks", True)),
        "created_by": user["email"],
    }
    try:
        _sb.table("contests").upsert(row, on_conflict="id").execute()
    except Exception as e:
        if "hide_from_tasks" in str(e):
            raise HTTPException(status_code=400,
                                detail="contests table is missing hide_from_tasks — run supabase/schema.sql")
        raise _db_err(e)
    _contest_pid_cache["at"] = 0.0   # visibility changed
    return {"ok": True, "contest": _contest_public(row)}


@app.delete("/api/contests/{cid}")
def delete_contest(request: Request, cid: str) -> dict:
    user = request.session.get("user") or {}
    if not _is_admin(user.get("email", "")):
        raise HTTPException(status_code=403, detail="admin only")
    if _sb is None:
        raise HTTPException(status_code=404, detail="contests not configured")
    try:
        _sb.table("contests").delete().eq("id", cid).execute()
    except Exception as e:
        raise _db_err(e)
    _contest_pid_cache["at"] = 0.0   # visibility changed
    return {"ok": True}


def _contest_scoreboard(contest: dict, live: bool) -> List[dict]:
    """Best score per problem per user inside one contest.

    Non-admins see a frozen board while the contest runs: submissions newer than
    ends_at - freeze_minutes are hidden until the contest is over.
    """
    if _sb is None:
        return []
    try:
        end = dt.datetime.fromisoformat(str(contest.get("ends_at")).replace("Z", "+00:00"))
    except Exception:
        end = None
    freeze_at = None
    if not live and end and (contest.get("freeze_minutes") or 0) > 0:
        freeze_at = end - dt.timedelta(minutes=int(contest["freeze_minutes"]))
    try:
        res = _sb.table("submissions").select(
            "user_email,name,problem,score,accepted,created_at").eq(
            "contest_id", contest.get("id", "")).order("created_at").limit(5000).execute()
    except Exception as e:
        raise _db_err(e)
    users: Dict[str, dict] = {}
    for r in res.data or []:
        if freeze_at and dt.datetime.now(dt.timezone.utc) < end:
            try:
                created = dt.datetime.fromisoformat(
                    str(r.get("created_at")).replace("Z", "+00:00"))
            except Exception:
                created = None
            if created and created > freeze_at:
                continue
        u = r.get("user_email") or ""
        if not u:
            continue
        agg = users.setdefault(u, {"name": r.get("name") or "?", "best": {}, "solved": set()})
        agg["name"] = r.get("name") or agg["name"]
        p = r.get("problem") or ""
        agg["best"][p] = max(agg["best"].get(p, 0), r.get("score") or 0)
        if r.get("accepted"):
            agg["solved"].add(p)
    board = [{"name": a["name"], "points": sum(a["best"].values()),
              "solved": len(a["solved"]), "per_problem": a["best"]}
             for a in users.values()]
    board.sort(key=lambda t: (-t["points"], -t["solved"], t["name"]))
    return board


@app.get("/api/contests/{cid}")
def contest_detail(request: Request, cid: str) -> dict:
    contest = _contest_or_404(cid)
    user = request.session.get("user") or {}
    email = user.get("email", "")
    listed = [str(x) for x in (contest.get("problems") or [])]
    status = _contest_window(contest)
    live = _is_admin(email) or status != "running"
    problems = []
    for pid in listed:
        p = PROBLEMS.get(pid)
        if p is None:
            continue
        problems.append({"id": p.pid, "title": p.title, "difficulty": p.difficulty,
                         "tags": p.tags, "tests": len(p.tests), "samples": len(p.samples),
                         "time_limit": p.time_limit, "memory_limit": p.memory_limit})
    return {
        **_contest_public(contest), "problem_details": problems,
        "frozen": not live and (contest.get("freeze_minutes") or 0) > 0,
        "scoreboard": _contest_scoreboard(contest, live),
    }


# ---- admin: rejudge (A4) + plagiarism (B8) ----
@app.post("/api/admin/rejudge")
async def admin_rejudge(request: Request) -> dict:
    """Re-run stored submissions against the current tests.

    Body: {"ids": [...]} or {"problem": "count_islands", "limit": 50}.
    """
    user = request.session.get("user") or {}
    if not _is_admin(user.get("email", "")):
        raise HTTPException(status_code=403, detail="admin only")
    if _sb is None:
        raise HTTPException(status_code=404, detail="history not configured")
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    ids = [str(i) for i in (body.get("ids") or [])][:REJUDGE_MAX]
    problem = str(body.get("problem", "")).strip()
    try:
        limit = max(1, min(int(body.get("limit") or 50), REJUDGE_MAX))
    except (TypeError, ValueError):
        limit = 50
    # One worker on a fractional core: a 200-row rejudge would block students for
    # hours. Keep the batch within the queue budget; the admin can call again.
    budget = min(REJUDGE_MAX, QUEUE_MAX)
    if limit > budget:
        limit = budget
    ids = ids[:budget]
    cols = "id,problem,language,filename,name,user_email,code"
    try:
        if ids:
            res = _sb.table("submissions").select(cols).in_("id", ids).execute()
        else:
            if not problem:
                raise HTTPException(status_code=400, detail="give ids[] or problem")
            res = _sb.table("submissions").select(cols).eq("problem", problem).order(
                "created_at", desc=True).limit(limit).execute()
    except HTTPException:
        raise
    except Exception as e:
        raise _db_err(e)
    queued: List[str] = []
    skipped: List[str] = []
    for row in res.data or []:
        pid = row.get("problem", "")
        lang = row.get("language", "")
        code = row.get("code") or ""
        if not code.strip() or pid not in PROBLEMS or lang not in LANGS:
            skipped.append(str(row.get("id")))
            continue
        job = await _create_job({
            "kind": "rejudge", "user_email": row.get("user_email") or "",
            "name": row.get("name") or "", "problem": pid, "language": lang,
            "filename": row.get("filename"), "source": code,
            "target_id": row.get("id"), "reveal": REVEAL_SAMPLES,
            "tests_hash": grader.tests_hash(PROBLEMS[pid]),
            "grader_version": grader.GRADER_VERSION,
        }, track_active=False)
        queued.append(job["id"])
    return {"queued": len(queued), "skipped": len(skipped), "jobs": queued}


def _plagiarism_module():
    """tools/plagiarism.py is a standalone script: load it without packaging."""
    path = ROOT / "tools" / "plagiarism.py"
    if not path.is_file():
        return None
    import importlib.util
    spec = importlib.util.spec_from_file_location("ng_plagiarism", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@app.get("/api/admin/plagiarism")
def admin_plagiarism(request: Request, problem: str = "",
                     threshold: float = 0.6, limit: int = 300) -> dict:
    """Similar-code pairs among the most recent submissions of one problem."""
    user = request.session.get("user") or {}
    if not _is_admin(user.get("email", "")):
        raise HTTPException(status_code=403, detail="admin only")
    if problem not in PROBLEMS:
        raise HTTPException(status_code=400, detail="unknown problem")
    if _sb is None:
        raise HTTPException(status_code=404, detail="history not configured")
    mod = _plagiarism_module()
    if mod is None:
        raise HTTPException(status_code=501, detail="tools/plagiarism.py not available")
    threshold = min(max(float(threshold), 0.05), 1.0)
    limit = max(2, min(int(limit), 600))
    try:
        res = _sb.table("submissions").select(
            "id,name,user_email,language,code,created_at").eq(
            "problem", problem).order("created_at", desc=True).limit(limit).execute()
    except Exception as e:
        raise _db_err(e)
    rows = [{"id": r["id"], "name": r.get("name") or "?", "problem": problem,
             "language": r.get("language") or "", "code": r.get("code") or ""}
            for r in (res.data or []) if (r.get("code") or "").strip()]
    pairs = mod.similar_pairs(rows, threshold=threshold)
    return {"problem": problem, "threshold": threshold, "scanned": len(rows),
            "pairs": pairs[:200]}


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import argparse
    import uvicorn

    ap = argparse.ArgumentParser(description="Brutal grader web server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
