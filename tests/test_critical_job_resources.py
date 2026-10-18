"""Synthetic control/gate regressions; real kernel tests are ec2_canaries.py."""
import asyncio
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch, AsyncMock, Mock

from critical_helpers import test_server
import job_resources as resources
import judge_runner

server = test_server()


class CriticalJobResources(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.root = self.base / "delegation"
        self.workspace = self.base / "workspace"
        self.root.mkdir()
        self.workspace.mkdir()
        self.patches = [patch.object(resources, "_ready", (self.root, self.workspace)),
                        patch.object(resources, "_active", False),
                        patch.object(resources, "_poisoned", False)]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)

    def test_critical_attachment_failure_does_not_execute_the_command(self):
        marker = self.base / "untrusted-ran"

        class Refuse:
            def attach(self, pid):
                raise resources.IsolationUnavailable("synthetic attach refusal")

        with self.assertRaises(resources.IsolationUnavailable):
            judge_runner.run_bounded(
                [sys.executable, "-c", f"open({str(marker)!r},'w').write('ran')"],
                "", 3, output_limit=1024, env={"PATH": os.defpath}, containment=Refuse())
        self.assertFalse(marker.exists())

    def test_critical_control_values_are_written_and_checked_before_attachment(self):
        def write(path, value):
            path.write_text(value)
        with patch.object(resources, "initialize"), \
                patch.object(resources, "_write", side_effect=write):
            boundary = resources.JobResources()
            boundary.create()
        self.assertEqual((boundary.group / "memory.max").read_text(), str(640 * resources.MIB))
        self.assertEqual((boundary.group / "memory.swap.max").read_text(), "0")
        self.assertEqual((boundary.group / "memory.oom.group").read_text(), "1")
        self.assertEqual((boundary.group / "pids.max").read_text(), "64")
        self.assertEqual((boundary.group / "cpu.max").read_text(), "100000 100000")
        self.assertEqual(boundary.workspace.stat().st_mode & 0o777, 0o755)

    def test_critical_control_write_or_readback_failure_refuses_setup(self):
        with patch.object(resources, "initialize"), \
                patch.object(resources, "_write", side_effect=OSError("read-only")):
            with self.assertRaises(OSError):
                resources.JobResources().create()
        with patch.object(resources, "initialize"), \
                patch.object(resources, "_write"), patch.object(resources, "_read", return_value="max"):
            with self.assertRaisesRegex(resources.IsolationUnavailable, "readback"):
                resources.JobResources().create()

    def test_critical_cleanup_failure_poison_prevents_next_claim(self):
        with patch.object(resources, "initialize"):
            boundary = resources.JobResources()
        boundary.group.mkdir()
        with patch.object(resources, "_empty_group", side_effect=OSError("synthetic kill failure")):
            with self.assertRaises(OSError):
                boundary.close()
        with patch.dict(os.environ, {"GRADER_REQUIRE_JOB_CGROUP": "1"}):
            with self.assertRaises(resources.IsolationUnavailable):
                resources.assert_healthy()

    def test_critical_job_scope_rejects_concurrent_workspace_users(self):
        with patch.dict(os.environ, {"GRADER_REQUIRE_JOB_CGROUP": "1"}), \
                patch.object(resources.JobResources, "create"), \
                patch.object(resources.JobResources, "close"), \
                patch.object(resources, "initialize"):
            with resources.job_scope():
                with self.assertRaises(resources.IsolationUnavailable):
                    with resources.job_scope():
                        self.fail("second job must not start")
            self.assertFalse(resources._active)

    def test_critical_global_cgroup_root_is_never_modified(self):
        with patch.dict(os.environ, {"GRADER_REQUIRE_JOB_CGROUP": "1", "GRADER_JOB_CGROUP_ROOT": "/sys/fs/cgroup"}), \
                patch.object(resources.sys, "platform", "linux"), \
                patch.object(resources.os, "geteuid", return_value=0), \
                patch.object(resources, "_private_directory"), \
                patch.object(resources, "_write") as write:
            with self.assertRaises(resources.IsolationUnavailable):
                resources.initialize()
        write.assert_not_called()

    def test_critical_ordinary_workspace_directory_is_not_a_quota(self):
        with patch.object(resources, "_private_directory"), \
                patch.object(Path, "read_text", return_value=f"1 0 0:1 / {self.workspace} rw - ext4 none rw\n"):
            with self.assertRaisesRegex(resources.IsolationUnavailable, "tmpfs"):
                resources._verify_workspace(self.workspace)

    def test_critical_disabled_cgroups_preserve_existing_runner_path(self):
        with patch.dict(os.environ, {"GRADER_REQUIRE_JOB_CGROUP": "0"}), \
                patch.object(resources, "initialize", side_effect=AssertionError("not needed")):
            with resources.job_scope() as boundary:
                self.assertIsNone(boundary)

    def test_critical_paused_admission_precedes_database_or_local_mutation(self):
        for mode in ("local", "database"):
            with self.subTest(mode=mode), patch.dict(os.environ, {"GRADER_ACCEPT_JOBS": "0"}), \
                    patch.object(server, "QUEUE_MODE", mode), \
                    patch.object(server, "_queue_rpc", new_callable=AsyncMock) as rpc, \
                    patch.object(server, "_remember_job") as remember:
                with self.assertRaises(server.HTTPException) as error:
                    asyncio.run(server._create_job({"user_email": "synthetic@example.invalid"}, track_active=False))
                self.assertEqual(error.exception.status_code, 503)
                rpc.assert_not_called()
                remember.assert_not_called()

    def test_critical_invalid_policy_flags_are_fail_closed(self):
        with patch.dict(os.environ, {"GRADER_REQUIRE_JOB_CGROUP": "maybe"}):
            with self.assertRaises(resources.IsolationUnavailable):
                resources.required()

    def test_critical_worker_preflight_does_not_claim_or_serve(self):
        import worker
        fake = Mock(validate_runtime=AsyncMock(), serve_workers=AsyncMock())
        with patch.dict(os.environ, {"GRADER_ROLE": "worker"}), \
                patch.dict(sys.modules, {"server": fake}):
            worker.main(["--check"])
        fake.validate_runtime.assert_awaited_once()
        fake.serve_workers.assert_not_called()

    def test_critical_missing_supervisor_capabilities_refuse_before_controls(self):
        with patch.dict(os.environ, {"GRADER_REQUIRE_JOB_CGROUP": "1"}), \
                patch.object(resources.sys, "platform", "linux"), \
                patch.object(resources.os, "geteuid", return_value=0), \
                patch.object(Path, "read_text", return_value="CapEff:\t000000000000006b\n"), \
                patch.object(resources, "_write") as write:
            with self.assertRaisesRegex(resources.IsolationUnavailable, "capabilities"):
                resources.initialize()
        write.assert_not_called()

    def test_critical_required_cgroups_are_checked_even_for_nonroot_worker(self):
        with patch.dict(os.environ, {"GRADER_ALLOW_UNISOLATED_JUDGE": "1", "GRADER_REQUIRE_NETNS": "0"}), \
                patch.object(server, "GRADER_ROLE", "worker"), \
                patch.object(server, "QUEUE_MODE", "database"), \
                patch.object(server.os, "geteuid", return_value=1000), \
                patch.object(resources, "initialize", side_effect=resources.IsolationUnavailable("requires root")), \
                patch.object(server, "_queue_rpc", new_callable=AsyncMock) as rpc:
            with self.assertRaisesRegex(resources.IsolationUnavailable, "root"):
                asyncio.run(server.validate_runtime())
        rpc.assert_not_called()
