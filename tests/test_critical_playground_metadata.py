"""Cold/warm custom-input jobs use limits metadata without private test bytes."""
from contextlib import ExitStack
import unittest
from unittest.mock import patch

import grader
import problem_store
from critical_helpers import test_server, patch_server_state
from judge_runner import run_isolated


def metadata_problem():
    return grader.Problem('metadata_only', 'Metadata only', 1.25, 96, 'token',
                          0.000001, '', [], samples=[], is_published=True)


class PlaygroundMetadataTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.server = test_server()
        self.problem = metadata_problem()
        stack = ExitStack()
        self.addCleanup(stack.close)
        for name, value in (('GRADER_ROLE', 'worker'), ('QUEUE_MODE', 'database'),
                            ('PROBLEM_SOURCE', 'supabase'), ('MEMORY_CAP_MB', 128),
                            ('PROBLEMS', {self.problem.pid: self.problem}), ('_jobs', {})):
            stack.enter_context(patch_server_state(self.server, name, value))
        stack.enter_context(patch.object(problem_store, 'load_problem_supabase',
                                        side_effect=AssertionError('private suite load')))
        stack.enter_context(patch.object(problem_store, '_download',
                                        side_effect=AssertionError('private file download')))

    def job(self):
        return {'id': 'synthetic-cold-playground', 'kind': 'playground',
                'problem': self.problem.pid, 'language': 'python',
                'source': 'print(input().upper())',
                'payload': {'stdin_data': 'load probe\n', 'time_limit': 1.25, 'memory_mb': 96}}

    async def test_cold_selected_problem_reaches_real_runner_with_limits_and_custom_input(self):
        completion = await self.server._prepare_and_judge(self.job(), run_isolated)
        self.assertEqual(completion.error, '')
        self.assertEqual(completion.result['verdict'], 'OK')
        self.assertEqual(completion.result['stdout'], 'LOAD PROBE\n')
        self.assertEqual(completion.result['limits']['problem'], self.problem.pid)
        self.assertEqual(completion.result['limits']['memory_mb'], 96)
        self.assertEqual(completion.result['limits']['time_s'], 1.25)

    async def test_local_selected_problem_also_embeds_metadata_without_child_disk_load(self):
        with patch.object(self.server, 'PROBLEM_SOURCE', 'local'):
            completion = await self.server._prepare_and_judge(self.job(), run_isolated)
        self.assertEqual(completion.error, '')
        self.assertEqual(completion.result['stdout'], 'LOAD PROBE\n')

    async def test_warm_cached_suite_is_not_read_or_embedded_for_custom_input(self):
        class PrivateCase:
            name = 'private-case'
            @property
            def input(self):
                raise AssertionError('private input accessed by playground')
            @property
            def expected(self):
                raise AssertionError('private expected output accessed by playground')
        self.problem.tests = [PrivateCase()]
        captured = []
        async def execute(kind, payload, timeout):
            captured.append(payload)
            self.assertEqual(kind, 'playground')
            self.assertFalse(payload['problem_data'].get('tests'))
            return {'verdict': 'OK', 'stdout': 'LOAD PROBE\n'}
        completion = await self.server._prepare_and_judge(self.job(), execute)
        self.assertEqual(completion.error, '')
        self.assertEqual(len(captured), 1)

    async def test_submission_still_refuses_an_empty_embedded_suite(self):
        payload = {'problem': self.problem.pid,
                   'problem_data': problem_store.serialize_problem(self.problem),
                   'ext': '.py', 'source': 'print(1)', 'reveal': 'none',
                   'memory_cap_mb': 128, 'judge_jobs': 1}
        with self.assertRaises(problem_store.ProblemUnavailable):
            problem_store.deserialize_problem(payload['problem_data'])
        with self.assertRaisesRegex(RuntimeError, 'subprocess exited unsuccessfully'):
            await run_isolated('submission', payload, 10)

    async def test_unpublished_problem_is_refused_before_runner(self):
        self.problem.is_published = False
        async def execute(*args):
            self.fail('unpublished problem executed')
        completion = await self.server._prepare_and_judge(self.job(), execute)
        self.assertIn('unknown problem', completion.error)
