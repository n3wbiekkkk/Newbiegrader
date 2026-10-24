# Official solution authoring

Read `AGENTS.md`, the problem's complete `statement.md`, `config.json`, public
samples and reference implementation before writing. Keep `problems/`, references,
solution sources and PDFs private and ignored by Git. Never put a solution inside
the statement or change rules, tests, limits, numbering or existing reference code.

## Shared workflow for humans and AI agents

1. Scaffold: `python tools/solution_authoring.py new <id>`. This refuses existing
   sources and uses `tools/templates/solution/`. Complete `solution.md` and
   `solution.py` and `solution.cpp` inside the existing problem package.
2. Explain the actual technique, explicit steps, correctness, time/space costs
   and problem-specific pitfalls in the five required Thai sections. Match code
   and proof; define variables and count large output and integer costs when
   relevant. A passing reference alone does not prove an explanation correct.
3. Include complete executable C++17 and Python 3 solutions. Every PDF must include
   both, with C++17 first. Use safe integer widths, exact decimal arithmetic or
   an explicit big-integer representation when the input bounds require it. Do
   not assume libraries outside the judge toolchain are installed. Independently cross-check
   small/boundary cases and test deliberately wrong approaches where useful.
   Do not include hidden fixture values or machine-specific paths in prose.
4. Build: `python tools/solution_authoring.py build <id>`. Requires `tectonic`.
   The renderer reuses `tools/make_statement_tex.py` typography, fonts, wordmark,
   margins and public sample table; do not invent a separate visual template.
   Code lives in `solution.cpp` and `solution.py`, not Markdown fences. Only public fixtures selected
   by `config.samples` can become examples; long samples are omitted from the
   explanation table rather than clipped.
5. Inspect every rendered page with `pdftoppm -png -r 110 problems/<id>/solution.pdf /private/path/page`. Check Thai glyphs, math,
   indentation, code escapes, line wrapping and page breaks. A wrapped code line
   continues without a repeated line number; the executable source is unchanged.
6. Check: `python tools/solution_authoring.py check <id>` detects incomplete
   sources, changed inputs/template/fonts and PDF corruption. It is a hash and
   syntax check, not proof of correctness or visual quality.
7. Qualify: `python tools/solution_authoring.py verify <id>` uses the canonical
   `grader.py` CLI and current checker against every shipped case in both languages.
   `verify <id> --lang cpp` or `--lang py` rechecks one language; the default is all. Use a qualified
   Linux environment for isolation and limit claims; report failures and skips.
   Direct output comparisons on development machines are supplementary checks.
   Successful qualification writes `solution.verify.json` (Python) and
   `solution.cpp.verify.json` (C++), binding each executable
   code, problem configuration and test set to the recorded result.

The build record `solution.build.json` hashes the source, configuration,
statement, selected public examples, renderer, fonts, logo and generated PDF.
Retain `solution.md`, `solution.py`, `solution.cpp`, PDF and build record on the development
machine and in the private authoring archive; PDF-only deployment is not an
editable authoring backup.

## Member access and protected backend files

The Thai เฉลย tab is second to last, immediately before แจ้งปัญหา. Any signed-in member can read a
solution without an accepted submission. Both metadata and PDF requests check
current publication/visibility and fresh contest policy; upcoming/running contests
block solutions, including old links and conditional requests. Policy outages
fail closed. Responses are `private, no-store`. The browser drops displayed
solutions on identity/task/tab changes and rejects delayed responses.

PDF bytes are stored as `<slug>/solution.pdf` in the existing problem bucket's
protected backend index. API reads use only the API-readable public root; there
is no cloud-file fallback, public static PDF or database schema migration.
"Public root" means trusted API-readable, not anonymously downloadable.

Preview publication with `python tools/publish_solutions.py --all --dry-run`
(or `--problem <id>`); it rejects missing, failed or stale canonical qualification for either language.
A Python-only PDF or missing C++ report cannot pass publication.
Use `--publish` only in the trusted publisher with the current backend roots.

Publish only after all authoring and release gates pass: back up, pause admission,
drain jobs/leases, use `backend_problem_files.publish` under the trusted publisher
with the current backend roots, preserve root/group permissions, verify all hashes
and access rules, then reopen. Deploy the compatible backend before the frontend.
Follow the host deployment and encrypted backup/recovery guides. Do not place
source code, private tests or author archives in HTTP-serving directories.

## Sync private authoring packages between development machines

Git synchronizes source tools; ignored problem packages need a separate private
transfer. Keep a complete author archive on the backend outside application,
static and problem-file serving roots, readable only by the designated operator.
This is a private SSH transfer, not a website download endpoint. Never include
`.env`, credentials or machine-specific configuration.

On the machine with the complete, verified packages:

```sh
python tools/problem_sync.py pack --output /private/path/authoring-YYYYMMDD.tar.gz
```

Transfer the archive to the operator's protected backend directory via SSH/SFTP.
Keep previous dated archives and the existing encrypted off-host backups. The
runtime file generation alone does not contain every editable source/reference.

On either development computer, after updating Git:

```sh
python3 tools/problem_sync.py fetch --host <operator@backend> \
  --remote-path /private/backend/path/authoring-YYYYMMDD.tar.gz \
  --output /private/local/path/authoring-YYYYMMDD.tar.gz
python3 tools/problem_sync.py unpack \
  --archive /private/local/path/authoring-YYYYMMDD.tar.gz \
  --destination /private/local/path/new-staging-folder
```

SSH credentials and aliases are configured independently on each machine. Host
keys must already be verified. Fetch verifies the archive manifest before making
it available; unpack checks every path, size and SHA-256, rejects links, duplicate
names and traversal, and requires a new destination. Files are private (0600).
Compare staging with local `problems/` and `examples/`, back up local changes,
then merge deliberately. No automatic deletion or overwrite is provided. Source
changes made independently on both machines need a manual conflict review.
