"""The isolated judge must work without loading the HTTP/database stack."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import mock_open, patch

import grader
import judge_execution


class ExecutionStartupTests(unittest.TestCase):
    def test_job_entrypoint_does_not_import_web_or_database(self):
        # Refuse these imports, including accidentally reading server/.env,
        # while exercising the real JSON job entrypoint and shared executor.
        code = '''
import importlib.abc, io, json, sys
class RefuseWeb(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'server', 'submission_disclosure', 'fastapi', 'supabase', 'email_auth'}:
            raise AssertionError('web/database import: ' + fullname)
sys.meta_path.insert(0, RefuseWeb())
import judge_runner, grader, problem_store
problem_store.deserialize_problem = lambda _: grader.Problem(
    'empty', 'Empty', 1, 128, 'token', 0.000001, '', [], samples=[])
sys.stdin = io.StringIO(json.dumps({'kind': 'submission', 'payload': {
    'memory_cap_mb': 128, 'judge_jobs': 1, 'problem': 'empty',
    'problem_data': {'pid': 'empty', 'title': 'Empty', 'time_limit': 1,
        'memory_limit': 128, 'checker': 'token', 'tolerance': 0.000001,
        'description': '', 'tests': [], 'samples': []},
    'ext': '.py', 'source': 'print(1)', 'reveal': 'none'}}))
raise SystemExit(judge_runner._job())
'''
        result = subprocess.run([sys.executable, '-c', code], capture_output=True,
                                text=True, cwd=Path(__file__).resolve().parents[1], timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'error': 'problem store unavailable (no tests)'})

    def test_explicit_budget_preserves_host_and_declared_limits(self):
        settings = judge_execution.Settings(128, 1, 1.0, 1024)
        tl, memory, limits = judge_execution._effective(None, 2.5, 256, settings)
        self.assertEqual((tl, memory), (2.5, 128))
        self.assertEqual(limits, {'time_s': 2.5, 'memory_mb': 128,
            'declared_mb': 256, 'capped': True, 'host_memory_mb': 1024,
            'host_cpu': 1.0, 'problem': ''})

    def test_linux_reaped_and_zombie_samples_do_not_spawn_ps(self):
        for status in (None, 'Name:\tsynthetic\nState:\tZ (zombie)\n'):
            with self.subTest(status=status), patch.object(sys, 'platform', 'linux'), \
                    patch('builtins.open', mock_open(read_data=status or '')) as opened, \
                    patch.object(grader.subprocess, 'run') as ps:
                if status is None:
                    opened.side_effect = FileNotFoundError
                self.assertEqual(grader._sample_rss_mb(123), 0.0)
                ps.assert_not_called()

    def test_live_peak_and_non_linux_fallback_remain_available(self):
        with patch('builtins.open', mock_open(read_data='VmHWM:\t20480 kB\n')):
            self.assertEqual(grader._sample_rss_mb(123), 20.0)
        with patch.object(sys, 'platform', 'darwin'), \
                patch('builtins.open', side_effect=FileNotFoundError), \
                patch.object(grader.subprocess, 'run') as ps:
            ps.return_value.stdout = '10240\n'
            self.assertEqual(grader._sample_rss_mb(123), 10.0)
            ps.assert_called_once()
