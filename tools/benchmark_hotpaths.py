#!/usr/bin/env python3
"""Synthetic checker/cache benchmark; no problems, credentials, or live DB.

Optional --baseline-grader/--baseline-server accept trusted local repository
source files. Only the named checker/cache functions are loaded from them.
Reports JSON timings, fixture sizes, and simulated database call counts.
"""
import argparse
import ast
import asyncio
import contextlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import grader


def load_functions(path, names):
    tree = ast.parse(path.read_text(encoding='utf-8'))
    nodes = [node for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
             and node.name in names]
    if {node.name for node in nodes} != set(names):
        raise ValueError('baseline does not define the required functions')
    namespace = {'asyncio': asyncio, 'time': time, '_cache': {},
                 'DECIMAL2_RE': grader.DECIMAL2_RE}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(path), 'exec'), namespace)
    return namespace


def timing(fn, repeats):
    fn()
    start = time.perf_counter()
    for _ in range(3):
        fn()
    seconds = (time.perf_counter() - start) / 3
    loops = max(1, min(50000, int(.02 / max(seconds, 1e-8))))
    samples = []
    for _ in range(repeats):
        start = time.perf_counter()
        for _ in range(loops):
            fn()
        samples.append((time.perf_counter() - start) / loops)
    return {'median_ms': statistics.median(samples) * 1000,
            'samples_ms': [value * 1000 for value in samples], 'loops': loops}


async def cache_burst(fn, cache, clients):
    cache.clear()
    count, lock = 0, threading.Lock()

    def build():
        nonlocal count
        with lock:
            count += 1
        time.sleep(.05)  # synthetic database round trip; no network
        return {'synthetic': 1}
    start = time.perf_counter()
    rows = await asyncio.gather(*(fn('stats', 30, build) for _ in range(clients)))
    assert rows == [{'synthetic': 1}] * clients
    return {'clients': clients, 'database_reads': count,
            'batch_ms': (time.perf_counter() - start) * 1000}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-grader', type=Path)
    parser.add_argument('--baseline-server', type=Path)
    parser.add_argument('--repeats', type=int, default=7)
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error('--repeats must be positive')
    token = ('12345 67890 54321 98765\n' * 43691)[:1048576]
    decimal = '1.00 2.50 -3.00\n' * 65536
    fixtures = [('token_equal_1MiB', 'check_token', token, token.encode().decode()),
                ('token_whitespace_1MiB', 'check_token', token, token.replace(' ', '\t')),
                ('decimal_equal', 'check_decimal2', decimal, decimal.encode().decode())]
    variants = {'current': vars(grader)}
    if args.baseline_grader:
        variants = {'baseline': load_functions(args.baseline_grader, ['check_token', 'check_decimal2']), **variants}
    report = {'platform': platform.platform(), 'python': platform.python_version(),
              'checkers': {}, 'cache_bursts': {}}
    for label, checker, expected, actual in fixtures:
        row = {'bytes_per_output': len(expected.encode())}
        for name, functions in variants.items():
            fn = functions[checker]
            assert fn(expected, actual) is True
            row[name] = timing(lambda: fn(expected, actual), args.repeats)
        report['checkers'][label] = row
    # Explicit synthetic child mode prevents dotenv, Supabase setup, and real
    # catalog loading even when this tool is run from a configured checkout.
    os.environ.update(GRADER_RUNNER_CHILD='1', GRADER_PROBLEM_SOURCE='local',
                      SESSION_SECRET='synthetic-benchmark-only')
    with tempfile.TemporaryDirectory(prefix='hotpaths-empty-') as empty, contextlib.redirect_stdout(sys.stderr):
        grader.PROBLEMS_DIR = Path(empty)
        import server
    cache_variants = {'current': {'_acached': server._acached, '_cache': server._cache}}
    if args.baseline_server:
        cache_variants = {'baseline': load_functions(args.baseline_server, ['_acached']), **cache_variants}
    for name, functions in cache_variants.items():
        report['cache_bursts'][name] = asyncio.run(cache_burst(functions['_acached'], functions['_cache'], 64))
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
