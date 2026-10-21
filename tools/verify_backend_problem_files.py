#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Offline full asset/parity verification against a private read-only catalog export.

No network credentials, reference programs or submitted programs are used. Reuses
production loaders with the repository's in-memory catalog substitute.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import stat
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
import backend_problem_files as files
import grader
import problem_store
from fake_supabase import FakeSupabase


def verify(catalog):
    if files.backend() != 'local':
        raise files.FilesUnavailable('verification requires local file storage')
    path=Path(catalog);s=path.lstat()
    if not stat.S_ISREG(s.st_mode) or s.st_uid not in (0,os.geteuid()) or s.st_mode & 0o077:
        raise files.FilesUnavailable('catalog export must be private')
    source=json.loads(path.read_bytes());rows=source['rows'];fake=FakeSupabase();fake.tables['problems']=rows
    if not rows or len({r['slug'] for r in rows})!=len(rows):
        raise files.FilesUnavailable('empty/duplicate source catalog')
    report=files.validate(verify_bytes=True)
    class NoRemoteStorage:
        def from_(self,*args):raise AssertionError('offline verification cannot use remote Storage')
    fake.storage=NoRemoteStorage()
    cases=pdfs=source_pdfs=0;largest_suite=0
    for row in rows:
        prob=problem_store.load_problem_supabase(row['slug'],fake)
        if grader.tests_hash(prob)!=row['tests_hash'] or len(prob.tests)!=row['tests_count']:
            raise files.FilesUnavailable('problem suite/version mismatch')
        suite=0
        for test in prob.tests:
            for suffix,value in [('in',test.input),('out',test.expected)]:
                raw=files.download(problem_store.problem_bucket(),f'{prob.pid}/tests/{test.name}.{suffix}')
                if raw!=value.encode('utf-8'):
                    raise files.FilesUnavailable('raw asset and selected suite differ')
                suite+=len(raw)
        largest_suite=max(largest_suite,suite);cases+=len(prob.tests)
        if row.get('statement_pdf_path'):
            pdf=problem_store.get_statement_pdf(row['slug'],'supabase',fake)
            expected=source.get('objects',{}).get(row['statement_pdf_path'])
            if expected is not None:
                if len(pdf)!=int(expected['size']):raise files.FilesUnavailable('PDF size mismatch')
                if expected.get('sha256') and hashlib.sha256(pdf).hexdigest()!=expected['sha256']:
                    raise files.FilesUnavailable('PDF checksum mismatch')
                source_pdfs+=1
            pdfs+=1
    report.update(problems=len(rows),cases=cases,pdfs=pdfs,pdf_source_versions_compared=source_pdfs,raw_suite_bytes_equal=True,
                  tests_hashes_equal=True,largest_suite_bytes=largest_suite,
                  process_maxrss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                  maxrss_units='KiB on Linux; bytes on macOS',network_requests=0,
                  submissions_executed=0,full_problem_cache_entries=len(problem_store._PROBLEMS_CACHE))
    return report


def main(argv=None):
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--catalog',type=Path,required=True);args=ap.parse_args(argv)
    try:result=verify(args.catalog)
    except Exception:
        print('Backend file parity failed; no source bytes/credentials printed.',file=sys.stderr);return 1
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())
