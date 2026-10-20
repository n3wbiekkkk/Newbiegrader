# Twenty-problem catalog release — 2026-10-20

Status: published and accepted on AWS. The operator requested **20 new problems**
and explicitly approved **renumbering every problem by difficulty**. The earlier
[problem 69 file repair](PROBLEM_69_FILES_2026-10-20.md) was completed first.

## Scope and result

- Catalog: **69 → 89 problems**, **1,194 → 1,594 cases**.
- New problems: 20 cases each, including three public samples; 2 seconds / 128 MB.
- Current numbering: easy 1–47, medium 48–81, hard 82–89. These are instructional
  tiers, not empirical difficulty ratings. Existing order within each tier was
  retained. See the [complete old/new map](../catalog/problem-numbers-2026-10-20.csv)
  and [new-problem catalog](../catalog/NEW_PROBLEMS_2026-10-20.md).
- Existing slug IDs, tests, limits, statements, visibility and history references
  were preserved. Previous numeric aliases intentionally have new meanings.
- Backend remains `/opt/newbiegrader/releases/f88a406-peer-learning-20261020`;
  engine 2.0.7, t3.small, one worker. This was a file/catalog publication, not an
  application deployment, infrastructure resize or worker-concurrency change.
- Files remain on protected backend disk; Supabase remains authoritative for
  metadata, auth and durable queue. No Supabase Storage objects were written or
  deleted. No schema, RLS, grant, authentication or user-data migration occurred.
- Current active file indexes describe **3,532 logical objects**, 89 selected
  PDFs and 1,594 cases. All old entries were preserved; 820 objects were added.

## Authoring and correctness evidence

Used the versioned scaffold, validators, canonical sample synchronization and
`tools/make_statement_tex.py`. Kept problem packages, generator/oracle scripts,
references and test bytes outside public Git. New prose and data were authored
for this project; topic references and overlap review are recorded in the
[catalog](../catalog/NEW_PROBLEMS_2026-10-20.md).

Actual checks in an isolated Docker Linux ARM64/root environment, Python 3.11,
GCC, no network or production credentials:

| Check | Actual result |
| --- | --- |
| `python tools/validate_problem.py <new-id> --strict`, all 20 IDs | 20 packages passed; reference AC 400/400 |
| `python tools/import_problems_supabase.py --strict --dry-run --problem <id> ...` | 20 checked, 0 failed; offline, no remote writes |
| Independent answer checks | All 400 shipped case answers checked with alternate small-case or closed-form oracles |
| Additional deterministic randomized comparisons | 6,000 matched independent brute-force/alternate implementations |
| Invalid-input checks | 281 malformed inputs rejected |
| Deliberately wrong solution canaries | 20/20 rejected by the actual engine with WA |
| Full Python suite with all 89 private packages available | 423 passed, 0 skipped |
| `python tools/run_critical_tests.py` | 252 passed, 0 skipped |
| `node --test tests/test_*.js` on macOS | 101 passed, 0 skipped |
| Python compile, JS syntax, frontend/style guards, plagiarism self-test | Passed |
| PDF review | 20 PDFs / 40 rendered pages individually inspected |

Strict validation is not a proof of algorithmic correctness or complete test
coverage. The independent checks and wrong solutions are additional evidence,
not an exhaustive proof. Linux test hosts were ARM64; no contestant code was
executed on production as part of this publication.

The private-package suite exposed an existing stale assertion in
`tests/test_problems_supabase.py`: it expected immediate HTTP 500 for missing
hidden bytes. Unmodified `fa612a3` reproduced HTTP 202 because admission is
metadata-only. The corrected test follows the job to an infrastructure error
and requires no verdict/result or persisted submission. Production behavior was
not relaxed. Public CI has no private packages, so those private-package tests
also ran separately rather than relying solely on GitHub Actions.

The reported CI failure for historical `d288d99` was independently reproduced:
all 14 peer-inspection tests failed because a missing source-slice boundary
loaded app code twice (`SHORT_TIME_OPTS` redeclaration). It was already fixed by
`b919a70`, merged in `fa612a3`; that version passed 15/15 focused tests. Its
[GitHub CI run](https://github.com/n3wbiekkkk/Newbiegrader/actions/runs/39385768677)
passed validate, critical-security and queue-sql. No duplicate CI fix was made.

## Publication safety and live verification

Maintenance operation: `problem-expansion-bd52760894`. Protected root-only
evidence is under `/var/lib/newbiegrader/maintenance-reports/` on EC2; encrypted
off-host backups and authoring evidence are in the operator's private store.

1. Read-only preflight checked the complete 69-row metadata snapshot, unique
   numbers and references. No numeric problem references were found in contest,
   submission, job or report records; contests were empty at the snapshot.
2. Rehearsed the exact activation SQL in disposable PostgreSQL 17 with cloned
   relevant types/constraints. Valid activation produced 89 unique numbers;
   stale replay and numeric-reference guards refused; an injected failure after
   parking numbers rolled back the entire transaction.
3. Armed a dedicated rollback timer, paused admission, observed queued/running
   zero twice, and stopped only the singleton worker. Encrypted the original
   matching files/catalog and verified authenticated decryption off-host.
4. Published checksum-verified assets first. Public root is root:API 0750 with
   files 0440; private root is root:root 0700 with files 0400. Native verification
   initially refused staged metadata mode 0644; it passed after tightening that
   staged file to 0600. The verifier was not weakened.
5. Activated metadata at `2026-10-20T08:12:46.029565+00:00` in one guarded
   PostgreSQL transaction. Table locks blocked concurrent reference changes;
   temporary negative numbers never became a separately committed state.
   Inserted 20 rows and changed old numbers only; readback confirmed old content
   and `created_at` unchanged. The SQL digest was
   `ca85ac04cdf04861ff6f857dc46f545af08033de0a7f6027cc7b1b0fde15fcec`.
6. Restarted the API while paused. Credential-free native EC2 verification
   under PrivateNetwork, 512 MiB MemoryMax and CPUQuota 50% verified all 3,532
   objects, 89 suites / 1,594 cases and 89 PDFs. Peak RSS was 116,624 KiB;
   zero submission programs or network requests were used by this check.
7. Took an encrypted post-publication backup, restored it into an independent
   root-only EC2 directory and repeated full verification (peak RSS 100,476 KiB).
   Removed only that disposable restored copy.
8. From the operator Mac over public HTTPS outside AWS, all 20 details and PDFs
   matched, all 60 public samples matched exact bytes, hidden sample 1001 returned
   404 for each new problem, and all 20 new numeric aliases resolved correctly.
9. Resumed the existing worker and admission; public HTTPS smoke passed 15/15:
   `python deploy/ec2/smoke_https.py --production --expected-problems 89 --expected-samesite none`.
   Accepted with queued 0 / running 0 and disabled the dedicated rollback timer.
   No operation-specific pause or rollback timer remains active.

The smoke tool now accepts an explicit expected count rather than assuming the
historical 68 everywhere. Its default remains 68 for compatibility with old
staging fixtures; production commands must specify the reviewed count. New
tests reject a stale 68-entry catalog when 89 is expected. The frontend cache
namespace changes to `ng_problems_v3` and app asset to `v=56`, so the old one-hour
browser catalog cannot retain obsolete numbers after that asset is published.

## Recovery records

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| Before files/catalog, encrypted | 193859992 | `27d8c3911473af9489786096a6c242509d7f8d7b35d5c71a84a44fa4c8e429f0` |
| After files/catalog, encrypted | 228991768 | `d6c37f5df881c3a8cd90067a1ec6e0c40f4d0e47ab0751ac24a8157ca7425183` |
| Authoring source, references and original configs, encrypted | 6184485 | `e8956b43bbb8ce5c031341d8831df4da52fe7d69daf2814737aec76a844906fd` |
| Public index after | — | `2c0cb7a3f50f7048a1e4676df547efcdcaacae1229f1e8448593ad1c15d702b2` |
| Private index after | — | `602998f0461ef8178e84d8b91b54341ff69e80defe185130a5988d9effa86ce0` |

All three encrypted archives passed authenticated decryption. The age private
identity stayed on the operator Mac. These file/catalog backups are **not** a
complete PostgreSQL/Auth backup. Existing application secrets/service units
were unchanged; this record does not claim a new full configuration backup.

Do not replay the accepted maintenance controller or its old rollback against
later data. For recovery, prepare a fresh pause/drain operation; restore and
verify coherent files/catalog in separate private roots before switching.
If only numbering must be reverted, use the CSV plus a fresh guarded transaction
and collision checks. Preserve the new rows/files and any subsequent history;
do not delete the 20 problems or restore old indexes blindly after users may
have submitted to them. Application rollback stays on AWS, never JustRunMy.

## Remaining limits

- No fresh Google/OTP login or authenticated public HTTP submission was exercised
  in this operation. Local engine correctness checks do not prove those flows.
- Existing per-host resource policy, S04 status and T3 CPU-credit policy are
  unchanged. One worker remains active; no two-worker deployment is claimed.
- Existing 256 MB problem declarations remain unchanged despite this host's
  effective 128 MB policy; the new 20 explicitly use 128 MB.
- Protected private source is synchronized to 89 packages. Unrelated dirty
  worktrees were preserved; neither they nor a public checkout alone should be
  treated as an automatically deployable replacement for the live backend.
