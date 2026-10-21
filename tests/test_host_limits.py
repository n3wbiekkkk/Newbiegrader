# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Unit tests for the container-capability detection that drives judge capacity.

Prod runs on a fractional vCPU / small-RAM container, so grading concurrency and
the per-test memory cap are derived from cgroup files. These tests feed fake
cgroup layouts (via GRADER_CGROUP_ROOT) and assert the numbers the server would
derive for a 0.5 CPU / 512 MB box.

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import grader  # noqa: E402


class CgroupDetection(unittest.TestCase):
    def setUp(self):
        self._old = os.environ.get("GRADER_CGROUP_ROOT")
        self.tmp = tempfile.TemporaryDirectory(prefix="ng_cgroup_")
        self.root = Path(self.tmp.name)
        os.environ["GRADER_CGROUP_ROOT"] = str(self.root)

    def tearDown(self):
        if self._old is None:
            os.environ.pop("GRADER_CGROUP_ROOT", None)
        else:
            os.environ["GRADER_CGROUP_ROOT"] = self._old
        self.tmp.cleanup()

    def write(self, rel: str, value: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    # ---- cgroup v2 ----
    def test_v2_half_core_half_gig(self):
        self.write("cpu.max", "50000 100000")          # 0.5 vCPU
        self.write("memory.max", str(512 * 1024 * 1024))
        self.assertEqual(grader.cpu_quota(), 0.5)
        self.assertEqual(grader.ram_limit_mb(), 512)

    def test_v2_two_cores_four_gig(self):
        self.write("cpu.max", "200000 100000")
        self.write("memory.max", str(4 * 1024 * 1024 * 1024))
        self.assertEqual(grader.cpu_quota(), 2.0)
        self.assertEqual(grader.ram_limit_mb(), 4096)

    def test_v2_unlimited_falls_back_to_host(self):
        self.write("cpu.max", "max 100000")
        self.write("memory.max", "max")
        self.assertEqual(grader.cpu_quota(), float(os.cpu_count() or 1))
        self.assertGreater(grader.ram_limit_mb(), 64)

    def test_v2_quarter_core(self):
        self.write("cpu.max", "25000 100000")
        self.write("memory.max", str(256 * 1024 * 1024))
        self.assertEqual(grader.cpu_quota(), 0.25)
        self.assertEqual(grader.ram_limit_mb(), 256)

    # ---- cgroup v1 ----
    def test_v1_legacy_files(self):
        self.write("cpu/cpu.cfs_quota_us", "50000")
        self.write("cpu/cpu.cfs_period_us", "100000")
        self.assertEqual(grader.cpu_quota(), 0.5)
        # "unlimited" in v1 is a near-2^63 sentinel: must not be taken literally
        self.write("memory/memory.limit_in_bytes", str(1 << 62))
        self.assertGreater(grader.ram_limit_mb(), 64)

    def test_v1_memory_limit(self):
        self.write("memory/memory.limit_in_bytes", str(512 * 1024 * 1024))
        self.assertEqual(grader.ram_limit_mb(), 512)

    # ---- derived server settings ----
    def test_server_settings_for_a_half_core_box(self):
        self.write("cpu.max", "50000 100000")
        self.write("memory.max", str(512 * 1024 * 1024))
        self.assertEqual(grader.cpu_quota(), 0.5)      # precondition for the math below
        from critical_helpers import test_server
        server = test_server()
        with patch.dict(os.environ, {"GRADER_MEMORY_CAP_MB": "0", "GRADER_JUDGE_WORKERS": "0"}):
            capacity = server._derive_capacity(grader.cpu_quota(), grader.ram_limit_mb())
        self.assertEqual(capacity["workers"], 1)
        self.assertEqual(capacity["judge_jobs"], 1)
        self.assertEqual(capacity["memory_cap_mb"], 85)
        self.assertLessEqual(capacity["reserve_mb"] + capacity["per_job_mb"], 512)

    def test_missing_cgroup_files_do_not_crash(self):
        self.assertEqual(grader.ram_limit_mb() > 0, True)
        self.assertGreater(grader.cpu_quota(), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
