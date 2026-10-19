# EC2 migration work log and runbook

## Current checkpoint — AWS production cutover verified (2026-10-19)

The operator explicitly authorized production cutover and then stopping
JustRunMy, stating its queue was empty. **Production now uses AWS.** JustRunMy
application 69356 is stopped, not deleted; persistent volume 65068 at
`/var/lib/newbiegrader` remains for rollback. No credentials were rotated and no
existing user data was deleted. The original HTTPS port mapping was preserved.

Executed sequence and evidence:

1. Tested the provider's advertised port-update behavior **without a restart**:
   removing bindings still returned HTTP 200 on three old-origin probes. The
   original mapping was restored. This did not fence admission and is not
   counted as a successful drain. After the operator's explicit stop approval,
   captured the locked old UID ledger (22 records), stopped the application,
   and verified `isStarted=false`. The earlier real admin overview showed zero
   queued/running/backlog; no atomic in-process drain control is claimed.
2. Merged the final old UID reservations into the disabled AWS worker ledger:
   zero additional records were needed, because its high-water mark was already
   greater. No ledger reset. Installed production Nginx on **loopback 8081**.
3. Deployed a separate **private production Worker**,
   `newbiegrader-aws-production`, with public/preview URLs disabled and its own
   server-only shared key. Existing Pages `newbiegrader` now uses
   `BACKEND_TRANSPORT=service`, `BACKEND_SERVICE` pointing at that Worker and
   the matching Pages secret. No custom domain or public EC2 app port.
   The existing specific VPC Service now targets 127.0.0.1:8081 over the existing
   named tunnel. Production deployment at verification was
   `dded0f35-2665-4211-a016-d4825916f0ed` (later Git deployments may supersede it).
   Cloudflare required equal `fail_open` settings in production and preview;
   both were set false after the first rejected configuration request.
4. Verified zero queued/running/live leases, passed the actual worker preflight
   and **11/11 EC2 kernel canaries**, then enabled exactly one database worker
   and API admission. Production `/api/version` reports 2.0.7, role `api`, queue
   `database`, Supabase source and 68 problems; backend fingerprint is unchanged
   from the staged release. Source release remains the root-owned `6cba18c…`.
5. Used the operator's legitimate existing browser session, then completed a
   **fresh real Google OAuth login** as that same account. No token/cookie was
   extracted and no admin session was forged. Normal production forms executed
   newly authored Python, C and C++/STL playground files with synthetic stdin.
   Each finished `OK`, first attempt, with the expected output. Initial C++
   output comparison failed because the native textarea submitted CRLF; the
   recorded input proved it. A repeat without a final line ending matched
   exactly. Do not count that first byte comparison as a pass.
6. Submitted an intentional synthetic `#error` C++ file through the normal UI:
   async queue/poll completed with CE, linked to **exactly one** persisted
   submission and visible in owner history. It never executed hidden inputs.
   No real user's program or existing reference solution was run. File uploads
   were used so the operator's editor drafts were not overwritten.
7. Paused AWS admission, restarted API, verified zero queued/running/live leases,
   and **rebooted EC2 with the real worker enabled**. SSH recovered in **30.3 s**;
   API, Nginx, tunnel and worker all restarted automatically; the UID ledger hash
   was unchanged. With admission still paused, stopped the idle worker, ran all
   **11 kernel canaries again**, restored its gate and reopened admission. A
   fresh authenticated Python run then returned the expected canary output.
   Actual worker private workspace and delegated cgroup checks found zero
   leftover job directories/groups. Last queue readback: **45 done, zero queued,
   running or live leases** (39 prior jobs plus six synthetic migration jobs).

Production anonymous HTTPS checks **15/15** passed, including cookies, CSRF,
body bounds, Google redirect/state rejection and unauthorized execution denial.
The staging key gate still passed **17/17** after switching VPC to port 8081.
Anonymous problems/languages JSON and a public statement PDF (valid `%PDF-`,
103,068 bytes) also returned successfully. Vantage: operator Mac on its normal
external internet connection via curl with ordinary TLS verification; real login
and form checks used the existing native Chrome profile.

Final local Linux arm64/root, network-disabled Docker suite: **269 run, 266
passed, three private-problem modules skipped**; separate critical suite
**189/189, zero skips**, Node **61/61, zero skips**. Two new smoke-CLI tests also
passed on macOS and verify production never requires/sends the staging secret.
An initial full and critical attempt each failed one compiler-deadline test:
the new in-process CLI test had left `umask=077`, making later root-owned compiler
fixtures unreadable. Its teardown now restores the original mask; both entire
suites were rerun and passed. No sandbox control was disabled or engine changed.
Python compilation, frontend guards and plagiarism self-test passed. The clean
snapshot's validator returned zero with no private packages; this is **not** a
new 68-problem/reference validation claim.

Fresh post-cutover logical DB backup/recovery passed: snapshot archive
`20261019T010725Z-postgres-snapshot.dump.age`, 792,423 encrypted bytes, dump 10.8 s,
51 table/partition content comparisons, 58 relation/ACL/RLS definitions and 150
constraints matched. The disposable recovery container/tmpfs was removed.
Configuration/UID/tunnel backup `20261019T011231Z-0e5f224a.tar.age` was decrypted
successfully. A separate nine-member encrypted Cloudflare recovery archive,
`20261019T011501Z-cloudflare-production.tar.age`, preserves the new server-only
key/config and before/after metadata; no OAuth/SSH/age private key is included.
Earlier Storage file-byte recovery remains separate. See `EC2_BACKUP_RESTORE.md`.

**Scope:** this establishes the executed migration and listed functionality,
not a guarantee that every judge verdict, feature or security finding is correct.
S04 now has hard aggregate **job-budget** containment; its fixed 640 MiB ceiling
is not a dynamically enforced per-test memory verdict for descendants. See the
updated audit note. Live OTP email delivery, in-flight production crash/lease
recovery, sustained load, credit-exhaustion performance, external alert delivery
and full hosted Auth/Storage restoration were not tested here. Cloudflare VPC
remains open-beta/free-during-beta, not a permanent price/SLA guarantee. T3
Unlimited and the estimated $24.84/month fixed AWS subtotal remain unchanged.

### Current operational controls

- Readiness: `python3 deploy/ec2/smoke_https.py --production --expected-samesite none`.
  It performs anonymous/synthetic checks only, not real login or job execution.
- API/worker: `systemctl status newbiegrader-api.service newbiegrader-worker.service`;
  independent services, worker enabled and one concurrent job.
- Maintenance: set only API `GRADER_ACCEPT_JOBS=0` privately, restart API, inspect
  database diagnostics until queued/running/live leases are zero, then stop worker.
  Keep the ledger and completed rows intact. Resume by restoring the worker gate,
  starting worker and setting API admission to 1. Never print complete env files.
- Rollback: fence/drain AWS first; reconcile durable jobs and append the **latest
  AWS UID reservations to the old persistent volume** before any old judge
  execution. The old image lacks cgroups, so read-only API rollback is the safe
  default; do not silently reopen its less-contained judge. Restore the saved
  Pages origin/transport only after the old API is healthy, using the preserved
  provider image/env/ports. A Pages deployment rollback does not restore project
  configuration, secrets, queue state or UID reservations. Do not run both workers.
- Keep the stopped old application/volume during initial observation. No old
  application, volume, database row or credential was deleted. Retiring that
  retained rollback state is a separate destructive action.

## Earlier checkpoint — logical DB recovery verified (2026-10-19)

Operator-provided libpq files are regular 0600 files. Initial TLS verification
failed because Supabase's CA was absent from system roots; the project's actual
dashboard certificate link supplied the CA. `verify-full` authentication then
succeeded. The session pooler ignored the requested read-only `PGOPTIONS`
default; explicit read-only transactions were verified instead. No source
permission change, password reset or database write was made.

A repeatable-read read-only exported snapshot produced an age-encrypted full
logical dump: **791,071 bytes / 10.9 seconds**. Actual restore into a separate
network-disabled Supabase PostgreSQL 17.11 container passed. Source/restored
comparison matched **51 table/partition counts/content hashes, 58 relation
owners/ACL/RLS definitions, 150 constraints, zero explicit policies and eight
public functions**. Two local extension monitoring views needed their captured
owner/grantor defaults restored before the final metadata comparison matched.
Source was unchanged. Details, limitations and exact encrypted recipe location:
`EC2_BACKUP_RESTORE.md`. This is logical DB recovery, not a running managed
Auth/Storage service rehearsal. Earlier Storage byte recovery remains separate.

The operator's existing Chrome profile displayed an authenticated legacy admin
overview with **zero queued/running/backlog** when inspected. This is a point-in-
time observation before an admission fence, not proof of a drained migration
window. The separate automation profile's earlier 403 is historical evidence.
Final cutover still requires a verified old admission fence, fresh in-process
queue readback under that fence, final backup/UID merge and explicit approval
for production routing/worker enable and authenticated smoke tests. JustRunMy
and production Pages remain unchanged; AWS public admission/worker remain off.

After the DB rehearsal, the unchanged application snapshot was retested in a
network-disabled Linux arm64/root Docker container: **267 tests, 264 passed,
three private-problem-module skips**. The separate critical gate passed
**187/187 with zero skips**; Node passed **61/61 with zero skips**, frontend
syntax/ID/style checks and plagiarism self-test 4/4 passed. These overlapping
suite counts are not additive. No real problem/reference validator or user
submission was run; this checkpoint changes documentation only. Changed-file
Gitleaks scan and `git diff --check` passed. These local follow-up changes were
not pushed; the approved original seven-commit remote range is unchanged.

## Earlier checkpoint — operator-only API rehearsal (2026-10-19)

Production remains on JustRunMy. The separate Pages staging API now requires a
private test key; missing/wrong credentials were actually denied before enabling
the private Worker's full API mode. VPC targets loopback port 8082. This opens
no public submissions: AWS API admission remains zero, the consumer is inactive,
and its enable file is absent. See `EC2_CLOUDFLARE_SETUP.md` for exact fences.

- **17 actual HTTPS smoke checks passed** on the audit Mac, including canonical
  Google redirect, session attributes, two logout cookies, CSRF, anonymous
  admin/job/submit/run rejection and the 1 MiB body cap. Real Google/OTP login
  and authenticated submission/history remain unverified.
- The copied legacy session setting is **SameSite=None, Secure, HttpOnly**.
  An initial Lax expectation failed and was corrected to explicitly check the
  actual existing setting. No proxy cookie loss was demonstrated.
- Temporary Nginx metadata-only probes confirmed a single unchanged client IP
  despite XFF/X-Real-IP spoofing, and both keys stripped. Temporary logs/config
  were removed; access logging is off. CF-header combined probe 403 origin/layer
  is unverified; earlier transient probe failures are excluded from passes.
- **11/11 actual EC2 isolation canaries passed this round**, zero skips. Linux
  arm64/root disposable Docker suite: **267 run, 264 pass, 3 skipped** (private
  problem modules); critical **187/187, no skips**, overlapping that full suite.
  Node **61/61**, zero skips. Storage recovery synthetic tests **4/4** on macOS.
- Read-only production diagnostics after anonymous smoke tests still showed
  **39 completed jobs, zero running/leased**. This does not establish that the
  old in-memory queue is drained.
- Re-read the deployed old `_create_job` and `_lifespan` through provider MCP:
  it has **no admission-pause flag** and shutdown cancels its async workers.
  Provider port/env changes require a restart. A proper old admission fence and
  authenticated inspection of its actual in-process queue remain cutover gates;
  neither an environment edit alone nor database counts prove safe drain.

Storage file-byte backup/recovery **passed**: 2,679 objects / 185,493,091 bytes,
all restored hashes matched, plaintext temporary files removed; encrypted archive
0600 on the FileVault-protected Mac. This does not prove DB/managed Auth/Storage
API recovery. The PostgreSQL dump connection remains unavailable until the
operator-provided libpq files exist. Browser admin overview returned 403 in the
automation profile; authenticated old in-process queue counts remain unverified.
Actual OS reboot was repeated after the gated API setup and complete Storage
backup. SSH recovered in **24.0 seconds**, boot ID changed and the UID ledger hash
was unchanged before new canaries ran. API/nginx/named tunnel recovered;
application/metrics ports remained loopback-only. The worker stayed inactive,
its enable flag absent. Post-reboot **11/11 kernel canaries** and **17/17 HTTPS
smoke checks** passed again. A fresh encrypted configuration/UID/tunnel backup
was taken after those canaries. No EC2 stop/start or address-stability guarantee
is asserted.

New local review commits: `b0c3f39` (gated HTTPS API rehearsal), `be856ff`
(encrypted Storage byte recovery). No additional branch push or main merge was
performed; only the earlier approved seven-commit range is on origin. Changed
file secret scanning returned zero findings.

No production route, queue claim, old-backend deployment, credential rotation,
paid AWS resource or public judge enable occurred in this checkpoint.

## Earlier checkpoint — stable health-only HTTPS staging (2026-10-19)

This checkpoint supersedes earlier notes saying Cloudflare connection approval
was withheld. The latest task authorized safe staging setup and pushing the
seven reviewed migration commits. **Production still uses JustRunMy.**

- Installed official Cloudflare skills/MCP and completed OAuth; all four MCP
  tools were exercised. Details: `CODEX_MCP_SETUP.md`.
- Deployed a separate Pages project, `newbiegrader-aws-staging`, with an explicit
  service binding to a private Worker, a specific VPC Service and a named tunnel.
  Stable URL: `https://newbiegrader-aws-staging.pages.dev/api/health`.
  No public Worker route or EC2 application port; no custom domain required.
- Actual audit-Mac curl GET returned 200 / 68 problems before and after a named
  tunnel restart at the **same** URL. Auth/jobs/submit/run probes returned 404.
  HEAD health is 404 both directly on EC2 and through Pages: the existing API
  defines GET only. Initial urllib 403 and rejected future compatibility date
  are recorded in `EC2_CLOUDFLARE_SETUP.md`, not counted as passes.
- Named tunnel readback returned healthy / four connections after reconnection;
  systemd is enabled/active. Nginx/API remain loopback-only. Real worker remains
  inactive, its enable flag absent, and admission disabled. No production queue
  claim/admit or user submission was executed.
- Existing Pages production canonical deployment remained
  `ec40128a-991f-418b-916d-a1951180723d` before/after staging creation. Private
  Worker readback confirms public subdomain and preview URLs disabled.
- Account is Workers Free / $0 current plan. VPC is free **during open beta**;
  no permanent free-price/SLA claim is made. No paid AWS resource was added.
- Pushed exactly the seven reviewed commits (`8bceb7d` through `0fdfae2`) to
  `origin/infra/ec2-migration`; remote head was verified. Gitleaks scanned that
  commit range with complete redaction: zero findings; no AGENTS.md/private
  credentials/artifacts were included. No main merge or production deploy.
- Expanded the encrypted state backup with an explicit `--include-tunnel` option.
  Actual new archive was decrypted only in memory: seven fixed members, root
  ownership, 0600 environment/token files; no plaintext extraction. Two synthetic
  regression tests cover opt-in file selection and private-directory refusal.

This round reran the clean tracked/synthetic snapshot on Linux arm64/root in a
network-disabled disposable Docker container (Python 3.11): **263 run, 260 pass,
3 skipped** (`test_api_e2e`, `test_judge_limits`, `test_problems_supabase`, which
need private problems). The separate critical gate passed **187/187, zero
skips**; these overlap the full suite and must not be added to its total. Node
on the audit Mac passed **57/57, zero skips**. The two new backup tests also ran
on macOS: 2/2. Python byte-compilation and frontend syntax/ID/style guards passed.
No kernel isolation changes were made this round; the previous 11 post-reboot
EC2 canaries remain prior-checkpoint evidence, not a new execution claim.

Supabase MCP read-only inspection returned PostgreSQL 17.11. A database dump
connection is not currently configured in local connection variables, `.env`,
`~/.pgpass` or `~/.pg_service.conf` (only presence/names checked). MCP SQL access
and API service keys do not by themselves provide a pg_dump connection. DB and
Storage backup/restore remains **UNVERIFIED**; see `EC2_BACKUP_RESTORE.md`.

New follow-up commits remain local for review: `285a5fe` (private service-binding
transport) and `efb1e2e` (encrypted tunnel backup). Only the explicitly approved original seven
were pushed. Changed-file secret scanning found zero findings. A broader tracked
snapshot scan also flagged one existing baseline document's public 64-hex source
fingerprint; it was checked as a fingerprint, not treated as a leaked credential.
No scan result is proof that every historic secret is absent.

Current gates: finish backup/restore verification; prepare and approve the old
local-queue maintenance/drain; approve controlled full-chain login/submission
verification and final route change. Do not disable JustRunMy yet.

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

## Earlier staging checkpoint — before Cloudflare authorization (2026-10-19)

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
see [EC2_CLOUDFLARE_SETUP.md](EC2_CLOUDFLARE_SETUP.md). Named health-only staging
is now deployed; full API/cutover approval remains separate.

Read-only diagnostics: `systemctl show <unit> -p ActiveState -p Result -p MemoryCurrent`,
`journalctl -u <unit>` (inspect locally; do not paste credentials/queries),
`ss -lnt`, `df -h`, `systemctl list-timers`, and loopback health/version.
Never use `systemctl show -p Environment`, `/proc/*/environ`, or `cat *.env`
as a report command. Worker preflight reads configuration without displaying it.

### Remaining gates before closing JustRunMy

1. Stable health-only HTTPS and named-tunnel restart are now verified through
   the separate staging Pages project. Real Pages cookie/CSRF/IP/redirect and
   login/submission behavior remains unverified; production binding is unchanged.
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
sudo systemctl disable --now newbiegrader-tunnel.service
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

Original migration commits (the seven-commit range ending at `0fdfae2` was
pushed to `origin/infra/ec2-migration` at the latest checkpoint):

- `8bceb7d`: inventory and gated rollout plan.
- `cbfc28a`: delegated job containment, admission pause and fail-closed checks.
- `9e52b26`: real PostgreSQL concurrent queue/lease rehearsal in CI.
- `855ed85`: prepared Pages/Worker routing and tests; no live cutover.
- `6cba18c`: EC2 units, bootstrap, pinned runtime, canaries and UID migration.
- `335fe9d`: encrypted off-host configuration/UID backup and CI syntax coverage.
- `0fdfae2`: final original staging results and cutover gates.

Evidence logs are private under the audit Mac's
`~/.local/share/newbiegrader-validation/ec2-migration-79vf4btl/`; they contain
test metadata/synthetic fixtures, not production credentials or user code.

### Encrypted off-host state backup

`python3 deploy/ec2/backup_state.py` was executed on the audit Mac using official
Homebrew `age`. It holds a shared allocator-directory lock on EC2 and streams a
fixed five-file tar archive through SSH directly into age encryption. After
named-tunnel provisioning, `--include-tunnel` was run to include its token and
unit: seven members were verified in memory. The five-file mode remains usable
before a named tunnel has been installed. No
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
