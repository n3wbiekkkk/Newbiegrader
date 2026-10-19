# Two-GiB host: observed state and single-worker release gate

2026-10-19. Documentation/read-only verification only. No instance, security
rule, credit mode, service, route or application deployment was changed here.

## Actual versus requested hardware

The user reports a completed resize to **t8i.small**. Refreshed Sydney EC2
Console for the original instance `i-0e1c8c4d0256f541e` instead shows
**t3.small**, Running, **3/3 checks passed**, Public IPv4 **15.135.225.193**,
credit specification **unlimited**. Target t8i.small remains unverified on that
live instance; the clarification is pending. Do not resize again automatically.
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

AWS lists both t3.small and t8i.small at 20% baseline per vCPU, earning 24 CPU
credits/hour (aggregate baseline approximately 0.4 vCPU). Unlimited can incur
surplus charges under sustained load; Standard can reduce available CPU after
credits are exhausted. Availability of t8i.small in this exact AZ is not verified; use the read-only
offering query below before planning a change. Actual credit mode is confirmed **unlimited**; balance,
surplus balance and charges were not measured. No mode change was made.
See [AWS credit table](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/burstable-credits-baseline-concepts.html)
and [official T8i specifications](https://aws.amazon.com/ec2/instance-types/t8i/).
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
aws ec2 describe-instance-type-offerings --region ap-southeast-2 \
  --location-type availability-zone \
  --filters Name=instance-type,Values=t8i.small Name=location,Values=ap-southeast-2b
```

Use existing CloudWatch graphs for CPUCreditBalance, CPUSurplusCreditBalance,
CPUSurplusCreditsCharged and CPUUtilization. No paid detailed monitoring or
resource change is required for this read-only review. Local CLI credentials
were unavailable in the earlier audit; Console/SSH supplied current evidence.

## Revised deployment prerequisites

1. Resolve the observed t3.small versus requested t8i.small discrepancy. Do not
   change type, stop/start or credit mode on inferred permission.
2. Keep one worker, existing limits and Supabase. The prior m7i-flex.large
   throughput/fairness results are historical; do not reuse them as a pass on
   either 2-GiB burstable instance. Never increase problem limits to hide slower CPU.
3. Before an approved application rollout, record current health, memory/events,
   disk reserve and CPU-credit state. Fresh drain and rollback record are still
   required. Use only an explicitly approved maintenance window for native
   single-worker C/C++/Python, memory/process/workspace and matched-deadline tests.
4. Observe total memory, API latency, queue completion and verdict parity with
   bounded synthetic workloads; preserve CPU/credit state alongside timings.
   No OOM outside the job, no leftover processes, no infrastructure SE mistaken
   for a contestant verdict, healthy API and one worker are acceptance conditions.
5. If these fail, stop that rollout and retain the last verified one-worker
   release. A change back to a larger paid instance or another resize requires
   separate approval; do not perform it as an automatic rollback.

The code-only artifact from 7691557 is still prepared and unpushed. The app code
has not changed in this hardware documentation update. No deployment approval
is inferred from the user's statement that the resize is already complete.
