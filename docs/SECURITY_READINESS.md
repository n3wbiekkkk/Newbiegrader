# Security release checks

Updated 2026-10-22 for the four-worker PC deployment. This describes verified
controls and their limits; each release must repeat the applicable checks.
See [current architecture](PRODUCTION_ARCHITECTURE.md),
[host deployment](HOST_DEPLOYMENT.md) and the
[latest measured qualification](releases/pc-execution-performance-2026-10-22.json).

## Execution and identity controls

- API and worker roles are separate. The API accepts durable jobs and serves
  authorized results; it cannot execute submissions or read private test files.
- Each job reserves a unique numeric UID/GID in a root-controlled append-only
  ledger. Compiler/runtime processes drop supplementary groups, identity and
  capabilities. Workspaces are private to that identity; UID reservations are
  shared across the four worker instances and never reset during a release.
- The launcher verifies `no_new_privs`, applies resource limits, Landlock
  filesystem rules and seccomp endpoint denial. Production uses the explicitly
  declared non-netns posture with these mandatory controls. No `CAP_SYS_ADMIN`
  or privileged container is added to make isolation pass.
- Per-job cgroups contain descendants, with 640 MiB memory, no swap, 64 tasks
  and one CPU. Each worker has a separate one-CPU / one-GiB unit and private
  128 MiB / 4,096-inode workspace tmpfs; the four-worker slice caps aggregate
  judging at four CPUs / four GiB. Slot release waits for process-tree cleanup.
- Trusted Python bytecode is prepared before activation. Runtime services cannot
  replace the root-owned caches. Private fixtures, credentials and references
  remain outside application releases and sandbox filesystem allowances.
- Isolated execution imports the standard-library `judge_execution.py` module,
  not the HTTP app or database clients. Budgets are passed explicitly and the
  shared feedback helpers remain the same on API, persistence and runner paths.
- Session authorization requires a currently verified, versioned identity.
  Password/OTP and Google provider linking use the existing identity contract;
  the PC move preserved identities and `SESSION_SECRET`. That move tested an
  existing verified session, without claiming a fresh OTP/Google login.
- Visibility, CSRF, proxy-header trust, body bounds and result allowlists remain
  enforced. Owner practice feedback and peer/contest restrictions follow the
  [feedback policy](submission-feedback-policy.md).

## Required validation

Run applicable commands in `.github/workflows/ci.yml`. The Linux/root critical
suite requires GCC/G++, application dependencies and `httpx`; any skip fails.
It uses synthetic compiler/redaction fixtures, cleanup/ownership canaries and
fake services, without production credentials or private problem data.

Run ordinary unittests and private reference validation in an authorized
checkout. SQL/queue concurrency checks run only against an empty disposable
PostgreSQL database. Production host qualification also requires native kernel
canaries, cleanup recovery, file-access/verdict checks and read-only worker
preflights. Test all four allocations concurrently before changing their budgets.
Use the reviewed host runbook to pause/drain when a check requires idle workers.

The latest code release passed 301 critical tests and 497 full Linux tests with
zero skips, 127 frontend tests, native isolation canaries and public HTTPS checks.
These counts describe that checkpoint, not a substitute for future validation.

## Verify the deployed backend

`GET /api/version` returns `build_sha256`, computed at startup from every path in
`server.BUILD_SOURCE_FILES`. Read that tuple from the exact checkout instead of
maintaining a separate list that can become stale. This command parses source
without importing the application, reading `.env` or creating a database client:

```sh
python3 - <<'PY'
import ast
import hashlib
from pathlib import Path
module = ast.parse(Path('server.py').read_text())
assignment = next(node for node in module.body if isinstance(node, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == 'BUILD_SOURCE_FILES'
                          for t in node.targets))
digest = hashlib.sha256()
for name in ast.literal_eval(assignment.value):
    digest.update(name.encode('ascii') + b'\0')
    digest.update(Path(name).read_bytes())
    digest.update(b'\0')
print(digest.hexdigest())
PY
```

Compare against an uncached deployed version request and verify health, role,
four worker slots, durable queue and protected local-file mode. Separately
check the installed release, units, limits, ownership and actual host probes.
The fingerprint identifies public source bytes; it does not attest to dependency
versions, configuration, credentials, file contents or sandbox posture.

## Remaining limits

Per-job cgroups enforce whole-job containment, including compiler/runner memory.
They do not prove exact descendant memory attribution for each individual test.
The engine's parent-process RSS sampling and per-process address-space limits
remain distinct from that aggregate containment. Do not claim complete per-test
memory accounting or blanket closure of earlier audit findings.

Local combined queue mode remains a development option with process-local state;
production uses durable database leases and atomic completion/history. A healthy
API alone proves neither worker effectiveness nor recovery. The file/configuration
restore rehearsals do not prove complete hosted Database/Auth/Storage recovery;
see [backup coverage](HOST_BACKUP_RESTORE.md).
