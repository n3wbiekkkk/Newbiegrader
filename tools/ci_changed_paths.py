#!/usr/bin/env python3
"""Select CI check groups from the files changed in a pull request.

The workflow writes changed paths to a text file, then this script prints one
GITHUB_OUTPUT line. It reads no repository state and contacts no network.
"""
import argparse
import fnmatch
import json
from pathlib import Path
import sys

ALL_GROUPS = ("static", "python", "frontend", "image", "security", "sql")

SQL_ROOT_FILES = frozenset({
    "account_deletion.py",
    "backend_problem_files.py",
    "database_client.py",
    "email_auth.py",
    "judge_lifecycle.py",
    "problem_catalog.py",
    "problem_store.py",
    "server.py",
    "submission_disclosure.py",
    "worker.py",
    "worker_fleet.py",
})

DOCUMENTATION_PATTERNS = (
    "docs/*",
    "README.md",
    "CONTRIBUTING.md",
    "GLOSSARY.md",
    "LICENSE",
    "SECURITY.md",
    ".github/ISSUE_TEMPLATE/*",
    ".github/PULL_REQUEST_TEMPLATE.md",
)

CATALOG_PATTERNS = ("docs/catalog/*",)

FORCE_ALL_PATTERNS = (
    ".github/workflows/*",
    "tools/ci_changed_paths.py",
    "tools/check_ci_results.py",
)

RULES = {
    "python": (
        "Dockerfile",
        "tools/*",
        "tests/*.py",
        "requirements.txt",
        "deploy/host/*",
        "supabase/*",
        "static/*",
        "functions/*",
        "docs/catalog/*",
    ),
    "frontend": (
        "static/*",
        "functions/*",
        "deploy/host/cloudflare/worker.js",
        "tools/check_frontend.js",
        "tools/check_styles.js",
        "tests/*.js",
    ),
    "image": (
        "Dockerfile",
        ".dockerignore",
        "requirements.txt",
        "static/*",
        "tools/plagiarism.py",
    ),
    "security": (
        "Dockerfile",
        "requirements.txt",
        "deploy/host/smoke_https.py",
        "deploy/host/fleet_snapshot.py",
        "static/_headers",
        "tools/run_critical_tests.py",
        "tools/host_*",
        "tools/import_problems_supabase.py",
        "tools/publish_problem_files.py",
        "tools/statement_build.py",
        "tools/validate_problem.py",
        "tools/check_job_resource_host.py",
        "tools/verify_backend_problem_files.py",
        "tests/critical_helpers.py",
        "tests/fake_supabase.py",
        "tests/test_critical_*.py",
        "tests/test_judge_runner.py",
        "tests/test_queue_admission.py",
        "tests/test_audit_integrity.py",
        "tests/test_contest_policy_audit.py",
        "tests/test_request_boundaries.py",
        "tests/test_auth_retention_audit.py",
        "tests/test_solutions.py",
        "tests/test_optimization_review.py",
    ),
    "sql": (
        "supabase/*",
        "tests/*.sql",
        "tests/account_*.py",
        "tests/auth_*.py",
        "tests/session_*.py",
        "tests/queue_*.py",
        "deploy/host/reconcile_account_restore.py",
    ),
}


def matches(path, patterns):
    return any(fnmatch.fnmatchcase(path, pattern) for pattern in patterns)


def select_groups(changed_paths, event_name):
    """Return the ordered check groups for one event and its changed paths."""
    if event_name != "pull_request":
        return list(ALL_GROUPS)

    normalized = [path.strip() for path in changed_paths if path.strip()]
    paths = sorted({path[2:] if path.startswith("./") else path for path in normalized})
    if not paths or any(matches(path, FORCE_ALL_PATTERNS) for path in paths):
        return list(ALL_GROUPS)

    docs_only = all(
        matches(path, DOCUMENTATION_PATTERNS)
        and not matches(path, CATALOG_PATTERNS)
        for path in paths
    )
    if docs_only:
        return ["static"]

    groups = ["static"]
    root_python = any("/" not in path and path.endswith(".py") for path in paths)

    for group in ALL_GROUPS[1:]:
        triggered = any(matches(path, RULES[group]) for path in paths)
        if group == "python":
            triggered = triggered or root_python
        if group == "image":
            triggered = triggered or root_python
        if group == "security":
            triggered = triggered or root_python
        if group == "sql":
            triggered = triggered or any(path in SQL_ROOT_FILES for path in paths)
        if triggered:
            groups.append(group)

    return groups


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--files", required=True, help="text file with one changed path per line")
    parser.add_argument("--event", required=True, help="GitHub event name")
    args = parser.parse_args(argv)

    content = Path(args.files).read_text(encoding="utf-8")
    groups = select_groups(content.splitlines(), args.event)
    print("groups=" + json.dumps(groups, separators=(",", ":")))
    for group in ALL_GROUPS:
        print(f"{group}={'true' if group in groups else 'false'}")
    print("CI groups: " + ", ".join(groups), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
