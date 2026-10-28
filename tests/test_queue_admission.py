"""Concurrency and ownership regressions; no external database is contacted."""
import asyncio
import concurrent.futures
import datetime as dt
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import AsyncMock, patch
from starlette.requests import Request

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_KEY", "")
os.environ.setdefault("SESSION_SECRET", "queue-test-secret")
from fake_supabase import FakeSupabase
from critical_helpers import synthetic_problem, test_server

server = test_server()


def job(email="student@example.com", kind="submit"):
    return {"kind": kind, "user_email": email, "problem": "security_canary",
            "language": "python", "source": "print(1)", "reveal": "samples"}


class DatabaseWorkerBackoff(unittest.IsolatedAsyncioTestCase):
    async def delays(self, outcomes, count):
        delays = []

        @asynccontextmanager
        async def slot():
            yield

        async def claim(*_args, **_kwargs):
            outcome = outcomes.pop(0) if outcomes else None
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        async def sleep(delay):
            delays.append(delay)
            if len(delays) == count:
                raise asyncio.CancelledError

        from unittest.mock import AsyncMock
        with patch.object(server, "QUEUE_MODE", "database"), \
                patch.object(server, "GRADER_ROLE", "combined"), \
                patch.object(server, "_host_slot", slot), \
                patch.object(server, "_queue_rpc", side_effect=claim), \
                patch.object(server, "_run_job", new_callable=AsyncMock) as run, \
                patch.object(server.asyncio, "sleep", side_effect=sleep):
            with self.assertRaises(asyncio.CancelledError):
                await server._judge_worker(0)
        return delays, run.await_count

    async def test_idle_polling_backs_off_with_a_bounded_admission_delay(self):
        delays, runs = await self.delays([], 5)
        self.assertEqual(delays, [.5, 1, 1, 1, 1])
        self.assertEqual(runs, 0)

    async def test_claimed_work_resets_the_poll_delay(self):
        delays, runs = await self.delays([None, None, {"id": "synthetic"}, None], 4)
        self.assertEqual(delays, [.5, 1, 0, .5])
        self.assertEqual(runs, 1)

    async def test_ready_backlog_has_no_artificial_gap_between_jobs(self):
        delays, runs = await self.delays([{"id": str(i)} for i in range(3)] + [None], 4)
        self.assertEqual(delays, [0, 0, 0, .5])
        self.assertEqual(runs, 3)

    async def test_outage_backs_off_and_recovery_resets_delay(self):
        delays, runs = await self.delays([RuntimeError("synthetic outage")] * 8 +
                                       [{"id": "synthetic"}], 9)
        self.assertEqual(delays, [1, 2, 4, 8, 16, 30, 30, 30, 0])
        self.assertEqual(runs, 1)


class QueueAdmission(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fake = FakeSupabase()
        self.patches = [patch.object(server, "_sb", self.fake),
                        patch.object(server._catalog, '_problems', {"security_canary": synthetic_problem()}),
                        patch.object(server, "PROBLEM_SOURCE", "local"),
                        patch.object(server._catalog, '_hashes', {}),
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
        for x in out:
            if not isinstance(x, dict):
                self.assertEqual(x.status_code, 409)
                self.assertIn("Retry-After", x.headers)
                self.assertTrue(x.headers["Retry-After"].isdigit())

    async def test_local_same_user_admission_is_atomic_across_database_yield(self):
        with patch.object(server, "QUEUE_MODE", "local"):
            out = await asyncio.gather(*(server._create_job(job()) for _ in range(8)),
                                       return_exceptions=True)
        self.assertEqual(sum(isinstance(x, dict) for x in out), 1)
        self.assertTrue(all(x.status_code == 409 for x in out if not isinstance(x, dict)))
        for x in out:
            if not isinstance(x, dict):
                self.assertEqual(x.status_code, 409)
                self.assertIn("Retry-After", x.headers)
                self.assertTrue(x.headers["Retry-After"].isdigit())

    async def test_queue_capacity_is_atomic(self):
        out = await asyncio.gather(*(server._create_job(job(f"s{i}@example.com"))
                                     for i in range(8)), return_exceptions=True)
        self.assertEqual(sum(isinstance(x, dict) for x in out), 2)
        self.assertTrue(all(x.status_code == 503 for x in out if not isinstance(x, dict)))
        for x in out:
            if not isinstance(x, dict):
                self.assertEqual(x.status_code, 503)
                self.assertIn("Retry-After", x.headers)
                self.assertTrue(x.headers["Retry-After"].isdigit())

    async def test_database_failure_does_not_accept_local_work(self):
        self.fake.missing.add("judge_jobs")
        with self.assertRaises(server.HTTPException) as raised:
            await server._create_job(job())
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("Retry-After", raised.exception.headers)
        self.assertTrue(raised.exception.headers["Retry-After"].isdigit())
        self.assertFalse(server._jobs)
        self.assertFalse(server._active_jobs)

    async def test_database_status_failure_is_503_when_client_is_unavailable(self):
        with patch.object(server, "_sb", None):
            with self.assertRaises(server.HTTPException) as raised:
                await server._load_job("not-cached")
        self.assertEqual(raised.exception.status_code, 503)

    async def test_create_job_503_when_database_unavailable_has_retry_after(self):
        with patch.object(server, "_sb", None), patch.object(server, "QUEUE_MODE", "database"):
            with self.assertRaises(server.HTTPException) as raised:
                await server._create_job(job())
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("Retry-After", raised.exception.headers)
        self.assertTrue(raised.exception.headers["Retry-After"].isdigit())

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
        result = {"results": [{"test": "1001", "input": "secret", "expected": "secret",
                               "actual": "x", "diff": "secret", "verdict": "WA"},
                              {"test": "01", "input": "sample", "verdict": "WA"}]}
        stored = server._submission_row({"id": "x", **job()}, result)
        self.assertNotIn("input", stored["results"][0])
        self.assertEqual(stored["results"][1]["input"], "sample")

    async def test_rejudge_uses_only_remaining_capacity(self):
        await server._create_job(job("first@example.com"))
        await server._create_job(job("other@example.com", "rejudge"), track_active=False)
        with self.assertRaises(server.HTTPException) as raised:
            await server._create_job(job("third@example.com", "rejudge"), track_active=False)
        self.assertEqual(raised.exception.status_code, 503)
        self.assertIn("Retry-After", raised.exception.headers)
        self.assertTrue(raised.exception.headers["Retry-After"].isdigit())


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


class IsolationPosture(unittest.TestCase):
    """Fail-closed boot contract: judge roles must declare their isolation
    posture; silence is never consent to judge without guaranteed isolation."""

    def posture(self, **kw):
        base = dict(role="combined", strict=False, acknowledged=False,
                    can_sandbox=False, netns_ok=False)
        base.update(kw)
        return server._judge_isolation_posture(**base)

    def test_api_role_never_judges_so_never_blocked(self):
        for strict in (False, True):
            self.assertEqual(
                self.posture(role="api", strict=strict, can_sandbox=True),
                "api")

    def test_strict_with_working_namespace_boots(self):
        self.assertEqual(
            self.posture(role="combined", strict=True,
                         can_sandbox=True, netns_ok=True), "strict")
        self.assertEqual(
            self.posture(role="worker", strict=True, acknowledged=True,
                         can_sandbox=True, netns_ok=True), "strict")

    def test_strict_on_incapable_runtime_refuses(self):
        with self.assertRaises(RuntimeError):
            self.posture(role="combined", strict=True, can_sandbox=False)
        with self.assertRaises(RuntimeError):
            self.posture(role="worker", strict=True,
                         can_sandbox=True, netns_ok=False)

    def test_missing_and_disabled_strict_refuse_on_sandbox_host(self):
        # Absent and explicitly-0 are indistinguishable — and equally refused.
        with self.assertRaises(RuntimeError):
            self.posture(role="combined", can_sandbox=True)
        with self.assertRaises(RuntimeError):
            self.posture(role="worker", strict=False,
                         can_sandbox=True, netns_ok=True)

    def test_explicit_acknowledgement_boots_anywhere(self):
        self.assertEqual(
            self.posture(role="combined", acknowledged=True,
                         can_sandbox=True), "acknowledged")
        self.assertEqual(self.posture(role="worker", acknowledged=True),
                         "acknowledged")

    def test_dev_runtime_warns_instead_of_refusing(self):
        self.assertEqual(self.posture(role="combined"), "dev")

    def test_netns_probe_is_negative_off_linux(self):
        import grader
        with patch.object(grader.sys, "platform", "darwin"):
            self.assertFalse(grader.netns_available())


def _http_request(peer, headers=None):
    raw = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope = {"type": "http", "headers": raw, "client": (peer, 12345)}
    return Request(scope)


class TrustedProxyIp(unittest.TestCase):
    """_client_ip: peer-first trust, chain walked only from trusted peers."""

    def test_direct_request_uses_peer_ip(self):
        r = _http_request("203.0.113.7")
        self.assertEqual(server._client_ip(r), "203.0.113.7")

    def test_direct_forged_xff_is_ignored(self):
        r = _http_request("203.0.113.7",
                          {"x-forwarded-for": "198.51.100.9, 192.0.2.1"})
        self.assertEqual(server._client_ip(r), "203.0.113.7")

    def test_direct_forged_cf_connecting_ip_is_ignored(self):
        r = _http_request("203.0.113.7",
                          {"cf-connecting-ip": "198.51.100.9"})
        self.assertEqual(server._client_ip(r), "203.0.113.7")

    def test_trusted_peer_honors_client_ip(self):
        with unittest.mock.patch.dict(os.environ,
                                      {"GRADER_TRUSTED_PROXY_CIDRS": "10.0.0.0/8"}):
            r = _http_request("10.1.2.3",
                              {"x-forwarded-for": "203.0.113.7"})
            self.assertEqual(server._client_ip(r), "203.0.113.7")

    def test_spoofed_chain_cannot_pick_attacker_address(self):
        with unittest.mock.patch.dict(os.environ,
                                      {"GRADER_TRUSTED_PROXY_CIDRS": "10.0.0.0/8"}):
            # Rightmost untrusted entry wins; forged prepends are never used.
            r = _http_request("10.1.2.3", {"x-forwarded-for":
                                           "6.6.6.6, 203.0.113.7"})
            self.assertEqual(server._client_ip(r), "203.0.113.7")
            # Trusted hops are skipped leftwards to the real client.
            r = _http_request("10.1.2.3", {"x-forwarded-for":
                                           "203.0.113.7, 10.9.9.9"})
            self.assertEqual(server._client_ip(r), "203.0.113.7")
            # CF header agrees with the chain walk.
            r = _http_request("10.1.2.3",
                              {"cf-connecting-ip": "203.0.113.7",
                               "x-forwarded-for": "203.0.113.7"})
            self.assertEqual(server._client_ip(r), "203.0.113.7")

    def test_conflicting_cf_cannot_override_usable_xff(self):
        # M-1: a non-sanitizing proxy may forward a client-forged
        # CF-Connecting-IP alongside a correct XFF chain. XFF wins.
        with unittest.mock.patch.dict(os.environ,
                                      {"GRADER_TRUSTED_PROXY_CIDRS": "10.0.0.0/8"}):
            r = _http_request("10.1.2.3",
                              {"cf-connecting-ip": "198.51.100.9",
                               "x-forwarded-for": "203.0.113.7"})
            self.assertEqual(server._client_ip(r), "203.0.113.7")
            # Stability: varying only CF never moves the identity.
            for cf in ("198.51.100.9", "192.0.2.1", "203.0.113.7"):
                r = _http_request("10.1.2.3",
                                  {"cf-connecting-ip": cf,
                                   "x-forwarded-for": "203.0.113.7"})
                self.assertEqual(server._client_ip(r), "203.0.113.7", cf)
            # Even when every XFF hop is trusted, a conflicting CF is
            # ignored (resolves to the peer, never to the forged value).
            r = _http_request("10.1.2.3",
                              {"cf-connecting-ip": "198.51.100.9",
                               "x-forwarded-for": "10.9.9.9"})
            self.assertEqual(server._client_ip(r), "10.1.2.3")
            # A malformed XFF chain cannot fall back to a conflicting CF.
            r = _http_request("10.1.2.3",
                              {"cf-connecting-ip": "198.51.100.9",
                               "x-forwarded-for": "203.0.113.7, garbage!!!"})
            self.assertEqual(server._client_ip(r), "10.1.2.3")

    def test_cf_fallback_only_without_xff(self):
        # CF-Connecting-IP is never trusted as a client identity: when XFF
        # is absent, the socket peer is authoritative (a forged CF header
        # cannot impersonate another IP).
        with unittest.mock.patch.dict(os.environ,
                                      {"GRADER_TRUSTED_PROXY_CIDRS": "10.0.0.0/8"}):
            r = _http_request("10.1.2.3",
                              {"cf-connecting-ip": "203.0.113.7"})
            self.assertEqual(server._client_ip(r), "10.1.2.3")
            # ...and never from an untrusted direct caller either.
            r = _http_request("203.0.113.99",
                              {"cf-connecting-ip": "203.0.113.7",
                               "x-forwarded-for": "203.0.113.7"})
            self.assertEqual(server._client_ip(r), "203.0.113.99")

    def test_unconfigured_proxy_peer_is_untrusted(self):
        with unittest.mock.patch.dict(os.environ,
                                      {"GRADER_TRUSTED_PROXY_CIDRS": "10.0.0.0/8"}):
            r = _http_request("192.0.2.99",
                              {"x-forwarded-for": "203.0.113.7"})
            self.assertEqual(server._client_ip(r), "192.0.2.99")

    def test_malformed_headers_never_500(self):
        with unittest.mock.patch.dict(os.environ,
                                      {"GRADER_TRUSTED_PROXY_CIDRS": "10.0.0.0/8"}):
            for headers in ({"x-forwarded-for": "garbage!!!"},
                            {"cf-connecting-ip": "999.999.999.999"},
                            {"x-forwarded-for": "203.0.113.7, garbage!!!"},
                            {"x-forwarded-for": ""}):
                r = _http_request("10.1.2.3", headers)
                self.assertEqual(server._client_ip(r), "10.1.2.3", headers)

    def test_ipv6_peer_and_chain(self):
        with unittest.mock.patch.dict(os.environ,
                                      {"GRADER_TRUSTED_PROXY_CIDRS": "::1/128"}):
            r = _http_request("::1", {"x-forwarded-for": "2001:db8::5"})
            self.assertEqual(server._client_ip(r), "2001:db8::5")
        with unittest.mock.patch.dict(os.environ,
                                      {"GRADER_TRUSTED_PROXY_CIDRS": "2001:db8::/32"}):
            r = _http_request("2001:db8::1",
                              {"x-forwarded-for": "2001:db9::7, 2001:db8::9"})
            self.assertEqual(server._client_ip(r), "2001:db9::7")
            r = _http_request("2001:db8::1")
            self.assertEqual(server._client_ip(r), "2001:db8::1")

    def test_malformed_config_rejected(self):
        for bad in ("bogus", "1.2.3.4/33", "10.0.0.0/8, nope"):
            with unittest.mock.patch.dict(os.environ,
                                          {"GRADER_TRUSTED_PROXY_CIDRS": bad}):
                with self.assertRaises(ValueError):
                    server._trusted_proxy_nets()

    def test_malformed_config_refuses_to_boot(self):
        async def go():
            with unittest.mock.patch.dict(
                    os.environ, {"GRADER_TRUSTED_PROXY_CIDRS": "bogus"}), \
                 unittest.mock.patch.object(server, "GRADER_ROLE", "combined"), \
                 unittest.mock.patch.object(server, "QUEUE_MODE", "local"):
                with self.assertRaises(RuntimeError):
                    await server.validate_runtime()
        import asyncio
        asyncio.run(go())
