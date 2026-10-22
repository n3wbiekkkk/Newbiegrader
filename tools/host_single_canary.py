#!/usr/bin/env python3
"""Approved, credential-free single-worker native qualification; fixed fixtures.

Refuses ordinary shells and active production workers. Never claims a queue job.
Production OAuth/API flows are outside this test.
"""
import asyncio
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def authorize():
    gate = Path('/etc/newbiegrader/single-canary-approved')
    expected = '/sys/fs/cgroup/system.slice/newbiegrader-single-canary.service'
    try:
        info = gate.lstat()
        valid = (sys.platform.startswith('linux') and os.geteuid() == 0 and
                 stat.S_ISREG(info.st_mode) and info.st_uid == 0 and
                 stat.S_IMODE(info.st_mode) == 0o400 and info.st_nlink == 1 and
                 os.environ.get('GRADER_JOB_CGROUP_ROOT') == expected and
                 not Path('/etc/newbiegrader/worker-enabled').exists() and
                 not os.environ.get('SUPABASE_URL') and not os.environ.get('SUPABASE_KEY'))
    except OSError:
        valid = False
    workers = ['newbiegrader-worker.service'] + [
        f'newbiegrader-worker@{i}.service' for i in range(1, 5)]
    if valid and subprocess.run(['systemctl', 'is-active', '--quiet', *workers],
                                capture_output=True).returncode == 0:
        valid = False
    if not valid:
        raise SystemExit('REFUSED: approved idle native canary unit required')


class Verdicts(unittest.TestCase):
    def tearDown(self):
        root, workspace = resources._ready
        self.assertFalse(list(root.glob('job-*')))
        self.assertFalse(list(workspace.glob('job-*')))

    def submission(self, source, ext='.py', limit=3):
        prob = synthetic_problem()
        prob.time_limit = limit
        message = {'problem': None, 'problem_data': store.serialize_problem(prob),
                   'ext': ext, 'source': source, 'reveal': 'none',
                   'memory_cap_mb': 128, 'judge_jobs': 1}
        result = asyncio.run(runner.run_isolated('submission', message, 30))
        self.assertNotIn('error', result)
        return result

    def test_standard_c_cpp_python_are_accepted(self):
        for ext, source in [('.c', '#include <stdio.h>\nint main(void){puts("hello");}'),
                            ('.cpp', '#include <iostream>\n#include <vector>\n#include <string>\nint main(){std::vector<std::string> v{"hello"};std::cout<<v[0];}'),
                            ('.py', 'print("hello")')]:
            with self.subTest(language=ext):
                result = self.submission(source, ext)
                self.assertTrue(result['accepted'])
                self.assertEqual(result['counts'], {'AC': 2})

    def test_wrong_answer_has_no_hidden_bytes(self):
        result = self.submission('print("SYNTHETIC_WRONG_OUTPUT")')
        self.assertEqual(result['counts'], {'WA': 2})
        self.assertNotIn('SYNTHETIC_WRONG_OUTPUT', json.dumps(result))
        self.assertNotIn('synthetic-hidden-input', json.dumps(result))

    def test_runtime_stderr_has_no_hidden_bytes(self):
        result = self.submission('import sys\nsys.stderr.write(sys.stdin.read())\nsys.exit(1)')
        self.assertEqual(result['counts'], {'RE': 2})
        self.assertNotIn('synthetic-hidden-input', json.dumps(result))

    def test_compile_error_stays_compile_error(self):
        result = self.submission('int main( {', '.cpp')
        self.assertEqual(result['counts'], {'CE': 2})
        self.assertTrue(result['compile_error'])

    def test_finite_sleep_exceeds_fixed_deadline(self):
        result = self.submission('import time\ntime.sleep(.6)', limit=.15)
        self.assertEqual(result['counts'], {'TLE': 2})

    def test_same_deadline_single_worker_repeatability(self):
        iterations = 4000000
        source = f's=0\nfor i in range({iterations}):s=(s+i)%1000000007\nprint(s)'
        expected = str((iterations * (iterations - 1) // 2) % 1000000007)
        calibration = [playground(source, limit=3) for _ in range(3)]
        self.assertTrue(all(r['verdict'] == 'OK' and r['stdout'].strip() == expected
                            for r in calibration))
        deadline = max(r['wall_s'] for r in calibration) * 1.25
        replay = [playground(source, limit=deadline) for _ in range(6)]
        repeatability.update(iterations=iterations, calibration_wall_s=[r['wall_s'] for r in calibration],
                             fixed_deadline_s=deadline,
                             replay=[{k: r[k] for k in ('verdict', 'wall_s', 'cpu_s')} for r in replay])
        self.assertTrue(all(r['verdict'] == 'OK' and r['stdout'].strip() == expected
                            for r in replay), 'fixed-deadline single-worker repeatability failed')


def main():
    authorize()
    global resources, store, runner, playground, synthetic_problem, repeatability
    import job_resources as resources
    import problem_store as store
    import judge_runner as runner
    from tools.host_canaries import KernelIsolation, playground
    sys.path.insert(0, str(ROOT / 'tests'))
    from critical_helpers import synthetic_problem
    resources.initialize()
    repeatability = {}
    measurements = []
    original = resources.JobResources.close

    def measured_close(boundary):
        try:
            measurements.append({'peak_bytes': int((boundary.group / 'memory.peak').read_text()),
                                 'oom_kill': int(dict(line.split() for line in
                                     (boundary.group / 'memory.events').read_text().splitlines())['oom_kill'])})
        finally:
            original(boundary)

    suite = unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(KernelIsolation),
                               unittest.defaultTestLoader.loadTestsFromTestCase(Verdicts)])
    with patch.object(resources.JobResources, 'close', measured_close):
        result = unittest.TextTestRunner(verbosity=2, failfast=True).run(suite)
    print(json.dumps({'synthetic_only': True, 'single_worker': True,
                      'tests': result.testsRun, 'failures': len(result.failures),
                      'errors': len(result.errors), 'skipped': len(result.skipped),
                      'success': result.wasSuccessful(), 'repeatability': repeatability,
                      'peak_job_bytes': max((r['peak_bytes'] for r in measurements), default=0),
                      'controlled_job_oom_kills': sum(r['oom_kill'] for r in measurements),
                      'jobs_observed': len(measurements)}), flush=True)
    return 0 if result.wasSuccessful() and result.testsRun == 17 and not result.skipped else 1


if __name__ == '__main__':
    raise SystemExit(main())
