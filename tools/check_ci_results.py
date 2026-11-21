#!/usr/bin/env python3
"""Fail an aggregate CI job when one of its required jobs failed or vanished.

GitHub passes the dependency results as JSON through CI_RESULTS. A skipped job
is accepted because path filtering can legitimately remove work from a pull
request. A cancelled or failed job is never accepted.
"""
import json
import os
import sys

ACCEPTED_RESULTS = {"success", "skipped"}


def check_results(results, expected_jobs, primary_job="changes"):
    """Return the errors a reader of the aggregate check needs to see."""
    expected = list(dict.fromkeys([primary_job, *expected_jobs]))
    errors = []

    for job in expected:
        if job not in results:
            errors.append(f"{job}: missing from dependency results")

    if primary_job in results and results[primary_job] != "success":
        errors.append(f"{primary_job}: {results[primary_job]}")

    for job in expected:
        result = results.get(job)
        if result is not None and job != primary_job and result not in ACCEPTED_RESULTS:
            errors.append(f"{job}: {result}")

    return errors


def main():
    expected_jobs = [
        name.strip()
        for name in os.environ.get("CI_EXPECTED_JOBS", "").split(",")
        if name.strip()
    ]
    primary_job = os.environ.get("CI_PRIMARY_JOB", "changes")

    try:
        raw = json.loads(os.environ.get("CI_RESULTS", ""))
    except json.JSONDecodeError as exc:
        print(f"CI_RESULTS is not valid JSON: {exc}", file=sys.stderr)
        return 1

    results = {
        name: value.get("result")
        for name, value in raw.items()
        if isinstance(value, dict) and isinstance(value.get("result"), str)
    }
    errors = check_results(results, expected_jobs, primary_job)
    if errors:
        for error in errors:
            print(f"[CI-FAIL] {error}", file=sys.stderr)
        return 1

    print("[CI-PASS] " + ", ".join(f"{name}={results[name]}" for name in results))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
