#!/usr/bin/env python3
"""Publish qualified solution PDFs to protected backend disk. No database writes."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import backend_problem_files as files
import grader
import problem_store
from tools import solution_authoring


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument('--problem')
    choice.add_argument('--all', action='store_true')
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument('--dry-run', action='store_true')
    action.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if files.backend() != 'local':
        parser.error('solution publishing requires GRADER_FILE_STORAGE=local')
    packages = sorted(p.parent for p in grader.PROBLEMS_DIR.glob('*/config.json'))
    if args.problem:
        packages = [p for p in packages if p.name == args.problem]
    if not packages:
        parser.error('no matching authoring packages')
    jobs = []
    for folder in packages:
        solution_authoring.check(folder)
        prob = grader.load_problem(folder.name)
        for lang, (filename, report_name) in solution_authoring.LANGUAGES.items():
            verified = json.loads((folder/report_name).read_text())
            if (verified.get('accepted') is not True or verified.get('total') != len(prob.tests)
                    or verified.get('passed') != len(prob.tests) or not prob.tests
                    or verified.get('language') != lang
                    or verified.get('code_sha256') != hashlib.sha256((folder/filename).read_bytes()).hexdigest()
                    or verified.get('config_sha256') != hashlib.sha256((folder/'config.json').read_bytes()).hexdigest()
                    or verified.get('tests_sha256') != grader.tests_hash(prob)):
                raise ValueError('missing, failed or stale canonical solution verification: '
                                 +folder.name+' ('+lang+')')
        jobs.append((f'{folder.name}/solution.pdf', (folder/'solution.pdf').read_bytes(), 'application/pdf'))
    if args.dry_run:
        print(json.dumps({'qualified_solutions': len(jobs), 'published': False}))
        return
    result = files.publish(problem_store.problem_bucket(), jobs)
    for name, data, _ in jobs:
        if files.download_public_pdf(problem_store.problem_bucket(), name) != data:
            raise ValueError('published solution parity failed')
    print(json.dumps({'qualified_solutions': len(jobs), 'parity_verified': True, **result}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, files.FilesUnavailable) as exc:
        raise SystemExit(f'publish_solutions: {exc}')
