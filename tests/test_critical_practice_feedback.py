# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Owner-authorized failed practice I/O; contest boundaries stay closed."""
import asyncio
import contextlib
import copy
import datetime as dt
import os
import unittest
import uuid
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import grader
from critical_helpers import synthetic_problem, test_server
from fake_supabase import FakeSupabase

server = test_server()
ORIGINAL_CONTEST_POLICY = server._contest_policy_rows
EMAIL = 'practice-owner@example.invalid'


class CriticalPracticeFeedback(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.prob = synthetic_problem()
        self.canary = 'SYNTHETIC_PRACTICE_' + uuid.uuid4().hex
        self.prob.tests[1].input = self.canary + '\n'
        self.fake = FakeSupabase()
        self.contests = []
        self.email = EMAIL
        for key, value in {'PROBLEMS': {self.prob.pid: self.prob}, '_sb': self.fake,
                           'QUEUE_MODE': 'local', 'PROBLEM_SOURCE': 'local',
                           'JUDGE_JOBS': 1, 'MEMORY_CAP_MB': 128, '_jobs': {},
                           '_active_jobs': {}}.items():
            self.stack.enter_context(patch.object(server, key, value))
        self.stack.enter_context(patch.object(server, '_contest_policy_rows', side_effect=lambda **_kwargs: self.contests))
        # Peer detail reads the freshest contest policy from the DB, not the
        # cached feedback policy used by _effective_reveal.
        self.stack.enter_context(patch.object(server, '_all_contest_rows', side_effect=lambda: self.contests))
        self.stack.enter_context(patch.dict(os.environ, {'GRADER_REQUIRE_NETNS': '0'}))
        app = FastAPI()

        @app.middleware('http')
        async def identity(request: Request, call_next):
            request.scope['session'] = {'user': {'email': self.email}}
            return await call_next(request)

        app.get('/api/jobs/{jid}')(server.job_status)
        app.get('/api/history/{sid}')(server.history_detail)
        self.client = self.stack.enter_context(TestClient(app))

    def contest(self, *, upcoming=False, show_samples=True):
        now = dt.datetime.now(dt.timezone.utc)
        return {'id': 'synthetic-contest', 'problems': [self.prob.pid],
                'starts_at': (now + dt.timedelta(hours=1) if upcoming else now - dt.timedelta(hours=1)).isoformat(),
                'ends_at': (now + dt.timedelta(hours=2)).isoformat(), 'show_samples': show_samples}

    def execute(self, source, jobs=1, mode='local', contest_id=None):
        job = {'id': str(uuid.uuid4()), 'kind': 'submit', 'problem': self.prob.pid,
               'language': 'python', 'source': source, 'name': 'Synthetic',
               'status': 'queued', 'created_at': server._iso_now(), 'user_email': EMAIL,
               'reveal': server.REVEAL_PRACTICE, 'contest_id': contest_id}
        server._jobs[job['id']] = job
        self.fake.table('judge_jobs').insert(copy.deepcopy(job)).execute()
        captured = {}

        async def rpc(action, **params):
            if action == 'heartbeat': return True
            captured.update(params)
            return {'applied': True}

        with patch.object(server, 'JUDGE_JOBS', jobs), patch.object(server, 'QUEUE_MODE', mode):
            if mode == 'database':
                job.update(worker_id='synthetic-worker', attempt=1)
                with patch.object(server, '_queue_rpc', side_effect=rpc):
                    asyncio.run(server._run_job(job))
                return job, captured['p_result'], captured['p_submission']
            asyncio.run(server._run_job(job))
        self.assertEqual(job['status'], 'done', job.get('error'))
        return job, self.fake.tables['judge_jobs'][-1]['result'], self.fake.tables['submissions'][-1]

    def test_critical_failed_practice_io_survives_job_history_and_persistence(self):
        for mode, jobs in (('local', 1), ('database', 2)):
            with self.subTest(mode=mode):
                job, stored, row = self.execute('import sys\nprint(sys.stdin.read())\n', jobs, mode)
                for results in (stored['results'], row['results']):
                    hidden = next(r for r in results if r['test'] == '1001')
                    self.assertEqual(hidden['verdict'], 'WA')
                    self.assertEqual(hidden['input'], self.canary + '\n')
                    self.assertIn(self.canary, hidden['actual'])
                    self.assertIn('expected', hidden)
                    self.assertFalse(hidden.get('hidden'))
                if mode == 'local':
                    for url in ('/api/jobs/' + job['id'], '/api/history/' + row['id']):
                        response = self.client.get(url)
                        self.assertEqual(response.status_code, 200)
                        self.assertIn(self.canary, response.text)

    def test_critical_failed_practice_runtime_stderr_and_partial_stdout_are_available(self):
        _, stored, row = self.execute("import sys\nprint('partial',flush=True)\nsys.stderr.write(sys.stdin.read())\nsys.exit(7)\n")
        for results in (stored['results'], row['results']):
            hidden = next(r for r in results if r['test'] == '1001')
            self.assertEqual(hidden['verdict'], 'RE')
            self.assertIn(self.canary, hidden['detail'])
            self.assertEqual(hidden['actual'], 'partial\n')

    def test_critical_practice_accepted_cases_remain_redacted(self):
        _, stored, row = self.execute("print('hello')\n")
        for results in (stored['results'], row['results']):
            hidden = next(r for r in results if r['test'] == '1001')
            self.assertEqual(hidden['verdict'], 'AC')
            self.assertTrue(hidden['hidden'])
            self.assertFalse({'input','expected','actual','diff','practice_feedback'} & hidden.keys())

    def test_critical_omitting_contest_parameter_never_opens_protected_problem(self):
        self.assertEqual(server._effective_reveal(None, EMAIL, self.prob.pid), server.REVEAL_PRACTICE)
        for upcoming in (False, True):
            for samples in (False, True):
                self.contests[:] = [self.contest(upcoming=upcoming, show_samples=samples)]
                expected = server.REVEAL_NONE if not upcoming and not samples else server.REVEAL_SAMPLES
                self.assertEqual(server._effective_reveal(None, EMAIL, self.prob.pid), expected)
                self.assertNotEqual(server._effective_reveal(self.contests[0], EMAIL, self.prob.pid), server.REVEAL_PRACTICE)

    def test_critical_feedback_eligibility_bypasses_stale_cross_replica_contest_cache(self):
        with patch.object(server, '_contest_policy_rows', wraps=ORIGINAL_CONTEST_POLICY), \
                patch.object(server, '_cached_contest_rows', return_value=[]) as cached, \
                patch.object(server, '_all_contest_rows', return_value=[self.contest()]) as fresh:
            self.assertEqual(server._effective_reveal(None, EMAIL, self.prob.pid), server.REVEAL_SAMPLES)
            fresh.assert_called_once_with()
            cached.assert_not_called()

    def test_critical_policy_outage_and_invalid_contest_time_fail_closed(self):
        with patch.object(server, '_contest_policy_rows', side_effect=RuntimeError('synthetic outage')):
            self.assertEqual(server._effective_reveal(None, EMAIL, self.prob.pid), server.REVEAL_NONE)
        for bad in (None, 'invalid', '2026-10-18T00:00:00'):
            self.contests[:] = [self.contest() | {'ends_at': bad}]
            self.assertEqual(server._effective_reveal(None, EMAIL, self.prob.pid), server.REVEAL_NONE)

    def test_critical_prior_practice_history_and_job_are_redacted_when_contest_is_scheduled(self):
        job, _, row = self.execute('print("wrong")\n')
        self.contests[:] = [self.contest(upcoming=True)]
        for url in ('/api/jobs/' + job['id'], '/api/history/' + row['id']):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(self.canary, response.text)
        self.email = 'another-user@example.invalid'
        self.assertEqual(self.client.get('/api/jobs/' + job['id']).status_code, 404)
        self.assertEqual(self.client.get('/api/history/' + row['id']).status_code, 403)
        self.email = ''
        self.assertEqual(self.client.get('/api/jobs/' + job['id']).status_code, 401)
        self.assertEqual(self.client.get('/api/history/' + row['id']).status_code, 401)

    def test_critical_contest_result_cannot_opt_into_practice_storage(self):
        _, stored, row = self.execute('import sys\nprint(sys.stdin.read())\n', contest_id='synthetic-contest')
        for results in (stored['results'], row['results']):
            hidden = next(r for r in results if r['test'] == '1001')
            self.assertTrue(hidden['hidden'])
            self.assertFalse({'input','expected','actual','diff','practice_feedback'} & hidden.keys())

    def test_critical_limit_feedback_is_available_only_with_explicit_practice_marker(self):
        for verdict in ('WA', 'RE', 'TLE', 'MLE', 'OLE'):
            raw = {'test':'1001','verdict':verdict,'input':self.canary,'expected':'ok',
                   'actual':'partial','detail':self.canary,'practice_feedback':True}
            result = server._redact_results([raw], server.REVEAL_PRACTICE)[0]
            self.assertEqual(result['input'], self.canary)
            unmarked = {k:v for k,v in raw.items() if k != 'practice_feedback'}
            self.assertNotIn('input', server._redact_results([unmarked], server.REVEAL_PRACTICE)[0])
            for reveal in (server.REVEAL_SAMPLES, server.REVEAL_NONE):
                redacted = server._redact_results([raw], reveal)[0]
                self.assertNotIn('input', redacted)
                self.assertNotIn(self.canary, redacted.get('detail', ''))
