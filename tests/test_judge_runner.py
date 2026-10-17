"""Real process regressions for the execution boundary and output collector."""
import asyncio
import ctypes
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

import grader
from critical_helpers import synthetic_problem


def process_alive(pid):
    if os.name == "nt":
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        try:
            code = ctypes.c_ulong()
            kernel.GetExitCodeProcess(ctypes.c_void_p(handle), ctypes.byref(code))
            return code.value == 259
        finally:
            kernel.CloseHandle(ctypes.c_void_p(handle))
    try:
        os.kill(pid, 0)
        stat = Path(f"/proc/{pid}/stat")
        return not stat.exists() or stat.read_text().rsplit(")", 1)[1].split()[0] != "Z"
    except ProcessLookupError:
        return False


class OutputCollectionTests(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "needs Linux subreaper + prctl(PDEATHSIG)")
    def test_owner_death_terminates_the_owned_job(self):
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o777)
            marker = Path(tmp) / "pid"
            command = [sys.executable, "-c", "import os, time; "
                       f"open({str(marker)!r}, 'w').write(str(os.getpid())); time.sleep(60)"]
            parent = subprocess.Popen([sys.executable, "-c",
                "from judge_runner import run_bounded; import grader; "
                f"run_bounded({command!r}, '', 60, output_limit=32768, env=grader.judge_env())"],
                stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 10
                while not marker.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(marker.exists(), "owner failed to launch the job")
                pid = int(marker.read_text())
                parent.kill()  # An abrupt death cannot run Python finally blocks.
                parent.communicate(timeout=5)
                deadline = time.monotonic() + 5
                while process_alive(pid) and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertFalse(process_alive(pid), "job survived the owner's death")
            finally:
                if parent.poll() is None:
                    parent.kill()
                parent.communicate(timeout=5)

    def test_stdout_is_stopped_during_collection(self):
        # Removing the live output ceiling would collect a megabyte and report OK.
        with patch.object(grader, "OUTPUT_LIMIT_BYTES", 32768):
            result = grader.run_one(
                [sys.executable, "-c", "import os\nwhile True: os.write(1, b'x' * 8192)"],
                "", 3, 256)
        self.assertEqual(result["reason"], "ole")
        self.assertLessEqual(len(result["stdout"].encode()), 32768)

    def test_stderr_is_stopped_during_collection(self):
        # stderr must have the same live bound as stdout, even on exit code zero.
        with patch.object(grader, "OUTPUT_LIMIT_BYTES", 32768):
            result = grader.run_one(
                [sys.executable, "-c", "import os; os.write(2, b'x' * 1000000)"],
                "", 10, 256)
        self.assertEqual(result["reason"], "ole")
        self.assertLessEqual(len(result["stderr"].encode()), 32768)

    @unittest.skipUnless(shutil.which("gcc"), "gcc required")
    def test_compiler_diagnostics_are_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "solution.c"
            src.write_text(("#warning " + "x" * 512 + "\n") * 500 + "int main(void) {return 0;}\n")
            env = grader.judge_env() | {"TEMP": tmp, "TMP": tmp}
            with patch.object(grader, "OUTPUT_LIMIT_BYTES", 32768), patch.object(grader, "judge_env", return_value=env):
                with self.assertRaises(grader.CompileError) as raised:
                    grader.prepare_command(src, Path(tmp))
        self.assertLessEqual(len(str(raised.exception).encode()), 33000)

    def test_compile_deadline_kills_compiler_descendants(self):
        # Exercise the shared compiler path with a compiler subprocess that hangs.
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "pid"
            source = Path(tmp) / "compiler.py"
            source.write_text(
                "import os, subprocess, sys, time\n"
                "p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], "
                "start_new_session=(os.name == 'posix'))\n"
                f"open({str(marker)!r}, 'w').write(str(p.pid))\n"
                "time.sleep(60)\n")
            with patch.object(grader, "COMPILE_TIMEOUT", 1):
                with self.assertRaises(grader.CompileError):
                    grader._compile([sys.executable, str(source)], Path(tmp))
            self.assertTrue(marker.exists(), "compiler did not reach its subprocess")
            self.assertFalse(process_alive(int(marker.read_text())))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux RLIMIT semantics")
    def test_sandbox_preserves_memory_and_process_limits(self):
        result = grader.run_one([sys.executable, "-c",
                                "import json, resource; print(json.dumps(["
                                "resource.getrlimit(resource.RLIMIT_AS)[0],"
                                "resource.getrlimit(resource.RLIMIT_NPROC)[0],"
                                "resource.getrlimit(resource.RLIMIT_FSIZE)[0],"
                                "resource.getrlimit(resource.RLIMIT_NOFILE)[0]]))"], "", 3, 128)
        self.assertEqual(result["reason"], "")
        self.assertEqual(result["stdout"].strip(), "[134217728, 64, 67108864, 64]")

    @unittest.skipUnless(os.name == "posix", "POSIX signal return codes")
    def test_supervisor_preserves_signal_verdict_classification(self):
        result = grader.run_one([sys.executable, "-c", "import os, signal; os.kill(os.getpid(), signal.SIGKILL)"],
                               "", 3, 128)
        self.assertEqual(result["reason"], "sigkill")

    def test_strict_refusal_marker_maps_to_sandbox_unavailable(self):
        # Fail-closed plumbing, platform-independent: a wrapper that exits
        # 126 with the marker (strict netns refusal) must surface as
        # reason "sandbox-unavailable", never as a verdict.
        from judge_runner import BoundedResult
        fake = BoundedResult(stdout="", stderr="[grader] FATAL: boom (GRADER_REQUIRE_NETNS=1); refusing",
                             returncode=126, reason="")
        with patch("judge_runner.run_bounded", return_value=fake):
            result = grader.run_one([sys.executable, "-c", "print(1)"], "", 3, 128)
        self.assertEqual(result["reason"], "sandbox-unavailable")
        # ...and judge_test must raise instead of scoring it.
        prob = synthetic_problem()
        with patch("judge_runner.run_bounded", return_value=fake):
            with self.assertRaises(grader.SandboxUnavailable):
                grader.judge_test([sys.executable, "-c", "print(1)"],
                                  prob.tests[0], prob, False, False, None)
        # An ordinary exit-126 WITHOUT the marker stays a plain RE, not refusal.
        plain = BoundedResult(stdout="", stderr="oops", returncode=126, reason="")
        with patch("judge_runner.run_bounded", return_value=plain):
            result = grader.run_one([sys.executable, "-c", "print(1)"], "", 3, 128)
        self.assertNotEqual(result["reason"], "sandbox-unavailable")

    @unittest.skipUnless(sys.platform.startswith("linux") and os.geteuid() == 0,
                         "needs Linux + root for the real namespace path")
    def test_strict_netns_refuses_without_namespace(self):
        # End-to-end security invariant under GRADER_REQUIRE_NETNS=1: either
        # execution is refused before user code starts (hosts where unshare
        # fails, e.g. stock Docker), or the namespace exists and the socket
        # is denied. Unrestricted egress must never happen.
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o777)  # judged child runs as nobody: needs write access
            canary = Path(tmp) / "ran"
            code = (f"open({str(canary)!r}, 'w').write('x')\n"
                    "import socket\n"
                    "try:\n"
                    " socket.create_connection(('8.8.8.8', 53), timeout=5).close()\n"
                    " print('EGRESS-OPEN')\n"
                    "except Exception:\n"
                    " print('EGRESS-DENIED')\n")
            prob = synthetic_problem()
            tc = prob.tests[0]
            with patch.dict(os.environ, {"GRADER_REQUIRE_NETNS": "1"}):
                try:
                    verdict, _w, _c, _m, _e, actual = grader.judge_test(
                        [sys.executable, "-c", code], tc, prob,
                        False, False, None)
                except grader.SandboxUnavailable:
                    verdict, actual = "REFUSED", ""
            if verdict == "REFUSED":
                self.assertFalse(canary.exists(), "user code ran despite refusal")
            else:
                # Namespace was created (e.g. caps/userns host): the connect
                # attempt must then fail fast, so the verdict is WA with the
                # denial printed — never AC, never EGRESS-OPEN.
                self.assertNotEqual(verdict, "AC")
                self.assertIn("EGRESS-DENIED", actual,
                              "namespace exists but egress was allowed")
        # Default mode is unchanged: same program executes (and fails open,
        # which is why strict mode exists for public hosts).
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("GRADER_REQUIRE_NETNS", None)
            result = grader.run_one([sys.executable, "-c", "print('hi')"], "", 3, 128)
        self.assertEqual(result["stdout"].strip(), "hi")


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    def runner(self):
        if importlib.util.find_spec("judge_runner") is None:
            self.fail("the supervised execution boundary is missing")
        from judge_runner import run_isolated
        return run_isolated

    def payload(self, source):
        return {"problem": None, "ext": ".py", "source": source,
                "stdin_data": "", "time_limit": 30, "memory_mb": 256,
                "memory_cap_mb": 256, "judge_jobs": 1}

    async def wait_file(self, path):
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if path.exists() and path.stat().st_size:
                return
            await asyncio.sleep(.02)
        self.fail("child did not start")

    def descendant_source(self, path, exit_parent=False):
        # A different session defeats killpg-only cleanup on POSIX.
        child = "import time; time.sleep(60)"
        return ("import os, subprocess, sys, time\n"
                f"p = subprocess.Popen([sys.executable, '-c', {child!r}], "
                "start_new_session=(os.name == 'posix'))\n"
                f"open({str(path)!r}, 'w').write(str(p.pid))\n"
                + ("" if exit_parent else "time.sleep(60)\n"))

    @unittest.skipUnless(sys.platform.startswith("linux"), "needs Linux subreaper + /proc descendant reaping")
    async def test_hard_deadline_kills_descendant_that_changes_session(self):
        run = self.runner()
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o777)
            marker = Path(tmp) / "pid"
            task = asyncio.create_task(run("playground", self.payload(
                self.descendant_source(marker)), 10))
            await self.wait_file(marker)
            pid = int(marker.read_text())
            with self.assertRaises(TimeoutError):
                await task
            self.assertFalse(process_alive(pid), "deadline returned with child alive")

    @unittest.skipUnless(sys.platform.startswith("linux"), "needs Linux subreaper + /proc descendant reaping")
    async def test_cancellation_waits_for_descendant_cleanup(self):
        run = self.runner()
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o777)
            marker = Path(tmp) / "pid"
            task = asyncio.create_task(run("playground", self.payload(
                self.descendant_source(marker)), 30))
            await self.wait_file(marker)
            pid = int(marker.read_text())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertFalse(process_alive(pid), "cancellation returned with child alive")

    @unittest.skipUnless(sys.platform.startswith("linux"), "needs Linux subreaper + /proc descendant reaping")
    async def test_success_also_cleans_orphan_descendants(self):
        run = self.runner()
        with tempfile.TemporaryDirectory() as tmp:
            os.chmod(tmp, 0o777)
            marker = Path(tmp) / "pid"
            result = await run("playground", self.payload(
                self.descendant_source(marker, exit_parent=True)), 15)
            self.assertEqual(result["verdict"], "OK")
            self.assertFalse(process_alive(int(marker.read_text())))

    async def test_playground_reuses_limits_and_stdin_contract(self):
        result = await self.runner()("playground", self.payload(
            "print(input()[::-1])") | {"stdin_data": "hello\n", "memory_cap_mb": 128}, 15)
        self.assertEqual(result["stdout"], "olleh\n")
        self.assertEqual(result["limits"]["memory_mb"], 128)
        self.assertTrue(result["memory_capped"])

    async def test_submission_preserves_hidden_test_redaction(self):
        import problem_store
        problem = synthetic_problem()
        result = await self.runner()("submission", {
            "problem": problem.pid, "problem_data": problem_store.serialize_problem(problem),
            "ext": ".py", "source": "print('wrong')",
            "reveal": "samples", "memory_cap_mb": 128, "judge_jobs": 1}, 20)
        self.assertGreater(result["total"], 0)
        sample_names = set(problem.samples)
        hidden = [item for item in result["results"] if item["test"] not in sample_names]
        self.assertTrue(hidden)
        for item in hidden:
            self.assertFalse({"input", "actual", "expected", "diff", "detail"} & item.keys())


if __name__ == "__main__":
    unittest.main()
