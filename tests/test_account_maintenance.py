"""Retention checks use disposable files and fake transports only."""
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from deploy.host import account_retention

from deploy.host.prune_operator_backups import expired_archives

spec = importlib.util.spec_from_file_location('scheduled_backup',
    Path(__file__).resolve().parents[1] / 'deploy/host/newbiegrader-backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class BackupRetention(unittest.TestCase):
    def test_local_expiration_preserves_identity_unknown_files_and_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            for name in ['20260901T000000Z-data.tar.age', '20261023T000000Z-data.tar.age',
                         'backup-identity.txt', 'unknown.tar.age', '20269999T000000Z-data.tar.age']:
                (root / name).write_text('synthetic')
            (root / '20260101T000000Z-link.tar.age').symlink_to(root / 'backup-identity.txt')
            now = dt.datetime(2026, 10, 24, tzinfo=dt.timezone.utc)
            expired = expired_archives(root, now=now)
            self.assertEqual([p.name for p in expired], ['20260901T000000Z-data.tar.age'])
            root.chmod(0o755)
            with self.assertRaises(ValueError):
                expired_archives(root, now=now)

    def test_remote_age_is_enforced_even_when_count_is_below_keep(self):
        old = '20000101T000000Z-backup.tar.age'
        recent = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-backup.tar.age'
        calls = []
        def open_(request, **kwargs):
            calls.append(request)
            return io.BytesIO(json.dumps([{'name': old}, {'name': recent},
                {'name': 'backup-identity.txt'}, {'name': 'unrecognized.tar.age'}]).encode()
                if request.get_method() == 'POST' else b'{}')
        with patch.object(backup.urllib.request, 'urlopen', side_effect=open_):
            self.assertEqual(backup.prune('https://synthetic.invalid', 'synthetic-secret',
                'synthetic-bucket', 14), [old])
        self.assertEqual(sum(r.get_method() == 'DELETE' for r in calls), 1)
        self.assertEqual(calls[-1].full_url,
            'https://synthetic.invalid/storage/v1/object/synthetic-bucket')
        self.assertEqual(json.loads(calls[-1].data), {'prefixes': [old]})
        self.assertEqual(calls[-1].get_header('Content-type'), 'application/json')

    def test_remote_prune_errors_are_visible_to_backup_monitoring(self):
        with patch.object(backup.urllib.request, 'urlopen', side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):
                backup.prune('https://synthetic.invalid', 'synthetic-secret', 'bucket', 14)

    def test_account_migration_stays_appended_and_server_only(self):
        root = Path(__file__).resolve().parents[1]
        sql = (root / 'supabase/account_lifecycle.sql').read_text()
        self.assertTrue((root / 'supabase/schema.sql').read_text().endswith(sql))
        self.assertNotIn('security definer', sql)
        self.assertIn("interval '1 year'", sql)
        self.assertIn("interval '90 days'", sql)


class AccountDeletionRecovery(unittest.TestCase):
    def client(self):
        client = Mock()
        client.table.return_value.select.return_value.limit.return_value.execute.return_value.data = [
            {'email': 'synthetic@example.invalid', 'auth_subject': '00000000-0000-0000-0000-000000000001'}]
        client.rpc.return_value.execute.side_effect = [SimpleNamespace(data={'ok': True}),
            SimpleNamespace(data={'jobs': 1, 'submissions': 2, 'PRIVATE_FIELD': 'sentinel'})]
        return client

    def test_default_dry_run_never_deletes_or_prunes(self):
        client = self.client()
        with patch.object(account_retention.email_auth, 'delete_identity') as provider:
            result = account_retention.maintain(client, {})
        self.assertEqual(result, {'execute': False, 'pending_deletions': 1})
        provider.assert_not_called()
        client.rpc.assert_not_called()

    def test_recovery_removes_provider_before_finishing_app_deletion(self):
        client = self.client()
        sequence = []
        client.rpc.side_effect = lambda name, params: sequence.append(name) or client.rpc.return_value
        with patch.object(account_retention.email_auth, 'delete_identity',
                side_effect=lambda *args: sequence.append('provider')):
            result = account_retention.maintain(client,
                {'SUPABASE_URL': 'https://synthetic.invalid', 'SUPABASE_KEY': 'synthetic'}, execute=True)
        self.assertEqual(sequence, ['provider', 'account_delete_finish', 'account_retention_prune'])
        self.assertEqual(result, {'finished': 1, 'failed': 0, 'retention': {'jobs': 1, 'submissions': 2}})
        self.assertNotIn('sentinel', str(result))

    def test_provider_failure_keeps_pending_work_and_reports_failure(self):
        client = self.client()
        client.rpc.return_value.execute.side_effect = [SimpleNamespace(data={'jobs': 0, 'submissions': 0})]
        with patch.object(account_retention.email_auth, 'delete_identity', side_effect=RuntimeError('private sentinel')):
            result = account_retention.maintain(client,
                {'SUPABASE_URL': 'https://synthetic.invalid', 'SUPABASE_KEY': 'synthetic'}, execute=True)
        self.assertEqual(result['failed'], 1)
        client.rpc.assert_called_once_with('account_retention_prune', {})
        self.assertNotIn('sentinel', str(result))
