"""Offline regressions for submission provenance and input boundaries."""
import asyncio
from unittest.mock import patch
import unittest

import grader
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
