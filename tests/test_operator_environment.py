"""Operator preflight and encrypted-file publication regressions."""
import hashlib
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch

from deploy.host import deliver_backup
from tools.check_test_environment import check_interpreter


class BackupDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root / 'source.age'
        self.source.write_bytes(b'synthetic encrypted bytes')
        self.source.chmod(0o600)
        self.target = self.root / 'target.age'
        self.digest = hashlib.sha256(self.source.read_bytes()).hexdigest()

    def test_cross_mount_publication_never_renames_source(self):
        # Source-to-target rename would raise EXDEV across mounts. The only
        # link operation must be between the target-local staging file and target.
        original = deliver_backup.os.link
        def local_link(source, target):
            self.assertEqual(Path(source).parent, Path(target).parent)
            return original(source, target)
        with patch.object(deliver_backup.os, 'rename', side_effect=OSError('EXDEV')), \
                patch.object(deliver_backup.os, 'replace', side_effect=OSError('EXDEV')), \
                patch.object(deliver_backup.os, 'link', side_effect=local_link):
            report = deliver_backup.deliver(self.source, self.target, self.digest)
        self.assertEqual(self.target.read_bytes(), self.source.read_bytes())
        self.assertEqual(self.target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(report['sha256'], self.digest)
        self.assertEqual(list(self.root.glob('.backup-*')), [])

    def test_existing_target_and_symlink_are_never_overwritten(self):
        for symlink in (False, True):
            with self.subTest(symlink=symlink):
                if symlink:
                    self.target.symlink_to(self.root / 'absent')
                else:
                    self.target.write_bytes(b'keep me')
                with self.assertRaises(FileExistsError):
                    deliver_backup.deliver(self.source, self.target, self.digest)
                if not symlink:
                    self.assertEqual(self.target.read_bytes(), b'keep me')
                else:
                    self.assertTrue(self.target.is_symlink())
                self.target.unlink()
                self.assertEqual(list(self.root.glob('.backup-*')), [])

    def test_wrong_hash_and_interrupted_copy_publish_nothing(self):
        with self.assertRaisesRegex(ValueError, 'SHA256 mismatch'):
            deliver_backup.deliver(self.source, self.target, '0' * 64)
        with patch.object(deliver_backup.os, 'fsync', side_effect=OSError('interrupted')):
            with self.assertRaises(OSError):
                deliver_backup.deliver(self.source, self.target, self.digest)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob('.backup-*')), [])
        self.assertTrue(self.source.exists())

    def test_incomplete_copy_is_not_published(self):
        info = self.source.stat()
        with patch.object(deliver_backup.os, 'fstat', return_value=SimpleNamespace(
                st_mode=info.st_mode, st_size=info.st_size + 1)):
            with self.assertRaisesRegex(ValueError, 'Source size'):
                deliver_backup.deliver(self.source, self.target, self.digest)
        self.assertFalse(self.target.exists())
        self.assertEqual(list(self.root.glob('.backup-*')), [])

    def test_source_symlink_and_public_directory_are_refused(self):
        link = self.root / 'link.age'
        link.symlink_to(self.source)
        with self.assertRaises(OSError):
            deliver_backup.deliver(link, self.target, self.digest)
        self.root.chmod(0o755)
        with self.assertRaisesRegex(ValueError, 'directory'):
            deliver_backup.deliver(self.source, self.target, self.digest)


class TestInterpreterPreflight(unittest.TestCase):
    def test_venv_symlink_in_temporary_root_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            executable = root / 'venv/bin/python'
            executable.parent.mkdir(parents=True)
            executable.symlink_to('/usr/bin/python3')
            with self.assertRaisesRegex(RuntimeError, 'temporary root'):
                check_interpreter(executable, [root])

    def test_interpreter_outside_temporary_root_is_allowed(self):
        check_interpreter('/opt/project/venv/bin/python', ['/tmp', '/var/tmp'])
