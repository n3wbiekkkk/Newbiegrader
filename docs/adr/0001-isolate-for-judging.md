---
status: proposed
---

# Judge submissions with isolate, on native worker units

The custom sandbox in `job_sandbox.py` (private UID ledger, Landlock, network namespace, seccomp) is replaced by `isolate` for both compiling and running submissions. `isolate` is purpose-built for judging and is what CMS and IOI use; it gives per-box UIDs, a chroot with explicit mounts, namespaces, cgroup limits and time/memory metering. Because it needs host cgroups, the `newbiegrader-worker@N` units stay native systemd services (one isolate box ID each) instead of moving into containers.

## Considered Options

- **A Docker container per job**: rejected. Slower startup, and matching today's cgroup/UID guarantees would need privileged or cgroup-host access, which weakens the host boundary. CMS itself uses Docker only for dev/test, not for isolation.
- **Keep the custom sandbox**: rejected in favour of a widely audited tool, at the cost of porting the canaries.

## Consequences

- `grader.py` stays the only source of verdicts; its version is bumped so every verdict stays traceable to the sandbox that produced it.
- The critical canaries in `tools/run_critical_tests.py` must be ported and pass before cutover.
- `isolate` is not packaged by Ubuntu; install it from the upstream apt repo or a pinned build.
- `isolate` has no seccomp layer. Do not stack a second sandbox on top without a new decision.
