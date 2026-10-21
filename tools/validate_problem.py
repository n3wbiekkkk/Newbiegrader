#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Validate every problem under problems/ (stdlib only).

Usage:
    python3 tools/validate_problem.py [id ...] [--jobs N]

Checks, per problem:
  1. config.json  (title / limits / checker / difficulty / tags / samples).
     `samples` is a list of test-name strings (canonical); an int (first N tests
     public) is accepted too since grader.load_problem supports it. Policy: at
     least MIN_SAMPLES (3) public samples per problem.
  2. statement.md (non-empty) and statement.pdf (>1KB; missing = warning)
  3. tests/        count >= 10, samples numbered 01.. (small) + hidden tests
                   numbered contiguously from 1001 up, no orphans,
                   UTF-8, no CR, .in non-empty
  4. statement samples: match public fixtures exactly in config.samples order
     (ignoring one terminal LF only). Whitespace/layout mismatches fail.
     Oversized examples (> MAX_SAMPLE_TOKENS) are warnings.
  5. reference solution examples/<id>_ref.{py,cpp}: must compile and AC all tests
  6. optional trusted input_validator.py: validate every input with a deadline.
     --strict requires this validator, standard structure and no warnings.

Exit code 0 only when there are no failures (warnings do not fail).

Reuses grader.load_problem / KNOWN_TAGS / prepare_command / judge_test /
CompileError so the validator and the judge cannot drift apart.
"""
from __future__ import annotations

import argparse
import io
import json
import re
import subprocess
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
from tools.statement_build import check_build  # noqa: E402

PROBLEMS_DIR = REPO / "problems"
EXAMPLES_DIR = REPO / "examples"

VALID_CHECKERS = {"token", "exact", "float", "decimal2"}
VALID_DIFFICULTIES = {"easy", "medium", "hard"}
PDF_MIN_BYTES = 1024
MIN_TESTS = 10
MIN_SAMPLES = 3
# Sample examples must stay short and readable: a public example is a
# demonstration, not a stress test. Inputs past this many tokens are flagged.
MAX_SAMPLE_TOKENS = 40

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
    return "\n".join(lines).strip("\n")


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


def public_sample_errors(cfg: dict, md: str, tests: list[grader.TestCase]) -> list[str]:
    """Public samples must match fixtures in declared order, including spaces.

    A single terminal LF in a fixture is a file terminator, not sample content.
    Never include fixture contents in diagnostics (tests can be hidden).
    """
    names = cfg.get("samples")
    if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
        return ["config.samples must be a list of public test names"]
    if (len(names) < MIN_SAMPLES or len(set(names)) != len(names)
            or any(not re.fullmatch(r"(?:0[1-9]|[1-9][0-9])", n) for n in names)):
        return ["config.samples must list at least 3 unique public names (01..99)"]
    pairs = parse_samples(md)
    errors = []
    if len(pairs) != len(names):
        errors.append(f"statement.md has {len(pairs)} sample block(s) but config.samples lists {len(names)}")
    by_name = {t.name: t for t in tests}
    for idx, (name, pair) in enumerate(zip(names, pairs), 1):
        tc = by_name.get(name)
        if tc is None:
            errors.append(f"sample #{idx}: declared test {name} is missing")
        elif pair[1] is None:
            errors.append(f"sample #{idx}: missing output label")
        elif (pair[0] != tc.input.removesuffix("\n")
              or pair[1] != tc.expected.removesuffix("\n")):
            errors.append(f"sample #{idx}: must match public test {name} exactly (including spaces and line breaks)")
    return errors


def statement_contract_errors(cfg: dict, md: str) -> list[str]:
    """Strict authoring style; supplements semantic review, never replaces it."""
    errors = []
    title = str(cfg.get("title") or "")
    if not re.fullmatch(r".+ [\(][^()]*[A-Za-z][^()]*[\)]", title) or not any("\u0e00" <= c <= "\u0e7f" for c in title):
        errors.append("config.title must use Thai Name (English Name)")
    if not md.splitlines() or md.splitlines()[0] != f"# {title}":
        errors.append("statement heading must equal config.title")
    headings = re.findall(r"^## (.+)$", md, flags=re.M)
    required = ["Input", "Output", "ตัวอย่าง", "คำอธิบายตัวอย่าง"]
    if any(headings.count(h) != 1 for h in required):
        errors.append("require one Input, Output, ตัวอย่าง and คำอธิบายตัวอย่าง section")
    elif [headings.index(h) for h in required] != sorted(headings.index(h) for h in required):
        errors.append("statement sections must follow the template order")
    for h in headings:
        if h.casefold() in {"แนวคิด", "วิธีทำ", "คำใบ้", "กับดัก", "hint", "hints", "solution", "editorial"}:
            errors.append("statement must not include solution/hint sections")
    if re.search(r"\b(?:TODO|TBD)\b|\{\{TITLE\}\}", md):
        errors.append("statement contains unfinished template placeholders")
    if "Limits" in headings:
        try:
            expected = f"- เวลา {float(cfg['time_limit']):g} วินาที, หน่วยความจำ {cfg['memory_limit']} MB"
            section = re.split(r"^## ", md.split("## Limits\n", 1)[1], maxsplit=1, flags=re.M)[0]
            if expected not in section.splitlines():
                errors.append("Limits resource line must match config.time_limit/memory_limit")
        except (KeyError, ValueError, TypeError, IndexError):
            errors.append("cannot verify Limits resource line")
    return errors


# ---------------------------------------------------------------- one problem

def validate_problem(pid: str, strict: bool = False) -> dict:
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
    if strict and isinstance(cfg, dict):
        for error in statement_contract_errors(cfg, md):
            fail(error)
    if isinstance(cfg, dict):
        for error in check_build(pdir, cfg, md, required=strict):
            fail(error)

    # ---- 3. tests ------------------------------------------------------
    tdir = pdir / "tests"
    paired: list[grader.TestCase] = []
    declared_samples: list[str] | None = None
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
            # Naming scheme: the number itself tells the status apart —
            # public samples keep small numbers (01, 02, ...) while every
            # hidden test is numbered from 1001 up. So a small-numbered test
            # must be a declared sample, and hidden names must be contiguous.
            raw = cfg.get("samples") if isinstance(cfg, dict) else None
            declared = set(raw) if isinstance(raw, list) else set()
            big = [s for s in stems if len(s) == 4 and s.startswith("10")]
            small = [s for s in stems if s not in big]
            bad_small = [s for s in small if s not in declared]
            if bad_small:
                fail(f"tests {bad_small} are not declared in config.samples — "
                     "small numbers are public samples only, hidden tests must "
                     "be numbered 1001..")
            want_big = [str(1000 + i) for i in range(1, len(big) + 1)]
            if big != want_big:
                fail(f"hidden tests must be contiguous 1001..{1000 + len(big)} "
                     f"(got {big})")
        if len(stems) < MIN_TESTS:
            fail(f"only {len(stems)} tests, need at least {MIN_TESTS}")

        # At least one hidden test is required so hidden-test protection
        # is meaningful.
        hidden_tests = [s for s in stems if len(s) == 4 and s.startswith("10")]
        if not hidden_tests:
            fail(f"problem {pid}: at least one hidden test (numbered 1001+) is required")

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
                elif samples < MIN_SAMPLES:
                    fail(f"config.samples={samples} < MIN_SAMPLES={MIN_SAMPLES}: every "
                         "problem must ship at least 3 public examples")
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
                declared_samples = [s for s in samples if isinstance(s, str)]
                if len(declared_samples) < MIN_SAMPLES:
                    fail(f"config.samples lists {len(declared_samples)} sample(s); policy "
                         f"requires at least {MIN_SAMPLES} (3 public examples)")
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

    # Trusted author-provided grammar checker, invoked on every input (public
    # and hidden) with a deadline and discarded diagnostics. Never a judge hook.
    validator = pdir / "input_validator.py"
    if strict and not validator.is_file():
        fail("input_validator.py is required in strict mode")
    if validator.is_file():
        try:
            unfinished = re.search(r"\b(?:TODO|TBD)\b", validator.read_text(encoding="utf-8"))
            if unfinished:
                fail("input_validator.py contains unfinished template placeholders")
            else:
                for tc in paired:
                    try:
                        check = subprocess.run([sys.executable, "-I", str(validator.resolve())],
                                               input=tc.input.encode("utf-8"), cwd=pdir,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                               timeout=2, check=False)
                        if check.returncode != 0:
                            fail(f"input_validator.py rejected test {tc.name} (exit {check.returncode})")
                    except subprocess.TimeoutExpired:
                        fail(f"input_validator.py timed out on test {tc.name}")
        except (OSError, UnicodeError):
            fail("input_validator.py is unreadable")

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
        if strict and re.search(r"\b(?:TODO|TBD)\b", ref.read_text(encoding="utf-8")):
            fail("reference solution contains unfinished template placeholders")
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
        if isinstance(cfg, dict):
            sample_cfg = cfg
            count = cfg.get("samples")
            if declared_samples is None and isinstance(count, int) and not isinstance(count, bool):
                sample_cfg = dict(cfg, samples=[t.name for t in paired[:max(0, count)]])
            for error in public_sample_errors(sample_cfg, md, paired):
                fail(error)
        for idx, (s_in, _s_out) in enumerate(samples, 1):
            if len(tokens(s_in)) > MAX_SAMPLE_TOKENS:
                warn(f"sample #{idx} exceeds {MAX_SAMPLE_TOKENS} input tokens; use a short example")

    if tmpdir is not None:
        tmpdir.cleanup()

    # visibility (contest-only problems are kept out of the public Task list)
    try:
        prob = grader.load_problem(pid)
        res["hidden"] = bool(prob.hidden)
        res["no"] = int(prob.no)
    except SystemExit:
        res["hidden"] = False
    if strict:
        res["failures"].extend(f"strict: {w}" for w in res["warnings"])
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
    ap.add_argument("--strict", action="store_true",
                    help="require the authoring template, input validator and PDF; fail on warnings or missing packages")
    ap.add_argument("--jobs", "-j", type=int, default=1,
                    help="problems to validate concurrently (default: %(default)s). "
                         "Keep this low: judge_test enforces wall-clock time limits, so "
                         "running many references at once causes contention-induced TLEs")
    args = ap.parse_args(argv)

    if args.ids:
        ids = sorted(dict.fromkeys(args.ids))
    else:
        if not PROBLEMS_DIR.is_dir():
            # Problem packages are not versioned in this repository (the source
            # of truth is Supabase). Nothing to validate here: report a skip so
            # CI stays green; run from a checkout that has problems/ to validate.
            print(f"skip: no problems/ directory at {PROBLEMS_DIR} "
                  "(problem data lives in Supabase)")
            return 1 if args.strict else 0
        ids = sorted(p.name for p in PROBLEMS_DIR.iterdir() if p.is_dir())
    if not ids:
        print("no problems to validate")
        return 1 if args.strict else 0

    jobs = max(1, args.jobs)
    results: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for res in pool.map(lambda pid: validate_problem(pid, strict=args.strict), ids):
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
