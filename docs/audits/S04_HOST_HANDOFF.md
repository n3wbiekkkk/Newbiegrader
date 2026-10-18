# S04 host prerequisites — 2026-10-18 follow-up

**High · CONFIRMED host prerequisite failure · aggregate enforcement OPEN.**
Scheduling arithmetic and fail-closed rlimit setup are already deployed. This
follow-up adds a read-only diagnostic and tests; it does not implement a cgroup
launcher or change verdicts. The actual provider probe was run without deploying
the diagnostic, by passing its reviewed source to a transient Python process.

## Reproducible read-only preflight

Run inside the intended Linux worker container:

```sh
python tools/check_job_resource_host.py
# Or, after the provider provisions a private delegated parent:
python tools/check_job_resource_host.py --cgroup-root /path/from/provider
```

The tool reads only mount metadata and named cgroup control files. It never
mounts/remounts anything, changes a controller, attaches a process, reads an env
value, runs a submission, or creates a cgroup. Exit 2 means `HOST_BLOCKED`.
Exit 0 means `HOST_CANDIDATE_ENFORCEMENT_UNVERIFIED`, not a security pass: write
access checks alone cannot prove successful creation, attachment or enforcement.
Job and workspace verification flags stay false in both cases.

Actual JustRunMy app 69356 probe returned exit **2**, `HOST_BLOCKED`:

- cgroup v2 mount options: `ro,nosuid,nodev,noexec,relatime`.
- `cpu`, `memory`, `pids` are available but `cgroup.subtree_control` is empty.
- The selected parent is populated or unreadable and its delegation access
  check fails. This is not a usable empty delegated job parent.
- Whole-container limits remain 512 MiB memory, 0.5 CPU, 38,451 pids. These do
  not isolate a judge job from the API in the combined container.
- Provider MCP exposes application CPU/RAM quotas, but no exposed tool was found
  for per-job cgroup delegation or workspace quotas. This does not prove that
  the provider cannot offer them through operator support.

No production configuration, capability, container image, quota or volume was
changed. The probe ran through the operator's provider MCP, not an HTTP request
from an assumed privileged network.

## Why a summed RSS verdict was not substituted

`grader.py:660` still samples the main process; S04's descendant-memory gap
remains. Simply adding all processes' RSS can double-count shared resident pages.
A disposable Linux arm64 container (128 MiB, 1 CPU, 16 pids, network disabled)
ran a bounded diagnostic: one trusted Python parent allocated 8 MiB, forked
exactly two sleeping children, sampled only its own three processes, then waited
for both children. Summed RSS was **57.80 MiB**, summed PSS **22.22 MiB**.
This was a synthetic measurement, not a fork bomb or user submission.

Using RSS summation as an immediate verdict threshold could reject shared-memory
programs incorrectly. PSS sampling also is not a hard allocation boundary and
can miss short-lived processes. No sampler/threshold replacement is made here.
See the kernel's [RSS/PSS definitions](https://docs.kernel.org/filesystems/proc.html)
and [cgroup v2 memory/process accounting](https://docs.kernel.org/admin-guide/cgroup-v2.html).

## Prepared request to hosting — not sent

Recipient: the operator's hosting administrator or
`support@justrunmy.app` ([provider support](https://justrunmy.app/blog/mcp-server/)).

> We operate Newbiegrader, a programming judge, in application 69356. Can you
> provide a private cgroup v2 delegated subtree for this application's trusted
> worker supervisor, with cpu, memory and pids controllers enabled and an empty
> delegated parent? The container currently sees a read-only cgroup mount.
> The supervisor must be able to create bounded child groups and attach each
> job before any untrusted compiler/program starts. API processes must remain
> outside job groups. We also need a per-job workspace byte and inode bound
> with automatic cleanup. Please specify supported paths, ownership, controller
> permissions, restart behavior, security constraints and any additional cost.
> The delegation must not expose host/other-tenant cgroups or the Docker socket.
> Please do not enable privileged mode or grant CAP_SYS_ADMIN. If delegation is
> unsupported, please confirm whether you offer an equivalent isolated worker
> runtime with these guarantees. This is an inquiry, not approval to change
> configuration or billing.

No message has been sent and no new hosting purchase is authorized. A larger
container by itself does not close per-job aggregate containment.

## Acceptance criteria after the provider responds

1. Review the exact delegation/workspace boundary and cost before changing
   production. Re-run the read-only preflight; candidate status alone is not enough.
2. Implement a minimal launcher that installs and reads back aggregate memory,
   swap policy, pids and CPU controls before releasing the untrusted exec gate.
   Every setup/attachment failure must produce a job error, with no uncontained
   fallback. Budget runner/supervisor and tmpfs charges as well as submissions.
3. Verify with bounded synthetic Linux/root canaries in a disposable delegated
   environment: limits include children and detached descendants; API stays
   outside the group; cleanup completes after success, timeout, cancellation and
   runner exit; unavailable controls prevent user code from starting.
4. Prove workspace byte/inode bounds and cleanup separately. RLIMIT_FSIZE bounds
   one file only. Verify restart recovery, no leaked groups and no UID-ledger reset.
5. Run critical/full regressions and trusted reference compatibility checks before
   requesting a reviewed production release. Do not induce production OOM or
   run real user submissions to establish the limits.

## Test scope

`tests/test_critical_resource_host.py` covers read-only mount versus writable
superblock, controller availability/enabling, populated/unreadable delegation,
denied access, regular-directory impersonation, nested mount precedence,
symlink/non-Linux refusal, no writes and no false enforcement claims. These are
synthetic preflight tests, not tests of actual job cgroup enforcement.

Actual validation in this follow-up:

- Baseline disposable Linux arm64/root, Python 3.11: 236 discovered,
  **233 passed / 3 private-problem module skips** (27.947 seconds).
- Candidate in the same environment: critical **174 passed / 0 skips**
  (27.229 seconds); full discovery **241 passed / 3 skips** out of 244
  (29.222 seconds). Network disabled, default capabilities, no privileged mode.
- The eight new diagnostic tests also passed on macOS; they model host metadata
  and do not claim macOS cgroup support. Actual production preflight returned
  `HOST_BLOCKED`, exit 2, as detailed above.
- JavaScript **42 passed / 0 skips** including the separate Google-logo change.
  Python byte compilation, JS syntax, DOM/icon and style token guards passed.
  Packaged plagiarism self-test passed 4/4. The problem validator explicitly
  skipped because private `problems/` is absent from the clean snapshot; no claim
  of revalidating 68 private packages in this follow-up.

Private evidence directory:
`~/.local/share/newbiegrader-validation/s04-followup-jetr_3tg/`.
