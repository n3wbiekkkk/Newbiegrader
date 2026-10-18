# EC2 migration backup/restore gate

Status 2026-10-19: EC2 configuration recovery archive verified; Supabase data and
Storage recovery **UNVERIFIED**. No production restore, permission change,
credential reset, new paid project or user-data export was performed here.

## Available verified backup

Run `python3 deploy/ec2/backup_state.py --include-tunnel` from the authorized Mac.
It streams seven fixed files under a shared UID allocator lock directly through
age encryption. Actual authenticated decryption and in-memory archive checks
passed: root ownership, expected member names and root-only credential modes.
This is configuration/UID/tunnel state, not database/Storage protection. The
identity stays on the Mac; keep a separate protected offline copy. Restore into
approved root-only paths. Never replace the current UID ledger with an older
snapshot: append/merge reservations under the allocator lock.

## Exact missing access

Read-only MCP SQL works and reported PostgreSQL **17.11**. No pg_dump connection
was configured in the inspected process connection variables, local `.env`,
`~/.pgpass` or `~/.pg_service.conf`. Only presence and variable names were reported.
A Supabase service-role API key or MCP OAuth connection is not a PostgreSQL dump
credential. Do not paste a password/URL into chat or put one in command arguments.

Provision a local libpq service named `newbiegrader_backup` using Supabase's
Connect dialog (direct or **session** pooler, not transaction pooler), mandatory
TLS certificate/hostname validation, and a private 0600 password file. Inspect
files privately; never print them. Use a client at least as new as server major
17. Configure a separate disposable local restore target; never reuse the source
service name for restore. No paid Supabase branch is required.

## Required verification sequence (not yet executed)

1. Capture nonsecret source manifest: server version; relation/function/extension
   definitions; row counts by table; RLS/ACLs; object counts and total bytes by
   bucket. Keep any object names/user data inside encrypted private artifacts.
   Record timestamps and consistency limitations; do not claim independent DB
   and Storage downloads form one atomic snapshot during concurrent writes.
2. Export roles/schema/data using the current official Supabase backup procedure.
   For app-public-schema-only rehearsal, a native client can use
   `pg_dump --dbname=service=newbiegrader_backup --schema=public --format=custom`
   with stdout piped directly into age encryption under `umask 077` and checked
   pipeline exit statuses. This partial export is **not** a full Supabase backup:
   auth, Storage metadata, extensions, roles and project settings need the
   official procedure and separate inventory. Do not save plaintext SQL files.
3. Download private Storage objects separately through authorized server-side
   access, preserving object bytes/metadata and checksums inside encryption.
   Database backups contain Storage metadata, **not object contents**. Record
   object errors/count/bytes; a failed/partial download cannot satisfy this gate.
4. Restore only to an isolated local Supabase/PostgreSQL-17 environment with no
   production credentials, outbound webhooks, OAuth integrations or consumers.
   Follow Supabase's local-restore instructions for its managed auth/storage
   schemas; a plain postgres image alone does not prove full-stack recovery.
   Use encrypted local disk/private files where plaintext restore is required;
   never put database rows or hidden tests into terminal output/test logs.
5. Compare manifests/row counts, constraints, foreign keys, RLS/ACLs and checksums.
   Run the repository queue/security/auth SQL tests against an **empty synthetic
   disposable database**, not the restored user-data copy. Separately inspect
   restored application data with aggregate-only checks; no submissions execute.
   Verify synthetic auth/history/problem retrieval and downloaded object bytes
   in the isolated environment. No email is sent and no production jobs claimed.
6. Record backup and restore durations, validated scope, encrypted file size,
   checksums, recovery point/time objectives, and a protected offline identity
   copy. Schedule bounded off-host retention only after reviewing storage cost.
   A decrypt/list check alone does not count as a successful database restore.

Any partial test, missing object bytes, schema/ACL mismatch or failed restore
keeps this gate open. Production restoration requires separate explicit approval;
it is not a routine migration rollback.

## References

- [Supabase backup and restore](https://supabase.com/docs/guides/platform/migrating-within-supabase/backup-restore)
- [Database backups and Storage limitation](https://supabase.com/docs/guides/platform/backups)
- [Local restore from downloaded backup](https://supabase.com/docs/guides/local-development/restoring-downloaded-backup)
