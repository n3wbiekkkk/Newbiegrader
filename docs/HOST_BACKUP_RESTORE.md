# Backend backup and recovery

Keep the age private identity only on the operator's protected machine and an
offline copy. The PC holds only the recipient public key. Never upload the
private identity or publish configuration, catalogs, test bytes or backups.

## Coverage

- `newbiegrader-backup.timer` runs daily. Its encrypted archive contains API,
  per-worker and file-storage configuration, unit/drop-in configuration, the
  append-only UID ledger and application table rows fetched from Supabase. It
  uploads to the private `judge-backups` bucket. This is an application-data
  export, not a transactional PostgreSQL/Auth/Storage-service backup. The
  credential table `web_sessions` is deliberately excluded; durable account,
  queue and history rows remain included.
- Protected problem-file bytes require a separate encrypted off-host archive.
  Lock public and private roots in publisher order, and the UID ledger, while
  streaming the archive into age. Copy the encrypted result off the PC and
  verify authenticated decryption. Repeat before and after file publication.
- Keep a matching private catalog export and source release. The committed SQL
  defines schema/policies; table exports alone do not restore hosted Auth,
  Storage configuration, database roles or all database service behavior.
- `backup_state.py` is a compatibility tool for a singleton layout. It does not
  collect all four instance env files or the complete current unit set, and it
  assumes noninteractive remote sudo. Do not use it as the current PC's complete
  recovery backup or broaden sudo privileges to make it run. The installed
  scheduled backup covers the fleet configuration. `backup_storage.py` reads an
  explicitly selected legacy Storage recovery source, not active local file bytes.

Private operator artifacts default to `~/.local/share/newbiegrader-private/host-backups/`.
Preserve the existing identity when changing directories; a newly generated key
cannot decrypt earlier archives. Archive names and detailed recovery evidence
remain private.

## Recovery rehearsal

Restore into new empty directories or an isolated host, with admission disabled
and every worker gate absent. Verify safe archive member names/types, all hashes,
root ownership and modes. Restore API-readable public roots as root:newbiegrader-api
0750 with 0440 files; restore private roots as root:root 0700 with 0400 files.
Encrypted transfer archives may deliberately have stricter modes, so confirm
service readability without exposing private tests.

Restore with an empty `public.web_sessions` table and generate a fresh
`SESSION_SECRET` before opening admission. When replacing an existing database,
have the maintainer clear old session rows first. Do not import session rows or
reuse a signing key from the encrypted configuration backup. All browsers sign
in again. Rollback must also retain the newly rotated key. See
[session recovery](SESSION_REVOCATION.md#backup-and-restore).

Run `tools/verify_backend_problem_files.py --catalog <private-export>` with the
local file roots configured. Require matching problem/test counts and hashes,
all samples/PDFs, zero cloud-file fallback, and native negative access probes.
Merge UID reservations; never reset an existing ledger. Run worker preflight,
critical tests and real HTTPS validation before reopening admission.

The migration rehearsal verified 2,987 physical files against the source SHA256
manifest and production loaders verified 89 problems, 1,594 cases and 89 PDFs.
These checks prove the measured byte/package parity; they do not prove complete
database/Auth recovery, problem correctness or test coverage. Verify the latest
off-host backup after each operational or problem-file change.

`newbiegrader-alert.timer` checks all four configured worker units, tunnel, API,
durable queue, disk and backup age. Its root-only webhook configuration retains
the existing token and host label. Use `--check-only` for validation without
sending a message; schedule the watchdog only on the intended active host.
With `NEWBIEGRADER_PUBLIC_URL` configured it also checks the public HTTPS chain.

The latest 2026-10-23 scheduled export was downloaded and decrypted
off-host: the one-CPU API unit, UID ledger and 12 application table exports were
readable. This supplements the earlier protected-file restore rehearsal; it
does not extend the stated Database/Auth/Storage recovery coverage.

On 2026-10-23 an authenticated configuration/data archive was also restored into
a disposable PostgreSQL 17 instance on the operator Mac. It accepted the committed
schema twice (13 application tables), restored all 12 durable exported tables
with `web_sessions` empty, matched every row value
(normalizing equivalent timestamp/numeric representations), and passed the real
server-only privilege checks. The instance listened only on a private Unix socket
and was removed after testing. No production database was modified. This proves
the tested application-table recovery path; hosted Auth, Storage-service state,
point-in-time recovery and transactional consistency across table exports remain
outside that rehearsal.


## Account-erasure and retention rollout

The [account-data runbook](ACCOUNT_DATA.md) defines the candidate one-year history,
90-day audit/deletion-block and 30-day encrypted-backup policy. Its migration and
maintenance schedule are not yet production-qualified. The scheduled backup
candidate now prunes its own recognized archives by age as well as count and
fails visibly if pruning fails. Off-host destinations require their own reviewed
cleanup; unknown filenames and backup identities are never removed automatically.

An old backup can contain an account deleted after that snapshot. Preserve the
latest deletion blocks, pending work and matching privacy salt, reconcile erased
accounts before reopening, and restore no sessions. If deletion state is missing,
stop restoration for operator resolution. The older recovery rehearsals above do
not qualify this new erasure-reconciliation step.
