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
import concurrent.futures
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

LANGS: Dict[str, Dict[str, object]] = {
    "python": {"name": "Python 3", "ext": ".py", "accept": [".py"]},
    "c": {"name": "C (C11)", "ext": ".c", "accept": [".c"]},
    "cpp": {"name": "C++ (C++17)", "ext": ".cpp", "accept": [".cpp", ".cc", ".cxx"]},
}
EXT2LANG = {".py": "python", ".c": "c", ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp"}

MAX_CODE_BYTES = 256 * 1024   # 256 KB source cap
JUDGE_JOBS = 4                # parallel test workers per submission
MAX_PARALLEL_SUBMITS = 4      # concurrent submissions cap
OVERALL_TIMEOUT = 90.0        # seconds per submission (thread keeps cleaning up after)
DETAIL_HEAD = 4000            # max chars of detail/diff sent to frontend

app = FastAPI(title="Newbiegrader API", version="1.0.0")
app.add_middleware(GZipMiddleware, minimum_size=500)
submit_sem = asyncio.Semaphore(MAX_PARALLEL_SUBMITS)
_active_submits: set = set()  # user emails with a judging currently running

# Split deployment (frontend on Vercel etc.): allow the static origin, e.g.
#   GRADER_CORS_ORIGINS=https://gradernew.vercel.app
# Empty (default) = same-origin only, no CORS headers.
_cors_origins = [o.strip() for o in
                 os.environ.get("GRADER_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
        allow_credentials=True,  # login session cookie is cross-origin (vercel -> backend)
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


async def _store_submission(row: dict) -> None:
    """Persist one submission; never fails the judging response."""
    if _sb is None:
        return
    try:
        await asyncio.wait_for(
            asyncio.to_thread(lambda: _sb.table("submissions").insert(row).execute()),
            timeout=10,
        )
    except Exception as e:
        print(f"[web] supabase insert failed: {e}", file=sys.stderr)


# ---- Google login (OAuth 2.0 code flow, session cookie) ----
# Env: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET (from Google Auth Platform),
#   GOOGLE_REDIRECT_URI (must match the Authorised redirect URI exactly),
#   FRONTEND_URL (where to send the user after login),
#   SESSION_SECRET (random string; sessions reset on restart if unset),
#   SESSION_SAMESITE (none for cross-origin prod, lax for local http),
#   SESSION_SECURE (true in prod, false for local http).
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "").strip()
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "").strip()
GOOGLE_REDIRECT_URI = os.environ.get(
    "GOOGLE_REDIRECT_URI",
    "https://gradernew-static.vercel.app/api/auth/callback").strip()
FRONTEND_URL = os.environ.get(
    "FRONTEND_URL", "https://gradernew-static.vercel.app").rstrip("/")

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
    same_site=os.environ.get("SESSION_SAMESITE", "none"),
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
    return {"user": user, "is_admin": _is_admin(email)}


@app.post("/api/auth/logout")
def auth_logout(request: Request) -> dict:
    request.session.clear()
    return {"ok": True}


# ---- password login (no Google needed) ----
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PW_MIN, PW_MAX = 8, 128
LOGIN_WINDOW_S = 300
LOGIN_MAX_TRIES = 20
_login_tries: Dict[str, list] = {}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return (request.client.host if request.client else "?") or "?"


def _check_rate_limit(request: Request) -> None:
    now = time.monotonic()
    key = _client_ip(request)
    hits = [t for t in _login_tries.get(key, []) if now - t < LOGIN_WINDOW_S]
    if len(hits) >= LOGIN_MAX_TRIES:
        raise HTTPException(status_code=429, detail="too many attempts, try later")
    hits.append(now)
    _login_tries[key] = hits
    if len(_login_tries) > 10000:
        _login_tries.clear()


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
    _check_rate_limit(request)
    _require_users_table()
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))
    name = str(body.get("name", "")).strip()[:50] or email.split("@")[0]
    if not EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="bad email")
    if not (PW_MIN <= len(password) <= PW_MAX):
        raise HTTPException(status_code=400, detail="password must be 8-128 characters")
    try:
        exists = _sb.table("users").select("email").eq("email", email).limit(1).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"supabase query failed: {e}")
    if exists.data:
        raise HTTPException(status_code=409, detail="email already registered")
    pw_hash = await asyncio.to_thread(_hash_password, password)
    try:
        _sb.table("users").insert(
            {"email": email, "name": name, "password_hash": pw_hash}).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"supabase write failed: {e}")
    request.session["user"] = {"email": email, "name": name, "picture": "",
                               "provider": "password"}
    return {"ok": True, "user": request.session["user"]}


@app.post("/api/auth/password")
async def auth_password(request: Request) -> dict:
    _check_rate_limit(request)
    _require_users_table()
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON")
    email = str(body.get("email", "")).strip().lower()
    password = str(body.get("password", ""))
    try:
        res = _sb.table("users").select("email,name,password_hash").eq(
            "email", email).limit(1).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"supabase query failed: {e}")
    rows = res.data or []
    user = rows[0] if rows else None
    ok = await asyncio.to_thread(_verify_password, password,
                                 (user or {}).get("password_hash", ""))
    if not user or not ok:
        raise HTTPException(status_code=401, detail="wrong email or password")
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
        raise HTTPException(status_code=500, detail=f"supabase query failed: {e}")


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
        raise HTTPException(status_code=500, detail=f"supabase write failed: {e}")
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


def run_submission(prob: grader.Problem, ext: str, source: str) -> dict:
    """Judge one submission synchronously (runs inside a worker thread)."""
    with tempfile.TemporaryDirectory(prefix="websub_") as tmp:
        workdir = Path(tmp)
        src = workdir / ("solution" + ext)
        src.write_text(source, encoding="utf-8")
        try:
            cmd, _disp, warnings = grader.prepare_command(src, workdir)
        except grader.CompileError as e:
            return {
                "problem": prob.pid, "verdict": "CE", "accepted": False,
                "passed": 0, "total": len(prob.tests), "score": 0,
                "counts": {"CE": len(prob.tests)},
                "build_warnings": "", "compile_error": str(e)[:4000],
                "limits": {"time_s": prob.time_limit, "memory_mb": prob.memory_limit},
                "checker": prob.checker, "results": [],
            }
        except SystemExit as e:
            return {"error": str(e)}

        results: List[dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=JUDGE_JOBS) as ex:
            futs = [ex.submit(grader.judge_test, cmd, tc, prob, False, False)
                    for tc in prob.tests]
            for tc, f in zip(prob.tests, futs):
                v, wall, cpu, mem, detail, actual = f.result()
                item = {
                    "test": tc.name, "verdict": v,
                    "wall_s": round(wall, 4), "cpu_s": round(cpu, 4),
                    "peak_mb": round(mem, 2),
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
            "limits": {"time_s": prob.time_limit, "memory_mb": prob.memory_limit},
            "checker": prob.checker, "results": results,
        }


@app.get("/api/health")
def health() -> dict:
    return {"ok": True, "problems": sorted(PROBLEMS.keys())}


@app.get("/api/languages")
def languages() -> dict:
    return {"languages": [
        {"id": lid, "name": info["name"], "ext": info["ext"]}
        for lid, info in LANGS.items()
    ]}


@app.get("/api/problems")
def list_problems() -> dict:
    return {"problems": [
        {"id": p.pid, "title": p.title, "time_limit": p.time_limit,
         "memory_limit": p.memory_limit, "checker": p.checker,
         "difficulty": p.difficulty, "tags": p.tags,
         "tests": len(p.tests)}
        for p in PROBLEMS.values()
    ]}


@app.get("/api/problems/{pid}")
def problem_detail(pid: str) -> dict:
    p = _problem_or_404(pid)
    return {"id": p.pid, "title": p.title, "time_limit": p.time_limit,
            "memory_limit": p.memory_limit, "checker": p.checker,
            "difficulty": p.difficulty, "tags": p.tags,
            "tests": len(p.tests), "statement": p.description,
            "has_pdf": (grader.PROBLEMS_DIR / p.pid / "statement.pdf").is_file()}


@app.get("/api/problems/{pid}/pdf")
def problem_pdf(pid: str):
    p = _problem_or_404(pid)
    f = grader.PROBLEMS_DIR / p.pid / "statement.pdf"
    if not f.is_file():
        raise HTTPException(status_code=404, detail="no PDF statement for this problem")
    return FileResponse(str(f), media_type="application/pdf", filename=f"{p.pid}.pdf")


@app.post("/api/submit")
async def submit(
    request: Request,
    problem: str = Form(...),
    language: str = Form(...),
    code: str = Form(""),
    file: Optional[UploadFile] = File(None),
    name: str = Form(""),
):
    prob = _problem_or_404(problem)
    if language not in LANGS:
        raise HTTPException(status_code=400,
                            detail=f"unsupported language: {language} (choose python/c/cpp)")
    name = (name or "").strip()
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="name too long (max 50 characters)")
    user = request.session.get("user") or {}
    if not user.get("email"):
        raise HTTPException(status_code=401, detail="login with Google first")
    name = await asyncio.to_thread(
        _profile_display_name, user.get("email", ""),
        user.get("name") or user.get("email", ""))

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

    assert source is not None
    ext = str(LANGS[language]["ext"])

    if user["email"] in _active_submits:
        raise HTTPException(status_code=409,
                            detail="you already have a submission judging, please wait")
    _active_submits.add(user["email"])
    try:
        async with submit_sem:
            try:
                result = await asyncio.wait_for(
                    asyncio.to_thread(run_submission, prob, ext, source),
                    timeout=OVERALL_TIMEOUT,
                )
            except asyncio.TimeoutError:
                raise HTTPException(status_code=504, detail="judging timed out (server overloaded?)")
            except Exception:
                traceback.print_exc()
                raise HTTPException(status_code=500, detail="internal judging error")
    finally:
        _active_submits.discard(user["email"])
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    result["filename"] = filename
    result["name"] = name
    await _store_submission({
        "problem": prob.pid, "language": language, "filename": filename,
        "name": name, "user_email": user.get("email", ""),
        "verdict": result.get("verdict", ""), "accepted": result.get("accepted", False),
        "passed": result.get("passed", 0), "total": result.get("total", 0),
        "score": result.get("score", 0), "counts": result.get("counts", {}),
        "results": result.get("results", []), "code": source[:200000],
        "detail": (result.get("compile_error", "") or "")[:4000],
    })
    return result


@app.get("/api/history")
def history(request: Request, problem: Optional[str] = None, limit: int = 20,
            mine: bool = False) -> dict:
    if _sb is None:
        return {"configured": False, "submissions": []}
    limit = max(1, min(limit, 100))
    try:
        q = _sb.table("submissions").select(
            "id,created_at,problem,language,name,filename,verdict,accepted,passed,total,score,counts"
        ).order("created_at", desc=True).limit(limit)
        if problem:
            q = q.eq("problem", problem)
        if mine:
            u = request.session.get("user") or {}
            if not u.get("email"):
                raise HTTPException(status_code=401, detail="login required")
            q = q.eq("user_email", u["email"])
        res = q.execute()
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"supabase query failed: {e}")
    return {"configured": True, "submissions": res.data or []}


@app.get("/api/history/{sid}")
def history_detail(sid: str) -> dict:
    if _sb is None:
        raise HTTPException(status_code=404, detail="history not configured")
    try:
        res = _sb.table("submissions").select("*").eq("id", sid).limit(1).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"supabase query failed: {e}")
    rows = res.data or []
    if not rows:
        raise HTTPException(status_code=404, detail="submission not found")
    row = dict(rows[0])
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
        raise HTTPException(status_code=500, detail=f"supabase write failed: {e}")
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
        raise HTTPException(status_code=500, detail=f"supabase query failed: {e}")
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
        raise HTTPException(status_code=500, detail=f"supabase write failed: {e}")
    return {"ok": True}


@app.get("/api/leaderboard")
def leaderboard(limit: int = 50) -> dict:
    if _sb is None:
        return {"configured": False, "top": []}
    limit = max(1, min(limit, 100))
    try:
        res = _sb.table("submissions").select(
            "problem,user_email,name,accepted,score,created_at").order(
            "created_at", desc=True).limit(2000).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"supabase query failed: {e}")
    users: dict = {}
    for r in res.data or []:
        u = users.setdefault(r["user_email"], {"name": r.get("name") or "?",
                                               "best": {}, "acc": set()})
        u["name"] = r.get("name") or u["name"]  # latest name wins (rows are desc)
        p = r["problem"]
        u["best"][p] = max(u["best"].get(p, 0), r.get("score") or 0)
        if r.get("accepted"):
            u["acc"].add(p)
    if _sb is not None and users:
        # display names from Settings override historical submission names
        try:
            pres = _sb.table("profiles").select(
                "user_email,display_name").in_(
                "user_email", list(users.keys())).execute()
            for p in pres.data or []:
                dn = (p.get("display_name") or "").strip()
                if dn and p["user_email"] in users:
                    users[p["user_email"]]["name"] = dn
        except Exception as e:
            print(f"[web] leaderboard profile lookup failed: {e}", file=sys.stderr)
    top = sorted(
        ({"name": u["name"], "solved": len(u["acc"]),
          "points": sum(u["best"].values())} for u in users.values()),
        key=lambda t: (-t["points"], -t["solved"], t["name"]))
    return {"configured": True, "top": top[:limit]}


@app.get("/api/stats")
def stats() -> dict:
    if _sb is None:
        return {"configured": False, "stats": {}}
    try:
        res = _sb.table("submissions").select(
            "problem,accepted,score").order("created_at", desc=True).limit(500).execute()
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"supabase query failed: {e}")
    agg: dict = {}
    for r in res.data or []:
        p = agg.setdefault(r["problem"], {"subs": 0, "accepted": 0, "best": 0, "total_score": 0})
        p["subs"] += 1
        p["accepted"] += 1 if r["accepted"] else 0
        p["best"] = max(p["best"], r["score"] or 0)
        p["total_score"] += r["score"] or 0
    return {"configured": True, "stats": {
        k: {"subs": v["subs"], "accepted": v["accepted"], "best": v["best"],
            "avg": round(v["total_score"] / v["subs"], 1)}
        for k, v in agg.items()
    }}


app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")


if __name__ == "__main__":
    import argparse
    import uvicorn

    ap = argparse.ArgumentParser(description="Brutal grader web server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    args = ap.parse_args()
    uvicorn.run(app, host=args.host, port=args.port)
