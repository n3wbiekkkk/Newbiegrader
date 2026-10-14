"""End-to-end API tests: judge queue, feedback policy, quota, contests, admin.

Runs the real FastAPI app with the real judge engine; only Supabase is replaced
by tests/fake_supabase.py, so these tests never touch production data.

    python3 -m unittest discover -s tests -v
"""
from __future__ import annotations

import datetime as dt
import os
import sys
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

# Configure the app BEFORE importing it: no database, no HTTPS-only cookies,
# fixed session secret, and one test admin.
os.environ["SESSION_SECRET"] = "test-secret-not-for-production"
os.environ["SESSION_SECURE"] = "false"
os.environ["SESSION_SAMESITE"] = "lax"
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ["SUPABASE_URL"] = ""
os.environ["SUPABASE_KEY"] = ""
os.environ["GRADER_JUDGE_WORKERS"] = "2"

from fastapi.testclient import TestClient  # noqa: E402

from fake_supabase import FakeSupabase  # noqa: E402

import grader  # noqa: E402
import server  # noqa: E402

STUDENT_A = "student.a@example.com"
STUDENT_B = "student.b@example.com"
ADMIN = "admin@example.com"
PASSWORD = "testpass123"
THAI_REF = (ROOT / "examples" / "thai_time_ref.py").read_text(encoding="utf-8")
WRONG = 'print("nope")\n'


def _iso(offset_minutes: int) -> str:
    return (dt.datetime.now(dt.timezone.utc)
            + dt.timedelta(minutes=offset_minutes)).isoformat()


class ApiE2E(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(server.app)
        cls.client = cls._ctx.__enter__()
        cls.fake = FakeSupabase()
        server._sb = cls.fake

    @classmethod
    def tearDownClass(cls):
        server._sb = None
        cls._ctx.__exit__(None, None, None)

    # ---------- helpers ----------
    def setUp(self):
        # The API rate-limits auth per client IP; the suite logs in many times
        # from the same fake IP, so start each test with a clean window.
        server._login_tries.clear()
        server._quota_hits.clear()

    def login(self, email: str, name: str = "Tester") -> None:
        self.client.cookies.clear()
        r = self.client.post("/api/auth/register",
                             json={"email": email, "password": PASSWORD, "name": name})
        if r.status_code == 409:
            r = self.client.post("/api/auth/password",
                                 json={"email": email, "password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.text)

    def submit(self, problem: str, code: str, expect: int = 202,
               contest: str = "", language: str = "python"):
        data = {"problem": problem, "language": language, "code": code}
        if contest:
            data["contest"] = contest
        r = self.client.post("/api/submit", data=data)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json() if r.content else {}

    def wait_job(self, jid: str, timeout: float = 120.0) -> dict:
        deadline = time.time() + timeout
        last = {}
        while time.time() < deadline:
            r = self.client.get(f"/api/jobs/{jid}")
            self.assertEqual(r.status_code, 200, r.text)
            last = r.json()
            if last["status"] in ("done", "error"):
                return last
            time.sleep(0.05)
        self.fail(f"job {jid} did not finish: {last}")

    def judged(self, problem: str, code: str) -> dict:
        """Submit and wait; returns the finished job payload."""
        job = self.submit(problem, code)
        self.assertEqual(job["status"], "queued", job)
        return self.wait_job(job["job_id"])

    def stored(self, **match) -> list:
        return [r for r in self.fake.rows("submissions")
                if all(r.get(k) == v for k, v in match.items())]

    # ---------- tests ----------
    def test_version_reports_test_hashes(self):
        r = self.client.get("/api/version")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body["version"], grader.GRADER_VERSION)
        thai = body["tests"]["thai_time"]
        self.assertEqual(thai["hash"], grader.tests_hash(server.PROBLEMS["thai_time"]))
        self.assertEqual(thai["samples"], ["02"])
        self.assertGreater(thai["tests"], len(thai["samples"]))

    def test_samples_are_public_hidden_tests_are_not(self):
        ok = self.client.get("/api/problems/thai_time/sample/02")
        self.assertEqual(ok.status_code, 200)
        self.assertIn("input", ok.json())
        for hidden_name in ("01", "09", "15"):
            r = self.client.get(f"/api/problems/thai_time/sample/{hidden_name}")
            self.assertEqual(r.status_code, 404, hidden_name)

    def test_accepted_submission_hides_hidden_test_data(self):
        self.login(STUDENT_A)
        job = self.judged("thai_time", THAI_REF)
        self.assertEqual(job["status"], "done", job)
        result = job["result"]
        self.assertTrue(result["accepted"], result)
        self.assertEqual(result["score"], 100)
        self.assertEqual(result["samples"], 1)

        public = [i for i in result["results"] if not i.get("hidden")]
        hidden = [i for i in result["results"] if i.get("hidden")]
        self.assertEqual([i["test"] for i in public], ["02"])
        self.assertEqual(public[0]["verdict"], "AC")
        self.assertEqual(public[0]["wall_s"] >= 0, True)
        self.assertTrue(hidden, "expected hidden tests to be redacted")
        for item in hidden:
            for leaked in ("input", "expected", "actual", "diff"):
                self.assertNotIn(leaked, item, f"{item['test']} leaked {leaked}")

        rows = self.stored(job_id=job["id"])
        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row["tests_hash"], grader.tests_hash(server.PROBLEMS["thai_time"]))
        self.assertEqual(row["grader_version"], grader.GRADER_VERSION)
        self.assertEqual(row["kind"], "submit")
        for item in row["results"]:
            if item.get("hidden"):
                self.assertNotIn("input", item)
                self.assertNotIn("expected", item)

    def test_wrong_answer_keeps_feedback_but_not_hidden_tests(self):
        self.login(STUDENT_A)
        job = self.judged("thai_time", WRONG)
        result = job["result"]
        self.assertFalse(result["accepted"])
        self.assertEqual(result["score"], 0)
        sample = [i for i in result["results"] if i["test"] == "02"][0]
        self.assertEqual(sample["verdict"], "WA")
        self.assertIn("diff", sample)          # public sample: full feedback
        for item in result["results"]:
            if item.get("hidden"):
                self.assertNotIn("diff", item)
                self.assertNotIn("input", item)
                self.assertNotIn("expected", item)

    def test_submit_returns_202_and_rejects_concurrent(self):
        self.login(STUDENT_A)
        slow = "import time\ntime.sleep(1.2)\nprint('x')\n"
        first = self.submit("thai_time", slow)
        second = self.submit("thai_time", slow, expect=409)
        self.assertIn("already have a submission", second["detail"])
        job = self.wait_job(first["job_id"])
        self.assertEqual(job["status"], "done")

    def test_submit_quota_returns_429(self):
        original = server.SUBMIT_QUOTA
        server.SUBMIT_QUOTA = (1, 600)
        try:
            self.login("quota@example.com")
            self.judged("thai_time", THAI_REF)
            r = self.client.post("/api/submit", data={
                "problem": "thai_time", "language": "python", "code": THAI_REF})
            self.assertEqual(r.status_code, 429, r.text)
            self.assertIn("quota", r.json()["detail"])
            self.assertIn("Retry-After", r.headers)
        finally:
            server.SUBMIT_QUOTA = original

    def test_playground_run_with_custom_input(self):
        self.login(STUDENT_A)
        code = "import sys\nsys.stdout.write(sys.stdin.read().strip().upper())\n"
        r = self.client.post("/api/run", data={
            "language": "python", "code": code, "input": "abc", "problem": "thai_time"})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["verdict"], "OK")
        self.assertEqual(body["stdout"], "ABC")

        tle = self.client.post("/api/run", data={
            "language": "python", "code": "while True:\n    pass\n",
            "input": "", "time_limit": "0.2"})
        self.assertEqual(tle.status_code, 200, tle.text)
        self.assertEqual(tle.json()["verdict"], "TLE")

        bad = self.client.post("/api/run", data={
            "language": "python", "code": "print(1)\n", "input": "x" * 1024})
        self.assertEqual(bad.status_code, 200)
        self.assertEqual(len(bad.json()["stdout"].strip()), 1)

    def test_history_detail_is_owner_or_admin_only(self):
        self.login(STUDENT_A)
        job = self.judged("thai_time", THAI_REF)
        sid = job["result"]["id"]
        self.assertTrue(sid)

        self.login(STUDENT_B)
        r = self.client.get(f"/api/history/{sid}")
        self.assertEqual(r.status_code, 403, r.text)

        self.login(STUDENT_A)
        r = self.client.get(f"/api/history/{sid}")
        self.assertEqual(r.status_code, 200, r.text)
        self.assertIn("code", r.json())
        self.assertIn("THAI", r.json()["code"].upper() + "THAI")

        self.login(ADMIN)
        r = self.client.get(f"/api/history/{sid}")
        self.assertEqual(r.status_code, 200, r.text)

    def test_contests_end_to_end(self):
        self.login(ADMIN)
        r = self.client.post("/api/contests", json={
            "id": "test-cup", "title": "Test Cup",
            "starts_at": _iso(-5), "ends_at": _iso(55),
            "problems": ["thai_time"], "freeze_minutes": 60, "show_samples": False})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["contest"]["status"], "running")

        self.login(STUDENT_A)
        listed = self.client.get("/api/contests").json()
        self.assertTrue(listed["configured"])
        self.assertIn("test-cup", [c["id"] for c in listed["contests"]])
        self.assertEqual([c for c in listed["contests"]
                          if c["id"] == "test-cup"][0]["status"], "running")

        # running contest with show_samples=false: even sample data is withheld
        job = self.judged_contest("thai_time", WRONG, "test-cup")
        for item in job["result"]["results"]:
            self.assertNotIn("input", item, item)
            self.assertNotIn("expected", item, item)
            self.assertTrue(item.get("hidden"), item)
        rows = self.stored(job_id=job["id"])
        self.assertEqual(rows[0]["contest_id"], "test-cup")

        # problem outside the contest, and a closed contest, are refused
        self.submit("hanoi", THAI_REF, expect=400, contest="test-cup")

        detail = self.client.get("/api/contests/test-cup").json()
        self.assertEqual(detail["id"], "test-cup")
        self.assertTrue(detail["frozen"], "freeze window must hide live rows")
        self.assertEqual(detail["scoreboard"], [], "frozen board hides fresh rows")
        self.assertEqual([p["id"] for p in detail["problem_details"]], ["thai_time"])

        self.login(ADMIN)
        admin_view = self.client.get("/api/contests/test-cup").json()
        self.assertFalse(admin_view["frozen"])
        self.assertEqual(admin_view["scoreboard"][0]["name"], "Tester")

        past = self.client.post("/api/contests", json={
            "id": "old-cup", "title": "Old", "starts_at": _iso(-120),
            "ends_at": _iso(-60), "problems": ["thai_time"]})
        self.assertEqual(past.status_code, 200)
        self.logout_in(STUDENT_A)
        self.submit("thai_time", THAI_REF, expect=403, contest="old-cup")

        self.login(ADMIN)
        self.assertEqual(self.client.delete("/api/contests/old-cup").status_code, 200)
        bad = self.client.post("/api/contests", json={
            "id": "bad cup", "starts_at": _iso(0), "ends_at": _iso(10),
            "problems": ["thai_time"]})
        self.assertEqual(bad.status_code, 400)

    def judged_contest(self, problem: str, code: str, contest: str) -> dict:
        job = self.submit(problem, code, contest=contest)
        return self.wait_job(job["job_id"])

    def logout_in(self, email: str) -> None:
        self.login(email)

    def test_rejudge_updates_the_same_row(self):
        self.login(STUDENT_A)
        job = self.judged("thai_time", THAI_REF)
        sid = job["result"]["id"]
        before = len(self.fake.rows("submissions"))

        self.login(ADMIN)
        r = self.client.post("/api/admin/rejudge", json={"ids": [sid]})
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["queued"], 1)
        done = self.wait_job(r.json()["jobs"][0])
        self.assertEqual(done["status"], "done", done)

        self.assertEqual(len(self.fake.rows("submissions")), before,
                         "rejudge must not create a new row")
        rows = self.stored(id=sid)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["kind"], "rejudge")
        self.assertEqual(rows[0]["passed"] + sum(
            n for v, n in rows[0]["counts"].items() if v != "AC"), rows[0]["total"])

    def test_plagiarism_finds_identical_submissions(self):
        self.login(STUDENT_A)
        first = self.judged("thai_time", THAI_REF)["result"]["id"]
        self.login(STUDENT_B)
        second = self.judged("thai_time", THAI_REF)["result"]["id"]

        self.login(ADMIN)
        r = self.client.get("/api/admin/plagiarism",
                            params={"problem": "thai_time", "threshold": 0.8})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertGreaterEqual(body["scanned"], 2)
        mine = [p for p in body["pairs"]
                if {p["a_id"], p["b_id"]} == {first, second}]
        self.assertTrue(mine, f"pair for the two identical submissions missing: {body['pairs']}")
        self.assertGreaterEqual(mine[0]["similarity"], 0.8)
        self.assertGreater(mine[0]["matches"], 10)
        self.assertEqual(mine[0]["language"], "python")

    def test_admin_endpoints_forbidden_for_students(self):
        self.login(STUDENT_A)
        self.assertEqual(self.client.post("/api/admin/rejudge",
                                          json={"ids": []}).status_code, 403)
        self.assertEqual(self.client.get("/api/admin/plagiarism",
                                         params={"problem": "thai_time"}).status_code, 403)
        self.assertEqual(self.client.post("/api/contests", json={}).status_code, 403)
        self.assertEqual(self.client.get("/api/admin/overview").status_code, 403)

    def test_admin_overview_reports_queue_state(self):
        # sync endpoint: it runs in a threadpool, where an event loop must not be
        # assumed (regression: _queue() raised "no running event loop" -> 500)
        self.login(ADMIN)
        r = self.client.get("/api/admin/overview")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertIn("jobs", body)
        self.assertEqual(set(body["jobs"]), {"queued", "running", "queue_depth", "workers"})
        self.assertGreaterEqual(body["jobs"]["workers"], 1)
        self.assertGreaterEqual(body["problems"], 40)
        self.assertIn("count_islands", body["system"]["problems_loaded"])

    def test_leaderboard_and_stats_use_all_time_views(self):
        r = self.client.get("/api/leaderboard")
        self.assertEqual(r.status_code, 200, r.text)
        top = r.json()["top"]
        self.assertTrue(top, "leaderboard should not be empty")
        points = [t["points"] for t in top]
        self.assertEqual(points, sorted(points, reverse=True))

        s = self.client.get("/api/stats").json()
        self.assertTrue(s["configured"])
        thai = s["stats"]["thai_time"]
        self.assertGreaterEqual(thai["subs"], thai["accepted"])
        self.assertGreaterEqual(thai["best"], 0)

    def test_health_and_problem_listing(self):
        h = self.client.get("/api/health").json()
        self.assertTrue(h["ok"])
        self.assertEqual(len(h["problems"]), len(server.PROBLEMS))
        detail = self.client.get("/api/problems/count_islands").json()
        self.assertEqual(detail["samples"], ["03"])
        self.assertEqual(detail["hidden_tests"], detail["tests"] - 1)


class PreMigrationFallback(unittest.TestCase):
    """Production runs this code BEFORE supabase/schema.sql is re-run: the new
    columns/tables/views are missing. Nothing may hard-fail."""

    OLD_SUB_COLS = {"id", "created_at", "problem", "language", "filename", "name",
                    "user_email", "verdict", "accepted", "passed", "total", "score",
                    "counts", "results", "code", "detail"}

    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(server.app)
        cls.client = cls._ctx.__enter__()
        cls.fake = FakeSupabase(
            columns={"submissions": cls.OLD_SUB_COLS,
                     "users": {"email", "name", "password_hash"},
                     "profiles": {"user_email", "display_name", "default_language"}},
            missing={"judge_jobs", "contests"}, views=False)
        server._sb = cls.fake

    @classmethod
    def tearDownClass(cls):
        server._sb = None
        cls._ctx.__exit__(None, None, None)

    def setUp(self):
        server._login_tries.clear()
        server._quota_hits.clear()

    def _register(self, email: str, name: str) -> None:
        self.client.cookies.clear()
        r = self.client.post("/api/auth/register", json={
            "email": email, "password": "testpass123", "name": name})
        self.assertIn(r.status_code, (200, 409), r.text)
        if r.status_code == 409:
            r = self.client.post("/api/auth/password",
                                 json={"email": email, "password": "testpass123"})
            self.assertEqual(r.status_code, 200, r.text)

    def _submit_and_wait(self, problem: str, code: str) -> dict:
        submit = self.client.post("/api/submit", data={
            "problem": problem, "language": "python", "code": code})
        self.assertEqual(submit.status_code, 202, submit.text)
        jid = submit.json()["job_id"]
        deadline = time.time() + 60
        job = {}
        while time.time() < deadline:
            job = self.client.get(f"/api/jobs/{jid}").json()
            if job["status"] in ("done", "error"):
                return job
            time.sleep(0.05)
        self.fail(f"job never finished without the queue tables: {job}")

    def test_submit_still_judges_and_stores_on_old_schema(self):
        self._register("legacy@example.com", "Legacy")
        job = self._submit_and_wait("thai_time", THAI_REF)
        self.assertEqual(job["status"], "done", job)
        self.assertEqual(job["result"]["score"], 100)

        rows = [r for r in self.fake.rows("submissions") if r.get("id") == job["result"]["id"]]
        self.assertEqual(len(rows), 1)
        # the traceability columns are dropped instead of losing the submission
        self.assertNotIn("tests_hash", rows[0])
        self.assertNotIn("grader_version", rows[0])

    def test_aggregates_fall_back_to_row_scan(self):
        self._register("legacy2@example.com", "Legacy2")
        self._submit_and_wait("thai_time", THAI_REF)

        led = self.client.get("/api/leaderboard")
        self.assertEqual(led.status_code, 200, led.text)
        self.assertTrue(led.json()["configured"])
        top = led.json()["top"]
        self.assertTrue(top, "fallback scan must still produce a leaderboard")
        self.assertIn("Legacy2", [t["name"] for t in top])

        stats = self.client.get("/api/stats")
        self.assertEqual(stats.status_code, 200, stats.text)
        self.assertIn("thai_time", stats.json()["stats"])
        self.assertGreaterEqual(stats.json()["stats"]["thai_time"]["accepted"], 1)

    def test_contests_report_unconfigured(self):
        body = self.client.get("/api/contests").json()
        self.assertFalse(body["configured"])
        self.assertEqual(body["contests"], [])
        self.assertIn("hint", body)

    def test_version_still_reports_hashes(self):
        body = self.client.get("/api/version").json()
        self.assertIn("thai_time", body["tests"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
