"""The same resume interface is used by HTTP and scheduled recovery."""
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from account_deletion import AccountDeletion, DeletionIncomplete
import account_deletion


EMAIL = 'deletion@example.invalid'
SUBJECT = '00000000-0000-0000-0000-000000000001'


class PreparedDeletionTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock()
        self.client.rpc.return_value.execute.return_value = SimpleNamespace(data={'ok': True})
        self.deletion = AccountDeletion(self.client, 'https://synthetic.invalid', 'synthetic')
        self.lookup = self.enterContext(patch.object(account_deletion.email_auth, 'find_identity', return_value=SUBJECT))
        self.provider = self.enterContext(patch.object(account_deletion.email_auth, 'delete_identity'))

    def test_mapped_identity_is_deleted_before_finish_without_lookup(self):
        sequence = []
        self.provider.side_effect = lambda *args: sequence.append('provider')
        self.client.rpc.side_effect = lambda *args: sequence.append('finish') or self.client.rpc.return_value
        self.deletion.resume(EMAIL, SUBJECT)
        self.assertEqual(sequence, ['provider', 'finish'])
        self.lookup.assert_not_called()
        self.client.rpc.assert_called_once_with('account_delete_finish', {'p_email': EMAIL})

    def test_legacy_identity_lookup_is_bounded_to_the_requested_account(self):
        self.deletion.resume(EMAIL)
        self.lookup.assert_called_once_with('https://synthetic.invalid', 'synthetic', EMAIL)
        self.provider.assert_called_once_with('https://synthetic.invalid', 'synthetic', SUBJECT)

    def test_missing_identity_can_finish_prepared_deletion(self):
        self.lookup.return_value = None
        self.deletion.resume(EMAIL)
        self.provider.assert_not_called()
        self.client.rpc.assert_called_once()

    def test_provider_failures_never_finish_or_retry_inline(self):
        for stage in ('lookup', 'delete'):
            with self.subTest(stage=stage):
                self.lookup.reset_mock(side_effect=True)
                self.provider.reset_mock(side_effect=True)
                self.lookup.return_value = SUBJECT
                failing = self.lookup if stage == 'lookup' else self.provider
                failing.side_effect = OSError('private provider sentinel')
                with self.assertRaises(DeletionIncomplete) as raised:
                    self.deletion.resume(EMAIL)
                self.assertEqual(str(raised.exception), 'account deletion incomplete')
                self.assertTrue(raised.exception.__suppress_context__)
                self.assertEqual(failing.call_count, 1)
                self.client.rpc.assert_not_called()

    def test_finish_failure_can_resume_after_provider_identity_disappears(self):
        self.client.rpc.return_value.execute.side_effect = [OSError('ambiguous finish'),
                                                          SimpleNamespace(data={'ok': True})]
        with self.assertRaises(DeletionIncomplete):
            self.deletion.resume(EMAIL)
        self.assertEqual(self.client.rpc.call_count, 1)
        self.lookup.return_value = None
        self.deletion.resume(EMAIL)
        self.assertEqual(self.client.rpc.call_count, 2)
        self.provider.assert_called_once()

    def test_unconfirmed_finish_is_never_success(self):
        for data in (None, [], {}, {'ok': False}):
            with self.subTest(data=data):
                self.client.rpc.return_value.execute.return_value = SimpleNamespace(data=data)
                with self.assertRaises(DeletionIncomplete):
                    self.deletion.resume(EMAIL, SUBJECT)


if __name__ == '__main__':
    unittest.main()
