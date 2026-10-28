#!/usr/bin/env python3
"""Fail early on an unsuitable test interpreter, then exercise the real runner.

Uses the caller's isolation settings without adding sandbox bypass flags.
This synthetic playground probe does not load a database or private problems.
"""
import asyncio
import json
from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def check_interpreter(executable, temporary_roots):
    # Resolve the parent rather than the executable: a venv symlink under a
    # job temporary root is still rejected by the executor's O_NOFOLLOW guard.
    parent = Path(executable).absolute().parent.resolve()
    for root in temporary_roots:
        if parent.is_relative_to(Path(root).resolve()):
            raise RuntimeError('Test Python is inside a temporary root; create the venv in the project or user cache')


def main():
    check_interpreter(sys.executable, (tempfile.gettempdir(), '/tmp', '/var/tmp'))
    sys.path.insert(0, str(ROOT))
    from judge_runner import run_isolated
    result = asyncio.run(run_isolated('playground', {
        'problem': '', 'ext': '.py', 'source': 'print(input()[::-1])',
        'stdin_data': 'preflight\n', 'time_limit': 2, 'memory_mb': 128,
        'memory_cap_mb': 128, 'judge_jobs': 1}, 15))
    if result.get('verdict') != 'OK' or result.get('stdout') != 'thgilferp\n':
        raise RuntimeError('Synthetic runner probe failed; verify interpreter access and sandbox prerequisites')
    print(json.dumps({'runner_probe': 'passed', 'python': sys.version.split()[0]}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
