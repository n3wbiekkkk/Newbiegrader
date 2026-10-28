"""Single-worker correctness gates; synthetic fixtures, no live services."""
import asyncio
from contextlib import ExitStack
import os
import unittest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException, Request
from critical_helpers import synthetic_problem, test_server
from critical_helpers import patch_server_state

server = test_server()


class CriticalReleaseCorrectness(unittest.TestCase):
    def test_critical_job_status_and_result_share_one_observation_snapshot(self):
        owner = 'snapshot-owner@example.invalid'
        job = {'id': 'snapshot', 'status': 'queued', 'user_email': owner}
        project = server._disclosure.job_result

        def complete_during_policy_read(snapshot):
            job.update(status='done', result={'score': 100, 'results': []})
            return project(snapshot)

        with patch.object(server, 'QUEUE_MODE', 'local'), \
                patch.object(server, '_jobs', {'snapshot': job}), \
                patch.object(server, '_queue_position_hint', new_callable=AsyncMock, return_value=0), \
                patch.object(server._disclosure, 'job_result', side_effect=complete_during_policy_read):
            response = asyncio.run(server.job_status(Request({'type': 'http',
                'session': {'user': {'email': owner}}}), 'snapshot'))
        self.assertEqual(job['status'], 'done')
        self.assertEqual(response['status'], 'queued')
        self.assertIsNone(response['result'])

    def test_critical_changed_admitted_version_never_executes_or_persists_verdict(self):
        prob = synthetic_problem()
        with patch.object(server, 'GRADER_ROLE', 'worker'), \
                patch.object(server, 'PROBLEM_SOURCE', 'supabase'), \
                patch.object(server.problem_store, 'load_problem_supabase', return_value=prob) as load, \
                patch.object(server, 'QUEUE_MODE', 'local'), \
                patch.object(server, '_sb', None), \
                patch.object(server, '_jobs', {}) as observations, \
                patch('judge_runner.run_isolated', new_callable=AsyncMock) as run:
            asyncio.run(server._run_job({'id': 'synthetic', 'kind': 'submit',
                        'problem': prob.pid, 'tests_hash': 'different-version'}))
        self.assertEqual(load.call_count, 1)
        run.assert_not_called()
        self.assertIn('version changed', observations['synthetic']['error'])
        self.assertNotIn('result', observations['synthetic'])


    def test_critical_api_only_service_does_not_need_memory_for_a_judge(self):
        with patch.dict(os.environ,{'GRADER_MEMORY_CAP_MB':'128','SESSION_SECRET':'synthetic-api-budget'}), \
                patch.object(server,'JUDGE_WORKERS',0),patch.object(server,'GRADER_ROLE','api'), \
                patch.object(server,'QUEUE_MODE','database'),patch.object(server,'PROBLEM_SOURCE','local'), \
                patch.object(server,'_queue_rpc',new_callable=AsyncMock) as rpc:
            self.assertEqual(server._derive_capacity(.25,320)['workers'],0)
            asyncio.run(server.validate_runtime())
            rpc.assert_awaited_once_with('diagnostics')
            for role in ('worker','combined'):
                with patch.object(server,'GRADER_ROLE',role):
                    with self.assertRaisesRegex(RuntimeError,'host RAM'):
                        asyncio.run(server.validate_runtime())


    def test_critical_admission_never_downloads_private_tests_and_requires_a_version(self):
        prob = synthetic_problem()
        request = Request({'type': 'http', 'session': {'user': {
            'email': 'synthetic-admission@example.invalid', 'name': 'Synthetic'}}})
        for version in ('admitted-version', None):
            with self.subTest(version_present=version is not None), ExitStack() as stack:
                for name, value in {
                        'QUEUE_MODE': 'database', 'PROBLEM_SOURCE': 'supabase',
                        '_TESTS_HASH_CACHE': {prob.pid: version} if version else {}}.items():
                    stack.enter_context(patch_server_state(server, name, value))
                stack.enter_context(patch.object(server, '_ensure_problems_fresh'))
                stack.enter_context(patch.object(server, '_meta_or_404', return_value=prob))
                stack.enter_context(patch.object(server, '_visible_to', return_value=True))
                stack.enter_context(patch.object(server, '_profile_display_name', return_value='Synthetic'))
                stack.enter_context(patch.object(server._disclosure, 'admission_reveal', return_value='samples'))
                stack.enter_context(patch.object(server, '_queue_rpc', new_callable=AsyncMock, return_value={'queued': 0}))
                full = stack.enter_context(patch.object(server, '_problem_or_404', side_effect=AssertionError('private suite loaded during admission')))
                download = stack.enter_context(patch.object(server.problem_store, 'load_problem_supabase', side_effect=AssertionError('private tests downloaded')))
                create = stack.enter_context(patch.object(server, '_create_job', new_callable=AsyncMock,
                                                          return_value={'id': 'synthetic', 'status': 'queued'}))
                if version:
                    result = asyncio.run(server.submit(request, prob.pid, 'python', 'print("hello")', None, '', ''))
                    self.assertEqual(result['job_id'], 'synthetic')
                    self.assertEqual(create.call_args.args[0]['tests_hash'], version)
                else:
                    with self.assertRaises(HTTPException) as exc:
                        asyncio.run(server.submit(request, prob.pid, 'python', 'print("hello")', None, '', ''))
                    self.assertEqual(exc.exception.status_code, 503)
                    create.assert_not_awaited()
                full.assert_not_called()
                download.assert_not_called()

    def test_critical_worker_problem_failure_never_runs_or_persists_a_verdict(self):
        with patch.object(server, 'PROBLEM_SOURCE', 'supabase'), \
                patch.object(server.problem_store, 'load_problem_supabase',
                             side_effect=server.problem_store.ProblemUnavailable('synthetic source error')), \
                patch.object(server, 'QUEUE_MODE', 'local'), \
                patch.object(server, '_sb', None), \
                patch.object(server, '_jobs', {}) as observations, \
                patch('judge_runner.run_isolated', new_callable=AsyncMock) as run:
            asyncio.run(server._run_job({'id': 'synthetic', 'kind': 'submit',
                        'problem': 'synthetic', 'tests_hash': 'admitted-version'}))
        run.assert_not_called()
        self.assertEqual(observations['synthetic']['error'], 'problem store unavailable')
        self.assertNotIn('result', observations['synthetic'])

    def test_critical_committed_job_is_returned_when_optional_queue_diagnostics_fail(self):
        prob = synthetic_problem()
        request = Request({'type': 'http', 'session': {'user': {
            'email': 'synthetic-admission@example.invalid'}}})
        with ExitStack() as stack:
            for name, value in {'QUEUE_MODE': 'database', 'PROBLEM_SOURCE': 'supabase',
                                '_TESTS_HASH_CACHE': {prob.pid: 'admitted-version'}}.items():
                stack.enter_context(patch_server_state(server, name, value))
            stack.enter_context(patch.object(server, '_ensure_problems_fresh'))
            stack.enter_context(patch.object(server, '_meta_or_404', return_value=prob))
            stack.enter_context(patch.object(server, '_visible_to', return_value=True))
            stack.enter_context(patch.object(server, '_profile_display_name', return_value='Synthetic'))
            stack.enter_context(patch.object(server._disclosure, 'admission_reveal', return_value='samples'))
            stack.enter_context(patch.object(server, '_queue_rpc', new_callable=AsyncMock,
                                             side_effect=HTTPException(503, 'synthetic diagnostics outage')))
            create = stack.enter_context(patch.object(server, '_create_job', new_callable=AsyncMock,
                                                      return_value={'id': 'durably-admitted', 'status': 'queued'}))
            response = asyncio.run(server.submit(request, prob.pid, 'python', 'print("hello")', None, '', ''))
            self.assertEqual(response['job_id'], 'durably-admitted')
            self.assertEqual(response['status'], 'queued')
            self.assertIsNone(response['queued_ahead'])
            create.assert_awaited_once()
            stack.enter_context(patch.object(server, '_load_job', new_callable=AsyncMock, return_value={
                'id': 'durably-admitted', 'status': 'queued', 'user_email': 'synthetic-admission@example.invalid'}))
            response = asyncio.run(server.job_status(request, 'durably-admitted'))
            self.assertEqual(response['status'], 'queued')
            self.assertIsNone(response['queued_ahead'])

    def test_critical_native_qualification_refuses_an_ordinary_process(self):
        import subprocess
        import sys
        from pathlib import Path
        result = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] /
                                                     'tools/host_single_canary.py')],
                                env={**os.environ, 'GRADER_JOB_CGROUP_ROOT': 'not-approved'},
                                text=True, capture_output=True, timeout=5)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('REFUSED', result.stderr)
