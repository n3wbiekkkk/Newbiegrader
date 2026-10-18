# B08 database-queue preparation — 2026-10-18

**High reliability, CONFIRMED local-mode risk; existing database mode rehearsed.**

## Changes

`server._judge_worker()` previously issued an empty claim every 0.25 seconds,
including during database outages. Before enabling database mode, bounded idle
backoff now grows through 0.5, 1 and 2 seconds; completed work resets to 0.25.
Errors back off to 30 seconds, and successful work resets the delay. Cancellation
still propagates immediately. No admission, ownership, result or retry semantics
were replaced. At steady idle, two-second sleeps imply about 43,200 claim RPCs
per worker/day instead of 345,600, ignoring request latency. This is an estimate,
not a measured invoice; idle pickup can take up to two seconds plus RPC latency.

Three new synthetic scheduling tests failed before and pass after the change.
README now distinguishes local best-effort behavior from database durability,
and correctly describes the approved practice/contest feedback policy.

## Rehearsal and production read-only evidence

- Disposable network-none PostgreSQL 17: apply schema twice, then queue and
  permission SQL assertions, all passed. No production SQL migration was run.
- Four independent concurrent consumers: exactly one claim succeeded. After a
  one-second abandoned lease expired, another consumer reclaimed the same job
  with a new attempt. Stale completion was rejected; current completion applied.
  These were synthetic records in the disposable database, not real workloads.
- All five production RPC bodies match the rehearsed database's `md5(prosrc)`.
  Service-role execute allowed; anon/authenticated execute denied. The source
  checksum is a comparison aid, not a cryptographic security mechanism.
- Actual backend credentials successfully called the read-only diagnostics RPC:
  HTTP 200, zero queued/running rows. No credential values were printed.
- Full suite for this change: **283 passed, zero skips**, 105.627 seconds in
  disposable Linux arm64/root/Python 3.11. This is not a production crash drill.

## Cutover procedure

1. Record current application image, nonsecret queue settings and volume IDs.
   Preserve `/var/lib/newbiegrader/sandbox-identities` and its ledger.
2. Pause new ingress using provider controls. Drain the existing **local**
   consumer before stopping it; database counts alone do not prove its in-memory
   queue is empty. Never overlap local and database consumers.
3. Confirm no queued/running or legacy unleased-running rows. If such rows exist,
   inspect/reconcile them after stopping the old consumer; do not broadly reset
   active ownership or apply the entire schema as a repair shortcut.
4. With the already-reviewed RPC schema, set `GRADER_QUEUE_MODE=database`, keep
   `GRADER_ROLE=combined`, stable SESSION_SECRET and one judge worker. No new
   permission grants or problem-data changes are needed for the observed schema.
5. Start the tested image. Boot must successfully check queue diagnostics,
   filesystem restrictions and the network filter; database failure is a refusal
   to admit/boot work, not a silent fallback to a local queue.
6. Verify health/version, one synthetic job's durable admission/completion,
   owner read and redaction; re-open ingress only after the checks pass. Keep
   real user workloads out of a crash/retry experiment.

**This preparation does not itself prove or claim a production cutover.**
If an actual atomic local drain cannot be established, keep the cutover pending
rather than treating zero database rows as proof. A maintainer-controlled idle
maintenance window or authenticated drain control is required.

Rollback: stop admission, drain/stop the database consumer, inspect outstanding
leases, then restore the previous queue mode/image. Do not run the old local
recovery loop against active database leases. Preserve state/rows and UID ledger;
do not delete work to make the queue appear empty.

## Remaining operations work

Production restart/lease-expiry drill, queue/lease alerts, pool and RPC cost
measurement, retention, worker-role healthchecks and recovery/backups remain.
No automatic history deletion or production synthetic-row insertion occurred.

Private evidence: `~/.local/share/newbiegrader-validation/runtime-enforcement-hlp2u8fm/`
(`postgres-rehearsal.log`, `postgres-concurrency.json`, `queue-body-hashes.json`,
`production-queue-diagnostics.json`, `poll-before.log`, `poll-after.log`,
`queue-full.log`).
