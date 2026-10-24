"""Private author archive import preserves local work and rejects unsafe bytes."""
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from tools import problem_sync as sync


class ProblemSync(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base/'source'
        (self.root/'problems/synthetic/tests').mkdir(parents=True)
        (self.root/'examples').mkdir()
        for name, text in {'problems/synthetic/config.json': '{}',
                           'problems/synthetic/solution.md': '# synthetic',
                           'problems/synthetic/solution.cpp': 'int main() {}',
                           'problems/synthetic/solution.cpp.verify.json': '{}',
                           'problems/synthetic/tests/01.in': '1\n',
                           'problems/synthetic/tests/01.out': '1\n',
                           'examples/synthetic_ref.py': 'print(1)\n',
                           '.env': 'NEVER_EXPORT=private',
                           'problems/.DS_Store': 'irrelevant'}.items():
            (self.root/name).write_text(text)
        self.archive = self.base/'private.tar.gz'

    def test_roundtrip_and_secret_exclusion(self):
        self.assertEqual(sync.pack(self.archive, self.root), 7)
        stage = self.base/'stage'
        self.assertEqual(sync.unpack(self.archive, stage), 7)
        self.assertEqual((stage/'problems/synthetic/tests/01.in').read_text(), '1\n')
        self.assertFalse((stage/'.env').exists())
        self.assertEqual(self.archive.stat().st_mode & 0o777, 0o600)
        self.assertEqual((stage/'problems/synthetic/config.json').stat().st_mode & 0o777, 0o600)

    def test_existing_archive_or_destination_is_never_overwritten(self):
        sync.pack(self.archive, self.root)
        with self.assertRaises(ValueError):
            sync.pack(self.archive, self.root)
        stage = self.base/'existing'
        stage.mkdir()
        marker = stage/'local-work'
        marker.write_text('keep')
        with self.assertRaises(ValueError):
            sync.unpack(self.archive, stage)
        self.assertEqual(marker.read_text(), 'keep')

    def malicious(self, names):
        with tarfile.open(self.archive, 'w:gz') as a:
            for name, body in names:
                info = tarfile.TarInfo(name)
                info.size = len(body)
                a.addfile(info, io.BytesIO(body))

    def test_traversal_and_duplicate_entries_are_rejected_before_creating_destination(self):
        for names in [[('../escape', b'bad')], [('problem-sync.json', b'{}'), ('problem-sync.json', b'{}')]]:
            self.malicious(names)
            with self.assertRaises(ValueError):
                sync.unpack(self.archive, self.base/'stage')
            self.assertFalse((self.base/'stage').exists())

    def test_checksum_corruption_is_rejected(self):
        manifest = json.dumps({'version': 1, 'files': {'problems/synthetic/config.json': {'size': 2, 'sha256': '0'*64}}}).encode()
        self.malicious([('problem-sync.json', manifest), ('problems/synthetic/config.json', b'{}')])
        with self.assertRaises(ValueError):
            sync.unpack(self.archive, self.base/'stage')
        self.assertFalse((self.base/'stage').exists())

    def test_symlink_sources_are_rejected(self):
        path = self.root/'examples/synthetic_ref.py'
        path.unlink()
        path.symlink_to(self.root/'.env')
        with self.assertRaises(ValueError):
            sync.pack(self.archive, self.root)
