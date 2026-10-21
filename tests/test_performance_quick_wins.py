# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Regression tests for the low-risk performance quick wins."""
from contextlib import ExitStack
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi import Request, Response

from critical_helpers import synthetic_problem, test_server
from fake_supabase import FakeSupabase
import grader
import problem_store

server = test_server()


class PerformanceQuickWins(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.prob = synthetic_problem()

    def test_lean_snapshot_omits_statement_markdown(self):
        seen = {}

        def fake_fetch(_client, columns="*"):
            seen["columns"] = columns
            return []

        with patch.object(problem_store, "_fetch_all_rows", side_effect=fake_fetch):
            problem_store.load_snapshot(client=object(), lean=True)
        self.assertNotIn("statement_md", seen["columns"])
        self.assertIn("tests_hash", seen["columns"])
        self.assertIn("hidden_tests", seen["columns"])

    def test_detail_response_has_private_cache_and_pdf_flag(self):
        request = Request({"type": "http", "session": {"user": {"email": "u@example.com"}}})
        response = Response()
        with patch.object(server, "PROBLEM_SOURCE", "supabase"), \
                patch.object(server, "_ensure_problems_fresh"), \
                patch.object(server, "_meta_or_404", return_value=self.prob), \
                patch.object(server, "_visible_to", return_value=True), \
                patch.object(server, "_is_admin", return_value=False), \
                patch.object(server, "_hidden_pids", return_value=set()), \
                patch.object(server, "_contest_problem_sets", return_value=(set(), set())), \
                patch.object(server, "_tests_hash", return_value="hash"), \
                patch.object(server, "_problem_total", return_value=3), \
                patch.object(server, "_PROBLEM_EXTRA",
                             {self.prob.pid: {"has_pdf": True}}):
            body = server.problem_detail(request, self.prob.pid, response)
        self.assertTrue(body["has_pdf"])
        self.assertEqual(response.headers["cache-control"], "private, max-age=60")
        self.assertEqual(response.headers["vary"], "Cookie")

    def test_browse_cache_control_shortens_hidden_and_admin(self):
        with patch.object(server, "_is_admin", return_value=False), \
                patch.object(server, "_hidden_pids", return_value=set()):
            self.assertEqual(server._browse_cache_control("p", "u", 600),
                             "private, max-age=600")
        with patch.object(server, "_is_admin", return_value=False), \
                patch.object(server, "_hidden_pids", return_value={"p"}):
            self.assertEqual(server._browse_cache_control("p", "u", 600),
                             "private, max-age=30")
        with patch.object(server, "_is_admin", return_value=True), \
                patch.object(server, "_hidden_pids", return_value=set()):
            self.assertEqual(server._browse_cache_control("p", "u", 60),
                             "private, max-age=30")

    def test_lazy_statement_fetch_caches_into_problem(self):
        self.prob.description = ""
        with patch.object(server, "PROBLEM_SOURCE", "supabase"), \
                patch.object(server, "_sb", object()), \
                patch.object(problem_store, "load_statement_md",
                             return_value="lazy statement") as lookup:
            self.assertEqual(server._problem_description(self.prob), "lazy statement")
        self.assertEqual(self.prob.description, "lazy statement")
        lookup.assert_called_once()

    def test_catalog_refresh_returns_before_supabase_query(self):
        gate = threading.Event()
        started = threading.Event()
        lock = threading.Lock()

        def slow_load(client=None, *, lean=False):
            self.assertTrue(lean)
            started.set()
            gate.wait(2.0)
            return {}, {}, {}

        with patch.object(server, "PROBLEM_SOURCE", "supabase"), \
                patch.object(server, "_sb", object()), \
                patch.object(server, "_problem_refresh_lock", lock), \
                patch.object(server, "_problems_refresh_at", 0.0), \
                patch.object(problem_store, "cache_ttl_s", return_value=0.0), \
                patch.object(problem_store, "load_snapshot", side_effect=slow_load), \
                patch.object(problem_store, "invalidate_stale", return_value=[]), \
                patch.object(server, "_apply_problem_snapshot"):
            start = time.monotonic()
            server._ensure_problems_fresh()
            elapsed = time.monotonic() - start
            self.assertLess(elapsed, 0.2)
            self.assertTrue(started.wait(1.0))
            gate.set()
            for _ in range(100):
                if not lock.locked():
                    break
                time.sleep(0.01)
            self.assertFalse(lock.locked())

    def test_profile_display_name_is_cached_briefly(self):
        fake = FakeSupabase()
        fake.tables["profiles"] = [{"user_email": "a@example.com",
                                   "display_name": "Alice"}]
        with patch.object(server, "_sb", fake), \
                patch.object(server, "_PROFILE_NAME_CACHE", {}), \
                patch.object(fake, "table", wraps=fake.table) as table:
            self.assertEqual(server._profile_display_name("a@example.com", "fallback"),
                             "Alice")
            self.assertEqual(server._profile_display_name("a@example.com", "fallback"),
                             "Alice")
        self.assertEqual(table.call_count, 1)

    def test_cxx_pch_flag_only_when_header_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "pch"
            (root / "bits").mkdir(parents=True)
            gch = root / "bits" / "stdc++.h.gch"
            gch.write_bytes(b"pch")
            with patch.dict(os.environ, {"GRADER_CXX_PCH_DIR": str(root)}):
                self.assertEqual(grader._cxx_pch_flags(), ["-I", str(root)])
            gch.unlink()
            with patch.dict(os.environ, {"GRADER_CXX_PCH_DIR": str(root)}):
                self.assertEqual(grader._cxx_pch_flags(), [])


if __name__ == "__main__":
    unittest.main()
