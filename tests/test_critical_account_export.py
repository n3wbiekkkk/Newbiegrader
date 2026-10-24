"""Account export uses a field allowlist and real session authorization."""
from test_critical_login_boundary import LoginBoundary, EMAIL
from unittest.mock import patch


class AccountExport(LoginBoundary):
    def test_export_needs_login(self):
        self.assertEqual(self.client.get('/api/profile/export').status_code, 401)

    def test_export_includes_own_source_but_no_judge_secrets_or_credentials(self):
        self.db.rows('submissions').extend([
            {'id': 'a', 'user_email': EMAIL, 'problem': self.problem.pid,
             'code': 'print(1)', 'results': [{'expected': 'HIDDEN_SENTINEL'}],
             'detail': 'PRIVATE_DIAGNOSTIC', 'created_at': '2026-10-24'},
            {'id': 'b', 'user_email': 'other@example.invalid', 'code': 'OTHER_SOURCE'}])
        self.db.rows('profiles').append({'user_email': EMAIL, 'display_name': 'Me'})
        self.login()
        r = self.client.get('/api/profile/export')
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()['data']['submissions'][0]['code'], 'print(1)')
        self.assertEqual(len(r.json()['data']['submissions']), 1)
        for hidden in ['HIDDEN_SENTINEL', 'PRIVATE_DIAGNOSTIC', 'OTHER_SOURCE',
                       'password_hash', 'auth_version', 'web_sessions', 'email_auth_subject']:
            self.assertNotIn(hidden, r.text)
        self.assertIn('no-store', r.headers['cache-control'])
        self.assertIn('attachment', r.headers['content-disposition'])

    def test_database_failure_does_not_return_partial_export(self):
        self.login()
        with patch.object(self.db, 'table', side_effect=RuntimeError('private db detail')):
            r = self.client.get('/api/profile/export')
        self.assertEqual(r.status_code, 503)
        self.assertNotIn('private db detail', r.text)

    def test_anonymous_health_exposes_count_only(self):
        r = self.client.get('/api/health')
        self.assertEqual(r.status_code, 200)
        self.assertEqual(set(r.json()), {'ok', 'count'})
        self.assertNotIn(self.problem.pid, r.text)
