"""Fail-closed job cgroups inside a systemd delegation; one bounded workspace FS.

Trusted supervisor only. No user payload chooses a path, UID or resource limit.
The systemd manager supplies the tmpfs mount and delegated /manager subgroup;
this module never mounts filesystems or changes controllers outside that unit.
"""
from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import threading
import time
import uuid

MIB = 1024 * 1024
_lock = threading.Lock()
_active = False
_poisoned = False
_ready = None


class IsolationUnavailable(RuntimeError):
    pass


def required() -> bool:
    value = os.environ.get("GRADER_REQUIRE_JOB_CGROUP", "0")
    if value not in ("0", "1"):
        raise IsolationUnavailable("GRADER_REQUIRE_JOB_CGROUP must be 0 or 1")
    return value == "1"


def _number(name: str, default: int, minimum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except ValueError as exc:
        raise IsolationUnavailable("invalid job resource configuration") from exc
    if value < minimum:
        raise IsolationUnavailable("job resource limit is too small")
    return value


def _read(path: Path) -> str:
    return path.read_text(encoding="ascii").strip()


def _write(path: Path, value: str) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CLOEXEC | os.O_NOFOLLOW)
    try:
        if os.write(fd, value.encode("ascii")) != len(value):
            raise IsolationUnavailable("incomplete resource control write")
    finally:
        os.close(fd)


def _membership(pid: int | str = "self") -> str:
    lines = _read(Path(f"/proc/{pid}/cgroup")).splitlines()
    return next(line[3:] for line in lines if line.startswith("0::"))


def _private_directory(path: Path) -> None:
    if not path.is_absolute() or path.resolve() != path:
        raise IsolationUnavailable("resource paths must be canonical absolute directories")
    for parent in (path, *path.parents):
        info = parent.stat()
        if info.st_uid != 0 or info.st_mode & 0o022:
            raise IsolationUnavailable("resource directory is not root-controlled")


def _verify_workspace(root: Path) -> None:
    _private_directory(root)
    # An ordinary directory (or a larger parent tmpfs) is not a quota boundary.
    found = False
    for line in Path("/proc/self/mountinfo").read_text().splitlines():
        left, right = line.split(" - ", 1)
        if left.split()[4] == str(root) and right.split()[0] == "tmpfs":
            found = True
    stats = os.statvfs(root)
    if (not found or stats.f_blocks * stats.f_frsize > 128 * MIB
            or not 0 < stats.f_files <= 4096):
        raise IsolationUnavailable("workspace needs a dedicated <=128MiB/4096-inode tmpfs")


def _empty_group(group: Path) -> None:
    _write(group / "cgroup.kill", "1")
    deadline = time.monotonic() + 5
    while "populated 0" not in _read(group / "cgroup.events").splitlines():
        if time.monotonic() >= deadline:
            raise IsolationUnavailable("job processes did not leave their cgroup")
        time.sleep(.01)
    group.rmdir()


def initialize() -> None:
    """Check the actual manager subgroup; enable only its delegated parent."""
    global _ready
    if not required():
        return
    if not sys.platform.startswith("linux") or os.geteuid() != 0:
        raise IsolationUnavailable("job cgroups require a trusted Linux/root supervisor")
    status = Path("/proc/self/status").read_text()
    effective = next(int(line.split()[1], 16) for line in status.splitlines()
                     if line.startswith("CapEff:"))
    if effective & 0xeb != 0xeb:  # CHOWN, DAC_OVERRIDE, FOWNER, KILL, SETGID, SETUID
        raise IsolationUnavailable("supervisor lacks required privilege-drop/cleanup capabilities")
    root = Path(os.environ.get("GRADER_JOB_CGROUP_ROOT", ""))
    workspace = Path(os.environ.get("GRADER_WORKSPACE_ROOT", ""))
    _private_directory(root)
    try:
        expected = "/" + str(root.relative_to("/sys/fs/cgroup")) + "/manager"
    except ValueError as exc:
        raise IsolationUnavailable("delegation is outside the cgroup v2 hierarchy") from exc
    if root == Path("/sys/fs/cgroup") or _membership() != expected:
        raise IsolationUnavailable("supervisor is not in the configured delegated manager subgroup")
    _verify_workspace(workspace)
    if _poisoned:
        raise IsolationUnavailable("previous resource cleanup failed; restart worker")
    if _ready == (root, workspace):
        return
    if _read(root / "cgroup.procs"):
        raise IsolationUnavailable("delegation parent must have no processes")
    wanted = {"cpu", "memory", "pids"}
    if not wanted <= set(_read(root / "cgroup.controllers").split()):
        raise IsolationUnavailable("required delegated controllers unavailable")
    _write(root / "cgroup.subtree_control", "+cpu +memory +pids")
    if not wanted <= set(_read(root / "cgroup.subtree_control").split()):
        raise IsolationUnavailable("delegated controllers did not become active")
    # A service restart kills its entire cgroup first (KillMode=control-group).
    # Reap only our own generated groups; never remove unrelated cgroups.
    for child in root.iterdir():
        if re.fullmatch(r"job-[0-9a-f]{32}", child.name):
            _empty_group(child)
    _ready = (root, workspace)


def assert_healthy() -> None:
    if required() and _poisoned:
        raise IsolationUnavailable("resource cleanup failed; worker must stop")


class JobResources:
    def __init__(self):
        initialize()
        self.root, self.workspace_root = _ready
        self.group = self.root / ("job-" + uuid.uuid4().hex)
        self.workspace = None

    def create(self) -> None:
        self.group.mkdir(mode=0o700)
        values = {"memory.max": str(_number("GRADER_JOB_MEMORY_MB", 640, 32) * MIB),
                  "memory.swap.max": "0", "memory.oom.group": "1",
                  "pids.max": str(_number("GRADER_JOB_PIDS", 64, 8)),
                  "cpu.max": f'{_number("GRADER_JOB_CPU_QUOTA_US", 100000, 1000)} 100000'}
        for name, value in values.items():
            _write(self.group / name, value)
            if _read(self.group / name) != value:
                raise IsolationUnavailable("job resource control readback failed")
        self.workspace = Path(tempfile.mkdtemp(prefix="job-", dir=self.workspace_root))
        self.workspace.chmod(0o755)  # numeric sandbox UID must traverse to its private 0700 workspace

    def attach(self, pid: int) -> None:
        # run_bounded's supervisor is still blocked on its stdin gate here.
        _write(self.group / "cgroup.procs", str(pid))
        if _membership(pid) != "/" + str(self.group.relative_to("/sys/fs/cgroup")):
            raise IsolationUnavailable("blocked job supervisor was not attached")

    def close(self) -> None:
        global _poisoned
        try:
            if self.group.exists():
                _empty_group(self.group)
            if self.workspace is not None:
                shutil.rmtree(self.workspace)
        except BaseException:
            # Do not delete workspace paths while an uncontained process may live.
            # The worker exits before its next claim; systemd kills the whole unit.
            _poisoned = True
            raise


@contextmanager
def job_scope():
    global _active
    if not required():
        yield None
        return
    with _lock:
        if _active:
            raise IsolationUnavailable("single-job workspace boundary is already occupied")
        _active = True
    boundary = None
    try:
        boundary = JobResources()
        boundary.create()
        yield boundary
    finally:
        try:
            if boundary is not None:
                boundary.close()
        finally:
            with _lock:
                _active = False
