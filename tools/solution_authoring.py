#!/usr/bin/env python3
"""Scaffold, check, build and qualify private official solutions. No live writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

LANGUAGES = {'py': ('solution.py', 'solution.verify.json'),
             'cpp': ('solution.cpp', 'solution.cpp.verify.json')}

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import make_solution_tex as renderer


def check(folder, require_pdf=True):
    renderer.validate_source(folder)
    code = (folder/'solution.py').read_text()
    if any(word in code for word in ('TODO', 'TBD', 'REPLACE_ME')):
        raise ValueError('unfinished solution code')
    if require_pdf:
        pdf = folder/'solution.pdf'
        record = json.loads((folder/'solution.build.json').read_text())
        if record.get('kind') != 'solution' or record.get('source_sha256') != renderer.source_hash(folder):
            raise ValueError('solution PDF is stale; rebuild it')
        if not pdf.read_bytes().startswith(b'%PDF') or record.get('pdf_sha256') != hashlib.sha256(pdf.read_bytes()).hexdigest():
            raise ValueError('solution PDF integrity check failed')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('new', 'check', 'build', 'verify'):
        cmd = sub.add_parser(action)
        cmd.add_argument('problem')
        if action == 'verify':
            cmd.add_argument('--lang', choices=('all', *LANGUAGES), default='all')
        if action == 'build':
            cmd.add_argument('--engine', default='tectonic')
    args = parser.parse_args()
    if not args.problem or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_' for c in args.problem):
        parser.error('invalid problem ID')
    folder = ROOT/'problems'/args.problem
    if not (folder/'config.json').is_file():
        parser.error('problem package is missing')
    if args.action == 'new':
        sources = [('solution.md', 'solution.md'), ('solution.py.txt', 'solution.py'),
                   ('solution.cpp.txt', 'solution.cpp')]
        if any((folder/dest).exists() for _, dest in sources):
            parser.error('solution sources already exist; refusing to overwrite')
        for src, dest in sources:
            (folder/dest).write_bytes((ROOT/'tools/templates/solution'/src).read_bytes())
        print('Created private solution sources; complete all three files before building.')
    elif args.action == 'build':
        check(folder, require_pdf=False)
        print(renderer.build(folder, engine=args.engine))
    elif args.action == 'check':
        check(folder)
        print('Solution sources and PDF hashes match; runtime and visual review are separate gates.')
    else:
        check(folder)
        failed = False
        selected = LANGUAGES if args.lang == 'all' else {args.lang: LANGUAGES[args.lang]}
        for lang, (filename, report_name) in selected.items():
            report = folder/report_name
            report.unlink(missing_ok=True)
            result = subprocess.run([sys.executable, str(ROOT/'grader.py'), 'run', args.problem,
                                     str(folder/filename), '--no-color', '--stop-on-fail',
                                     '--json', str(report)], cwd=ROOT)
            if result.returncode == 0:
                import grader
                data = json.loads(report.read_text())
                data.update(source_sha256=renderer.source_hash(folder),
                            code_sha256=hashlib.sha256((folder/filename).read_bytes()).hexdigest(),
                            config_sha256=hashlib.sha256((folder/'config.json').read_bytes()).hexdigest(),
                            tests_sha256=grader.tests_hash(grader.load_problem(args.problem)),
                            language=lang, python_version=sys.version.split()[0], platform=sys.platform,
                            root_execution=os.geteuid() == 0 if hasattr(os, 'geteuid') else False)
                report.write_text(json.dumps(data, indent=2)+'\n')
            failed = failed or result.returncode != 0
        raise SystemExit(1 if failed else 0)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f'solution_authoring: {exc}')
