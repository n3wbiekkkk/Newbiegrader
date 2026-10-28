"""Browsing performance/security regressions; synthetic data, no live services."""
from critical_helpers import patch_server_state
from collections import OrderedDict
from contextlib import ExitStack
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import grader
import problem_store
from critical_helpers import synthetic_problem, test_server
from fake_supabase import FakeSupabase

server = test_server()
PDF = b"%PDF-1.4\nsynthetic statement\n%%EOF\n"


class ProblemLoading(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.problem = synthetic_problem()
        self.slug = self.problem.pid
        self.fake = FakeSupabase()
        samples, manifest = problem_store.manifest_for_problem(self.problem)
        self.row = {
            "slug": self.slug, "no": 99, "title": "Synthetic statement",
            "time_limit": self.problem.time_limit, "memory_limit": self.problem.memory_limit,
            "checker": self.problem.checker, "tolerance": self.problem.tolerance,
            "samples": self.problem.samples, "samples_data": samples,
            "hidden_tests": manifest, "tests_count": len(self.problem.tests),
            "tests_hash": grader.tests_hash(self.problem), "is_published": True,
            "statement_pdf_path": f"{self.slug}/statement.pdf", "updated_at": "v1",
        }
        self.fake.table("problems").insert(self.row).execute()
        bucket = self.fake.storage.from_("judge-assets")
        bucket.upload(self.row["statement_pdf_path"], PDF)
        for tc in self.problem.tests:
            bucket.upload(f"{self.slug}/tests/{tc.name}.in", tc.input.encode())
            bucket.upload(f"{self.slug}/tests/{tc.name}.out", tc.expected.encode())
        for name in ("_PDF_CACHE", "_PROBLEMS_CACHE"):
            self.stack.enter_context(patch.object(problem_store, name, OrderedDict()))
        meta, hashes, extra = problem_store.load_snapshot(client=self.fake)
        for name, value in {
            "PROBLEM_SOURCE": "supabase", "_sb": self.fake, "PROBLEMS": meta,
            "PROBLEMS_BY_NO": {99: self.slug}, "_TESTS_HASH_CACHE": hashes,
            "_PROBLEM_EXTRA": extra, "_problems_refresh_at": time.monotonic(),
            "_contest_pid_cache": {"at": 0.0, "all": set(), "hide": set()},
        }.items():
            self.stack.enter_context(patch_server_state(server, name, value))
        self.download = self.stack.enter_context(
            patch.object(problem_store, "_download", wraps=problem_store._download))
        app = FastAPI()

        @app.middleware("http")
        async def anonymous(request: Request, call_next):
            request.scope["session"] = {}
            return await call_next(request)

        app.get("/api/problems/{pid}/pdf")(server.problem_pdf)
        self.client = self.stack.enter_context(TestClient(app))
        self.url = f"/api/problems/{self.slug}/pdf"

    def test_pdf_downloads_only_statement_and_numeric_route_uses_same_cache(self):
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, PDF)
        self.assertEqual(self.download.call_count, 1)
        self.assertEqual(self.download.call_args.args[2], self.row["statement_pdf_path"])
        self.assertEqual(len(server._catalog._problems[self.slug].tests), len(self.problem.samples))
        self.assertEqual(self.client.get("/api/problems/99/pdf").content, PDF)
        self.assertEqual(self.download.call_count, 1)

    def test_conditional_get_revalidates_privately_without_storage_download(self):
        first = self.client.get(self.url)
        etag = first.headers["etag"]
        self.assertEqual(first.headers["cache-control"], "private, max-age=600")
        self.assertIn("Cookie", first.headers["vary"])
        for value in (etag, "W/" + etag, '"old", ' + etag, "*"):
            with self.subTest(value=value):
                response = self.client.get(self.url, headers={"If-None-Match": value})
                self.assertEqual(response.status_code, 304)
                self.assertEqual(response.content, b"")
        self.assertEqual(self.download.call_count, 1)

    def test_unpublished_and_contest_hidden_reject_before_storage_or_304(self):
        first = self.client.get(self.url)
        for policy in ("unpublished", "contest"):
            with self.subTest(policy=policy):
                if policy == "unpublished":
                    server._catalog._problems[self.slug].is_published = False
                else:
                    server._catalog._problems[self.slug].is_published = True
                    self.fake.tables["contests"] = [{
                        "id": "synthetic-contest", "problems": [self.slug],
                        "hide_from_tasks": True, "starts_at": "2999-01-01T00:00:00+00:00",
                        "ends_at": "2999-01-02T00:00:00+00:00"}]
                    server._contest_pid_cache["at"] = 0.0
                self.download.reset_mock()
                response = self.client.get(self.url, headers={"If-None-Match": first.headers["etag"]})
                self.assertEqual(response.status_code, 404)
                self.download.assert_not_called()

    def refresh(self):
        self.assertTrue(server._catalog.refresh())

    def test_statement_update_invalidates_pdf_without_changing_tests(self):
        first = self.client.get(self.url)
        new_pdf = PDF.replace(b"statement", b"updated statement")
        self.fake.storage.from_("judge-assets").update(self.row["statement_pdf_path"], new_pdf)
        self.fake.table("problems").update({"updated_at": "v2"}).eq("slug", self.slug).execute()
        self.refresh()
        response = self.client.get(self.url, headers={"If-None-Match": first.headers["etag"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, new_pdf)
        self.assertNotEqual(response.headers["etag"], first.headers["etag"])
        self.assertEqual(self.download.call_count, 2)
        self.assertEqual(server._catalog._hashes[self.slug], self.row["tests_hash"])

    def test_path_change_and_deleted_row_invalidate_pdf_only_cache(self):
        self.client.get(self.url)
        new_path = f"{self.slug}/statement-v2.pdf"
        self.fake.storage.from_("judge-assets").upload(new_path, PDF)
        self.fake.table("problems").update({"statement_pdf_path": new_path}).eq("slug", self.slug).execute()
        self.refresh()
        self.assertNotIn(self.slug, problem_store._PDF_CACHE)
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.download.call_args.args[2], new_path)
        self.fake.table("problems").delete().eq("slug", self.slug).execute()
        self.refresh()
        self.assertNotIn(self.slug, problem_store._PDF_CACHE)
        self.assertEqual(self.client.get(self.url).status_code, 404)

    def test_unchanged_metadata_keeps_pdf_and_judging_still_loads_all_tests(self):
        self.client.get(self.url)
        self.refresh()
        self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.download.call_count, 1)
        full = server._problem_or_404(self.slug)
        self.assertEqual(len(full.tests), len(self.problem.tests))
        self.assertEqual(grader.tests_hash(full), self.row["tests_hash"])
        self.assertGreater(self.download.call_count, 1)

    def test_pdf_cache_ttl_bounds_storage_only_changes(self):
        self.client.get(self.url)
        with patch.object(problem_store, "PDF_CACHE_TTL_S", -1):
            self.assertEqual(self.client.get(self.url).status_code, 200)
        self.assertEqual(self.download.call_count, 2)


if __name__ == "__main__":
    unittest.main()
