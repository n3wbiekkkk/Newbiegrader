"""Bounded synthetic HTTP bodies; no workload or external network access."""
import asyncio
from unittest.mock import Mock, patch
import unittest

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from critical_helpers import test_server

server = test_server()


class RequestBoundaries(unittest.TestCase):
    def test_body_limit_counts_chunks_even_without_content_length(self):
        called, sent = [], []

        async def app(scope, receive, send):
            called.append(True)

        async def exercise():
            messages = iter([{"type": "http.request", "body": b"x" * 40, "more_body": True},
                             {"type": "http.request", "body": b"y" * 40, "more_body": False}])
            async def receive():
                return next(messages)
            async def send(message):
                sent.append(message)
            await server.RequestBodyLimit(app, 64)(
                {"type": "http", "method": "POST", "path": "/api/test", "headers": []}, receive, send)
        asyncio.run(exercise())
        self.assertEqual(sent[0]["status"], 413)
        self.assertEqual(called, [])

    def test_oversize_body_never_reaches_the_parser_and_valid_json_is_unchanged(self):
        app = FastAPI()
        app.add_middleware(server.RequestBodyLimit, max_bytes=64)
        parsed = []

        @app.post("/api/test")
        async def endpoint(request: Request):
            parsed.append(True)
            return await server._json_object(request)

        with TestClient(app) as client:
            self.assertEqual(client.post("/api/test", content=b"x" * 65).status_code, 413)
            self.assertEqual(parsed, [])
            self.assertEqual(client.post("/api/test", json={"value": "synthetic"}).json(),
                             {"value": "synthetic"})
            for invalid in ([], None, 1, "text"):
                self.assertEqual(client.post("/api/test", content=__import__("json").dumps(invalid),
                                             headers={"Content-Type": "application/json"}).status_code, 400)

    def test_anonymous_submit_does_not_load_problem_data(self):
        app = FastAPI()

        @app.middleware("http")
        async def anonymous(request: Request, call_next):
            request.scope["session"] = {}
            return await call_next(request)

        app.post("/api/submit")(server.submit)
        lookup = Mock()
        with patch.object(server, "_problem_or_404", lookup), \
                patch.object(server, "_ensure_problems_fresh", lookup), TestClient(app) as client:
            response = client.post("/api/submit", data={
                "problem": "synthetic", "language": "python", "code": 'print("hello")'})
        self.assertEqual(response.status_code, 401)
        lookup.assert_not_called()
