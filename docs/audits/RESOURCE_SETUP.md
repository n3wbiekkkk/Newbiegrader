# S04 resource-limit setup follow-up — 2026-10-18

**High, CONFIRMED setup failure path; partially fixed. Aggregate containment OPEN.**

`grader.build_limits()` previously ignored failed setrlimit calls, including
Linux/root web launchers. A synthetic injected failure for each of AS, DATA,
CPU, NPROC, FSIZE, CORE and NOFILE allowed the launcher to continue; the regression
failed in all 14 OSError/ValueError subcases before the correction.

The smallest correction refuses Linux/root sandbox execution if any required
limit cannot be installed. It uses the existing privilege-refusal marker and
exit code, so compiler/runtime refusal remains a job error, not CE/RE. Limits
remain installed before dropping UID/GID, with no fallback to executing as root.
Non-root/non-Linux trusted CLI behavior remains best effort. Engine **2.0.5**.

Verification of the limits-only snapshot, disposable Linux arm64/root/Python 3.11:

- New `tests/test_critical_resource_setup.py`: **2 passed**, including all 14
  failure subcases and the limit-before-credential-drop assertion.
- Full suite: **274 passed, zero skips**, 104.558 s.
- Offline package/reference validator: **68/68 passed**.
- Node: **34 passed**, syntax/DOM/style guards passed. Byte compilation and
  plagiarism self-test passed. No real user submissions were executed.

## Actual production constraint

Read-only JustRunMy probe confirmed `/sys/fs/cgroup` mounted **read-only**, no
alternative delegated root configured, and no enabled child controllers. The
container is limited to 512 MiB / 0.5 CPU / 38,451 pids; memory.events reported
zero OOM kills at observation. These are whole-container bounds, not job bounds.

Hard aggregate memory/pids/CPU and workspace-byte enforcement cannot be honestly
claimed with this patch. The provider must supply reviewed cgroup delegation and
bounded workspace storage, or a suitable isolated worker runtime. No remount,
privileged flag, CAP_SYS_ADMIN, quota increase or production setting change was
attempted to bypass that restriction. Keep concurrency at one.

Private evidence: `~/.local/share/newbiegrader-validation/runtime-enforcement-hlp2u8fm/`.
The new tests are synthetic and discovered by the existing critical gate; its
any-skip failure rule is unchanged. Deployment is a separate verified step.
