"""Credential-free job execution shared by the API and isolated judge runner.

Only standard-library modules and the canonical grader are imported here. The
API owns admission, authorization and policy selection; the runner receives an
explicit immutable budget and never imports the web app or database client.
"""
from __future__ import annotations

import concurrent.futures
from contextvars import copy_context
from dataclasses import dataclass, replace
from pathlib import Path
import re
import tempfile
import time
from typing import Dict, List, Optional

import grader

DETAIL_HEAD = 4000
RUN_OUTPUT_MAX = 64 * 1024


@dataclass(frozen=True)
class Settings:
    memory_cap_mb: int
    judge_jobs: int
    cpu_quota: float
    ram_mb: int


def _sanitize_compile_error(text: str) -> str:
    """Redact host paths and compiler version banners from toolchain output
    before returning it to clients. Keeps diagnostics useful for students."""
    # 1. Redact absolute host paths (/tmp, /app, /root, /home, /usr, /var, /etc).
    text = re.sub(
        r"(/tmp|/app|/root|/home|/usr|/var|/etc)(?:/\S*)?(?=\s|$)",
        "[path]",
        text,
    )
    # 2. Redact compiler version banners to just "<tool> (compiler)".
    text = re.sub(
        r"(?m)^[ \t]*(gcc|g\+\+|javac|java|node|go|rustc).*$",
        lambda m: m.group(1) + " (compiler)",
        text,
    )
    # 4. Truncate to 4000 chars as a safety net.
    return text[:4000]


REVEAL_ALL = "all"          # admin: full detail
REVEAL_SAMPLES = "samples"  # contest/default legacy feedback: samples only
REVEAL_NONE = "none"        # live contest with show_samples = false
REVEAL_PRACTICE = "practice-failures"  # owner: failed practice cases only


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def _plain_text(text: str) -> str:
    """Drop ANSI colour codes from judge output.

    grader.py colours its CLI diff when stdout is a tty, so `python3 server.py`
    in a terminal produced `\\x1b[90m---·expected` inside the JSON payload and
    the history row: the browser showed the escape sequence instead of the diff.
    The CLI keeps its colours; the web/DB never sees them.
    """
    if "\x1b[" not in text:
        return text
    return _ANSI_RE.sub("", text)


def _redact_results(results: List[dict], reveal: str) -> List[dict]:
    """Strip test data from per-test results the caller is not allowed to see."""
    out: List[dict] = []
    for r in results:
        item = {k: (_plain_text(v) if isinstance(v, str) else v)
                for k, v in r.items()}
        public = bool(item.pop("public", False))
        practice = (reveal == REVEAL_PRACTICE and item.get("practice_feedback") is True
                    and item.get("verdict") in {"WA", "RE", "TLE", "MLE", "OLE"})
        if (not public and not practice) or reveal == REVEAL_NONE:
            # detail is user-controlled (including old persisted stderr).
            # Never attempt to distinguish it by matching its text.
            detail = item.pop("detail", None)
            item.pop("stderr", None)
            item.pop("stdout", None)
            if detail:
                item["detail"] = {
                    "RE": "runtime error", "MLE": "memory limit exceeded",
                    "TLE": "time limit exceeded", "OLE": "output limit exceeded",
                }.get(item.get("verdict"), "execution diagnostic withheld")
        if reveal == REVEAL_ALL or practice or (public and reveal != REVEAL_NONE):
            out.append(item)
            continue
        item.pop("practice_feedback", None)
        for k in ("diff", "input", "expected", "actual"):
            item.pop(k, None)
        item["hidden"] = True
        out.append(item)
    return out


def _effective(prob: Optional[grader.Problem], time_limit: float,
               memory_mb: int, settings: Settings) -> tuple[float, int, dict]:
    """Clamp a problem's declared limits to what this host can actually give."""
    eff = min(memory_mb, settings.memory_cap_mb)
    limits = {
        "time_s": time_limit, "memory_mb": eff, "declared_mb": memory_mb,
        "capped": eff < memory_mb, "host_memory_mb": settings.ram_mb,
        "host_cpu": settings.cpu_quota, "problem": prob.pid if prob else "",
    }
    return time_limit, eff, limits


def run_submission(prob: grader.Problem, ext: str, source: str,
                   reveal: str = REVEAL_SAMPLES, *, settings: Settings) -> dict:
    """Judge one submission (runs inside a worker thread, never inline in the loop).

    `reveal` decides which failures may carry test data. Storage re-applies the
    server-selected policy; contest records never opt into practice feedback.
    """
    if not prob.tests:
        # Fail closed: an empty suite must never become Accepted.
        return {"error": "problem store unavailable (no tests)"}
    samples = grader.sample_names(prob)
    practice = reveal == REVEAL_PRACTICE
    # The isolated runner receives trusted embedded tests but has no populated
    # metadata cache. Record these exact bytes, not a potentially stale API hash.
    executed_tests_hash = grader.tests_hash(prob)
    limits = _effective(prob, prob.time_limit, prob.memory_limit, settings)[2]
    if limits["capped"]:
        # Judge against the host-appropriate ceiling, keep the declared value
        # in the response so nobody wonders why 512 MB became 256 MB.
        capped = replace(prob, memory_limit=limits["memory_mb"])
    else:
        capped = prob
    with grader.job_sandbox.scope(), tempfile.TemporaryDirectory(prefix="websub_") as tmp:
        workdir = Path(tmp)
        src = workdir / ("solution" + ext)
        src.write_text(source, encoding="utf-8")
        try:
            grader.prepare_workspace(workdir, src)
            cmd, _disp, warnings = grader.prepare_command(src, workdir)
        except grader.SandboxUnavailable:
            return {"error": "execution environment unavailable"}
        except grader.CompileError as e:
            return {
                "problem": prob.pid, "verdict": "CE", "accepted": False,
                "passed": 0, "total": len(prob.tests), "score": 0,
                "counts": {"CE": len(prob.tests)},
                "compile_error": _sanitize_compile_error(str(e))[:4000],
                "limits": limits, "memory_capped": limits["capped"],
                "checker": prob.checker, "results": [], "samples": len(samples),
                "tests_hash": executed_tests_hash,
                "grader_version": grader.GRADER_VERSION,
            }
        except SystemExit as e:
            return {"error": _sanitize_compile_error(str(e))}

        results: List[dict] = []
        lang = grader.detect_language(Path("solution" + ext))
        # Public feedback must finish before any hidden input reaches user code:
        # tests in one job share a workspace, even with per-job isolation.
        stages = ([tc for tc in prob.tests if tc.name in samples],
                  [tc for tc in prob.tests if tc.name not in samples])
        if settings.judge_jobs <= 1:
            # Serial path: one test at a time on small hosts. Avoid
            # ThreadPoolExecutor overhead (thread spawn + future per test).
            judged = []
            for tc in (*stages[0], *stages[1]):
                try:
                    judged.append((tc, grader.judge_test(
                        cmd, tc, capped, False, False, lang,
                        diagnostics=(tc.name in samples or practice) and reveal != REVEAL_NONE,
                        reveal_failed=practice)))
                except grader.SandboxUnavailable:
                    # Fail closed: no test was judged, no verdict is recorded.
                    # The worker maps {"error": ...} to a job-level error.
                    return {"error": "execution environment unavailable"}
            for tc, (v, wall, cpu, mem, detail, actual) in judged:
                item = {
                    "test": tc.name, "verdict": v,
                    "wall_s": round(wall, 4), "cpu_s": round(cpu, 4),
                    "peak_mb": round(mem, 2),
                    "public": tc.name in samples,
                }
                if v == "WA" or (v != "AC" and (tc.name in samples or practice) and reveal != REVEAL_NONE):
                    if v == "WA":
                        item["diff"] = grader.show_diff(tc.expected, actual)[:DETAIL_HEAD]
                    item["input"] = tc.input[:2000]
                    item["expected"] = tc.expected[:2000]
                    item["actual"] = actual[:2000]
                if practice and v in {"WA", "RE", "TLE", "MLE", "OLE"}:
                    item["practice_feedback"] = True
                if detail:
                    item["detail"] = detail[:DETAIL_HEAD]
                results.append(item)
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=settings.judge_jobs) as ex:
                for stage in stages:
                    futs = [ex.submit(copy_context().run, grader.judge_test, cmd, tc, capped, False, False, lang,
                                      diagnostics=(tc.name in samples or practice) and reveal != REVEAL_NONE,
                                      reveal_failed=practice)
                            for tc in stage]
                    # result() returns only after the supervisor reaps all
                    # descendants; sample readers cannot survive this barrier.
                    for tc, f in zip(stage, futs):
                        try:
                            v, wall, cpu, mem, detail, actual = f.result()
                        except grader.SandboxUnavailable:
                            return {"error": "execution environment unavailable"}
                        item = {
                            "test": tc.name, "verdict": v,
                            "wall_s": round(wall, 4), "cpu_s": round(cpu, 4),
                            "peak_mb": round(mem, 2),
                            "public": tc.name in samples,
                        }
                        if v == "WA" or (v != "AC" and (tc.name in samples or practice) and reveal != REVEAL_NONE):
                            if v == "WA":
                                item["diff"] = grader.show_diff(tc.expected, actual)[:DETAIL_HEAD]
                            item["input"] = tc.input[:2000]
                            item["expected"] = tc.expected[:2000]
                            item["actual"] = actual[:2000]
                        if practice and v in {"WA", "RE", "TLE", "MLE", "OLE"}:
                            item["practice_feedback"] = True
                        if detail:
                            item["detail"] = detail[:DETAIL_HEAD]
                        results.append(item)

        order = {tc.name: index for index, tc in enumerate(prob.tests)}
        results.sort(key=lambda item: order[item["test"]])
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
            "samples": len(samples),
            "tests_hash": executed_tests_hash,
            "grader_version": grader.GRADER_VERSION,
        }


def _run_playground(prob: Optional[grader.Problem], ext: str, source: str,
                    stdin_data: str, time_limit: float, memory_mb: int, *, settings: Settings) -> dict:
    """One-shot run with user-supplied stdin. Never touches history."""
    with grader.job_sandbox.scope(), tempfile.TemporaryDirectory(prefix="webrun_") as tmp:
        workdir = Path(tmp)
        src = workdir / ("solution" + ext)
        src.write_text(source, encoding="utf-8")
        started = time.perf_counter()
        try:
            grader.prepare_workspace(workdir, src)
            cmd, _disp, warnings = grader.prepare_command(src, workdir)
        except grader.SandboxUnavailable:
            return {"error": "execution environment unavailable"}
        except grader.CompileError as e:
            return {"verdict": "CE", "stdout": "", "stderr": _sanitize_compile_error(str(e))[:4000],
                    "wall_s": round(time.perf_counter() - started, 4),
                    "cpu_s": 0.0, "peak_mb": 0.0, "reason": "compile-error",
                    "build_warnings": "",
                    "limits": _effective(prob, time_limit, memory_mb, settings)[2],
                    "memory_capped": memory_mb > settings.memory_cap_mb}
        except SystemExit as e:
            return {"error": _sanitize_compile_error(str(e))}
        _tl, eff_mem, limits = _effective(prob, time_limit, memory_mb, settings)
        res = grader.run_one(cmd, stdin_data, time_limit, eff_mem,
                             grader.detect_language(src))
        reason = res.get("reason", "")
        if reason in ("sandbox-unavailable", "spawn-fail"):
            # No user code ran (or mandatory isolation was unavailable): this
            # is an environment failure, never a user-visible RE/CE verdict.
            return {"error": "execution environment unavailable"}
        if reason == "timeout":
            verdict = "TLE"
        elif reason == "ole":
            verdict = "OLE"
        elif reason in ("oom", "sigkill"):
            verdict = "MLE"
        elif reason.startswith("signal:"):
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
