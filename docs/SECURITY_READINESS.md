# Security release checks

This is a record of verified safeguards and remaining launch work, not a claim
that executing public submissions is fully contained.

## Execution safeguards

- `grader._compile` uses the sandbox launcher on Linux/root, including when the
  compile memory limit is disabled. Compilers and descendants drop UID/GID.
- `grader.prepare_workspace` transfers a caller-created workspace and source to
  the sandbox identity using file descriptors, refusing symlinks. The directory
  stays `0700` and the source `0600`; no world-writable workspace is required.
- `grader.build_limits` enables and verifies Linux `no_new_privs` before dropping
  identity. A hardening or identity-drop failure refuses execution. The flag is
  inherited by compiler/runtime children and prevents exec from adding setuid,
  setgid or file-capability privileges. See the
  [Linux kernel documentation](https://docs.kernel.org/userspace-api/no_new_privs.html).
- Hidden execution diagnostics are engine-generated. User-controlled streams
  are redacted at engine, API, history, queue-result and persistence boundaries;
  public sample diagnostics remain available under the reveal policy.

## Required validation

Run the commands in `.github/workflows/ci.yml` before merging. In particular,
`python tools/run_critical_tests.py` must run inside Linux/root with GCC/G++,
the application requirements and `httpx` installed. Any skip is a failure.
The gate includes synthetic compiler/redaction canaries, process-tree cleanup,
queue admission/lease ownership and proxy-header trust checks. It requires no
private `problems/`, database credentials, or production network access.

Run the ordinary unittest suite as well. Where a local trusted problem set is
available, run `tools/validate_problem.py` to verify reference-solution parity.
Queue SQL tests belong in an empty disposable PostgreSQL database; the workflow
applies the schema twice before executing `tests/queue_sql.sql`.

### Verify the deployed backend

`GET /api/version` returns `build_sha256`, computed once at process startup from
the six public backend source files in `server.BUILD_SOURCE_FILES`. Compare it
with the expected hash from the exact checkout being deployed:

```sh
python3 - <<'PY'
import hashlib
from pathlib import Path
digest = hashlib.sha256()
for name in ('grader.py', 'server.py', 'judge_runner.py', 'problem_store.py',
             'container_entrypoint.py', 'worker.py'):
    digest.update(name.encode('ascii') + b'\0')
    digest.update(Path(name).read_bytes())
    digest.update(b'\0')
print(digest.hexdigest())
PY
```

Use an uncached request to the backend after its rebuild, then verify health.
The hash identifies these source bytes; it does not attest to dependencies,
container capabilities, configuration, secrets or the actual sandbox posture.
The calculation excludes environment variables, `.env`, and problem data.

## Remaining priorities

1. **Per-job identity and filesystem containment:** compile/runtime jobs still
   share `nobody`. `0700` does not isolate jobs with the same UID, and
   `RLIMIT_NPROC` counts processes per UID. `no_new_privs` does not fix either
   issue or provide mount, PID or syscall isolation.
2. **Verified identity:** password registration immediately trusts an unverified
   email, while authorization/data ownership use that email. Email ownership and
   safe provider linking need a dedicated change, including session migration.
3. **Network isolation:** compilation deliberately does not require a network
   namespace. Runtime isolation depends on the configured boot posture and host
   support. Do not add `CAP_SYS_ADMIN` or privileged mode to satisfy the probe.
4. **Durability and resource accounting:** local queue mode is process-local;
   review durable queue cutover, aggregate process-tree memory and quotas before
   relying on public concurrency. No production schema or queue-mode change was
   performed as part of these code changes.

An unauthenticated read from the development Mac on 2026-10-17 observed the
production backend reporting `combined`, queue `local`, problem source
`supabase`, 68 problems, 0.5 vCPU and 512 MB. These values do not establish its
capabilities, isolation flags, secret mounts, or worker effectiveness. Verify
those on the host before a public launch; do not infer them from a healthy API.
