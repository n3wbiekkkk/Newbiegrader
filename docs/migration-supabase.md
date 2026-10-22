# Problem metadata and file storage

Current production uses `GRADER_PROBLEM_SOURCE=supabase` for metadata and
`GRADER_FILE_STORAGE=local` for PDF/sample/test bytes. The Ubuntu PC serves the
protected files; Supabase retains metadata, identities, submissions and the
durable queue. See [current architecture](PRODUCTION_ARCHITECTURE.md) and the
[file-storage contract](BACKEND_PROBLEM_FILES.md).

The filename records the original metadata integration. Its former instructions
for uploading production fixtures to Storage and rolling back by changing one
environment variable are superseded by this document.

## Current mapping

| Authoring artifact | Production location | Access |
| --- | --- | --- |
| `config.json` limits, slug, number, level, tags and visibility | Supabase `problems` metadata | API applies publication/contest policy; server controls writes |
| Statement prose | `problems.statement_md` | Authorized detail response |
| Statement PDF | Protected public file root; row selects `statement_pdf_path` | API checks visibility before serving bytes |
| Explicit sample input/output | Protected public file root; row retains sample names | Only named public samples through the sample API |
| Other test input/output | Protected private file root; row retains names, sizes and hashes | Trusted judge worker; feedback follows the practice/contest policy |
| Reference solutions and input validators | Private operator authoring packages | Excluded from Git and application releases |

Legacy Storage objects and `samples_data` may still exist. They are unused by
production local-file reads. Removing them requires a separately scoped cleanup;
this host migration did not delete them. New local-file publication writes empty
legacy sample-byte copies while retaining canonical sample names.

## Authoring and publication

Follow [making-problems.md](making-problems.md), including strict checks for new
problems, canonical PDF tooling and sample synchronization. Keep `problems/`,
`examples/`, credentials, catalogs and recovery files private.

Use the existing importer with the exact protected file roots in its trusted
server environment. It publishes file bytes to disk first and updates Postgres
metadata afterward. Its name reflects the retained database integration.

```sh
python tools/import_problems_supabase.py --problem new_problem --strict --dry-run
# Only after authorized backup, admission pause, drain and worker stop:
python tools/import_problems_supabase.py --problem new_problem --strict
```

`--dry-run` writes nothing and does not prove a successful publication.
`--statements-only` updates prose/PDF without changing tests, limits or visibility.
The live CLI refuses cloud-file publication and refuses local-file `--prune`.
An unchanged tests hash does not remove the need to reconcile selected files.

Publishers serialize changes to files and metadata; there is no transaction
across both systems. Before reopening admission, verify complete package/hash
parity, selected PDFs, sample bytes, visibility and encrypted off-host recovery.
Restart all four workers after a file publication and reload API metadata as
required. Preserve permanent slugs, history and the newest UID ledger.

Catalog renumbering requires an explicitly approved committed map. Follow the
numbering section in the authoring guide; do not use the old automatic
`--renumber` examples as authorization to change an existing catalog.

## Runtime behavior

- Missing Supabase credentials in metadata mode refuse startup. There is no
  automatic fallback to the private local authoring checkout.
- Browsing uses metadata and selected public files, without loading hidden tests.
  Metadata refresh and PDF version invalidation are described in
  [problem-loading.md](problem-loading.md).
- Each claimed submission revalidates its problem metadata, publication status,
  selected file bytes and tests hash against the admitted version. Local-file
  mode retains no full private-suite cache between jobs.
- The isolated runner receives the trusted resolved suite. It has no database
  credentials and accepts no client-selected filesystem paths.
- An absent, unsafe, corrupted or mismatched asset is an infrastructure error;
  an incomplete or empty suite never becomes Accepted.
- Visibility and live feedback policy are separate. Disclosure checks bypass the
  contest cache where required; see [submission-feedback-policy.md](submission-feedback-policy.md).

For application rollback, pause/drain and use a compatible verified release on
the PC with the current file generation and append-only UID ledger. Changing
`GRADER_PROBLEM_SOURCE` alone is not an approved production rollback.

## Schema and verification

The existing append-only `supabase/schema.sql` defines metadata, identity and
queue permissions. No schema change was needed for the PC migration. Future DDL
must be reviewed and applied by the maintainer through Supabase SQL Editor.
Never replay an import or migration merely to check documentation.

CI uses synthetic fixtures and fake Supabase, plus an empty disposable PostgreSQL
instance for real SQL/ownership checks. Public Git contains no private problem
set. Run the full private-package checks from an authorized operator checkout;
use the official file verifier and current host checks before production changes.
