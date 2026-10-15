"""Concurrency and ownership regressions; no external database is contacted."""
import asyncio
import concurrent.futures
import datetime as dt
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")
os.environ.setdefault("SESSION_SECRET", "queue-test-secret")
from fake_supabase import FakeSupabase
import server


def job(email="student@example.com", kind="submit"):
    return {"kind": kind, "user_email": email, "problem": "thai_time",
            "language": "python", "source": "print(1)", "reveal": "samples"}


class QueueAdmission(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = FakeSupabase()
        self.patches = [patch.object(server, "_sb", self.fake),
                        patch.object(server, "QUEUE_MODE", "database", create=True),
                        patch.object(server, "GRADER_ROLE", "combined", create=True),
                        patch.object(server, "QUEUE_MAX", 2),
                        patch.object(server, "_jobs", {}),
                        patch.object(server, "_active_jobs", {}),
                        patch.object(server, "_job_queue", None),
                        patch.object(server, "_job_loop", None)]
        for p in self.patches:
            p.start()

    async def asyncTearDown(self):
        for p in reversed(self.patches):
            p.stop()

    async def test_concurrent_same_user_admission_is_atomic(self):
        out = await asyncio.gather(*(server._create_job(job()) for _ in range(8)),
                                   return_exceptions=True)
        self.assertEqual(sum(isinstance(x, dict) for x in out), 1)
        self.assertEqual([x.status_code for x in out if not isinstance(x, dict)], [409] * 7)

    async def test_local_same_user_admission_is_atomic_across_database_yield(self):
        with patch.object(server, "QUEUE_MODE", "local"):
            out = await asyncio.gather(*(server._create_job(job()) for _ in range(8)),
                                       return_exceptions=True)
        self.assertEqual(sum(isinstance(x, dict) for x in out), 1)
        self.assertTrue(all(x.status_code == 409 for x in out if not isinstance(x, dict)))

    async def test_queue_capacity_is_atomic(self):
        out = await asyncio.gather(*(server._create_job(job(f"s{i}@example.com"))
                                     for i in range(8)), return_exceptions=True)
        self.assertEqual(sum(isinstance(x, dict) for x in out), 2)
        self.assertTrue(all(x.status_code == 503 for x in out if not isinstance(x, dict)))

    async def test_database_failure_does_not_accept_local_work(self):
        self.fake.missing.add("judge_jobs")
        with self.assertRaises(server.HTTPException) as raised:
            await server._create_job(job())
        self.assertEqual(raised.exception.status_code, 503)
        self.assertFalse(server._jobs)
        self.assertFalse(server._active_jobs)

    async def test_database_status_failure_is_503_when_client_is_unavailable(self):
        with patch.object(server, "_sb", None):
            with self.assertRaises(server.HTTPException) as raised:
                await server._load_job("not-cached")
        self.assertEqual(raised.exception.status_code, 503)

    async def test_status_is_authoritative(self):
        queued = await server._create_job(job())
        self.fake.rows("judge_jobs")[0].update(status="done", result={"score": 100})
        loaded = await server._load_job(queued["id"])
        self.assertEqual(loaded["status"], "done")

    async def test_status_endpoint_ignores_stale_process_cache(self):
        queued = await server._create_job(job())
        server._jobs[queued["id"]] = {**queued, "status": "queued"}
        self.fake.rows("judge_jobs")[0].update(status="done", result={"score": 100})
        request = Request({"type": "http", "session": {"user": {"email": queued["user_email"]}}})
        response = await server.job_status(request, queued["id"])
        self.assertEqual(response["status"], "done")
        self.assertEqual(response["result"]["score"], 100)

    async def test_poll_refresh_cannot_replace_active_attempt_ownership(self):
        await server._create_job(job())
        first = self.fake.rpc("judge_queue_claim", {"p_worker": "old", "p_lease_seconds": 30}).execute().data
        entered, release = asyncio.Event(), asyncio.Event()
        async def execution(*args):
            entered.set()
            await release.wait()
            return {"verdict": "AC", "results": [], "score": 100}
        with patch("judge_runner.run_isolated", side_effect=execution):
            running = asyncio.create_task(server._run_job(first))
            await entered.wait()
            self.fake.rows("judge_jobs")[0]["lease_until"] = (
                dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=1)).isoformat()
            second = self.fake.rpc("judge_queue_claim", {"p_worker": "new", "p_lease_seconds": 30}).execute().data
            await server._load_job(first["id"])
            release.set()
            await running
        self.assertEqual(self.fake.rows("judge_jobs")[0]["status"], "running")
        self.assertEqual(self.fake.rows("judge_jobs")[0]["worker_id"], second["worker_id"])
        self.assertFalse(self.fake.rows("submissions"))

    async def test_separated_roles_require_database_and_stable_secret(self):
        for mode, secret in (("local", "stable"), ("database", "")):
            with patch.object(server, "GRADER_ROLE", "api"), \
                 patch.object(server, "QUEUE_MODE", mode), \
                 patch.dict(os.environ, {"SESSION_SECRET": secret}):
                with self.assertRaises(RuntimeError):
                    await server.validate_runtime()

    async def test_api_lifespan_does_not_start_workers(self):
        with patch.object(server, "GRADER_ROLE", "api"), \
             patch.object(server, "_judge_worker", AsyncMock()) as worker:
            async with server._lifespan(server.app):
                await asyncio.sleep(0)
        worker.assert_not_called()

    async def test_api_only_playground_awaits_durable_remote_result(self):
        request = Request({"type": "http", "session": {"user": {"email": "remote@example.com"}}})
        with patch.object(server, "GRADER_ROLE", "api"), \
             patch("judge_runner.run_isolated", AsyncMock()) as runner:
            pending = asyncio.create_task(server.run_custom(
                request, language="python", code="print(7)", file=None,
                input="", problem="", time_limit=1.0))
            for _ in range(100):
                if self.fake.rows("judge_jobs"):
                    break
                await asyncio.sleep(0.01)
            self.assertTrue(self.fake.rows("judge_jobs"))
            claimed = self.fake.rpc("judge_queue_claim", {"p_worker": "remote", "p_lease_seconds": 30}).execute().data
            self.fake.rpc("judge_queue_finish", {
                "p_id": claimed["id"], "p_worker": "remote", "p_attempt": claimed["attempt"],
                "p_result": {"verdict": "OK", "stdout": "7\n"}, "p_submission": None, "p_error": ""}).execute()
            response = await asyncio.wait_for(pending, 3)
        self.assertEqual(response["stdout"], "7\n")
        runner.assert_not_called()
        self.assertFalse(self.fake.rows("submissions"))

    async def test_heartbeat_failure_cancels_execution_before_return(self):
        queued = await server._create_job(job())
        claimed = self.fake.rpc("judge_queue_claim", {"p_worker": "worker", "p_lease_seconds": 30}).execute().data
        cleaned = asyncio.Event()
        async def long_execution(*args):
            try:
                await asyncio.Future()
            finally:
                await asyncio.sleep(0.01)
                cleaned.set()
        with patch("judge_runner.run_isolated", side_effect=long_execution), \
             patch.object(server, "HEARTBEAT_SECONDS", 0.01):
            self.fake.rows("judge_jobs")[0]["worker_id"] = "new-worker"
            await server._run_job(claimed)
        self.assertTrue(cleaned.is_set())
        self.assertEqual(self.fake.rows("judge_jobs")[0]["status"], "running")

    async def test_api_role_never_executes_job(self):
        with patch.object(server, "GRADER_ROLE", "api"):
            with self.assertRaises(RuntimeError):
                await server._run_job({"id": "x", **job()})

    async def test_stored_admin_feedback_is_samples_only(self):
        result = {"results": [{"test": "01", "input": "secret", "expected": "secret",
                               "actual": "x", "diff": "secret", "verdict": "WA"},
                              {"test": "02", "input": "sample", "verdict": "WA"}]}
        stored = server._submission_row({"id": "x", **job()}, result)
        self.assertNotIn("input", stored["results"][0])
        self.assertEqual(stored["results"][1]["input"], "sample")

    async def test_rejudge_uses_only_remaining_capacity(self):
        await server._create_job(job("first@example.com"))
        await server._create_job(job("other@example.com", "rejudge"), track_active=False)
        with self.assertRaises(server.HTTPException) as raised:
            await server._create_job(job("third@example.com", "rejudge"), track_active=False)
        self.assertEqual(raised.exception.status_code, 503)


class DatabaseOwnership(unittest.TestCase):
    def setUp(self):
        self.db = FakeSupabase()

    def rpc(self, name, **params):
        return self.db.rpc("judge_queue_" + name, params).execute().data

    def admit(self, email="student@example.com", kind="submit"):
        return self.rpc("admit", p_job=job(email, kind), p_queue_max=10,
                        p_track_active=kind != "rejudge", p_quota_limit=0,
                        p_quota_window=0)["job"]

    def claim(self, worker):
        return self.rpc("claim", p_worker=worker, p_lease_seconds=30)

    def test_two_consumers_claim_one_job_once(self):
        self.admit()
        with concurrent.futures.ThreadPoolExecutor(2) as executor:
            claims = list(executor.map(self.claim, ["a", "b"]))
        self.assertEqual(sum(bool(c) for c in claims), 1)

    def test_only_expired_ownership_is_recovered_and_old_attempt_cannot_finish(self):
        self.admit()
        first = self.claim("a")
        self.assertFalse(self.claim("b"))
        self.db.rows("judge_jobs")[0]["lease_until"] = (
            dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1)).isoformat()
        second = self.claim("b")
        self.assertGreater(second["attempt"], first["attempt"])
        stale = self.rpc("finish", p_id=first["id"], p_worker="a", p_attempt=first["attempt"],
                         p_result={}, p_submission=None, p_error="stale")
        self.assertFalse(stale["applied"])
        self.assertEqual(self.db.rows("judge_jobs")[0]["worker_id"], "b")

    def test_duplicate_completion_is_idempotent(self):
        self.admit()
        claimed = self.claim("a")
        args = dict(p_id=claimed["id"], p_worker="a", p_attempt=claimed["attempt"],
                    p_result={"score": 100}, p_error="",
                    p_submission={"problem": "thai_time", "language": "python", "verdict": "AC"})
        first = self.rpc("finish", **args)
        again = self.rpc("finish", **args)
        self.assertTrue(first["applied"])
        self.assertEqual(first, again)
        self.assertEqual(len(self.db.rows("submissions")), 1)

    def test_student_jobs_take_priority_over_rejudge(self):
        self.admit("a@example.com", "rejudge")
        student = self.admit("b@example.com")
        self.assertEqual(self.claim("a")["id"], student["id"])

    def test_expired_attempt_cannot_heartbeat_or_finish_before_reclaim(self):
        self.admit()
        owned = self.claim("a")
        self.db.rows("judge_jobs")[0]["lease_until"] = (dt.datetime.now(dt.timezone.utc)-dt.timedelta(seconds=1)).isoformat()
        args = dict(p_id=owned["id"], p_worker="a", p_attempt=owned["attempt"])
        self.assertFalse(self.rpc("heartbeat", **args, p_lease_seconds=30))
        self.assertFalse(self.rpc("finish", **args, p_result={}, p_submission=None, p_error="")["applied"])

    def test_shared_user_quota_survives_terminal_jobs(self):
        params = dict(p_job=job(), p_queue_max=10, p_track_active=True, p_quota_limit=1, p_quota_window=600)
        self.assertIn("job", self.rpc("admit", **params))
        claimed = self.claim("a")
        self.rpc("finish", p_id=claimed["id"], p_worker="a", p_attempt=claimed["attempt"],
                 p_result={}, p_submission=None, p_error="")
        denied = self.rpc("admit", **params)
        self.assertEqual(denied["status_code"], 429)

    def test_missing_lease_cannot_be_finalized(self):
        self.admit()
        owned = self.claim("a")
        self.db.rows("judge_jobs")[0]["lease_until"] = None
        result = self.rpc("finish", p_id=owned["id"], p_worker="a", p_attempt=owned["attempt"],
                          p_result={}, p_submission=None, p_error="")
        self.assertFalse(result["applied"])


class HostAdmission(unittest.TestCase):
    def test_overrides_cannot_exceed_cpu_or_memory_budget(self):
        with patch.dict(os.environ, {"GRADER_JUDGE_WORKERS": "100", "GRADER_JUDGE_JOBS": "100",
                                    "GRADER_MEMORY_CAP_MB": "10000"}):
            capacity = server._derive_capacity(0.5, 512)
        self.assertEqual(capacity["workers"], 1)
        self.assertEqual(capacity["judge_jobs"], 1)
        self.assertLessEqual(capacity["memory_cap_mb"] + capacity["reserve_mb"], 512)

    def test_host_slot_cannot_be_acquired_twice(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(server, "CAPACITY_DIR", Path(tmp), create=True), \
                 patch.object(server, "JUDGE_WORKERS", 1):
                first = server._try_host_slot()
                self.assertIsNotNone(first)
                self.assertIsNone(server._try_host_slot())
                first.close()
                second = server._try_host_slot()
                self.assertIsNotNone(second)
                second.close()

    def test_host_slot_is_shared_with_another_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(server, "CAPACITY_DIR", Path(tmp)), patch.object(server, "JUDGE_WORKERS", 1):
                first = server._try_host_slot()
                script = "import server; h=server._try_host_slot(); print('acquired' if h else 'busy'); h and h.close()"
                env = {**os.environ, "GRADER_RUNNER_CHILD": "1", "GRADER_CAPACITY_DIR": tmp,
                       "GRADER_JUDGE_WORKERS": "1"}
                blocked = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=15)
                first.close()
                allowed = subprocess.run([sys.executable, "-c", script], env=env, capture_output=True, text=True, timeout=15)
        self.assertEqual(blocked.returncode, 0, blocked.stderr)
        self.assertEqual(blocked.stdout.strip(), "busy")
        self.assertEqual(allowed.returncode, 0, allowed.stderr)
        self.assertEqual(allowed.stdout.strip(), "acquired")
