"""Manual-audit regressions with synthetic identities/measurements; no live services."""
import asyncio
from contextlib import ExitStack
import datetime as dt
import json
import threading
import unittest
from unittest.mock import patch

from fastapi import HTTPException, Request
from fastapi.testclient import TestClient
from critical_helpers import synthetic_problem, test_server
from fake_supabase import FakeSupabase
import grader
import judge_execution

server = test_server()
EMAIL = 'audit-regression@example.invalid'


class AuditRegressions(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.db = FakeSupabase()
        self.problem = synthetic_problem()
        self.stack.enter_context(patch.object(server, '_sb', self.db))
        self.stack.enter_context(patch.object(server, 'PROBLEMS', {self.problem.pid: self.problem}))
        self.stack.enter_context(patch.object(server, '_ensure_problems_fresh'))
        self.stack.enter_context(patch.object(server, 'ADMIN_EMAILS', set()))
        self.db.rows('users').append({'email': EMAIL, 'name': 'Synthetic',
            'password_hash': server._hash_password('synthetic-password'),
            'email_verified_at': '2026-10-26T00:00:00Z', 'auth_version': 1})

    def request(self):
        return Request({'type': 'http', 'session': {'user': {'email': EMAIL}}})

    def test_critical_live_roles_share_identity_rpc_and_ignore_stale_snapshot(self):
        client = self.stack.enter_context(TestClient(server.app, base_url='https://testserver'))
        response = client.post('/api/auth/password', json={'email': EMAIL, 'password': 'synthetic-password'},
            headers={'Origin': server.FRONTEND_URL})
        self.assertEqual(response.status_code, 200, response.text)
        self.db.rows('admins').append({'email': EMAIL})
        with patch.object(self.db, 'rpc', wraps=self.db.rpc) as rpc:
            self.assertTrue(client.get('/api/auth/me').json()['is_admin'])
            self.assertEqual([call.args[0] for call in rpc.call_args_list], ['auth_session_identity'])
        self.db.tables['admins'] = []
        with patch.object(server, '_db_admin_emails', frozenset({EMAIL})):
            self.assertFalse(client.get('/api/auth/me').json()['is_admin'])
            self.assertEqual(client.get('/api/admin/account-audit').status_code, 403)
        self.assertIsNone(server._request_admin.get())

    def test_critical_old_schema_role_result_fails_closed_without_caching(self):
        token = 'a' * 43
        with patch.object(server, '_auth_rpc', return_value={'valid': True, 'user': {
                'email': EMAIL, 'auth_version': 1}}):
            with self.assertRaises(HTTPException) as exc:
                server._session_identity(token)
        self.assertEqual(exc.exception.status_code, 503)

    def test_critical_old_admin_refresh_cannot_restore_removed_authority(self):
        self.db.rows('admins').append({'email': EMAIL})
        entered, release = threading.Event(), threading.Event()
        original_table = self.db.table
        first = True
        lock = threading.Lock()

        def table(name):
            query = original_table(name)
            execute = query.execute
            def delayed():
                nonlocal first
                result = execute()
                with lock:
                    block = name == 'admins' and query._op == 'select' and first
                    if block:
                        first = False
                if block:
                    entered.set()
                    if not release.wait(5):
                        raise AssertionError('refresh was not released')
                return result
            query.execute = delayed
            return query

        with patch.object(self.db, 'table', side_effect=table), \
                patch.object(server, 'ADMIN_EMAILS', {'bootstrap@example.invalid'}), \
                patch.object(server, '_db_admin_emails', frozenset({EMAIL})):
            worker = threading.Thread(target=server._load_db_admins_sync)
            worker.start()
            try:
                self.assertTrue(entered.wait(5))
                actor = Request({'type': 'http', 'session': {'user': {'email': 'bootstrap@example.invalid'}}})
                self.assertTrue(asyncio.run(server.admin_remove_admin(actor, EMAIL))['ok'])
            finally:
                release.set()
                worker.join(5)
            self.assertFalse(worker.is_alive())
            self.assertFalse(server._is_admin(EMAIL))

    def test_critical_playground_uses_language_threshold_with_capped_memory(self):
        for ext, peak, verdict in [('.c', 128, 'OK'), ('.c', 129, 'OK'), ('.c', 130, 'MLE'),
                                   ('.cpp', 150, 'MLE'), ('.py', 321, 'OK'), ('.py', 322, 'MLE')]:
            for reason, forced in [('', verdict), ('timeout', 'TLE'), ('ole', 'OLE')]:
                with self.subTest(ext=ext, peak=peak, reason=reason), \
                        patch.object(grader, 'prepare_workspace'), \
                        patch.object(grader, 'prepare_command', return_value=(['synthetic'], '', '')), \
                        patch.object(grader, 'run_one', return_value={
                            'stdout': '', 'stderr': '', 'returncode': 0, 'peak_mb': peak, 'reason': reason}):
                    result = judge_execution._run_playground(None, ext, 'synthetic', '', 2, 256,
                        settings=judge_execution.Settings(128, 1, 1, 1024))
                    self.assertEqual(result['verdict'], forced)
                    self.assertTrue(result['memory_capped'])

    def test_critical_submission_uses_admission_time_but_rejudge_preserves_original(self):
        admitted = '2026-01-01T00:00:00+00:00'
        job = {'id': 'synthetic', 'problem': self.problem.pid, 'created_at': admitted}
        self.assertEqual(server._submission_row(job, {'results': []})['created_at'], admitted)
        job['target_id'] = 'existing-submission'
        self.assertNotIn('created_at', server._submission_row(job, {'results': []}))

    def test_critical_scoreboard_hides_legacy_email_fallbacks(self):
        now = dt.datetime.now(dt.timezone.utc)
        contest = {'id': 'audit-round', 'starts_at': (now-dt.timedelta(hours=1)).isoformat(),
                   'ends_at': (now+dt.timedelta(hours=1)).isoformat()}
        self.db.tables['submissions'] = [{'id': 'synthetic', 'contest_id': contest['id'],
            'user_email': EMAIL, 'name': EMAIL, 'score': 100, 'accepted': True,
            'problem': self.problem.pid, 'created_at': now.isoformat()}]
        board = server._contest_scoreboard(contest, False)
        self.assertEqual(board[0]['name'], 'นักเรียน')
        self.assertNotIn(EMAIL, json.dumps(board))

    def test_critical_export_exhausts_small_pages_and_rejects_later_failure(self):
        self.db.tables['submissions'] = [{'id': f'{i:03}', 'user_email': EMAIL, 'code': 'print(0)'}
                                        for i in range(120)]
        original_table = self.db.table
        for cap in (1, 50, 100):
            calls = []
            def table(name):
                query = original_table(name)
                execute = query.execute
                def capped():
                    result = execute()
                    if name == 'submissions':
                        calls.append(query._offset)
                        result.data = result.data[:cap]
                    return result
                query.execute = capped
                return query
            with self.subTest(cap=cap), patch.object(self.db, 'table', side_effect=table):
                result = json.loads(server.export_profile(self.request()).body)
                rows = result['data']['submissions']
                self.assertEqual(len(rows), 120)
                self.assertEqual(len({r['id'] for r in rows}), 120)
                self.assertEqual(calls[-1], 120)
        def failed_table(name):
            query = original_table(name)
            execute = query.execute
            def failed():
                if name == 'submissions' and query._offset:
                    raise RuntimeError('synthetic later page failure')
                return execute()
            query.execute = failed
            return query
        with patch.object(self.db, 'table', side_effect=failed_table):
            with self.assertRaises(HTTPException) as exc:
                server.export_profile(self.request())
        self.assertEqual(exc.exception.status_code, 503)

    def test_critical_policy_wait_does_not_block_an_independent_coroutine(self):
        entered, release = threading.Event(), threading.Event()
        def policy():
            entered.set()
            if not release.wait(5):
                raise AssertionError('event loop never released policy query')
            return []
        async def scenario():
            with patch.object(server, '_all_contest_rows', side_effect=policy), \
                    patch.object(server, '_contest_pid_cache', {'at': 0, 'all': set(), 'hide': set()}):
                task = asyncio.create_task(server.history(self.request()))
                try:
                    self.assertTrue(await asyncio.to_thread(entered.wait, 3))
                    self.assertFalse(task.done())
                finally:
                    release.set()
                await task
        asyncio.run(scenario())
