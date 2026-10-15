#!/usr/bin/env python3
"""Validate every problem under problems/ (stdlib only).

Usage:
    python3 tools/validate_problem.py [id ...] [--jobs N]

Checks, per problem:
  1. config.json  (title / limits / checker / difficulty / tags / notice / samples).
     `samples` is a list of test-name strings (canonical); an int (first N tests
     public) is accepted too since grader.load_problem supports it.
  2. statement.md (non-empty) and statement.pdf (>1KB; missing = warning)
  3. tests/        count >= 10, contiguous 01..NN numbering, no orphans,
                   UTF-8, no CR, .in non-empty
  4. statement samples: every fenced `input:` / `output:` pair should match a
     shipped test under token comparison; when it does not, the statement
     example cannot be a public sample -> warning (not a failure)
  5. reference solution examples/<id>_ref.{py,cpp}: must compile and AC all tests

Exit code 0 only when there are no failures (warnings do not fail).

Reuses grader.load_problem / KNOWN_TAGS / prepare_command / judge_test /
CompileError so the validator and the judge cannot drift apart.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import sys
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

import grader  # noqa: E402  (path set above)

PROBLEMS_DIR = REPO / "problems"
EXAMPLES_DIR = REPO / "examples"

VALID_CHECKERS = {"token", "exact", "float", "decimal2"}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}
PDF_MIN_BYTES = 1024
MIN_TESTS = 10

# redirect_stdout swaps the *global* sys.stdout, so it must be serialized when
# problems are validated from a thread pool.
_LOAD_LOCK = threading.Lock()

FENCE_RE = re.compile(r"```[^\n]*\n(.*?)```", re.S)
INPUT_LABEL_RE = re.compile(r"^\s*input\s*:\s*(.*)$", re.I)
OUTPUT_LABEL_RE = re.compile(r"^\s*output\s*:\s*(.*)$", re.I)


# ---------------------------------------------------------------- statement

def parse_samples(md: str) -> list[tuple[str, str]]:
    """Extract (input, output) pairs from fenced `input:`/`output:` blocks.

    Several blocks may exist; a single block may even hold several pairs.
    Text after the label on the same line is part of the body.
    """
    pairs: list[tuple[str, str]] = []
    for body in FENCE_RE.findall(md):
        mode: str | None = None
        buf: dict[str, list[str]] = {"in": [], "out": []}
        for line in body.split("\n"):
            m = INPUT_LABEL_RE.match(line)
            if m and not OUTPUT_LABEL_RE.match(line):
                if mode == "out":
                    pairs.append((_join(buf["in"]), _join(buf["out"])))
                mode, buf = "in", {"in": [], "out": []}
                if m.group(1).strip():
                    buf["in"].append(m.group(1))
                continue
            m = OUTPUT_LABEL_RE.match(line)
            if m:
                mode = "out"
                if m.group(1).strip():
                    buf["out"].append(m.group(1))
                continue
            if mode == "in":
                buf["in"].append(line)
            elif mode == "out":
                buf["out"].append(line)
        if mode == "out":
            pairs.append((_join(buf["in"]), _join(buf["out"])))
        elif mode == "in":
            # `input:` without a matching `output:` label
            pairs.append((_join(buf["in"]), None))  # type: ignore[arg-type]
    return pairs


def _join(lines: list[str]) -> str:
    return "\n".join(lines).strip("\n").strip()


def canon(text: str) -> str:
    """Whitespace-normalized form: rstrip every line, drop trailing blank lines."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    while lines and not lines[-1].strip():
        lines.pop()
    while lines and not lines[0].strip():
        lines.pop(0)
    return "\n".join(lines)


def tokens(text: str) -> list[str]:
    return text.split()


# ---------------------------------------------------------------- one problem

def validate_problem(pid: str) -> dict:
    res: dict = {"pid": pid, "failures": [], "warnings": [],
                 "tests": 0, "slowest": None, "ref": "", "hidden": False, "no": 0}
    pdir = PROBLEMS_DIR / pid

    def fail(msg: str) -> None:
        res["failures"].append(msg)

    def warn(msg: str) -> None:
        res["warnings"].append(msg)

    if not pdir.is_dir():
        fail(f"problem directory not found: problems/{pid}")
        return res

    # ---- 1. config.json -----------------------------------------------
    cfg = {}
    cfg_path = pdir / "config.json"
    if not cfg_path.exists():
        fail("config.json is missing")
    else:
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except Exception as e:  # noqa: BLE001 - report any parse error verbatim
            fail(f"config.json is not valid JSON: {e}")
            cfg = None
    if isinstance(cfg, dict):
        title = cfg.get("title")
        if not isinstance(title, str) or not title.strip():
            fail("config.title must be a non-empty string")
        tl = cfg.get("time_limit")
        if not isinstance(tl, (int, float)) or isinstance(tl, bool) or not (0 < float(tl) <= 60):
            fail(f"config.time_limit must be 0 < t <= 60 (got {tl!r})")
        ml = cfg.get("memory_limit")
        if not isinstance(ml, int) or isinstance(ml, bool) or not (16 <= ml <= 4096):
            fail(f"config.memory_limit must be an int 16..4096 (got {ml!r})")
        if cfg.get("checker") not in VALID_CHECKERS:
            fail(f"config.checker must be one of {sorted(VALID_CHECKERS)} (got {cfg.get('checker')!r})")
        if cfg.get("difficulty") not in VALID_DIFFICULTIES:
            fail(f"config.difficulty must be one of {sorted(VALID_DIFFICULTIES)} (got {cfg.get('difficulty')!r})")
        tags = cfg.get("tags")
        if not isinstance(tags, list) or not tags:
            fail("config.tags must be a non-empty list")
        else:
            bad = [t for t in tags if t not in grader.KNOWN_TAGS]
            if bad:
                fail(f"config.tags has unknown tag(s) {bad}; known = {grader.KNOWN_TAGS}")
        if "notice" in cfg and not isinstance(cfg["notice"], str):
            fail(f"config.notice must be a string if present (got {type(cfg['notice']).__name__})")
        # numeric problem id: every problem must carry one (unique, checked in main)
        no = cfg.get("no")
        if no is None:
            fail("config.no is missing — assign one with "
                 "`python3 tools/number_problems.py --assign`")
        elif not isinstance(no, int) or isinstance(no, bool) or no < 1:
            fail(f"config.no must be an integer >= 1 (got {no!r})")
    elif cfg is not None:
        fail(f"config.json must contain a JSON object (got {type(cfg).__name__})")
        cfg = {}

    # ---- 2. statement --------------------------------------------------
    md_path = pdir / "statement.md"
    md = ""
    if not md_path.exists():
        fail("statement.md is missing")
    else:
        md = md_path.read_text(encoding="utf-8", errors="replace")
        if not md.strip():
            fail("statement.md is empty")
    pdf_path = pdir / "statement.pdf"
    if not pdf_path.exists():
        warn("statement.pdf is missing")
    elif pdf_path.stat().st_size <= PDF_MIN_BYTES:
        warn(f"statement.pdf is suspiciously small ({pdf_path.stat().st_size} bytes)")

    # ---- 3. tests ------------------------------------------------------
    tdir = pdir / "tests"
    paired: list[grader.TestCase] = []
    if not tdir.is_dir():
        fail("tests/ directory is missing")
    else:
        ins = {p.stem: p for p in tdir.glob("*.in")}
        outs = {p.stem: p for p in tdir.glob("*.out")}
        for stem in sorted(set(ins) - set(outs)):
            fail(f"tests/{stem}.in has no matching .out")
        for stem in sorted(set(outs) - set(ins)):
            fail(f"tests/{stem}.out has no matching .in")
        for p in sorted(list(ins.values()) + list(outs.values())):
            try:
                data = p.read_bytes()
            except OSError as e:
                fail(f"tests/{p.name} unreadable: {e}")
                continue
            if b"\r" in data:
                fail(f"tests/{p.name} contains CR (\\r) bytes; tests must be LF-only")
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError as e:
                fail(f"tests/{p.name} is not valid UTF-8: {e}")
                continue
            if p.suffix == ".in" and not data:
                fail(f"tests/{p.name} is empty")

        stems = sorted(ins)
        if stems:
            expected = [f"{i:02d}" for i in range(1, len(stems) + 1)]
            if stems != expected:
                missing = [s for s in expected if s not in ins]
                extra = [s for s in stems if s not in expected]
                detail = []
                if missing:
                    detail.append(f"missing {missing}")
                if extra:
                    detail.append(f"unexpected numbering {extra}")
                fail("tests are not a contiguous 01..NN sequence: " + "; ".join(detail))
        if len(stems) < MIN_TESTS:
            fail(f"only {len(stems)} tests, need at least {MIN_TESTS}")

        # samples key: canonical form is a list of test-name strings; an int
        # (first N tests public) is also accepted because grader.load_problem
        # supports it, but the repo does not use it.
        if isinstance(cfg, dict) and "samples" in cfg:
            samples = cfg["samples"]
            if isinstance(samples, bool):
                fail(f"config.samples must be a list of test names or an int (got {samples!r})")
            elif isinstance(samples, int):
                if not (0 <= samples <= len(stems)):
                    fail(f"config.samples={samples} out of range 0..{len(stems)}")
            elif isinstance(samples, list):
                valid_names = set(stems)
                seen: set[str] = set()
                for s in samples:
                    if not isinstance(s, str):
                        fail(f"config.samples entries must be strings (got {s!r})")
                    elif s not in valid_names:
                        fail(f"config.samples names unknown test '{s}' (not a tests/*.in stem)")
                    elif s in seen:
                        fail(f"config.samples lists test '{s}' more than once")
                    else:
                        seen.add(s)
            else:
                fail("config.samples must be a list of test-name strings or an int "
                     f"(got {type(samples).__name__})")

    # ---- load the problem through the real loader ----------------------
    prob = None
    if tdir.is_dir():
        buf = io.StringIO()
        with _LOAD_LOCK:
            try:
                with redirect_stdout(buf):
                    prob = grader.load_problem(pid)
            except SystemExit as e:
                fail(str(e))
        for ln in buf.getvalue().splitlines():
            if ln.strip():
                warn(f"grader: {ln.strip()}")
        if prob is not None:
            paired = prob.tests
            res["tests"] = len(prob.tests)

    # ---- 5. reference solution -----------------------------------------
    ref = EXAMPLES_DIR / f"{pid}_ref.py"
    if not ref.exists():
        alt = EXAMPLES_DIR / f"{pid}_ref.cpp"
        ref = alt if alt.exists() else None  # type: ignore[assignment]
    cmd = None
    tmpdir = None
    if ref is None:
        res["ref"] = "missing"
        fail(f"reference solution examples/{pid}_ref.py (or .cpp) is missing")
    elif prob is not None:
        tmpdir = tempfile.TemporaryDirectory(prefix=f"val_{pid}_")
        try:
            cmd, disp, build_warnings = grader.prepare_command(ref, Path(tmpdir.name))
            res["ref"] = disp
            for ln in (build_warnings or "").splitlines()[:10]:
                warn(f"ref build: {ln.strip()[:200]}")
        except grader.CompileError as e:
            cmd = None
            res["ref"] = "CE"
            fail(f"reference solution failed to compile:\n    " + str(e)[:2000].replace("\n", "\n    "))
        except SystemExit as e:
            cmd = None
            res["ref"] = "unavailable"
            fail(f"cannot prepare reference solution: {e}")

    if cmd is not None and prob is not None:
        verdicts = []
        slowest = 0.0
        for tc in prob.tests:
            v, wall, _cpu, _mem, _detail, _actual = grader.judge_test(
                cmd, tc, prob, False, False, grader.detect_language(ref))
            verdicts.append((tc.name, v))
            slowest = max(slowest, wall)
        res["slowest"] = slowest
        n_ac = sum(1 for _n, v in verdicts if v == "AC")
        res["ref"] = f"{res['ref']} AC {n_ac}/{len(verdicts)}"
        bad = [(n, v) for n, v in verdicts if v != "AC"]
        if bad:
            summary = ", ".join(f"{n}:{v}" for n, v in bad[:12])
            fail(f"reference solution is not AC on all tests ({n_ac}/{len(verdicts)} AC): {summary}")

    # ---- 4. sample consistency -----------------------------------------
    if md.strip():
        samples = parse_samples(md)
        if not samples:
            warn("statement.md has no fenced `input:`/`output:` sample block")
        test_pairs = [(t.input, t.expected, t.name) for t in paired]
        for idx, pair in enumerate(samples, 1):
            if pair[1] is None:
                warn(f"sample #{idx}: `input:` block has no `output:` label, skipped")
                continue
            s_in, s_out = pair
            hit = next((name for ti, to, name in test_pairs
                        if tokens(ti) == tokens(s_in) and tokens(to) == tokens(s_out)), None)
            if hit is not None:
                ti, to, _ = next(x for x in test_pairs if x[2] == hit)
                if canon(ti) != canon(s_in) or canon(to) != canon(s_out):
                    warn(f"sample #{idx} matches test {hit} only after whitespace "
                         "normalization (statement layout differs from tests/*.in|out)")
                continue
            # not among shipped tests: the statement example cannot be a public
            # sample (config.samples could never reference it) -> warning only.
            warn(f"sample #{idx}: statement example not shipped as a test "
                 f"-> cannot be public sample ({pid})")

    if tmpdir is not None:
        tmpdir.cleanup()

    # visibility (contest-only problems are kept out of the public Task list)
    try:
        prob = grader.load_problem(pid)
        res["hidden"] = bool(prob.hidden)
        res["no"] = int(prob.no)
    except SystemExit:
        res["hidden"] = False
    return res


def _read_no(pid: str) -> tuple:
    """(pid, no) from config.json, 0 when missing/invalid (cheap, no judging)."""
    try:
        cfg = json.loads((PROBLEMS_DIR / pid / "config.json").read_text(encoding="utf-8"))
    except Exception:
        return pid, 0
    no = cfg.get("no")
    return pid, no if isinstance(no, int) and not isinstance(no, bool) and no > 0 else 0


# ---------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate problems/ (config, tests, samples, refs).")
    ap.add_argument("ids", nargs="*", help="problem ids (default: all, sorted)")
    ap.add_argument("--jobs", "-j", type=int, default=1,
                    help="problems to validate concurrently (default: %(default)s). "
                         "Keep this low: judge_test enforces wall-clock time limits, so "
                         "running many references at once causes contention-induced TLEs")
    args = ap.parse_args(argv)

    if args.ids:
        ids = sorted(dict.fromkeys(args.ids))
    else:
        if not PROBLEMS_DIR.is_dir():
            print(f"no problems/ directory at {PROBLEMS_DIR}")
            return 1
        ids = sorted(p.name for p in PROBLEMS_DIR.iterdir() if p.is_dir())
    if not ids:
        print("no problems to validate")
        return 0

    jobs = max(1, args.jobs)
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for res in pool.map(validate_problem, ids):
            results[res["pid"]] = res

    # config.no must be unique across ALL problems, not just the ones requested
    numbers: dict[int, list] = {}
    if PROBLEMS_DIR.is_dir():
        all_ids = [p.name for p in PROBLEMS_DIR.iterdir() if p.is_dir()]
        with ThreadPoolExecutor(max_workers=max(1, min(jobs if jobs > 1 else 1, 8))) as pool:
            for pid, no in pool.map(_read_no, all_ids):
                if no:
                    numbers.setdefault(no, []).append(pid)
    for no, pids in sorted(numbers.items()):
        if len(pids) > 1:
            for pid in pids:
                if pid in results:
                    results[pid]["failures"].append(
                        f"config.no {no} is also used by "
                        f"{', '.join(p for p in pids if p != pid)}")

    n_fail = 0
    n_warn = 0
    for pid in ids:
        res = results[pid]
        if res["warnings"]:
            n_warn += 1
            print(f"WARN {pid}")
            for w in res["warnings"]:
                print(f"  ! {w}")
        if res["failures"]:
            n_fail += 1
            print(f"FAIL {pid}")
            for f in res["failures"]:
                print(f"  x {f}")
        else:
            slow = res["slowest"]
            slow_s = f"{slow:.3f}s" if slow is not None else "-"
            no_s = f"#{res['no']:<3}" if res.get("no") else "#—  "
            print(f"OK   {no_s} {pid:<22} tests={res['tests']:<3} slowest={slow_s:<8} ref={res['ref']}"
                  + ("  [contest-only: ไม่โชว์ในหน้า Task]" if res.get("hidden") else ""))

    ok = len(ids) - n_fail
    print("-" * 64)
    print(f"{ok}/{len(ids)} problems OK"
          + (f"  ({n_fail} FAIL, {n_warn} WARN)" if n_fail or n_warn else ""))
    return 0 if n_fail == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
