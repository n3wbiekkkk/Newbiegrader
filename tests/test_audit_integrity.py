"""Offline regressions for submission provenance and input boundaries."""
import asyncio
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
