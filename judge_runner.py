"""Supervised, bounded execution using only the Python standard library.

Linux supervisors are subreapers: descendants remain owned even after setsid
or an intermediate parent's exit. Windows uses a kill-on-close Job Object.
No untrusted command starts until its supervisor is attached to that object.
"""
from __future__ import annotations

import asyncio
import contextlib
import ctypes
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass

ROOT = Path(__file__).resolve().parent


class _WindowsJob:
    def __init__(self, process):
        from ctypes import wintypes

        class BasicLimit(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64),
                        ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD),
                        ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t),
                        ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t),
                        ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount",
                "ReadTransferCount", "WriteTransferCount", "OtherTransferCount")]

        class ExtendedLimit(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", BasicLimit), ("IoInfo", IO),
                        ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t),
                        ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.kernel.CreateJobObjectW.restype = wintypes.HANDLE
        self.kernel.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        self.kernel.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        self.kernel.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        self.kernel.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        self.kernel.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                         wintypes.DWORD, ctypes.c_void_p]
        self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = self.kernel.CreateJobObjectW(None, None)
        if not self.handle:
            raise ctypes.WinError(ctypes.get_last_error())
        limits = ExtendedLimit()
        limits.BasicLimitInformation.LimitFlags = 0x2000  # KILL_ON_JOB_CLOSE
        if not self.kernel.SetInformationJobObject(self.handle, 9, ctypes.byref(limits), ctypes.sizeof(limits)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())
        if not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            self.close()
            raise ctypes.WinError(ctypes.get_last_error())

    def terminate(self):
        if self.handle and not self.kernel.TerminateJobObject(self.handle, 1):
            raise ctypes.WinError(ctypes.get_last_error())
        # TerminateJobObject is asynchronous. Descendants may have closed their
        # output handles, so joining the stream readers alone is insufficient.
        accounting = (ctypes.c_uint64 * 6)()  # JOBOBJECT_BASIC_ACCOUNTING_INFORMATION
        while self.handle:
            if not self.kernel.QueryInformationJobObject(self.handle, 1, ctypes.byref(accounting),
                                                          ctypes.sizeof(accounting), None):
                raise ctypes.WinError(ctypes.get_last_error())
            active = ctypes.cast(ctypes.byref(accounting), ctypes.POINTER(ctypes.c_uint32))[10]
            if active == 0:
                return
            time.sleep(.005)

    def close(self):
        if self.handle:
            self.kernel.CloseHandle(self.handle)
            self.handle = None


def _children() -> dict[int, int]:
    result = {}
    for entry in Path("/proc").iterdir():
        if entry.name.isdecimal():
            try:
                fields = (entry / "stat").read_text().rsplit(")", 1)[1].split()
                result[int(entry.name)] = int(fields[1])
            except (OSError, ValueError, IndexError):
                pass
    return result


def _descendants(root: int) -> set[int]:
    parents = _children()
    descendants = {root}
    while True:
        expanded = descendants | {pid for pid, ppid in parents.items() if ppid in descendants}
        if expanded == descendants:
            return descendants - {root}
        descendants = expanded


def _cleanup_linux():
    # Freeze before killing to prevent a live parent from spawning replacements.
    # Adopted descendants are reaped here, including double-forked new sessions.
    while True:
        children = _descendants(os.getpid())
        for sig in (signal.SIGSTOP, signal.SIGKILL):
            for pid in children:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, sig)
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
                if pid == 0:
                    break
            except ChildProcessError:
                return
        time.sleep(.01)


def _supervise(command: list[str], pid_file: str, expected_parent: int) -> int:
    # os.read avoids a buffered read consuming the worker's subsequent stdin.
    if os.read(0, 1) != b"\0":
        return 125
    linux = sys.platform.startswith("linux")
    stopped = False

    def stop(_signum, _frame):
        nonlocal stopped
        stopped = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if linux:
        libc = ctypes.CDLL(None, use_errno=True)
        if libc.prctl(36, 1, 0, 0, 0) != 0:  # PR_SET_CHILD_SUBREAPER
            raise OSError(ctypes.get_errno(), "cannot enable child subreaper")
        if libc.prctl(1, signal.SIGTERM, 0, 0, 0) != 0:  # PR_SET_PDEATHSIG
            raise OSError(ctypes.get_errno(), "cannot monitor supervisor owner")
        # The owner may have died between spawning us and setting PDEATHSIG.
        if os.getppid() != expected_parent:
            stopped = True
    if stopped:
        return 124
    process = None
    try:
        process = subprocess.Popen(command)
        Path(pid_file).write_text(str(process.pid), encoding="ascii")
        while process.poll() is None and not stopped:
            time.sleep(.01)
        return 124 if stopped else process.returncode
    finally:
        if linux:
            _cleanup_linux()
        elif process is not None and process.poll() is None:
            process.kill()
            process.wait()


@dataclass
class BoundedResult:
    stdout: str
    stderr: str
    returncode: int
    reason: str


def run_bounded(command: list[str], stdin_data: str, timeout: float, *,
                output_limit: int, env: dict, cwd: str | None = None,
                cancel: threading.Event | None = None, sample=None) -> BoundedResult:
    """Collect each stream up to its byte limit, killing the full tree on overflow.

    The deadline includes process startup. Return only after process/pipe cleanup.
    Linux cleanup intentionally waits for all adopted descendants to be reaped.
    macOS retains process-group cleanup, but cannot contain escaped sessions.
    """
    started = time.monotonic()
    overflow = threading.Event()
    buffers = [bytearray(), bytearray()]
    job = None
    reason = ""
    with tempfile.TemporaryDirectory(prefix="judge_supervisor_") as tmp:
        pid_file = str(Path(tmp) / "pid")
        wrapped = [sys.executable, str(Path(__file__).resolve()), "--supervise", pid_file,
                   str(os.getpid()), "--", *command]
        process = subprocess.Popen(wrapped, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE, env=env, cwd=cwd,
                                   start_new_session=(os.name == "posix"))
        try:
            if os.name == "nt":
                job = _WindowsJob(process)
        except BaseException:
            process.kill()
            process.wait()
            for stream in (process.stdin, process.stdout, process.stderr):
                stream.close()
            raise

        def read_stream(stream, buffer):
            try:
                while True:
                    chunk = stream.read(8192)
                    if not chunk:
                        return
                    remaining = max(0, output_limit - len(buffer))
                    buffer.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        overflow.set()
            finally:
                stream.close()

        def write_input():
            try:
                process.stdin.write(b"\0" + stdin_data.encode("utf-8"))
                process.stdin.flush()
            except (BrokenPipeError, OSError):
                pass
            finally:
                process.stdin.close()

        threads = [threading.Thread(target=read_stream, args=(stream, buffer), daemon=True)
                   for stream, buffer in zip((process.stdout, process.stderr), buffers)]
        threads.append(threading.Thread(target=write_input, daemon=True))
        for thread in threads:
            thread.start()
        child_pid = None
        try:
            while process.poll() is None:
                if cancel is not None and cancel.is_set():
                    reason = "cancelled"
                elif overflow.is_set():
                    reason = "ole"
                elif time.monotonic() - started >= timeout:
                    reason = "timeout"
                if reason:
                    break
                if sample:
                    if child_pid is None:
                        with contextlib.suppress(OSError, ValueError):
                            child_pid = int(Path(pid_file).read_text(encoding="ascii"))
                    if child_pid:
                        sample(child_pid)
                time.sleep(.005)
        finally:
            if job is not None:
                # Also terminate descendants after a successful worker exit.
                job.terminate()
            elif process.poll() is None:
                process.terminate()
            if sys.platform == "darwin":
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
            process.wait()
            for thread in threads:
                thread.join()
            if job is not None:
                job.close()
        if overflow.is_set() and not reason:
            reason = "ole"
        # Preserve subprocess text=True's universal-newline behavior.
        return BoundedResult(*(bytes(buffer).decode("utf-8", "replace").replace("\r\n", "\n").replace("\r", "\n")
                               for buffer in buffers),
                             process.returncode, reason)


def _runner_env() -> dict:
    # Server import must neither read .env nor create a database client.
    import grader
    return grader.judge_env() | {"GRADER_RUNNER_CHILD": "1", "GRADER_ROLE": "combined",
                                 "GRADER_QUEUE_MODE": "local", "PYTHONUTF8": "1"}


async def run_isolated(kind: str, payload: dict, timeout: float) -> dict:
    if kind not in ("submission", "playground"):
        raise ValueError("unknown judge job kind")
    if timeout <= 0:
        raise TimeoutError("judge job deadline exceeded")
    cancel = threading.Event()
    task = asyncio.create_task(asyncio.to_thread(
        run_bounded, [sys.executable, str(Path(__file__).resolve()), "--job"],
        json.dumps({"kind": kind, "payload": payload}), timeout,
        output_limit=8 * 1024 * 1024, env=_runner_env(), cwd=str(ROOT), cancel=cancel))
    try:
        result = await asyncio.shield(task)
    except asyncio.CancelledError:
        cancel.set()
        # Repeated cancellations must not release capacity during tree cleanup.
        while not task.done():
            with contextlib.suppress(asyncio.CancelledError):
                await asyncio.shield(task)
        with contextlib.suppress(Exception):
            task.result()
        raise
    if result.reason == "timeout":
        raise TimeoutError("judge job deadline exceeded")
    if result.reason:
        raise RuntimeError(f"judge job failed: {result.reason}")
    if result.returncode:
        raise RuntimeError("judge subprocess exited unsuccessfully")
    try:
        data = json.loads(result.stdout)
        if not isinstance(data, dict):
            raise ValueError("result must be an object")
        return data
    except (ValueError, TypeError) as exc:
        raise RuntimeError("invalid judge subprocess result") from exc


def _job() -> int:
    message = json.load(sys.stdin)
    payload = message["payload"]
    # Keep the JSON result channel separate from import/engine diagnostics.
    with contextlib.redirect_stdout(sys.stderr):
        import grader
        import server
        server.MEMORY_CAP_MB = max(1, int(payload["memory_cap_mb"]))
        server.JUDGE_JOBS = max(1, int(payload["judge_jobs"]))
        grader.COMPILE_MEMORY_MB = max(256, server.MEMORY_CAP_MB)
        problem = grader.load_problem(payload["problem"]) if payload.get("problem") else None
        if message["kind"] == "submission":
            if problem is None:
                raise ValueError("submission requires a problem")
            result = server.run_submission(problem, payload["ext"], payload["source"], payload["reveal"])
        else:
            result = server._run_playground(problem, payload["ext"], payload["source"],
                                            payload["stdin_data"], payload["time_limit"], payload["memory_mb"])
    json.dump(result, sys.stdout, ensure_ascii=True)
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--supervise"]:
        returncode = _supervise(sys.argv[5:], sys.argv[2], int(sys.argv[3]))
        if os.name == "posix" and returncode < 0:
            # Replicate the signal after cleanup; SystemExit(-9) becomes 247 and
            # would hide the grader's existing SIGKILL/MLE classification.
            signal.signal(-returncode, signal.SIG_DFL) if -returncode != signal.SIGKILL else None
            os.kill(os.getpid(), -returncode)
        raise SystemExit(returncode)
    if sys.argv[1:] == ["--job"]:
        raise SystemExit(_job())
    raise SystemExit("invalid runner mode")
