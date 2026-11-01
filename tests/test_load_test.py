"""Safety and measurement regressions for the opt-in load harness."""
import json
import contextlib
import http.server
import io
import sys
import threading
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import load_test


class LoadHarnessTests(unittest.TestCase):
    def test_api_latency_excludes_failed_requests(self):
        metrics = load_test.Metrics()
        metrics.record("submit", load_test.Response(202, {}, 1.0))
        metrics.record("submit", load_test.Response(503, {}, 0.001, "http_503"))
        report = metrics.report()
        self.assertEqual(report["api_latency"]["submit"]["count"], 1)
        self.assertEqual(report["api_latency"]["submit"]["p95_s"], 1.0)
        self.assertEqual(report["request_errors"], {"submit:http_503": 1})

    def test_loopback_default_and_remote_opt_in(self):
        for target in ("http://127.0.0.1:8000", "http://localhost:8094", "http://[::1]:8000"):
            self.assertEqual(load_test.validate_target(target, False), target)
        for target in ("https://test.example", "http://127.0.0.1.evil.example", "http://192.168.1.2"):
            with self.assertRaises(ValueError):
                load_test.validate_target(target, False)
            self.assertEqual(load_test.validate_target(target, True), target)

    def test_target_rejects_credentials_and_ambiguous_urls_even_with_opt_in(self):
        for target in ("file:///tmp/test", "http://user:secret@localhost", "http://localhost/?token=secret",
                       "http://localhost/#fragment", "http://localhost:bad", "http://localhost/api"):
            with self.subTest(target=target), self.assertRaises(ValueError):
                load_test.validate_target(target, True)

    def test_credentials_are_only_read_from_named_environment_and_errors_are_redacted(self):
        secret = "never-print-this"
        with patch.dict("os.environ", {"NG_LOAD_ACCOUNTS": json.dumps([
                {"email": "test@example.invalid", "password": secret}])}):
            self.assertEqual(len(load_test.load_accounts("NG_LOAD_ACCOUNTS")), 1)
        for raw in (secret, "{}", '[{"email":"x","password":1}]', '[]'):
            with patch.dict("os.environ", {"NG_LOAD_ACCOUNTS": raw}):
                with self.assertRaises(ValueError) as caught:
                    load_test.load_accounts("NG_LOAD_ACCOUNTS")
                self.assertNotIn(secret, str(caught.exception))

    def test_percentiles_report_empty_and_skewed_samples(self):
        self.assertEqual(load_test.summarize([]), {"count": 0})
        summary = load_test.summarize([0.1, 0.2, 0.3, 9.4])
        self.assertEqual(summary["count"], 4)
        self.assertAlmostEqual(summary["mean_s"], 2.5)
        self.assertAlmostEqual(summary["p50_s"], 0.25)
        self.assertAlmostEqual(summary["p95_s"], 8.035)
        self.assertEqual(summary["max_s"], 9.4)

    def test_timestamps_override_poll_estimates_without_inventing_missing_service_time(self):
        precise = load_test.job_durations({"created_at": "2026-10-15T00:00:00Z",
            "started_at": "2026-10-15T00:00:02Z", "finished_at": "2026-10-15T00:00:05Z"},
            first_running_s=2.5, elapsed_s=6)
        self.assertEqual(precise, {"queue_wait_s": 2.0, "service_s": 3.0, "timing_source": "server"})
        estimated = load_test.job_durations({}, first_running_s=2.5, elapsed_s=6)
        self.assertEqual(estimated, {"queue_wait_s": 2.5, "service_s": 3.5,
                                     "timing_source": "poll_estimate"})
        missing = load_test.job_durations({}, first_running_s=None, elapsed_s=6)
        self.assertIsNone(missing["queue_wait_s"])
        self.assertIsNone(missing["service_s"])

    def test_opt_in_and_invalid_numeric_inputs_fail_before_network(self):
        with patch.object(load_test, "run_load") as run, contextlib.redirect_stderr(io.StringIO()):
            for args in ([], ["--execute"], ["--execute", "--test-installation", "--users", "0"],
                         ["--execute", "--test-installation", "--request-timeout", "nan"],
                         ["--execute", "--test-installation", "--poll-interval", "inf"]):
                with self.subTest(args=args), self.assertRaises(SystemExit):
                    load_test.main(args)
            run.assert_not_called()

    def test_playground_sends_the_supplied_input_and_counts_execution_failures(self):
        class RecordingClient:
            timeout = 5

            def request(self, kind, path, **kwargs):
                self.fields = kwargs["fields"]
                return load_test.Response(200, {"verdict": "RE"}, 0.01)

        client = RecordingClient()
        args = SimpleNamespace(job_timeout=10, problem="thai_time", language="python", stdin="9 PM\n")
        outcome = load_test.run_attempt(client, args, "print('test')", True)
        self.assertEqual(client.fields.get("input"), "9 PM\n")
        self.assertEqual(outcome["error"], "playground_execution_error")

    def test_invalid_terminal_result_is_reported_instead_of_crashing_the_burst(self):
        class BrokenResponseClient:
            timeout = 5

            def request(self, kind, path, **kwargs):
                if kind == "submit":
                    return load_test.Response(202, {"job_id": "test-job"}, 0.01)
                return load_test.Response(200, {"status": "done", "result": "unexpected"}, 0.01)

        args = SimpleNamespace(job_timeout=10, problem="thai_time", language="python", poll_interval=0.01)
        outcome = load_test.run_attempt(BrokenResponseClient(), args, "print('test')", False)
        self.assertEqual(outcome["error"], "invalid_job_result")
        self.assertFalse(outcome["completed"])

    def test_real_http_bursts_keep_sessions_and_report_queue_and_health_measurements(self):
        polls = {}
        visits = []
        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def respond(self, status, payload, cookie=None):
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                if cookie:
                    self.send_header("Set-Cookie", cookie)
                self.end_headers()
                self.wfile.write(json.dumps(payload).encode())

            def do_POST(self):
                visits.append(self.path)
                raw = self.rfile.read(int(self.headers["Content-Length"]))
                if self.path == "/api/auth/password":
                    identity = json.loads(raw)["email"]
                    self.respond(200, {"ok": True}, f"ng_session={identity}; Path=/")
                    return
                identity = self.headers.get("Cookie", "")
                if not identity.startswith("ng_session="):
                    self.respond(401, {})
                    return
                fields = parse_qs(raw.decode())
                if self.path == "/api/run":
                    self.respond(200, {"verdict": "OK" if fields.get("input") == ["6 AM\n"] else "RE"})
                else:
                    polls[identity] = 0
                    self.respond(202, {"job_id": identity})

            def do_GET(self):
                visits.append(self.path)
                if self.path == "/api/health":
                    self.respond(200, {"ok": True})
                    return
                identity = self.headers.get("Cookie", "")
                if identity not in polls:
                    self.respond(403, {})
                    return
                polls[identity] += 1
                status = ["queued", "running", "done"][min(2, polls[identity] - 1)]
                self.respond(200, {"status": status, "result": {"verdict": "AC"},
                    "created_at": "2026-10-15T00:00:00Z", "started_at": "2026-10-15T00:00:02Z",
                    "finished_at": "2026-10-15T00:00:05Z"})

        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                args = SimpleNamespace(target=f"http://127.0.0.1:{server.server_port}",
                    request_timeout=2, register=False, health_clients=1, health_interval=0.002,
                    bursts=2, burst_interval=0.005, playground_every=2,
                    job_timeout=5, problem="thai_time", language="python", stdin="6 AM\n", poll_interval=0.005)
                accounts = [{"email": f"test-{i}@example.invalid", "password": "disposable-test"} for i in range(2)]
                report = load_test.run_load(args, accounts, "print('test')")
            finally:
                server.shutdown()
                thread.join(timeout=2)
        self.assertIn("/api/auth/password", visits)
        self.assertNotIn("/api/auth/register", visits)
        self.assertEqual(report["correct"], 4)
        self.assertEqual(report["attempts"], 4)
        self.assertEqual(report["completed"], 4)
        self.assertEqual(report["outcome_errors"], {})
        self.assertEqual(report["request_errors"], {})
        self.assertEqual(report["submission"]["queue_wait_s"]["mean_s"], 2)
        self.assertEqual(report["submission"]["service_s"]["mean_s"], 3)
        self.assertGreater(report["api_latency"]["health"]["count"], 0)
        self.assertEqual(report["http_status_counts"]["status:200"], 6)
        self.assertGreater(report["throughput_completed_per_s"], 0)

    def test_polling_cap_is_configurable_and_invalid_caps_fail_before_network(self):
        calls = 0
        delays = []
        class Client:
            timeout = 5
            def request(self, kind, path, **kwargs):
                nonlocal calls
                if kind == "submit":
                    return load_test.Response(202, {"job_id": "synthetic"}, 0)
                calls += 1
                return load_test.Response(200, {"status": "queued"} if calls < 4 else
                    {"status": "done", "result": {"verdict": "AC"}}, 0)
        args = SimpleNamespace(job_timeout=10, problem="p", language="python",
                               poll_interval=0.8, poll_max_interval=1.0)
        with patch.object(load_test.time, "sleep", side_effect=delays.append), \
                patch.object(load_test.random, "uniform", return_value=1):
            outcome = load_test.run_attempt(Client(), args, "pass", False)
        self.assertTrue(outcome["correct"])
        self.assertEqual(delays, [0.8, 1.0, 1.0])
        calls = 0
        delays.clear()
        with patch.object(load_test.time, "sleep", side_effect=delays.append), \
                patch.object(load_test.random, "uniform", return_value=1.2):
            outcome = load_test.run_attempt(Client(), args, "pass", False)
        self.assertTrue(outcome["correct"])
        self.assertTrue(all(delay <= 1 for delay in delays))
        with patch.object(load_test, "run_load") as run, contextlib.redirect_stderr(io.StringIO()):
            for flags in (["--poll-max-interval", "3"],
                          ["--poll-interval", "1.5", "--poll-max-interval", "1"]):
                with self.subTest(flags=flags), self.assertRaises(SystemExit):
                    load_test.main(["--execute", "--test-installation", *flags])
            run.assert_not_called()

    def test_playground_uses_full_job_budget_and_aborts_ambiguous_attempt(self):
        class DelayedClient:
            timeout = 10
            def request(self, kind, path, **kwargs):
                self.timeout_used = kwargs["timeout"]
                return load_test.Response(0, {}, 10, "request_timeout")
        client = DelayedClient()
        args = SimpleNamespace(job_timeout=240, problem="p", language="python", stdin="")
        outcome = load_test.run_attempt(client, args, "pass", True)
        self.assertEqual(client.timeout_used, 240)
        self.assertTrue(outcome["fatal"])
        self.assertFalse(outcome["completed"])

    def test_submission_wrong_verdict_is_completed_but_not_correct(self):
        class Client:
            timeout = 5
            def request(self, kind, path, **kwargs):
                if kind == "submit":
                    return load_test.Response(202, {"job_id": "synthetic"}, 0)
                return load_test.Response(200, {"status": "done", "result": {"verdict": "WA"}}, 0)
        args = SimpleNamespace(job_timeout=10, problem="p", language="python", poll_interval=0.01)
        outcome = load_test.run_attempt(Client(), args, "pass", False)
        self.assertTrue(outcome["completed"])
        self.assertFalse(outcome["correct"])
        self.assertEqual(outcome["error"], "unexpected_verdict")

    def test_rejections_are_not_admitted_and_ambiguous_posts_are_fatal(self):
        args = SimpleNamespace(job_timeout=10, problem="p", language="python", poll_interval=0.01)
        class Client:
            timeout = 5
            def request(self, *a, **kw):
                return response
        for response in (load_test.Response(429, {}, 0, "http_429"),
                         load_test.Response(503, {}, 0, "http_503"),
                         load_test.Response(0, {}, 0, "request_timeout"),
                         load_test.Response(202, {}, 0)):
            with self.subTest(response=response):
                outcome = load_test.run_attempt(Client(), args, "pass", False)
                self.assertFalse(outcome["admitted"])
                self.assertFalse(outcome["completed"])
                self.assertEqual(outcome["fatal"], response.status != 429)
                if response.status in (429, 503):
                    self.assertEqual(outcome["rejection_status"], response.status)

    def test_register_refuses_otp_delivery_before_any_network(self):
        with patch.object(load_test, "run_load") as run, \
                contextlib.redirect_stderr(io.StringIO()) as err, self.assertRaises(SystemExit):
            load_test.main(["--execute", "--test-installation", "--register"])
        self.assertIn("OTP", err.getvalue())
        run.assert_not_called()

    @staticmethod
    def duration_args(**overrides):
        return SimpleNamespace(**({"target": "http://127.0.0.1:8094", "request_timeout": 2,
            "health_clients": 0, "health_interval": 0.01, "playground_every": None,
            "job_timeout": 1, "problem": "p", "language": "python", "stdin": "",
            "poll_interval": 0.001, "duration": 0.15, "think_time": 0.001,
            "ramp_seconds": 0, "browse": False} | overrides))

    def test_sustained_actors_are_independent_and_drain_after_deadline(self):
        calls = {"slow": 0, "fast": 0}
        class Client:
            timeout = 2
            def __init__(self, *_):
                pass
            def request(self, kind, path, **kwargs):
                if kind == "auth":
                    self.identity = kwargs["body"]["email"]
                    return load_test.Response(200, {}, 0)
                if kind == "submit":
                    calls[self.identity] += 1
                    time.sleep(0.10 if self.identity == "slow" else 0.003)
                    return load_test.Response(202, {"job_id": "synthetic"}, 0)
                return load_test.Response(200, {"status": "done", "result": {"verdict": "AC"}}, 0)
        accounts = [{"email": "slow"}, {"email": "fast"}]
        with patch.object(load_test, "Client", Client):
            report = load_test.run_load(self.duration_args(), accounts, "pass")
        self.assertGreater(calls["fast"], calls["slow"])
        self.assertTrue(report["duration_reached"])
        self.assertEqual(report["correct"], report["attempts"])
        self.assertLess(report["drain_s"], 1)

    def test_sustained_actor_never_resubmits_after_ambiguous_post(self):
        calls = []
        class Client:
            timeout = 2
            def __init__(self, *_):
                pass
            def request(self, kind, path, **kwargs):
                calls.append(kind)
                return (load_test.Response(200, {}, 0) if kind == "auth" else
                        load_test.Response(0, {}, 0, "request_timeout"))
        with patch.object(load_test, "Client", Client):
            report = load_test.run_load(self.duration_args(), [{"email": "synthetic"}], "pass")
        self.assertEqual(calls, ["auth", "submit"])
        self.assertEqual(report["actor_errors"], {"actor_stopped": 1})
        self.assertFalse(report["duration_reached"])
        self.assertEqual(report["admitted"], 0)

    def test_workload_reads_local_sources_and_browses_without_reporting_source(self):
        calls = []
        class Client:
            timeout = 2
            def __init__(self, *_):
                pass
            def request(self, kind, path, **kwargs):
                calls.append((kind, path, kwargs))
                if kind == "submit":
                    return load_test.Response(202, {"job_id": "synthetic"}, 0)
                if kind == "status":
                    return load_test.Response(200, {"status": "done", "result": {"verdict": "AC"}}, 0)
                return load_test.Response(200, {}, 0)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = 'print("private reference source")'
            (root / "reference.py").write_text(source)
            config = root / "workload.json"
            config.write_text(json.dumps([{"language": "cpp", "problem": "other",
                "source": "reference.py", "stdin": "canary", "weight": 2,
                "expected_verdict": "REJECTED"}]))
            workload = load_test.load_workload(config)
            self.assertEqual(workload[0]["expected_verdict"], "REJECTED")
            workload[0]["expected_verdict"] = "AC"
            args = self.duration_args(duration=None, workloads=workload, browse=True,
                                      bursts=1, burst_interval=0.01)
            with patch.object(load_test, "Client", Client):
                report = load_test.run_load(args, [{"email": "synthetic"}], "")
        self.assertEqual([kind for kind, *_ in calls], ["auth", "catalog", "detail", "submit", "status"])
        submission = next(kwargs["fields"] for kind, _, kwargs in calls if kind == "submit")
        self.assertEqual(submission["language"], "cpp")
        self.assertEqual(submission["problem"], "other")
        self.assertEqual(submission["code"], source)
        self.assertNotIn("private reference source", json.dumps(report))
        self.assertEqual(report["languages"]["cpp"]["correct"], 1)

    def test_duration_deadline_during_browsing_starts_no_new_job(self):
        calls = []
        class Client:
            timeout = 2
            def __init__(self, *_):
                pass
            def request(self, kind, path, **kwargs):
                calls.append(kind)
                if kind == "catalog":
                    time.sleep(0.03)
                return load_test.Response(200, {}, 0)
        with patch.object(load_test, "Client", Client):
            report = load_test.run_load(self.duration_args(duration=0.01, browse=True),
                                        [{"email": "synthetic"}], "pass")
        self.assertEqual(calls, ["auth", "catalog"])
        self.assertEqual(report["attempts"], 0)
        self.assertTrue(report["duration_reached"])

    def test_workload_invalid_shapes_fail_before_any_execution(self):
        valid = {"language": "python", "problem": "p", "source": "reference.py"}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "reference.py").write_text("pass")
            config = root / "workload.json"
            for data in ({}, [], [valid | {"weight": float("inf")}],
                         [valid | {"expected_verdict": []}], [valid | {"language": "shell"}]):
                with self.subTest(data=data), self.assertRaises(ValueError):
                    config.write_text(json.dumps(data))
                    load_test.load_workload(config)

    def test_redirects_do_not_send_credentials_to_the_redirect_destination(self):
        visited = []
        class RedirectHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass

            def do_POST(self):
                visited.append(self.path)
                self.rfile.read(int(self.headers["Content-Length"]))
                self.send_response(307)
                self.send_header("Location", "/credential-sink")
                self.end_headers()

        with http.server.ThreadingHTTPServer(("127.0.0.1", 0), RedirectHandler) as server:
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                client = load_test.Client(f"http://127.0.0.1:{server.server_port}", 2, load_test.Metrics())
                response = client.request("auth", "/api/auth/password", body={"password": "test-secret"})
            finally:
                server.shutdown()
                thread.join(timeout=2)
        self.assertEqual(response.status, 307)
        self.assertEqual(response.error, "http_307")
        self.assertEqual(visited, ["/api/auth/password"])


if __name__ == "__main__":
    unittest.main()
