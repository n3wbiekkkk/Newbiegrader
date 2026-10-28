"""Catalog snapshots and version coordination; never an authorization source.

The existing problem store supplies local files or remote metadata/protected
bytes. Readers retain stale metadata during refresh; private bytes stay lazy.
"""
import sys
import threading
import time
from types import MappingProxyType

import grader
import problem_store


class ProblemCatalog:
    def __init__(self, source, client, *, store=problem_store):
        self._source = source
        self._client = client
        self._store = store
        self._problems = {}
        self._numbers = {}
        self._hashes = {}
        self._extra = {}
        self._refreshed_at = time.monotonic()
        self._refresh_lock = threading.Lock()

    @property
    def problems(self):
        return MappingProxyType(self._problems)

    def preload(self):
        if self._source() == 'supabase':
            if self._client() is None:
                print('[web] supabase problem store unavailable (no local fallback)', file=sys.stderr)
                return
            try:
                self._install(*self._store.load_snapshot(client=self._client()))
            except Exception as exc:
                print(f'[web] supabase problem preload failed: {exc} (no local fallback)', file=sys.stderr)
        else:
            self._problems.update(self._store.load_all(source='local'))
            self._reindex()
        self._refreshed_at = time.monotonic()

    def resolve(self, token):
        token = (token or '').strip()
        if token in self._problems:
            return token
        return self._numbers.get(int(token), token) if token.isdigit() else token

    def cached_hash(self, pid):
        """Metadata-only: admission must not load private files for a hash."""
        return self._hashes.get(pid)

    def has_pdf(self, pid):
        return bool((self._extra.get(pid) or {}).get('has_pdf', False))

    def total(self, pid, problem):
        if self._source() == 'supabase':
            count = (self._extra.get(pid) or {}).get('tests') or 0
            if count:
                return int(count)
        return len(problem.tests)

    def description(self, problem):
        if problem.description or self._source() != 'supabase' or self._client() is None:
            return problem.description
        try:
            problem.description = self._store.load_statement_md(problem.pid, client=self._client())
        except Exception as exc:
            print(f'[web] statement unavailable for {problem.pid}: {exc}', file=sys.stderr)
        return problem.description

    def metadata(self, token):
        slug = self.resolve(token)
        problem = self._problems.get(slug)
        if problem is not None:
            return problem
        if self._source() != 'supabase':
            raise self._store.ProblemNotFound(slug)
        if self._client() is None:
            raise self._store.ProblemUnavailable('problem store unavailable')
        problem, _ = self._store.load_meta(slug, client=self._client())
        self._remember(problem)
        return problem

    def problem(self, token):
        slug = self.resolve(token)
        problem = self._problems.get(slug)
        if problem is not None:
            if self._source() == 'supabase' and len(problem.tests) <= len(problem.samples):
                problem = self._store.get_problem(slug, source='supabase', client=self._client())
                self._problems[slug] = problem
            return problem
        if self._source() != 'supabase':
            raise self._store.ProblemNotFound(slug)
        if self._client() is None:
            raise self._store.ProblemUnavailable('problem store unavailable')
        problem = self._store.get_problem(slug, source='supabase', client=self._client())
        self._remember(problem)
        self._hashes[problem.pid] = grader.tests_hash(problem)
        return problem

    def tests_hash(self, pid):
        hit = self._hashes.get(pid)
        if hit is not None:
            return hit
        problem = self._problems.get(pid)
        if problem is None:
            return ''
        if self._source() == 'supabase' and len(problem.tests) == len(problem.samples):
            try:
                problem = self._store.get_problem(pid, source='supabase', client=self._client())
                self._remember(problem)
            except Exception:
                return ''
        hashed = grader.tests_hash(problem)
        self._hashes[pid] = hashed
        return hashed

    def record_judged(self, problem, tests_hash):
        # Protected local bytes must be read and verified again for each claim.
        if self._store.backend_problem_files.backend() != 'local':
            self._problems[problem.pid] = problem
        self._hashes[problem.pid] = tests_hash

    def ensure_fresh(self):
        if self._source() != 'supabase':
            return
        ttl = self._store.cache_ttl_s()
        if ttl > 0 and time.monotonic() - self._refreshed_at < ttl:
            return
        if self._client() is None or not self._refresh_lock.acquire(blocking=False):
            return
        self._refreshed_at = time.monotonic()
        try:
            threading.Thread(target=self._refresh_owned, name='problem-refresh', daemon=True).start()
        except Exception as exc:
            self._refresh_lock.release()
            print(f'[web] cannot start problem refresh: {exc}', file=sys.stderr)

    def refresh(self):
        """Refresh remote metadata synchronously, sharing the background gate."""
        if self._source() != 'supabase' or self._client() is None:
            return False
        if not self._refresh_lock.acquire(blocking=False):
            return False
        return self._refresh_owned()

    def _refresh_owned(self):
        try:
            meta, hashes, extra = self._store.load_snapshot(client=self._client(), lean=True)
            dropped = self._store.invalidate_stale(hashes, extra)
            if dropped:
                print(f'[web] problem versions changed, dropped cache: {sorted(dropped)}', file=sys.stderr)
            self._install(meta, hashes, extra)
            return True
        except Exception as exc:
            print(f'[web] problem refresh failed, keeping {len(self._problems)} cached: {exc}', file=sys.stderr)
            return False
        finally:
            # Back off even after failure; stale metadata remains readable.
            self._refreshed_at = time.monotonic()
            self._refresh_lock.release()

    def _remember(self, problem):
        self._problems[problem.pid] = problem
        if problem.no > 0 and problem.no not in self._numbers:
            self._numbers[problem.no] = problem.pid

    def _reindex(self):
        self._numbers.clear()
        for pid, problem in sorted(self._problems.items()):
            if problem.no > 0:
                if problem.no in self._numbers:
                    print(f'[web] WARNING: problems {self._numbers[problem.no]} and {pid} share number {problem.no}; '
                          'the first one wins (fix with tools/number_problems.py)', file=sys.stderr)
                else:
                    self._numbers[problem.no] = pid
        if self._source() != 'supabase':
            self._hashes.clear()
            self._hashes.update({pid: grader.tests_hash(p) for pid, p in self._problems.items()})

    def _install(self, meta, hashes, extra):
        for slug, problem in meta.items():
            old = self._problems.get(slug)
            if old is None or problem.description:
                continue
            if self._hashes.get(slug) == hashes.get(slug) and str(
                    (self._extra.get(slug) or {}).get('updated_at') or '') == str(
                    (extra.get(slug) or {}).get('updated_at') or ''):
                problem.description = old.description
        for slug in list(self._problems):
            if slug not in meta:
                self._problems.pop(slug, None)
        self._problems.update(meta)
        self._hashes.clear()
        self._hashes.update(hashes)
        self._extra.clear()
        self._extra.update(extra)
        self._reindex()
