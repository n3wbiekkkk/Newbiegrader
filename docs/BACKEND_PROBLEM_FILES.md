# Backend problem-file storage

The production backend reads PDFs, public samples and private tests from
protected local disk with `GRADER_FILE_STORAGE=local`. Supabase retains metadata,
identities and the durable queue. See [current architecture](PRODUCTION_ARCHITECTURE.md).
No problem IDs, fixture bytes, judging rules or visibility policies change when
the host moves. Detailed migration records and catalogs remain private.

## Scope and trust boundary

- `GRADER_PROBLEM_SOURCE=supabase` retains relational metadata, visibility,
  problem IDs/numbers, public sample names and the existing tests hash.
- `GRADER_FILE_STORAGE=local` makes **all** file reads use backend disk. No
  network fallback to Supabase Storage exists in this mode. An absent, malformed,
  wrong-mode, symlinked, corrupted or checksum-mismatched test is an infrastructure
  error before the runner; it never becomes WA/AC on an incomplete suite.
- Supabase's existing objects remain untouched during preparation/rehearsal.
  Removing originals is a separate destructive operation after recovery proof.
- API routes and current practice/contest feedback policy stay unchanged. Owners
  may see permitted failed practice data; contest tests remain concealed.
- Frontend remains Cloudflare Pages. The PC runs four separately contained worker
  instances; see the current architecture for budgets and service names.

## Storage format and permissions

`backend_problem_files.py` reuses the existing loader boundary in
`problem_store._download`; the judge/checkers remain in `grader.py`.

| Directory | Reader | Required permissions |
| --- | --- | --- |
| `<generation>/public-files` | Trusted API and worker; PDFs and explicitly public sample files | root:newbiegrader-api 0750; regular files 0440 |
| `<generation>/private-files` | Trusted worker only; tests and remaining private package assets | root:root 0700; regular files 0400 |

Generation parent directories are root:newbiegrader-api 0750. They are outside
application/static paths and every submission workspace. Sandbox UIDs have no
matching API group, cannot traverse these roots and receive no Landlock allowance
or bind into their workspace. API cannot read private test files. Do not add
these paths to contestant filesystem allowlists.

Each logical bucket/path maps to SHA-256/byte length in `index.json`. Blob names
are full content hashes; old immutable versions are retained. Reads reject path
traversal/noncanonical paths, symlinks, hardlinks, loose permissions, unexpected
owners, oversized objects and checksum failures. Index identity/mtime/ctime/mode
changes invalidate the small parsed index cache. No full private problem cache
or `PROBLEMS` retention is used in local-file mode, bounding trusted-worker growth.
PDF caching retains the existing metadata-version invalidation contract.

A publisher locks both roots, writes/fsyncs blobs first, then replaces/fsyncs
indexes atomically. Readers see complete indexes. No automatic deletion or blob
pruning exists. Publication reserves 1024 MiB free disk by default (minimum 256);
individual objects are capped at 64 MiB. Across files plus database there is no
cross-system transaction: **pause/drain and serialize publishing**. A failed file
publish does not update metadata. Never reopen after a partial publish until
parity or the saved indexes/metadata are restored.

## Migration and verification tools

```sh
# Trusted private sources only, no network and no Supabase writes:
python tools/publish_problem_files.py --publish \
  --manifest /private/backup-manifest.json --objects /private/objects \
  --catalog /private/read-only-verification-catalog.json
python tools/verify_backend_problem_files.py \
  --catalog /private/read-only-verification-catalog.json
```

Set local mode and the two canonical root variables for both commands. The
manifest must come from authenticated backup decryption and match current
read-only Storage IDs/sizes/update times; a checksum alone is not authority.
The verifier reuses production loaders with the existing in-memory catalog,
checks all object hashes, complete test hashes/counts, raw input/output bytes
including samples, and selected PDF bytes. It performs no network requests,
compilation, reference execution or submissions. The private catalog is not Git.

## Future authoring: files never upload to Supabase Storage

Follow [making-problems.md](making-problems.md), preserve templates/IDs/PDF style
and perform real offline validation before publishing. Set `GRADER_FILE_STORAGE=local`
and the exact protected backend roots in the trusted publisher environment. Existing
`tools/import_problems_supabase.py` now writes file bytes to local roots, then
updates **Postgres metadata only**; its name describes that retained metadata
integration. `--statements-only` still preserves tests/limits/publication flags. Full local
publishing writes empty legacy `samples_data` bytes while preserving sample
names: both the worker and sample API read canonical backend files. Existing
legacy DB sample copies are unused and retained until an approved cleanup.
The live CLI refuses legacy cloud-file publishing and local `--prune` before DB
access. `--dry-run` remains read-only; it does not prove publication success.

Publishing remains a separately approved production-data operation: back up,
pause admission, drain/stop all four worker instances, publish files/metadata, verify all
changed suites/PDFs/visibility, create and recover an off-host backup, then restart
and reopen. Never run unreviewed author tools or references with production keys.

## Backup, restore and application rollback

See [host backup and recovery](HOST_BACKUP_RESTORE.md). Configuration snapshots
and table exports do not contain protected problem-file bytes; maintain and
recover a separate encrypted off-host file archive. Restore into empty roots,
verify modes/hashes/catalog parity, merge the append-only UID ledger and run
native compiler/runtime denial probes before activation.

Pause admission and drain queued/running jobs and live leases before stopping
workers or publishing. Reopen only after complete file/metadata parity and
worker preflight. Application rollback uses a verified compatible release on
the current PC, preserving file generations and the newest UID ledger. There
is no automatic cloud-file or retired-host fallback.
