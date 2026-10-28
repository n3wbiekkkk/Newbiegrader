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
import account_deletion

from deploy.host.prune_operator_backups import expired_archives, reviewed_archives
import hashlib

spec = importlib.util.spec_from_file_location('scheduled_backup',
    Path(__file__).resolve().parents[1] / 'deploy/host/newbiegrader-backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class BackupRetention(unittest.TestCase):
    def test_reviewed_historical_formats_require_matching_hash_and_stay_inside_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            archive = root / 'old-snapshot.dump.age'
            archive.write_bytes(b'synthetic encrypted archive')
            manifest = root / 'reviewed.json'
            row = {'path': archive.name, 'created_at': '2000-01-01T00:00:00Z',
                   'sha256': hashlib.sha256(archive.read_bytes()).hexdigest()}
            def save(rows):
                manifest.write_text(json.dumps({'format': 1, 'archives': rows}))
                manifest.chmod(0o600)
            save([row])
            self.assertEqual(reviewed_archives(root, manifest), [archive])
            archive.write_bytes(b'changed')
            with self.assertRaises(ValueError):
                reviewed_archives(root, manifest)
            for name in ('../escape.tar.age', '/escape.tar.age', 'backup-identity.txt',
                         'backup-identity.tar.age', 'allocated-uids.tar.age'):
                save([{**row, 'path': name}])
                with self.assertRaises(ValueError):
                    reviewed_archives(root, manifest)
            link = root / 'link'
            link.symlink_to(root, target_is_directory=True)
            save([{**row, 'path': 'link/' + archive.name}])
            with self.assertRaises(ValueError):
                reviewed_archives(root, manifest)
            save([row, row])
            with self.assertRaises(ValueError):
                reviewed_archives(root, manifest)
            archive.unlink()
            save([row])
            self.assertEqual(reviewed_archives(root, manifest), [])

    def test_reviewed_canonical_directories_cover_future_archives_without_following_symlinks(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            root.chmod(0o700)
            canonical = root / 'host-backups'
            canonical.mkdir(mode=0o700)
            future = canonical / '20000101T000000Z-backup.tar.age'
            future.write_bytes(b'synthetic encrypted archive')
            (canonical / '20000101T000000Z-authoring-source.tar.age').write_bytes(b'preserve source')
            (canonical / '20000101T000000Z-allocated-uids.tar.age').write_bytes(b'preserve ledger')
            manifest = root / 'reviewed.json'
            manifest.write_text(json.dumps({'format': 1, 'archives': [],
                                           'canonical_directories': ['host-backups']}))
            manifest.chmod(0o600)
            self.assertEqual(reviewed_archives(root, manifest), [future])
            canonical.rename(root / 'real')
            canonical.symlink_to(root / 'real', target_is_directory=True)
            with self.assertRaises(ValueError):
                reviewed_archives(root, manifest)

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

    def test_host_backup_retention_stays_inside_its_namespace(self):
        old = '20000101T000000Z-backup.tar.age'
        calls = []
        def open_(request, **kwargs):
            calls.append(request)
            return io.BytesIO(json.dumps([{'name': old}, {'name': 'hosts'},
                {'name': '../other/' + old}]).encode() if request.get_method() == 'POST' else b'{}')
        with patch.object(backup.urllib.request, 'urlopen', side_effect=open_):
            self.assertEqual(backup.prune('https://synthetic.invalid', 'synthetic-secret',
                'synthetic-bucket', 14, prefix='hosts/promma-server/'), ['hosts/promma-server/' + old])
        self.assertEqual(json.loads(calls[0].data)['prefix'], 'hosts/promma-server/')
        self.assertEqual(json.loads(calls[-1].data), {'prefixes': ['hosts/promma-server/' + old]})

    def test_backup_namespace_rejects_traversal_and_ambiguous_paths(self):
        self.assertEqual(backup.object_prefix(''), '')
        self.assertEqual(backup.object_prefix('hosts/promma-server'), 'hosts/promma-server/')
        for value in ('../other', '/root', 'hosts//other', 'hosts/../other', 'a?b', 'a\\b'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                backup.object_prefix(value)

    def test_remote_prune_errors_are_visible_to_backup_monitoring(self):
        with patch.object(backup.urllib.request, 'urlopen', side_effect=OSError('synthetic')):
            with self.assertRaises(OSError):
                backup.prune('https://synthetic.invalid', 'synthetic-secret', 'bucket', 14)

    def test_account_migration_stays_appended_and_server_only(self):
        root = Path(__file__).resolve().parents[1]
        sql = (root / 'supabase/account_lifecycle.sql').read_text()
        schema = (root / 'supabase/schema.sql').read_text()
        self.assertIn(sql, schema)
        self.assertIn((root / 'supabase/auth_email_capacity.sql').read_text(), schema)
        fences = (root / 'supabase/account_write_fences.sql').read_text()
        live_roles = (root / 'supabase/live_roles_submission_time.sql').read_text()
        self.assertIn(fences, schema)
        self.assertTrue(schema.endswith(live_roles))
        self.assertLess(schema.index(fences), schema.index(live_roles))
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
        with patch.object(account_deletion.email_auth, 'delete_identity') as provider:
            result = account_retention.maintain(client, {})
        self.assertEqual(result, {'execute': False, 'pending_deletions': 1})
        provider.assert_not_called()
        client.rpc.assert_not_called()

    def test_recovery_removes_provider_before_finishing_app_deletion(self):
        client = self.client()
        sequence = []
        client.rpc.side_effect = lambda name, params: sequence.append(name) or client.rpc.return_value
        with patch.object(account_deletion.email_auth, 'delete_identity',
                side_effect=lambda *args: sequence.append('provider')):
            result = account_retention.maintain(client,
                {'SUPABASE_URL': 'https://synthetic.invalid', 'SUPABASE_KEY': 'synthetic'}, execute=True)
        self.assertEqual(sequence, ['provider', 'account_delete_finish', 'account_retention_prune'])
        self.assertEqual(result, {'finished': 1, 'failed': 0, 'retention': {'jobs': 1, 'submissions': 2}})
        self.assertNotIn('sentinel', str(result))

    def test_provider_failure_keeps_pending_work_and_reports_failure(self):
        client = self.client()
        client.rpc.return_value.execute.side_effect = [SimpleNamespace(data={'jobs': 0, 'submissions': 0})]
        with patch.object(account_deletion.email_auth, 'delete_identity', side_effect=RuntimeError('private sentinel')):
            result = account_retention.maintain(client,
                {'SUPABASE_URL': 'https://synthetic.invalid', 'SUPABASE_KEY': 'synthetic'}, execute=True)
        self.assertEqual(result['failed'], 1)
        client.rpc.assert_called_once_with('account_retention_prune', {})
        self.assertNotIn('sentinel', str(result))
