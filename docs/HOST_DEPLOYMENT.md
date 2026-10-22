# Native backend deployment

The backend runs on an Ubuntu PC with Python 3.11, Nginx and systemd. The
frontend remains on Cloudflare Pages; Supabase retains metadata, identities and
the durable queue. See [current architecture](PRODUCTION_ARCHITECTURE.md).
Deployment templates are in `deploy/host/`. Application source, protected
problem files and credentials are separate installation inputs.

## Host and resource allocation

The production PC has an i5-10400T (6 cores / 12 threads), about 7.1 GiB RAM and
SSD storage. Keep system Python unchanged. `bootstrap.sh` installs a separate
3.11 interpreter and venv under `/usr/local/lib/newbiegrader/` and preserves
existing firewall, Tailscale, disks and unrelated services.

`newbiegrader-worker@1.service` through `@4.service` each run one judge job at a
time. Each unit has one CPU, 1 GiB memory, no swap and a private 128 MiB /
4096-inode workspace tmpfs. `newbiegrader-judge.slice` caps the entire fleet at
four CPUs / 4 GiB / 512 tasks. Tests within a submission remain serial, with the
existing language memory allowances, 128 MiB declared-memory cap and 240-second
overall timeout. The API has its own 320 MiB / one-CPU budget.

Each instance reads `/etc/newbiegrader/worker-N.env`, with:

- `GRADER_JUDGE_WORKERS=1` and `GRADER_CAPACITY_DIR=/var/lib/newbiegrader/capacity/worker-N`.
- `GRADER_JOB_CGROUP_ROOT` and `GRADER_CGROUP_ROOT` pointing to its own unit under
  `/sys/fs/cgroup/newbiegrader.slice/newbiegrader-judge.slice/`.
- The shared durable `GRADER_SANDBOX_IDENTITY_DIR=/var/lib/newbiegrader/sandbox-identities`.

Capacity locks are separate because each unit has a separately enforced
allocation. UID reservations remain shared and append-only. Never copy an old
ledger over a newer one; use `merge_uid_ledger.py` while all workers are stopped.
The API reads the aggregate slice through `GRADER_CGROUP_ROOT` and reports four
worker slots; this changes neither its own cgroup budget nor judging semantics.

## Staging and activation

1. Install a reviewed source snapshot in a new root-owned release directory.
   Exclude credentials, private problems, reference solutions and operator notes.
   Install the pinned `requirements.lock` into the project venv, then run
   `deploy/host/precompile_runtime.py --release /opt/newbiegrader/releases/<release>`
   using `/usr/local/lib/newbiegrader/venv/bin/python` from the reviewed release.
   Precompiling the trusted runtime avoids parsing the same Python modules for
   every sandbox launch; runtime services continue to disallow bytecode writes.
2. Transfer configuration privately. Preserve `SESSION_SECRET`, OAuth settings,
   Supabase credentials and cookie settings. Set `GRADER_ACCEPT_JOBS=0` in API and
   worker configuration. Keep `/etc/newbiegrader/worker-enabled` absent.
3. Restore protected file roots into empty directories and verify hashes, modes,
   the exported catalog, all samples and PDFs. See the [file guide](BACKEND_PROBLEM_FILES.md).
4. Install the unit templates and loopback-only Nginx configuration. Remove the
   default welcome site before unmasking Nginx. Create a separate named tunnel;
   preserve any unrelated `cloudflared.service` and its metrics listener.
5. Run native kernel canaries, `verify-recovery.sh`, the 21-test file/verdict
   qualification, `verify-workers.sh` and the Linux critical gate. A skip,
   unsupported control or missing cleanup is a failure. Qualify all four
   synthetic worker allocations concurrently before enabling real consumers.
6. Verify the gated HTTPS transport, session continuity, CSRF, body limits and
   anonymous access boundaries. Stop admission on the previous active host,
   drain queued/running jobs and live leases, stop every previous consumer, and
   merge the final UID reservations before enabling the new workers.
7. Change the Pages service binding to the verified private bridge. Create the
   worker gate, enable exactly instances 1–4, open admission and verify real
   Python/C/C++ jobs and linked history over production HTTPS.
8. Verify reboot recovery, encrypted off-host recovery and the backup/watchdog
   configuration. Schedule operations on the active host only.

All execution protections remain mandatory: per-job cgroups, private numeric
UIDs, capability drop, seccomp endpoint denial, Landlock filesystem rules,
resource limits and descendant cleanup. Do not weaken these to make a check pass.

Application rollback uses a verified release on this PC with the current
protected files and UID ledger. Pause/drain before changing a release. The
application has no fallback to a retired hosting provider.

## Watchdog configuration

Install `/etc/newbiegrader/host.env` as root:root 0600 with the complete fleet:

```ini
NEWBIEGRADER_WORKER_UNITS="newbiegrader-worker@1.service newbiegrader-worker@2.service newbiegrader-worker@3.service newbiegrader-worker@4.service"
```

The watchdog reads this through its unit's `EnvironmentFile`. Without this
setting its compatibility default checks the old singleton unit. Preserve the
root-only webhook/token and host label, run `--check-only` with the same host
environment, then enable the backup/alert/health timers on the active PC.

## Automatic recovery and availability

Enable Tailscale, Nginx, API, the project tunnel and exactly worker instances 1–4
for boot. The production PC was rebooted and reconnected through Tailscale with
all four workers and the private tunnel active. Its unrelated tunnel is preserved.
For an always-on desktop host, install `server-sleep.conf.example` as
`/etc/systemd/sleep.conf.d/60-newbiegrader-server.conf`; this disables automatic
suspend/hibernation. Power must remain available; service startup does not turn
a physically powered-off PC on. Preserve existing Tailscale authentication and
verify device-key expiry policy separately from service enablement. The latest
2026-10-22 readback reports expiry on 2027-04-20. Review or disable device-key
expiry in the authorized tailnet administration for long-term unattended use;
local service enablement does not change that policy.

## Submission startup latency

Precompile each reviewed release and the dedicated runtime before activation.
The same synthetic 17-case workload took 7.6–8.3 seconds before preparation and
3.4–3.8 seconds afterward on this PC (two runs each for Python/C++). This is
startup evidence for short programs; expensive solutions and deep queues still
need their actual runtime. The subsequent execution-only refactor avoids
loading the HTTP/database stack for each isolated job and redundant Linux `ps`
samples after process exit. The same bounded workload now takes 2.82–3.03 seconds,
about 20% less than the already-precompiled baseline. Include `judge_execution.py`
in every application snapshot and container; it shares the existing grader and
feedback logic. See the [current measurement record](releases/pc-execution-performance-2026-10-22.json).

Workers immediately attempt the next durable claim after completing work, while
idle/outage backoff remains bounded. Browser polls for running jobs and the head
of the queue cap their scheduled wait at one second, with network time additional;
deeper queues retain traffic backoff. The
API has one CPU independently of the unchanged four-CPU judge slice. All test
cases, sandbox boundaries, language allowances and declared limits are preserved.

The public HTTPS verification used an existing verified operator session; it
did not repeat a fresh Google/OTP login. Both Python/C/C++ results and linked
history were checked. See [security validation](SECURITY_READINESS.md) for the
source fingerprint and the limits of these checks.
