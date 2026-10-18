#!/usr/bin/env python3
"""Run synthetic P0 tests; any skip or empty discovery fails this CI gate."""
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parent.parent


class CriticalResult(unittest.TextTestResult):
    def addSkip(self, test, reason):
        self.stream.writeln(f"[CRITICAL-SKIP] {test}: {reason}")
        super().addSkip(test, reason)


def main():
    sys.path.insert(0, str(ROOT))
    # Queue ownership and process cleanup must also run without the private
    # problem set; do not let a module-level skip hide these regressions in CI.
    suite = unittest.TestSuite()
    for pattern in ("test_critical_*.py", "test_judge_runner.py", "test_queue_admission.py",
                    "test_audit_integrity.py", "test_contest_policy_audit.py",
                    "test_request_boundaries.py", "test_auth_retention_audit.py"):
        suite.addTests(unittest.defaultTestLoader.discover(str(ROOT / "tests"),
                                                        pattern=pattern))
    result = unittest.TextTestRunner(verbosity=2, resultclass=CriticalResult).run(suite)
    if result.skipped or result.testsRun == 0:
        print(f"[CRITICAL-FAIL] ran={result.testsRun}, skipped={len(result.skipped)}; "
              "critical tests must run without skips on Linux/root", file=sys.stderr)
        return 1
    if not result.wasSuccessful():
        return 1
    print(f"[CRITICAL-PASS] {result.testsRun} tests, 0 skips")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
