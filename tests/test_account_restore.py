"""Offline restore state validation; SQL behavior runs against real PG in CI."""
import copy
import datetime as dt
import hashlib
import json
import unittest

from deploy.host import reconcile_account_restore as restore


def snapshot():
    now = dt.datetime.now(dt.timezone.utc)
    salt = 'synthetic-privacy-salt'
    email = 'pending@example.invalid'
    return {
        'format': 1, 'captured_at': now.isoformat(),
        'salt': [{'singleton': True, 'salt': salt}],
        'blocks': [{'email_hash': hashlib.sha256((salt + email).encode()).hexdigest(),
                    'requested_at': (now - dt.timedelta(days=100)).isoformat(),
                    'expires_at': (now - dt.timedelta(days=10)).isoformat()}],
        'work': [{'email': email, 'auth_subject': None,
                  'requested_at': (now - dt.timedelta(days=100)).isoformat()}],
        'audit': [],
    }


class RestoreStateValidation(unittest.TestCase):
    def setUp(self):
        self.state = snapshot()
        self.now = restore.timestamp(self.state['captured_at'])
        self.backup = (self.now - dt.timedelta(days=2)).isoformat()

    def valid(self, state=None, backup=None):
        return restore.validate_state(state or self.state, backup or self.backup, now=self.now)

    def test_pending_work_survives_beyond_ninety_days(self):
        self.assertIs(self.valid(), self.state)

    def test_missing_salt_and_incomplete_or_duplicate_deletion_state_fail_closed(self):
        for field in ('salt', 'blocks', 'work', 'audit'):
            state = copy.deepcopy(self.state)
            del state[field]
            with self.assertRaises((ValueError, KeyError)):
                self.valid(state)
        for field in ('salt', 'blocks'):
            state = copy.deepcopy(self.state)
            state[field] = []
            with self.assertRaises(ValueError):
                self.valid(state)
        state = copy.deepcopy(self.state)
        state['work'] *= 2
        with self.assertRaises(ValueError):
            self.valid(state)

    def test_old_future_or_pre_backup_deletion_snapshot_is_rejected(self):
        for delta in (dt.timedelta(hours=-25), dt.timedelta(minutes=6)):
            state = copy.deepcopy(self.state)
            state['captured_at'] = (self.now + delta).isoformat()
            with self.assertRaises(ValueError):
                self.valid(state)
        for delta in (dt.timedelta(days=-31), dt.timedelta(seconds=1)):
            with self.assertRaises(ValueError):
                self.valid(backup=(self.now + delta).isoformat())

    def test_timezone_and_pending_hash_mismatch_are_rejected(self):
        state = copy.deepcopy(self.state)
        state['salt'][0]['salt'] = 'different-synthetic-salt'
        with self.assertRaises(ValueError):
            self.valid(state)
        with self.assertRaises(ValueError):
            self.valid(backup='2026-10-24T12:00:00')

    def test_audit_cannot_import_personal_data_or_forged_counts(self):
        state = copy.deepcopy(self.state)
        for counts in ({'email': 'private@example.invalid'}, {'users': 1}, {'submissions': True}):
            state['audit'] = [{'id': '00000000-0000-0000-0000-000000000001',
                               'created_at': self.now.isoformat(), 'event': 'account_deleted',
                               'counts': counts}]
            with self.assertRaises(ValueError):
                self.valid(state)

    def test_snapshot_values_never_become_sql_syntax(self):
        state = snapshot()
        state['salt'][0]['salt'] = "literal'; drop table users; --"
        sql = restore.reconciliation_sql(state)
        self.assertNotIn(state['salt'][0]['salt'], sql)
        self.assertNotIn('pending@example.invalid', sql)
        self.assertTrue(sql.endswith('rollback;'))
        self.assertTrue(restore.reconciliation_sql(state, execute=True).endswith('commit;'))


if __name__ == '__main__':
    unittest.main()
