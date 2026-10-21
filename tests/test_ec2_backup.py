# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
import io
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from deploy.ec2 import backup_state


class EncryptedStateBackup(unittest.TestCase):
    def setUp(self):
        previous = os.umask(0o077)
        self.addCleanup(os.umask, previous)

    def test_named_tunnel_files_are_explicitly_opted_in(self):
        for include in (False, True):
            with self.subTest(include_tunnel=include), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                identity = directory / 'backup-identity.txt'
                identity.write_text('synthetic-test-identity')
                identity.chmod(0o400)
                source = SimpleNamespace(stdout=io.BytesIO(b'synthetic-archive'), wait=lambda: 0)

                def run(args, **kwargs):
                    if args[0:2] == ['age', '-r']:
                        kwargs['stdout'].write(b'synthetic-encrypted-archive')
                    return SimpleNamespace(returncode=0)

                argv = ['backup_state.py', '--directory', tmp]
                if include:
                    argv += ['--include-tunnel', '--include-problem-files-config',
                             '--ssh-host-key-alias', 'synthetic-known-host']
                with patch('sys.argv', argv), \
                        patch.object(backup_state.subprocess, 'check_output', return_value='synthetic-recipient'), \
                        patch.object(backup_state.subprocess, 'Popen', return_value=source) as popen, \
                        patch.object(backup_state.subprocess, 'run', side_effect=run) as runner, \
                        patch('builtins.print'):
                    backup_state.main()
                remote = popen.call_args.args[0][-1]
                self.assertIn('flock --shared', remote)
                self.assertIn('etc/newbiegrader/api.env', remote)
                self.assertEqual('etc/newbiegrader/tunnel-token' in remote, include)
                self.assertEqual('etc/systemd/system/newbiegrader-tunnel.service' in remote, include)
                self.assertEqual('etc/newbiegrader/problem-files.env' in remote, include)
                self.assertEqual('30-problem-files.conf' in remote, include)
                self.assertEqual('HostKeyAlias=synthetic-known-host' in popen.call_args.args[0], include)
                self.assertIn('--decrypt', runner.call_args.args[0])
                archive, = directory.glob('*.tar.age')
                self.assertEqual(archive.stat().st_mode & 0o777, 0o600)

    def test_public_backup_directory_is_rejected_before_connecting(self):
        with tempfile.TemporaryDirectory() as tmp:
            Path(tmp).chmod(0o755)
            with patch('sys.argv', ['backup_state.py', '--directory', tmp]), \
                    patch.object(backup_state.subprocess, 'Popen') as popen:
                with self.assertRaisesRegex(SystemExit, 'must be private'):
                    backup_state.main()
                popen.assert_not_called()
