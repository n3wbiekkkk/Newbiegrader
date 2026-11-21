"""CI workflow contracts; no GitHub token, network or private data required."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools import check_ci_results, ci_changed_paths


REQUIRED_COMMANDS = (
    "pip-audit -r requirements.txt",
    "pip-audit -r deploy/host/requirements.lock",
    "python3 -m compileall -q",
    "node --check static/app.js",
    "node tools/check_frontend.js",
    "node tools/check_styles.js",
    "node --test tests/test_*.js",
    "python3 tools/validate_problem.py",
    "python3 -m unittest discover -s tests -p test_problem_authoring.py -v",
    "python3 tools/plagiarism.py",
    "python3 tools/check_test_environment.py",
    "python3 -m unittest discover -s tests -v",
    "docker build -t newbiegrader-ci .",
    "python tools/run_critical_tests.py",
    "psql -X -v ON_ERROR_STOP=1 -f supabase/schema.sql",
    "python3 tests/queue_concurrency.py",
)


def job_blocks(text):
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "jobs:")
    blocks = {}
    current = None
    for line in lines[start + 1:]:
        heading = re.match(r"^  ([A-Za-z0-9_-]+):\s*$", line)
        if heading:
            current = heading.group(1)
            blocks[current] = []
        elif current and line.startswith("    "):
            blocks[current].append(line)
    return blocks


class ChangedPaths(unittest.TestCase):
    def select(self, paths, event="pull_request"):
        return ci_changed_paths.select_groups(paths, event)

    def test_docs_only_change_keeps_the_fast_check_and_skips_the_rest(self):
        self.assertEqual(self.select(["README.md", "docs/guide.md"]), ["static"])

    def test_catalog_csv_is_not_treated_as_documentation_only(self):
        self.assertEqual(
            self.select(["docs/catalog/problem-numbers-2026-11-01.csv"]),
            ["static", "python"],
        )

    def test_frontend_change_runs_frontend_and_python_checks(self):
        groups = self.select(["static/app.js", "tests/test_job_polling.js"])
        self.assertEqual(groups, ["static", "python", "frontend", "image"])

    def test_critical_only_supports_trigger_security_checks(self):
        paths = [
            "tests/fake_supabase.py",
            "tools/import_problems_supabase.py",
            "tools/publish_problem_files.py",
            "tools/statement_build.py",
            "tools/validate_problem.py",
        ]
        for path in paths:
            with self.subTest(path=path):
                self.assertIn("security", self.select([path]))

    def test_dockerfile_change_runs_python_tests(self):
        self.assertIn("python", self.select(["Dockerfile"]))

    def test_database_related_python_change_runs_sql_checks(self):
        groups = self.select(["server.py"])
        self.assertIn("python", groups)
        self.assertIn("security", groups)
        self.assertIn("image", groups)
        self.assertIn("sql", groups)

    def test_workflow_change_selects_every_group(self):
        self.assertEqual(
            self.select([".github/workflows/ci.yml"]),
            list(ci_changed_paths.ALL_GROUPS),
        )

    def test_non_pull_request_events_select_every_group(self):
        for event in ("push", "merge_group", "workflow_dispatch"):
            with self.subTest(event=event):
                self.assertEqual(self.select(["README.md"], event), list(ci_changed_paths.ALL_GROUPS))

    def test_cli_writes_one_output_line_per_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "changed.txt"
            path.write_text("docs/guide.md\n", encoding="utf-8")
            result = subprocess.run(
                [sys.executable, str(ROOT / "tools/ci_changed_paths.py"),
                 "--files", str(path), "--event", "pull_request"],
                capture_output=True, text=True, check=False,
            )
        self.assertEqual(result.returncode, 0, result.stderr)
        outputs = dict(line.split("=", 1) for line in result.stdout.splitlines())
        self.assertEqual(json.loads(outputs["groups"]), ["static"])
        self.assertEqual(outputs["static"], "true")
        self.assertEqual(outputs["sql"], "false")


class AggregateResults(unittest.TestCase):
    def test_success_and_skipped_pass(self):
        results = {"changes": "success", "static": "success", "sql": "skipped"}
        self.assertEqual(
            check_ci_results.check_results(results, ["static", "sql"]), []
        )

    def test_failure_cancellation_and_missing_job_fail(self):
        results = {"changes": "success", "static": "failure", "sql": "cancelled"}
        errors = check_ci_results.check_results(results, ["static", "sql", "frontend"])
        self.assertTrue(any(error.startswith("static:") for error in errors))
        self.assertTrue(any(error.startswith("sql:") for error in errors))
        self.assertTrue(any("frontend: missing" in error for error in errors))

    def test_failed_selector_fails_the_aggregate(self):
        results = {"changes": "failure", "static": "success"}
        self.assertTrue(
            any("changes: failure" in error
                for error in check_ci_results.check_results(results, ["static"]))
        )

    def test_cli_uses_github_results_json(self):
        env = dict(os.environ)
        env["CI_RESULTS"] = json.dumps({"changes": {"result": "success"},
                                        "validate": {"result": "skipped"}})
        env["CI_EXPECTED_JOBS"] = "validate"
        result = subprocess.run(
            [sys.executable, str(ROOT / "tools/check_ci_results.py")],
            capture_output=True, text=True, env=env, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)


class WorkflowContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
        cls.jobs = job_blocks(cls.text)

    def test_trigger_and_permissions_keep_fork_pull_requests_read_only(self):
        self.assertIn("merge_group:", self.text)
        self.assertIn("pull_request:", self.text)
        self.assertNotIn("pull_request_target:", self.text)
        self.assertNotIn("secrets.", self.text)
        self.assertNotIn("continue-on-error", self.text)
        self.assertIn("permissions:\n  contents: read", self.text)

    def test_container_images_are_pinned_by_digest(self):
        self.assertRegex(self.text, r"python:3\.13-slim@sha256:[0-9a-f]{64}")
        self.assertRegex(self.text, r"postgres:17@sha256:[0-9a-f]{64}")
        self.assertNotIn("image: postgres:17\n", self.text)

    def test_container_job_uses_the_container_python(self):
        self.assertNotIn("uses: actions/setup-python", "\n".join(self.jobs["critical-security"]))

    def test_every_job_has_a_timeout(self):
        for name, block in self.jobs.items():
            with self.subTest(job=name):
                self.assertTrue(any("timeout-minutes:" in line for line in block))

    def test_every_checkout_drops_the_token(self):
        uses = len(re.findall(r"uses: actions/checkout@", self.text))
        self.assertGreater(uses, 0)
        self.assertEqual(self.text.count("persist-credentials: false"), uses)

    def test_all_original_checks_are_still_present(self):
        for command in REQUIRED_COMMANDS:
            with self.subTest(command=command):
                self.assertIn(command, self.text)

    def test_required_check_names_and_aggregate_are_preserved(self):
        for name in ("changes", "static-checks", "python-tests", "frontend-tests",
                     "image-checks", "validate", "critical-security", "queue-sql", "ci"):
            with self.subTest(job=name):
                self.assertIn(name, self.jobs)

    def test_leaf_jobs_are_gated_by_the_selector_outputs(self):
        expectations = {
            "static-checks": "needs.changes.outputs.static == 'true'",
            "python-tests": "needs.changes.outputs.python == 'true'",
            "frontend-tests": "needs.changes.outputs.frontend == 'true'",
            "image-checks": "needs.changes.outputs.image == 'true'",
        }
        for job, expression in expectations.items():
            with self.subTest(job=job):
                self.assertTrue(
                    any(expression in line for line in self.jobs[job]),
                    f"{job} must be gated by {expression}",
                )

    def test_aggregate_jobs_use_the_result_checker(self):
        self.assertEqual(self.text.count("tools/check_ci_results.py"), 2)


if __name__ == "__main__":
    unittest.main()
