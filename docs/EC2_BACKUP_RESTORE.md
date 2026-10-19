# EC2 migration backup/restore gate

## Latest backend file-data recovery check — 2026-10-19

With admissions paused and the singleton stopped, both file roots were locked in
publisher order and streamed directly into local age encryption:
`20261019T122951Z-file-data.tar.age` (188,882,136 bytes, SHA-256
`fae766fadeab7a6ae0120804c799ac29a3bb43980b5bc90a2926718b770566c5`). Authenticated
decryption passed. A restore into a disposable `0700` EC2 directory re-verified
**2679 objects / 68 problems / 1178 cases / 68 PDFs** and identical public/private
index hashes before the disposable copy was removed. Configuration/UID/tunnel
plus `/etc/newbiegrader/problem-files.env` and the API/worker file-mode drop-ins
were encrypted as `20261019T124435Z-ae06c238.tar.age`; decryption was verified.
See the [backend file release record](releases/PRODUCTION_BACKEND_FILES_2026-10-19.md).
Automatic off-host scheduling is still not established.

## Previous application-rollout recovery check — 2026-10-19

Read-only snapshot `20261019T105234Z-postgres-snapshot.dump.age` (795645 encrypted
bytes, 11.1 s dump) was restored into network-disabled disposable PostgreSQL.
All 51 table content comparisons, 58 relation/ACL/RLS definitions, 150 constraints
and policies matched. This supersedes the earlier logical snapshot for this
rollout; hosted Auth/Storage-service recovery remains unverified. Configuration,
UID and Cloudflare recovery were encrypted and decryption verified. See
[exact scope and recovery locations](releases/PRODUCTION_CORRECTNESS_RELEASE_2026-10-19.md).

Status 2026-10-19: EC2 configuration recovery, PostgreSQL **logical database**
recovery and private Storage **file-byte** recovery verified. Running managed
Auth/full Storage service recovery remains **UNVERIFIED**. No production restore,
DB permission change, credential reset,
new paid project, user-account mutation or job execution was performed here.

Post-cutover update: the same procedure was repeated with admission paused.
`20261019T010725Z-postgres-snapshot.dump.age` is **792,423 encrypted bytes**,
dump **10.8 s**, with 51 table/partition content checks, 58 relation/ACL/RLS
definitions and 150 constraints matching the isolated restored database. Restore
plus comparison took about 0.3 s; the same two local extension-view adjustments
were required. The tmpfs recovery container was removed afterward. Its table
manifest totals 3,107 rows including partition-parent counts. This supersedes
the earlier archive as the latest rehearsed data snapshot; the historical
procedure and limits below still apply.

After reopening services, fresh configuration/UID/tunnel state was encrypted as
`20261019T011231Z-0e5f224a.tar.age`. New Cloudflare production key/config and
before/after metadata were separately encrypted in the nine-member
`20261019T011501Z-cloudflare-production.tar.age`; authenticated decryption passed,
0600 archive, no SSH/OAuth/age private key included. Keep both with the existing
local age identity and maintain a separate protected offline identity copy.

## Verified PostgreSQL logical recovery

The operator created `~/.pg_service.conf` and `~/.pgpass`: both regular files,
owner-only 0600. No password was displayed. The first connection failed CA
verification before authentication: the pooler uses Supabase's private CA, absent
from the client's system roots. The CA was obtained over verified HTTPS from
the **existing project's Database Settings → Download certificate** link:
`https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt`.
Its SHA-256 certificate fingerprint was
`807025AD50D4ED219D2C9C7D299C004F824EB00CF7F65AFEF607D07B72E6CAFA`.
Only the PostgreSQL client's CA file was selected; the system trust store was
not changed and `sslmode=verify-full` stayed mandatory. Authentication then
succeeded, reporting PostgreSQL 17.11 and 68 public problem records.

The shared session pooler did **not** carry the requested read-only default from
`PGOPTIONS`: an initial readback returned `default_transaction_read_only=off`.
It is not an admission/security boundary. A subsequent explicit `BEGIN READ
ONLY` returned `transaction_read_only=on`. The backup holder used **REPEATABLE
READ READ ONLY**, exported a snapshot, and kept it open while `pg_dump 17.11`
used `--snapshot`. Its table-content manifest was read in that same transaction.
No source DDL, data write, job admission/claim or password reset was executed.

Actual consistent archive: **`20261019T003815Z-postgres-snapshot.dump.age`**,
**791,071 encrypted bytes**, dump **10.9 seconds**. It streamed from a disposable
Docker PostgreSQL client directly into local age encryption; no plaintext dump
was saved. The matching manifest, role export **without role passwords**, public
function manifest and exact private recovery recipe are separately encrypted in
`~/.local/share/newbiegrader-private/ec2-backups/`. All five matching artifacts
were checked/corrected to 0600; their directory is 0700 on FileVault storage.
An earlier non-exported-snapshot dump is not the consistency evidence above.

Actual restore used the official image
`supabase/postgres:17.11.0.004`, digest
`sha256:b15d862126dd2dac02da524696ccfde2dcce2ceaee0a58973b2727befe492706`,
in a **separate container with network=none, no published ports, no source
credentials, 768 MiB RAM/no swap, one CPU, 96 tasks, logging disabled and a
384 MiB tmpfs PGDATA**. No Auth, mailer, Storage API, cron consumer or judge ran.
Restore targeted a new empty `recovery` database, never the source service.
`pg_restore --clean --if-exists --single-transaction --exit-on-error` returned
zero. The successful restore command plus comparison took about **0.3 seconds**;
image download/bootstrap and earlier diagnostic attempts are excluded.

Verification after restore:

| Check | Actual result |
| --- | --- |
| Table/partition counts and deterministic row-content checksums | 51/51 match |
| Relation names, owners, sorted ACLs, RLS/forced-RLS flags | 58/58 match |
| Constraint definitions under a fixed `pg_catalog` search path | 150/150 match |
| RLS policy definitions | Equal; zero explicit policies in this snapshot |
| Public function definitions, signatures, owners and sorted ACLs | 8/8 match |
| Non-internal public triggers | Equal; zero in this snapshot |

The table manifest totals 3,096 rows **including partition-parent counts**; this
is not a count of distinct database records. MD5 row fingerprints are corruption
comparison evidence, not an authentication primitive; age authenticates the
encrypted artifacts. Public function comparison was read separately immediately
after the snapshot restore, not inside the exported data snapshot.

All five final encrypted artifacts passed authenticated decryption. The
disposable restore container was removed after comparison, discarding its tmpfs
database; readback confirmed it was absent and no plaintext `.dump` files were
left in the backup directory. The original connection files remain 0600.

An initial raw comparison exposed ACL ordering and search-path qualification
differences; both were normalized before comparing. Two **extension monitoring
views** (`extensions.pg_stat_statements` and `pg_stat_statements_info`) inherited
different owner/grantor defaults from the local image. Their owner/ACLs were
restored to the captured source definitions **only in the disposable database**,
then all 58 relation comparisons matched. Exact local adjustment SQL is in the
encrypted recovery recipe. No source permission changes were required. The local
restore role briefly needed superuser and was returned to its original setting.

### Repeating this rehearsal safely

1. On the authorized Mac, decrypt the recovery recipe only into a private 0700
   temporary directory on encrypted storage; inspect it privately. It records
   the exact snapshot/manifest procedure and local extension adjustments. Never
   print its database contents. Keep the age identity local and offline-backed.
2. Use `postgres:17` as the source client, bind the two 0600 libpq files read-only
   to `/run/pg_service.conf` and `/run/pgpass`, and the verified public CA to
   `/run/supabase-ca.crt`. Set only `PGSERVICEFILE` and `PGPASSFILE` path variables.
   Supply `service=newbiegrader_backup sslrootcert=/run/supabase-ca.crt
   sslmode=verify-full` as libpq options: no password in argv. Hold/export a
   read-only repeatable-read snapshot, capture the manifest, and stream
   `pg_dump --format=custom --compress=6 --lock-wait-timeout=10s --snapshot=<id>`
   into age. Check both process exits; delete a failed partial encrypted output.
3. Start the pinned official Supabase PostgreSQL image with the isolation and
   tmpfs bounds above. Prepare source role **names** locally; do not import real
   login passwords or mount source connection files. Use an empty template0
   database. Stream authenticated age decryption into `docker exec -i <restore>
   pg_restore -U postgres -d recovery --clean --if-exists --single-transaction
   --exit-on-error`. Only this isolated local role may temporarily need superuser.
4. Apply the captured two-view correction locally, normalize ACL order/search
   path, and compare the encrypted manifest. Revoke temporary local privileges,
   remove the disposable container/tmpfs and verify no plaintext dump remains.

Scope limits: this proves logical database recovery, including Auth/Storage
**table bytes**, and the listed application metadata. It does not prove hosted
Auth sessions/OAuth/SMTP settings, service/API startup, Vault key portability,
every extension implementation, role-password recovery or end-to-end managed
Supabase recovery. `vault.secrets` had zero rows. The roles export was captured
separately, not atomically with table data. Storage bytes were backed up earlier;
the two backups are not one atomic DB/Storage snapshot. Supabase stays on its
current provider during this backend migration. Scheduled backup/retention,
offline identity custody and final maintenance-window backup remain outstanding.

## Verified private Storage object recovery

Actual command on the authorized FileVault-protected Mac:

```sh
python3 deploy/ec2/backup_storage.py
```

The read-only source runs as the unprivileged `newbiegrader-api` user in a
transient systemd service on EC2, with EnvironmentFile loaded by systemd (not
printed/exported), NoNewPrivileges, 256 MiB memory, no swap, 25% CPU, 32 tasks and
a 1,200-second deadline. Eight bounded HTTPS downloads run concurrently; judge
concurrency is unchanged. Only the fixed existing project and `judge-assets`
bucket are accepted. Limits: 10,000 objects, 16 MiB/object, 256 MiB total.

Source listing before/after download matched. All bytes and a checksum manifest
streamed through SSH directly into age encryption on the Mac. Actual final run:
**2,679 objects / 185,493,091 bytes**, **445.6 seconds**. It decrypted into an
isolated 0700 temporary directory on FileVault storage, recovered 0600 regular
files, and re-read every restored SHA-256: **all matched**. Recovery rejects path
traversal, symlinks, duplicates, excessive sizes and hash mismatches; four
synthetic regression tests passed. The temporary plaintext directory was removed
and a separate check found zero leftovers. Encrypted archive mode is 0600.

Private archive: `~/.local/share/newbiegrader-private/ec2-backups/`, file ending
`-storage.tar.age`; use its matching local `backup-identity.txt`, never Git/chat.
The bucket manifest/object paths and bytes are not printed in logs/reports.
No production objects were written/deleted. This confirms **file-byte recovery**,
not restored Supabase bucket policies, managed Auth or a working Storage API.
Those still require the DB/metadata/full-stack rehearsal below. This is a
one-time backup; scheduled retention and off-host/offline identity custody remain
operational tasks.

Earlier attempts are excluded: the initial source lacked python-dotenv, so the
implementation now uses systemd EnvironmentFile with installed dependencies;
a four-download run was stopped because network throughput threatened its
original deadline and its partial archive was removed. Only the complete final
eight-download run above counts as verified. Interrupted/failed backups do not
produce a usable archive.

## Available verified backup

Run `python3 deploy/ec2/backup_state.py --include-tunnel` from the authorized Mac.
It streams seven fixed files under a shared UID allocator lock directly through
age encryption. Actual authenticated decryption and in-memory archive checks
passed: root ownership, expected member names and root-only credential modes.
This is configuration/UID/tunnel state, not database/Storage protection. The
identity stays on the Mac; keep a separate protected offline copy. Restore into
approved root-only paths. Never replace the current UID ledger with an older
snapshot: append/merge reservations under the allocator lock.

## Earlier missing-access checkpoint (resolved for logical backup)

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

## Full managed-service verification sequence (partially executed above)

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
