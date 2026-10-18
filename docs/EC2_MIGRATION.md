# EC2 migration work log and runbook

## Phase A — initial evidence and plan (2026-10-18)

Branch: `infra/ec2-migration`, base `8845f4a`. Existing production is unchanged.
SSH uses the existing owner-only `~/.ssh/newbiegrader-judge.pem`; its contents
are never copied or displayed. Target instance identity was checked through
IMDSv2: `i-0e1c8c4d0256f541e`, t3.small, ap-southeast-2, x86_64. Ubuntu 24.04.4,
systemd 255, 1,907 MiB usable memory, no swap, approximately 17 GiB free on root.
Only SSH was listening publicly; UFW initially inactive. The cgroup v2 mount is
writable and cpu/memory/pids controllers are available. These observations alone
do not close S04. No AWS CLI credentials or instance IAM role were found, so
AWS security-group/EBS/credit-mode API inspection is currently unavailable.

Repository facts supersede old documentation: engine 2.0.6, production combined
role/local queue, Supabase project `qblnlfzjublfnnsasgpe`. Existing five queue RPCs
provide admission, claim, heartbeat, completion and diagnostics. API role already
refuses job execution. Worker uses a secret-free child environment; compiler and
program UID/GID drops, Landlock, seccomp, time/output limits and subreaper cleanup
must be retained. Persistent UID allocation state must not be reset.

### Plan

1. Establish a clean Linux/root baseline; prepare reproducible native Python 3.11
   runtime and root-owned releases. Keep the Ubuntu system Python unchanged.
2. Create independent systemd API and worker services with conservative memory,
   tasks and CPU ceilings. API uses a dedicated unprivileged account. The trusted
   worker supervisor needs root for the existing UID/GID drop; submitted programs
   and compilers must still execute without root/capabilities.
3. Add fail-closed per-job cgroups below a systemd-delegated private subtree,
   attaching a blocked supervisor before releasing its exec gate. Bound the
   worker's single-job workspace filesystem in bytes and inodes. Verify cleanup,
   child-process accounting, unavailable-control refusal and secret/network denial
   with bounded synthetic canaries on EC2. No public queue consumer is started.
4. Stage the API on loopback with admission disabled. Validate existing Supabase
   permissions/queue RPCs read-only; rehearse queue crash/retry in disposable
   PostgreSQL. Transfer only required credentials over authenticated SSH to
   root-only files; keep OAuth/API secrets out of worker and runner environments.
5. Prepare a loopback reverse proxy, bounded request bodies, explicit proxy trust,
   logs/health/reboot recovery and a configurable Pages backend origin. Keep the
   current JustRunMy fallback and live route untouched.
6. The operator owns no custom domain or DNS zone. Evaluate Quick Tunnel for
   staging HTTPS without inbound ports; its random hostname/restart behavior is
   a remaining production stability gate, not a permanent DNS solution.
7. Record actual tests, costs, access gaps and the cutover/rollback checklist.
   Request final approval before traffic changes, production queue consumption,
   destructive SQL, credential rotation, old-backend removal or paid expansion.

### Cutover and rollback boundaries

Final approval must cover a maintenance window: stop admission on the old backend,
inspect its actual local queue and drain it, stop its consumer, verify no active
leases, enable the new database worker and switch the Pages origin. Zero DB queue
counts alone do not prove a local queue is drained. Keep session signing secrets
and canonical OAuth callbacks unchanged. Do not allow simultaneous old/new
consumers against production work. Re-open admission only after synthetic smoke
checks pass under the new route.

Rollback: stop new admission and worker, inspect outstanding leases/results,
restore the old Pages origin and approved old-backend queue mode, then re-open
admission. Preserve all user rows, jobs and UID ledgers; never reset running jobs
or restore an older identity ledger to hide an incomplete migration.

Subsequent sections record executed work and remaining gates; a plan is not
deployment evidence.

## Executed staging checkpoint — 2026-10-19

**JustRunMy is still the production backend. Do not shut it down yet.** The
operator declined Cloudflare OAuth/named-tunnel/VPC provisioning at this
checkpoint. Preparation continues locally; no live route, public judge admission,
production queue claim, schema mutation or credential rotation was performed.

| Phase | Actual status |
| --- | --- |
| A discovery | Complete for repository and existing EC2; baseline recorded |
| B host preparation | Installed and verified; API/nginx/tunnel/health timer enabled |
| C S04 | Kernel controls and synthetic crash cleanup verified on EC2; production rollout remains OPEN |
| D backend | API active on loopback, database mode; worker preflight passed but consumer disabled |
| E Cloudflare | Temporary health-only HTTPS passed; permanent connection files prepared, authorization withheld |
| F Supabase/queue | Existing project unchanged; read-only connectivity/ACL/body checks and disposable SQL/concurrency tests passed |
| G tests | Results below; real login/cutover not verified; actual OS reboot/SSH recovery and persistent UID ledger checked |
| H cutover | Not performed; requires a stable approved connection and final approval |
| I rollback/docs | Prepared; a full traffic rollback exercise is not yet executed |

### Host and infrastructure changes

- Existing instance only; no extra EC2, EIP, LB, NAT, RDS, upgraded EBS or paid
  monitoring resource was provisioned. Actual volume is encrypted 20 GiB gp3,
  baseline 3,000 IOPS / 125 MiB/s, delete-on-termination enabled (Console read).
- AWS Console security rules show TCP 22 from one operator /32 only; outbound
  IPv4 permitted. No application/database ingress rule. UFW additionally denies
  inbound except OpenSSH. IMDSv2 required; no instance IAM role. No AWS API
  credential was obtained or permission expanded.
- Root-owned releases under `/opt/newbiegrader/releases`; managed CPython
  **3.11.17** under `/usr/local/lib/newbiegrader`, uv **0.13.1**, gcc/g++ 13.
  Ubuntu system Python remains unchanged. The 36 actual application packages
  are pinned in `deploy/ec2/requirements.lock`.
- API runs as `newbiegrader-api`, 320 MiB / 25% CPU; worker supervisor root,
  1 GiB / 100% CPU / 128 tasks, with only CHOWN/DAC_OVERRIDE/FOWNER/KILL/SETGID/
  SETUID capabilities. No CAP_SYS_ADMIN, privileged container or Docker socket.
- Journald storage bounded to 200 MiB persistent / 32 MiB runtime, seven days,
  with rate limits. Nginx/Uvicorn access logs disabled to avoid OAuth query
  credentials. A loopback health timer runs every minute. External alert
  delivery is **not configured**.
- Worker `ExecCondition` requires `/etc/newbiegrader/worker-enabled`, absent.
  API/worker configuration sets `GRADER_ACCEPT_JOBS=0`. The worker is not
  enabled for boot. Canary refuses to run once the worker enable flag exists.

### S04 controls and exact scope

`job_resources.py` creates one private job cgroup below the worker's delegated
systemd subtree; its supervisor lives in `/manager`. A child blocks at its exec
gate until attachment and membership verification succeed. All compiler,
runtime and descendant processes inherit that group. Default controls:

| Control | Verified value / behavior |
| --- | --- |
| Aggregate memory | 640 MiB per job, swap 0, `memory.oom.group=1` |
| CPU | `cpu.max=100000 100000` (one CPU); bounded throttle canary passed |
| Processes/threads | `pids.max=64`; bounded eight-task kernel probe passed |
| Workspace | Private tmpfs 128 MiB / 4,096 inodes, one active job guard; byte/inode ENOSPC passed |
| Deadline/output | Existing wall deadlines and 32 MiB output ceiling retained |
| Cleanup | cgroup.kill, populated=0 verification, reaping and workspace removal; failures poison the worker before another claim |
| Identity/filesystem | Fresh numeric UID/GID, empty groups, zero effective/ambient capabilities, Landlock ABI 7 on this host |
| Network | Mandatory seccomp endpoint/ptrace/io_uring denial; socket creation refusal verified |

The workspace quota is a dedicated per-worker filesystem with exactly one
active job, rather than a new filesystem mount for each test. Metadata caches
and the trusted API/worker remain outside that per-job filesystem but inside
their service budgets. Aggregate OOM can terminate the whole job runner; it is
reported as a job error, not falsely claimed as a proven per-test MLE verdict.
Existing per-test RSS/rlimit verdict logic remains in place. No chroot/PID/net
namespace guarantee is asserted. Root in the trusted supervisor is a remaining
trust boundary; submitted programs and compilers were verified unprivileged.

`GRADER_REQUIRE_NETNS=0` and the legacy acknowledgement flag are explicit because
systemd denies namespace creation and no CAP_SYS_ADMIN is granted. This does
**not** disable mandatory Landlock/seccomp/cgroup checks. Missing caps/controllers,
wrong delegation, ordinary unbounded directories or failed control readback
refuse execution. Required cgroups also refuse non-root worker boot.

Initial actual-host tests exposed a missing effective CAP_SETUID (0x6b rather
than the bounded 0xeb). Adding `AmbientCapabilities=CAP_SETUID` to the trusted
unit preserved its existing bounding set; post-drop effective and ambient
capabilities were verified zero. A startup guard now refuses that failure.
Another initial canary incorrectly expected OLE at 2 MiB; the engine correctly
allows up to 32 MiB. The test now writes bounded chunks beyond that actual limit.
These earlier failures are not counted as passing runs.

### Secrets, state and persistence

Existing credentials were transferred privately from the authorized old provider
through SSH stdin to root:root 0600 `/etc/newbiegrader/api.env` and `worker.env`
under a 0700 directory. No value is in this report, Git or process argv.

API credential names: SUPABASE_URL, SUPABASE_KEY, SUPABASE_AUTH_KEY,
SESSION_SECRET, GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI,
FRONTEND_URL, ADMIN_EMAILS and session/CORS settings. Worker holds only
SUPABASE_URL, SUPABASE_KEY and the existing SESSION_SECRET required by the
separated-role validator. Runner children receive a separate secret-free
environment; API/OAuth credentials are not inherited by compiler/programs.
Use the reviewed `.env.example` files in `deploy/ec2` for nonsecret settings.

The old host UID ledger was read under its allocator lock and its reservations
merged without resetting the AWS ledger. Earlier staging canary reservations
were merged too. Canary and worker now share one durable root-only ledger.
`merge_uid_ledger.py` appends only increasing reservations, rejects partial,
empty-existing, symlink and permissive ledgers, and never lowers the high-water
mark. **Repeat the final snapshot/merge after old admission is stopped and the
local queue drained.** Never restore an older ledger after a failed rollout.

Application history, users, problems, Storage and queue remain in the same
Supabase project. No production data was copied, rewritten or deleted. The five
production queue functions have the same bodies, argument definitions and
security configuration as this schema; anon/authenticated lack execute and
service_role retains execute. The functions are SECURITY DEFINER with fixed
search_path, not SECURITY INVOKER. Their read-only diagnostics passed through
both staged API and actual worker preflight. No production claim/admit RPC was
called. Disposable tests cover stale owners, retries, idempotent completion and
atomic history writes; that is not a claim of exactly-once execution after crash.

### Recorded verification

| Command / environment | Observed result |
| --- | --- |
| Clean tracked baseline, Docker Linux arm64/root, Python 3.11, network none | 244 run: 241 pass, 3 module skips |
| Candidate `python -m unittest discover -s tests -v`, same isolation | 261 run: 258 pass, 3 private-problem module skips |
| `python tools/run_critical_tests.py`, Docker Linux/root | 187/187 pass, zero skips |
| Actual EC2 x86_64/root Python 3.11, full unittest suite | 261 run: 258 pass / 3 private-problem module skips, 72.849s; includes the last non-root boot check |
| Critical command on actual EC2 | 187/187 pass, zero skips, 63.678s |
| `systemctl start newbiegrader-canary` on EC2 | 11/11 pass, zero skips; memory/pids/CPU/quota/identity/network/output/cleanup |
| `deploy/ec2/verify-recovery.sh` on EC2 | Synthetic manager SIGKILL: descendants/cgroup/workspace removed; API PID unchanged; 11/11 passed after restart |
| `deploy/ec2/verify-worker.sh` on EC2 | Actual worker hardening + credentials preflight success, no job claim; enable flag still absent |
| PostgreSQL 17 disposable, network none | Schema twice, queue_sql.sql, security_sql.sql, auth_sql.sql passed |
| `tests/auth_concurrency.py --container newbiegrader-ec2-sql` | 8 budget clients → one send allowed; 8 identity claims → one row |
| `tests/queue_concurrency.py --container newbiegrader-ec2-sql` | 4 admissions / 8 clients → 4 distinct claims; expired lease recovered, stale finish denied, duplicate finish idempotent |
| `node --test tests/test_*.js` on macOS | 53/53 pass, no skips; includes prepared Pages and VPC bridge tests |
| Frontend syntax/ID/style checks; Python compileall | Passed |
| Local problem validator on macOS | 68/68 existing reference packages passed; compatibility check, not Linux isolation evidence |
| pip-audit of all 36 EC2 package pins | No known vulnerabilities reported at this checkpoint; no security guarantee |
| Docker build + network-none packaging smoke | Image built; resource module imports; packaged plagiarism self-test 4/4 pass |

No real user code or dangerous escape payload was executed. Synthetic canaries
contain fixed bounds; the intended job OOM was confined to its child cgroup.
Unit mocks verify fail-closed decisions; real kernel canaries verify enforcement.
The three omitted private-package modules are `test_api_e2e`, `test_judge_limits`
and `test_problems_supabase`; their skip reasons are recorded, not counted as
passes. The independent critical suites and EC2 canaries use versioned synthetic
fixtures and do not depend on those modules.

HTTP vantage points: EC2 loopback `/api/health` 200/68, `/api/version` engine
2.0.7 / API role / database queue / Supabase source. Audit Mac external internet
→ temporary HTTPS health 200/68; `/api/auth/me` and `/api/submit` 404 at Nginx.
EC2 anonymous job lookup returned 401. Twenty-five loopback health probes during
the isolation suite all returned 200, measured p95 0.561s / max 1.665s; this is
not a sustained load/SLA test. A separate audit-Mac urllib request to production
Pages `/api/version` returned 403; it does not establish backend failure or
direct reachability. Read-only **inside JustRunMy loopback** confirmed production
engine 2.0.6, combined/local queue, Supabase source, 68 problems, 85 MiB effective
memory cap. AWS staging's configured effective cap is 128 MiB.

### Costs — USD, 730 hours/month, before credit/tax/traffic

Official Sydney Linux On-Demand t3.small price is $0.0264/hour → **$19.27**.
One public IPv4 at $0.005/hour → **$3.65**. Actual 20 GiB gp3 at Sydney
$0.096/GB-month → **$1.92**, baseline IOPS/throughput included. Estimated fixed
subtotal **$24.84/month**. Stop/start may change the auto-assigned public IP;
an EIP was not allocated. Supabase/Cloudflare existing-plan usage, storage,
traffic, snapshots if later approved and CPU surplus are additional.

Console confirms **T3 Unlimited**, unchanged. Surplus CPU can cost
$0.05/vCPU-hour. T3 small baseline is 0.4 vCPU aggregate; a continuously busy
1-vCPU judge alone can add roughly $21.90/730h after credits are exhausted,
with API/tunnel/OS demand additional. Standard mode avoids surplus charging but
can throttle and cause false wall-time TLEs; do not switch without a credit-
exhaustion performance rehearsal and an operator decision. No assertion is made
that trial credits cover charges. Use the existing AWS Billing/CPU credit
dashboards; no paid monitor or automatic scaling was enabled.

Pricing evidence: [Sydney EC2 public price map](https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ec2-ondemand-without-sec-sel/Asia%20Pacific%20%28Sydney%29/Linux/index.json),
[regional AWS price list](https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/AmazonEC2/current/ap-southeast-2/index.csv)
(gp3 storage SKU QR74UAP3E9WUYT9B), [public IPv4](https://aws.amazon.com/vpc/pricing/),
[T3 credits](https://aws.amazon.com/ec2/instance-types/t3/).

### Reproduction / service management

From an approved source release on Ubuntu 24.04, run as root:

```sh
sh deploy/ec2/bootstrap.sh
/usr/local/lib/newbiegrader/bootstrap/bin/uv pip sync --python /usr/local/lib/newbiegrader/venv/bin/python deploy/ec2/requirements.lock
# Privately provision /etc/newbiegrader/{api,worker}.env before starting units.
# Install reviewed .service/.timer files into /etc/systemd/system, daemon-reload.
systemctl enable --now newbiegrader-api.service newbiegrader-health.timer
sh deploy/ec2/verify-worker.sh
systemctl start newbiegrader-canary.service
sh deploy/ec2/verify-recovery.sh
```

Only after reviewing the staging exposure:
`sh deploy/ec2/install-staging-tunnel.sh`. It installs pinned cloudflared and
the health-only listener, never a production origin. For the stable option,
see [EC2_CLOUDFLARE_SETUP.md](EC2_CLOUDFLARE_SETUP.md); approval is currently absent.

Read-only diagnostics: `systemctl show <unit> -p ActiveState -p Result -p MemoryCurrent`,
`journalctl -u <unit>` (inspect locally; do not paste credentials/queries),
`ss -lnt`, `df -h`, `systemctl list-timers`, and loopback health/version.
Never use `systemctl show -p Environment`, `/proc/*/environ`, or `cat *.env`
as a report command. Worker preflight reads configuration without displaying it.

### Remaining gates before closing JustRunMy

1. Authorize and verify a stable HTTPS/Cloudflare connection, including tunnel
   restart and real Pages cookie/CSRF/IP/redirect behavior. Prepared bridge code
   is tested locally but **not deployed**; named tunnel does not exist.
2. Approve a maintenance window; implement/verify an admission block on the
   **currently deployed old backend**, then inspect/drain its actual local queue.
   Merely setting a provider env variable without restarting its old code is
   not an admission fence. Do not restart/drop active local jobs to fake drain.
3. Stop old consumer, take final UID snapshot/append, verify queue leases, enable
   exactly one AWS consumer and switch Pages only after explicit final approval.
   Then run authorized synthetic end-to-end jobs, operator Google/OTP login,
   practice/contest feedback and history/rejudge checks through the live chain.
4. Actual OS reboot and SSH recovery passed with the same UID ledger. Post-reboot
   API/nginx/tunnel/timer recovery, source fingerprint, external HTTPS health and
   all 11 isolation canaries passed again; worker stayed disabled. Stop/start
   (which can change the public IP) has not been executed; keep the Console
   instance-ID lookup procedure available rather than relying on a fixed IP.
5. Configuration/UID state now has a verified encrypted off-host backup on the
   audit Mac (details below). Supabase DB, private Storage and versioned problem
   asset backup/restore still need confirmation. No production restore,
   scheduled off-host backup or alert delivery is verified. Do not buy snapshots
   or modify production retention without approval.
6. Keep JustRunMy available during an agreed observation window. Only retire it
   after success criteria hold and the user explicitly approves its removal.

### Rollback commands and safeguards

The current staging can be stopped without affecting production:

```sh
sudo systemctl disable --now newbiegrader-staging-tunnel.service
sudo systemctl stop newbiegrader-worker.service
sudo rm -f /etc/newbiegrader/worker-enabled
```

After a future cutover, first set API admission to 0 and restart only the API,
drain or stop/fence the AWS consumer and inspect outstanding database leases.
Restore the reviewed old Pages origin and compatible old backend; verify its
session/queue configuration before reopening admission. Jobs already in the
database must be reconciled/finished by the database consumer, not silently
resubmitted into a local queue. Do not erase jobs, history, Storage or ledgers.

Code rollback uses a prior root-owned release directory and atomic `current`
symlink replacement, followed by API restart. Keep the worker disabled until its
isolation contract is reverified; never restore a less-restrictive worker just
to regain availability. No Git reset/force-push or production DB restore is
part of routine rollback. Operator approval is still required for live changes.

## Final staging source and reboot evidence

Frozen root-owned release on EC2:
`/opt/newbiegrader/releases/6cba18c68366993fed7fc7572c87368bbb773ea9`, selected by
the atomic `/opt/newbiegrader/current` symlink. Application fingerprint returned
by `/api/version` matches local source:
`543f8fba5e783c3748d7a45a32fbe6e82e2bfb41176ac5f4775306cf9239b6f3`.
The later audit-document commit does not change those executable sources.

An actual OS reboot changed the kernel boot ID; SSH recovered after roughly
15 seconds of retry intervals. The UID ledger hash was identical before/after
reboot. API, Nginx, tunnel and timer started automatically. Worker stayed
inactive/disabled with no enable flag. The actual worker preflight and all
11 kernel canaries passed after reboot. EC2 loopback health/version returned
200 with 68 problems and the expected fingerprint; the audit Mac's external
HTTPS probe also returned 200/68 using normal certificate validation.

The Quick Tunnel hostname changed across reboot, confirming why it must not be
used as the permanent Pages origin. No production traffic was switched. A host
stop/start was not performed and can change the auto-assigned public IP; use
the instance ID in the AWS Console to rediscover it. Do not change SSH host-key
verification to work around a different or unverified machine.

Local commits (none pushed by this migration):

- `8bceb7d`: inventory and gated rollout plan.
- `cbfc28a`: delegated job containment, admission pause and fail-closed checks.
- `9e52b26`: real PostgreSQL concurrent queue/lease rehearsal in CI.
- `855ed85`: prepared Pages/Worker routing and tests; no live cutover.
- `6cba18c`: EC2 units, bootstrap, pinned runtime, canaries and UID migration.
- `335fe9d`: encrypted off-host configuration/UID backup and CI syntax coverage.

Evidence logs are private under the audit Mac's
`~/.local/share/newbiegrader-validation/ec2-migration-79vf4btl/`; they contain
test metadata/synthetic fixtures, not production credentials or user code.

### Encrypted off-host state backup

`python3 deploy/ec2/backup_state.py` was executed on the audit Mac using official
Homebrew `age`. It holds a shared allocator-directory lock on EC2 and streams a
fixed five-file tar archive through SSH directly into age encryption. No
plaintext tar, configuration value, SSH private key or user data is written to
the repository or printed. The private backup identity remains on this Mac.

Private directory: `~/.local/share/newbiegrader-private/ec2-backups/` (0700).
`backup-identity.txt` is 0400; timestamped `.tar.age` files are 0600. Archive
contents: API/worker environment files, their two systemd unit files and the
numeric UID reservation ledger. Authenticated decryption and an **in-memory**
restore inspection verified all five expected members, root ownership, private
environment modes and increasing ledger records. No plaintext was extracted.

This is one local off-host copy, not scheduled disaster recovery or a Supabase
DB/Storage backup. Keep a separately protected offline copy of the backup
identity; losing both the Mac and identity makes these archives unrecoverable.
Never upload the identity to EC2/Git or send it in chat. A real restoration must
preserve current/newer UID reservations using append/merge, not replace the
ledger with this older snapshot. Restore credentials only to approved root-only
paths after reviewing source/target identity. Never decrypt the archive to stdout
in a recorded terminal; use a private restore environment and inspect names only.
