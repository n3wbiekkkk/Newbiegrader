# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
import os
from pathlib import Path
import tempfile
import unittest

from deploy.ec2.merge_uid_ledger import append_reservations, records


class LedgerRecords(unittest.TestCase):
    def test_invalid_incoming_records_are_rejected(self):
        for data in (b'', b'1000000', b'999999\n', b'2147483648\n',
                     b'1000001\n1000000\n', b'1000000\n1000000\n', b'x\n'):
            with self.subTest(data=data), self.assertRaises(ValueError):
                records(data)


@unittest.skipUnless(hasattr(os, 'geteuid') and os.geteuid() == 0,
                     'LINUX_ROOT_REQUIRED: numeric UID ledger ownership tests require root')
class LedgerMerge(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.file = self.root / 'allocated-uids'

    def test_merge_preserves_prior_bytes_and_never_moves_backwards(self):
        self.assertEqual(append_reservations(self.root, b'1000000\n1000002\n'), 2)
        before = self.file.read_bytes()
        self.assertEqual(append_reservations(self.root, b'1000000\n1000001\n'), 0)
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(append_reservations(self.root, b'1000003\n'), 1)
        self.assertEqual(self.file.read_bytes(), before + b'1000003\n')

    def test_empty_existing_or_partial_ledger_refuses_reuse(self):
        for content in (b'', b'1000000'):
            self.file.write_bytes(content)
            self.file.chmod(0o600)
            with self.assertRaises(ValueError):
                append_reservations(self.root, b'1000001\n')
            self.assertEqual(self.file.read_bytes(), content)

    def test_symlink_and_public_ledger_are_rejected(self):
        other = self.root / 'other'
        other.write_bytes(b'1000000\n')
        self.file.symlink_to(other)
        with self.assertRaises(OSError):
            append_reservations(self.root, b'1000001\n')
        self.file.unlink()
        self.file.write_bytes(b'1000000\n')
        self.file.chmod(0o644)
        with self.assertRaises(ValueError):
            append_reservations(self.root, b'1000001\n')
