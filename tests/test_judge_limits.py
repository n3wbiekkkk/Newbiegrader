# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Memory-limit semantics of the judge.

RLIMIT_AS limits *virtual* address space, not resident memory, and it is enforced
on Linux but not on macOS for mmap. Enforcing a problem's declared limit directly
on it therefore killed correct Python solutions in CI and in production while the
same code passed on a developer's Mac.

The judge now keeps two numbers per submission:

  * a peak-RSS threshold — declared limit x language allowance — which is what the
    verdict uses and what the student is shown;
  * an RLIMIT_AS ceiling above that threshold, which only exists to stop a runaway
    child from taking the host down.

These tests pin that behaviour down: a correct Python program must not be failed
for the interpreter it runs on, and a program that really exceeds the allowance
must still be MLE.
"""

import pathlib
import sys
import tempfile
import unittest
from dataclasses import replace

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
if str(ROOT / "tests") not in sys.path:
    sys.path.insert(0, str(ROOT / "tests"))

import grader

# No local problem set in the repository (problem data lives in Supabase), so
# these regression tests only run where problems/ exists; CI reports a skip.
if not grader.PROBLEMS_DIR.is_dir():
    raise unittest.SkipTest("no local problems/ (source of truth is Supabase)")


def judge_python(source, pid="hanoi", limit_mb=None):
    """Judge one Python program against the first test of `pid`."""
    prob = grader.load_problem(pid)
    if limit_mb is not None:
        prob = replace(prob, memory_limit=limit_mb)
    workdir = pathlib.Path(tempfile.mkdtemp(prefix="mltest_"))
    src = workdir / "solution.py"
    src.write_text(source, encoding="utf-8")
    cmd, _disp, _warnings = grader.prepare_command(src, workdir)
    return grader.judge_test(cmd, prob.tests[0], prob, False, False, "python")


class MemoryLimitPolicy(unittest.TestCase):
    def test_compiled_languages_keep_the_declared_limit(self):
        self.assertEqual(grader.mem_limit_mb(64, "cpp"), 64)
        self.assertEqual(grader.mem_limit_mb(64, "c"), 64)
        self.assertEqual(grader.enforced_memory_mb(64, "cpp"), 64)

    def test_interpreted_languages_get_an_allowance(self):
        for lang in ("python", "node", "java"):
            with self.subTest(lang=lang):
                self.assertGreater(grader.mem_limit_mb(64, lang), 64)

    def test_kernel_ceiling_leaves_room_above_the_threshold(self):
        # the interpreter reserves virtual space it never touches, so the ceiling
        # must sit above the threshold or Linux kills correct submissions
        self.assertGreater(grader.enforced_memory_mb(64, "python"),
                           grader.mem_limit_mb(64, "python"))

    def test_correct_python_solution_is_ac(self):
        """The regression that failed CI: a correct Python program must pass."""
        prob = grader.load_problem("hanoi")
        src = ROOT / "examples" / "hanoi_ref.py"
        cmd, _disp, _warnings = grader.prepare_command(src, pathlib.Path(tempfile.mkdtemp()))
        verdicts = [grader.judge_test(cmd, tc, prob, False, False, "python")[0]
                    for tc in prob.tests]
        self.assertEqual(set(verdicts), {"AC"}, f"reference solution verdicts: {verdicts}")

    @unittest.skipUnless(sys.platform.startswith("linux"),
                         "RLIMIT_AS kernel ceiling is enforced on Linux, not macOS mmap")
    def test_python_over_the_kernel_ceiling_is_mle(self):
        """Far over the allowance: the RLIMIT_AS ceiling stops it (SIGKILL)."""
        declared = 64
        way_over_mb = int(grader.enforced_memory_mb(declared, "python") * 2)
        verdict, _wall, _cpu, _peak, _detail, _actual = judge_python(
            f"import sys\nx = bytearray({way_over_mb} * 1024 * 1024)\nsys.stdin.read()\n",
            limit_mb=declared)
        self.assertEqual(verdict, "MLE")

    def test_rss_measurement_decides_when_the_process_survives(self):
        """Inside the ceiling but over the threshold: the verdict comes from the
        measured peak RSS, which is also the number reported to the student.

        The sampler polls, so the test holds the allocation for a moment — an
        allocation that lives for less than one sampling interval can be missed.
        """
        declared = 32
        threshold = grader.mem_limit_mb(declared, "python")
        ceiling = grader.enforced_memory_mb(declared, "python")
        alloc_mb = int(threshold + 10)
        self.assertLess(alloc_mb, ceiling, "test setup: allocation must fit the ceiling")
        verdict, _wall, _cpu, peak, detail, _actual = judge_python(
            "import sys, time\n"
            f"x = bytearray({alloc_mb} * 1024 * 1024)\n"
            "sys.stdin.read()\n"
            "time.sleep(0.3)\n",
            limit_mb=declared)
        self.assertEqual(verdict, "MLE", detail)
        self.assertGreater(peak, threshold)

    def test_tiny_python_program_under_a_small_limit_is_not_mle(self):
        """A few MB of work on a 32MB problem must be judged on its answer."""
        verdict, _wall, _cpu, _peak, _detail, _actual = judge_python(
            "import sys\nsys.stdin.read()\nprint('0')\n", limit_mb=32)
        self.assertIn(verdict, ("AC", "WA"), f"unexpected verdict: {verdict}")


if __name__ == "__main__":
    unittest.main()
