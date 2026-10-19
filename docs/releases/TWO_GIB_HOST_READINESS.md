# Two-GiB host: observed state and single-worker release gate

2026-10-19. The initial resize review was read-only. A subsequent explicitly
approved bounded maintenance ran synthetic single-worker qualification and
restored production. No instance, security rule, credit mode, route or
application release was changed. See the qualification record below.

## Confirmed hardware

The user has confirmed **t3.small** as the selected instance type, matching the
refreshed Sydney EC2 Console observation for `i-0e1c8c4d0256f541e`: Running,
**3/3 checks passed**, Public IPv4 **15.135.225.193**, credit specification
**unlimited**. The earlier instance-family discrepancy is resolved. These are
recorded observations from the resize review, not a fresh status probe in this
documentation-only clarification. No further resize is planned.
The previous 3.25.235.29 SSH endpoint timed out. SSH to the new address succeeded
with strict checking against the original known host key; no new key trust,
Security Group change, Elastic IP or public backend listener was introduced.

Native read-only inspection: x86_64, 2 logical CPUs, MemTotal 1951736 KiB
(about 1906 MiB usable), MemAvailable 1423440 KiB, no swap. API, existing
singleton worker and tunnel active; admission=1, database queue, Supabase source,
explicit worker count=1, declared memory cap=128 MiB. Both service memory.events
have zero OOM/oom_kill; system oom_kill since boot=0. These are idle snapshots,
not peak-load or post-resize judge-isolation qualification.

Loopback health=200. One normal curl from the macOS audit machine outside AWS
VPC through existing Pages also returned 200 in 2.139317 s. No public backend
request, user submission or queue mutation was used. The private route recovered
without depending on the old public IP. Source: [sanitized observation](two-gib-host-observation.json).

## Budget: retain the existing singleton settings

| Boundary | Existing/proposed retained limit | Accounting |
| --- | --- | --- |
| API service | MemoryMax=320 MiB, CPUQuota=25% | Existing service; idle current 78331904 bytes |
| Worker service | MemoryMax=1024 MiB, CPUQuota=100% | Existing service; idle current 67338240 bytes |
| Job aggregate | Default memory.max=640 MiB, pids.max=64 | Inside worker budget; not another host allocation |
| Workspace | Dedicated tmpfs 128 MiB / 4096 inodes | Service accounting includes charged pages; do not add a second worker |
| Submission declared cap | 128 MiB | Preserve existing language/headroom and verdict semantics |
| OS, tunnel, Nginx and cache | About 562 MiB after both service maxima | Calculation from usable MemTotal, not a measured safety margin |

API+worker maxima total 1344 MiB. This leaves roughly 562 MiB on the observed
host; it is a proposed upper-budget check, not proof that memory pressure cannot
occur. The 640-MiB safety boundary is not a complete dynamic declared-memory
limit (S04 remains open). Do not enable a metadata publisher, mirror, compilation
concurrency or second worker on this budget as part of the release.

A local Linux ARM64 Docker capacity calculation with 2048-MiB/2-CPU limit,
explicit GRADER_JUDGE_WORKERS=1 and GRADER_MEMORY_CAP_MB=128 passed for:

- Whole-host 2048/1906 MiB: one worker, cap 128.
- Worker service 1024 MiB/one CPU: one worker, cap 128.
- API service 320 MiB/0.25 CPU: zero safe judge slots. The reviewed API-only
  startup correction permits that role while preserving worker fail-closed boot.

This was a pure capacity probe with no submissions or network. It does not
simulate x86 throughput, host-wide memory saturation or CPU-credit exhaustion.
Existing 284 Python / 204 critical / 76 JS release results remain valid for their
recorded Linux ARM64 environment, not native qualification of this resized host.

## CPU-credit and cost gate

AWS lists t3.small at 20% baseline per vCPU, earning 24 CPU
credits/hour (aggregate baseline approximately 0.4 vCPU). Unlimited can incur
surplus charges under sustained load; Standard can reduce available CPU after
credits are exhausted. The observed credit mode is **unlimited**; balance,
surplus balance and charges were not measured. No mode change was made.
See [AWS credit table](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html)
and [official T3 specifications](https://aws.amazon.com/ec2/instance-types/t3/).
Do not assume free-tier eligibility or trial credits cover every charge.

Read-only checks after normal AWS authentication (do not export/send credentials):

```sh
aws ec2 describe-instances --region ap-southeast-2 \
  --instance-ids i-0e1c8c4d0256f541e \
  --query 'Reservations[].Instances[].{State:State.Name,Type:InstanceType,IP:PublicIpAddress}'
aws ec2 describe-instance-status --region ap-southeast-2 \
  --instance-ids i-0e1c8c4d0256f541e --include-all-instances
aws ec2 describe-instance-credit-specifications --region ap-southeast-2 \
  --instance-ids i-0e1c8c4d0256f541e
```

Use existing CloudWatch graphs for CPUCreditBalance, CPUSurplusCreditBalance,
CPUSurplusCreditsCharged and CPUUtilization. No paid detailed monitoring or
resource change is required for this read-only review. Local CLI credentials
were unavailable in the earlier audit; Console/SSH supplied current evidence.

## Completed native t3.small qualification

The approved maintenance tested source commit
`c206dd7faa5420866858082f161fc0a3c277387a`, staged separately at
`/opt/newbiegrader/staging/t3-qualification-ba5d2f15c0e7`. The sanitized archive
SHA-256 is `e9871ad1ddc1107cc5045fa0b2fdc5325c22246cd40ebd4d22b3c387fa2aa0f0`.
Full measurements and before/after state are in
[the sanitized native record](t3-native-qualification.json).

Admission was paused and the queue drained before stopping the singleton. A
separate systemd canary unit used the existing isolation engine and worker
budget, blank Supabase credentials and synthetic fixtures only. Its command was
`/usr/local/lib/newbiegrader/venv/bin/python -u <candidate>/tools/ec2_single_canary.py`.
This command requires the explicitly approved delegated unit and protected gate;
it refuses ordinary shells. An independent ten-minute restoration timer was
armed before pausing production and stopped after verified recovery.

Results on Ubuntu 24.04, native x86_64 t3.small:

- **17 tests passed, zero failures/errors/skips**, observing 31 isolated jobs.
  Includes kernel isolation/cleanup, normal C/C++ STL/Python, CE/WA/RE/TLE and
  synthetic hidden-output redaction under REVEAL none.
- Matched-deadline single-worker replay **6/6 passed**: fixed 0.89225-second
  deadline, observed wall times 0.6549–0.7645 seconds after three calibration runs.
  No real problem limits were changed.
- Test wall time 43.657 seconds; sampled service CPU usage 41.017 CPU-seconds.
  Peak observed job memory 256 MiB; the intentional aggregate-memory fixture
  caused **seven contained child-job OOM kills**. Canary service-local and
  production API/worker OOM counters remained zero.
- Minimum sampled host MemAvailable 1275156 KiB. Twenty loopback API health
  probes all returned 200, maximum 1.063 seconds. These sparse samples are not
  an API latency benchmark or sustained-load safety proof.

Restoration passed: original admission=1; original singleton, API and tunnel
active; both template workers inactive; queue unchanged at done=48, error=0,
queued=0, running=0. The production release stayed at
`6cba18c68366993fed7fc7572c87368bbb773ea9`; service budgets stayed unchanged.
Temporary approval gate, API overlay, canary cgroup and workspace were removed;
the monotonic UID ledger was retained. A normal public curl from the macOS
audit network outside AWS VPC through Pages returned **200 in 0.352941 seconds**.

This qualifies the bounded fixtures in the observed credit state only. CPU
credit balance/exhaustion, surplus charges, sustained capacity, all real problem
deadlines and production OAuth/submit/poll/history were not verified. S04's
declared-memory semantics remain open; this is not a two-worker qualification.

## Revised deployment prerequisites

1. Use the confirmed t3.small target. Type selection is resolved; any further
   resize, stop/start or credit-mode change needs separate approval.
2. Keep one worker, existing limits and Supabase. The prior m7i-flex.large
   throughput/fairness results are historical; do not reuse them as a pass on
   this 2-GiB burstable instance. Never increase problem limits to hide slower CPU.
3. Before an approved application rollout, record current health, memory/events,
   disk reserve and CPU-credit state. Fresh drain and rollback record are still
   required. The bounded native tests above passed; further maintenance or
   application rollout requires its own explicit approval.
4. Observe total memory, API latency, queue completion and verdict parity with
   bounded synthetic workloads; preserve CPU/credit state alongside timings.
   No OOM outside the job, no leftover processes, no infrastructure SE mistaken
   for a contestant verdict, healthy API and one worker are acceptance conditions.
5. If these fail, stop that rollout and retain the last verified one-worker
   release. A change back to a larger paid instance or another resize requires
   separate approval; do not perform it as an automatic rollback.

The c206dd7 qualification artifact is staged and unpushed. The application code
has not changed since 837366c; later changes add qualification tooling and docs.
No application deployment approval is inferred from approval of this maintenance.
