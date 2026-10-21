"""Per-job Linux identities; only bounded synthetic processes and files."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from critical_helpers import test_server
from critical_helpers import synthetic_problem
import grader
import job_sandbox

server = test_server()


class CriticalJobIdentity(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not sys.platform.startswith("linux") or os.geteuid() != 0:
            reason = "[CRITICAL-SKIP] per-job identity checks require Linux/root"
            print(reason, file=sys.stderr, flush=True)
            raise unittest.SkipTest(reason)

    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.base = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.base.chmod(0o755)
        self.stack.enter_context(patch.object(tempfile, "tempdir", str(self.base)))
        self.stack.enter_context(patch.dict(os.environ, {
            "GRADER_SANDBOX_IDENTITY_DIR": str(self.base / "identity-state"),
            "GRADER_REQUIRE_NETNS": "0"}))

    def test_critical_overlapping_jobs_cannot_read_write_or_signal_each_other(self):
        victim_source = (
            'from pathlib import Path\nimport os,time\n'
            'Path("victim.pid").write_text(str(os.getpid()))\n'
            'deadline=time.monotonic()+8\n'
            'while not Path("release").exists() and time.monotonic()<deadline: time.sleep(.02)\n'
            'print("hello")\n')
        with ThreadPoolExecutor(max_workers=1) as executor:
            victim = executor.submit(server._run_playground, None, ".py", victim_source, "", 10, 128)
            deadline = time.monotonic() + 5
            pid_file = None
            while time.monotonic() < deadline:
                found = list(self.base.glob("webrun_*/victim.pid"))
                if found and found[0].read_text():
                    pid_file = found[0]
                    break
                if victim.done():
                    self.fail(f"synthetic victim exited before handshake: {victim.result()}")
                time.sleep(.02)
            self.assertIsNotNone(pid_file, "synthetic victim did not start")
            victim_path = pid_file.parent / "solution.py"
            victim_uid = victim_path.stat().st_uid
            victim_pid = int(pid_file.read_text())
            source = (
                'from pathlib import Path\nimport os,json\n'
                f'p=Path({str(victim_path)!r})\n'
                'result={"uid":os.getuid(),"gid":os.getgid()}\n'
                'for name,operation in [("read",lambda:p.read_text()),'
                '("write",lambda:p.write_text("SYNTHETIC_TAMPER")),'
                f'("signal",lambda:os.kill({victim_pid},0))]:\n'
                ' try: operation();result[name]=True\n'
                ' except PermissionError: result[name]=False\n'
                'print(json.dumps(result))\n')
            try:
                attacker = server._run_playground(None, ".py", source, "", 5, 128)
                self.assertEqual(attacker["verdict"], "OK", attacker)
                result = json.loads(attacker["stdout"])
                self.assertEqual({k: result[k] for k in ("read", "write", "signal")},
                                 {"read": False, "write": False, "signal": False})
                self.assertNotEqual(victim_uid, result["uid"])
                self.assertNotEqual(victim_uid, result["gid"])
                self.assertEqual(victim_path.read_text(), victim_source)
            finally:
                (pid_file.parent / "release").touch()
            self.assertEqual(victim.result(timeout=5)["stdout"], "hello\n")

    def test_critical_world_readable_files_and_shared_tmp_writes_are_denied(self):
        outside = self.base / "synthetic-shared"
        outside.mkdir(mode=0o777)
        outside.chmod(0o777)
        canary = outside / "synthetic-public-canary"
        canary.write_text("SYNTHETIC_PUBLIC_CANARY")
        canary.chmod(0o666)
        source = (
            'from pathlib import Path\nimport json,os\n'
            f'p=Path({str(canary)!r})\n'
            'Path("own-file").write_text("own data")\n'
            'Path("alias").symlink_to(p)\n'
            'result={}\n'
            'for name,operation in [("read",lambda:p.read_text()),'
            '("write",lambda:p.write_text("tampered")),'
            '("symlink",lambda:Path("alias").read_text()),'
            f'("create",lambda:Path({str(outside / "new-file")!r}).write_text("outside"))]:\n'
            ' try: operation();result[name]=True\n'
            ' except PermissionError: result[name]=False\n'
            'print(json.dumps(result))\n')
        result = server._run_playground(None, ".py", source, "", 5, 128)
        self.assertEqual(result["verdict"], "OK", result)
        self.assertEqual(json.loads(result["stdout"]),
                         {"read": False, "write": False, "symlink": False, "create": False})
        self.assertEqual(canary.read_text(), "SYNTHETIC_PUBLIC_CANARY")
        self.assertFalse((outside / "new-file").exists())

    def test_critical_compiler_cannot_include_world_readable_files_outside_job(self):
        canary = self.base / "synthetic-public.h"
        marker = "SYNTHETIC_PUBLIC_HEADER_CANARY"
        canary.write_text(f'#error {marker}\n')
        canary.chmod(0o644)
        for ext in (".c", ".cpp"):
            with self.subTest(language=ext):
                result = server.run_submission(synthetic_problem(), ext,
                    f'#include "{canary}"\nint main(void){{return 0;}}\n')
                self.assertEqual(result.get("verdict"), "CE", result)
                self.assertNotIn(marker, json.dumps(result))
                self.assertIn("Permission denied", result["compile_error"])

    def test_critical_parallel_tests_use_one_identity_and_private_temp_directory(self):
        prob = synthetic_problem()
        source = ('import os,tempfile\n'
                  'assert os.getuid()>=1000000 and os.getgid()==os.getuid()\n'
                  'assert tempfile.gettempdir()==os.getcwd()\n'
                  'with tempfile.TemporaryFile() as f: f.write(b"synthetic")\n'
                  'print("hello")\n')
        with patch.object(server, "JUDGE_JOBS", 2):
            result = server.run_submission(prob, ".py", source)
        self.assertTrue(result.get("accepted"), result)

    def test_critical_identity_store_failure_is_a_job_error(self):
        with patch.dict(os.environ, {"GRADER_SANDBOX_IDENTITY_DIR": str(self.base)}):
            result = server._run_playground(None, ".py", 'print("UNTRUSTED_RAN")', "", 5, 128)
        self.assertEqual(result, {"error": "execution environment unavailable"})

    def test_critical_uid_ledger_is_shared_across_processes_and_never_reuses(self):
        from judge_runner import run_bounded
        # Trusted root allocator probes, not submissions; never pass secrets.
        code = ('import job_sandbox,json\n'
                'with job_sandbox.scope(): print(json.dumps(job_sandbox.identity()))\n')
        env = grader.judge_env() | {"GRADER_SANDBOX_IDENTITY_DIR": str(self.base / "identity-state")}
        def allocate(_):
            result = run_bounded([sys.executable, "-c", code], "", 10,
                                 output_limit=4096, env=env, cwd=str(grader.ROOT))
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout)[0]
        with ThreadPoolExecutor(max_workers=4) as executor:
            allocated = list(executor.map(allocate, range(8)))
        self.assertEqual(len(set(allocated)), 8)
        later = allocate(0)  # fresh process, persisted state
        self.assertGreater(later, max(allocated))

    def test_critical_partial_ledger_and_state_symlinks_fail_closed(self):
        directory = self.base / "identity-state"
        directory.mkdir(mode=0o700)
        ledger = directory / "allocated-uids"
        ledger.write_text("1000000\n1000")
        ledger.chmod(0o600)
        with job_sandbox.scope(), self.assertRaises(OSError):
            job_sandbox.identity()
        ledger.unlink()
        canary = self.base / "root-canary"
        canary.write_text("1000000\n")
        canary.chmod(0o600)
        ledger.symlink_to(canary)
        with job_sandbox.scope(), self.assertRaises(OSError):
            job_sandbox.identity()
        self.assertEqual(canary.read_text(), "1000000\n")

    def test_critical_missing_landlock_refuses_before_exec(self):
        from judge_runner import run_bounded
        code = (
            'from unittest.mock import patch\nimport grader,job_sandbox\n'
            'with job_sandbox.launch_scope(), patch.object(job_sandbox,"landlock_abi",side_effect=OSError("synthetic unavailable")):\n'
            ' grader.build_limits(0,5,network=False)()\n'
            ' print("UNTRUSTED_RAN")\n')
        with job_sandbox.scope():
            workdir = self.base / "job"
            workdir.mkdir()
            grader.prepare_workspace(workdir)
            result = run_bounded([sys.executable, "-c", code], "", 10,
                                 output_limit=4096, env=grader.judge_env(str(workdir)),
                                 cwd=str(grader.ROOT))
        self.assertEqual(result.returncode, grader.PRIVILEGE_REFUSED_RC)
        self.assertIn(grader.PRIVILEGE_REFUSED_MARKER, result.stderr)
        self.assertNotIn("UNTRUSTED_RAN", result.stdout)

    def test_critical_compile_runtime_and_descendants_share_only_their_job_identity(self):
        canary = self.base / "synthetic-public-file"
        canary.write_text("SYNTHETIC_OUTSIDE")
        canary.chmod(0o644)
        probe = ('import os,json\n'
                 f'target={str(canary)!r}\n'
                 'try: open(target).close();outside=True\n'
                 'except PermissionError: outside=False\n'
                 'print(json.dumps([os.getuid(),os.getgid(),os.getgroups(),outside]))\n')
        source = ('import subprocess,sys\n' + probe +
                  f'subprocess.run([sys.executable,"-c",{probe!r}],check=True)\n')
        with job_sandbox.scope():
            workspace = self.base / "synthetic-job"
            workspace.mkdir()
            script = workspace / "solution.py"
            script.write_text(source)
            grader.prepare_workspace(workspace, script)
            uid, gid = grader.sandbox_identity()
            compiled = grader._compile([sys.executable, str(script)], workspace)
            executed = grader.run_one([sys.executable, str(script)], "", 5, 128, "python")
        self.assertEqual(compiled.returncode, 0, compiled.stderr)
        self.assertEqual(executed["returncode"], 0, executed)
        expected = [uid, gid, [], False]
        for stdout in (compiled.stdout, executed["stdout"]):
            self.assertEqual([json.loads(line) for line in stdout.splitlines()], [expected, expected])

    def test_critical_fsync_failure_never_publishes_an_identity(self):
        with patch.object(job_sandbox.os, "fsync", side_effect=OSError("synthetic fsync failure")):
            result = server._run_playground(None, ".py", 'print("UNTRUSTED_RAN")', "", 5, 128)
        self.assertEqual(result, {"error": "execution environment unavailable"})

    def test_critical_isolated_runner_preserves_the_trusted_identity_store_setting(self):
        from judge_runner import _runner_env
        self.assertEqual(_runner_env()["GRADER_SANDBOX_IDENTITY_DIR"],
                         os.environ["GRADER_SANDBOX_IDENTITY_DIR"])

    def test_critical_missing_landlock_blocks_worker_boot_even_when_network_is_acknowledged(self):
        with patch.object(job_sandbox, "landlock_abi", side_effect=OSError("synthetic unavailable")), \
                patch.object(server, "GRADER_ROLE", "combined"), \
                patch.object(server, "QUEUE_MODE", "local"), \
                patch.object(server, "PROBLEM_SOURCE", "local"), \
                patch.dict(os.environ, {"GRADER_ALLOW_UNISOLATED_JUDGE": "1"}):
            with self.assertRaisesRegex(RuntimeError, "Landlock ABI"):
                asyncio.run(server.validate_runtime())
