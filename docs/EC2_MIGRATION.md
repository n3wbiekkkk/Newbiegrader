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
