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
    suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"),
                                              pattern="test_critical_*.py")
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
