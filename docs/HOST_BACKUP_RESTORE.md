# Backend backup and recovery

Keep the age private identity only on the operator's protected machine and an
offline copy. The PC holds only the recipient public key. Never upload the
private identity or publish configuration, catalogs, test bytes or backups.

## Coverage

- `newbiegrader-backup.timer` runs daily. Its encrypted archive contains API,
  per-worker and file-storage configuration, unit/drop-in configuration, the
  append-only UID ledger and application table rows fetched from Supabase. It
  uploads to the private `judge-backups` bucket. This is an application-data
  export, not a transactional PostgreSQL/Auth/Storage-service backup.
- Protected problem-file bytes require a separate encrypted off-host archive.
  Lock public and private roots in publisher order, and the UID ledger, while
  streaming the archive into age. Copy the encrypted result off the PC and
  verify authenticated decryption. Repeat before and after file publication.
- Keep a matching private catalog export and source release. The committed SQL
  defines schema/policies; table exports alone do not restore hosted Auth,
  Storage configuration, database roles or all database service behavior.
- `backup_state.py --host <verified-host> --ssh-key <key> --include-tunnel
  --include-problem-files-config` is an additional configuration/UID snapshot;
  it does not include protected file bytes. The separate `backup_storage.py`
  reads an explicitly selected Storage recovery source, not the active local
  file backend.

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
