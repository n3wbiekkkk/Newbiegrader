"""Realtime admin management: DB-backed admins + immutable env bootstrap.

Runs the real FastAPI app against tests/fake_supabase.py only.
"""
from __future__ import annotations

import os
import sys
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

os.environ["SESSION_SECRET"] = "test-secret-not-for-production"
os.environ["SESSION_SECURE"] = "false"
os.environ["SESSION_SAMESITE"] = "lax"
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_KEY"] = ""
os.environ["GRADER_JUDGE_WORKERS"] = "2"
os.environ["GRADER_PROBLEM_SOURCE"] = "local"

from fastapi.testclient import TestClient  # noqa: E402

from fake_supabase import FakeSupabase  # noqa: E402

import grader  # noqa: E402
import server  # noqa: E402

if not grader.PROBLEMS_DIR.is_dir():
    raise unittest.SkipTest(
        "no local problems/ (problem data lives in Supabase); "
        "run from a checkout that has problems/ for API coverage")

ADMIN = "admin@example.com"
NEW_ADMIN = "newadmin@example.com"
STUDENT = "student.adminmgmt@example.com"
PASSWORD = "testpass123"


def _browser_origin() -> str:
    from urllib.parse import urlsplit
    parts = urlsplit(server.FRONTEND_URL)
    return f"{parts.scheme}://{parts.hostname}"


BROWSER = {"Origin": _browser_origin()}


class AdminManagement(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(server.app)
        cls.client = cls._ctx.__enter__()
        cls.fake = FakeSupabase()
        cls._auth_stack = ExitStack()
        cls._auth_stack.enter_context(
            patch.dict(os.environ, {"SUPABASE_AUTH_KEY": "synthetic-public"}))
        cls._auth_stack.enter_context(
            patch.object(server, "_sb_url", "https://synthetic.supabase.co"))
        cls._auth_stack.enter_context(patch.object(server.email_auth, "request_code"))
        server._sb = cls.fake

    @classmethod
    def tearDownClass(cls):
        server._sb = None
        server._db_admin_emails = frozenset()
        cls._ctx.__exit__(None, None, None)
        cls._auth_stack.close()

    def setUp(self):
        self.client.cookies.clear()
        server._login_tries.clear()
        server._account_tries.clear()
        server._quota_hits.clear()
        server._db_admin_emails = frozenset()
        self.fake.tables.clear()

    def login(self, email: str, name: str = "Tester") -> None:
        self.client.cookies.clear()
        if not any(u.get("email") == email for u in self.fake.rows("users")):
            self.fake.table("users").insert({
                "email": email, "name": name,
                "password_hash": server._hash_password(PASSWORD),
                "email_verified_at": "2026-10-18T00:00:00+00:00",
                "auth_version": 1}).execute()
        r = self.client.post("/api/auth/password",
                             json={"email": email, "password": PASSWORD},
                             headers=BROWSER)
        self.assertEqual(r.status_code, 200, r.text)

    def me(self) -> dict:
        r = self.client.get("/api/auth/me")
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()

    def test_env_admin_is_bootstrap_and_cannot_be_removed(self):
        self.login(ADMIN, "Admin")
        body = self.client.get("/api/admin/admins").json()
        self.assertTrue(body["configured"])
        env = [a for a in body["admins"] if a["source"] == "env"]
        self.assertEqual([a["email"] for a in env], [ADMIN])
        self.assertFalse(env[0]["removable"])

        r = self.client.delete(f"/api/admin/admins/{ADMIN}", headers=BROWSER)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertTrue(server._is_admin(ADMIN))

    def test_add_is_effective_immediately_for_existing_session(self):
        self.login(NEW_ADMIN, "New Admin")   # session exists before promotion
        self.assertFalse(self.me()["is_admin"])
        pending_session = self.client.cookies.get("ng_session")
        self.assertTrue(pending_session)

        self.login(ADMIN, "Admin")
        r = self.client.post("/api/admin/admins",
                             json={"email": NEW_ADMIN.upper()}, headers=BROWSER)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["email"], NEW_ADMIN)
        self.assertTrue(server._is_admin(NEW_ADMIN))

        # Restore the pre-promotion cookie: no re-login, no restart.
        self.client.cookies.clear()
        self.client.cookies.set("ng_session", pending_session)
        self.assertTrue(self.me()["is_admin"])
        self.assertEqual(
            self.client.get("/api/admin/admins").status_code, 200)

    def test_remove_takes_effect_immediately(self):
        self.login(ADMIN, "Admin")
        self.client.post("/api/admin/admins",
                         json={"email": NEW_ADMIN}, headers=BROWSER)
        self.assertTrue(server._is_admin(NEW_ADMIN))
        r = self.client.delete(f"/api/admin/admins/{NEW_ADMIN}", headers=BROWSER)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertFalse(server._is_admin(NEW_ADMIN))
        self.login(NEW_ADMIN, "New Admin")
        self.assertFalse(self.me()["is_admin"])

    def test_non_admins_and_anonymous_are_denied(self):
        self.assertIn(self.client.get("/api/admin/admins").status_code, (401, 403))
        self.assertIn(self.client.post("/api/admin/admins", json={"email": NEW_ADMIN},
                                       headers=BROWSER).status_code, (401, 403))
        self.login(STUDENT, "Student")
        self.assertEqual(self.client.get("/api/admin/admins").status_code, 403)
        r = self.client.post("/api/admin/admins",
                             json={"email": NEW_ADMIN}, headers=BROWSER)
        self.assertEqual(r.status_code, 403)
        self.assertFalse(server._is_admin(NEW_ADMIN))

    def test_invalid_email_duplicate_and_env_conflicts(self):
        self.login(ADMIN, "Admin")
        for bad in ("", "no-at-sign", "a b@example.com", "x@localhost"):
            r = self.client.post("/api/admin/admins",
                                 json={"email": bad}, headers=BROWSER)
            self.assertEqual(r.status_code, 400, (bad, r.text))
        r = self.client.post("/api/admin/admins",
                             json={"email": ADMIN}, headers=BROWSER)
        self.assertEqual(r.status_code, 409, r.text)
        self.assertEqual(self.client.post(
            "/api/admin/admins", json={"email": NEW_ADMIN}, headers=BROWSER
        ).status_code, 200)
        r = self.client.post("/api/admin/admins",
                             json={"email": NEW_ADMIN}, headers=BROWSER)
        self.assertEqual(r.status_code, 409, r.text)

    def test_admin_cannot_remove_themselves(self):
        self.login(ADMIN, "Admin")
        self.client.post("/api/admin/admins",
                         json={"email": NEW_ADMIN}, headers=BROWSER)
        self.login(NEW_ADMIN, "New Admin")
        r = self.client.delete(f"/api/admin/admins/{NEW_ADMIN}", headers=BROWSER)
        self.assertEqual(r.status_code, 400, r.text)
        self.assertTrue(server._is_admin(NEW_ADMIN))

    def test_missing_table_falls_back_to_env_only(self):
        unavailable = FakeSupabase(missing={"admins"})
        with patch.object(server, "_sb", unavailable):
            server._db_admin_emails = frozenset({"stale@example.com"})
            self.assertFalse(server._load_db_admins_sync())
            self.assertTrue(server._is_admin(ADMIN))
            self.assertFalse(server._is_admin("stale@example.com"))

    def test_background_refresh_picks_up_external_rows(self):
        self.fake.table("admins").insert(
            {"email": NEW_ADMIN, "created_by": "sql"}).execute()
        server._db_admin_emails = frozenset()
        self.assertTrue(server._load_db_admins_sync())
        self.assertTrue(server._is_admin(NEW_ADMIN))

    def _seed_submissions(self, count: int = 5, problem: str = "hanoi") -> None:
        for i in range(count):
            self.fake.table("submissions").insert({
                "created_at": f"2026-10-20T00:00:{i:02d}+00:00",
                "problem": problem,
                "language": "python",
                "name": f"User {i}",
                "user_email": f"user{i}@example.com",
                "verdict": "AC" if i % 2 else "WA",
                "accepted": bool(i % 2),
                "passed": i, "total": count, "score": i * 10,
                "counts": {"AC": i} if i % 2 else {"WA": 1},
            }).execute()

    def test_admin_submissions_paginates_with_exact_total(self):
        self.login(ADMIN, "Admin")
        self._seed_submissions(5)
        body = self.client.get(
            "/api/admin/submissions?page=1&per_page=20").json()
        self.assertEqual(body["total"], 5)
        self.assertEqual(body["pages"], 1)
        self.assertEqual(body["per_page"], 20)
        self.assertEqual([r["name"] for r in body["submissions"]],
                         ["User 4", "User 3", "User 2", "User 1", "User 0"])
        self.assertTrue(all("user_email" in r for r in body["submissions"]))
        self.assertNotIn("code", body["submissions"][0])
        self.assertNotIn("results", body["submissions"][0])

        page2 = self.client.get(
            "/api/admin/submissions?page=2&per_page=20").json()
        self.assertEqual(page2["submissions"], [])

    def test_admin_submissions_page_sizes_and_filters(self):
        self.login(ADMIN, "Admin")
        self._seed_submissions(5, "hanoi")
        self._seed_submissions(3, "other")
        two = self.client.get(
            "/api/admin/submissions?page=1&per_page=50").json()
        self.assertEqual((two["total"], len(two["submissions"])), (8, 8))
        self.assertEqual(two["per_page"], 50)
        # Only the three advertised sizes are accepted; anything else falls back.
        odd = self.client.get(
            "/api/admin/submissions?page=1&per_page=17").json()
        self.assertEqual(odd["per_page"], 20)
        filtered = self.client.get(
            "/api/admin/submissions?page=1&per_page=20&problem=hanoi").json()
        self.assertEqual(filtered["total"], 5)
        self.assertTrue(all(r["problem"] == "hanoi"
                            for r in filtered["submissions"]))
        unknown = self.client.get(
            "/api/admin/submissions?problem=no-such-problem").json()
        self.assertEqual(unknown["total"], 0)

    def test_admin_submissions_requires_admin(self):
        self._seed_submissions(2)
        self.assertIn(self.client.get("/api/admin/submissions").status_code,
                      (401, 403))
        self.login(STUDENT, "Student")
        self.assertEqual(
            self.client.get("/api/admin/submissions").status_code, 403)


if __name__ == "__main__":
    unittest.main()
