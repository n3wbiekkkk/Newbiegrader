# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Synthetic DeepSeek review: query budgets, parity and fail-closed reads."""
from contextlib import ExitStack
import copy
import datetime as dt
import unittest
from unittest.mock import patch
from fastapi import Request, Response
from critical_helpers import synthetic_problem, test_server
from fake_supabase import FakeSupabase

server = test_server()


class OptimizationReview(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.fake = FakeSupabase()
        self.prob = synthetic_problem()
        self.now = dt.datetime.now(dt.timezone.utc)
        for key, value in {'_sb': self.fake, 'PROBLEMS': {self.prob.pid: self.prob},
                           '_reg_table_ok': {'value': True},
                           '_reg_count_cache': {'at': 0., 'counts': {}}}.items():
            self.stack.enter_context(patch.object(server, key, value))
        self.table = self.stack.enter_context(patch.object(self.fake, 'table', wraps=self.fake.table))

    def contest(self, cid):
        return {'id': cid, 'title': cid, 'problems': [self.prob.pid],
                'starts_at': (self.now - dt.timedelta(hours=1)).isoformat(),
                'ends_at': (self.now + dt.timedelta(minutes=10)).isoformat(),
                'freeze_minutes': 5}

    def test_list_query_budget_and_200_row_contract(self):
        for n in (0, 1, 200, 1200):
            with self.subTest(contests=n):
                server._reg_count_cache['at'] = 0
                rows = [self.contest(f'{i:04d}') for i in range(n)]
                self.fake.tables['contests'] = rows
                self.fake.tables['contest_registrations'] = [
                    {'contest_id': r['id'], 'user_email': 'one@example.invalid'} for r in rows]
                self.table.reset_mock()
                response = Response()
                listing = server.list_contests(Request({'type': 'http', 'session': {
                    'user': {'email': 'one@example.invalid'}}}), response)
                returned = min(n, 200)
                self.assertEqual(len(listing['contests']), returned)
                self.assertTrue(all(r['registered'] for r in listing['contests']))
                expected = 1 + (max(1, (n + 999) // 1000) if n else 0) + (returned + 99) // 100
                self.assertEqual(self.table.call_count, expected)
                self.assertEqual(response.headers['cache-control'], 'private, no-store')
                # Another account must not reuse the first account's registrations.
                other = server.list_contests(Request({'type': 'http', 'session': {
                    'user': {'email': 'two@example.invalid'}}}))
                self.assertTrue(all(not r['registered'] for r in other['contests']))

    def test_counts_do_not_truncate_after_5000_registrations(self):
        self.fake.tables['contest_registrations'] = [
            {'contest_id': 'c', 'user_email': f'{i:05d}@example.invalid'} for i in range(6001)]
        self.assertEqual(server._registration_counts(), {'c': 6001})
        self.assertEqual(self.table.call_count, 7)

    def test_detail_reuses_registration_and_upcoming_hides_problems(self):
        contest = self.contest('c')
        self.fake.tables['contests'] = [contest]
        self.fake.tables['contest_registrations'] = [{'contest_id': 'c', 'user_email': 'one@example.invalid'}]
        request = Request({'type': 'http', 'session': {'user': {'email': 'one@example.invalid'}}})
        with patch.object(server, '_ensure_problems_fresh'), patch.object(server, '_is_registered', wraps=server._is_registered) as reg:
            detail = server.contest_detail(request, 'c')
            self.assertTrue(detail['can_submit'])
            self.assertEqual(reg.call_count, 1)
            contest['starts_at'] = (self.now + dt.timedelta(minutes=1)).isoformat()
            detail = server.contest_detail(request, 'c')
            self.assertEqual(detail['problem_details'], [])
            self.assertFalse(detail['can_submit'])

    def test_scoreboard_freeze_matches_existing_policy_and_empty_filter_queries_zero(self):
        contest = self.contest('c')
        cutoff = dt.datetime.fromisoformat(contest['ends_at']) - dt.timedelta(minutes=5)
        rows = []
        for i, stamp in enumerate((cutoff-dt.timedelta(seconds=1), cutoff, cutoff+dt.timedelta(seconds=1))):
            rows.append({'id': str(i), 'contest_id': 'c', 'problem': self.prob.pid,
                         'created_at': stamp.isoformat(), 'user_email': str(i), 'name': str(i),
                         'accepted': True, 'score': 100})
        self.fake.tables['submissions'] = rows
        expected = {r['name'] for r in rows if not server._contest_result_frozen(contest, r)}
        self.assertEqual({r['name'] for r in server._contest_scoreboard(contest, False, {self.prob.pid})}, expected)
        self.table.reset_mock()
        self.assertEqual(server._contest_scoreboard(contest, False, set()), [])
        self.assertEqual(self.table.call_count, 0)

    def test_scoreboard_accepts_server_pages_smaller_than_requested_without_count(self):
        from fake_supabase import _Query
        self.fake.tables['submissions'] = [
            {'id': str(i), 'contest_id': 'c', 'problem': self.prob.pid, 'created_at': str(i),
             'user_email': str(i), 'name': str(i), 'score': 100, 'accepted': True} for i in range(1100)]
        original = _Query._execute
        def capped(query):
            if query.table == 'submissions':
                query._limit = min(query._limit or 500, 500)
                result = original(query)
                result.count = None
                return result
            return original(query)
        with patch.object(_Query, '_execute', capped):
            self.assertEqual(len(server._contest_scoreboard(self.contest('c'), True)), 1100)

    def test_problem_catalog_paginates_past_1000_rows(self):
        import problem_store
        self.fake.tables['problems'] = [{'slug':f'p{i:04d}','no':i} for i in range(1201)]
        rows=problem_store._fetch_all_rows(self.fake)
        self.assertEqual(len(rows),1201)
        self.assertEqual(len({r['slug'] for r in rows}),1201)
        self.assertEqual(self.table.call_count,3)

    def test_metadata_change_with_unchanged_test_hash_invalidates_full_problem_cache(self):
        from collections import OrderedDict
        import problem_store
        samples,hidden=problem_store.manifest_for_problem(self.prob)
        import grader
        row={'slug':self.prob.pid,'title':'Old','updated_at':'one','samples':self.prob.samples,
             'samples_data':samples,'hidden_tests':hidden,'time_limit':self.prob.time_limit,
             'memory_limit':self.prob.memory_limit,'tests_hash':grader.tests_hash(self.prob)}
        self.fake.tables['problems']=[row]
        for tc in self.prob.tests:
            self.fake.storage.from_('judge-assets').upload(f'{self.prob.pid}/tests/{tc.name}.in',tc.input.encode())
            self.fake.storage.from_('judge-assets').upload(f'{self.prob.pid}/tests/{tc.name}.out',tc.expected.encode())
        with patch.object(problem_store,'_PROBLEMS_CACHE',OrderedDict()):
            self.assertEqual(problem_store.load_problem_supabase(self.prob.pid,self.fake).title,'Old')
            row.update(title='New',updated_at='two')
            self.assertEqual(problem_store.load_problem_supabase(self.prob.pid,self.fake).title,'New')

    def test_scoreboard_ties_are_deterministic_and_private_problem_scores_excluded(self):
        contest=self.contest('c')
        self.fake.tables['submissions']=[
            {'id':str(i),'contest_id':'c','problem':pid,'created_at':self.now.isoformat(),
             'user_email':user,'name':user,'score':score,'accepted':score==100}
            for i,(user,pid,score) in enumerate((('B',self.prob.pid,100),('A',self.prob.pid,100),('A','private',100)))]
        board=server._contest_scoreboard(contest,True,{self.prob.pid})
        self.assertEqual([r['name'] for r in board],['A','B'])
        self.assertEqual([r['points'] for r in board],[100,100])
        self.assertTrue(all(set(r['per_problem'])=={self.prob.pid} for r in board))

    def test_batched_user_registrations_survive_small_server_row_cap(self):
        from fake_supabase import _Query
        ids=[f'c{i:03d}' for i in range(200)]
        self.fake.tables['contest_registrations']=[{'contest_id':cid,'user_email':'one@example.invalid'} for cid in ids]
        original=_Query._execute
        def capped(query):
            query._limit=min(query._limit or 30,30)
            result=original(query)
            result.count=None
            return result
        with patch.object(_Query,'_execute',capped):
            self.assertEqual(server._registered_contest_ids('one@example.invalid',ids),set(ids))

    def test_browser_metadata_cache_varies_by_cookie_and_authorization(self):
        request=Request({'type':'http','session':{}})
        with patch.object(server,'_ensure_problems_fresh'),patch.object(server,'_TESTS_HASH_CACHE',{}):
            for endpoint in (server.health,server.list_problems,server.version):
                with self.subTest(endpoint=endpoint.__name__):
                    response=Response()
                    endpoint(request,response)
                    self.assertEqual(response.headers['vary'],'Cookie, Authorization')
                    self.assertTrue(response.headers['cache-control'].startswith('private'))
