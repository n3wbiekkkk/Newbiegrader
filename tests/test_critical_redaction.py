"""Synthetic F3 regressions across engine, queue, API, and persistence."""
import asyncio
import contextlib
import copy
import io
import json
import os
import sys
import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

import grader
import judge_runner
from critical_helpers import synthetic_problem, test_server
from fake_supabase import FakeSupabase

server = test_server()
EMAIL = "synthetic-student@example.invalid"
STDERR_SOURCE = "import sys\nsys.stderr.write(sys.stdin.read())\nsys.exit(7)\n"
STDOUT_SOURCE = "import sys\nsys.stdout.write(sys.stdin.read())\n"


class CriticalRedaction(unittest.TestCase):
    def setUp(self):
        self.problem = synthetic_problem()
        self.canary = "SYNTHETIC_HIDDEN_" + uuid.uuid4().hex
        self.problem.tests[1].input = self.canary + "\n"
        self.fake = FakeSupabase()
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        for name, value in {
            "PROBLEMS": {self.problem.pid: self.problem},
            "PROBLEM_SOURCE": "local", "QUEUE_MODE": "local", "GRADER_ROLE": "combined",
            "JUDGE_JOBS": 1, "MEMORY_CAP_MB": 128, "_sb": self.fake,
            "_jobs": {}, "_active_jobs": {}, "_TESTS_HASH_CACHE": {},
        }.items():
            self.stack.enter_context(patch.object(server, name, value))
        self.stack.enter_context(patch.dict(os.environ, {"GRADER_REQUIRE_NETNS": "0"}))
        original_env = judge_runner._runner_env
        self.stack.enter_context(patch.object(judge_runner, "_runner_env", side_effect=lambda:
            original_env() | {"GRADER_PROBLEM_SOURCE": "supabase"}))
        # Real handlers and HTTP serialization, with a synthetic identity.
        # Authentication itself is outside this regression's scope.
        app = FastAPI()

        @app.middleware("http")
        async def identity(request: Request, call_next):
            request.scope["session"] = {"user": {"email": EMAIL}}
            return await call_next(request)

        app.get("/api/jobs/{jid}")(server.job_status)
        app.get("/api/history")(server.history)
        app.get("/api/history/{sid}")(server.history_detail)
        self.client = self.stack.enter_context(TestClient(app))

    def assert_no_canary(self, value):
        self.assertEqual(json.dumps(value).count(self.canary), 0)

    def execute_job(self, source, reveal="samples", mode="local", jobs=1):
        job = {"id": str(uuid.uuid4()), "problem": self.problem.pid,
               "language": "python", "source": source, "kind": "submit",
               "user_email": EMAIL, "name": "Synthetic student", "filename": "canary.py",
               "reveal": reveal, "status": "queued", "created_at": server._iso_now()}
        server._jobs[job["id"]] = job
        self.fake.table("judge_jobs").insert(copy.deepcopy(job)).execute()
        output = io.StringIO()
        with patch.object(server, "QUEUE_MODE", mode), patch.object(server, "JUDGE_JOBS", jobs), \
                contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
            if mode == "database":
                job.update(worker_id="synthetic-worker", attempt=1)
                captured = {}

                async def rpc(action, **params):
                    if action == "heartbeat":
                        return True
                    self.assertEqual(action, "finish")
                    captured.update(params)
                    return {"applied": True}

                with patch.object(server, "_queue_rpc", side_effect=rpc):
                    asyncio.run(server._run_job(job))
                self.assert_no_canary(captured)
                self.assert_no_canary(output.getvalue())
                return captured["p_result"], captured["p_submission"]
            asyncio.run(server._run_job(job))
        self.assert_no_canary(output.getvalue())
        self.assertEqual(server._jobs[job["id"]]["status"], "done")
        response = self.client.get("/api/jobs/" + job["id"])
        self.assertEqual(response.status_code, 200)
        self.assert_no_canary(response.json())
        persisted = self.fake.tables["judge_jobs"][0]["result"]
        self.assert_no_canary(persisted)
        rows = self.fake.tables["submissions"]
        self.assertEqual(len(rows), 1)
        self.assert_no_canary(rows)
        history = self.client.get("/api/history/" + rows[0]["id"])
        self.assertEqual(history.status_code, 200)
        self.assert_no_canary(history.json())
        listing = self.client.get("/api/history?mine=true")
        self.assertEqual(listing.status_code, 200)
        self.assert_no_canary(listing.json())
        return response.json()["result"], rows[0]

    def test_critical_hidden_stderr_absent_from_job_history_and_persistence(self):
        result, row = self.execute_job(STDERR_SOURCE)
        self.assertEqual(result["counts"], {"RE": 2})
        hidden = next(r for r in result["results"] if r["test"] == "1001")
        self.assertEqual(hidden["detail"], "runtime error")
        public = next(r for r in result["results"] if r["test"] == "01")
        self.assertIn("public-input", public["detail"])
        self.assertIn("public-input", json.dumps(row["results"]))

    def test_critical_reveal_none_hides_public_stderr_too(self):
        result, row = self.execute_job(STDERR_SOURCE, reveal="none")
        self.assertNotIn("public-input", json.dumps(result))
        self.assertNotIn("public-input", json.dumps(row))

    def test_critical_hidden_stdout_wa_stays_redacted(self):
        result, row = self.execute_job(STDOUT_SOURCE)
        self.assertEqual(result["counts"], {"WA": 2})
        hidden = next(r for r in result["results"] if r["test"] == "1001")
        self.assertFalse({"input", "expected", "actual", "diff"} & hidden.keys())
        public = next(r for r in result["results"] if r["test"] == "01")
        self.assertIn("public-input", public["actual"])
        self.assert_no_canary(row)

    def test_critical_reveal_none_hides_public_wa_output_too(self):
        result, row = self.execute_job(STDOUT_SOURCE, reveal="none")
        self.assertEqual(result["counts"], {"WA": 2})
        for value in (result, row):
            self.assertNotIn("public-input", json.dumps(value))

    def test_critical_database_finish_rpc_gets_redacted_results(self):
        result, submission = self.execute_job(STDERR_SOURCE, mode="database")
        self.assertEqual(result["counts"], {"RE": 2})
        self.assert_no_canary(submission)
        self.assertEqual(submission["results"][1]["detail"], "runtime error")

    def test_critical_parallel_judging_applies_the_same_policy(self):
        result, row = self.execute_job(STDERR_SOURCE, jobs=2)
        self.assertEqual(result["counts"], {"RE": 2})
        self.assert_no_canary(row)

    def test_critical_engine_never_returns_hidden_stderr_in_detail(self):
        tc = self.problem.tests[1]
        base = {"wall": 0.01, "cpu": 0.01, "peak_mb": 1,
                "stdout": self.canary, "stderr": self.canary,
                "reason": "", "returncode": 7}
        for reason, code, err in (("", 7, self.canary), ("signal:SIGSEGV", -11, self.canary),
                                  ("spawn-fail", -1, self.canary), ("oom", -9, self.canary),
                                  ("sigkill", -9, self.canary), ("", 1, "MemoryError " + self.canary)):
            with self.subTest(reason=reason, code=code), \
                    patch.object(grader, "run_one", return_value=base | {
                        "reason": reason, "returncode": code, "stderr": err}):
                verdict = grader.judge_test([], tc, self.problem, False, True)
                self.assertNotIn(self.canary, verdict[4])

    def test_critical_redactor_covers_all_reveal_modes_and_raw_stream_keys(self):
        for reveal in ("all", "samples", "none"):
            for public in (False, True):
                with self.subTest(reveal=reveal, public=public):
                    raw = [{"test": "01" if public else "1001", "verdict": "RE",
                            "public": public, "detail": self.canary,
                            "stdout": self.canary, "stderr": self.canary}]
                    result = server._redact_results(raw, reveal)
                    if not public or reveal == "none":
                        self.assert_no_canary(result)
                    else:
                        self.assertIn(self.canary, result[0]["detail"])

    def test_critical_legacy_job_and_history_details_are_redacted_on_read(self):
        raw = {"results": [{"test": "1001", "verdict": "RE", "detail": self.canary}]}
        jid, sid = str(uuid.uuid4()), str(uuid.uuid4())
        server._jobs[jid] = {"id": jid, "status": "done", "kind": "submit", "user_email": EMAIL,
                             "problem": self.problem.pid, "result": raw}
        self.fake.tables["submissions"] = [{"id": sid, "user_email": EMAIL,
            "problem": self.problem.pid, "results": raw["results"]}]
        for path in ("/api/jobs/" + jid, "/api/history/" + sid):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assert_no_canary(response.json())
        # The database-backed poll path must apply the same read redaction.
        self.fake.tables["judge_jobs"] = [copy.deepcopy(server._jobs[jid])]
        server._jobs.clear()
        with patch.object(server, "QUEUE_MODE", "database"):
            response = self.client.get("/api/jobs/" + jid)
        self.assertEqual(response.status_code, 200)
        self.assert_no_canary(response.json())

    def test_critical_storage_boundaries_reject_raw_hidden_details(self):
        job = {"id": str(uuid.uuid4()), "problem": self.problem.pid,
               "kind": "submit", "reveal": "samples", "user_email": EMAIL}
        raw = {"results": [{"test": "1001", "verdict": "RE", "detail": self.canary}]}
        self.assert_no_canary(server._submission_row(job, raw, stored=raw))
        server._jobs[job["id"]] = job
        self.fake.tables["judge_jobs"] = [copy.deepcopy(job)]
        asyncio.run(server._finish_job(job["id"], result=raw, stored=raw))
        self.assert_no_canary(server._jobs[job["id"]]["result"])
        self.assert_no_canary(self.fake.tables["judge_jobs"][0]["result"])


if __name__ == "__main__":
    unittest.main()
