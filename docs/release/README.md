# Release and recovery checks

The [documentation index](../README.md) identifies current guides and dated
qualification records. The running snapshot is
`architecture-20261028-1bf56506a130` (grader 2.0.8 / Python 3.13.17);
see [architecture qualification](../releases/backend-architecture-2026-10-28.json).
All three hosts share this fingerprint, with four primary, two homeserver and ten
auxiliary-PC workers. The [primary/failover activation](../releases/primary-failover-2026-10-27.json)
remains the transport baseline. Documentation-only changes do not imply a rollout.

Use the [host runbook](../HOST_DEPLOYMENT.md),
[current architecture](../PRODUCTION_ARCHITECTURE.md) and
[backup/recovery guide](../HOST_BACKUP_RESTORE.md). Keep credentials, private
catalogs, dumps, hidden tests and detailed host records outside Git.

Before a backend release, run the repository checks, Linux/root critical gate
with zero skips, native isolation/verdict/file-access probes and the actual
worker preflights. Test public HTTPS, sessions, CSRF, request bounds, anonymous
permissions and Python/C/C++ execution plus linked history. Four-worker hosts
also require concurrent native qualification under the real resource budgets.

Pause admission, drain queued/running jobs and live leases, stop consumers and
capture final configuration/file hashes and UID reservations before a host
switch. Preserve the session secret and the newest UID ledger. Keep one active
worker fleet; independent hosts coordinate job ownership through the durable
queue, not copied local queue state.

Backup coverage is explicit: daily encrypted configuration/UID/application-row
exports, a separate locked encrypted archive of protected file bytes and a
matching catalog/source release. Decryption is only one check: rehearse a
restore into empty private roots and verify hashes, permissions and all selected
packages/PDFs/samples. A table-row export is not a transactional database backup
or proof of hosted Auth/Storage recovery. Do not claim those guarantees without
a separate isolated restore and comparison.

Give host backups separate object namespaces; retain one watchdog, presence and
account-retention owner on the homeserver. Use watchdog
`--check-only` for validation without sending messages. After activation, verify
reboot recovery and the absence of orphan processes, workspaces and live leases
on the previous consumer. Rollback uses the current host's compatible verified
release and preserved file generation, without an external-host fallback.
