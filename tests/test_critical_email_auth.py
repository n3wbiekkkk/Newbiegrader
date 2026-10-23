"""Synthetic identity proofs only: no real SMTP, credentials, users or problems."""
import base64
import copy
import io
import json
import os
import threading
import time
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from fastapi import FastAPI
from fastapi.testclient import TestClient
from itsdangerous import TimestampSigner, URLSafeTimedSerializer
from starlette.middleware.sessions import SessionMiddleware

import email_auth
from critical_helpers import test_server
from fake_supabase import FakeSupabase

server = test_server()
EMAIL = "proof-canary@example.invalid"
PASSWORD = "synthetic-new-password"
OLD_PASSWORD = "synthetic-attacker-password"
SECRET = "synthetic-email-session-secret"
SUBJECT = str(uuid.uuid5(uuid.NAMESPACE_DNS, EMAIL))


def signed_cookie(session):
    return TimestampSigner(SECRET).sign(base64.b64encode(json.dumps(session).encode())).decode()


def verified_row(email=EMAIL, password=PASSWORD):
    return {"email": email, "name": "Synthetic", "password_hash": server._hash_password(password),
            "email_verified_at": "2026-10-18T00:00:00Z", "auth_version": 1}


class EmailAuth(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.db = FakeSupabase()
        self.stack.enter_context(patch.dict(os.environ, {
            "SUPABASE_AUTH_KEY": "synthetic-publishable-key", "SESSION_SECURE": "true"}))
        for key, value in {"_sb": self.db, "_sb_url": "https://synthetic.supabase.co",
                           "_login_tries": {}, "_account_tries": {}}.items():
            self.stack.enter_context(patch.object(server, key, value))
        self.codes = {}
        self.lock = threading.Lock()
        def request_code(url, key, email):
            self.codes[email] = "12345678"
        def verify_code(url, key, email, code):
            with self.lock:
                if self.codes.get(email) != code:
                    raise email_auth.InvalidCode()
                self.codes.pop(email)
            return str(uuid.uuid5(uuid.NAMESPACE_DNS, email))
        self.sender = self.stack.enter_context(patch.object(email_auth, "request_code", side_effect=request_code))
        self.verifier = self.stack.enter_context(patch.object(email_auth, "verify_code", side_effect=verify_code))
        self.app = FastAPI()
        self.app.middleware("http")(server._security_headers)
        self.app.middleware("http")(server._csrf_origin_check)
        self.app.add_middleware(server.VerifiedIdentityMiddleware)
        self.app.add_middleware(SessionMiddleware, secret_key=SECRET, session_cookie="ng_session",
                                same_site="lax", https_only=True)
        for path, handler in (("register", server.auth_register), ("email/request", server.auth_register),
                              ("email/verify", server.auth_email_verify), ("password", server.auth_password),
                              ("logout", server.auth_logout)):
            self.app.post("/api/auth/" + path)(handler)
        for path, handler in (("me", server.auth_me), ("restore", server.auth_restore),
                              ("finish", server.auth_finish)):
            self.app.get("/api/auth/" + path)(handler)
        self.app.get("/api/profile")(server.get_profile)
        self.app.post("/api/submit")(server.submit)
        self.client = self.stack.enter_context(TestClient(self.app, base_url="https://testserver",
            headers={"Origin": server.FRONTEND_URL}, follow_redirects=False))

    def start(self, email=EMAIL, **extra):
        return self.client.post("/api/auth/email/request", json={"email": email, **extra})

    def test_restore_hint_skips_absent_cookie_without_trusting_present_cookie(self):
        response = self.client.get('/api/auth/me')
        self.assertFalse(response.json()['restore_available'])
        self.assertEqual(response.headers['cache-control'], 'no-store')
        self.client.cookies.set('ng_remember', 'synthetic-invalid-cookie')
        data = self.client.get('/api/auth/me').json()
        self.assertTrue(data['restore_available'])
        self.assertIsNone(data['user'])
        self.assertFalse(data['is_admin'])
        self.assertFalse(self.client.get('/api/auth/restore').json()['restored'])

    def finish(self, **extra):
        return self.client.post("/api/auth/email/verify", json={
            "email": EMAIL, "code": "12345678", "password": PASSWORD, "name": "Owner", **extra})

    def test_signup_does_not_reserve_identity_or_issue_session_with_chosen_password(self):
        response = self.client.post("/api/auth/register", json={
            "email": EMAIL, "password": OLD_PASSWORD, "name": "Attacker", "remember": True})
        self.assertEqual(response.status_code, 202)
        self.assertEqual(self.db.rows("users"), [])
        self.assertIsNone(self.client.get("/api/auth/me").json()["user"])
        self.assertNotIn("ng_remember", self.client.cookies)
        raw = TimestampSigner(SECRET).unsign(self.client.cookies["ng_session"])
        pending = json.loads(base64.b64decode(raw))
        self.assertNotIn("password", json.dumps(pending))
        self.assertNotIn(OLD_PASSWORD, json.dumps(pending))
        self.assertEqual(self.client.post("/api/submit", data={
            "problem": "synthetic", "language": "python", "code": "print(0)"}).status_code, 401)

    def test_verified_owner_chooses_password_and_history_owner_never_changes(self):
        self.db.rows("submissions").append({"user_email": EMAIL, "id": "synthetic-history"})
        self.start(password=OLD_PASSWORD)
        response = self.finish(remember=True)
        self.assertEqual(response.status_code, 200, response.text)
        row = self.db.rows("users")[0]
        self.assertEqual(row["email_auth_subject"], SUBJECT)
        self.assertTrue(server._verify_password(PASSWORD, row["password_hash"]))
        self.assertFalse(server._verify_password(OLD_PASSWORD, row["password_hash"]))
        self.assertEqual(self.db.rows("submissions")[0]["user_email"], EMAIL)
        self.assertIn("ng_remember", self.client.cookies)
        self.assertNotIn("password_hash", response.text)
        self.assertNotIn("access_token", response.text)
        self.assertEqual(self.client.get("/api/profile").status_code, 200)

    def test_eight_digit_provider_code_matches_live_settings(self):
        self.start()
        self.codes[EMAIL] = "87654321"
        response = self.finish(code="87654321")
        self.assertEqual(response.status_code, 200, response.text)

    def test_legacy_password_never_authenticates_until_inbox_proof_and_new_password(self):
        self.db.rows("users").append({"email": EMAIL, "name": "Old",
                                     "password_hash": server._hash_password(OLD_PASSWORD)})
        denied = self.client.post("/api/auth/password", json={"email": EMAIL, "password": OLD_PASSWORD})
        self.assertEqual(denied.status_code, 403)
        self.assertIsNone(self.client.get("/api/auth/me").json()["user"])
        self.start()
        self.assertEqual(self.finish().status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.client.post("/api/auth/password", json={
            "email": EMAIL, "password": OLD_PASSWORD}).status_code, 401)
        self.assertEqual(self.client.post("/api/auth/password", json={
            "email": EMAIL, "password": PASSWORD}).status_code, 200)

    def test_reset_revokes_copied_session_remember_and_pending_handoff(self):
        self.db.rows("users").append(verified_row(password=OLD_PASSWORD))
        self.client.post("/api/auth/password", json={"email": EMAIL, "password": OLD_PASSWORD, "remember": True})
        old_session, old_remember = self.client.cookies["ng_session"], self.client.cookies["ng_remember"]
        handoff = server._login_signer.dumps({"user": {"email": EMAIL, "auth_version": 1}, "jti": "old-proof"})
        self.client.cookies.clear()
        self.start()
        self.assertEqual(self.finish().status_code, 200)
        self.assertEqual(self.db.rows("users")[0]["auth_version"], 2)
        self.client.cookies.clear()
        self.client.cookies.set("ng_session", old_session)
        self.assertEqual(self.client.get("/api/profile").status_code, 401)
        self.client.cookies.clear()
        self.client.cookies.set("ng_remember", old_remember)
        self.assertFalse(self.client.get("/api/auth/restore").json()["restored"])
        self.assertIn("login=failed", self.client.get("/api/auth/finish", params={"token": handoff}).headers["location"])

    def test_all_old_unversioned_cookies_fail_even_for_reserved_admin(self):
        self.client.cookies.set("ng_session", signed_cookie({"user": {"email": next(iter(server.ADMIN_EMAILS))}}))
        self.assertFalse(self.client.get("/api/auth/me").json()["is_admin"])
        self.assertEqual(self.client.get("/api/profile").status_code, 401)
        old = URLSafeTimedSerializer(server._session_secret, salt="remember-me").dumps({"email": EMAIL})
        self.client.cookies.clear()
        self.client.cookies.set("ng_remember", old)
        self.assertFalse(self.client.get("/api/auth/restore").json()["restored"])

    def test_bad_expired_replayed_and_wrong_email_codes_cannot_grant_identity(self):
        self.start()
        self.assertEqual(self.finish(code="00000000").status_code, 400)
        self.assertEqual(self.finish(email="another@example.invalid").status_code, 400)
        self.assertEqual(self.db.rows("users"), [])
        self.assertEqual(self.finish().status_code, 200)
        self.assertEqual(self.finish().status_code, 400)
        self.client.cookies.clear()
        self.client.cookies.set("ng_session", signed_cookie({"email_challenge": {
            "email": EMAIL, "issued_at": int(time.time()) - 601}}))
        self.assertEqual(self.finish().status_code, 400)

    def test_concurrent_use_of_same_provider_code_has_one_winner(self):
        self.start()
        cookie = self.client.cookies["ng_session"]
        def finish(_):
            with TestClient(self.app, base_url="https://testserver", headers={
                    "Origin": server.FRONTEND_URL, "Cookie": "ng_session=" + cookie}) as client:
                return client.post("/api/auth/email/verify", json={
                    "email": EMAIL, "code": "12345678", "password": PASSWORD}).status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            codes = list(pool.map(finish, range(4)))
        self.assertEqual(codes.count(200), 1, codes)
        self.assertEqual(len(self.db.rows("users")), 1)

    def test_existing_and_unknown_email_start_responses_are_identical(self):
        unknown = self.start().json()
        self.client.cookies.clear()
        self.db.rows("users").append(verified_row(email="existing@example.invalid"))
        existing = self.start(email="existing@example.invalid").json()
        self.assertEqual(existing, unknown)

    def test_central_request_and_guess_budget_survives_new_client_and_local_counter_reset(self):
        self.assertEqual(self.start().status_code, 202)
        self.client.cookies.clear()
        server._account_tries.clear()
        self.assertEqual(self.start().status_code, 429)
        self.assertEqual(self.sender.call_count, 1)
        self.client.cookies.set("ng_session", signed_cookie({"email_challenge": {
            "email": EMAIL, "issued_at": int(time.time())}}))
        for _ in range(8):
            self.assertEqual(self.finish(code="00000000").status_code, 400)
        denied = self.finish()
        self.assertEqual(denied.status_code, 429)
        self.assertIn("retry-after", denied.headers)
        self.assertEqual(self.db.rows("users"), [])

    def test_provider_outage_and_database_failure_never_issue_identity(self):
        self.sender.side_effect = email_auth.Unavailable("SYNTHETIC_SECRET")
        response = self.start()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("SYNTHETIC_SECRET", response.text)
        self.assertEqual(self.db.rows("users"), [])
        self.sender.side_effect = lambda *args: None
        self.client.cookies.set("ng_session", signed_cookie({"email_challenge": {
            "email": EMAIL, "issued_at": int(time.time())}}))
        self.codes[EMAIL] = "12345678"
        original = self.db.rpc
        def broken(name, params):
            if name == "auth_email_complete":
                raise RuntimeError("SYNTHETIC_DATABASE_SECRET")
            return original(name, params)
        with patch.object(self.db, "rpc", side_effect=broken):
            response = self.finish()
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("SYNTHETIC_DATABASE_SECRET", response.text)
        self.assertIsNone(self.client.get("/api/auth/me").json()["user"])
        self.assertEqual(self.finish().status_code, 400)

    def test_verified_session_db_outage_never_reports_successful_logout(self):
        self.db.rows("users").append(verified_row())
        self.client.post("/api/auth/password", json={"email": EMAIL, "password": PASSWORD})
        with patch.object(self.db, "table", side_effect=RuntimeError("synthetic outage")):
            self.assertEqual(self.client.get("/api/profile").status_code, 503)
            self.assertEqual(self.client.post("/api/auth/logout").status_code, 503)

    def test_real_application_middleware_rejects_legacy_and_revoked_sessions(self):
        self.db.rows("users").append(verified_row())
        # Do not enter the lifespan: this exercises the production HTTP stack
        # without starting workers, loading private problems, or judging jobs.
        client = TestClient(server.app, base_url="https://testserver",
                            headers={"Origin": server.FRONTEND_URL})
        self.addCleanup(client.close)
        login = client.post("/api/auth/password", json={"email": EMAIL, "password": PASSWORD,
                                                       "remember": True})
        self.assertEqual(login.status_code, 200)
        self.assertEqual(client.get("/api/profile").status_code, 200)
        self.db.rows("users")[0]["auth_version"] += 1
        self.assertEqual(client.get("/api/profile").status_code, 401)
        self.assertFalse(client.get("/api/auth/restore").json()["restored"])
        legacy = TimestampSigner(server._session_secret).sign(base64.b64encode(
            json.dumps({"user": {"email": EMAIL}}).encode())).decode()
        client.cookies.clear()
        client.cookies.set("ng_session", legacy)
        self.assertEqual(client.get("/api/profile").status_code, 401)

    def test_missing_provider_configuration_does_not_fall_back_to_legacy_signup(self):
        with patch.dict(os.environ, {"SUPABASE_AUTH_KEY": ""}):
            self.assertEqual(self.start().status_code, 503)
        self.assertEqual(self.db.rows("users"), [])

    def test_google_claim_clears_legacy_password_and_never_autolinks_verified_password(self):
        self.db.rows("users").append({"email": EMAIL, "name": "Attacker",
            "password_hash": server._hash_password(OLD_PASSWORD), "auth_version": 0})
        claimed = server._auth_rpc("auth_google_identity", {
            "p_email": EMAIL, "p_subject": "google-synthetic", "p_name": "Owner"})
        self.assertEqual(claimed["auth_version"], 1)
        self.assertEqual(self.db.rows("users")[0]["password_hash"], "")
        self.assertEqual(self.client.post("/api/auth/password", json={
            "email": EMAIL, "password": OLD_PASSWORD}).status_code, 401)
        self.assertTrue(server._auth_rpc("auth_google_identity", {
            "p_email": EMAIL, "p_subject": "different-google-sub", "p_name": "Other"})["link_required"])
        self.db.rows("users").clear()
        self.db.rows("users").append(verified_row())
        before = copy.deepcopy(self.db.rows("users"))
        self.assertTrue(server._auth_rpc("auth_google_identity", {
            "p_email": EMAIL, "p_subject": "google-synthetic", "p_name": "Other"})["link_required"])
        self.assertEqual(self.db.rows("users"), before)

    def test_missing_identity_migration_never_uses_password_only_fallback(self):
        self.db.rows("users").append(verified_row())
        self.assertEqual(self.client.post("/api/auth/password", json={
            "email": EMAIL, "password": PASSWORD}).status_code, 200)
        with patch.object(self.db, "table", side_effect=RuntimeError("missing identity columns")):
            self.assertEqual(self.client.get("/api/profile").status_code, 503)

    def test_expired_and_forged_subjects_cannot_replace_an_existing_identity(self):
        row = verified_row()
        row["email_auth_subject"] = str(uuid.uuid4())
        self.db.rows("users").append(row)
        before = copy.deepcopy(row)
        self.start()
        self.assertEqual(self.finish().status_code, 503)
        self.assertEqual(row, before)

    def test_unverified_google_third_party_email_does_not_claim_legacy_history(self):
        self.app.get("/api/auth/callback")(server.auth_callback)
        self.client.cookies.set("ng_session", signed_cookie({"oauth_state": "synthetic-state"}))
        with patch.object(server, "_google_userinfo", return_value={
                "email": EMAIL, "sub": "synthetic-sub", "email_verified": True}):
            response = self.client.get("/api/auth/callback", params={
                "code": "synthetic-code", "state": "synthetic-state"})
        self.assertIn("email_proof=required", response.headers["location"])
        self.assertEqual(self.db.rows("users"), [])

    def test_normalization_input_bounds_and_csrf_apply_to_new_endpoints(self):
        self.assertEqual(self.start(email="  PROOF-canary@example.invalid  ").status_code, 202)
        self.assertEqual(self.sender.call_args.args[-1], EMAIL)
        for bad in (None, {}, "x" * 255 + "@x.test", "é@example.invalid", "x@y.invalid\nx"):
            with self.subTest(bad=bad):
                self.assertEqual(self.start(email=bad).status_code, 400)
        for path in ("request", "verify"):
            self.assertEqual(self.client.post("/api/auth/email/" + path,
                json={"email": EMAIL}, headers={"Origin": "https://attacker.invalid"}).status_code, 403)
        self.assertEqual(self.client.post("/api/auth/email/verify", json={"email": EMAIL},
            headers={"Origin": ""}).status_code, 403)
        self.client.headers.pop("Origin")
        self.assertEqual(self.client.post("/api/auth/email/verify", json={"email": EMAIL}).status_code, 403)


class ProviderTransport(unittest.TestCase):
    def post_response(self, payload):
        opener = Mock()
        opener.open.return_value = io.BytesIO(json.dumps(payload).encode())
        return patch.object(email_auth, "build_opener", return_value=opener), opener

    def test_verification_uses_server_response_email_confirmation_and_subject_only(self):
        payload = {"user": {"id": SUBJECT, "email": EMAIL, "email_confirmed_at": "2026-10-18T00:00:00Z"},
                   "access_token": "synthetic-bearer", "refresh_token": "synthetic-refresh"}
        context, opener = self.post_response(payload)
        with context:
            subject = email_auth.verify_code("https://synthetic.supabase.co", "synthetic-public", EMAIL, "12345678")
        self.assertEqual(subject, SUBJECT)
        request = opener.open.call_args.args[0]
        self.assertEqual(request.full_url, "https://synthetic.supabase.co/auth/v1/verify")
        self.assertEqual(json.loads(request.data), {"email": EMAIL, "token": "12345678", "type": "email"})
        self.assertEqual(opener.open.call_args.kwargs["timeout"], 15)

    def test_wrong_unverified_missing_or_malformed_provider_identity_fails_closed(self):
        for user in ({}, {"id": SUBJECT, "email": EMAIL},
                     {"id": SUBJECT, "email": "wrong@example.invalid", "email_confirmed_at": "yes"},
                     {"id": "not-uuid", "email": EMAIL, "email_confirmed_at": "yes"}):
            with self.subTest(user=user):
                context, _ = self.post_response({"user": user})
                with context, self.assertRaises(email_auth.InvalidCode):
                    email_auth.verify_code("https://synthetic.supabase.co", "synthetic-public", EMAIL, "12345678")

    def test_provider_error_bodies_are_never_read_or_propagated(self):
        for status, expected in ((400, email_auth.InvalidCode), (429, email_auth.Unavailable),
                                 (500, email_auth.Unavailable), (302, email_auth.Unavailable)):
            body = Mock()
            opener = Mock()
            opener.open.side_effect = HTTPError("https://synthetic.invalid", status,
                "synthetic error", {}, body)
            with patch.object(email_auth, "build_opener", return_value=opener):
                with self.assertRaises(expected):
                    email_auth.verify_code("https://synthetic.supabase.co", "synthetic-public", EMAIL, "12345678")
            body.read.assert_not_called()
            body.close.assert_called_once()

    def test_redirects_insecure_urls_and_oversized_provider_responses_are_refused(self):
        self.assertIsNone(email_auth._NoRedirect().redirect_request(None, None, 302, "", {}, "https://attacker.invalid"))
        for url in ("http://synthetic.invalid", "https://user:pass@synthetic.invalid", "https://synthetic.invalid/?x=1"):
            with self.assertRaises(email_auth.Unavailable):
                email_auth.request_code(url, "synthetic-public", EMAIL)
        opener = Mock()
        opener.open.return_value = io.BytesIO(b"x" * 131073)
        with patch.object(email_auth, "build_opener", return_value=opener), self.assertRaises(email_auth.Unavailable):
            email_auth.request_code("https://synthetic.supabase.co", "synthetic-public", EMAIL)


if __name__ == "__main__":
    unittest.main()
