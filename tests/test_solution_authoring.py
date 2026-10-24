"""Private solution tooling uses synthetic authoring files only."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from tools import make_solution_tex as renderer
from tools import solution_authoring as author
from tools import publish_solutions as publisher


class SolutionAuthoring(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)/'synthetic'
        self.folder.mkdir()
        self.cfg = {'title': 'ทดสอบ (Synthetic)', 'time_limit': 1, 'memory_limit': 32, 'samples': ['01']}
        (self.folder/'config.json').write_text(json.dumps(self.cfg))
        (self.folder/'statement.md').write_text('# ทดสอบ\n')
        (self.folder/'tests').mkdir()
        (self.folder/'tests/01.in').write_text('1\n')
        (self.folder/'tests/01.out').write_text('1\n')
        self.md = '\n'.join('## '+s+'\nคำอธิบาย\n' for s in renderer.REQUIRED_SECTIONS)
        (self.folder/'solution.md').write_text(self.md)
        (self.folder/'solution.py').write_text('print(1)\n')
        (self.folder/'solution.cpp').write_text('int main() { return 0; }\n')

    def test_required_sections_and_unfinished_prose(self):
        self.assertEqual(renderer.validate_source(self.folder), self.md)
        for text in ['## แนวคิด\nคำอธิบาย', self.md+'TODO']:
            (self.folder/'solution.md').write_text(text)
            with self.assertRaises(ValueError):
                renderer.validate_source(self.folder)

    def test_source_hash_tracks_code_statement_and_public_samples(self):
        original = renderer.source_hash(self.folder)
        for name in ['solution.py', 'solution.cpp', 'statement.md', 'tests/01.out']:
            p = self.folder/name
            before = p.read_bytes()
            p.write_bytes(before+b'\n')
            self.assertNotEqual(renderer.source_hash(self.folder), original)
            p.write_bytes(before)
            self.assertEqual(renderer.source_hash(self.folder), original)

    def test_code_backslashes_are_escaped_once_and_page_rows_are_bounded(self):
        escaped = renderer.escape_code(r"b'\x01' {value}")
        self.assertIn(r'\textbackslash{}x01', escaped)
        self.assertNotIn(r'\textbackslash\{', escaped)
        tex = renderer.code_pages('print(1)\n'*54)
        self.assertEqual(tex.count(r'\newpage'), 2)

    def test_build_record_and_pdf_integrity(self):
        import hashlib
        pdf = self.folder/'solution.pdf'
        pdf.write_bytes(b'%PDF-1.4\nsynthetic')
        record = {'kind': 'solution', 'source_sha256': renderer.source_hash(self.folder),
                  'pdf_sha256': hashlib.sha256(pdf.read_bytes()).hexdigest()}
        (self.folder/'solution.build.json').write_text(json.dumps(record))
        self.assertTrue(author.check(self.folder))
        pdf.write_bytes(b'%PDF-changed')
        with self.assertRaises(ValueError):
            author.check(self.folder)

    def test_publication_rejects_code_changes_after_successful_qualification(self):
        import hashlib
        from types import SimpleNamespace
        from contextlib import ExitStack
        record = {'accepted': True, 'passed': 1, 'total': 1, 'tests_sha256': 'suite',
                  'code_sha256': hashlib.sha256((self.folder/'solution.py').read_bytes()).hexdigest(),
                  'config_sha256': hashlib.sha256((self.folder/'config.json').read_bytes()).hexdigest()}
        for lang, (filename, report_name) in author.LANGUAGES.items():
            record.update(language=lang, code_sha256=hashlib.sha256(
                (self.folder/filename).read_bytes()).hexdigest())
            (self.folder/report_name).write_text(json.dumps(record))
        (self.folder/'solution.pdf').write_bytes(b'%PDF-synthetic')
        with ExitStack() as stack:
            stack.enter_context(patch.object(publisher.files, 'backend', return_value='local'))
            stack.enter_context(patch.object(publisher.grader, 'PROBLEMS_DIR', self.folder.parent))
            stack.enter_context(patch.object(publisher.grader, 'load_problem', return_value=SimpleNamespace(tests=[1])))
            stack.enter_context(patch.object(publisher.grader, 'tests_hash', return_value='suite'))
            stack.enter_context(patch.object(publisher.solution_authoring, 'check', return_value=True))
            write = stack.enter_context(patch.object(publisher.files, 'publish'))
            stack.enter_context(patch('sys.argv', ['publish_solutions.py', '--all', '--dry-run']))
            publisher.main()
            for filename in ('solution.cpp', 'solution.py'):
                path = self.folder/filename
                original = path.read_text()
                path.write_text(original+'\n')
                with self.assertRaises(ValueError):
                    publisher.main()
                path.write_text(original)
            (self.folder/'solution.cpp.verify.json').unlink()
            with self.assertRaises(OSError):
                publisher.main()
            write.assert_not_called()

    def test_missing_or_unfinished_cpp_is_rejected(self):
        path = self.folder/'solution.cpp'
        path.unlink()
        with self.assertRaises(OSError):
            author.check(self.folder, require_pdf=False)
        path.write_text('// TODO\n')
        with self.assertRaises(ValueError):
            author.check(self.folder, require_pdf=False)

    def test_cpp_pages_have_explicit_language_heading(self):
        tex = renderer.code_pages('int main() {}\n'*54, 'C++17')
        self.assertEqual(tex.count(r'\newpage'), 2)
        self.assertIn('++17', tex)
        self.assertNotIn('Python 3', tex)

    def test_verify_runs_both_languages_and_propagates_failure(self):
        from types import SimpleNamespace
        import hashlib
        import grader
        calls = []
        def run(args, **kwargs):
            filename = Path(args[4]).name
            calls.append(filename)
            report = Path(args[-1])
            report.write_text(json.dumps({'accepted': filename == 'solution.py'}))
            return SimpleNamespace(returncode=0 if filename == 'solution.py' else 1)
        root = self.folder.parent/'repo'
        (root/'problems').mkdir(parents=True)
        import shutil
        shutil.copytree(self.folder, root/'problems/synthetic')
        with patch.object(author, 'ROOT', root), \
                patch.object(author, 'check', return_value=True), \
                patch.object(author.subprocess, 'run', side_effect=run), \
                patch.object(grader, 'load_problem', return_value=object()), \
                patch.object(grader, 'tests_hash', return_value='suite'), \
                patch('sys.argv', ['solution_authoring.py', 'verify', 'synthetic']):
            with self.assertRaises(SystemExit) as stopped:
                author.main()
        self.assertEqual(stopped.exception.code, 1)
        self.assertEqual(calls, ['solution.py', 'solution.cpp'])
        record = json.loads((root/'problems/synthetic/solution.verify.json').read_text())
        self.assertEqual(record['language'], 'py')
        self.assertEqual(record['code_sha256'], hashlib.sha256(
            (self.folder/'solution.py').read_bytes()).hexdigest())
