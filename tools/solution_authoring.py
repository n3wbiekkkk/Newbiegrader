#!/usr/bin/env python3
"""Scaffold, check, build and qualify private official solutions. No live writes."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

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
        if action == 'build':
            cmd.add_argument('--engine', default='tectonic')
    args = parser.parse_args()
    if not args.problem or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789_' for c in args.problem):
        parser.error('invalid problem ID')
    folder = ROOT/'problems'/args.problem
    if not (folder/'config.json').is_file():
        parser.error('problem package is missing')
    if args.action == 'new':
        sources = [('solution.md', 'solution.md'), ('solution.py.txt', 'solution.py')]
        if any((folder/dest).exists() for _, dest in sources):
            parser.error('solution sources already exist; refusing to overwrite')
        for src, dest in sources:
            (folder/dest).write_bytes((ROOT/'tools/templates/solution'/src).read_bytes())
        print('Created private solution sources; complete both files before building.')
    elif args.action == 'build':
        check(folder, require_pdf=False)
        print(renderer.build(folder, engine=args.engine))
    elif args.action == 'check':
        check(folder)
        print('Solution sources and PDF hashes match; runtime and visual review are separate gates.')
    else:
        check(folder)
        report = folder/'solution.verify.json'
        report.unlink(missing_ok=True)
        result = subprocess.run([sys.executable, str(ROOT/'grader.py'), 'run', args.problem,
                                 str(folder/'solution.py'), '--no-color', '--stop-on-fail',
                                 '--json', str(report)], cwd=ROOT)
        if result.returncode == 0:
            import grader
            data = json.loads(report.read_text())
            data.update(source_sha256=renderer.source_hash(folder),
                        code_sha256=hashlib.sha256((folder/'solution.py').read_bytes()).hexdigest(),
                        config_sha256=hashlib.sha256((folder/'config.json').read_bytes()).hexdigest(),
                        tests_sha256=grader.tests_hash(grader.load_problem(args.problem)),
                        python_version=sys.version.split()[0], platform=sys.platform,
                        root_execution=os.geteuid() == 0 if hasattr(os, 'geteuid') else False)
            report.write_text(json.dumps(data, indent=2)+'\n')
        raise SystemExit(result.returncode)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError) as exc:
        raise SystemExit(f'solution_authoring: {exc}')
