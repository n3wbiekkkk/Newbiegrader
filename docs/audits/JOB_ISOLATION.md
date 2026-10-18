# Web-job isolation follow-up — 2026-10-18

Base: `cc2106a`; working branch: `fix/p0-job-identities`.
This is a local correction for S03, not a production rollout or a claim that the
whole sandbox is secure. No application data, production configuration or secrets
were changed. `main`, ignored `AGENTS.md` and existing `review.diff` are untouched.

## Changed behavior

- Each web submission/playground job reserves a numeric UID and matching GID.
  Compiler, runtime and their descendants inherit it; different jobs get different
  IDs. Parallel test threads retain their own job's trusted context.
- Root state defaults to `/var/lib/newbiegrader/sandbox-identities`; override with
  `GRADER_SANDBOX_IDENTITY_DIR`. Directory mode must be 0700, ledger mode 0600,
  owned by root. Ancestors must be root-controlled; root sticky /tmp is allowed.
  Symlinks/hardlinked ledgers and malformed/incomplete state refuse allocation.
- A directory flock serializes allocation across processes. The append-only
  `allocated-uids` ledger is fsynced, including its directory, before exposing an
  ID. IDs start at 1,000,000 and are never reused while this state survives.
  Named accounts/groups are skipped. No random collision/reusable lease pool.
- Landlock ABI >= 3 restricts filesystem opens/creation/removal/rename/truncation.
  Workspace writes are allowed; other job files and global temporary writes are
  denied, including world-readable files outside the policy. Toolchain paths
  `/usr`, `/bin`, `/lib`, `/lib64` are read/execute; selected loader/time/proc files,
  self-proc and null/random/zero devices supply normal runtime needs.
- Both launcher modes apply no_new_privs, drop supplementary groups/GID/UID,
  then apply filesystem restrictions before exec. Failure yields a job error,
  never execution as root or an invented CE/RE verdict. Linux/root combined and
  worker roles also refuse boot without Landlock ABI >= 3; the network allowance
  flag does not turn filesystem protection off.
- Trusted launch environment carries identity/workspace only between supervisors;
  it is stripped before executing the toolchain/program. HOME/TMPDIR remain the
  private workspace. Service-role/OAuth/session credentials are not forwarded.

The filesystem inheritance behavior and ABI requirements follow the
[Linux 6.8 Landlock documentation](https://docs.kernel.org/6.8/userspace-api/landlock.html).
No extra capability or privileged container was added. Network isolation follows
the existing independent contract.

## Deployment prerequisites — not performed

1. Linux arm64 or x86_64, root supervisor able to setgroups/setgid/setuid; kernel
   Landlock enabled with ABI >= 3. Default Docker profile worked on the test host
   (Linux 6.8.0-117-generic, arm64, ABI 4); production support is UNVERIFIED.
2. Reserve the allocator's numeric UID/GID range in the execution UID namespace;
   mapped IDs must support it. A user namespace mapping only 0..65535 cannot use
   this range: jobs must fail closed until an appropriate runtime is provisioned.
3. Persist the identity state whenever job files or processes can survive a
   container recreation. All cooperating workers sharing a Linux UID namespace
   must coordinate through the same locked state (or use separate UID namespaces).
   Do not reset/delete/roll back the ledger, or replace it with a stale backup,
   while old processes/files can survive. An incomplete ledger requires operator
   recovery; deleting it to make jobs pass is unsafe.
4. A persistent named volume at the default state directory is one possible
   deployment configuration, subject to host review/approval. No such mount was
   created in production. Restrict who can replace that directory/volume.
5. Keep secrets and user data outside the readable system trees. Inspect actual
   mounts, UID maps, caps, network and cgroups before public release. A passing
   filesystem test does not establish network or host escape resistance.

Read-only ABI probe for the actual container (no submission execution):

```sh
docker exec CONTAINER python -c 'import ctypes,platform; assert platform.machine() in ("aarch64","x86_64"); c=ctypes.CDLL(None,use_errno=True); print({"landlock_abi":c.syscall(444,0,0,1),"errno":ctypes.get_errno()})'
docker exec CONTAINER cat /proc/self/uid_map
docker exec CONTAINER cat /proc/self/gid_map
```

Do not solve failures by granting CAP_SYS_ADMIN, disabling filesystem confinement,
falling back to nobody, or exposing global /tmp.

## Evidence and tests

All execution tests use synthetic programs/canaries in disposable network-none
Docker containers, Linux arm64/root/Python 3.11. No user submissions were run.

- Before fix: overlapping synthetic jobs read and overwrote the victim's private
  source; signal-0 permission check succeeded. The new regression failed on the
  baseline. After fix all three operations are denied and the benign job completes.
- Twelve new critical tests: outside-file read/write/symlink/creation denial,
  public-header include denial, inherited compiler/runtime/child identity and
  filesystem policy, parallel tests/private TMPDIR, process-safe durable UID
  allocation, invalid state/fsync refusal, and unavailable-Landlock boot/exec refusal.
- Expanded critical suite: **114 passed, 0 skipped** (23.849 s).
- Full suite: **254 passed, 0 skipped** (92.878 s).
- Trusted offline problem/reference validation: **68/68 passed**. This validates
  existing packages in isolation; it is not a security proof or a live workload.
- Node: **25 passed**, syntax/DOM/style guards passed; Python byte compilation passed.
- Clean packaged image: startup validation plus synthetic Python and C++/STL both
  Accepted, ABI 4, no `/app/.env`. No production code deployment occurred.

Existing process-cleanup tests formerly wrote markers outside the submission
workspace. The tests now write inside it and let the trusted observer read the
PID, retaining the same descendant-death assertions. The policy was not relaxed
to satisfy the old coordination fixture. Critical tests still fail on any skip.

Evidence directory:
`~/.local/share/newbiegrader-validation/job-identities-1s_hws5b/`.

## Remaining risks

- No per-job cgroup, hard aggregate memory/pids/CPU/disk bound, mount/PID/IPC
  namespace or new network policy. S04 and production network verification remain
  open. SysV/abstract-socket IPC and kernel attack surfaces are not covered by
  these file/process-access canaries. Filesystem metadata visibility is not fully
  hidden by this Landlock ABI.
- Same-job tests retain a shared workspace/UID. A separate synthetic diagnostic
  confirmed a preexisting leak when hidden and public tests run concurrently:
  hidden data can be written into that workspace and echoed by a public sample.
  The follow-up S13 correction now runs all samples to completion before hidden
  tests, retaining parallel execution within each phase and original result order.
- Standalone trusted CLI/reference tools keep their legacy identity policy. They
  are not a safe replacement for the web execution boundary for arbitrary code.
- UID ledger/root state lifecycle and real host configuration must be verified
  before deployment; the SQL-only approval did not authorize a code release.

S03 implementation commit: `b982100`. Roll back with `git revert b982100` only
after reverting dependent follow-ups and rerun all gates.
Do not delete the allocated-UID ledger during rollback; restoring old permissions
or UID behavior reopens the original vulnerability. Production rollback/deploy
requires a separate review and approval.

## S13 feedback-order follow-up

The two failing-before canary regressions now pass across API/history/job result/
persistence and the database completion payload. A third test verifies parallel
hidden execution remains enabled. Grader version is 2.0.1; this changes the
execution order for noncanonical metadata, while preserving response ordering.

Final combined validation: critical **117 passed, zero skips** (23.483 s);
redaction suite **13 passed** (7.208 s). Full suite **257 passed, zero skips**
(89.718 s). No production code was deployed.

Final packaged image reports engine 2.0.1 and ABI 4; normal synthetic Python and
C++/STL are Accepted and the shared-file feedback canary does not leak. Its source
fingerprint matches the worktree:
`7fc8e0df63989cfb9cd637636ad5e09cc272a20e15fcfeb17d636aadd4083428`.
Separate synthetic probes also denied outside-file reads through `/proc/self/root`
and an O_PATH descriptor reopened through `/proc/self/fd`.
