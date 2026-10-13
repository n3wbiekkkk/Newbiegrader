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
import os
import sys
import tempfile
import traceback
from pathlib import Path
from typing import Dict, List, Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

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

app = FastAPI(title="Brutal Grader API", version="1.0.0")
submit_sem = asyncio.Semaphore(MAX_PARALLEL_SUBMITS)

# Split deployment (frontend on Vercel etc.): allow the static origin, e.g.
#   GRADER_CORS_ORIGINS=https://gradernew.vercel.app
# Empty (default) = same-origin only, no CORS headers.
_cors_origins = [o.strip() for o in
                 os.environ.get("GRADER_CORS_ORIGINS", "").split(",") if o.strip()]
if _cors_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
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

# Preload problems at startup (fail fast on broken tests, skip with warning).
PROBLEMS: Dict[str, grader.Problem] = {}
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
         "tests": len(p.tests)}
        for p in PROBLEMS.values()
    ]}


@app.get("/api/problems/{pid}")
def problem_detail(pid: str) -> dict:
    p = _problem_or_404(pid)
    return {"id": p.pid, "title": p.title, "time_limit": p.time_limit,
            "memory_limit": p.memory_limit, "checker": p.checker,
            "tests": len(p.tests), "statement": p.description}


@app.post("/api/submit")
async def submit(
    problem: str = Form(...),
    language: str = Form(...),
    code: str = Form(""),
    file: Optional[UploadFile] = File(None),
):
    prob = _problem_or_404(problem)
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

    assert source is not None
    ext = str(LANGS[language]["ext"])

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
    if "error" in result:
        raise HTTPException(status_code=500, detail=result["error"])
    result["filename"] = filename
    await _store_submission({
        "problem": prob.pid, "language": language, "filename": filename,
        "verdict": result.get("verdict", ""), "accepted": result.get("accepted", False),
        "passed": result.get("passed", 0), "total": result.get("total", 0),
        "score": result.get("score", 0), "counts": result.get("counts", {}),
        "results": result.get("results", []), "code": source[:200000],
        "detail": (result.get("compile_error", "") or "")[:4000],
    })
    return result


@app.get("/api/history")
def history(problem: Optional[str] = None, limit: int = 20) -> dict:
    if _sb is None:
        return {"configured": False, "submissions": []}
    limit = max(1, min(limit, 100))
    try:
        q = _sb.table("submissions").select(
            "id,created_at,problem,language,filename,verdict,accepted,passed,total,score,counts"
        ).order("created_at", desc=True).limit(limit)
        if problem:
            q = q.eq("problem", problem)
        res = q.execute()
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
    return rows[0]


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
