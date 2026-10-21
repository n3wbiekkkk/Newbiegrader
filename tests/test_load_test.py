# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Safety and measurement regressions for the opt-in load harness."""
import json
import contextlib
import http.server
import io
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tools import load_test


class LoadHarnessTests(unittest.TestCase):
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
                if self.path == "/api/auth/register":
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
                    request_timeout=2, register=True, health_clients=1, health_interval=0.002,
                    bursts=2, burst_interval=0.005, playground_every=2,
                    job_timeout=5, problem="thai_time", language="python", stdin="6 AM\n", poll_interval=0.005)
                accounts = [{"email": f"test-{i}@example.invalid", "password": "disposable-test"} for i in range(2)]
                report = load_test.run_load(args, accounts, "print('test')")
            finally:
                server.shutdown()
                thread.join(timeout=2)
        self.assertEqual(report["attempts"], 4)
        self.assertEqual(report["completed"], 4)
        self.assertEqual(report["outcome_errors"], {})
        self.assertEqual(report["request_errors"], {})
        self.assertEqual(report["submission"]["queue_wait_s"]["mean_s"], 2)
        self.assertEqual(report["submission"]["service_s"]["mean_s"], 3)
        self.assertGreater(report["api_latency"]["health"]["count"], 0)
        self.assertEqual(report["http_status_counts"]["status:200"], 6)
        self.assertGreater(report["throughput_completed_per_s"], 0)

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
