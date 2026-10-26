"""Authentication-cookie regressions using synthetic identities and in-memory DB."""
from contextlib import ExitStack
from http.cookies import SimpleCookie
import os
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from critical_helpers import test_server
from fake_supabase import FakeSupabase

server = test_server()
EMAIL = "cookie-canary@example.invalid"
PASSWORD = "synthetic-cookie-password"


class AuthCookies(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch.dict(os.environ, {"SESSION_SECURE": "true"}))
        for key, value in {"_sb": FakeSupabase(), "_login_tries": {}, "_account_tries": {},
                           "GOOGLE_CLIENT_ID": "synthetic-client"}.items():
            self.stack.enter_context(patch.object(server, key, value))
        app = FastAPI()
        app.middleware("http")(server._security_headers)
        app.add_middleware(server.VerifiedIdentityMiddleware)
        app.add_middleware(SessionMiddleware, secret_key="synthetic-cookie-session-secret",
                           session_cookie="ng_session", max_age=30 * 86400,
                           same_site="lax", https_only=True)
        app.post("/api/auth/register")(server.auth_register)
        app.post("/api/auth/password")(server.auth_password)
        app.post("/api/auth/logout")(server.auth_logout)
        app.get("/api/auth/me")(server.auth_me)
        app.get("/api/auth/restore")(server.auth_restore)
        app.get("/api/auth/login")(server.auth_login)
        app.get("/api/auth/callback")(server.auth_callback)
        app.get("/api/auth/finish")(server.auth_finish)
        self.app = app
        self.client = self.stack.enter_context(TestClient(app, base_url="https://testserver", follow_redirects=False))
        server._sb.table("users").insert({"email": EMAIL, "name": "Synthetic",
            "password_hash": server._hash_password(PASSWORD),
            "email_verified_at": "2026-10-18T00:00:00Z", "auth_version": 1,
            "google_subject": "synthetic-google-sub"}).execute()

    def login(self, **kwargs):
        return self.client.post("/api/auth/password", json={"email": EMAIL, "password": PASSWORD, **kwargs})

    def test_long_lived_cookie_is_opt_in_and_cannot_be_enabled_by_a_string(self):
        for value in ({}, {"remember": False}, {"remember": "false"}):
            with self.subTest(value=value):
                self.assertEqual(self.login(**value).status_code, 200)
                self.assertNotIn("ng_remember", self.client.cookies)
        self.assertEqual(self.login(remember=True).status_code, 200)
        self.assertIn("ng_remember", self.client.cookies)

    def test_opt_out_clears_previous_remember_cookie(self):
        self.login(remember=True)
        self.assertIn("ng_remember", self.client.cookies)
        self.login(remember=False)
        self.assertNotIn("ng_remember", self.client.cookies)
        self.client.cookies.delete("ng_session")
        self.assertFalse(self.client.get("/api/auth/restore").json()["restored"])

    def test_account_switch_opt_out_clears_another_accounts_remember_cookie(self):
        self.login(remember=True)
        server._sb.table("users").insert({"email": "other-cookie@example.invalid", "name": "Other",
            "password_hash": server._hash_password(PASSWORD),
            "email_verified_at": "2026-10-18T00:00:00Z", "auth_version": 1}).execute()
        response = self.client.post("/api/auth/password", json={
            "email": "other-cookie@example.invalid", "password": PASSWORD, "remember": False})
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("ng_remember", self.client.cookies)

    def test_auth_cookie_flags_and_private_responses(self):
        response = self.login(remember=True)
        cookies = SimpleCookie()
        for header in response.headers.get_list("set-cookie"):
            cookies.load(header)
        for name in ("ng_session", "ng_remember"):
            cookie = cookies[name]
            self.assertTrue(cookie["secure"])
            self.assertTrue(cookie["httponly"])
            self.assertEqual(cookie["samesite"], "lax")
            self.assertEqual(cookie["path"], "/")
            self.assertEqual(cookie["domain"], "")
        self.assertEqual(int(cookies["ng_remember"]["max-age"]), server.REMEMBER_MAX_AGE)
        for path in ("/api/auth/me", "/api/auth/restore"):
            self.assertEqual(self.client.get(path).headers["cache-control"], "no-store")
        self.assertEqual(response.headers["cache-control"], "no-store")

    def test_restore_and_logout_remove_both_browser_cookies(self):
        self.login(remember=True)
        self.client.cookies.delete("ng_session")
        self.assertTrue(self.client.get("/api/auth/restore").json()["restored"])
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["email"], EMAIL)
        response = self.client.post("/api/auth/logout")
        self.assertEqual(response.status_code, 200)
        self.assertNotIn("ng_session", self.client.cookies)
        self.assertNotIn("ng_remember", self.client.cookies)
        self.assertIsNone(self.client.get("/api/auth/me").json()["user"])
        self.assertFalse(self.client.get("/api/auth/restore").json()["restored"])

    def test_tampered_remember_cookie_cannot_restore_identity(self):
        self.client.cookies.clear()
        self.client.cookies.set("ng_remember", "synthetic-invalid-token")
        self.assertFalse(self.client.get("/api/auth/restore").json()["restored"])
        self.assertIsNone(self.client.get("/api/auth/me").json()["user"])

    def test_google_remember_choice_survives_signed_handoff(self):
        for remember in (False, True):
            with self.subTest(remember=remember):
                self.client.cookies.clear()
                response = self.client.get("/api/auth/login", params={"next": "#/tasks", "remember": str(remember).lower()})
                oauth_state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
                with patch.object(server, "_google_userinfo", return_value={"email": EMAIL, "name": "Synthetic", "sub": "synthetic-google-sub", "hd": "example.invalid"}):
                    response = self.client.get("/api/auth/callback", params={"code": "synthetic-code", "state": oauth_state})
                args = parse_qs(urlsplit(response.headers["location"]).query)
                response = self.client.get("/api/auth/finish", params={k: v[0] for k, v in args.items()})
                self.assertEqual(response.status_code, 307)
                self.assertEqual("ng_remember" in self.client.cookies, remember)
                self.assertEqual(response.headers["cache-control"], "no-store")
                replay = self.client.get("/api/auth/finish", params={k: v[0] for k, v in args.items()})
                self.assertIn("login=failed", replay.headers["location"])

    def test_handoff_cannot_switch_another_browser_or_revoke_its_family(self):
        victim_email = "other-browser@example.invalid"
        server._sb.table("users").insert({"email": victim_email, "name": "Victim",
            "password_hash": server._hash_password(PASSWORD), "auth_version": 1,
            "email_verified_at": "2026-10-18T00:00:00Z"}).execute()
        victim = self.stack.enter_context(TestClient(self.app, base_url="https://testserver",
                                                     follow_redirects=False))
        self.assertEqual(victim.post("/api/auth/password", json={
            "email": victim_email, "password": PASSWORD}).status_code, 200)
        response = self.client.get("/api/auth/login")
        state = parse_qs(urlsplit(response.headers["location"]).query)["state"][0]
        with patch.object(server, "_google_userinfo", return_value={"email": EMAIL,
                "sub": "synthetic-google-sub", "hd": "example.invalid"}):
            response = self.client.get("/api/auth/callback", params={"code": "synthetic", "state": state})
        args = {k: v[0] for k, v in parse_qs(urlsplit(response.headers["location"]).query).items()}
        refused = victim.get("/api/auth/finish", params=args)
        self.assertIn("login=failed", refused.headers["location"])
        self.assertEqual(victim.get("/api/auth/me").json()["user"]["email"], victim_email)
        # A failed cross-browser attempt must not consume the rightful handoff.
        accepted = self.client.get("/api/auth/finish", params=args)
        self.assertNotIn("login=failed", accepted.headers["location"])
        self.assertEqual(self.client.get("/api/auth/me").json()["user"]["email"], EMAIL)

    def test_missing_wrong_and_legacy_browser_bindings_fail_before_activation(self):
        from fastapi import Request
        binding = 'n' * 43
        correct_hash = server._session_hash(binding)
        for supplied, recorded in [('', correct_hash), ('x' * 43, correct_hash),
                                   (binding, None), (binding, []), (binding, 'ก' * 64)]:
            with self.subTest(supplied=supplied, recorded=recorded):
                data = {"sid": 's' * 43, "remember": True}
                if recorded is not None:
                    data['browser_hash'] = recorded
                token = server._login_signer.dumps(data)
                request = Request({"type": "http", "session": {}, "headers": [
                    (b'cookie', (server._OAUTH_BINDING_COOKIE + '=' + supplied).encode())]})
                with patch.object(server, '_session_identity') as identity:
                    response = server.auth_finish(request, token)
                self.assertIn('login=failed', response.headers['location'])
                identity.assert_not_called()

    def test_oauth_binding_cookie_is_private_and_only_its_hash_enters_handoff(self):
        response = self.client.get('/api/auth/login')
        cookies = SimpleCookie()
        for header in response.headers.get_list('set-cookie'):
            cookies.load(header)
        binding = cookies[server._OAUTH_BINDING_COOKIE]
        self.assertTrue(binding['secure'])
        self.assertTrue(binding['httponly'])
        self.assertEqual(binding['samesite'], 'lax')
        self.assertEqual(binding['path'], '/api/auth/')
        self.assertEqual(binding['domain'], '')
        self.assertEqual(int(binding['max-age']), 600)
        state = parse_qs(urlsplit(response.headers['location']).query)['state'][0]
        with patch.object(server, '_google_userinfo', return_value={'email': EMAIL,
                'sub': 'synthetic-google-sub', 'hd': 'example.invalid'}):
            response = self.client.get('/api/auth/callback', params={'code': 'synthetic', 'state': state})
        args = {k: v[0] for k, v in parse_qs(urlsplit(response.headers['location']).query).items()}
        data = server._login_signer.loads(args['token'])
        self.assertEqual(data['browser_hash'], server._session_hash(binding.value))
        self.assertNotIn(binding.value, str(data))
        self.client.get('/api/auth/finish', params=args)
        self.assertNotIn(server._OAUTH_BINDING_COOKIE, self.client.cookies)


if __name__ == "__main__":
    unittest.main()
