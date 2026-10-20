# Backend problem-file storage

2026-10-19: **DEPLOYED and accepted in production** after native parity, the
gated 21-test suite, an encrypted off-host backup with a verified restore
rehearsal, and controlled activation. Release `609bbf1f49c510d914c440763bb2304a45db376e`
serves all problem PDFs, public samples and private tests from backend disk;
`/api/version.system.problem_file_storage` reports `local`. Metadata, auth and
the durable queue remain in Supabase. See the
[production release record](releases/PRODUCTION_BACKEND_FILES_2026-10-19.md).

The operator explicitly requested moving files to the backend. No database
migration or user-data rewrite was needed. This document keeps the design and
operating rules; the release record holds the exact deployment evidence.

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
- Frontend remains Cloudflare Pages, backend remains AWS t3.small / one worker.
  Vercel and JustRunMy are not used. No second worker or metadata mirror timer.

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

Preparation evidence actually executed:

- Fresh read-only database snapshot matched the verified Storage backup:
  **68 problems, 1178 cases, 2679 objects / 185493091 raw bytes**; source writes=0.
- Docker Linux ARM64/root, network none: all 2679 objects published/verified;
  all 68 problem hashes, 1178 cases and 68 selected PDFs matched. Largest suite
  19808282 bytes, max RSS 114780 KiB, zero retained full-problem cache entries.
- EC2 t3.small, 2026-10-19, against the staged generation `g1-4e9ba14273bc`:
  production loaders re-verified **2679 objects / 68 problems / 1178 cases /
  68 selected PDFs**, raw suite bytes equal, tests hashes equal, 0 network
  requests, 0 program executions, max RSS 118424 KiB. The gated native suite
  then passed **21/21 tests, 0 skipped** in 47.835 s (peak synthetic job memory
  268435456 bytes; the intentional contained-OOM tests reported 8 controlled
  job OOM kills, all inside the job cgroup).
- Logical indexes: **687 public objects** (275 PDF variants + 412 public sample
  files) and **1992 private objects**, 2679 active objects total. Content-hash
  deduplication stores 553 + 1799 = 2352 unique blobs; the remaining logical
  objects reuse identical bytes. Historical immutable blobs are retained, so
  physical file counts are larger than the active index.
- The complete package also retains older private assets/PDF versions: 275 PDF
  logical objects before selecting sample permissions. Public sample files are
  separately whitelisted from the matching source catalog; all other test files
  stay private. Only existing authorized
  problem/PDF/sample routes expose selected public data.
- Synthetic regression suite covers permissions, compiler denial, corruption,
  missing files, no Storage fallback, path/hardlink/symlink/static/workspace
  rejection, atomic failure, concurrent publishers, API metadata-only playground
  and source-backup verification. Linux/root checks do not silently skip in CI.

Native deployment (2026-10-19): candidate `609bbf1f49c510d914c440763bb2304a45db376e`
installed at `/opt/newbiegrader/releases/609bbf1f49c510d914c440763bb2304a45db376e`;
`/etc/newbiegrader/problem-files.env` plus `30-problem-files.conf` drop-ins set
`GRADER_FILE_STORAGE=local`, the staged public/private roots and
`GRADER_FILE_MIN_FREE_MB=1024` for both API and worker. Admission was paused,
drained and the singleton stopped before the switch; the API restarted in local
mode, the real worker `--check` passed with its isolation profile, and exactly
one worker restarted. The 45-minute recovery timer was stopped only after the
public checks and one synthetic CE job passed. Exact IDs, backup hashes and
limits are in the [release record](releases/PRODUCTION_BACKEND_FILES_2026-10-19.md).

Do not infer deployment from Docker checks alone; those checks remain local
evidence. A real authenticated `POST /api/submit` was not exercised because no
legitimate test session was available. The synthetic CE job used the same
durable `judge_queue_admit` RPC as the API; the HTTP submit route was checked for
authentication/CSRF/paused admission only. Fresh Google/OTP login is also not
claimed.

## Future authoring: files never upload to Supabase Storage

Follow [making-problems.md](making-problems.md), preserve templates/IDs/PDF style
and perform real offline validation before publishing. Set `GRADER_FILE_STORAGE=local`
and the exact protected EC2 roots in the trusted publisher environment. Existing
`tools/import_problems_supabase.py` now writes file bytes to local roots, then
updates **Postgres metadata only**; its name describes that retained metadata
integration. `--statements-only` still preserves tests/limits/publication flags. Full local
publishing writes empty legacy `samples_data` bytes while preserving sample
names: both the worker and sample API read canonical backend files. Existing
legacy DB sample copies are unused and retained until an approved cleanup.
The live CLI refuses legacy cloud-file publishing and local `--prune` before DB
access. `--dry-run` remains read-only; it does not prove publication success.

Publishing remains a separately approved production-data operation: back up,
pause admission, drain/stop the singleton, publish files/metadata, verify all
changed suites/PDFs/visibility, create and recover an off-host backup, then restart
and reopen. Never run unreviewed author tools or references with production keys.

## Backup and restore

Keep the existing age private identity **only off-host**. Config/UID/tunnel backup
must include `--include-problem-files-config`; this includes the shared file env
and API/worker drop-ins but **not** the file data.

For data backup, use both directory locks in the publisher's order while making
one archive of public/private roots. Stream SSH stdout directly into local age
encryption, check both process exits, verify authenticated decryption and restore
into **new empty private directories**. Never restore over live roots or upload
the private age identity. Verify indexes, all blobs and the matching exported
catalog after restore; protect metadata/file generations consistently during
future updates. EBS-only copies are not an off-host backup. Automatic off-host
backup scheduling is not established by a manual successful rehearsal.

Executed 2026-10-19: `20261019T122951Z-file-data.tar.age` (188,882,136 encrypted
bytes, SHA-256 `fae766fadeab7a6ae0120804c799ac29a3bb43980b5bc90a2926718b770566c5`)
contains both locked roots plus the private verification catalog. Authenticated
decryption passed. It was restored into a disposable `0700` EC2 directory,
re-verified (2679 objects / 68 problems / 1178 cases / 68 PDFs, identical public
and private index hashes), then removed. Configuration/UID/tunnel plus the new
file-mode env and drop-ins were separately encrypted as
`20261019T124435Z-ae06c238.tar.age`; decryption was verified. Both files stay in
the protected off-host backup directory with the age identity.

## Cutover and rollback gates

All pre-cutover gates passed on 2026-10-19: current-source parity, native
checksums/permissions, negative compiler/runtime access canaries, actual worker
preflight and encrypted backup/restore. API/worker budgets and concurrency were
unchanged. `/etc/newbiegrader/problem-files.env` and reviewed service drop-ins
are root-owned; the credential-bearing API/worker env files were not printed.

After switch, `/api/version.problem_file_storage` reported `local`; 206 public
samples and 68 selected PDFs matched the staged bytes through loopback, six
samples/three PDFs matched through public HTTPS, hidden sample names returned
404, anonymous checks passed 15/15, and one synthetic CE job produced exactly
one job (attempt 1), one linked submission and an empty queue. No job cgroup,
workspace, API/worker OOM or second worker remained. Admission was then reopened
and the recovery timer stopped.

Application rollback stays on **AWS**, never Vercel/JustRunMy. New controller:
`/var/lib/newbiegrader/maintenance-reports/file-migration-609bbf1/controller.py`
(`status`, `rollback`; the first-release controller is a completed, separate
transaction). Rollback pauses/drains, stops the singleton, removes only the
file-storage drop-ins, restores the recorded previous AWS release
`f88364747037d800ae1abf3bb799fdde450d7c33`, runs preflight, restarts services and
reopens admission. Keep the local files/immutable versions/current UID ledger.
Previously retained Supabase files are only an explicitly selected recovery
source, never an automatic fallback. If old Storage copies are later removed,
rollback must use a compatible verified AWS local-file release or restore the
reviewed file backup first; the old Supabase-file release is no longer a valid
operational rollback target.
