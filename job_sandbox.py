# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Linux web-job identity allocation and inherited filesystem confinement.

No UID is recycled while the root-owned append-only allocation ledger survives.
Keep this state with any shared/persistent job files; never reset it while old
jobs or their files can survive. These controls do not replace cgroup/network
isolation. Standalone trusted CLI/reference runs retain the grader's old policy.
"""
from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
import ctypes
from dataclasses import dataclass, field
import os
from pathlib import Path
import platform
import stat
import subprocess
import sys
import threading

UID_FIRST = 1_000_000
UID_LAST = 2_147_483_647


@dataclass
class _Job:
    identity: tuple[int, int] | None = None
    workspace: str | None = None
    lock: object = field(default_factory=threading.Lock)


_current: ContextVar[_Job | None] = ContextVar("judge_job_identity", default=None)


@contextmanager
def scope():
    """One trusted web job, including compile and every parallel test."""
    token = _current.set(_Job())
    try:
        yield
    finally:
        _current.reset(token)


def _state_directory() -> int:
    """Open/create only root-controlled ancestors; no symlink traversal."""
    path = Path(os.environ.get("GRADER_SANDBOX_IDENTITY_DIR",
                               "/var/lib/newbiegrader/sandbox-identities"))
    if not path.is_absolute() or ".." in path.parts or path == Path("/"):
        raise OSError("identity state needs an absolute private directory")
    fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            info = os.fstat(fd)
            # A root sticky /tmp ancestor is safe for a root-owned child entry.
            if info.st_uid != 0 or (info.st_mode & 0o022 and not info.st_mode & stat.S_ISVTX):
                raise OSError("identity state ancestor is not root-controlled")
        if stat.S_IMODE(os.fstat(fd).st_mode) != 0o700:
            raise OSError("identity state directory must be root-only")
        return fd
    except BaseException:
        os.close(fd)
        raise


def _allocate() -> tuple[int, int]:
    import fcntl
    import grp
    import pwd

    directory = _state_directory()
    fd = None
    try:
        # Lock the stable directory before creation too: another process must
        # not mistake the first writer's not-yet-initialized file for corruption.
        fcntl.flock(directory, fcntl.LOCK_EX)
        flags = os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW | os.O_NONBLOCK
        try:
            fd = os.open("allocated-uids", flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=directory)
            created = True
        except FileExistsError:
            fd = os.open("allocated-uids", flags, dir_fd=directory)
            created = False
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != 0 or info.st_nlink != 1
                or stat.S_IMODE(info.st_mode) != 0o600):
            raise OSError("unsafe identity allocation ledger")
        if info.st_size:
            os.lseek(fd, max(0, info.st_size - 64), os.SEEK_SET)
            tail = os.read(fd, 64)
            if not tail.endswith(b"\n") or not tail.splitlines()[-1].isdigit():
                raise OSError("incomplete identity allocation ledger")
            previous = int(tail.splitlines()[-1])
            if not UID_FIRST <= previous <= UID_LAST:
                raise OSError("invalid identity allocation ledger")
            candidate = previous + 1
        elif created:
            candidate = UID_FIRST
        else:
            raise OSError("empty existing identity ledger; refusing UID reuse")
        # The range must be reserved for this judge in its UID namespace.
        # Do not borrow a named account or primary group even if misconfigured.
        while candidate <= UID_LAST:
            try:
                pwd.getpwuid(candidate)
            except KeyError:
                try:
                    grp.getgrgid(candidate)
                except KeyError:
                    break
            candidate += 1
        if candidate > UID_LAST:
            raise OSError("sandbox identity range exhausted")
        record = f"{candidate}\n".encode("ascii")
        while record:
            written = os.write(fd, record)
            if written <= 0:
                raise OSError("cannot reserve sandbox identity")
            record = record[written:]
        # Reserve durably before publishing the identity to a workspace/process.
        os.fsync(fd)
        os.fsync(directory)
        return candidate, candidate
    finally:
        if fd is not None:
            os.close(fd)
        os.close(directory)


def identity() -> tuple[int, int] | None:
    job = _current.get()
    if job is None or not sys.platform.startswith("linux") or os.geteuid() != 0:
        return None
    with job.lock:
        if job.identity is None:
            job.identity = _allocate()
        return job.identity


def launch_environment(workspace: str | None) -> dict:
    job = _current.get()
    if job is None or job.identity is None:
        return {}
    if not workspace or not os.path.isabs(workspace):
        raise OSError("job launch requires its workspace")
    uid, gid = job.identity
    return {"GRADER_JOB_UID": str(uid), "GRADER_JOB_GID": str(gid),
            "GRADER_JOB_WORKSPACE": workspace}


@contextmanager
def launch_scope():
    """Load only the trusted supervisor's launch environment, never job JSON."""
    keys = ("GRADER_JOB_UID", "GRADER_JOB_GID", "GRADER_JOB_WORKSPACE")
    values = [os.environ.pop(key, None) for key in keys]
    token = None
    try:
        if any(value is not None for value in values):
            uid, gid = int(values[0]), int(values[1])
            workspace = values[2]
            if not (UID_FIRST <= uid <= UID_LAST and uid == gid and workspace
                    and os.path.isabs(workspace)):
                raise OSError("invalid sandbox launch identity")
            token = _current.set(_Job((uid, gid), workspace))
        yield
    finally:
        if token is not None:
            _current.reset(token)


def _libc():
    if not sys.platform.startswith("linux") or platform.machine() not in ("aarch64", "x86_64"):
        raise OSError("filesystem sandbox needs Linux arm64 or x86_64")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    return libc


def landlock_abi() -> int:
    libc = _libc()
    version = libc.syscall(444, 0, 0, 1)  # landlock_create_ruleset VERSION
    if version < 3:
        raise OSError(ctypes.get_errno(), "Landlock ABI >= 3 required")
    return version


def _network_filter_program(machine: str) -> list[tuple[int, int, int, int]]:
    """Classic BPF over seccomp_data; reject foreign ABIs before syscall checks.

    Numbers follow Linux's x86 syscall_64.tbl and asm-generic/unistd.h.
    Anonymous AF_UNIX stream pairs support Python asyncio and local IPC; named
    sockets, datagram pairs, new endpoints and io_uring are unavailable.
    """
    if machine == "x86_64":
        arch, pair = 0xc000003e, 53  # AUDIT_ARCH_X86_64
        denied = (41, 42, 43, 49, 50, 101, 288, 425, 426, 427)
    elif machine == "aarch64":
        arch, pair = 0xc00000b7, 199  # AUDIT_ARCH_AARCH64, little endian
        denied = (117, 198, 200, 201, 202, 203, 242, 425, 426, 427)
    else:
        raise OSError("network syscall filter needs Linux arm64 or x86_64")
    allow, kill, refused = 0x7fff0000, 0x80000000, 0x50001  # ERRNO(EPERM)
    instructions = [
        (0x20, 0, 0, 4),             # load architecture
        (0x15, 1, 0, arch), (0x06, 0, 0, kill),
        (0x20, 0, 0, 0),             # load syscall number
        (0x35, 0, 1, 0x40000000), (0x06, 0, 0, kill),  # no x32 ABI
        (0x15, 0, 7, pair),
        (0x20, 0, 0, 16),            # socketpair domain, args[0]
        (0x15, 0, 4, 1),             # AF_UNIX only
        (0x20, 0, 0, 24), (0x54, 0, 0, 0xf),  # type without creation flags
        (0x15, 0, 1, 1),             # SOCK_STREAM only
        (0x06, 0, 0, allow), (0x06, 0, 0, refused),
    ]
    for number in denied:
        instructions.extend(((0x15, 0, 1, number), (0x06, 0, 0, refused)))
    instructions.append((0x06, 0, 0, allow))
    return instructions


def _install_network_filter() -> None:
    libc = _libc()

    class Instruction(ctypes.Structure):
        _fields_ = [("code", ctypes.c_ushort), ("jt", ctypes.c_ubyte),
                    ("jf", ctypes.c_ubyte), ("k", ctypes.c_uint32)]

    class Program(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ushort),
                    ("instructions", ctypes.POINTER(Instruction))]

    values = _network_filter_program(platform.machine())
    instructions = (Instruction * len(values))(*(Instruction(*v) for v in values))
    program = Program(len(values), instructions)
    # no_new_privs has already been set by the launcher; no new capability.
    if libc.prctl(22, 2, ctypes.byref(program), 0, 0) != 0:  # PR_SET_SECCOMP FILTER
        raise OSError(ctypes.get_errno(), "cannot install network syscall filter")


def restrict_network() -> None:
    if _current.get() is not None:
        _install_network_filter()


def verify_network_filter() -> None:
    """Trusted boot probe in a separate process, never restrict the API itself."""
    code = (
        "import ctypes,errno,socket,job_sandbox\n"
        "c=ctypes.CDLL(None,use_errno=True)\n"
        "assert c.prctl(38,1,0,0,0)==0\n"  # PR_SET_NO_NEW_PRIVS
        "job_sandbox._install_network_filter()\n"
        "for family in (socket.AF_INET,socket.AF_INET6):\n"
        " try: socket.socket(family);raise AssertionError('socket allowed')\n"
        " except OSError as e: assert e.errno==errno.EPERM\n")
    try:
        result = subprocess.run([sys.executable, "-c", code], cwd=Path(__file__).parent,
                                env={"PATH": "/usr/bin:/bin:/usr/local/bin"},
                                capture_output=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise OSError("network syscall filter probe unavailable") from exc
    if result.returncode != 0:
        raise OSError("network syscall filter probe failed")


def restrict_filesystem() -> None:
    """Called after no_new_privs and UID/GID drop, immediately before exec."""
    job = _current.get()
    if job is None:
        return  # trusted standalone CLI, not a web job
    if job.identity is None or job.workspace is None:
        raise OSError("missing job filesystem boundary")
    landlock_abi()
    libc = _libc()
    execute, write, read, read_dir = 1, 2, 4, 8
    handled = (1 << 15) - 1  # ABI 1 + REFER (v2) + TRUNCATE (v3)

    class Ruleset(ctypes.Structure):
        _fields_ = [("handled_access_fs", ctypes.c_uint64)]

    class PathRule(ctypes.Structure):
        _pack_ = 1
        _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]

    attrs = Ruleset(handled)
    ruleset = libc.syscall(444, ctypes.byref(attrs), ctypes.sizeof(attrs), 0)
    if ruleset < 0:
        raise OSError(ctypes.get_errno(), "cannot create filesystem ruleset")

    def allow(path, access, *, optional=False, workspace=False):
        try:
            fd = os.open(path, os.O_PATH | (os.O_NOFOLLOW | os.O_DIRECTORY if workspace else 0))
        except FileNotFoundError:
            if optional:
                return
            raise
        try:
            info = os.fstat(fd)
            if workspace and (info.st_uid != job.identity[0] or info.st_gid != job.identity[1]
                              or os.path.realpath(path) != os.getcwd()):
                raise OSError("filesystem workspace does not match job identity")
            rule = PathRule(access, fd)
            if libc.syscall(445, ruleset, 1, ctypes.byref(rule), 0) != 0:
                raise OSError(ctypes.get_errno(), "cannot add filesystem rule")
        finally:
            os.close(fd)

    try:
        allow(job.workspace, handled, workspace=True)
        for path in ("/usr", "/bin", "/lib", "/lib64"):
            allow(path, execute | read | read_dir, optional=True)
        for path in ("/etc/ld.so.cache", "/etc/localtime", "/proc/cpuinfo", "/proc/meminfo"):
            allow(path, read, optional=True)
        allow("/proc/self", read | read_dir)
        for path in ("/dev/null", "/dev/zero"):
            allow(path, read | write)
        for path in ("/dev/urandom", "/dev/random"):
            allow(path, read, optional=True)
        if libc.syscall(446, ruleset, 0) != 0:
            raise OSError(ctypes.get_errno(), "cannot enforce filesystem ruleset")
    finally:
        os.close(ruleset)
