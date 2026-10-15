#!/usr/bin/env python3
"""
Brutal Competitive Programming Grader (stdlib only, no dependencies).

Usage:
    python grader.py list
    python grader.py info <problem_id>
    python grader.py run <problem_id> <solution_file> [--time-limit X] [--memory-limit Y]
        [--strict] [--stop-on-fail] [--verbose] [--jobs N] [--json report.json] [--no-color]

Exit code: 0 if AC (100 pts), 1 otherwise.
Works on macOS/Linux. Windows: runs but without RLIMIT isolation.
"""
from __future__ import annotations
import argparse
import concurrent.futures
import difflib
import hashlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).parent
PROBLEMS_DIR = ROOT / "problems"

# Brutal constants
OUTPUT_LIMIT_BYTES = 32 * 1024 * 1024  # stdout เกินนี้ -> OLE (กัน print-loop อนันต์ถล่ม RAM)
# Judging semantics version: bump when a change could make the same submission
# score differently (checker rules, limits handling, verdict mapping). Stored on
# every submission together with the per-problem tests hash so old rows can be
# told apart from new ones (and optionally rejudged).
GRADER_VERSION = "2.0.0"

# ---------- host capability (container aware) ----------
def cgroup_root() -> str:
    """Where to look for cgroup files. Overridable so the detection math can be
    unit-tested (and for exotic mounts)."""
    return (os.environ.get("GRADER_CGROUP_ROOT", "/sys/fs/cgroup").rstrip("/")
            or "/sys/fs/cgroup")


def _read_first(path: str) -> str:
    try:
        return Path(path).read_text().strip()
    except (OSError, ValueError):
        return ""


def cpu_quota() -> float:
    """vCPU allowance of this container (cgroup v2 -> v1 -> cpu_count).

    Hosts are often a fraction of a core (e.g. 0.5), where judging two
    submissions at once steals CPU from both and turns wall-clock TLEs into
    noise, so the grader scales its concurrency from this number.
    """
    root = cgroup_root()
    parts = _read_first(f"{root}/cpu.max").split()
    if len(parts) == 2 and parts[0] != "max":
        try:
            quota, period = float(parts[0]), float(parts[1])
            if quota > 0 and period > 0:
                return max(0.1, quota / period)
        except ValueError:
            pass
    try:
        quota = float(_read_first(f"{root}/cpu/cpu.cfs_quota_us"))
        period = float(_read_first(f"{root}/cpu/cpu.cfs_period_us"))
        if quota > 0 and period > 0:
            return max(0.1, quota / period)
    except ValueError:
        pass
    return float(os.cpu_count() or 1)


def ram_limit_mb() -> int:
    """Memory ceiling of this container in MB (cgroup v2 -> v1 -> total RAM)."""
    root = cgroup_root()
    unlimited = 1 << 62
    for path in (f"{root}/memory.max",
                 f"{root}/memory/memory.limit_in_bytes"):
        raw = _read_first(path)
        if raw and raw != "max":
            try:
                val = int(raw)
            except ValueError:
                continue
            if 0 < val < unlimited:
                return max(64, val // (1024 * 1024))
    try:
        return max(64, (os.sysconf("SC_PHYS_PAGES") * os.sysconf("SC_PAGE_SIZE"))
                   // (1024 * 1024))
    except (ValueError, OSError, AttributeError):
        return 512


CPU_QUOTA = cpu_quota()
RAM_MB = ram_limit_mb()

# Peak-RSS sampling: 5 ms is free on a real core, wasteful on a 0.5 vCPU box
# (a thread waking 200x/s competes with the very process being measured).
SAMPLE_INTERVAL = float(os.environ.get("GRADER_SAMPLE_INTERVAL", "0") or 0) or (
    0.005 if CPU_QUOTA > 1 else 0.02)
# Compiling C++ with -O2 can take tens of seconds on a fractional core.
COMPILE_TIMEOUT = float(os.environ.get("GRADER_COMPILE_TIMEOUT", "0") or 0) or (
    60.0 if CPU_QUOTA > 1 else 90.0)

# ---------- colors ----------
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    DIM = "\033[2m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    GRAY = "\033[90m"

USE_COLOR = sys.stdout.isatty()

def c(s: str, color: str) -> str:
    if not USE_COLOR or os.environ.get("NO_COLOR"):
        return s
    return f"{color}{s}{C.RESET}"

def verdict_color(v: str) -> str:
    return {
        "AC": C.GREEN, "WA": C.RED, "TLE": C.YELLOW, "OLE": C.YELLOW,
        "MLE": C.MAGENTA, "RE": C.RED, "CE": C.RED,
    }.get(v, C.RESET)

# ---------- data ----------
@dataclass
class TestCase:
    name: str
    input: str
    expected: str

@dataclass
class Problem:
    pid: str
    title: str
    time_limit: float
    memory_limit: int  # MB
    checker: str       # exact | token | float
    tolerance: float
    description: str
    tests: list[TestCase]
    difficulty: str = ""        # easy | medium | hard (ไว้ filter)
    tags: list[str] = field(default_factory=list)
    notice: str = ""            # ประกาศโชว์บนหน้า task (เช่น ข้อนี้ใช้อะไรก็ได้)
    samples: list[str] = field(default_factory=list)  # ชื่อ test ที่เป็น "ตัวอย่างสาธารณะ" (ที่เหลือ = hidden)
    hidden: bool = False        # true = โจทย์ชุดคอนเทสต์: ไม่โชว์ในหน้า Task (admin/คอนเทสต์เห็น)
    no: int = 0                 # เลขโจทย์ (id เลข ใช้เรียง/ค้นหา) — 0 = ยังไม่กำหนด

# Canonical tag taxonomy (frontend Tag Filter renders exactly this list).
KNOWN_TAGS = [
    "Implementation", "Math", "Ad-hoc", "String", "Data Structure", "DP",
    "Sweepline", "Greedy", "DFS", "Bitmasks", "Binary Search", "Graph",
    "DSU", "Sorting", "Sliding Window", "Divide and Conquer",
    "Matrix Exponential", "Tree", "Fixed Parameter", "Hashing", "Geometry",
    "NP", "Recursive", "Linear Algebra", "Matching",
]

def load_problem(pid: str) -> Problem:
    pdir = PROBLEMS_DIR / pid
    if not pdir.is_dir():
        raise SystemExit(f"Problem '{pid}' not found. Run `python grader.py list`.")
    cfg_path = pdir / "config.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) if cfg_path.exists() else {}
    title = cfg.get("title", pid)
    time_limit = float(cfg.get("time_limit", 1.0))
    memory_limit = int(cfg.get("memory_limit", 256))
    checker = cfg.get("checker", "token")
    tolerance = float(cfg.get("tolerance", 1e-6))
    difficulty = str(cfg.get("difficulty", ""))
    _tags = cfg.get("tags", [])
    tags = [str(t) for t in _tags] if isinstance(_tags, list) else []
    for t in tags:
        if t not in KNOWN_TAGS:
            print(c(f"WARNING: problem '{pid}' uses unknown tag '{t}'", C.YELLOW))
    notice = str(cfg.get("notice", ""))
    desc_path = pdir / "statement.md"
    description = desc_path.read_text(encoding="utf-8") if desc_path.exists() else ""

    tests: list[TestCase] = []
    tdir = pdir / "tests"
    if tdir.is_dir():
        ins = sorted(tdir.glob("*.in"))
        for inp in ins:
            outp = inp.with_suffix(".out")
            if not outp.exists():
                print(c(f"WARNING: {inp.name} has no matching .out, skipped", C.YELLOW))
                continue
            tests.append(TestCase(
                name=inp.stem,
                input=inp.read_text(encoding="utf-8"),
                expected=outp.read_text(encoding="utf-8"),
            ))
    if not tests:
        raise SystemExit(f"Problem '{pid}' has no tests in problems/{pid}/tests/")
    tests.sort(key=lambda t: t.name)
    names = {t.name for t in tests}
    raw_samples = cfg.get("samples", [])
    samples: list[str] = []
    if isinstance(raw_samples, list):
        # canonical form: explicit test names, e.g. ["02", "03"]
        samples = [str(s) for s in raw_samples if str(s) in names]
        missing = [str(s) for s in raw_samples if str(s) not in names]
        if missing:
            print(c(f"WARNING: problem '{pid}' samples not found in tests: {missing}", C.YELLOW))
    elif isinstance(raw_samples, int) and raw_samples > 0:
        # shorthand: first N tests are public samples
        samples = [t.name for t in tests[:raw_samples]]
    samples = sorted(set(samples))
    hidden = bool(cfg.get("hidden", False))
    try:
        no = int(cfg.get("no", 0))
    except (TypeError, ValueError):
        print(c(f"WARNING: problem '{pid}' has a non-numeric 'no' ({cfg.get('no')!r})",
                C.YELLOW))
        no = 0
    if no < 0:
        print(c(f"WARNING: problem '{pid}' has a negative 'no' ({no})", C.YELLOW))
        no = 0
    return Problem(pid, title, time_limit, memory_limit, checker, tolerance, description, tests,
                   difficulty, tags, notice, samples, hidden, no)


DIFFICULTY_RANK = {"easy": 0, "medium": 1, "hard": 2}


def order_key(prob: "Problem") -> tuple:
    """Display order: numbered problems first by number, then the rest by
    difficulty/name (so a problem added before numbering still shows up)."""
    return (0 if prob.no > 0 else 1, prob.no if prob.no > 0 else 0,
            DIFFICULTY_RANK.get((prob.difficulty or "").lower(), 9), prob.pid)


def sort_problems(probs) -> list:
    return sorted(probs, key=order_key)


def tests_hash(prob: Problem) -> str:
    """Stable 16-hex fingerprint of the data that decides a verdict.

    Any edit to tests/limits/checker/samples changes it, so a stored submission
    can be traced to the exact test set it was judged against.
    """
    h = hashlib.sha256()
    h.update(f"{prob.pid}\n{prob.time_limit}\n{prob.memory_limit}\n"
             f"{prob.checker}\n{prob.tolerance}\n"
             f"{','.join(sorted(prob.samples))}\n".encode())
    for tc in prob.tests:
        h.update(b"--" + tc.name.encode("utf-8") + b"\n")
        h.update(tc.input.encode("utf-8", "replace"))
        h.update(b"\x00")
        h.update(tc.expected.encode("utf-8", "replace"))
        h.update(b"\x00")
    return h.hexdigest()[:16]


def sample_names(prob: Problem) -> set[str]:
    """Public sample test names (statement examples). Everything else is hidden."""
    return set(prob.samples)

def list_problems() -> None:
    if not PROBLEMS_DIR.is_dir():
        print("No problems directory.")
        return
    print(c(f"{'ID':<14}{'TITLE':<32}{'TL':<8}{'MEM':<8}{'TESTS':<6}CHECKER", C.BOLD))
    print("-" * 80)
    for pdir in sorted(PROBLEMS_DIR.iterdir()):
        if not pdir.is_dir():
            continue
        try:
            p = load_problem(pdir.name)
            print(f"{p.pid:<14}{p.title:<32}{p.time_limit:<8}{str(p.memory_limit)+'MB':<8}{len(p.tests):<6}{p.checker}")
        except SystemExit as e:
            print(f"{pdir.name:<14}{c(str(e), C.RED)}")

# ---------- language handling ----------
def detect_language(src: Path):
    ext = src.suffix.lower()
    return {
        ".py": "python", ".pyw": "python",
        ".cpp": "cpp", ".cc": "cpp", ".cxx": "cpp",
        ".c": "c", ".java": "java", ".js": "node",
        ".go": "go", ".rs": "rust",
    }.get(ext)

def prepare_command(src: Path, workdir: Path) -> tuple[list[str], str, str]:
    """Compile if needed. Returns (argv, display, warnings). Raises CompileError."""
    lang = detect_language(src)
    if lang is None:
        raise SystemExit(f"Unsupported extension '{src.suffix}'. Supported: .py .cpp .c .java .js .go .rs")
    src = src.resolve()  # absolute: compile/run steps chdir into isolated dirs
    if lang == "python":
        return [sys.executable, str(src.resolve())], f"python {src.name}", ""
    if lang == "node":
        if not shutil.which("node"):
            raise SystemExit("node not found in PATH")
        return ["node", str(src.resolve())], f"node {src.name}", ""
    if lang == "cpp":
        comp = shutil.which("g++") or shutil.which("clang++")
        if not comp:
            raise SystemExit("No C++ compiler (g++/clang++) found")
        exe = workdir / "sol"
        r = subprocess.run([comp, "-O2", "-std=c++17", "-Wall", "-Wextra",
                            "-o", str(exe), str(src)],
                           capture_output=True, text=True, cwd=str(workdir), env=judge_env(), timeout=COMPILE_TIMEOUT)
        if r.returncode != 0:
            raise CompileError(r.stderr or r.stdout or "compile failed")
        return [str(exe)], f"{Path(comp).name} -O2 -Wall {src.name}", (r.stderr or "").strip()
    if lang == "c":
        comp = shutil.which("gcc") or shutil.which("clang")
        if not comp:
            raise SystemExit("No C compiler found")
        exe = workdir / "sol"
        r = subprocess.run([comp, "-O2", "-std=c11", "-Wall", "-Wextra",
                            "-o", str(exe), str(src)],
                           capture_output=True, text=True, cwd=str(workdir), env=judge_env(), timeout=COMPILE_TIMEOUT)
        if r.returncode != 0:
            raise CompileError(r.stderr or r.stdout or "compile failed")
        return [str(exe)], f"{Path(comp).name} -O2 -Wall {src.name}", (r.stderr or "").strip()
    if lang == "java":
        if not shutil.which("javac") or not shutil.which("java"):
            raise SystemExit("javac/java not found")
        r = subprocess.run(["javac", "-Xlint:all", "-d", str(workdir), str(src)],
                           capture_output=True, text=True, cwd=str(workdir), env=judge_env(), timeout=COMPILE_TIMEOUT)
        if r.returncode != 0:
            raise CompileError(r.stderr or r.stdout or "compile failed")
        cls = src.stem
        return ["java", "-cp", str(workdir), cls], f"javac {src.name} && java {cls}", (r.stderr or "").strip()
    if lang == "go":
        if not shutil.which("go"):
            raise SystemExit("go not found")
        exe = workdir / "sol"
        r = subprocess.run(["go", "build", "-o", str(exe), str(src)],
                           capture_output=True, text=True, cwd=str(workdir), env=judge_env(), timeout=COMPILE_TIMEOUT)
        if r.returncode != 0:
            raise CompileError(r.stderr or r.stdout or "compile failed")
        return [str(exe)], f"go build {src.name}", (r.stderr or "").strip()
    if lang == "rust":
        if not shutil.which("rustc"):
            raise SystemExit("rustc not found")
        exe = workdir / "sol"
        r = subprocess.run(["rustc", "-O", "-o", str(exe), str(src)],
                           capture_output=True, text=True, cwd=str(workdir), env=judge_env(), timeout=COMPILE_TIMEOUT)
        if r.returncode != 0:
            raise CompileError(r.stderr or r.stdout or "compile failed")
        return [str(exe)], f"rustc -O {src.name}", (r.stderr or "").strip()
    raise SystemExit("unreachable")

class CompileError(Exception):
    pass

# ---------- checkers ----------
def check_exact(expected: str, actual: str) -> bool:
    return _linewise_exact(expected, actual)

def _linewise_exact(expected: str, actual: str) -> bool:
    # Brutal: ทุกบรรทัดต้องตรงกันแบบ char-level (รวม trailing space)
    # ผ่อนให้อย่างเดียว: newline ตัวสุดท้ายของไฟล์ (convention ของ judge ทั่วไป)
    e = expected.rstrip("\r\n").split("\n")
    a = actual.rstrip("\r\n").split("\n")
    if len(e) != len(a):
        return False
    for x, y in zip(e, a):
        if x.rstrip("\r") != y.rstrip("\r"):
            return False
    return True

def check_token(expected: str, actual: str) -> bool:
    return expected.split() == actual.split()

def check_float(expected: str, actual: str, tol: float) -> bool:
    et, at = expected.split(), actual.split()
    if len(et) != len(at):
        return False
    for x, y in zip(et, at):
        try:
            fx, fy = float(x), float(y)
            if abs(fx - fy) > tol and abs(fx - fy) / max(1.0, abs(fx), abs(fy)) > tol:
                return False
        except ValueError:
            if x != y:
                return False
    return True

DECIMAL2_RE = re.compile(r"^-?\d+\.\d{2}$")


def check_decimal2(expected: str, actual: str, tol: float = 1e-6) -> bool:
    """Line-locked 2-decimal checker: same line/token counts, every token must
    look like setprecision(2) output, values within tolerance. Leading/trailing
    spaces per line (and multi-space gaps) are forgiven."""
    e = expected.rstrip("\r\n").split("\n")
    a = actual.rstrip("\r\n").split("\n")
    if len(e) != len(a):
        return False
    for x, y in zip(e, a):
        et, at = x.split(), y.split()
        if len(et) != len(at):
            return False
        for u, v in zip(et, at):
            if not DECIMAL2_RE.match(u) or not DECIMAL2_RE.match(v):
                return False
            if abs(float(u) - float(v)) > tol:
                return False
    return True


def run_checker(checker: str, expected: str, actual: str, tol: float) -> bool:
    if checker == "exact":
        return check_exact(expected, actual)
    if checker == "float":
        return check_float(expected, actual, tol)
    if checker == "decimal2":
        return check_decimal2(expected, actual, tol)
    return check_token(expected, actual)

def visible(s: str) -> str:
    return s.replace(" ", "·").replace("\t", "→").replace("\r", "␍")


def _show_diff_head(expected: str, actual: str, e: list[str], a: list[str],
                     context: int = 5) -> str:
    """Linear-scan diff for huge outputs: first mismatch + context window."""
    n = min(len(e), len(a))
    idx = next((i for i in range(n) if e[i].rstrip("\r") != a[i].rstrip("\r")), n)
    out = [c(f"output too large for full diff ({len(e)} vs {len(a)} lines) — "
             f"first mismatch at line {idx + 1}", C.DIM)]
    lo, hi = max(0, idx - context), min(max(len(e), len(a)), idx + context + 1)
    for i in range(lo, hi):
        tag = ">>>" if i == idx else "   "
        le = visible(e[i]) if i < len(e) else c("(no line)", C.GRAY)
        la = visible(a[i]) if i < len(a) else c("(no line)", C.GRAY)
        out.append(f"{tag} line {i + 1}: expected=[{le}] actual=[{la}]")
    out += _whitespace_hints(expected, actual, e, a)
    return "\n".join(out)


def _whitespace_hints(expected: str, actual: str, e: list[str], a: list[str]) -> list[str]:
    hints = []
    e_trail = sum(1 for l in e if l != l.rstrip())
    a_trail = sum(1 for l in a if l != l.rstrip())
    if e_trail or a_trail:
        hints.append(c(f"hint: trailing whitespace — expected lines with trailing ws: {e_trail}, actual: {a_trail}", C.YELLOW))
    if expected.split() == actual.split() and expected.rstrip("\n") != actual.rstrip("\n"):
        hints.append(c("hint: tokens match but whitespace/layout differs → fix newlines/spaces (try --strict to force exact)", C.YELLOW))
    return hints

def show_diff(expected: str, actual: str, max_lines: int = 20) -> str:
    e = expected.rstrip("\n").split("\n")
    a = actual.rstrip("\n").split("\n")
    # difflib is quadratic-ish on huge outputs (100k lines took 100+s):
    # fall back to a linear first-mismatch window instead.
    if len(e) > 5000 or len(a) > 5000 or len(expected) + len(actual) > 400_000:
        return _show_diff_head(expected, actual, e, a)
    diff = list(difflib.unified_diff(e, a, fromfile="expected", tofile="actual", lineterm=""))
    out = []
    for line in diff[:max_lines]:
        if line.startswith("+") and not line.startswith("+++"):
            out.append(c(visible(line), C.GREEN))
        elif line.startswith("-") and not line.startswith("---"):
            out.append(c(visible(line), C.RED))
        else:
            out.append(c(visible(line), C.GRAY))
    if len(diff) > max_lines:
        out.append(c(f"... ({len(diff)-max_lines} more diff lines)", C.DIM))
    out += _whitespace_hints(expected, actual, e, a)
    return "\n".join(out)

# ---------- resource measurement ----------
def _cpu_children() -> float:
    """CPU seconds (user+sys) ของ child ที่ wait ไปแล้ว ใช้หักลบเป็นราย test ได้"""
    try:
        import resource
        u = resource.getrusage(resource.RUSAGE_CHILDREN)
        return u.ru_utime + u.ru_stime
    except Exception:
        return 0.0

def _sample_rss_mb(pid: int) -> float:
    """RSS ปัจจุบันของ pid (MB). Linux ใช้ VmHWM = peak, ที่เหลือ fallback ไป ps."""
    try:
        with open(f"/proc/{pid}/status", "r", encoding="utf-8") as f:
            for line in f:
                if line.startswith("VmHWM:"):
                    return int(line.split()[1]) / 1024.0
    except Exception:
        pass
    try:
        r = subprocess.run(["ps", "-o", "rss=", "-p", str(pid)],
                           capture_output=True, text=True, timeout=2)
        parts = r.stdout.strip().split()
        if parts:
            return int(parts[0]) / 1024.0
    except Exception:
        pass
    return 0.0

class PeakSampler(threading.Thread):
    """Poll RSS อยู่เบื้องหลัง จับ memory spike สั้นๆ ที่ sample ทีเดียวอาจพลาด"""

    def __init__(self, pid: int, interval: float = SAMPLE_INTERVAL):
        super().__init__(daemon=True)
        self.pid = pid
        self.interval = interval
        self.peak = 0.0
        self._stop_event = threading.Event()

    def run(self) -> None:
        while not self._stop_event.is_set():
            v = _sample_rss_mb(self.pid)
            if v > self.peak:
                self.peak = v
            self._stop_event.wait(self.interval)

    def stop(self) -> float:
        self._stop_event.set()
        self.join(timeout=1.0)
        return self.peak

def _sig_name(rc: int) -> str:
    try:
        return signal.Signals(-rc).name
    except Exception:
        return f"SIG{-rc}"

SIGNAL_HINTS = {
    "SIGSEGV": "Segmentation fault (array out of bounds / stack overflow?)",
    "SIGABRT": "Aborted (assert / uncaught exception / malloc failure?)",
    "SIGFPE": "Floating point exception (divide by zero?)",
    "SIGBUS": "Bus error (bad memory access)",
    "SIGXCPU": "CPU limit exceeded",
    "SIGXFSZ": "File size limit exceeded",
}

OOM_WORDS = ("bad_alloc", "out of memory", "MemoryError",
             "cannot allocate", "std::bad_alloc")

# ---------- memory limit semantics ----------
# Two separate numbers, because "memory limit" means two different things:
#
#  * the *threshold* a submission is judged against — the peak RSS reported to
#    the student. Interpreted runtimes carry real overhead per value (a CPython
#    int costs 28 bytes plus an 8-byte pointer, a JVM reserves its heap), so the
#    same algorithm needs more bytes than in C. Problems declare their limit for
#    a compact language, and a language allowance keeps Python and Java students
#    from being failed for the runtime they were told to use.
#  * the *ceiling* enforced with RLIMIT_AS — the threshold plus headroom for the
#    runtime's virtual address space, which is reserved but never resident.
#    Enforcing the threshold directly on RLIMIT_AS killed correct solutions on
#    Linux while the same code passed on macOS, where RLIMIT_AS is not enforced
#    for mmap (that is what broke CI and production).
LANG_MEM_MULTIPLIER = {
    "python": 2.5, "node": 2.5, "java": 3.0,
    "go": 1.0, "rust": 1.0, "c": 1.0, "cpp": 1.0,
}
LANG_MEM_HEADROOM_MB = {
    "python": 64, "node": 96, "java": 512,
    "go": 0, "rust": 0, "c": 0, "cpp": 0,
}

def mem_limit_mb(declared_mb: int, lang: Optional[str]) -> float:
    """Peak-RSS threshold for this language (MB). Reported and judged."""
    if not declared_mb or declared_mb <= 0:
        return float(declared_mb or 0)
    return declared_mb * LANG_MEM_MULTIPLIER.get(lang or "", 1.0)

def enforced_memory_mb(declared_mb: int, lang: Optional[str]) -> int:
    """RLIMIT_AS value actually applied: threshold + runtime virtual headroom."""
    if not declared_mb or declared_mb <= 0:
        return declared_mb
    return int(mem_limit_mb(declared_mb, lang) + LANG_MEM_HEADROOM_MB.get(lang or "", 0))

# Tolerance for the measured peak RSS (sampling misses the very first frames).
RSS_SLACK_MB = 1.0

def over_memory_limit(declared_mb: int, peak_mb: float, lang: Optional[str] = None) -> bool:
    if not declared_mb or declared_mb <= 0:
        return False
    return peak_mb > mem_limit_mb(declared_mb, lang) + RSS_SLACK_MB

def memory_note(declared_mb: int, lang: Optional[str]) -> str:
    """Human-readable note when a language allowance applies (else empty)."""
    mult = LANG_MEM_MULTIPLIER.get(lang or "", 1.0)
    if mult == 1.0:
        return ""
    return f" (allowance for {lang} x{mult:g} = {mem_limit_mb(declared_mb, lang):.0f}MB)"

# ---------- execution with limits ----------
def build_limits(memory_mb: int, time_limit: float):
    def _fn():
        try:
            import resource
            if memory_mb and memory_mb > 0:
                mem_bytes = memory_mb * 1024 * 1024
                try:
                    resource.setrlimit(resource.RLIMIT_AS, (mem_bytes, mem_bytes))
                except (ValueError, OSError):
                    pass
                try:
                    resource.setrlimit(resource.RLIMIT_DATA, (mem_bytes, mem_bytes))
                except (ValueError, OSError):
                    pass
            try:
                cpu = int(time_limit) + 2
                resource.setrlimit(resource.RLIMIT_CPU, (cpu, cpu))
            except (ValueError, OSError):
                pass
            for lim, val in (
                ("RLIMIT_NPROC", 64),      # กัน fork bomb
                ("RLIMIT_FSIZE", 64 * 1024 * 1024),  # กันเขียนไฟล์ถล่ม disk
                ("RLIMIT_CORE", 0),        # ไม่เอา core dump
                ("RLIMIT_NOFILE", 64),     # กันเปิด fd ถล่ม (pipe+stdlib ใช้ไม่ถึง)
            ):
                try:
                    resource.setrlimit(getattr(resource, lim), (val, val))
                except (AttributeError, ValueError, OSError):
                    pass
        except ImportError:
            pass
        # Sandbox: ตัด network + ลดสิทธิ์เป็น nobody (เฉพาะ Linux ที่รันเป็น
        # root คือ prod Docker). Best-effort: ล้มเหลวตรงไหนก็ใช้ rlimits ต่อ.
        # หมายเหตุ: workdir/binary ต้อง chmod 0755 ฝั่ง parent ก่อน (ดู run_one)
        try:
            if sys.platform.startswith("linux") and os.geteuid() == 0:
                try:  # detached net namespace ก่อน drop root (ต้องใช้ CAP_SYS_ADMIN)
                    import ctypes
                    libc = ctypes.CDLL("libc.so.6", use_errno=True)
                    libc.unshare(0x40000000)  # CLONE_NEWNET
                except Exception:
                    pass
                try:
                    import grp
                    gid = grp.getgrnam("nogroup").gr_gid
                except Exception:
                    gid = 65534
                try:
                    import pwd
                    uid = pwd.getpwnam("nobody").pw_uid
                except Exception:
                    uid = 65534
                try:
                    # สำคัญ: setuid ไม่ล้าง supplementary groups เอง — root มักอยู่
                    # group root ซึ่งยังมีสิทธิ์บน problems/ ผ่าน group bits ได้
                    # ต้อง setgroups([]) ก่อน ไม่เช่นนั้น nobody ยังอ่าน test ได้
                    os.setgroups([])
                except OSError:
                    pass
                try:
                    os.setgid(gid)
                    os.setuid(uid)
                except OSError:
                    pass
        except Exception:
            pass
        try:
            os.setsid()
        except OSError:
            pass
    return _fn


def judge_env() -> dict:
    """Minimal env for untrusted code: compilers/runtimes work, secrets never leak."""
    path = os.environ.get("PATH", "/usr/bin:/bin:/usr/local/bin")
    return {"PATH": path, "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8",
            "HOME": "/tmp", "TMPDIR": "/tmp"}


def _run_cwd(cmd: list[str]) -> str | None:
    """Best-effort isolated working dir: the submission's own temp dir."""
    try:
        if (len(cmd) >= 3 and Path(cmd[0]).name in ("java", "java.exe")
                and cmd[1] == "-cp"):
            return str(Path(cmd[2]))
        if cmd and Path(cmd[0]).stem == "sol":  # our compiled binaries
            return str(Path(cmd[0]).parent)
        for arg in cmd[1:]:
            p = Path(arg)
            if p.suffix.lower() in (".py", ".pyw", ".js") and p.is_file():
                return str(p.resolve().parent)
    except Exception:
        pass
    return None

def run_one(cmd: list[str], stdin_data: str, time_limit: float, memory_mb: int,
            lang: Optional[str] = None) -> dict:
    """Run 1 test ภายใต้ limit.

    Returns dict(stdout, stderr, wall, cpu, peak_mb, returncode, killed, reason).
    reason in {'', 'timeout', 'ole', 'oom', 'sigkill', 'signal:*', 'spawn-fail'}.
    `lang` only affects the enforced memory ceiling (see LANG_MEM_HEADROOM_MB).
    """
    use_limits = (os.name == "posix")
    preexec = build_limits(enforced_memory_mb(memory_mb, lang), time_limit) if use_limits else None
    start = time.perf_counter()
    cpu0 = _cpu_children()
    cwd = _run_cwd(cmd)
    try:  # sandbox child (nobody) ต้อง traverse cwd + exec binary ได้
        if cwd:
            os.chmod(cwd, 0o755)
        if cmd and os.path.isfile(cmd[0]):
            os.chmod(cmd[0], 0o755)
    except OSError:
        pass
    try:
        p = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, preexec_fn=preexec, env=judge_env(), cwd=cwd,
        )
    except OSError as e:
        return {"stdout": "", "stderr": str(e), "wall": time.perf_counter() - start,
                "cpu": 0.0, "peak_mb": 0.0, "returncode": -1, "killed": False,
                "reason": "spawn-fail"}
    sampler = PeakSampler(p.pid)
    sampler.peak = _sample_rss_mb(p.pid)  # sync sample แรกกันพลาด test ที่จบเร็วมาก
    sampler.start()
    try:
        try:
            out, err = p.communicate(input=stdin_data, timeout=time_limit)
        except subprocess.TimeoutExpired:
            try:
                if use_limits:
                    os.killpg(os.getpgid(p.pid), signal.SIGKILL)
                else:
                    p.kill()
            except Exception:
                pass
            try:
                out, err = p.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    p.kill()
                except Exception:
                    pass
                out, err = p.communicate()
            return {"stdout": out or "", "stderr": err or "",
                    "wall": time.perf_counter() - start, "cpu": _cpu_children() - cpu0,
                    "peak_mb": sampler.stop(), "returncode": None, "killed": True,
                    "reason": "timeout"}
        wall = time.perf_counter() - start
        cpu = _cpu_children() - cpu0
        peak = sampler.stop()
        if len((out or "").encode("utf-8", "ignore")) > OUTPUT_LIMIT_BYTES:
            return {"stdout": "", "stderr": err or "", "wall": wall, "cpu": cpu,
                    "peak_mb": peak, "returncode": p.returncode, "killed": False,
                    "reason": "ole"}
        rc = p.returncode
        if rc is not None and rc < 0:
            if -rc == signal.SIGKILL:
                # timeout path return ไปก่อนแล้ว ดังนั้น SIGKILL ตรงนี้ = โดน OOM killer เชือด
                return {"stdout": out or "", "stderr": err or "", "wall": wall, "cpu": cpu,
                        "peak_mb": peak, "returncode": rc, "killed": False, "reason": "sigkill"}
            return {"stdout": out or "", "stderr": err or "", "wall": wall, "cpu": cpu,
                    "peak_mb": peak, "returncode": rc, "killed": False,
                    "reason": f"signal:{_sig_name(rc)}"}
        if err and any(w in err for w in OOM_WORDS):
            return {"stdout": out or "", "stderr": err or "", "wall": wall, "cpu": cpu,
                    "peak_mb": peak, "returncode": rc, "killed": False, "reason": "oom"}
        return {"stdout": out or "", "stderr": err or "", "wall": wall, "cpu": cpu,
                "peak_mb": peak, "returncode": rc, "killed": False, "reason": ""}
    finally:
        sampler.stop()

def judge_test(cmd, tc: TestCase, prob: Problem, strict: bool,
               verbose: bool, lang: Optional[str] = None) -> tuple[str, float, float, float, str, str]:
    """Returns (verdict, wall_s, cpu_s, peak_mb, detail, actual_stdout)."""
    res = run_one(cmd, tc.input, prob.time_limit, prob.memory_limit, lang)
    wall, cpu, mem = res["wall"], res["cpu"], res["peak_mb"]
    checker = "exact" if strict else prob.checker
    reason = res.get("reason", "")

    if reason == "timeout":
        return "TLE", wall, cpu, mem, "", ""
    if reason == "ole":
        return "OLE", wall, cpu, mem, f"stdout > {OUTPUT_LIMIT_BYTES // (1024 * 1024)}MB", ""
    if reason in ("oom", "sigkill"):
        tail = (res["stderr"] or "")[-500:] if verbose else ""
        return "MLE", wall, cpu, mem, tail or "killed (likely OOM)", ""
    if over_memory_limit(prob.memory_limit, mem, lang):
        # The kernel ceiling grants the runtime its virtual headroom, so a
        # program can finish inside it while still exceeding the limit it is
        # judged against: the measured peak RSS decides (and is what we report).
        return ("MLE", wall, cpu, mem,
                f"peak {mem:.1f}MB > limit {mem_limit_mb(prob.memory_limit, lang):.0f}MB"
                + memory_note(prob.memory_limit, lang), "")
    if reason.startswith("signal:"):
        sig = reason.split(":", 1)[1]
        hint = SIGNAL_HINTS.get(sig, sig)
        tail = (res["stderr"] or "")[-2000:]
        detail = hint + (f"\n{tail}" if tail.strip() else "")
        return "RE", wall, cpu, mem, detail, ""
    if reason == "spawn-fail":
        return "RE", wall, cpu, mem, res["stderr"] or "spawn failed", ""
    rc = res["returncode"]
    if rc is not None and rc != 0:
        err = res["stderr"] or ""
        if "MemoryError" in err or "bad_alloc" in err:
            return "MLE", wall, cpu, mem, err[-2000:], ""
        return "RE", wall, cpu, mem, err[-2000:] if err else f"exit code {rc}", ""
    ok = run_checker(checker, tc.expected, res["stdout"], prob.tolerance)
    extra = (res["stderr"] or "")[-1000:] if (verbose and res["stderr"]) else ""
    if ok:
        return "AC", wall, cpu, mem, extra, ""
    return "WA", wall, cpu, mem, extra, res["stdout"]

# ---------- run ----------
def cmd_run(args) -> int:
    global USE_COLOR
    if args.no_color:
        USE_COLOR = False
    prob = load_problem(args.problem)
    if args.time_limit:
        prob.time_limit = args.time_limit
    if args.memory_limit:
        prob.memory_limit = args.memory_limit
    src = Path(args.solution)
    if not src.exists():
        raise SystemExit(f"Solution file not found: {src}")

    print(c(f"Problem: {prob.pid} — {prob.title}", C.CYAN))
    print(f"  tests={len(prob.tests)}  TL={prob.time_limit}s  MEM={prob.memory_limit}MB  "
          f"checker={prob.checker}" + ("  STRICT" if args.strict else ""))
    lang = detect_language(src)
    print("-" * 64)

    with tempfile.TemporaryDirectory(prefix="grader_") as tmp:
        try:
            cmd, disp, warnings = prepare_command(src, Path(tmp))
        except CompileError as e:
            print(c("[CE] Compile Error", C.RED))
            print(str(e)[:4000])
            print(c("Score: 0/100  → 0 passed", C.RED))
            return 1
        print(c(f"build ok: {disp}", C.DIM))
        if warnings:
            print(c("build warnings:", C.YELLOW))
            for ln in warnings.splitlines()[:15]:
                print(c(f"  {ln[:200]}", C.DIM))
        print(c(f"run: {' '.join(cmd)}", C.DIM))
        jobs = max(1, args.jobs or 1)
        if args.stop_on_fail and jobs > 1:
            print(c("(note: --stop-on-fail forces --jobs 1)", C.DIM))
            jobs = 1
        if jobs > 1:
            print(c(f"parallel judging: {jobs} workers", C.DIM))
        print("-" * 64)

        results: list[dict] = []

        def execute(tc: TestCase) -> dict:
            v, wall, cpu, mem, extra, actual = judge_test(cmd, tc, prob, args.strict, args.verbose, lang)
            return {"name": tc.name, "verdict": v, "wall": wall, "cpu": cpu,
                    "mem": mem, "extra": extra, "actual": actual, "tc": tc}

        def report(i: int, r: dict) -> None:
            tc, v = r["tc"], r["verdict"]
            wall, cpu, mem, extra, actual = r["wall"], r["cpu"], r["mem"], r["extra"], r["actual"]
            tag = c(f"[{v}]", verdict_color(v))
            print(f"test {i:02d} ({tc.name}): {tag}  wall={wall:.3f}s cpu={cpu:.3f}s peak={mem:.1f}MB")
            if v == "AC":
                if args.verbose and extra:
                    print(c("  (stderr non-empty but ignored):", C.DIM))
                    print("  " + "\n  ".join(extra.strip().splitlines()[-5:]))
            elif v == "TLE":
                print(c(f"  → Time Limit Exceeded (wall {wall:.2f}s > {prob.time_limit}s, cpu {cpu:.2f}s). "
                        "Hint: O(n^2) won't survive the hidden max test.", C.YELLOW))
            elif v == "MLE":
                print(c("  → Memory Limit Exceeded (OOM / killed).", C.MAGENTA))
                if extra:
                    print(c("  " + extra.strip().splitlines()[-1][:200], C.DIM))
            elif v == "OLE":
                print(c(f"  → Output Limit Exceeded ({extra}). Print loop?", C.YELLOW))
            elif v == "RE":
                print(c("  → Runtime Error:", C.RED))
                lines = extra.strip().splitlines() if extra.strip() else ["(no stderr)"]
                print("  " + lines[0][:300])
                if args.verbose and len(lines) > 1:
                    print(c("  ---- detail (tail) ----", C.DIM))
                    print("  " + "\n  ".join(lines[-15:]))
            elif v == "WA":
                print(c("  → Wrong Answer. diff (·=space, →=tab):", C.RED))
                print("  " + show_diff(tc.expected, actual).replace("\n", "\n  "))
                if args.verbose:
                    print(c("  ---- input (head) ----", C.DIM))
                    print("  " + tc.input[:2000].replace("\n", "\n  "))
                    print(c("  ---- expected (head) ----", C.DIM))
                    print("  " + tc.expected[:500].replace("\n", "\n  "))
                    print(c("  ---- actual (head) ----", C.DIM))
                    print("  " + actual[:500].replace("\n", "\n  "))
                    if extra:
                        print(c("  ---- stderr ----", C.YELLOW))
                        print("  " + extra[:1000].replace("\n", "\n  "))

        if jobs == 1:
            stop = False
            for i, tc in enumerate(prob.tests, 1):
                if stop:
                    results.append({"name": tc.name, "verdict": "SKIP", "wall": 0.0,
                                    "cpu": 0.0, "mem": 0.0, "extra": "", "actual": "", "tc": tc})
                    continue
                r = execute(tc)
                results.append(r)
                report(i, r)
                if r["verdict"] != "AC" and args.stop_on_fail:
                    print(c("  (stopping on first failure: --stop-on-fail)", C.DIM))
                    stop = True
        else:
            with concurrent.futures.ThreadPoolExecutor(max_workers=jobs) as ex:
                ordered = list(ex.map(execute, prob.tests))
            for i, r in enumerate(ordered, 1):
                results.append(r)
                report(i, r)

        passed = sum(1 for r in results if r["verdict"] == "AC")
        total = len(prob.tests)
        score = 100 * passed // total if total else 0
        print("-" * 64)
        counts: dict[str, int] = {}
        for r in results:
            counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
        summ = "  ".join(f"{k}:{n}" for k, n in sorted(counts.items()))
        judged = [r for r in results if r["verdict"] != "SKIP"]
        stat = ""
        if judged:
            tot_wall = sum(r["wall"] for r in judged)
            slowest = max(judged, key=lambda r: r["wall"])
            stat = f"  total_wall={tot_wall:.2f}s  slowest={slowest['name']} ({slowest['wall']:.3f}s)"
        if passed == total:
            print(c(f"ACCEPTED  {passed}/{total}  score={score}/100  [{summ}]{stat}", C.GREEN + C.BOLD))
            print(c("Rank: S — brutal mode cleared", C.GREEN))
            rc = 0
        else:
            print(c(f"REJECTED  {passed}/{total}  score={score}/100  [{summ}]{stat}", C.RED + C.BOLD))
            ratio = passed / total if total else 0
            rank = "F" if ratio < 0.4 else "C" if ratio < 0.7 else "B"
            print(c(f"Rank: {rank} — fix it and resubmit", C.YELLOW))
            rc = 1
        if args.json:
            payload = {
                "problem": prob.pid, "title": prob.title,
                "solution": str(src), "command": cmd,
                "limits": {"time_s": prob.time_limit, "memory_mb": prob.memory_limit},
                "checker": ("exact" if args.strict else prob.checker),
                "results": [{"test": r["name"], "verdict": r["verdict"],
                             "wall_s": round(r["wall"], 4), "cpu_s": round(r["cpu"], 4),
                             "peak_mb": round(r["mem"], 2)} for r in results],
                "passed": passed, "total": total, "score": score,
                "accepted": passed == total,
            }
            Path(args.json).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            print(c(f"JSON report: {args.json}", C.DIM))
        return rc

def cmd_info(args) -> int:
    prob = load_problem(args.problem)
    print(c(f"{prob.pid} — {prob.title}", C.BOLD))
    print(f"TL={prob.time_limit}s MEM={prob.memory_limit}MB checker={prob.checker} tests={len(prob.tests)}")
    print()
    print(prob.description[:6000])
    return 0

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Brutal CP grader (stdlib only)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list problems")
    pi = sub.add_parser("info", help="show problem statement")
    pi.add_argument("problem")
    pr = sub.add_parser("run", help="judge a solution")
    pr.add_argument("problem")
    pr.add_argument("solution")
    pr.add_argument("--time-limit", type=float, default=None)
    pr.add_argument("--memory-limit", type=int, default=None)
    pr.add_argument("--strict", action="store_true", help="byte-exact checker (whitespace nazi mode)")
    pr.add_argument("--stop-on-fail", action="store_true")
    pr.add_argument("--verbose", "-v", action="store_true")
    pr.add_argument("--no-color", action="store_true")
    pr.add_argument("--jobs", type=int, default=1, help="parallel test workers (default 1 = sequential)")
    pr.add_argument("--json", default=None, metavar="FILE", help="write machine-readable report to FILE")
    pr.set_defaults(func=cmd_run)
    args = ap.parse_args(argv)
    if args.cmd == "list":
        list_problems()
        return 0
    if args.cmd == "info":
        return cmd_info(args)
    return cmd_run(args)

if __name__ == "__main__":
    raise SystemExit(main())
