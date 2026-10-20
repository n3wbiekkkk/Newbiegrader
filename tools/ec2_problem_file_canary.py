#!/usr/bin/env python3
"""Opt-in native filesystem canaries plus existing isolation/verdict suite.

Requires the same approved idle singleton gate as ec2_single_canary. No queue,
production credentials, real submissions or existing private asset bytes used.
"""
import asyncio
import json
import os
from pathlib import Path
import pwd
import subprocess
import sys
import tempfile
import unittest
import uuid
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT));sys.path.insert(0,str(ROOT/'tests'))
from tools import ec2_single_canary as baseline


class FileBoundary(unittest.TestCase):
    def setUp(self):
        self.created=[]
        self.addCleanup(lambda:[p.unlink(missing_ok=True) for p in self.created])
        marker='SYNTHETIC-FILE-BOUNDARY-'+uuid.uuid4().hex
        self.marker=marker
        self.pub=files.root(True)/('.canary-'+uuid.uuid4().hex)
        self.private=files.root(False)/('.canary-'+uuid.uuid4().hex)
        api=pwd.getpwnam('newbiegrader-api');self.api_uid,self.api_gid=api.pw_uid,api.pw_gid
        self.assertNotEqual(self.api_uid,0);self.assertNotEqual(self.api_gid,0)
        for path,public in [(self.pub,True),(self.private,False)]:
            fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o400)
            self.created.append(path)
            with os.fdopen(fd,'wb') as stream:stream.write(marker.encode())
            if public:os.chown(path,0,self.api_gid);path.chmod(0o440)

    def test_api_identity_reads_public_canary_but_not_private(self):
        code=('import os,sys;os.setgroups([]);os.setgid(int(sys.argv[1]));os.setuid(int(sys.argv[2]));'
              'open(sys.argv[3],"rb").close();\ntry:open(sys.argv[4],"rb");sys.exit(2)\nexcept PermissionError:pass\n')
        r=subprocess.run([sys.executable,'-c',code,str(self.api_gid),str(self.api_uid),str(self.pub),str(self.private)],capture_output=True,timeout=5)
        self.assertEqual(r.returncode,0)

    def test_compiler_cannot_include_synthetic_private_asset(self):
        prob=baseline.synthetic_problem();source=f'#include "{self.private}"\nint main(){{}}'
        message={'problem':None,'problem_data':store.serialize_problem(prob),'ext':'.cpp','source':source,
                 'reveal':'none','memory_cap_mb':128,'judge_jobs':1}
        result=asyncio.run(runner.run_isolated('submission',message,30))
        self.assertEqual(result['counts'],{'CE':2});self.assertNotIn(self.marker,json.dumps(result))
        self.assertIn('Permission denied',result['compile_error'])

    def test_runtime_cannot_read_either_asset_root(self):
        for path in (self.pub,self.private):
            source=f'try:\n open({str(path)!r},"rb").read()\n print("UNEXPECTED")\nexcept PermissionError:\n print("DENIED")'
            result=baseline.playground(source,limit=3)
            self.assertEqual(result['verdict'],'OK');self.assertEqual(result['stdout'].strip(),'DENIED')
            self.assertNotIn(self.marker,json.dumps(result))

    def test_local_synthetic_suite_acceptance_and_redaction(self):
        from fake_supabase import FakeSupabase
        prob=baseline.synthetic_problem();samples,hidden=store.manifest_for_problem(prob)
        row={'slug':prob.pid,'title':prob.title,'no':99,'time_limit':prob.time_limit,
             'memory_limit':prob.memory_limit,'checker':prob.checker,'tolerance':prob.tolerance,
             'statement_md':prob.description,'samples':prob.samples,'samples_data':samples,
             'hidden_tests':hidden,'tests_count':len(prob.tests),'tests_hash':grader.tests_hash(prob)}
        fake=FakeSupabase();fake.tables['problems']=[row]
        fake.storage=None
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{
                'GRADER_FILE_STORAGE':'local','GRADER_PUBLIC_FILE_ROOT':str(Path(tmp)/'public'),
                'GRADER_PRIVATE_FILE_ROOT':str(Path(tmp)/'private')}):
            jobs=[]
            for t in prob.tests:jobs.extend([(f'{prob.pid}/tests/{t.name}.in',t.input.encode(),'text/plain'),(f'{prob.pid}/tests/{t.name}.out',t.expected.encode(),'text/plain')])
            files.publish('judge-assets',jobs,{f'{prob.pid}/tests/{name}.{suffix}' for name in prob.samples for suffix in ('in','out')});loaded=store.load_problem_supabase(prob.pid,fake)
            for source,expected in [('print("hello")',{'AC':2}),('import sys;sys.stderr.write(sys.stdin.read());sys.exit(1)',{'RE':2})]:
                result=asyncio.run(runner.run_isolated('submission',{'problem':None,
                    'problem_data':store.serialize_problem(loaded),'ext':'.py','source':source,
                    'reveal':'none','memory_cap_mb':128,'judge_jobs':1},30))
                self.assertEqual(result['counts'],expected)
                self.assertNotIn('synthetic-hidden-input',json.dumps(result))


def main():
    baseline.authorize()
    global files,store,runner,grader
    import backend_problem_files as files
    import problem_store as store
    import judge_runner as runner
    import grader
    import job_resources as resources
    from tools.ec2_canaries import KernelIsolation,playground
    from critical_helpers import synthetic_problem
    if files.backend() != "local":raise SystemExit("REFUSED: local file backend required")
    resources.initialize()
    baseline.resources=resources;baseline.store=store;baseline.runner=runner
    baseline.playground=playground;baseline.synthetic_problem=synthetic_problem;baseline.repeatability={}
    measurements=[];close=resources.JobResources.close
    def measured(boundary):
        try:measurements.append({'peak_bytes':int((boundary.group/'memory.peak').read_text()),'oom_kills':dict(l.split() for l in (boundary.group/'memory.events').read_text().splitlines()).get('oom_kill','0')})
        finally:close(boundary)
    suite=unittest.TestSuite(unittest.defaultTestLoader.loadTestsFromTestCase(c) for c in [KernelIsolation,baseline.Verdicts,FileBoundary])
    with patch.object(resources.JobResources,'close',measured):result=unittest.TextTestRunner(verbosity=2,failfast=True).run(suite)
    report={'synthetic_only':True,'single_worker':True,'problem_file_canary':True,
            'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
            'skipped':len(result.skipped),'success':result.wasSuccessful() and not result.skipped and result.testsRun==21,
            'jobs_observed':len(measurements),'peak_job_bytes':max((r['peak_bytes'] for r in measurements),default=0),
            'controlled_job_oom_kills':sum(int(r['oom_kills']) for r in measurements),'repeatability':baseline.repeatability}
    print(json.dumps(report,sort_keys=True));return 0 if report['success'] else 1


if __name__=='__main__':raise SystemExit(main())
