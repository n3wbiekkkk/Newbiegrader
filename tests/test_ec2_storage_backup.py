import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from deploy.ec2.backup_storage import restore_files, safe_key


def fixture(*, bad_hash=False, extra=None):
    stream = io.BytesIO()
    content = b'synthetic canary bytes\n'
    with tarfile.open(fileobj=stream, mode='w') as archive:
        info = tarfile.TarInfo('objects/synthetic/tests/01.in')
        info.size = len(content)
        archive.addfile(info, io.BytesIO(content))
        if extra is not None:
            archive.addfile(extra, io.BytesIO())
        manifest = {'bucket': 'judge-assets', 'objects': {'synthetic/tests/01.in': {
            'size': len(content), 'sha256': 'wrong' if bad_hash else hashlib.sha256(content).hexdigest()}}}
        body = json.dumps(manifest).encode()
        info = tarfile.TarInfo('manifest.json')
        info.size = len(body)
        archive.addfile(info, io.BytesIO(body))
    stream.seek(0)
    return stream


class StorageRecovery(unittest.TestCase):
    def test_synthetic_bytes_are_recovered_and_rehashed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            result = restore_files(fixture(), root)
            self.assertEqual(result, {'objects': 1, 'bytes': 23, 'all_restored_hashes_match': True})
            path = root / 'synthetic/tests/01.in'
            self.assertEqual(path.read_bytes(), b'synthetic canary bytes\n')
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)

    def test_path_traversal_and_aliases_are_refused(self):
        for value in ('/absolute', '../escape', 'a/../b', 'a//b', 'a/./b', 'a\\b', 'a\nb', ''):
            with self.subTest(value=value), self.assertRaises(ValueError):
                safe_key(value)

    def test_wrong_hash_fails_the_restore_gate(self):
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
            restore_files(fixture(bad_hash=True), Path(tmp))

    def test_symlinks_duplicates_and_traversal_members_are_refused(self):
        for name, kind in [('objects/link', tarfile.SYMTYPE),
                           ('objects/synthetic/tests/01.in', tarfile.REGTYPE),
                           ('objects/../escape', tarfile.REGTYPE)]:
            info = tarfile.TarInfo(name)
            info.type = kind
            info.linkname = '/synthetic-outside' if kind == tarfile.SYMTYPE else ''
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp, self.assertRaises(ValueError):
                restore_files(fixture(extra=info), Path(tmp))
