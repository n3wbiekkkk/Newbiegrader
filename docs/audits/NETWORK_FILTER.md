# Compiler/runtime network restriction — 2026-10-18

**High exposure in acknowledged mode, CONFIRMED; corrected in this release.**

The deployed host cannot create a network namespace, and has explicitly enabled
`GRADER_ALLOW_UNISOLATED_JUDGE`. Previously a web program/compiler could create
network sockets in that mode. Synthetic pre-fix checks created a socket (without
connecting or sending anything), violating the new denial assertion.

## Correction

- `job_sandbox.py`: mandatory inherited seccomp BPF filter for Linux web jobs on
  x86_64/arm64. Reject other syscall architectures and x32; return EPERM for new
  sockets, bind/connect/listen/accept, ptrace and io_uring operations. This is
  syscall filtering, not a claim of a complete sandbox or a network namespace.
- Anonymous **AF_UNIX/SOCK_STREAM socketpair** is allowed, including CLOEXEC and
  NONBLOCK flags, for Python asyncio/local IPC. Datagram, seqpacket and foreign
  family pairs are denied. The pair has no named external endpoint; connect and
  bind are still denied. No service network descriptors are passed to user code.
- `grader.build_limits()`: install after no_new_privs, identity drop and Landlock,
  before exec. Compiler mode also installs it, independent of its netns flag.
  Children inherit across fork/exec. Failure uses the existing job-error path.
- `server.validate_runtime()`: test the filter in a bounded trusted child before
  starting a Linux/root worker. Do not apply it to the API process, which needs
  Supabase/OAuth networking. Probe failure refuses boot.
- Existing strict-netns behavior stays strict: a requested but unavailable netns
  still refuses boot. The older allowance flag only acknowledges namespace
  absence; it does not disable this new network filter. No new capabilities,
  privileged mode, global network rules or security-control bypass.
- Engine **2.0.6** records the changed execution semantics.

Design references: [Linux seccomp documentation](https://docs.kernel.org/userspace-api/seccomp_filter.html),
[x86 syscall table](https://github.com/torvalds/linux/blob/v6.12/arch/x86/entry/syscalls/syscall_64.tbl),
[generic syscall numbers](https://github.com/torvalds/linux/blob/v6.12/include/uapi/asm-generic/unistd.h).

## Evidence

- Six new synthetic tests: native syscall policy, architecture/x32 guards,
  compiler path, runtime plus exec descendant, installation refusal and boot
  refusal. No real network connections, user submissions or hidden data used.
- On disposable Linux arm64/root/Python 3.11 the new tests pass, including a benign
  asyncio loop, anonymous stream-pair data exchange and ordinary C/C++ STL tests.
  Full suite **280 passed, zero skips**, 106.526 s; offline validator **68/68**.
- Critical gate **140 passed, zero skips**, 25.434 s. Clean packaged image at
  0.5 CPU / 512 MiB passed eight operator canaries (Python/C/C++ STL, outside-file
  denial, practice/contest policy and network creation denial), network none.
- Real production x86_64 operator preflight installed the filter only in its own
  child process: eight family/type creation probes denied, anonymous stream pair
  passed. Application processes/configuration remained unchanged by that probe.
  This is compatibility evidence, not application rollout evidence.
- Foreign ABI/x32 behavior is tested against a BPF interpreter, not by executing
  a compat-mode payload on the host. Actual foreign-ABI execution is unverified.

## Remaining risks

This is not an allowlist of every kernel API and does not replace updates,
Landlock, UID isolation or host containment. Filesystem metadata, IPC/kernel
surfaces, host UID reservation and aggregate resource limits remain relevant.
The filter assumes trusted launchers close unrelated descriptors; future changes
must not pass a network or io_uring descriptor into a job. Unknown architectures
fail rather than reusing a different architecture's syscall numbers.

Actual production cgroup mount is read-only. **S04 aggregate limits remain OPEN**
as documented in RESOURCE_SETUP.md; no fork bomb or OOM experiment was performed.
New tests are included by the existing any-skip-fails critical gate.

Evidence: `~/.local/share/newbiegrader-validation/runtime-enforcement-hlp2u8fm/`.
Deployment and post-deployment verification must be recorded separately.
