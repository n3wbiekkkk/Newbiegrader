"""Synthetic-only helpers; never load .env, real problems, or a live database."""
from pathlib import Path
import os
from unittest.mock import patch

import grader


def synthetic_problem():
    with patch.object(grader, "PROBLEMS_DIR", Path(__file__).parent / "fixtures"):
        return grader.load_problem("security_canary")


def test_server():
    # server imports preload local problems. Point that loader away from the
    # developer's problem set, and disable dotenv/database initialization.
    with patch.dict(os.environ, {"GRADER_RUNNER_CHILD": "1",
                                "GRADER_PROBLEM_SOURCE": "local",
                                "SESSION_SECRET": "synthetic-critical-session-secret"}), \
            patch.object(grader, "PROBLEMS_DIR", Path(__file__).parent / "fixtures"):
        import server
    return server
