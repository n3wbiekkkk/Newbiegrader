# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Synthetic read-only preflight tests; candidate status is never enforcement."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools.check_job_resource_host import inspect_host


class CriticalResourceHost(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name).resolve()
        self.root = self.base / "cgroup"
        self.root.mkdir()
        self.mountinfo = self.base / "mountinfo"
        for name, value in (("cgroup.controllers", "cpu memory pids io"),
                            ("cgroup.subtree_control", "cpu memory pids"),
                            ("cgroup.procs", "")):
            (self.root / name).write_text(value)
        self.mount()

    def mount(self, options="rw", filesystem="cgroup2"):
        self.mountinfo.write_text(f"1 0 0:1 / {self.root} {options} - {filesystem} none rw\n")

    def inspect(self):
        return inspect_host(self.root, mountinfo=self.mountinfo, platform="linux")

    def test_critical_read_only_mount_blocks_even_when_superblock_is_writable(self):
        self.mount("ro,nosuid,nodev,noexec")
        with patch("tools.check_job_resource_host.os.access", return_value=True):
            result = self.inspect()
        self.assertEqual(result["status"], "HOST_BLOCKED")
        self.assertIn("cgroup mount is read-only", result["blockers"])

    def test_critical_empty_subtree_does_not_mean_controllers_are_enabled(self):
        (self.root / "cgroup.subtree_control").write_text("")
        result = self.inspect()
        self.assertIn("cpu/memory/pids controllers are not all enabled", result["blockers"])

    def test_critical_missing_controller_or_unreadable_state_blocks(self):
        (self.root / "cgroup.controllers").write_text("cpu pids")
        (self.root / "cgroup.procs").unlink()
        result = self.inspect()
        self.assertIn("cpu/memory/pids controllers are not all available", result["blockers"])
        self.assertFalse(result["delegation_empty"])

    def test_critical_populated_parent_or_denied_access_blocks(self):
        (self.root / "cgroup.procs").write_text("123\n")
        with patch("tools.check_job_resource_host.os.access", return_value=False):
            result = self.inspect()
        self.assertFalse(result["delegation_empty"])
        self.assertFalse(result["delegation_access_check"])
        self.assertEqual(len(result["blockers"]), 2)

    def test_critical_regular_directory_cannot_masquerade_as_delegation(self):
        self.mount(filesystem="ext4")
        self.assertEqual(self.inspect()["status"], "HOST_BLOCKED")

    def test_critical_most_specific_mount_controls_read_only_status(self):
        self.mount("ro")
        with self.mountinfo.open("a") as stream:
            stream.write("2 0 0:2 / / rw - ext4 none rw\n")
        self.assertTrue(self.inspect()["mount_read_only"])

    def test_critical_candidate_is_not_verified_job_or_workspace_enforcement(self):
        before = {p.name: p.read_bytes() for p in self.root.iterdir()}
        with patch("tools.check_job_resource_host.os.access", return_value=True):
            result = self.inspect()
        self.assertEqual(result["status"], "HOST_CANDIDATE_ENFORCEMENT_UNVERIFIED")
        self.assertFalse(result["job_enforcement_verified"])
        self.assertFalse(result["workspace_enforcement_verified"])
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.iterdir()})

    def test_critical_non_linux_and_symlink_are_explicitly_blocked(self):
        result = inspect_host(self.root, mountinfo=self.mountinfo, platform="darwin")
        self.assertEqual(result["status"], "HOST_BLOCKED")
        link = self.base / "link"
        link.symlink_to(self.root, target_is_directory=True)
        result = inspect_host(link, mountinfo=self.mountinfo, platform="linux")
        self.assertIn("canonical absolute directory", result["blockers"][0])
