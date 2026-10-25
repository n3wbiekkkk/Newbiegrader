# Erasure reconciliation before reopening a restored database

This is an offline application-data recovery gate. Restoring an older export
must not restore an erased account, its source/history or an old browser session.
Hosted Auth/Storage/PITR recovery remains a separate operation.

## Preserve current deletion state first

Close account-changing routes and job admission, drain live jobs/leases and stop
workers under the host runbook. Independently preserve the **current** privacy
salt, deletion blocks, pending provider-deletion work and counts-only audit. Never
substitute the copy inside the older archive. If current deletion state is lost,
stop recovery for operator resolution; a fresh salt or an empty list is unsafe.

`capture_query()` in
[`reconcile_account_restore.py`](../deploy/host/reconcile_account_restore.py)
returns the read-only SQL for one consistent snapshot of these four tables.
Run that SELECT against the verified current project, save its JSON result as a
private `0600` file in a `0700` operator directory, and independently record its
SHA256 and capture/source information. It contains a privacy secret and possibly
pending account identities: never paste it into an issue, report, command line or
public SQL snippet. Preserve this state independently of the old restore source.

The tool rejects missing salt/state, invalid or duplicate rows, pending work
without its matching salted block, snapshots older than 24 hours, and backups
that postdate the deletion snapshot or are over 30 days older. A checksum detects
file changes; it does not prove that an operator selected the correct project or
captured all deletion requests. Quiescing and verifying the source are mandatory.

## Restore and review in isolation

Restore application rows into a new offline PostgreSQL database with no TCP
listener and a private operator-owned Unix socket. Apply the current schema and
privileges. Do not restore sessions or start a worker against this database.
Keep the latest append-only UID ledger and protected problem files separately.

```sh
python deploy/host/reconcile_account_restore.py \
  --state /private/recovery/deletion-state.json \
  --state-sha256 <independently-recorded-file-sha256> \
  --backup-at <archive-creation-time-with-timezone> \
  --socket /private/recovery/socket \
  --port 5432 --database newbiegrader_restore
```

The default transaction **rolls back** and returns only per-table counts. Review
the affected counts before repeating the exact command with `--execute`. All
tables are locked during reconciliation; this command intentionally supports
only private local sockets, not hosted production connections.

Reconciliation replaces the old deletion state with the independently captured
state, finds erased identities across account/owned/organizer rows, removes their
owned data and admin grants, and anonymizes organizer references while retaining
the contests and announcements. Old queued/running jobs in the offline snapshot
are removed for erased identities; these are not live production leases.
Every restored browser session is removed, including surviving users' sessions.

Current pending provider work survives even past its normal 90-day block expiry.
Reconciliation does not call Auth, mark a provider deletion completed, or invent a
completed-deletion audit. Run the normal provider recovery before reopening.
Preserve the current counts-only audit and verify that a second run is harmless.

## Final recovery gate

1. Confirm no erased account/history/owned job survived and no old session works.
2. Complete pending hosted Auth deletion and verify current identity mappings.
   Never restore an old hosted Auth snapshot without the same erasure review.
3. Restore no signing secret/session rows from the archive. Follow
   [session disaster recovery](SESSION_REVOCATION.md#backup-and-restore), including
   a fresh signing key, and retain that key during any later rollback.
4. Verify problem bytes, native worker controls, real HTTPS identity/CSRF checks,
   and Python/C/C++ submissions before starting consumers or admitting users.

The real PostgreSQL regression test is `tests/account_restore_sql.py`, wired into
the `queue-sql` CI job. It checks resurrected source/results, a stale leased job,
all owned tables, organizer anonymization, other-device sessions, Google/OTP
recreation denial, pending work older than 90 days, audit preservation and a
repeat run. Fixtures are synthetic and the transaction rolls back.
