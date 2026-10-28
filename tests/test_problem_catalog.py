"""Catalog contracts through lookups and refresh, with synthetic storage."""
from contextlib import ExitStack
from pathlib import Path
import threading
import time
import unittest
from unittest.mock import patch

import grader
import problem_store
import problem_catalog
from problem_catalog import ProblemCatalog
from critical_helpers import synthetic_problem
from fake_supabase import FakeSupabase


class ProblemCatalogTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict('os.environ', {'GRADER_FILE_STORAGE': 'supabase'}))
        problem_store.invalidate_cache()
        self.addCleanup(problem_store.invalidate_cache)
        self.problem = synthetic_problem()
        self.slug = self.problem.pid
        self.db = FakeSupabase()
        samples, manifest = problem_store.manifest_for_problem(self.problem)
        self.row = {'slug': self.slug, 'no': 99, 'title': 'Original',
                    'time_limit': self.problem.time_limit, 'memory_limit': self.problem.memory_limit,
                    'checker': self.problem.checker, 'tolerance': self.problem.tolerance,
                    'samples': self.problem.samples, 'samples_data': samples,
                    'hidden_tests': manifest, 'tests_count': len(self.problem.tests),
                    'tests_hash': grader.tests_hash(self.problem), 'updated_at': 'v1',
                    'is_published': True, 'statement_md': 'Original statement',
                    'statement_pdf_path': self.slug + '/statement.pdf'}
        self.db.table('problems').insert(self.row).execute()
        self.bucket = self.db.storage.from_('judge-assets')
        for case in self.problem.tests:
            self.bucket.upload(f'{self.slug}/tests/{case.name}.in', case.input.encode())
            self.bucket.upload(f'{self.slug}/tests/{case.name}.out', case.expected.encode())
        self.bucket.upload(self.row['statement_pdf_path'], b'%PDF-original')
        self.catalog = ProblemCatalog(lambda: 'supabase', lambda: self.db)
        self.catalog.preload()
        original_snapshot = problem_store.load_snapshot

        def snapshot(client=None, *, lean=False):
            result = original_snapshot(client=client, lean=lean)
            # FakeSupabase doesn't project SELECT columns. Emulate the real
            # metadata response without changing the shared database substitute.
            if lean:
                for problem in result[0].values():
                    problem.description = ''
            return result

        self.stack.enter_context(patch.object(problem_store, 'load_snapshot', side_effect=snapshot))

    def test_browsing_and_cached_hash_never_download_private_files(self):
        with patch.object(problem_store, '_download', side_effect=AssertionError('private download')):
            self.assertEqual(self.catalog.resolve('99'), self.slug)
            self.assertEqual(self.catalog.metadata('99').title, 'Original')
            self.assertEqual(self.catalog.cached_hash(self.slug), self.row['tests_hash'])
            self.assertEqual(self.catalog.tests_hash(self.slug), self.row['tests_hash'])
            self.assertEqual(self.catalog.total(self.slug, self.catalog.metadata(self.slug)), len(self.problem.tests))
            self.assertTrue(self.catalog.has_pdf(self.slug))
        with self.assertRaises(TypeError):
            self.catalog.problems['another'] = self.problem

    def test_judging_loads_full_tests_only_when_requested(self):
        self.assertEqual(len(self.catalog.metadata(self.slug).tests), len(self.problem.samples))
        with patch.object(problem_store, '_download', wraps=problem_store._download) as download:
            full = self.catalog.problem('99')
            self.assertEqual(len(full.tests), len(self.problem.tests))
            self.assertEqual(grader.tests_hash(full), self.row['tests_hash'])
            self.assertGreater(download.call_count, 0)

    def test_unchanged_version_keeps_description_without_lazy_fetch(self):
        self.assertTrue(self.catalog.refresh())
        with patch.object(problem_store, 'load_statement_md', side_effect=AssertionError('redundant statement fetch')):
            self.assertEqual(self.catalog.description(self.catalog.metadata(self.slug)), 'Original statement')

    def test_changed_test_hash_cannot_reuse_old_full_suite(self):
        self.catalog.problem(self.slug)
        self.db.table('problems').update({'tests_hash': 'f' * 16}).eq('slug', self.slug).execute()
        self.assertTrue(self.catalog.refresh())
        self.assertEqual(self.catalog.cached_hash(self.slug), 'f' * 16)
        with self.assertRaises(problem_store.ProblemUnavailable):
            self.catalog.problem(self.slug)

    def test_statement_version_changes_without_test_changes(self):
        self.db.table('problems').update({'updated_at': 'v2', 'statement_md': 'Changed statement'}).eq('slug', self.slug).execute()
        self.assertTrue(self.catalog.refresh())
        self.assertEqual(self.catalog.cached_hash(self.slug), self.row['tests_hash'])
        with patch.object(problem_store, 'load_statement_md', wraps=problem_store.load_statement_md) as load:
            problem = self.catalog.metadata(self.slug)
            self.assertEqual(self.catalog.description(problem), 'Changed statement')
            self.assertEqual(self.catalog.description(problem), 'Changed statement')
            load.assert_called_once()

    def test_pdf_path_change_and_row_deletion_invalidate_versioned_files(self):
        self.assertEqual(problem_store.get_statement_pdf(self.slug, source='supabase', client=self.db), b'%PDF-original')
        path = self.slug + '/new.pdf'
        self.bucket.upload(path, b'%PDF-changed')
        self.db.table('problems').update({'statement_pdf_path': path}).eq('slug', self.slug).execute()
        self.assertTrue(self.catalog.refresh())
        self.assertEqual(problem_store.get_statement_pdf(self.slug, source='supabase', client=self.db), b'%PDF-changed')
        self.db.table('problems').delete().eq('slug', self.slug).execute()
        self.assertTrue(self.catalog.refresh())
        self.assertNotIn(self.slug, self.catalog.problems)
        self.assertEqual(self.catalog.resolve('99'), '99')
        with self.assertRaises(problem_store.ProblemNotFound):
            self.catalog.metadata(self.slug)
        with self.assertRaises(problem_store.ProblemNotFound):
            problem_store.get_statement_pdf(self.slug, source='supabase', client=self.db)

    def test_refresh_failure_keeps_snapshot_and_backs_off(self):
        with patch.object(problem_store, 'load_snapshot', side_effect=OSError('unavailable')) as load, \
                patch.object(problem_catalog.time, 'monotonic', return_value=100) as clock:
            self.assertFalse(self.catalog.refresh())
            clock.return_value = 101
            self.catalog.ensure_fresh()
            load.assert_called_once()
        self.assertEqual(self.catalog.metadata(self.slug).title, 'Original')

    def test_background_refresh_is_single_flight_and_readers_keep_stale_snapshot(self):
        gate, started = threading.Event(), threading.Event()
        original = problem_store.load_snapshot

        def slow_load(*args, **kwargs):
            started.set()
            gate.wait(2)
            return original(*args, **kwargs)

        self.db.table('problems').update({'title': 'Changed title'}).eq('slug', self.slug).execute()
        with patch.object(problem_store, 'cache_ttl_s', return_value=0), \
                patch.object(problem_store, 'load_snapshot', side_effect=slow_load) as load:
            try:
                before = time.monotonic()
                self.catalog.ensure_fresh()
                self.assertLess(time.monotonic() - before, .2)
                self.assertTrue(started.wait(1))
                self.catalog.ensure_fresh()
                self.assertFalse(self.catalog.refresh())
                self.assertEqual(self.catalog.metadata(self.slug).title, 'Original')
                self.assertEqual(load.call_count, 1)
            finally:
                gate.set()
                deadline = time.monotonic() + 2
                while self.catalog.metadata(self.slug).title != 'Changed title' and time.monotonic() < deadline:
                    time.sleep(.005)
            self.assertEqual(self.catalog.metadata(self.slug).title, 'Changed title')

    def test_failed_thread_start_releases_gate_for_later_refresh(self):
        with patch.object(problem_store, 'cache_ttl_s', return_value=0), \
                patch.object(problem_catalog.threading, 'Thread', side_effect=RuntimeError('unavailable')):
            self.catalog.ensure_fresh()
        self.assertTrue(self.catalog.refresh())

    def test_local_adapter_never_falls_back_to_remote_snapshot(self):
        local = ProblemCatalog(lambda: 'local', lambda: None)
        with patch.object(grader, 'PROBLEMS_DIR', Path(__file__).parent / 'fixtures'), \
                patch.object(problem_store, 'load_snapshot', side_effect=AssertionError('remote fallback')):
            local.preload()
            self.assertEqual(local.problem(self.slug).pid, self.slug)
            self.assertEqual(local.tests_hash(self.slug), grader.tests_hash(local.problem(self.slug)))
            self.assertFalse(local.refresh())
            local.ensure_fresh()


if __name__ == '__main__':
    unittest.main()
