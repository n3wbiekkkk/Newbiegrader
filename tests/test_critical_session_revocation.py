"""Copied-cookie revocation against the real HTTP stack and synthetic DB only."""
import base64
from contextlib import ExitStack
import json
import os
from pathlib import Path
import secrets
import time
import unittest
from unittest.mock import patch

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner, URLSafeTimedSerializer
from starlette.middleware.sessions import SessionMiddleware

from critical_helpers import test_server
from fake_supabase import FakeSupabase

server = test_server()
SECRET = 'synthetic-revocation-cookie-secret'
EMAIL = 'revocation-canary@example.invalid'
PASSWORD = 'synthetic-revocation-password'


class SessionRevocation(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack(); self.addCleanup(self.stack.close)
        self.db = FakeSupabase()
        self.stack.enter_context(patch.object(server, '_sb', self.db))
        self.stack.enter_context(patch.object(server, '_login_tries', {}))
        self.stack.enter_context(patch.object(server, '_account_tries', {}))
        self.stack.enter_context(patch.dict(os.environ, {'SESSION_SECURE': 'true'}))
        self.db.rows('users').append({'email': EMAIL, 'name': 'Synthetic',
            'password_hash': server._hash_password(PASSWORD), 'auth_version': 1,
            'email_verified_at': '2026-10-23T00:00:00Z'})
        self.app = FastAPI()
        self.app.middleware('http')(server._security_headers)
        self.app.middleware('http')(server._csrf_origin_check)
        self.app.add_middleware(server.VerifiedIdentityMiddleware)
        self.app.add_middleware(SessionMiddleware, secret_key=SECRET,
            session_cookie='ng_session', max_age=30 * 86400, same_site='lax', https_only=True)
        for path, fn in [('password', server.auth_password), ('logout', server.auth_logout)]:
            self.app.post('/api/auth/' + path)(fn)
        for path, fn in [('me', server.auth_me), ('restore', server.auth_restore), ('finish', server.auth_finish)]:
            self.app.get('/api/auth/' + path)(fn)
        self.app.get('/api/profile')(server.get_profile)
        self.client = self.new_client()

    def new_client(self, cookie=''):
        headers = {'Origin': server.FRONTEND_URL}
        if cookie: headers['Cookie'] = cookie
        client = self.stack.enter_context(TestClient(self.app, base_url='https://testserver',
            headers=headers, follow_redirects=False))
        return client

    def login(self, client=None, remember=False):
        client = client or self.client
        r = client.post('/api/auth/password', json={'email': EMAIL, 'password': PASSWORD,
                                                   'remember': remember})
        self.assertEqual(r.status_code, 200, r.text)
        return r

    def copied(self, *, session=True, remember=True):
        return '; '.join(f'{name}={self.client.cookies[name]}' for name, allowed in
            [('ng_session', session), ('ng_remember', remember)] if allowed and name in self.client.cookies)

    def decode(self, value=None):
        return json.loads(base64.b64decode(TimestampSigner(SECRET).unsign(
            value or self.client.cookies['ng_session'])))

    def cookie(self, payload):
        return TimestampSigner(SECRET).sign(base64.b64encode(json.dumps(payload).encode())).decode()

    def pending(self):
        binding = secrets.token_urlsafe(32)
        self.client.cookies.set(server._OAUTH_BINDING_COOKIE, binding, path='/api/auth/')
        request = Request({'type': 'http', 'session': {}, 'headers': []})
        sid = server._start_web_session(request, {'email': EMAIL, 'auth_version': 1,
            'provider': 'google', 'picture': ''}, True, pending=True)
        return sid, server._login_signer.dumps({'sid': sid, 'remember': True,
                                               'browser_hash': server._session_hash(binding)})

    def test_cookie_is_opaque_db_only_stores_hash_and_json_never_exposes_token(self):
        response = self.login(remember=True)
        payload = self.decode(); sid = payload['auth_session']
        self.assertNotIn('user', payload)
        self.assertNotIn(EMAIL, json.dumps(payload))
        self.assertEqual(self.db.rows('web_sessions')[0]['token_hash'], server._session_hash(sid))
        self.assertNotIn(sid, json.dumps(self.db.tables))
        self.assertNotIn(sid, response.text)
        self.assertNotIn(sid, self.client.get('/api/auth/me').text)
        self.assertEqual(set(server._remember_signer.loads(self.client.cookies['ng_remember'])), {'sid'})

    def test_logout_rejects_copied_session_and_remember(self):
        self.login(remember=True); copied = self.copied()
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        attacker = self.new_client(copied)
        self.assertEqual(attacker.get('/api/profile').status_code, 401)
        self.assertFalse(attacker.get('/api/auth/restore').json()['restored'])
        self.assertIsNone(attacker.get('/api/auth/me').json()['user'])

    def test_logout_with_only_remember_revokes_its_existing_session(self):
        self.login(remember=True); copied = self.copied()
        self.client.cookies.delete('ng_session')
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.assertEqual(self.new_client(copied).get('/api/profile').status_code, 401)

    def test_normal_logout_keeps_another_devices_session(self):
        self.login(remember=True)
        other = self.new_client(); self.login(other, remember=True)
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.assertEqual(other.get('/api/profile').status_code, 200)
        self.assertEqual(len([r for r in self.db.rows('web_sessions') if r['revoked_at'] is None]), 1)

    def test_logout_is_idempotent_even_with_a_copied_revoked_cookie(self):
        self.login(); copied = self.copied()
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.assertEqual(self.new_client(copied).post('/api/auth/logout').status_code, 200)

    def test_failed_logout_returns_failure_and_can_be_retried(self):
        self.login(remember=True); copied = self.copied()
        with patch.object(self.db, 'rpc', side_effect=RuntimeError('SYNTHETIC_DB_SECRET')):
            response = self.client.post('/api/auth/logout')
            self.assertEqual(response.status_code, 503)
            self.assertNotIn('SYNTHETIC_DB_SECRET', response.text)
            self.assertIn('ng_remember', self.client.cookies)
            self.assertEqual(self.client.get('/api/profile').status_code, 503)
        self.assertEqual(self.new_client(copied).get('/api/profile').status_code, 200)
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 200)
        self.assertEqual(self.new_client(copied).get('/api/profile').status_code, 401)

    def test_missing_session_schema_fails_closed_without_identity_only_fallback(self):
        self.login(); self.db.missing.add('web_sessions')
        self.assertEqual(self.client.get('/api/profile').status_code, 503)
        self.assertEqual(self.client.post('/api/auth/logout').status_code, 503)
        anonymous = self.new_client()
        self.assertIsNone(anonymous.get('/api/auth/me').json()['user'])

    def test_legacy_versioned_cookies_cannot_upgrade_to_new_sessions(self):
        user = {'email': EMAIL, 'auth_version': 1}
        legacy = URLSafeTimedSerializer(server._session_secret, salt='remember-me-v2').dumps({'user': user})
        client = self.new_client('ng_session=' + self.cookie({'user': user}) + '; ng_remember=' + legacy)
        self.assertEqual(client.get('/api/profile').status_code, 401)
        self.assertFalse(client.get('/api/auth/restore').json()['restored'])
        self.assertEqual(self.db.rows('web_sessions'), [])

    def test_signed_random_sid_cannot_authenticate_without_server_record(self):
        client = self.new_client('ng_session=' + self.cookie({'auth_session': secrets.token_urlsafe(32),
                                                           'user': {'email': EMAIL, 'auth_version': 1}}))
        self.assertEqual(client.get('/api/profile').status_code, 401)

    def test_data_restore_with_empty_session_table_cannot_resurrect_cookies(self):
        self.login(remember=True); copied = self.copied()
        self.db.tables['web_sessions'] = []
        client = self.new_client(copied)
        self.assertEqual(client.get('/api/profile').status_code, 401)
        self.assertFalse(client.get('/api/auth/restore').json()['restored'])

    def test_password_version_change_invalidates_every_device_and_remember(self):
        self.login(remember=True); copied = self.copied()
        other = self.new_client(); self.login(other, remember=True)
        self.db.rows('users')[0]['auth_version'] += 1
        for client in [self.new_client(copied), other]:
            self.assertEqual(client.get('/api/profile').status_code, 401)
            self.assertFalse(client.get('/api/auth/restore').json()['restored'])

    def test_remember_restore_keeps_the_same_revocable_family(self):
        self.login(remember=True); copied = self.copied()
        sid = self.decode()['auth_session']
        self.client.cookies.delete('ng_session')
        self.assertTrue(self.client.get('/api/auth/restore').json()['restored'])
        self.assertEqual(self.decode()['auth_session'], sid)
        self.client.post('/api/auth/logout')
        self.assertFalse(self.new_client(copied).get('/api/auth/restore').json()['restored'])

    def test_remember_expiry_does_not_end_a_still_valid_session_cookie(self):
        self.login(remember=True); remember = self.copied(session=False)
        self.db.rows('web_sessions')[0]['remember_until'] = time.time() - 1
        self.assertFalse(self.new_client(remember).get('/api/auth/restore').json()['restored'])
        self.assertEqual(self.client.get('/api/profile').status_code, 200)

    def test_cookie_thirty_day_age_is_still_enforced_with_longer_row_retention(self):
        self.login(); payload = self.decode()
        for days, expected in [(29, 200), (31, 401)]:
            with patch.object(TimestampSigner, 'get_timestamp', return_value=int(time.time()) - days * 86400):
                cookie = self.cookie(payload)
            self.assertEqual(self.new_client('ng_session=' + cookie).get('/api/profile').status_code, expected)

    def test_active_session_retention_renews_rarely_not_on_every_poll(self):
        self.login(); row = self.db.rows('web_sessions')[0]
        row['expires_at'] = time.time() + 44 * 86400
        self.assertEqual(self.client.get('/api/profile').status_code, 200)
        renewed = row['expires_at']; self.assertGreater(renewed, time.time() + 59 * 86400)
        for _ in range(5): self.assertEqual(self.client.get('/api/profile').status_code, 200)
        self.assertEqual(row['expires_at'], renewed)

    def test_google_handoff_is_pending_then_single_use_in_shared_database(self):
        sid, token = self.pending()
        before = self.new_client('ng_session=' + self.cookie({'auth_session': sid}))
        self.assertEqual(before.get('/api/profile').status_code, 401)
        first = self.client.get('/api/auth/finish', params={'token': token, 'next': '#/tasks'})
        self.assertNotIn('login=failed', first.headers['location'])
        replay = self.new_client().get('/api/auth/finish', params={'token': token})
        self.assertIn('login=failed', replay.headers['location'])
        self.assertEqual(self.client.get('/api/profile').status_code, 200)
        self.client.post('/api/auth/logout')
        self.assertIn('login=failed', self.new_client().get('/api/auth/finish',
                      params={'token': token}).headers['location'])

    def test_expired_handoff_and_credential_change_never_activate(self):
        for field in ['handoff_until', 'auth_version']:
            sid, token = self.pending()
            if field == 'handoff_until': self.db.rows('web_sessions')[-1][field] = time.time() - 1
            else: self.db.rows('users')[0][field] += 1
            response = self.client.get('/api/auth/finish', params={'token': token})
            self.assertIn('login=failed', response.headers['location'])
            self.assertFalse(self.db.rows('web_sessions')[-1]['activated'])

    def test_logout_csrf_rejection_does_not_revoke_a_live_session(self):
        self.login()
        self.assertEqual(self.client.post('/api/auth/logout', headers={'Origin': 'https://attacker.invalid'}).status_code, 403)
        self.assertEqual(self.client.get('/api/profile').status_code, 200)

    def test_migration_patch_matches_canonical_schema_and_has_no_public_table_access(self):
        root = Path(__file__).resolve().parents[1]
        self.assertIn((root / 'supabase/session_revocation.sql').read_text(),
                      (root / 'supabase/schema.sql').read_text())
        patch_sql = (root / 'supabase/session_revocation.sql').read_text()
        self.assertIn('alter table public.web_sessions enable row level security', patch_sql)
        self.assertNotIn('security definer', patch_sql)


if __name__ == '__main__': unittest.main()
