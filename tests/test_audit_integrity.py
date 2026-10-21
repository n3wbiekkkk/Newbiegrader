# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Offline regressions for submission provenance and input boundaries."""
import asyncio
import io
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest

import grader
import judge_runner
import problem_store
from critical_helpers import synthetic_problem, test_server
from judge_runner import run_isolated

server = test_server()


class SubmissionIntegrity(unittest.TestCase):
    def test_persisted_source_is_the_complete_validated_source(self):
        source = "#" + "s" * 210000 + '\nprint("hello")\n'
        accepted, _ = asyncio.run(server._read_source("python", source, None))
        row = server._submission_row({"source": accepted}, {"results": []})
        self.assertEqual(row["code"], source)

    def test_persisted_hash_comes_from_the_executed_suite(self):
        prob = synthetic_problem()
        with patch.object(server, "PROBLEMS", {prob.pid: prob}), \
                patch.object(server, "_TESTS_HASH_CACHE", {prob.pid: "stale-cached-hash"}):
            row = server._submission_row({"problem": prob.pid, "tests_hash": "admission-hash"},
                                         {"tests_hash": "executed-suite-hash", "results": []})
        self.assertEqual(row["tests_hash"], "executed-suite-hash")

    def test_isolated_runner_reports_the_hash_of_embedded_tests(self):
        prob = synthetic_problem()
        result = asyncio.run(run_isolated("submission", {
            "problem": prob.pid, "problem_data": problem_store.serialize_problem(prob),
            "ext": ".py", "source": 'print("hello")\n', "reveal": "samples",
            "memory_cap_mb": 128, "judge_jobs": 1,
        }, 20))
        self.assertTrue(result.get("accepted"), result)
        self.assertEqual(result["tests_hash"], grader.tests_hash(prob))


class _RetryClient:
    """Supabase stand-in that fails the first insert, then succeeds."""

    def __init__(self, error: str):
        self.error = error
        self.inserts: list[dict] = []

    def table(self, _name):
        client = self

        class _Query:
            def insert(self, row):
                client.inserts.append(dict(row))
                if len(client.inserts) == 1:
                    raise Exception(client.error)
                return type("_Builder", (), {
                    "execute": lambda _self: type("_Resp", (), {"data": [{"id": "retried"}]})()})()

        return _Query()


class _RetryUpdateClient:
    """Supabase stand-in that fails the first rejudge update, then succeeds."""

    def __init__(self, error: str):
        self.error = error
        self.updates: list[dict] = []

    def table(self, _name):
        client = self

        class _Builder:
            def __init__(self, row):
                self.row = row

            def eq(self, _column, _value):
                return self

            def execute(self):
                if len(client.updates) == 1:
                    raise Exception(client.error)
                return type("_Resp", (), {"data": [{"id": "rejudged"}]})()

        class _Query:
            def update(self, row):
                client.updates.append(dict(row))
                return _Builder(row)

        return _Query()



class SubmissionStoreRetry(unittest.TestCase):
    """Schema fallback must never downgrade contest provenance.

    The retry exists for pre-2026-10 databases. It must not fire for integrity
    errors that merely mention a column. If contest_id itself is unavailable,
    a contest row must fail closed rather than being persisted as practice data
    (visible to the all-time leaderboard and later practice feedback). A
    practice row has no provenance to lose and may use the legacy fallback.
    """

    def test_integrity_error_mentioning_a_column_is_not_retried(self):
        client = _RetryClient('null value in column "contest_id" of relation '
                              '"submissions" violates not-null constraint')
        with patch.object(server, "_sb", client):
            sid = asyncio.run(server._store_submission(
                {"problem": "p", "contest_id": "c1", "kind": "submit"}))
        self.assertIsNone(sid)
        self.assertEqual(len(client.inserts), 1, "integrity error must not be retried")

    def test_missing_column_error_retries_but_preserves_contest_id(self):
        client = _RetryClient("Could not find the 'tests_hash' column of "
                              "'submissions' in the schema cache")
        with patch.object(server, "_sb", client):
            sid = asyncio.run(server._store_submission(
                {"problem": "p", "contest_id": "c1", "kind": "submit",
                 "job_id": "j1"}))
        self.assertEqual(sid, "retried")
        self.assertEqual(len(client.inserts), 2)
        self.assertEqual(client.inserts[1]["contest_id"], "c1")
        self.assertNotIn("tests_hash", client.inserts[1])
        self.assertNotIn("job_id", client.inserts[1])

    def test_missing_contest_id_column_is_not_downgraded_to_practice(self):
        client = _RetryClient("Could not find the 'contest_id' column of "
                              "'submissions' in the schema cache")
        with patch.object(server, "_sb", client):
            sid = asyncio.run(server._store_submission(
                {"problem": "p", "contest_id": "c1", "kind": "submit"}))
        self.assertIsNone(sid)
        self.assertEqual(len(client.inserts), 1, "must not retry a contest row without contest_id")

    def test_missing_contest_id_column_still_accepts_a_practice_row(self):
        client = _RetryClient("Could not find the 'contest_id' column of "
                              "'submissions' in the schema cache")
        with patch.object(server, "_sb", client):
            sid = asyncio.run(server._store_submission(
                {"problem": "p", "contest_id": None, "kind": "submit"}))
        self.assertEqual(sid, "retried")
        self.assertEqual(len(client.inserts), 2)
        self.assertNotIn("contest_id", client.inserts[1])

    def test_missing_relation_is_not_retried_as_a_missing_column(self):
        client = _RetryClient('relation "public.submissions" does not exist')
        with patch.object(server, "_sb", client):
            sid = asyncio.run(server._store_submission({"problem": "p"}))
        self.assertIsNone(sid)
        self.assertEqual(len(client.inserts), 1)

    def test_missing_traceability_column_on_rejudge_preserves_contest_id(self):
        client = _RetryUpdateClient("Could not find the 'tests_hash' column of "
                                    "'submissions' in the schema cache")
        with patch.object(server, "_sb", client):
            sid = asyncio.run(server._store_submission(
                {"problem": "p", "contest_id": "c1", "kind": "rejudge",
                 "tests_hash": "h", "job_id": "j1"}, target_id="sub-1"))
        self.assertEqual(sid, "rejudged")
        self.assertEqual(len(client.updates), 2)
        self.assertEqual(client.updates[1]["contest_id"], "c1")
        self.assertNotIn("tests_hash", client.updates[1])
        self.assertNotIn("job_id", client.updates[1])

    def test_missing_contest_id_on_contest_rejudge_fails_closed(self):
        client = _RetryUpdateClient("Could not find the 'contest_id' column of "
                                    "'submissions' in the schema cache")
        with patch.object(server, "_sb", client):
            sid = asyncio.run(server._store_submission(
                {"problem": "p", "contest_id": "c1", "kind": "rejudge"},
                target_id="sub-1"))
        self.assertIsNone(sid)
        self.assertEqual(len(client.updates), 1)

    def test_missing_contest_id_on_practice_rejudge_retries(self):
        client = _RetryUpdateClient("Could not find the 'contest_id' column of "
                                    "'submissions' in the schema cache")
        with patch.object(server, "_sb", client):
            sid = asyncio.run(server._store_submission(
                {"problem": "p", "contest_id": None, "kind": "rejudge"},
                target_id="sub-1"))
        self.assertEqual(sid, "rejudged")
        self.assertEqual(len(client.updates), 2)
        self.assertNotIn("contest_id", client.updates[1])

    def test_integrity_error_on_rejudge_is_not_retried(self):
        client = _RetryUpdateClient('null value in column "contest_id" of '
                                    'relation "submissions" violates not-null constraint')
        with patch.object(server, "_sb", client):
            sid = asyncio.run(server._store_submission(
                {"problem": "p", "contest_id": "c1", "kind": "rejudge"},
                target_id="sub-1"))
        self.assertIsNone(sid)
        self.assertEqual(len(client.updates), 1)


class SpawnFailureIsNeverAVerdict(unittest.TestCase):
    """Host exhaustion must end a job as an environment error, never a RE.

    The engine already refuses to score strict-sandbox refusals; a supervisor
    that cannot start the sandbox wrapper at all must follow the same contract.
    """

    def test_supervisor_marker_codes_stay_in_sync_with_the_engine(self):
        self.assertEqual(judge_runner.SPAWN_FAILED_RC, grader.SPAWN_FAILED_RC)
        self.assertEqual(judge_runner.SPAWN_FAILED_MARKER, grader.SPAWN_FAILED_MARKER)

    def test_unspawnable_wrapper_reports_the_marker_end_to_end(self):
        result = judge_runner.run_bounded(
            ["/nonexistent/newbiegrader-synthetic-binary"], "", 10,
            output_limit=65536, env=grader.judge_env())
        self.assertEqual(result.returncode, grader.SPAWN_FAILED_RC)
        self.assertIn(grader.SPAWN_FAILED_MARKER, result.stderr)

    def test_run_one_maps_the_marker_to_spawn_fail(self):
        fake = judge_runner.BoundedResult(
            "", f"[judge_runner] {grader.SPAWN_FAILED_MARKER}: synthetic",
            grader.SPAWN_FAILED_RC, "")
        with patch.object(judge_runner, "run_bounded", return_value=fake):
            res = grader.run_one(["/nonexistent/newbiegrader-synthetic-binary"], "", 3, 128)
        self.assertEqual(res["reason"], "spawn-fail")

    def test_judge_test_refuses_to_score_a_spawn_failure(self):
        prob = synthetic_problem()
        res = {"stdout": "", "stderr": "synthetic host failure", "wall": 0.0,
               "cpu": 0.0, "peak_mb": 0.0, "returncode": -1, "killed": False,
               "reason": "spawn-fail"}
        with patch.object(grader, "run_one", return_value=res):
            with self.assertRaises(grader.SandboxUnavailable):
                grader.judge_test([], prob.tests[0], prob, False, True)

    class _FakeProcess:
        pid = 12345

        def poll(self):
            return 0

        def kill(self):
            pass

        def wait(self):
            return 0

    def test_supervisor_setup_failure_reports_the_marker(self):
        """A pid-file write failure happens after Popen but before any user
        code. It must be an environment error, not exit code 1 scored as RE."""
        stderr = io.StringIO()
        with patch.object(judge_runner.os, "read", return_value=b"\0"), \
                patch.object(judge_runner.sys, "platform", "darwin"), \
                patch.object(judge_runner.signal, "signal"), \
                patch.object(judge_runner.subprocess, "Popen",
                             return_value=self._FakeProcess()), \
                patch.object(judge_runner.Path, "write_text",
                             side_effect=OSError("synthetic disk full")), \
                patch("sys.stderr", stderr):
            rc = judge_runner._supervise(["synthetic"], "/tmp/synthetic-pid",
                                         judge_runner.os.getpid())
        self.assertEqual(rc, judge_runner.SPAWN_FAILED_RC)
        self.assertIn(judge_runner.SPAWN_FAILED_MARKER, stderr.getvalue())

    def test_supervisor_handshake_failure_reports_the_marker(self):
        stderr = io.StringIO()
        with patch.object(judge_runner.os, "read", return_value=b""), \
                patch("sys.stderr", stderr):
            rc = judge_runner._supervise(["synthetic"], "/tmp/synthetic-pid",
                                         judge_runner.os.getpid())
        self.assertEqual(rc, judge_runner.SPAWN_FAILED_RC)
        self.assertIn(judge_runner.SPAWN_FAILED_MARKER, stderr.getvalue())

    def test_compile_spawn_failure_is_not_a_compile_error(self):
        """A host that cannot start the compiler must not mark the source CE."""
        fake = judge_runner.BoundedResult(
            "", f"[judge_runner] {grader.SPAWN_FAILED_MARKER}: synthetic",
            grader.SPAWN_FAILED_RC, "")
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(judge_runner, "run_bounded", return_value=fake):
            with self.assertRaises(grader.SandboxUnavailable):
                grader._compile(["/nonexistent/newbiegrader-synthetic-binary"], Path(tmp))

    def test_compile_spawn_oserror_is_not_a_compile_error(self):
        with tempfile.TemporaryDirectory() as tmp, \
                patch.object(judge_runner, "run_bounded",
                             side_effect=OSError("synthetic EAGAIN")):
            with self.assertRaises(grader.SandboxUnavailable):
                grader._compile(["/nonexistent/newbiegrader-synthetic-binary"], Path(tmp))
