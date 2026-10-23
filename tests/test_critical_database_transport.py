"""Exercise the pinned SDK and real HTTP/1.1 connection turnover without secrets."""
import ast
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import ssl
import threading
import unittest

import httpx
from postgrest.utils import SyncClient as PostgrestSession
from supabase import ClientOptions

from database_client import WorkerSupabaseClient, create_database_client


KEY = "synthetic.key.signature"


class DatabaseTransport(unittest.TestCase):
    def test_only_worker_changes_protocol_and_keeps_tls_auth_schema_timeout(self):
        for role in ("worker", "api", "combined"):
            with self.subTest(role=role):
                client = create_database_client("https://synthetic.supabase.co", KEY, role=role)
                session = client.postgrest.session
                self.addCleanup(session.close)
                pool = session._transport._pool
                self.assertEqual(pool._http2, role != "worker")
                self.assertTrue(pool._http1)
                self.assertEqual(pool._ssl_context.verify_mode, ssl.CERT_REQUIRED)
                self.assertTrue(pool._ssl_context.check_hostname)
                self.assertEqual(session.headers["apikey"], KEY)
                self.assertEqual(session.headers["authorization"], "Bearer " + KEY)
                self.assertEqual(session.headers["accept-profile"], "public")
                self.assertEqual(session.headers["content-profile"], "public")
                self.assertEqual(session.timeout.read, 120)

    def test_custom_schema_timeout_and_auth_are_preserved(self):
        client = WorkerSupabaseClient.create("https://synthetic.supabase.co", KEY,
            ClientOptions(schema="private_schema", postgrest_client_timeout=7))
        session = client.postgrest.session
        self.addCleanup(session.close)
        self.assertEqual(session.headers["accept-profile"], "private_schema")
        self.assertEqual(session.headers["content-profile"], "private_schema")
        self.assertEqual(session.timeout.read, 7)
        self.assertEqual(session.headers["authorization"], "Bearer " + KEY)

    def test_ambiguous_claim_failure_is_not_replayed(self):
        client = create_database_client("https://synthetic.supabase.co", KEY, role="worker")
        original = client.postgrest.session
        headers = dict(original.headers)
        original.close()
        calls = []

        def fail(request):
            calls.append(request)
            raise httpx.RemoteProtocolError("synthetic disconnect after acceptance")

        session = PostgrestSession(base_url=client.rest_url, headers=headers,
                                  transport=httpx.MockTransport(fail))
        self.addCleanup(session.close)
        client.postgrest.session = session
        with self.assertRaises(httpx.RemoteProtocolError):
            client.rpc("judge_queue_claim", {"p_worker": "synthetic", "p_lease_seconds": 300}).execute()
        self.assertEqual(len(calls), 1)
        self.assertEqual(json.loads(calls[0].content)["p_worker"], "synthetic")

    def test_real_rpc_survives_repeated_server_connection_turnover(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                received.append((self.path, payload, self.headers["Authorization"]))
                body = b'{"queued":0,"running":0}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *_args):
                pass

        host = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=host.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(host.server_close)
        self.addCleanup(host.shutdown)
        client = create_database_client(f"http://127.0.0.1:{host.server_port}", KEY, role="worker")
        self.addCleanup(client.postgrest.session.close)
        for _ in range(12):
            self.assertEqual(client.rpc("judge_queue_diagnostics", {}).execute().data,
                             {"queued": 0, "running": 0})
        self.assertEqual(len(received), 12)
        self.assertTrue(all(path == "/rest/v1/rpc/judge_queue_diagnostics" and payload == {}
                            and auth == "Bearer " + KEY for path, payload, auth in received))

    def test_server_selects_role_and_release_fingerprint_covers_adapter(self):
        root = Path(__file__).resolve().parents[1]
        tree = ast.parse((root / "server.py").read_text())
        assignments = [node for node in tree.body if isinstance(node, ast.Assign)]
        files = next(ast.literal_eval(node.value) for node in assignments
                     if any(isinstance(t, ast.Name) and t.id == "BUILD_SOURCE_FILES"
                            for t in node.targets))
        self.assertIn("database_client.py", files)
        calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Name) and node.func.id == "create_client"]
        self.assertEqual(len(calls), 1)
        self.assertTrue(any(k.arg == "role" and isinstance(k.value, ast.Name)
                            and k.value.id == "GRADER_ROLE" for k in calls[0].keywords))
