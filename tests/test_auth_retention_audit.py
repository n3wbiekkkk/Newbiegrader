"""Synthetic OAuth verification and terminal-job memory regressions."""
import asyncio
import io
import json
import logging
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi import Request
from fake_supabase import FakeSupabase
from critical_helpers import test_server

server = test_server()


class AuthRetentionAudit(unittest.TestCase):
    def test_uvicorn_access_log_omits_oauth_credentials(self):
        for path in ("/api/auth/finish?token=SYNTHETIC_BEARER&next=%23/",
                     "/api/%61uth/finish?token=SYNTHETIC_BEARER",
                     "/api/auth/callback?code=SYNTHETIC_CODE&state=synthetic"):
            record = logging.LogRecord("uvicorn.access", logging.INFO, "synthetic", 1,
                '%s - "%s %s HTTP/%s" %d', ("synthetic-peer", "GET", path, "1.1", 307), None)
            self.assertTrue(server.AuthQueryLogFilter().filter(record))
            self.assertNotIn("SYNTHETIC_", record.getMessage())
            self.assertIn(path.split("?", 1)[0], record.getMessage())
            self.assertIn("307", record.getMessage())

    def test_google_requires_explicit_verified_email(self):
        for verified in (False, None, "true"):
            with self.subTest(verified=verified):
                replies = [io.BytesIO(b'{"access_token":"synthetic"}'), io.BytesIO(json.dumps({
                    "email": "synthetic@example.invalid", "email_verified": verified, "sub": "synthetic-google-sub"}).encode())]
                with patch.object(server, "urlopen", side_effect=replies):
                    with self.assertRaises(RuntimeError):
                        server._google_userinfo("synthetic-code")
        replies = [io.BytesIO(b'{"access_token":"synthetic"}'), io.BytesIO(json.dumps({
            "email": "synthetic@example.invalid", "email_verified": True, "sub": "synthetic-google-sub"}).encode())]
        with patch.object(server, "urlopen", side_effect=replies):
            self.assertEqual(server._google_userinfo("synthetic-code")["email"],
                             "synthetic@example.invalid")

    def make_handoff(self, db):
        email = "synthetic@example.invalid"
        db.rows("users").append({"email": email, "name": "Synthetic", "auth_version": 1,
                                 "email_verified_at": "2026-10-23T00:00:00Z"})
        request = Request({"type": "http", "session": {}, "headers": []})
        sid = server._start_web_session(request, {"email": email, "auth_version": 1,
                                                 "provider": "google"}, False, pending=True)
        return server._login_signer.dumps({"sid": sid, "remember": False})

    def test_handoff_has_no_process_replay_cache_capacity_cutoff(self):
        db = FakeSupabase()
        with patch.object(server, "_sb", db):
            token = self.make_handoff(db)
            db.rows("web_sessions").extend({"token_hash": f"{i:064x}"} for i in range(10001))
            request = Request({"type": "http", "session": {}, "headers": []})
            server.auth_finish(request, token, "#/tasks")
            self.assertEqual(request.session["user"]["email"], "synthetic@example.invalid")
            replay = Request({"type": "http", "session": {}, "headers": []})
            server.auth_finish(replay, token, "#/tasks")
            self.assertNotIn("user", replay.session)

    def test_finished_jobs_release_source_and_payload(self):
        jobs = {"synthetic": {"id": "synthetic", "kind": "playground", "status": "running",
                              "source": "synthetic-source", "payload": {"input": "synthetic-input"}}}
        with patch.object(server, "_jobs", jobs), patch.object(server, "_sb", None), \
                patch.object(server, "QUEUE_MODE", "local"), patch.object(server, "_active_jobs", {}):
            asyncio.run(server._finish_job("synthetic", result={"verdict": "OK"}))
            self.assertNotIn("source", jobs["synthetic"])
            self.assertNotIn("payload", jobs["synthetic"])
            self.assertEqual(jobs["synthetic"]["result"]["verdict"], "OK")

    def test_concurrent_handoff_is_single_use_and_database_failure_is_closed(self):
        db = FakeSupabase()
        with patch.object(server, "_sb", db):
            token = self.make_handoff(db)
            def finish(_):
                request = Request({"type": "http", "session": {}, "headers": []})
                server.auth_finish(request, token, "#/")
                return "user" in request.session
            with ThreadPoolExecutor(max_workers=8) as pool:
                self.assertEqual(sum(pool.map(finish, range(32))), 1)
            with patch.object(db, "rpc", side_effect=RuntimeError("synthetic outage")):
                with self.assertRaises(server.HTTPException) as error:
                    finish(0)
                self.assertEqual(error.exception.status_code, 503)

    def test_expired_completed_jobs_prune_below_the_old_5000_threshold(self):
        old = time.monotonic() - server.JOB_TTL_S - 1
        jobs = {"old": {"status": "done", "created_monotonic": old},
                "running": {"status": "running", "created_monotonic": old}}
        with patch.object(server, "_jobs", jobs):
            server._remember_job({"id": "fresh", "status": "queued"})
            self.assertNotIn("old", jobs)
            self.assertIn("running", jobs)
