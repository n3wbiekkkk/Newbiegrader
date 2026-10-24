"""Official solutions: fresh member/contest policy and protected local PDFs."""
import contextlib
import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from critical_helpers import synthetic_problem, test_server
import backend_problem_files as files
import problem_store

server = test_server()
PDF = b'%PDF-1.4\nSYNTHETIC SOLUTION'


class SolutionAccess(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.prob = synthetic_problem()
        self.email = 'viewer@example.invalid'
        self.contests = []
        for key, value in {'PROBLEMS': {self.prob.pid: self.prob},
                           'PROBLEMS_BY_NO': {99: self.prob.pid},
                           'PROBLEM_SOURCE': 'local'}.items():
            self.stack.enter_context(patch.object(server, key, value))
        self.stack.enter_context(patch.object(server, '_ensure_problems_fresh'))
        self.stack.enter_context(patch.object(server, '_visible_to', return_value=True))
        self.stack.enter_context(patch.object(server, '_all_contest_rows', side_effect=lambda: self.contests))
        self.load = self.stack.enter_context(patch.object(problem_store, 'get_solution_pdf', return_value=PDF))
        app = FastAPI()

        @app.middleware('http')
        async def identity(request: Request, call_next):
            request.scope['session'] = {'user': {'email': self.email}} if self.email else {}
            return await call_next(request)

        app.get('/api/problems/{pid}/solution')(server.problem_solution)
        app.get('/api/problems/{pid}/solution/pdf')(server.problem_solution_pdf)
        self.client = self.stack.enter_context(TestClient(app, raise_server_exceptions=False))
        self.url = f'/api/problems/{self.prob.pid}/solution'

    def test_member_without_any_submission_can_read_and_pdf_is_private(self):
        self.assertEqual(self.client.get(self.url).json()['available'], True)
        r = self.client.get(self.url + '/pdf')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content, PDF)
        self.assertEqual(r.headers['cache-control'], 'private, no-store')
        self.assertIn('application/pdf', r.headers['content-type'])

    def test_anonymous_and_invisible_requests_never_read_a_file(self):
        self.email = ''
        self.assertEqual(self.client.get(self.url + '/pdf').status_code, 401)
        self.email = 'viewer@example.invalid'
        with patch.object(server, '_visible_to', return_value=False):
            self.assertEqual(self.client.get(self.url + '/pdf').status_code, 404)
        self.load.assert_not_called()

    def test_policy_is_checked_again_for_pdf_even_after_successful_metadata(self):
        self.assertEqual(self.client.get(self.url).status_code, 200)
        now = dt.datetime.now(dt.timezone.utc)
        self.contests = [{'id': 'new-cup', 'problems': [self.prob.pid],
                          'starts_at': (now + dt.timedelta(hours=1)).isoformat(),
                          'ends_at': (now + dt.timedelta(hours=2)).isoformat()}]
        self.load.reset_mock()
        self.assertEqual(self.client.get(self.url + '/pdf', headers={'If-None-Match': '*'}).status_code, 403)
        self.load.assert_not_called()

    def test_malformed_policy_and_outages_fail_closed(self):
        self.contests = [{'id': 'bad', 'problems': [self.prob.pid], 'starts_at': 'bad', 'ends_at': 'bad'}]
        self.assertEqual(self.client.get(self.url + '/pdf').status_code, 403)
        with patch.object(server, '_all_contest_rows', side_effect=RuntimeError('outage')):
            self.assertEqual(self.client.get(self.url + '/pdf').status_code, 503)
        self.load.assert_not_called()

    def test_missing_pdf_and_damaged_store_are_distinct(self):
        self.load.side_effect = problem_store.ProblemNotFound('missing')
        self.assertEqual(self.client.get(self.url + '/pdf').status_code, 404)
        self.load.side_effect = problem_store.ProblemUnavailable('corrupt')
        self.assertEqual(self.client.get(self.url + '/pdf').status_code, 503)

    def test_ended_contest_allows_solution(self):
        now = dt.datetime.now(dt.timezone.utc)
        self.contests = [{'id': 'ended', 'problems': [self.prob.pid],
                          'starts_at': (now - dt.timedelta(hours=2)).isoformat(),
                          'ends_at': (now - dt.timedelta(hours=1)).isoformat()}]
        self.assertEqual(self.client.get(self.url + '/pdf').status_code, 200)


class SolutionStorage(unittest.TestCase):
    def test_only_public_index_is_read_and_integrity_is_enforced(self):
        import os
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp).resolve()
            env = {'GRADER_FILE_STORAGE': 'local', 'GRADER_PUBLIC_FILE_ROOT': str(base/'public'),
                   'GRADER_PRIVATE_FILE_ROOT': str(base/'private'), 'GRADER_FILE_MIN_FREE_MB': '256'}
            with patch.dict(os.environ, env), patch.object(files, '_INDEX_CACHE', {}):
                files.publish('judge-assets', [('synthetic/solution.pdf', PDF, 'application/pdf')])
                with patch.object(files, 'root', wraps=files.root) as roots:
                    self.assertEqual(problem_store.get_solution_pdf('synthetic', 'supabase'), PDF)
                    self.assertEqual(roots.call_args_list[0].args, (True,))
                    self.assertEqual(roots.call_count, 1)
                with self.assertRaises(problem_store.ProblemNotFound):
                    problem_store.get_solution_pdf('missing', 'supabase')
                path = next((base/'public').glob('*.blob'))
                path.chmod(0o600)
                path.write_bytes(b'%PDF-CORRUPT')
                path.chmod(0o400)
                with self.assertRaises(problem_store.ProblemUnavailable):
                    problem_store.get_solution_pdf('synthetic', 'supabase')
                with self.assertRaises(problem_store.ProblemNotFound):
                    problem_store.get_solution_pdf('../private', 'supabase')
