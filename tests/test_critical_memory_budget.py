# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Synthetic S04 capacity arithmetic; no private problem set or live services."""
import os
import unittest
from unittest.mock import patch

import grader
from critical_helpers import test_server

server = test_server()


class CriticalMemoryBudget(unittest.TestCase):
    def capacity(self, cpu, ram, cap='0', workers='0'):
        with patch.dict(os.environ, {'GRADER_MEMORY_CAP_MB': cap,
                                   'GRADER_JUDGE_WORKERS': workers}):
            return server._derive_capacity(cpu, ram)

    def assert_budget(self, capacity, ram):
        runtime = max(grader.enforced_memory_mb(capacity['memory_cap_mb'], lang)
                      for lang in server.LANGS)
        compiler = max(256, capacity['memory_cap_mb'])
        self.assertGreaterEqual(capacity['per_job_mb'], max(runtime, compiler) + 64)
        self.assertLessEqual(capacity['reserve_mb'] + capacity['workers'] * capacity['per_job_mb'], ram)

    def test_critical_half_gig_budget_includes_python_allowance_and_virtual_headroom(self):
        capacity = self.capacity(.5, 512)
        self.assertEqual(capacity['workers'], 1)
        self.assertEqual(capacity['judge_jobs'], 1)
        self.assert_budget(capacity, 512)

    def test_critical_capacity_overrides_cannot_overbook_runtime_ceilings(self):
        for ram in (256, 384, 512, 1024, 4096, 16384):
            for cap in ('0', '64', '256', '100000'):
                with self.subTest(ram=ram, cap=cap):
                    capacity = self.capacity(8, ram, cap, '100')
                    self.assert_budget(capacity, ram)
                    self.assertLessEqual(capacity['workers'], 8)

    def test_critical_insufficient_ram_refuses_a_worker_instead_of_forcing_one(self):
        for ram in (128, 256, 384):
            self.assertEqual(self.capacity(.5, ram)['workers'], 0)

    def test_critical_budget_tracks_enabled_languages(self):
        with patch.dict(server.LANGS, {'java': {'ext': '.java'}}):
            capacity = self.capacity(2, 1024)
            self.assert_budget(capacity, 1024)
