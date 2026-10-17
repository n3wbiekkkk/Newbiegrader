"""Synthetic-only helpers; never load .env, real problems, or a live database."""
from pathlib import Path
import os
from unittest.mock import patch

import grader


def synthetic_problem():
    return grader.Problem(
        "security_canary", "Synthetic security canary", 3.0, 128,
        "token", 1e-6, "Synthetic fixture only",
        [grader.TestCase("01", "public-input\n", "hello\n"),
         grader.TestCase("1001", "synthetic-hidden-input\n", "hello\n")],
        samples=["01"])


def test_server():
    # server imports preload local problems. Point that loader away from the
    # developer's problem set, and disable dotenv/database initialization.
    with patch.dict(os.environ, {"GRADER_RUNNER_CHILD": "1",
                                "GRADER_PROBLEM_SOURCE": "local",
                                "SESSION_SECRET": "synthetic-critical-session-secret"}), \
            patch.object(grader, "PROBLEMS_DIR", Path(__file__).parent / "fixtures"):
        import server
    return server
