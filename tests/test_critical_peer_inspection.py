"""Synthetic peer-source access: historical attempts, fresh policy, safe JSON."""
import contextlib
import datetime as dt
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from critical_helpers import synthetic_problem, test_server
from fake_supabase import FakeSupabase

server = test_server()
REAL_ALL_CONTEST_ROWS = server._all_contest_rows
VIEWER = 'peer-viewer@example.invalid'
AUTHOR = 'peer-author@example.invalid'
CANARY = 'PRIVATE_TEST_AND_DIAGNOSTIC_CANARY'


class CriticalPeerInspection(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.prob = synthetic_problem()
        self.db = FakeSupabase()
        self.email = VIEWER
        self.contests = []
        self.stack.enter_context(patch.object(server, '_sb', self.db))
        self.stack.enter_context(patch.object(server, 'PROBLEMS', {self.prob.pid: self.prob}))
        self.stack.enter_context(patch.object(server, '_is_admin', side_effect=lambda e: e == 'admin@example.invalid'))
        self.stack.enter_context(patch.object(server, '_all_contest_rows', side_effect=lambda: self.contests))
        self.stack.enter_context(patch.object(server, '_contest_pid_cache', {'at': 0, 'all': set(), 'hide': set()}))
        self.target = self.row('peer', AUTHOR)
        self.db.rows('submissions').append(self.target)
        app = FastAPI()

        @app.middleware('http')
        async def identity(request: Request, call_next):
            request.scope['session'] = {'user': {'email': self.email}}
            return await call_next(request)

        app.get('/api/history')(server.history)
        app.get('/api/history/{sid}')(server.history_detail)
        app.middleware('http')(server._security_headers)
        self.client = self.stack.enter_context(TestClient(app, raise_server_exceptions=False))

    def row(self, sid, email=VIEWER, verdict='REJECTED', counts=None, **extra):
        row = {'id': sid, 'created_at': '2026-01-01T00:00:00+00:00',
               'user_email': email, 'problem': self.prob.pid, 'kind': 'submit',
               'verdict': verdict, 'accepted': verdict == 'AC',
               'counts': {'WA': 1} if counts is None else counts,
               'passed': 0, 'total': 1, 'score': 0, 'name': 'Peer Display Name',
               'language': 'python', 'filename': 'peer.py', 'code': 'print("peer source")',
               'results': [{'verdict': next(iter(counts or {'WA': 1})),
                            'wall_s': 0.1, 'cpu_s': 0.05, 'peak_mb': 8}],
               'contest_id': None}
        return row | extra

    def qualify(self, **extra):
        row = self.row('qualifying', **extra)
        self.db.rows('submissions').append(row)
        return row

    def get(self):
        return self.client.get('/api/history/peer')

    def contest(self, window='running', **extra):
        now = dt.datetime.now(dt.timezone.utc)
        bounds = {'running': (-1, 1), 'upcoming': (1, 2), 'ended': (-2, -1)}[window]
        return {'id': 'cup', 'problems': [self.prob.pid], 'hide_from_tasks': False,
                'starts_at': (now + dt.timedelta(hours=bounds[0])).isoformat(),
                'ends_at': (now + dt.timedelta(hours=bounds[1])).isoformat()} | extra

    def test_critical_allowed_completed_verdicts_unlock_peer_source(self):
        for verdict in ('AC', 'WA', 'TLE', 'MLE', 'OLE'):
            for top in (verdict, 'AC' if verdict == 'AC' else 'REJECTED'):
                with self.subTest(verdict=verdict, top=top):
                    self.db.rows('submissions')[:] = [self.target]
                    self.qualify(verdict=top, counts={verdict: 1})
                    response = self.get()
                    self.assertEqual(response.status_code, 200, response.text)
                    self.assertEqual(response.json()['code'], 'print("peer source")')
                    self.assertEqual(response.json()['name'], 'Peer Display Name')

    def test_critical_missing_ce_re_and_mixed_runtime_attempts_stay_locked(self):
        cases = [None, {'verdict': 'CE', 'counts': {'CE': 1}},
                 {'verdict': 'RE', 'counts': {'RE': 1}},
                 {'counts': {'RE': 1}}, {'counts': {'WA': 1, 'RE': 1}},
                 {'counts': {'WA': 1, 'CE': 1}}, {'verdict': 'AC', 'counts': {'RE': 1}},
                 {'kind': 'playground'}, {'status': 'queued'}, {'status': 'running'},
                 {'status': 'error'}, {'verdict': 'RUNNING'}, {'verdict': 'UNKNOWN'},
                 {'counts': {}}, {'counts': {'WA': '1'}}, {'counts': {'WA': -1}},
                 {'counts': {'WA': 1, 'UNKNOWN': 1}}, {'counts': []},
                 {'results': [{'verdict': 'RE'}]}, {'results': [{'verdict': 'UNKNOWN'}]}]
        for attempt in cases:
            with self.subTest(attempt=attempt):
                self.db.rows('submissions')[:] = [self.target]
                if attempt is not None:
                    self.qualify(**attempt)
                self.assertEqual(self.get().status_code, 403)

    def test_critical_legacy_explicit_verdict_without_counts_can_unlock(self):
        self.qualify(verdict='TLE', counts={}, results=[])
        self.assertEqual(self.get().status_code, 200)

    def test_critical_historical_attempt_survives_recent_feed_window_and_restart(self):
        self.qualify(created_at='2020-01-01T00:00:00+00:00')
        self.db.rows('submissions').extend(
            self.row('new-' + str(i), verdict='REJECTED', counts={'RE': 1},
                     created_at='2026-10-01T00:00:00+00:00') for i in range(550))
        # No process-local eligibility state is available or necessary.
        with patch.object(server, '_jobs', {}):
            self.assertEqual(self.get().status_code, 200)

    def test_critical_history_pagination_handles_lower_database_response_caps(self):
        self.qualify(created_at='2020-01-01T00:00:00+00:00')
        self.db.rows('submissions').extend(
            self.row('new-' + str(i), counts={'RE': 1}) for i in range(80))
        original = self.db.table

        def table(name):
            query = original(name)
            execute = query.execute

            def capped_execute():
                response = execute()
                if getattr(query, '_cols', '') == 'id,kind,verdict,counts':
                    response.data = response.data[:37]
                return response

            query.execute = capped_execute
            return query

        with patch.object(self.db, 'table', side_effect=table):
            self.assertEqual(self.get().status_code, 200)

    def test_critical_only_same_viewer_same_problem_attempt_counts(self):
        for extra in ({'email': 'other@example.invalid'}, {'problem': 'another-problem'}):
            with self.subTest(extra=extra):
                self.db.rows('submissions')[:] = [self.target]
                self.qualify(**extra)
                self.assertEqual(self.get().status_code, 403)

    def test_critical_any_completed_peer_target_verdict_is_readable(self):
        self.qualify()
        for verdict in ('CE', 'RE', 'WA', 'TLE', 'MLE', 'OLE', 'AC', 'REJECTED'):
            with self.subTest(verdict=verdict):
                self.target['verdict'] = verdict
                self.assertEqual(self.get().status_code, 200)
        for status in ('queued', 'running', 'error'):
            self.target['status'] = status
            self.assertEqual(self.get().status_code, 403)

    def test_critical_upcoming_running_and_reused_contests_block_every_peer_row(self):
        self.qualify()
        for window in ('upcoming', 'running'):
            for target_contest in (None, 'ended-cup'):
                with self.subTest(window=window, target_contest=target_contest):
                    self.target['contest_id'] = target_contest
                    self.contests[:] = [self.contest('ended', id='ended-cup'), self.contest(window)]
                    response = self.get()
                    self.assertEqual(response.status_code, 403)
                    self.assertIn('contest', response.json()['detail'])

    def test_critical_ended_contest_allows_peer_inspection(self):
        self.qualify()
        self.contests[:] = [self.contest('ended')]
        self.target['contest_id'] = 'cup'
        self.assertEqual(self.get().status_code, 200)

    def test_critical_target_contest_missing_from_current_policy_fails_closed(self):
        self.qualify()
        self.target['contest_id'] = 'missing-cup'
        self.assertEqual(self.get().status_code, 403)

    def test_critical_ended_hidden_problem_is_discoverable_in_its_submission_tab(self):
        self.qualify()
        self.prob.hidden = True
        self.contests[:] = [self.contest('ended', hide_from_tasks=True)]
        response = self.client.get('/api/history?problem=' + self.prob.pid)
        self.assertEqual(response.status_code, 200)
        self.assertIn('peer', [row['id'] for row in response.json()['submissions']])
        self.assertTrue(response.json()['peer_access']['allowed'])
        global_feed = self.client.get('/api/history').json()['submissions']
        self.assertNotIn('peer', [row['id'] for row in global_feed])

    def test_critical_new_contest_policy_bypasses_stale_visibility_cache(self):
        self.qualify()
        with patch.object(server, '_cached_contest_rows', return_value=[]):
            self.assertEqual(self.get().status_code, 200)
            self.contests.append(self.contest('upcoming'))
            self.assertEqual(self.get().status_code, 403)

    @contextlib.contextmanager
    def capped_real_contest_policy(self, *, second_page=None):
        original = self.db.table

        def table(name):
            query = original(name)
            execute = query.execute

            def capped_execute():
                if name == 'contests' and query._offset and second_page:
                    if second_page == 'outage':
                        raise RuntimeError('synthetic second-page policy outage')
                    response = execute()
                    response.data = None
                    return response
                response = execute()
                if name == 'contests':
                    response.data = response.data[:1]
                return response

            query.execute = capped_execute
            return query

        with patch.object(server, '_all_contest_rows', REAL_ALL_CONTEST_ROWS), \
                patch.object(self.db, 'table', side_effect=table):
            yield

    def test_critical_real_policy_pagination_cannot_hide_a_protected_contest(self):
        self.qualify()
        for window in ('upcoming', 'running'):
            with self.subTest(window=window):
                unrelated = self.contest('upcoming', id='unrelated', problems=['another-problem'],
                                         starts_at='2099-01-01T00:00:00+00:00')
                self.db.rows('contests')[:] = [unrelated, self.contest(window)]
                with self.capped_real_contest_policy():
                    response = self.get()
                self.assertEqual(response.status_code, 403, response.text)
                self.assertNotIn('peer source', response.text)

    def test_critical_real_policy_subsequent_page_outage_or_malformed_page_fails_closed(self):
        self.qualify()
        self.db.rows('contests')[:] = [self.contest('ended', problems=['another-problem'])]
        for failure in ('outage', 'malformed'):
            with self.subTest(failure=failure), self.capped_real_contest_policy(second_page=failure):
                response = self.get()
                self.assertEqual(response.status_code, 503, response.text)
                self.assertNotIn('peer source', response.text)

    def test_critical_real_policy_equal_start_times_have_stable_id_order(self):
        contest = self.contest('ended')
        self.db.rows('contests')[:] = [contest | {'id': sid} for sid in ('a', 'z', 'm')]
        with self.capped_real_contest_policy():
            self.assertEqual([row['id'] for row in server._all_contest_rows()], ['z', 'm', 'a'])

    def test_critical_policy_outage_and_invalid_dates_fail_closed(self):
        self.qualify()
        for exc in (RuntimeError('outage'), RuntimeError('relation "public.contests" does not exist')):
            with patch.object(server, '_all_contest_rows', side_effect=exc):
                response = self.get()
                self.assertIn(response.status_code, (403, 503))
                self.assertNotIn('peer source', response.text)
        for bad in (None, 'invalid', '2026-01-01T00:00:00'):
            self.contests[:] = [self.contest('ended', ends_at=bad)]
            self.assertEqual(self.get().status_code, 403)
        self.contests[:] = [self.contest('ended', starts_at='2030-01-01T00:00:00+00:00')]
        self.assertEqual(self.get().status_code, 403)

    def test_critical_qualifying_query_outage_cannot_unlock(self):
        self.qualify()
        original = self.db.table

        def table(name):
            query = original(name)
            original_eq = query.eq

            def eq(column, value):
                if name == 'submissions' and column == 'user_email':
                    raise RuntimeError('synthetic eligibility outage')
                return original_eq(column, value)

            query.eq = eq
            return query

        with patch.object(self.db, 'table', side_effect=table):
            self.assertIn(self.get().status_code, (403, 503))

    def test_critical_anonymous_owner_and_admin_boundaries(self):
        self.email = ''
        self.assertEqual(self.get().status_code, 401)
        self.contests[:] = [self.contest('running')]
        for email in (AUTHOR, 'admin@example.invalid'):
            self.email = email
            self.assertEqual(self.get().status_code, 200)

    def test_critical_peer_json_has_only_source_and_public_result_fields(self):
        self.qualify()
        self.target.update({'detail': CANARY, 'compile_error': CANARY,
                            'future_private_field': {'login_email': AUTHOR, 'secret': CANARY}})
        self.target['counts']['future_private_field'] = CANARY
        self.target['results'][0].update({key: CANARY for key in
            ('input', 'expected', 'actual', 'diff', 'detail', 'stderr', 'test', 'future_private_field')})
        self.target['results'][0]['nested_private'] = {'email': AUTHOR}
        response = self.get()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertNotIn(CANARY, response.text)
        self.assertNotIn(AUTHOR, response.text)
        row = response.json()
        self.assertEqual(row['language'], 'python')
        self.assertEqual(row['filename'], 'peer.py')
        self.assertEqual(row['results'], [{'verdict': 'WA', 'wall_s': 0.1,
                                         'cpu_s': 0.05, 'peak_mb': 8, 'hidden': True}])
        self.assertTrue(row['peer_inspection'])

    def test_critical_peer_measurement_fields_cannot_carry_nested_private_data(self):
        self.qualify()
        self.target['results'] = [{'verdict': {'private': CANARY}, 'wall_s': [CANARY],
                                  'cpu_s': {'private': CANARY}, 'peak_mb': float('nan')}]
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(CANARY, response.text)
        self.assertEqual(response.json()['results'], [{'verdict': 'UNKNOWN', 'hidden': True,
                                                      'wall_s': None, 'cpu_s': None, 'peak_mb': None}])

    def test_critical_public_feed_never_contains_code_email_or_private_fields(self):
        self.target.update(detail=CANARY, future_private_field=CANARY)
        self.target['counts']['future_private_field'] = CANARY
        response = self.client.get('/api/history?problem=' + self.prob.pid)
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(CANARY, response.text)
        self.assertNotIn(AUTHOR, response.text)
        self.assertNotIn('peer source', response.text)
        self.assertNotIn('results', response.json()['submissions'][0])

    def test_critical_legacy_name_email_fallback_is_not_a_public_display_name(self):
        self.qualify()
        self.target['name'] = AUTHOR
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertNotIn(AUTHOR, response.text)
        public = self.client.get('/api/history?problem=' + self.prob.pid)
        self.assertNotIn(AUTHOR, public.text)

    def test_critical_publication_and_hidden_visibility_are_enforced_for_peers(self):
        self.qualify()
        self.prob.is_published = False
        self.assertIn(self.get().status_code, (403, 404))
        self.prob.is_published = True
        self.prob.hidden = True
        self.assertIn(self.get().status_code, (403, 404))
        self.contests[:] = [self.contest('ended')]
        self.assertEqual(self.get().status_code, 200)

    def test_critical_owner_keeps_existing_practice_feedback(self):
        self.email = AUTHOR
        self.target['results'][0].update(practice_feedback=True, input=CANARY,
                                         expected='ok', actual='wrong')
        response = self.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['results'][0]['input'], CANARY)

    def test_critical_history_responses_are_not_stored_by_http_caches(self):
        self.email = AUTHOR
        for path in ('/api/history/peer', '/api/history?problem=' + self.prob.pid):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn('no-store', response.headers.get('cache-control', ''))
