# Problem 69: backend file publication repair — 2026-10-20

Status: completed and accepted on the existing AWS release. This was a data-file
repair, not an application deployment or database migration.

## Observed failure

`lucky_bracelet`, number 69, was already present in public PostgreSQL metadata
and `/api/version`, with 16 cases and tests hash `29f5db304089ede7`. Its metadata,
statement and hash matched the local package. Neither protected backend file
index contained its assets. All 33 required files were missing: 16 input/output
pairs and one PDF. Before repair, the public PDF returned 500 and sample 01
returned 503; EC2 loopback reproduced both failures. Thus metadata presence was
not evidence of successful publication.

## Validation and changes

- Used a protected, isolated copy of the package and committed tool sources;
  preserved all original dirty worktrees.
- Docker Linux ARM64/root, Python 3.11, no network or production credentials:
  strict package validation passed, Python reference AC 16/16, slowest 0.107s.
- Independently checked all 16 fixture answers using grouped prefix residues;
  300 deterministic small inputs matched exhaustive enumeration; 12 malformed
  inputs were rejected; four deliberately wrong algorithm models were rejected.
- Rendered and visually inspected both existing PDF pages. No source/PDF edits.
- Armed a dedicated 30-minute rollback timer, paused admission, drained queued
  and running counts to zero, and stopped the singleton worker.
- Encrypted an off-host snapshot before modification and verified authenticated
  decryption. Published exactly 33 files with the current immutable backend
  publisher. Preserved all pre-existing index entries byte-for-byte.
- **No PostgreSQL rows or Supabase Storage objects were written or deleted.**
- Native credential-free verification with PrivateNetwork, MemoryMax 512 MiB and
  CPUQuota 50% verified all 2712 active assets, 69 problem suites / 1194 cases,
  and 69 selected PDFs. No reference/submission programs executed on EC2.
- Took a second encrypted off-host snapshot, restored into a separate protected
  EC2 directory, repeated full verification, then removed only that disposable
  restored copy. The age private identity remained on the operator Mac.
- Restarted only the existing singleton worker and API to reopen admission;
  accepted after public checks. Dedicated rollback timer stopped.

## Evidence

| Item | Recorded value |
| --- | --- |
| Unchanged backend | `/opt/newbiegrader/releases/f88a406-peer-learning-20261020` |
| Maintenance operation | `lucky-bracelet-ccc999e6b7` |
| Public index SHA-256 after repair | `79660f7ca228c8ff7de879fa32e3f00809c96ec0c4bfc09c6ec6411b2766474c` |
| Private index SHA-256 after repair | `b1799322ea87ee6be62375fb750714e64d3f171e0a187cb59f35d1283b37167e` |
| PDF SHA-256 | `c9f7c156db016887b52e8e6cb38a4a97eb89ec8b10ce4accf3e9e67b0111147c` |
| Before encrypted archive | 188318792 bytes; SHA-256 `3ad54fd0af1a68bf2aa1f2141f6522cdf89912ed7947832b4243101623a0fa51` |
| After encrypted archive | 193388840 bytes; SHA-256 `58eaf7abd650d8488dd4fbeca7fdf1586678b54521d811615de94c0bf382e026` |
| Final queue | queued 0, running 0 |
| Final services | API and singleton worker active; admission enabled |

Mac operator public-HTTPS vantage: PDF exactly matched the package bytes; all
three public samples exactly matched canonical fixtures; sample/1001 returned
404. After reopening, health, detail and PDF each returned 200. A public HTTP
submission or fresh OAuth login was not exercised; no claim of either is made.

Protected operational scripts/evidence/backups are outside Git under the
operator's `newbiegrader-private/verify-lucky-bracelet-*` directory. Root-only
maintenance evidence is under `/var/lib/newbiegrader/maintenance-reports/` on
EC2. No hidden data, references, credentials or private identity is in this record.

The existing problem advertises 256 MB while the host has an effective 128 MB
declared cap. That pre-existing host policy was not changed by this repair.

## Recovery

The operation's automatic rollback restored only its saved indexes and service
admission state; that would restore the original missing-file condition for
this problem. It was disabled after acceptance. Do not run its controller
against later publications. For later recovery, restore a coherent catalog and
file snapshot into separate protected roots, verify it, then switch under a
new maintenance transaction; do not overwrite newer indexes blindly.
