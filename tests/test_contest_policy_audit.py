"""Synthetic contest-policy failures, frozen feeds and complete pagination."""
from contextlib import ExitStack
import asyncio
import datetime as dt
from unittest.mock import patch
import unittest

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient
from critical_helpers import synthetic_problem, test_server
from fake_supabase import FakeSupabase

server = test_server()


class ContestPolicyAudit(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.fake = FakeSupabase()
        self.prob = synthetic_problem()
        self.now = dt.datetime.now(dt.timezone.utc)
        self.contest = {"id": "synthetic-audit", "title": "Synthetic", "problems": [self.prob.pid],
            "starts_at": (self.now - dt.timedelta(hours=1)).isoformat(),
            "ends_at": (self.now + dt.timedelta(minutes=5)).isoformat(),
            "freeze_minutes": 20, "hide_from_tasks": False, "show_samples": False}
        for key, value in {"_sb": self.fake, "PROBLEMS": {self.prob.pid: self.prob},
                           "_reg_table_ok": {"value": True},
                           "_contest_pid_cache": {"at": 0., "all": set(), "hide": set()}}.items():
            self.stack.enter_context(patch.object(server, key, value))

    def test_policy_outage_does_not_open_problem_or_sample_access(self):
        with patch.object(server, "_cached_contest_rows", side_effect=RuntimeError("synthetic outage")):
            for lookup in (lambda: server._visible_to(self.prob.pid, ""), server._live_hidden_pids):
                with self.subTest(lookup=lookup):
                    with self.assertRaises(HTTPException) as exc:
                        lookup()
                    self.assertEqual(exc.exception.status_code, 503)

    def test_missing_registration_table_never_disables_the_gate(self):
        self.fake.missing.add("contest_registrations")
        for _ in range(2):
            self.assertFalse(server._is_registered(self.contest["id"], "synthetic@example.invalid"))

    def test_public_history_does_not_reveal_frozen_contest_scores(self):
        self.fake.tables["contests"] = [self.contest]
        self.fake.tables["submissions"] = [self.submission("frozen", 100)]
        app = FastAPI()

        @app.middleware("http")
        async def anonymous(request: Request, call_next):
            request.scope["session"] = {}
            return await call_next(request)

        app.get("/api/history")(server.history)
        with TestClient(app) as client:
            rows = client.get("/api/history").json()["submissions"]
        self.assertEqual(rows, [])

    def test_scoreboard_includes_results_after_the_old_5000_row_limit(self):
        self.fake.tables["submissions"] = [self.submission(str(i), 0) for i in range(5000)]
        self.fake.tables["submissions"].append(self.submission("last", 100, offset=1))
        board = server._contest_scoreboard(self.contest, live=True)
        self.assertEqual(board[0]["points"], 100)

    def test_contest_does_not_publish_unpublished_problem_metadata_or_scores(self):
        self.prob.is_published = False
        self.fake.tables["contests"] = [self.contest]
        self.fake.tables["submissions"] = [self.submission("private", 100)]
        request = Request({"type": "http", "session": {}})
        with patch.object(server, "_ensure_problems_fresh"), \
                patch.object(server, "_registration_counts", return_value={}):
            public = server._contest_public(self.contest)
            detail = server.contest_detail(request, self.contest["id"])
        self.assertEqual(public["problems"], [])
        self.assertEqual(detail["problem_details"], [])
        self.assertEqual(detail["scoreboard"], [])

    def test_public_stats_filters_private_and_unknown_problem_ids_even_on_cache_hit(self):
        cached = {"configured": True, "stats": {
            self.prob.pid: {"subs": 7}, "synthetic-deleted": {"subs": 5}}}
        self.prob.is_published = False
        with patch.object(server, "_acached", return_value=cached), \
                patch.object(server, "_ensure_problems_fresh"), \
                patch.object(server, "_contest_policy_rows", return_value=[]):
            self.assertEqual(asyncio.run(server.stats())["stats"], {})
            self.prob.is_published = True
            self.assertEqual(asyncio.run(server.stats())["stats"], {self.prob.pid: {"subs": 7}})

    def submission(self, sid, score, offset=0):
        return {"id": sid, "user_email": "synthetic@example.invalid", "name": "Synthetic",
                "problem": self.prob.pid, "score": score, "accepted": score == 100,
                "created_at": (self.now + dt.timedelta(seconds=offset)).isoformat(),
                "contest_id": self.contest["id"]}
