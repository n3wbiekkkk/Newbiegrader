"""Disclosure contracts through the module interface, without server globals."""
import copy
import datetime as dt
import unittest

from submission_disclosure import ContestUnavailable, DisclosureDenied, SubmissionDisclosure


NOW = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)
PRIVATE = "PRIVATE_DISCLOSURE_CANARY"


class FixtureSource:
    def __init__(self):
        self.rows = []
        self.admins = {"admin"}
        self.published = {"is_published": True, "hidden": False}
        self.failed = False
        self.contest_reads = 0

    def contests(self):
        self.contest_reads += 1
        if self.failed:
            raise RuntimeError("synthetic unavailable policy")
        return self.rows

    peer_contests = contests

    def contest(self, cid):
        for row in self.contests():
            if row["id"] == cid:
                return row
        raise ContestUnavailable

    def publication(self, pid):
        return self.published if pid == "p" else None

    def sample_names(self, pid):
        return {"01"} if pid == "p" else set()

    def resolve_pid(self, token):
        return "p" if token == "1" else token

    def is_admin(self, email):
        return email in self.admins


class SubmissionDisclosureTests(unittest.TestCase):
    def setUp(self):
        self.source = FixtureSource()
        self.disclosure = SubmissionDisclosure(self.source, clock=lambda: NOW)
        self.result = {"score": 0, "results": [
            {"test": "01", "verdict": "WA", "input": "sample"},
            {"test": "1001", "verdict": "WA", "input": PRIVATE,
             "actual": PRIVATE, "practice_feedback": True, "detail": PRIVATE},
        ]}
        self.row = {"id": "s", "problem": "p", "user_email": "owner",
                    "kind": "submit", "verdict": "WA", "name": "Owner",
                    "code": "print(1)", "results": self.result["results"]}

    def contest(self, **extra):
        return {"id": "c", "problems": ["1"], "show_samples": False,
                "starts_at": (NOW - dt.timedelta(hours=1)).isoformat(),
                "ends_at": (NOW + dt.timedelta(hours=1)).isoformat(), **extra}

    def test_stored_snapshot_survives_but_live_reads_recheck_current_policy(self):
        job = {**self.row, "status": "done", "reveal": "practice-failures"}
        stored = self.disclosure.stored_result(job, self.result)
        job["result"] = stored
        self.assertIn(PRIVATE, str(self.disclosure.job_result(job)))
        self.source.rows = [self.contest()]
        self.assertNotIn(PRIVATE, str(self.disclosure.job_result(job)))
        self.assertNotIn("sample", str(self.disclosure.history_detail(self.row, "owner")))
        self.assertIn(PRIVATE, str(stored))
        self.assertEqual(self.source.contest_reads, 3)

    def test_admin_viewer_does_not_elevate_the_submission_owner(self):
        self.source.rows = [self.contest()]
        row = {**self.row, "contest_id": "c"}
        self.assertNotIn(PRIVATE, str(self.disclosure.history_detail(row, "admin")))
        self.assertIn(PRIVATE, str(self.disclosure.history_detail(
            {**row, "user_email": "admin"}, "admin")))

    def test_peer_projection_excludes_private_fields_and_invalid_measurements(self):
        row = {**self.row, "name": "email@example.invalid", "results": [
            {"verdict": "WA", "input": PRIVATE, "detail": PRIVATE, "test": PRIVATE,
             "wall_s": float("nan"), "cpu_s": True, "peak_mb": -1},
            {"verdict": "AC", "wall_s": 0.1, "cpu_s": 0, "peak_mb": 3},
            "invalid"], "arbitrary_private_field": PRIVATE}
        result = self.disclosure.history_detail(row, "peer")
        self.assertNotIn(PRIVATE, str(result))
        self.assertNotIn("user_email", result)
        self.assertEqual(result["code"], "print(1)")
        self.assertEqual(result["name"], "นักเรียน")
        self.assertEqual(result["results"][0], {"verdict": "WA", "hidden": True,
            "wall_s": None, "cpu_s": None, "peak_mb": None})
        self.assertEqual(result["results"][1]["wall_s"], 0.1)

    def test_peer_outage_and_unfinished_rows_preserve_denial_status(self):
        self.source.failed = True
        with self.assertRaises(DisclosureDenied) as exc:
            self.disclosure.history_detail(self.row, "peer")
        self.assertEqual(exc.exception.status_code, 503)
        self.source.failed = False
        with self.assertRaises(DisclosureDenied) as exc:
            self.disclosure.history_detail({**self.row, "status": "queued"}, "peer")
        self.assertEqual(exc.exception.reason, "incomplete submission")
        self.assertEqual(exc.exception.status_code, 403)

    def test_public_lists_never_contain_source_or_per_case_details(self):
        public = self.disclosure.public_history({**self.row, "private": PRIVATE,
            "counts": {"WA": 2, "AC": True, "RE": -1, PRIVATE: 100}})
        self.assertFalse({"user_email", "code", "results", "private"} & public.keys())
        self.assertEqual(public["counts"], {"WA": 2})
        self.assertNotIn("code", self.disclosure.history_columns.split(","))

    def test_contest_storage_cannot_opt_into_practice_feedback(self):
        job = {**self.row, "contest_id": "c", "reveal": "practice-failures"}
        self.assertNotIn(PRIVATE, str(self.disclosure.stored_result(job, self.result)))
        self.assertNotIn(PRIVATE, str(self.disclosure.completion_result(job, self.result)))

    def test_rejudge_snapshots_are_per_batch_and_use_owner_privilege(self):
        self.source.rows = [self.contest()]
        batch = self.disclosure.rejudge_policy()
        self.assertEqual(batch("c", "owner", "p"), "none")
        self.assertEqual(batch("c", "admin", "p"), "all")
        self.assertEqual(self.source.contest_reads, 1)
        self.source.rows = []
        self.assertEqual(self.disclosure.rejudge_policy()("c", "owner", "p"), "none")
        self.assertEqual(self.source.contest_reads, 2)

    def test_invalid_policy_closes_reads_and_sample_lookup_errors_propagate(self):
        self.source.rows = [self.contest(ends_at="invalid")]
        self.assertEqual(self.disclosure.admission_reveal(None, "owner", "p"), "none")
        self.assertEqual(self.disclosure.hidden_sample_problems(), {"p"})
        self.assertFalse(self.disclosure.peer_access("peer", "p")["allowed"])
        self.source.failed = True
        with self.assertRaises(RuntimeError):
            self.disclosure.hidden_sample_problems()

    def test_unexpected_rejudge_adapter_errors_do_not_silently_enqueue(self):
        self.source.failed = True
        with self.assertRaises(RuntimeError):
            self.disclosure.rejudge_policy()("c", "owner", "p")

    def test_hidden_and_unpublished_problem_facts_are_rechecked(self):
        self.assertTrue(self.disclosure.peer_access("peer", "p")["allowed"])
        self.source.published = {"is_published": True, "hidden": True}
        self.assertFalse(self.disclosure.peer_access("peer", "p")["allowed"])
        self.source.rows = [self.contest(ends_at=(NOW - dt.timedelta(minutes=1)).isoformat(),
                                        starts_at=(NOW - dt.timedelta(hours=2)).isoformat())]
        self.assertTrue(self.disclosure.peer_access("peer", "p")["allowed"])
        self.source.published["is_published"] = False
        self.assertFalse(self.disclosure.peer_access("peer", "p")["allowed"])

    def test_projection_never_modifies_stored_input(self):
        original = copy.deepcopy(self.row)
        self.disclosure.history_detail(self.row, "owner")
        self.disclosure.history_detail(self.row, "peer")
        self.disclosure.stored_result(self.row, self.result)
        self.assertEqual(self.row, original)

    def test_pending_or_malformed_jobs_return_no_verdict(self):
        for result in (None, [], "corrupt"):
            self.assertIsNone(self.disclosure.job_result({"status": "done", "result": result}))
        self.assertIsNone(self.disclosure.job_result({"status": "queued", "result": self.result}))
        self.assertEqual(self.disclosure.job_result({"status": "done", "kind": "playground",
                                                    "result": {"stdout": "trial"}}), {"stdout": "trial"})
