#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Read-only S04 host preflight; never enables controllers or moves processes.

Exit 2 means host prerequisites are blocked. Exit 0 means a candidate delegation
only: no per-job enforcement, workload or workspace quota has been verified.
The command never reads environment values, user files or submission data.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

REQUIRED = frozenset({"cpu", "memory", "pids"})


def _mount_path(value: str) -> Path:
    for code, character in (("\\040", " "), ("\\011", "\t"),
                            ("\\012", "\n"), ("\\134", "\\")):
        value = value.replace(code, character)
    return Path(value)


def _read(path: Path) -> str | None:
    try:
        with path.open(encoding="ascii") as stream:
            value = stream.read(4097)
        return value.strip() if len(value) <= 4096 else None
    except (OSError, UnicodeError):
        return None


def inspect_host(root: Path = Path("/sys/fs/cgroup"), *,
                 mountinfo: Path = Path("/proc/self/mountinfo"),
                 platform: str = sys.platform) -> dict:
    report = {"status": "HOST_BLOCKED", "blockers": [],
              "job_enforcement_verified": False,
              "workspace_enforcement_verified": False}
    blocked = report["blockers"]
    if not platform.startswith("linux"):
        blocked.append("Linux cgroup v2 is required")
        return report
    if not root.is_absolute() or root.resolve() != root or not root.is_dir():
        blocked.append("cgroup root must be an existing canonical absolute directory")
        return report
    try:
        mounts = []
        for line in mountinfo.read_text().splitlines():
            left, right = line.split(" - ", 1)
            fields = left.split()
            path = _mount_path(fields[4])
            if root == path or path in root.parents:
                mounts.append((len(path.parts), fields[5].split(","), right.split()[0]))
        if not mounts:
            raise ValueError("mount unavailable")
        _, options, filesystem = max(mounts, key=lambda item: item[0])
    except (OSError, ValueError, IndexError):
        blocked.append("cannot identify cgroup mount")
        return report
    report["filesystem"] = filesystem
    report["mount_read_only"] = "ro" in options
    if filesystem != "cgroup2":
        blocked.append("selected path is not on cgroup v2")
        return report
    if "ro" in options:
        blocked.append("cgroup mount is read-only")
    controllers = _read(root / "cgroup.controllers")
    enabled = _read(root / "cgroup.subtree_control")
    for label, value in (("available", controllers), ("enabled", enabled)):
        report[f"required_controllers_{label}"] = sorted(REQUIRED & set((value or "").split()))
        if value is None or not REQUIRED <= set(value.split()):
            blocked.append(f"cpu/memory/pids controllers are not all {label}")
    processes = _read(root / "cgroup.procs")
    report["delegation_empty"] = processes == ""
    if processes != "":
        blocked.append("delegated parent is populated or unreadable")
    writable = all(os.access(path, os.W_OK) for path in (
        root, root / "cgroup.procs", root / "cgroup.subtree_control"))
    report["delegation_access_check"] = writable
    if not writable:
        blocked.append("delegation directory/control files are not writable")
    if not blocked:
        report["status"] = "HOST_CANDIDATE_ENFORCEMENT_UNVERIFIED"
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cgroup-root", type=Path, default=Path("/sys/fs/cgroup"))
    args = parser.parse_args()
    report = inspect_host(args.cgroup_root)
    print(json.dumps(report, sort_keys=True))
    return 2 if report["blockers"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
