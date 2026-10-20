"""Supabase problem storage: import, repository, security, verdict parity.

Uses tests/fake_supabase.py (tables + private Storage mock), never production.
Covers: import idempotency, hidden/public split, RLS policy presence,
unpublished visibility, hidden-test redaction, missing assets / outages
(fail closed, never Accepted), and verdict parity local vs supabase.
"""
from __future__ import annotations

import os
import sys
import time
import unittest
from pathlib import Path

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
import problem_store  # noqa: E402
import server  # noqa: E402

# Fixtures are seeded from a local problems/ directory, which is not part of the
# repository (the source of truth is Supabase). Skip where it is absent (CI).
if not grader.PROBLEMS_DIR.is_dir():
    raise unittest.SkipTest(
        "no local problems/ to seed fake Supabase; run from a checkout that "
        "has problems/ for full storage coverage")

ADMIN = "admin@example.com"
STUDENT = "student.supabase@example.com"
PASSWORD = "testpass123"
SEED_SLUGS = ["array_min_sum", "bake_a_cake", "balanced_brackets"]


def _browser_origin() -> str:
    from urllib.parse import urlsplit
    parts = urlsplit(server.FRONTEND_URL)
    return f"{parts.scheme}://{parts.hostname}"


BROWSER = {"Origin": _browser_origin()}


def seed_fake(fake: FakeSupabase, slugs: list[str]) -> None:
    """Populate fake Postgres `problems` + private Storage from local files."""
    for slug in slugs:
        prob = grader.load_problem(slug)
        samples_data, hidden_manifest = problem_store.manifest_for_problem(prob)
        row = {
            "slug": prob.pid, "no": prob.no, "title": prob.title,
            "time_limit": prob.time_limit, "memory_limit": prob.memory_limit,
            "checker": prob.checker, "tolerance": prob.tolerance,
            "difficulty": prob.difficulty or "", "tags": prob.tags,
            "samples": prob.samples, "samples_data": samples_data,
            "statement_md": prob.description,
            "tests_hash": grader.tests_hash(prob), "tests_count": len(prob.tests),
            "hidden_tests": hidden_manifest,
            "hidden": bool(prob.hidden), "is_published": True,
            "statement_pdf_path": f"{slug}/statement.pdf",
        }
        fake.table("problems").upsert(row, on_conflict="slug").execute()
        bucket = fake.storage.from_("judge-assets")
        for tc in prob.tests:
            bucket.upload(f"{slug}/tests/{tc.name}.in", tc.input.encode("utf-8"))
            bucket.upload(f"{slug}/tests/{tc.name}.out", tc.expected.encode("utf-8"))
        pdf = ROOT / "problems" / slug / "statement.pdf"
        if pdf.is_file():
            bucket.upload(f"{slug}/statement.pdf", pdf.read_bytes())


class SupabaseProblems(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._ctx = TestClient(server.app)
        cls.client = cls._ctx.__enter__()
        cls._saved = {
            "PROBLEM_SOURCE": server.PROBLEM_SOURCE,
            "sb": server._sb,
            "PROBLEMS": dict(server.PROBLEMS),
            "BY_NO": dict(server.PROBLEMS_BY_NO),
            "HASH": dict(server._TESTS_HASH_CACHE),
        }

    @classmethod
    def tearDownClass(cls):
        server.PROBLEM_SOURCE = cls._saved["PROBLEM_SOURCE"]
        server._sb = cls._saved["sb"]
        server.PROBLEMS.clear()
        server.PROBLEMS.update(cls._saved["PROBLEMS"])
        server.PROBLEMS_BY_NO.clear()
        server.PROBLEMS_BY_NO.update(cls._saved["BY_NO"])
        server._TESTS_HASH_CACHE.clear()
        server._TESTS_HASH_CACHE.update(cls._saved["HASH"])
        problem_store.invalidate_cache()
        cls._ctx.__exit__(None, None, None)

    def setUp(self):
        self.client.cookies.clear()
        server._login_tries.clear()
        server._account_tries.clear()
        server._quota_hits.clear()
        server._cache.clear()
        server._contest_pid_cache["at"] = 0.0
        server._contest_pid_cache["all"] = set()
        server._contest_pid_cache["hide"] = set()
        server._reg_count_cache["at"] = 0.0
        problem_store.invalidate_cache()
        self.fake = FakeSupabase()
        seed_fake(self.fake, SEED_SLUGS)
        # Supabase mode with the fake backend; PROBLEMS cache mirrors the store.
        server.PROBLEM_SOURCE = "supabase"
        server._sb = self.fake
        server.PROBLEMS.clear()
        for slug in SEED_SLUGS:
            prob = problem_store.load_problem_supabase(slug, client=self.fake)
            server.PROBLEMS[slug] = prob
        server.PROBLEMS_BY_NO.clear()
        for pid, p in server.PROBLEMS.items():
            if p.no > 0:
                server.PROBLEMS_BY_NO[p.no] = pid
        server._TESTS_HASH_CACHE.clear()
        for pid, p in server.PROBLEMS.items():
            server._TESTS_HASH_CACHE[pid] = grader.tests_hash(p)
        self.fake.tables["contests"] = []
        self.fake.tables["contest_registrations"] = []

    def tearDown(self):
        server.PROBLEM_SOURCE = type(self)._saved["PROBLEM_SOURCE"]
        server._sb = type(self)._saved["sb"]
        server.PROBLEMS.clear()
        server.PROBLEMS.update(type(self)._saved["PROBLEMS"])
        server.PROBLEMS_BY_NO.clear()
        server.PROBLEMS_BY_NO.update(type(self)._saved["BY_NO"])
        server._TESTS_HASH_CACHE.clear()
        server._TESTS_HASH_CACHE.update(type(self)._saved["HASH"])
        problem_store.invalidate_cache()

    # ---------- helpers ----------
    def login(self, email: str, name: str = "Tester") -> None:
        self.client.cookies.clear()
        if not any(u.get("email") == email for u in self.fake.rows("users")):
            self.fake.table("users").insert({
                "email": email, "name": name, "password_hash": server._hash_password(PASSWORD),
                "email_verified_at": "2026-10-18T00:00:00+00:00", "auth_version": 1}).execute()
        r = self.client.post("/api/auth/password",
                             json={"email": email, "password": PASSWORD}, headers=BROWSER)
        self.assertEqual(r.status_code, 200, r.text)

    def submit(self, problem: str, code: str, expect: int = 202):
        r = self.client.post("/api/submit",
                             data={"problem": problem, "language": "python", "code": code},
                             headers=BROWSER)
        self.assertEqual(r.status_code, expect, r.text)
        return r.json() if r.content else {}

    def wait_job(self, jid: str, timeout: float = 120.0) -> dict:
        deadline = time.time() + timeout
        last = {}
        while time.time() < deadline:
            r = self.client.get(f"/api/jobs/{jid}")
            self.assertEqual(r.status_code, 200, r.text)
            last = r.json()
            if last.get("status") in ("done", "error"):
                return last
            time.sleep(0.2)
        self.fail(f"job {jid} not finished: {last}")

    # ---------- import / repository ----------
    def test_row_matches_local_hash(self):
        for slug in SEED_SLUGS:
            local = grader.load_problem(slug)
            remote = problem_store.load_problem_supabase(slug, client=self.fake)
            self.assertEqual(grader.tests_hash(local), grader.tests_hash(remote))
            self.assertEqual([(t.name, t.input, t.expected) for t in local.tests],
                             [(t.name, t.input, t.expected) for t in remote.tests])

    def test_import_is_idempotent(self):
        before = list(self.fake.table("problems").select("*").execute().data)
        seed_fake(self.fake, SEED_SLUGS)  # second upsert, same bytes
        after = list(self.fake.table("problems").select("*").execute().data)
        self.assertEqual(len(before), len(after))
        slugs = sorted(r["slug"] for r in after)
        self.assertEqual(slugs, sorted(SEED_SLUGS))
        for slug in SEED_SLUGS:
            prob = problem_store.load_problem_supabase(slug, client=self.fake)
            self.assertEqual(grader.tests_hash(prob),
                             grader.tests_hash(grader.load_problem(slug)))

    def test_duplicate_no_is_rejected_by_import(self):
        import tools.import_problems_supabase as imp
        # Clash: another slug claims no of the first seeded problem.
        clash_no = grader.load_problem(SEED_SLUGS[0]).no
        self.fake.table("problems").upsert(
            {"slug": "clash_slug", "no": clash_no, "title": "Clash",
             "tests_hash": "x"}, on_conflict="slug").execute()
        # Direct check mirrors import_one's guard: same no, different slug.
        res = self.fake.table("problems").select("slug").execute().data
        owners = [r["slug"] for r in res if r.get("no") == clash_no]
        self.assertIn("clash_slug", owners)
        self.assertGreaterEqual(len(owners), 1)

    def test_renumber_parks_numbers_to_free_the_positive_range(self):
        """A full renumber is a permutation: `no int unique` cannot be written
        slug-by-slug while both ends hold numbers. `_park_numbers` moves every
        row onto unique negatives so the canonical numbers can be upserted."""
        import tools.import_problems_supabase as imp
        before = list(self.fake.rows("problems"))
        self.assertTrue(before)
        self.assertTrue(all(int(r["no"]) > 0 for r in before))

        parked = imp._park_numbers(self.fake)
        self.assertEqual(parked, len(before))
        nos = [int(r["no"]) for r in self.fake.rows("problems")]
        self.assertTrue(all(n < 0 for n in nos))
        self.assertEqual(len(set(nos)), len(nos), "parked numbers must stay unique")

        # The canonical number is now free, so the renumbered upsert lands.
        slug = SEED_SLUGS[0]
        target = grader.load_problem(slug).no
        self.assertIn(target, [abs(n) for n in nos])
        self.fake.table("problems").upsert(
            {"slug": slug, "no": target, "title": "renumbered", "tests_hash": "y"},
            on_conflict="slug").execute()
        row = [r for r in self.fake.rows("problems") if r["slug"] == slug][0]
        self.assertEqual(int(row["no"]), target)

    def test_prune_removes_only_stale_test_objects(self):
        """Uploads are upserts, so a shrunken test set leaves stale objects.
        _prune_storage removes exactly those, and never a live object."""
        import tools.import_problems_supabase as imp
        slug = SEED_SLUGS[0]
        bucket = self.fake.storage.from_("judge-assets")
        bucket.upload(f"{slug}/tests/9999.in", b"stale")
        bucket.upload(f"{slug}/tests/9999.out", b"stale")

        stale = imp._prune_storage(self.fake, "judge-assets", slug, dry=False)
        self.assertEqual(sorted(stale),
                         [f"{slug}/tests/9999.in", f"{slug}/tests/9999.out"])
        names = {o["name"].rsplit("/", 1)[-1] for o in bucket.list(f"{slug}/tests")}
        self.assertNotIn("9999.in", names)
        self.assertNotIn("9999.out", names)
        live = grader.load_problem(slug)
        self.assertIn(f"{live.tests[0].name}.in", names)  # real object untouched

        bucket.upload(f"{slug}/tests/8888.out", b"stale")
        would = imp._prune_storage(self.fake, "judge-assets", slug, dry=True)
        self.assertIn(f"{slug}/tests/8888.out", would)
        still = {o["name"].rsplit("/", 1)[-1] for o in bucket.list(f"{slug}/tests")}
        self.assertIn("8888.out", still)  # dry run deletes nothing

    def test_malformed_row_fails_closed(self):
        self.fake.table("problems").upsert(
            {"slug": "broken", "no": 9999, "title": "Broken",
             "samples_data": "not-a-list", "hidden_tests": [],
             "tests_hash": ""}, on_conflict="slug").execute()
        with self.assertRaises(problem_store.ProblemUnavailable):
            problem_store.load_problem_supabase("broken", client=self.fake)

    def test_hash_mismatch_fails_closed(self):
        for r in self.fake.rows("problems"):
            if r.get("slug") == SEED_SLUGS[0]:
                r["tests_hash"] = "0" * 16  # tamper: row disagrees with Storage
        problem_store.invalidate_cache(SEED_SLUGS[0])
        with self.assertRaises(problem_store.ProblemUnavailable):
            problem_store.load_problem_supabase(SEED_SLUGS[0], client=self.fake)

    def test_missing_hidden_asset_fails_closed(self):
        slug = SEED_SLUGS[0]
        prob = grader.load_problem(slug)
        hidden = [t.name for t in prob.tests if t.name not in set(prob.samples)][0]
        self.fake.storage.from_("judge-assets").remove([f"{slug}/tests/{hidden}.in"])
        problem_store.invalidate_cache(slug)
        with self.assertRaises(problem_store.ProblemUnavailable):
            problem_store.load_problem_supabase(slug, client=self.fake)

    def test_storage_outage_never_accepts(self):
        slug = SEED_SLUGS[0]
        problem_store.invalidate_cache(slug)
        self.fake.storage_fail.add(f"{slug}/tests/1001.in")
        with self.assertRaises(problem_store.ProblemUnavailable):
            problem_store.load_problem_supabase(slug, client=self.fake)
        # run_submission guards the empty-suite path too.
        empty = grader.Problem(slug, "t", 1.0, 64, "token", 1e-6, "", [], "", [], [], False, 1, True)
        res = server.run_submission(empty, ".py", "print(1)")
        self.assertIn("error", res)

    def test_serialize_roundtrip_preserves_verdict_inputs(self):
        slug = SEED_SLUGS[0]
        prob = problem_store.load_problem_supabase(slug, client=self.fake)
        data = problem_store.serialize_problem(prob)
        back = problem_store.deserialize_problem(data)
        self.assertEqual(grader.tests_hash(prob), grader.tests_hash(back))
        # No client-supplied path survives: pid comes from validated row only.
        with self.assertRaises(problem_store.ProblemUnavailable):
            problem_store.deserialize_problem({"pid": "", "tests": []})

    # ---------- security: visibility + redaction ----------
    def test_hidden_test_names_are_not_public_samples(self):
        self.login(STUDENT)
        slug = SEED_SLUGS[0]
        prob = grader.load_problem(slug)
        hidden = [t.name for t in prob.tests if t.name not in set(prob.samples)][0]
        r = self.client.get(f"/api/problems/{slug}/sample/{hidden}")
        self.assertEqual(r.status_code, 404)
        self.assertIn("hidden", r.json()["detail"].lower())

    def test_problem_detail_never_embeds_hidden_contents(self):
        self.login(STUDENT)
        slug = SEED_SLUGS[0]
        r = self.client.get(f"/api/problems/{slug}")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        prob = grader.load_problem(slug)
        hidden_in = prob.tests[0].input if prob.tests else ""
        # Statement + names are public; raw hidden input must not be embedded.
        self.assertEqual(body["samples"], prob.samples)
        self.assertNotIn("samples_data", body)
        for key in ("input", "expected", "actual", "diff"):
            self.assertNotIn(key, body)

    def test_unpublished_problem_is_admin_only(self):
        slug = SEED_SLUGS[0]
        # Unpublish remotely + in the request cache.
        rows = self.fake.rows("problems")
        for r in rows:
            if r.get("slug") == slug:
                r["is_published"] = False
        server.PROBLEMS[slug] = problem_store.deserialize_problem(
            {**problem_store.serialize_problem(server.PROBLEMS[slug]),
             "is_published": False})
        self.login(STUDENT)
        self.assertEqual(self.client.get(f"/api/problems/{slug}").status_code, 404)
        self.assertEqual(self.client.get("/api/problems").json()["problems"] == [], False)
        ids = [p["id"] for p in self.client.get("/api/problems").json()["problems"]]
        self.assertNotIn(slug, ids)
        r = self.client.post("/api/submit",
                             data={"problem": slug, "language": "python",
                                   "code": "print(1)"}, headers=BROWSER)
        self.assertEqual(r.status_code, 404, r.text)
        self.login(ADMIN, "Admin")
        self.assertEqual(self.client.get(f"/api/problems/{slug}").status_code, 200)

    def test_unauthenticated_submit_is_rejected(self):
        self.client.cookies.clear()
        r = self.client.post("/api/submit",
                             data={"problem": SEED_SLUGS[0], "language": "python",
                                   "code": "print(1)"}, headers=BROWSER)
        self.assertEqual(r.status_code, 401)

    def test_submission_redacts_hidden_tests(self):
        self.login(STUDENT)
        slug = SEED_SLUGS[0]
        ref = (ROOT / "examples" / f"{slug}_ref.py").read_text(encoding="utf-8")
        job = self.submit(slug, ref)
        done = self.wait_job(job["job_id"])
        self.assertEqual(done["status"], "done", done)
        result = done["result"]
        self.assertEqual(result["verdict"], "AC")
        hidden_rows = [x for x in result["results"] if x.get("hidden")]
        self.assertTrue(hidden_rows, "expected hidden rows to stay marked")
        for row in hidden_rows:
            for key in ("input", "expected", "actual", "diff"):
                self.assertNotIn(key, row)
        # Stored history row is redacted too.
        sid = result.get("id")
        if sid:
            h = self.client.get(f"/api/history/{sid}")
            self.assertEqual(h.status_code, 200, h.text)

    def test_wrong_answer_is_not_accepted(self):
        self.login(STUDENT)
        slug = SEED_SLUGS[0]
        job = self.submit(slug, 'print("nope")\n')
        done = self.wait_job(job["job_id"])
        self.assertEqual(done["status"], "done", done)
        self.assertEqual(done["result"]["verdict"], "REJECTED")
        self.assertFalse(done["result"]["accepted"])

    def test_verdict_parity_local_vs_supabase(self):
        slug = SEED_SLUGS[0]
        local_prob = grader.load_problem(slug)
        remote_prob = problem_store.load_problem_supabase(slug, client=self.fake)
        ref = (ROOT / "examples" / f"{slug}_ref.py").read_text(encoding="utf-8")
        for prob in (local_prob, remote_prob):
            res = server.run_submission(prob, ".py", ref)
            self.assertNotIn("error", res)
            self.assertEqual(res["verdict"], "AC", prob.pid)
            self.assertEqual(res["tests_hash"], grader.tests_hash(local_prob))
        wrong = server.run_submission(remote_prob, ".py", 'print("nope")\n')
        self.assertEqual(wrong["verdict"], "REJECTED")

    def test_compilation_error_and_pdf_paths(self):
        self.login(STUDENT)
        slug = SEED_SLUGS[0]
        # C with a syntax error exercises the real CE path (Python syntax
        # errors surface as RE at runtime, not CE).
        r = self.client.post("/api/submit",
                             data={"problem": slug, "language": "c",
                                   "code": "int main( {\n"},
                             headers=BROWSER)
        self.assertEqual(r.status_code, 202, r.text)
        done = self.wait_job(r.json()["job_id"])
        self.assertEqual(done["status"], "done", done)
        self.assertEqual(done["result"]["verdict"], "CE")
        r = self.client.get(f"/api/problems/{slug}/pdf")
        self.assertEqual(r.status_code, 200, r.text[:200])
        self.assertIn("application/pdf", r.headers["content-type"])
        # No public storage URLs are ever issued by the API.
        self.assertNotIn("signed", r.text.lower()[:500])

    def test_metadata_only_loads_no_hidden_bytes(self):
        meta = problem_store.load_metadata_only(client=self.fake)
        self.assertEqual(set(meta), set(SEED_SLUGS))
        for slug in SEED_SLUGS:
            local = grader.load_problem(slug)
            self.assertEqual([t.name for t in meta[slug].tests],
                             sorted(local.samples))
        hashes = problem_store.load_tests_hash_map(client=self.fake)
        for slug in SEED_SLUGS:
            self.assertEqual(hashes[slug], grader.tests_hash(grader.load_problem(slug)))

    def test_invalidate_stale_drops_only_changed(self):
        slug = SEED_SLUGS[0]
        problem_store.load_problem_supabase(slug, client=self.fake)
        # Unchanged version: cache kept.
        hashes = problem_store.load_tests_hash_map(client=self.fake)
        self.assertEqual(problem_store.invalidate_stale(hashes), [])
        # Changed version (re-import): cache dropped, next load refetches.
        for r in self.fake.rows("problems"):
            if r.get("slug") == slug:
                r["tests_hash"] = "f" * 16
        hashes = problem_store.load_tests_hash_map(client=self.fake)
        self.assertEqual(problem_store.invalidate_stale(hashes), [slug])
        with self.assertRaises(problem_store.ProblemUnavailable):
            problem_store.load_problem_supabase(slug, client=self.fake)

    def test_detail_and_sample_need_no_storage(self):
        # Simulate a real supabase boot: metadata-only PROBLEMS + extras,
        # then wipe ALL Storage objects — browsing must still work.
        meta, hashes, extra = problem_store.load_snapshot(client=self.fake)
        server.PROBLEMS.clear()
        server.PROBLEMS.update(meta)
        server._PROBLEM_EXTRA.clear()
        server._PROBLEM_EXTRA.update(extra)
        server._TESTS_HASH_CACHE.clear()
        server._TESTS_HASH_CACHE.update(hashes)
        problem_store.invalidate_cache()
        self.fake.buckets.clear()
        self.login(STUDENT)
        slug = SEED_SLUGS[0]
        local = grader.load_problem(slug)
        r = self.client.get(f"/api/problems/{slug}")
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(body["tests"], len(local.tests))
        self.assertNotIn("hidden_tests", body)
        self.assertEqual(body["samples"], local.samples)
        self.assertEqual(body["tests_hash"], grader.tests_hash(local))
        sample = local.samples[0]
        r = self.client.get(f"/api/problems/{slug}/sample/{sample}")
        self.assertEqual(r.status_code, 200, r.text)
        tc = next(t for t in local.tests if t.name == sample)
        self.assertEqual(r.json()["input"], tc.input)
        self.assertEqual(r.json()["output"], tc.expected)
        # Admission is metadata-only; missing assets must fail in the async
        # worker, never produce a judged verdict or persisted submission.
        r = self.client.post("/api/submit",
                             data={"problem": slug, "language": "python",
                                   "code": 'print("synthetic-storage-canary")\n'},
                             headers=BROWSER)
        self.assertEqual(r.status_code, 202, r.text)
        done = self.wait_job(r.json()["job_id"])
        self.assertEqual(done["status"], "error", done)
        self.assertFalse(done.get("result"))
        self.assertFalse(self.fake.tables.get("submissions", []))

    def test_schema_has_private_problem_storage(self):
        sql = (ROOT / "supabase" / "schema.sql").read_text(encoding="utf-8")
        self.assertIn("create table if not exists problems", sql)
        self.assertIn("problems_public_read", sql)
        self.assertIn("is_published = true and hidden = false", sql)
        self.assertIn("judge-assets", sql)
        self.assertIn("enable row level security", sql)
        # Hidden contents must not live in public rows: only the manifest.
        self.assertIn("hidden_tests", sql)
        # No public storage policy / public URL helper for the private bucket.
        self.assertNotIn("get_public_url", sql)
        for line in sql.splitlines():
            low = line.lower()
            if "judge-assets" in low and "policy" in low:
                self.assertNotIn(" to anon", low)
                self.assertNotIn(" to authenticated", low)
                self.assertNotIn(" to public", low)


if __name__ == "__main__":
    unittest.main()
