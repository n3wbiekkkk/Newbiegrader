from test_critical_login_boundary import LoginBoundary, EMAIL, PASSWORD, server
from unittest.mock import patch
from fastapi.testclient import TestClient


class AccountDeletion(LoginBoundary):
    def test_write_fence_patch_is_appended_to_canonical_schema(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[1]
        patch_sql = (root / 'supabase/account_write_fences.sql').read_text()
        self.assertIn(patch_sql, (root / 'supabase/schema.sql').read_text())
        self.assertIn('security invoker', patch_sql)
        self.assertNotIn('security definer', patch_sql)

    def setUp(self):
        super().setUp()
        self.stack.enter_context(patch.object(server, 'QUEUE_MODE', 'database'))

    def delete(self):
        return self.client.request('DELETE', '/api/profile',
            headers={'Origin': server.FRONTEND_URL}, json={'confirmation': EMAIL})

    def test_deletion_removes_data_and_revokes_every_device(self):
        self.db.rows('users')[0]['email_auth_subject'] = '00000000-0000-0000-0000-000000000001'
        for table in ['submissions','profiles','reports','contest_registrations','judge_quota_events']:
            self.db.rows(table).append({'id': 'own', 'user_email': EMAIL})
            self.db.rows(table).append({'id': 'other', 'user_email': 'other@example.invalid'})
        self.login()
        cookie1 = self.client.cookies.get('ng_session')
        self.login()
        cookie2 = self.client.cookies.get('ng_session')
        with patch.object(server.email_auth, 'delete_identity') as provider:
            r = self.delete()
        self.assertEqual(r.status_code,200,r.text)
        provider.assert_called_once()
        for cookie in [cookie1,cookie2]:
            with TestClient(server.app,base_url='https://testserver') as device:
                self.assertEqual(device.get('/api/profile',headers={'Cookie':'ng_session='+cookie}).status_code,401)
        for table in ['submissions','profiles','reports','contest_registrations','judge_quota_events']:
            self.assertEqual([r['id'] for r in self.db.rows(table)],['other'])
        self.assertTrue(self.db.rows('account_audit'))
        self.assertNotIn(EMAIL,str(self.db.rows('account_audit')))
        self.assertNotEqual(self.client.post('/api/auth/password',headers={'Origin':server.FRONTEND_URL},json={'email':EMAIL,'password':PASSWORD}).status_code,200)

    def test_legacy_account_resolves_auth_subject_on_server_before_deletion(self):
        self.login()
        subject = '00000000-0000-0000-0000-000000000002'
        with patch.object(server.email_auth, 'find_identity', return_value=subject) as lookup, \
                patch.object(server.email_auth, 'delete_identity') as provider:
            response = self.delete()
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual(lookup.call_args.args[-1], EMAIL)
        self.assertEqual(provider.call_args.args[-1], subject)

    def test_deleted_account_cannot_request_new_provider_identity(self):
        self.db.rows('account_deletion_blocks').append({'email': EMAIL})
        with patch.dict('os.environ', {'SUPABASE_AUTH_KEY': 'synthetic-publishable'}), \
                patch.object(server, '_sb_url', 'https://synthetic.supabase.co'), \
                patch.object(server.email_auth, 'request_code') as provider:
            response = self.client.post('/api/auth/email/request',
                headers={'Origin': server.FRONTEND_URL}, json={'email': EMAIL})
        self.assertEqual(response.status_code, 403, response.text)
        provider.assert_not_called()

    def test_provider_outage_does_not_claim_deletion_success(self):
        self.db.rows('users')[0]['email_auth_subject']='00000000-0000-0000-0000-000000000001'
        self.login()
        with patch.object(server.email_auth,'delete_identity',side_effect=server.email_auth.Unavailable()):
            r=self.delete()
        self.assertEqual(r.status_code,503)
        self.assertTrue(self.db.rows('users'))
        self.assertEqual(self.client.get('/api/profile').status_code,401)
        self.assertFalse(self.db.rows('account_audit'))

    def test_live_job_requires_waiting_without_revoking_account(self):
        self.login()
        self.db.rows('judge_jobs').append({'user_email':EMAIL,'status':'running'})
        self.assertEqual(self.delete().status_code,409)
        self.assertEqual(self.client.get('/api/profile').status_code,200)

    def test_must_confirm_exact_account_email(self):
        self.login()
        r=self.client.request('DELETE','/api/profile',headers={'Origin':server.FRONTEND_URL},json={'confirmation':'someoneelse'})
        self.assertEqual(r.status_code,400)
        self.assertTrue(self.db.rows('users'))

    def test_audit_is_admin_only_and_allowlisted(self):
        self.login()
        self.db.rows('account_audit').append({'id':'audit','event':'account_deleted',
            'counts':{'submissions':1},'email':'PRIVATE_EMAIL'})
        self.assertEqual(self.client.get('/api/admin/account-audit').status_code,403)
        with patch.object(server,'_is_admin',return_value=True):
            r=self.client.get('/api/admin/account-audit')
        self.assertEqual(r.status_code,200,r.text)
        self.assertNotIn('PRIVATE_EMAIL',r.text)
