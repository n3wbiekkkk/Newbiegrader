# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Synthetic backend-file confidentiality/integrity; no private problem packages."""
import asyncio
from contextlib import ExitStack
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch
from fastapi import HTTPException, Request, Response
import backend_problem_files as files
from critical_helpers import synthetic_problem, test_server
from fake_supabase import FakeSupabase
import grader
import problem_store
from tools import import_problems_supabase as importer
from tools.publish_problem_files import publish_backup

server = test_server()


class CriticalBackendFiles(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.base = Path(self.stack.enter_context(tempfile.TemporaryDirectory())).resolve()
        self.public, self.private = self.base/'public', self.base/'private'
        self.stack.enter_context(patch.dict(os.environ, {
            'GRADER_FILE_STORAGE':'local','GRADER_PUBLIC_FILE_ROOT':str(self.public),
            'GRADER_PRIVATE_FILE_ROOT':str(self.private),'GRADER_FILE_MIN_FREE_MB':'256'}))
        self.stack.enter_context(patch.object(files, '_INDEX_CACHE', {}))
        self.prob = synthetic_problem()
        self.bucket = 'judge-assets'
        samples, hidden = problem_store.manifest_for_problem(self.prob)
        self.row = {'slug':self.prob.pid,'no':99,'title':self.prob.title,
                    'time_limit':self.prob.time_limit,'memory_limit':self.prob.memory_limit,
                    'checker':self.prob.checker,'tolerance':self.prob.tolerance,
                    'difficulty':self.prob.difficulty,'tags':self.prob.tags,
                    'statement_md':self.prob.description,'samples':self.prob.samples,
                    'samples_data':samples,'hidden_tests':hidden,
                    'tests_count':len(self.prob.tests),'tests_hash':grader.tests_hash(self.prob),
                    'updated_at':'synthetic-one','statement_pdf_path':self.prob.pid+'/statement.pdf'}
        self.fake=FakeSupabase();self.fake.tables['problems']=[self.row]
        self.pdf=b'%PDF-1.4\nSYNTHETIC PDF ONLY'
        self.jobs=[(self.row['statement_pdf_path'],self.pdf,'application/pdf')]
        for t in self.prob.tests:
            self.jobs.extend([(f'{self.prob.pid}/tests/{t.name}.in',t.input.encode(),'text/plain'),
                              (f'{self.prob.pid}/tests/{t.name}.out',t.expected.encode(),'text/plain')])
        self.public_samples={f"{self.prob.pid}/tests/{name}.{suffix}" for name in self.prob.samples for suffix in ("in","out")}
        files.publish(self.bucket,self.jobs,self.public_samples)
        problem_store.invalidate_cache()
        self.addCleanup(problem_store.invalidate_cache)

    def test_critical_pdf_and_all_tests_match_without_any_storage_network(self):
        with patch.object(self.fake.storage,'from_',side_effect=AssertionError('remote Storage')):
            loaded=problem_store.load_problem_supabase(self.prob.pid,self.fake)
            self.assertEqual(grader.tests_hash(loaded),self.row['tests_hash'])
            self.assertEqual(problem_store.get_statement_pdf(self.prob.pid,'supabase',self.fake),self.pdf)
        self.assertEqual(files.validate(verify_bytes=True)['objects'],len(self.jobs))
        self.assertNotIn(self.prob.pid,problem_store._PROBLEMS_CACHE)

    def test_critical_public_files_contain_no_private_input_expected_bytes(self):
        public=files._index(self.public)['objects']
        self.assertTrue(all(k.endswith('.pdf') or k.split('/',1)[1] in self.public_samples for k in public))
        self.assertFalse(any('/1001.' in key for key in public))
        self.assertTrue(all(b'synthetic-hidden-input' not in path.read_bytes()
                            for path in self.public.glob('*.blob')))
        self.assertEqual(self.private.stat().st_mode & 0o777,0o700)
        self.assertTrue(all(p.stat().st_mode & 0o077 == 0 for p in self.private.iterdir()))

    def test_critical_missing_asset_never_falls_back_to_storage(self):
        key=next(k for k in files._index(self.private)['objects'] if '/1001.in' in k)
        item=files._index(self.private)['objects'][key]
        (self.private/(item['sha256']+'.blob')).unlink()
        with patch.object(self.fake.storage,'from_',side_effect=AssertionError('fallback')), \
                self.assertRaises(problem_store.ProblemUnavailable):
            problem_store.load_problem_supabase(self.prob.pid,self.fake)

    def test_critical_corrupt_asset_is_infrastructure_error_before_runner(self):
        key=next(k for k in files._index(self.private)['objects'] if '/1001.in' in k)
        path=self.private/(files._index(self.private)['objects'][key]['sha256']+'.blob')
        path.chmod(0o600);path.write_bytes(b'SYNTHETIC CORRUPTION');path.chmod(0o400)
        with patch.object(server,'GRADER_ROLE','worker'),patch.object(server,'PROBLEM_SOURCE','supabase'), \
                patch.object(server,'_sb',self.fake),patch.object(server,'_jobs',{}), \
                patch.object(server,'_finish_job',new_callable=AsyncMock) as finish, \
                patch('judge_runner.run_isolated',new_callable=AsyncMock) as run:
            asyncio.run(server._run_job({'id':'synthetic','kind':'submit','problem':self.prob.pid,
                                        'tests_hash':self.row['tests_hash']}))
        run.assert_not_awaited();self.assertEqual(finish.call_args.kwargs,{'error':'problem store unavailable'})

    def test_critical_symlinks_hardlinks_permissions_and_traversal_rejected(self):
        for name in ['../outside','/absolute','x//y','x/./y','x\\y','x\ny']:
            with self.subTest(name=name),self.assertRaises(files.FilesUnavailable):files.download(self.bucket,name)
        index=self.public/'index.json';raw=index.read_bytes();index.unlink();outside=self.base/'outside';outside.write_bytes(raw);outside.chmod(0o400);index.symlink_to(outside)
        with self.assertRaises(OSError):files.download(self.bucket,self.row['statement_pdf_path'])
        index.unlink();index.write_bytes(raw);index.chmod(0o400);os.link(index,self.public/'hardlink')
        with self.assertRaises(files.FilesUnavailable):files.download(self.bucket,self.row['statement_pdf_path'])
        (self.public/'hardlink').unlink();self.private.chmod(0o755)
        with self.assertRaises(files.FilesUnavailable):files.validate()

    def test_critical_failed_publication_retains_old_index_and_cached_view(self):
        before=(self.public/'index.json').read_bytes();self.assertEqual(files.download(self.bucket,self.row['statement_pdf_path']),self.pdf)
        atomic=files._atomic
        def fail(folder,name,data):
            if name=='index.json':raise OSError('synthetic interruption')
            return atomic(folder,name,data)
        with patch.object(files,'_atomic',side_effect=fail),self.assertRaises(OSError):
            files.publish(self.bucket,[(self.row['statement_pdf_path'],b'%PDF-1.4\nNEW SYNTHETIC','application/pdf')])
        self.assertEqual((self.public/'index.json').read_bytes(),before)
        self.assertEqual(files.download(self.bucket,self.row['statement_pdf_path']),self.pdf)

    def test_critical_replacing_pointer_preserves_old_immutable_blob(self):
        before=hashlib.sha256(self.pdf).hexdigest();new=b'%PDF-1.4\nSECOND SYNTHETIC'
        files.publish(self.bucket,[(self.row['statement_pdf_path'],new,'application/pdf')])
        self.assertEqual(files.download(self.bucket,self.row['statement_pdf_path']),new)
        self.assertEqual((self.public/(before+'.blob')).read_bytes(),self.pdf)

    def test_critical_disk_reserve_failure_keeps_indexes(self):
        before=(self.private/'index.json').read_bytes()
        with patch.dict(os.environ,{'GRADER_FILE_MIN_FREE_MB':'1'}),self.assertRaises(files.FilesUnavailable):
            files.publish(self.bucket,[('synthetic/new.in',b'new synthetic','text/plain')])
        self.assertEqual((self.private/'index.json').read_bytes(),before)

    def test_critical_api_startup_validates_public_only(self):
        with patch.object(files,'root',wraps=files.root) as opened:
            files.validate('api',verify_bytes=True)
        self.assertTrue(all(c.args[0] is True for c in opened.call_args_list))
        (self.public/'index.json').unlink()
        with self.assertRaises(files.FilesUnavailable):files.validate('api')

    def test_critical_invalid_mode_cannot_select_remote_fallback(self):
        with patch.dict(os.environ,{'GRADER_FILE_STORAGE':'typo'}),self.assertRaises(problem_store.ProblemUnavailable):
            problem_store._download(self.fake,self.bucket,self.row['statement_pdf_path'])

    def test_critical_custom_input_run_uses_metadata_and_checks_visibility(self):
        request=Request({'type':'http','session':{'user':{'email':'synthetic@example.invalid'}}})
        for visible in (True,False):
            with self.subTest(visible=visible),patch.object(server,'QUEUE_MODE','database'), \
                    patch.object(server,'PROBLEM_SOURCE','supabase'),patch.object(server,'_ensure_problems_fresh'), \
                    patch.object(server,'_meta_or_404',return_value=self.prob), \
                    patch.object(server,'_visible_to',return_value=visible), \
                    patch.object(server,'_visible_problem_or_404',side_effect=AssertionError('private suite read')), \
                    patch.object(server,'_create_job',new_callable=AsyncMock,return_value={'id':'synthetic'}) as create, \
                    patch.object(server,'_load_job',new_callable=AsyncMock,return_value={'status':'done','result':{'verdict':'OK'}}):
                if visible:self.assertEqual(asyncio.run(server.run_custom(request,'python','print(1)',None,'synthetic',self.prob.pid,1)),{'verdict':'OK'})
                else:
                    with self.assertRaises(HTTPException) as e:asyncio.run(server.run_custom(request,'python','print(1)',None,'synthetic',self.prob.pid,1))
                    self.assertEqual(e.exception.status_code,404);create.assert_not_awaited()

    def test_critical_import_uploads_local_without_touching_storage(self):
        with patch.object(importer,'_upload_object',side_effect=AssertionError('remote upload')):
            importer._upload_many(self.fake,self.bucket,self.jobs,False,self.public_samples)
        self.assertEqual(files.download(self.bucket,self.row['statement_pdf_path']),self.pdf)

    def test_critical_legacy_cli_publish_and_prune_refused_before_db_access(self):
        for env,args in [({'GRADER_FILE_STORAGE':'supabase'},[]),({},['--prune','--dry-run'])]:
            with self.subTest(args=args),patch.dict(os.environ,env),patch.object(importer,'_client',side_effect=AssertionError('database')),self.assertRaises(SystemExit) as e:
                importer.main(args)
            self.assertEqual(e.exception.code,2)

    def test_critical_backup_publisher_verifies_source_before_switching_indexes(self):
        src=self.base/'source';src.mkdir(mode=0o700);(src/'synthetic').mkdir(mode=0o700)
        raw=b'new synthetic';(src/'synthetic/case.in').write_bytes(raw);(src/'synthetic/case.in').chmod(0o400)
        manifest=self.base/'manifest.json';manifest.write_text(json.dumps({'bucket':self.bucket,'objects':{'synthetic/case.in':{'sha256':'0'*64,'size':len(raw)}}}));manifest.chmod(0o600)
        before=(self.private/'index.json').read_bytes()
        with self.assertRaises(files.FilesUnavailable):publish_backup(manifest,src)
        self.assertEqual((self.private/'index.json').read_bytes(),before)

    def test_critical_cached_index_cannot_hide_corruption_or_permission_change(self):
        files.download(self.bucket,self.row['statement_pdf_path'])
        index=self.public/'index.json';index.chmod(0o600);index.write_bytes(b'{broken');index.chmod(0o400)
        with self.assertRaises(ValueError):files.download(self.bucket,self.row['statement_pdf_path'])

    def test_critical_static_workspace_and_nested_roots_refused(self):
        for root in [str(Path(files.__file__).resolve().parent/'static/files'),
                     '/var/lib/newbiegrader/workspaces/assets']:
            with self.subTest(root=root),patch.dict(os.environ,{'GRADER_PUBLIC_FILE_ROOT':root}),self.assertRaises(files.FilesUnavailable):
                files.root(True)
        with patch.dict(os.environ,{'GRADER_PRIVATE_FILE_ROOT':str(self.public)}),self.assertRaises(files.FilesUnavailable):
            files.validate('api')

    def test_critical_parallel_publishers_preserve_every_index_entry(self):
        from concurrent.futures import ThreadPoolExecutor
        def publish(i):return files.publish(self.bucket,[(f'synthetic/concurrent/{i}.in',str(i).encode(),'text/plain')])
        with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(publish,range(12)))
        for i in range(12):self.assertEqual(files.download(self.bucket,f'synthetic/concurrent/{i}.in'),str(i).encode())

    def test_critical_authoring_file_failure_does_not_change_metadata(self):
        before=json.loads(json.dumps(self.fake.tables['problems']))
        with patch.object(grader,'load_problem',return_value=self.prob),patch.object(importer,'_upload_many',side_effect=OSError('synthetic file failure')):
            status,_=importer.import_one(self.fake,self.bucket,self.prob.pid,False)
        self.assertEqual(status,'failed');self.assertEqual(self.fake.tables['problems'],before)

    def test_critical_valid_backup_publishes_without_changing_source_bytes(self):
        src=self.base/'source';src.mkdir(mode=0o700);(src/'synthetic').mkdir(mode=0o700)
        raw=b'new synthetic';path=src/'synthetic/case.in';path.write_bytes(raw);path.chmod(0o400)
        manifest=self.base/'manifest.json';manifest.write_text(json.dumps({'bucket':self.bucket,'objects':{'synthetic/case.in':{'sha256':hashlib.sha256(raw).hexdigest(),'size':len(raw)}}}));manifest.chmod(0o600)
        result=publish_backup(manifest,src)
        self.assertEqual(result['remote_writes'],0);self.assertEqual(files.download(self.bucket,'synthetic/case.in'),raw)
        self.assertEqual(path.read_bytes(),raw)

    def test_critical_native_file_canary_refuses_without_approved_idle_unit(self):
        tool=Path(__file__).resolve().parents[1]/'tools/ec2_problem_file_canary.py'
        result=subprocess.run([sys.executable,str(tool)],capture_output=True,text=True,timeout=10)
        self.assertNotEqual(result.returncode,0);self.assertIn('REFUSED',result.stderr)

    def test_critical_all_test_bytes_are_local_even_without_database_sample_bytes(self):
        self.row['samples_data']=[]
        with patch.object(self.fake.storage,'from_',side_effect=AssertionError('remote Storage')):
            prob=problem_store.load_problem_supabase(self.prob.pid,self.fake)
        self.assertEqual(grader.tests_hash(prob),self.row['tests_hash'])

    def test_critical_sample_api_checks_visibility_before_local_bytes(self):
        req=Request({'type':'http','session':{}})
        with patch.object(server,'PROBLEM_SOURCE','supabase'),patch.object(server,'_ensure_problems_fresh'), \
                patch.object(server,'_meta_or_404',return_value=self.prob),patch.object(server,'_visible_to',return_value=True), \
                patch.object(server,'_live_hidden_pids',return_value=set()),patch.object(server,'_is_admin',return_value=False), \
                patch.object(problem_store,'fetch_row',side_effect=AssertionError('sample bytes from DB')):
            resp=Response()
            result=server.problem_sample(req,self.prob.pid,self.prob.samples[0],resp);self.assertEqual(result['input'],self.prob.tests[0].input)
            with self.assertRaises(HTTPException) as e:server.problem_sample(req,self.prob.pid,'1001',resp)
            self.assertEqual(e.exception.status_code,404)
            with patch.object(server,'_visible_to',return_value=False),patch.object(problem_store,'_download',side_effect=AssertionError('read before visibility')):
                with self.assertRaises(HTTPException) as e:server.problem_sample(req,self.prob.pid,self.prob.samples[0],resp)
                self.assertEqual(e.exception.status_code,404)

    def test_critical_full_helper_loads_cases_when_metadata_has_no_sample_bytes(self):
        self.row['samples_data']=[]
        meta,_=problem_store.load_meta(self.prob.pid,self.fake)
        self.assertEqual(len(meta.tests),0)
        with patch.object(server,'PROBLEM_SOURCE','supabase'),patch.object(server,'_sb',self.fake), \
                patch.object(server,'PROBLEMS',{self.prob.pid:meta}):
            loaded=server._problem_or_404(self.prob.pid)
        self.assertEqual(grader.tests_hash(loaded),self.row['tests_hash'])

    @unittest.skipUnless(sys.platform.startswith('linux') and os.geteuid()==0,
                         '[CRITICAL-SKIP] real UID/file-access check requires Linux/root')
    def test_critical_api_uid_reads_pdf_but_not_private_test_blob(self):
        api_uid=12345;self.base.chmod(0o755);self.public.chmod(0o750);os.chown(self.public,0,api_uid)
        for path in self.public.iterdir():os.chown(path,0,api_uid);path.chmod(0o440)
        pdf=self.public/(hashlib.sha256(self.pdf).hexdigest()+'.blob')
        private=next(p for p in self.private.iterdir() if p.suffix=='.blob')
        code='import os,sys;os.setgroups([]);os.setgid(12345);os.setuid(12345);open(sys.argv[1],"rb").close();\ntry: open(sys.argv[2],"rb");sys.exit(2)\nexcept PermissionError: pass\n'
        result=subprocess.run([sys.executable,'-c',code,str(pdf),str(private)],capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)

    @unittest.skipUnless(sys.platform.startswith('linux') and os.geteuid()==0,
                         '[CRITICAL-SKIP] real compiler privilege check requires Linux/root')
    def test_critical_compiler_cannot_include_backend_private_blob(self):
        self.base.chmod(0o755);private=next(p for p in self.private.iterdir() if p.suffix=='.blob')
        result=server.run_submission(synthetic_problem(),'.cpp',f'#include "{private}"\nint main(){{}}')
        self.assertEqual(result['verdict'],'CE');self.assertIn('Permission denied',result['compile_error'])


if __name__=='__main__':unittest.main()
