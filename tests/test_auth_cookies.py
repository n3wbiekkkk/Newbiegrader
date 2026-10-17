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
                           "_used_login_jti": {}, "GOOGLE_CLIENT_ID": "synthetic-client"}.items():
            self.stack.enter_context(patch.object(server, key, value))
        app = FastAPI()
        app.middleware("http")(server._security_headers)
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
        self.client = self.stack.enter_context(TestClient(app, base_url="https://testserver", follow_redirects=False))
        self.client.post("/api/auth/register", json={"email": EMAIL, "password": PASSWORD})

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

    def test_register_opt_out_clears_another_accounts_remember_cookie(self):
        self.login(remember=True)
        response = self.client.post("/api/auth/register", json={
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
                with patch.object(server, "_google_userinfo", return_value={"email": EMAIL, "name": "Synthetic"}):
                    response = self.client.get("/api/auth/callback", params={"code": "synthetic-code", "state": oauth_state})
                args = parse_qs(urlsplit(response.headers["location"]).query)
                response = self.client.get("/api/auth/finish", params={k: v[0] for k, v in args.items()})
                self.assertEqual(response.status_code, 307)
                self.assertEqual("ng_remember" in self.client.cookies, remember)
                self.assertEqual(response.headers["cache-control"], "no-store")
                replay = self.client.get("/api/auth/finish", params={k: v[0] for k, v in args.items()})
                self.assertIn("login=failed", replay.headers["location"])


if __name__ == "__main__":
    unittest.main()
