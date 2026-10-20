"""Synthetic contest-policy failures, frozen feeds and complete pagination."""
from contextlib import ExitStack
import asyncio
import datetime as dt
import json
import time
from unittest.mock import patch
import unittest

from fastapi import FastAPI, HTTPException, Request, Response
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
        with patch.object(server, "_cached_contest_rows", side_effect=RuntimeError("synthetic outage")), \
                patch.object(server, "_all_contest_rows", side_effect=RuntimeError("synthetic outage")):
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

    def request_with(self, email, body):
        payload = json.dumps(body).encode()

        async def receive():
            return {"type": "http.request", "body": payload, "more_body": False}

        return Request({"type": "http", "session": {"user": {"email": email}}}, receive)

    def result_with_samples_and_hidden(self):
        return {"results": [
            {"test": "01", "verdict": "WA", "public": True, "input": "SAMPLE-IN",
             "expected": "SAMPLE-OUT", "actual": "WRONG", "diff": "sample-diff"},
            {"test": "1001", "verdict": "WA", "public": False, "input": "HIDDEN-IN",
             "expected": "HIDDEN-OUT", "actual": "WRONG", "diff": "hidden-diff"}]}

    def test_sample_route_does_not_trust_a_stale_contest_cache(self):
        """A different API process may have cached the old policy.

        show_samples=false is a live disclosure rule. Serving sample bytes from
        the 20s cached contest row would keep them public after an admin turns
        samples off (or after another process performs the update).
        """
        stale = dict(self.contest, show_samples=True)
        server._contest_pid_cache.update({
            "at": time.monotonic(), "all": {self.prob.pid},
            "hide": set(), "rows": [stale]})
        self.fake.tables["contests"] = [self.contest]
        with patch.object(server, "_ensure_problems_fresh"):
            with self.assertRaises(HTTPException) as exc:
                server.problem_sample(
                    Request({"type": "http", "session": {}}), self.prob.pid,
                    "01", Response())
        self.assertEqual(exc.exception.status_code, 404)

    def test_admin_rejudge_keeps_the_submission_owner_feedback_policy(self):
        """A rejudge stores the submission's policy, never the admin's view.

        The admin requester resolves to REVEAL_ALL and storage folds anything
        but REVEAL_NONE to REVEAL_SAMPLES, so an admin rejudge of a live
        show_samples=false submission came back from /api/history with public
        sample input/expected/diff — the feedback the contest withholds.
        """
        admin = "admin@example.invalid"
        self.fake.tables["contests"] = [self.contest]
        self.fake.tables.setdefault("judge_jobs", [])
        self.fake.tables["submissions"] = [
            dict(self.submission("sid-1", 0), language="python", code="print(1)")]
        with patch.object(server, "ADMIN_EMAILS", {admin}), \
                patch.object(server, "_ensure_problems_fresh"):
            out = asyncio.run(server.admin_rejudge(
                self.request_with(admin, {"ids": ["sid-1"]})))
        self.assertEqual(out["queued"], 1, out)
        jid = out["jobs"][0]
        self.addCleanup(server._jobs.pop, jid, None)
        job = server._jobs[jid]
        self.assertEqual(job["reveal"], server.REVEAL_NONE)

        row = server._submission_row(job, self.result_with_samples_and_hidden())
        read_back = server._result_with_reveal(row, {"results": row["results"]},
                                               server.REVEAL_SAMPLES)
        self.assertNotIn("SAMPLE-IN", json.dumps(read_back))
        self.assertNotIn("HIDDEN-IN", json.dumps(read_back))
        self.assertTrue(all(item.get("hidden") for item in read_back["results"]))

    def test_live_contest_hides_stored_sample_feedback_on_history_read(self):
        """A stored row may predate the live policy (or an old rejudge).

        /api/history/{sid} trusted the stored bytes and applied a static
        REVEAL_SAMPLES to contest rows, so a submission written while samples
        were allowed could still disclose them after the contest switched to
        show_samples=false. Re-evaluate the owner-facing policy at read time.
        """
        owner = "synthetic@example.invalid"
        row = dict(self.submission("sid-stored", 0), language="python",
                   results=[{"test": "01", "verdict": "WA", "input": "SAMPLE-IN",
                             "expected": "SAMPLE-OUT", "actual": "WRONG",
                             "diff": "sample-diff"}])
        self.fake.tables["contests"] = [self.contest]
        self.fake.tables["submissions"] = [row]
        out = asyncio.run(server.history_detail(self.request_with(owner, {}), "sid-stored"))
        self.assertNotIn("SAMPLE-IN", json.dumps(out))
        self.assertNotIn("SAMPLE-OUT", json.dumps(out))

        # Positive control: once the contest ends, the same stored row is
        # history and public sample feedback is allowed again.
        self.contest["ends_at"] = (self.now - dt.timedelta(minutes=1)).isoformat()
        self.fake.tables["contests"] = [self.contest]
        out = asyncio.run(server.history_detail(self.request_with(owner, {}), "sid-stored"))
        self.assertIn("SAMPLE-IN", json.dumps(out))

    def test_admin_rejudge_practice_in_live_hidden_contest_uses_none(self):
        """A practice row has no contest_id, but the problem can be in a live
        show_samples=false contest. Rejudge storage must use the same live
        practice policy as submit, not a blanket REVEAL_SAMPLES."""
        admin = "admin@example.invalid"
        self.fake.tables["contests"] = [self.contest]
        self.fake.tables.setdefault("judge_jobs", [])
        row = dict(self.submission("sid-practice-rejudge", 0), contest_id=None,
                   language="python", code="print(1)")
        self.fake.tables["submissions"] = [row]
        with patch.object(server, "ADMIN_EMAILS", {admin}), \
                patch.object(server, "_ensure_problems_fresh"):
            out = asyncio.run(server.admin_rejudge(
                self.request_with(admin, {"ids": ["sid-practice-rejudge"]})))
        self.assertEqual(out["queued"], 1, out)
        jid = out["jobs"][0]
        self.addCleanup(server._jobs.pop, jid, None)
        self.assertEqual(server._jobs[jid]["reveal"], server.REVEAL_NONE)

    def test_admin_rejudge_unknown_contest_fails_closed(self):
        """A deleted/unavailable contest must not fall back to samples."""
        admin = "admin@example.invalid"
        self.fake.tables["contests"] = []
        self.fake.tables.setdefault("judge_jobs", [])
        row = dict(self.submission("sid-missing-contest", 0),
                   contest_id="missing-contest", language="python", code="print(1)")
        self.fake.tables["submissions"] = [row]
        with patch.object(server, "ADMIN_EMAILS", {admin}), \
                patch.object(server, "_ensure_problems_fresh"):
            out = asyncio.run(server.admin_rejudge(
                self.request_with(admin, {"ids": ["sid-missing-contest"]})))
        self.assertEqual(out["queued"], 1, out)
        jid = out["jobs"][0]
        self.addCleanup(server._jobs.pop, jid, None)
        self.assertEqual(server._jobs[jid]["reveal"], server.REVEAL_NONE)

    def test_admin_rejudge_practice_outside_contest_keeps_practice_feedback(self):
        """Fail closed only where the policy is hidden; normal practice
        rejudges keep the owner's practice-level feedback."""
        admin = "admin@example.invalid"
        self.fake.tables["contests"] = []
        self.fake.tables.setdefault("judge_jobs", [])
        row = dict(self.submission("sid-practice-plain", 0), contest_id=None,
                   language="python", code="print(1)")
        self.fake.tables["submissions"] = [row]
        with patch.object(server, "ADMIN_EMAILS", {admin}), \
                patch.object(server, "_ensure_problems_fresh"):
            out = asyncio.run(server.admin_rejudge(
                self.request_with(admin, {"ids": ["sid-practice-plain"]})))
        self.assertEqual(out["queued"], 1, out)
        jid = out["jobs"][0]
        self.addCleanup(server._jobs.pop, jid, None)
        self.assertEqual(server._jobs[jid]["reveal"], server.REVEAL_PRACTICE)

    def test_admin_owner_keeps_admin_feedback_policy_on_contest_reads(self):
        """Contest rows use the submission owner's policy.

        _reveal_for grants admins REVEAL_ALL. The generic contest-free
        _effective_reveal does not, so re-checking a contest row without its
        row would silently strip the admin owner's own feedback. Use the
        owner's contest row, never the viewer's identity.
        """
        admin = "admin@example.invalid"
        row = dict(self.submission("sid-admin", 0), user_email=admin, language="python",
                   results=[{"test": "01", "verdict": "WA", "input": "SAMPLE-IN",
                             "expected": "SAMPLE-OUT", "actual": "WRONG",
                             "diff": "sample-diff"}])
        self.fake.tables["contests"] = [self.contest]
        self.fake.tables["submissions"] = [row]
        with patch.object(server, "ADMIN_EMAILS", {admin}):
            out = asyncio.run(server.history_detail(self.request_with(admin, {}), "sid-admin"))
        self.assertIn("SAMPLE-IN", json.dumps(out))

    def test_admin_viewing_another_users_contest_row_uses_owner_policy(self):
        """An admin viewer must not declassify someone else's stored row."""
        admin = "admin@example.invalid"
        owner = "synthetic@example.invalid"
        row = dict(self.submission("sid-other", 0), user_email=owner, language="python",
                   results=[{"test": "01", "verdict": "WA", "input": "SAMPLE-IN",
                             "expected": "SAMPLE-OUT", "actual": "WRONG",
                             "diff": "sample-diff"}])
        self.fake.tables["contests"] = [self.contest]
        self.fake.tables["submissions"] = [row]
        with patch.object(server, "ADMIN_EMAILS", {admin}):
            out = asyncio.run(server.history_detail(self.request_with(admin, {}), "sid-other"))
        self.assertNotIn("SAMPLE-IN", json.dumps(out))
        self.assertTrue(all(item.get("hidden") for item in out["results"]))

    def test_live_contest_hides_practice_history_for_newly_hidden_problem(self):
        """A practice row has no contest_id; the problem can still be listed
        in a contest that starts later. Reading its stored samples must obey
        the live policy rather than the row's provenance."""
        owner = "synthetic@example.invalid"
        row = dict(self.submission("sid-practice-stored", 0), contest_id=None,
                   language="python",
                   results=[{"test": "01", "verdict": "WA", "input": "SAMPLE-IN",
                             "expected": "SAMPLE-OUT", "actual": "WRONG",
                             "diff": "sample-diff"}])
        self.fake.tables["contests"] = [self.contest]
        self.fake.tables["submissions"] = [row]
        out = asyncio.run(server.history_detail(self.request_with(owner, {}),
                                                "sid-practice-stored"))
        self.assertNotIn("SAMPLE-IN", json.dumps(out))

        self.contest["ends_at"] = (self.now - dt.timedelta(minutes=1)).isoformat()
        self.fake.tables["contests"] = [self.contest]
        out = asyncio.run(server.history_detail(self.request_with(owner, {}),
                                                "sid-practice-stored"))
        self.assertIn("SAMPLE-IN", json.dumps(out))

    def test_live_contest_hides_stored_job_feedback_on_poll(self):
        """A job's reveal is a creation-time snapshot.

        A practice job stored while the problem was outside a contest holds
        REVEAL_SAMPLES. If the problem later enters a running
        show_samples=false contest, polling the finished job must re-check the
        live owner-facing policy, not replay the stale snapshot.
        """
        owner = "synthetic@example.invalid"
        jid = "synthetic-stale-policy-job"
        job = {"id": jid, "kind": "submit", "problem": self.prob.pid,
               "contest_id": None, "user_email": owner,
               "reveal": server.REVEAL_SAMPLES, "status": "done",
               "language": "python", "source": "print(1)", "name": "Synthetic",
               "result": self.result_with_samples_and_hidden()}
        self.fake.tables["contests"] = [self.contest]
        with patch.object(server, "QUEUE_MODE", "local"):
            server._jobs[jid] = dict(job)
            self.addCleanup(server._jobs.pop, jid, None)
            polled = asyncio.run(server.job_status(self.request_with(owner, {}), jid))
        self.assertNotIn("SAMPLE-IN", json.dumps(polled["result"]))
        self.assertNotIn("HIDDEN-IN", json.dumps(polled["result"]))
        # An admin polling someone else's job must use the owner's policy too.
        with patch.object(server, "ADMIN_EMAILS", {"admin@example.invalid"}):
            admin_polled = asyncio.run(server.job_status(
                self.request_with("admin@example.invalid", {}), jid))
        self.assertNotIn("SAMPLE-IN", json.dumps(admin_polled["result"]))

        # Positive control: after the contest ends, permitted sample feedback
        # is visible again.
        self.contest["ends_at"] = (self.now - dt.timedelta(minutes=1)).isoformat()
        self.fake.tables["contests"] = [self.contest]
        with patch.object(server, "QUEUE_MODE", "local"):
            polled = asyncio.run(server.job_status(self.request_with(owner, {}), jid))
        self.assertIn("SAMPLE-IN", json.dumps(polled["result"]))

    def test_rejudge_job_never_hands_the_owner_hidden_test_data(self):
        """The in-memory job record holds the redacted variant only.

        Local mode kept the requester-privileged REVEAL_ALL result, and
        /api/jobs/{id} re-applies the *job's* reveal to a record whose
        user_email is the original submitter: the owner could poll an admin
        rejudge of their own submission and read hidden input/expected/diff.
        """
        owner = "synthetic@example.invalid"
        jid = "synthetic-rejudge-job"
        self.fake.tables.setdefault("judge_jobs", [])
        job = {"id": jid, "kind": "rejudge", "problem": self.prob.pid,
               "contest_id": self.contest["id"], "user_email": owner,
               "reveal": server.REVEAL_ALL, "status": "running", "language": "python",
               "source": "print(1)", "name": "Synthetic"}
        with patch.object(server, "QUEUE_MODE", "local"):
            server._jobs[jid] = dict(job)
            self.addCleanup(server._jobs.pop, jid, None)
            stored = server._stored_result(job, self.result_with_samples_and_hidden())
            asyncio.run(server._finish_job(jid, result=self.result_with_samples_and_hidden(),
                                           stored=stored))
            polled = asyncio.run(server.job_status(self.request_with(owner, {}), jid))
        self.assertNotIn("HIDDEN-IN", json.dumps(server._jobs[jid]["result"]))
        self.assertNotIn("HIDDEN-IN", json.dumps(polled["result"]))
        self.assertNotIn("HIDDEN-OUT", json.dumps(polled["result"]))
