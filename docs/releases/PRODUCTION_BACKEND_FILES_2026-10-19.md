# Production backend problem-file deployment — 2026-10-19

Status: **DEPLOYED and accepted**. Problem PDFs, public samples and private tests
now live on the backend EBS volume. Supabase still holds relational metadata,
auth and the durable queue. No database migration, auth mutation, schema change,
second worker or paid infrastructure increase was performed.

## Current production

| Component | Verified state |
| --- | --- |
| Public application | `https://newbiegrader.pages.dev` (frontend unchanged, `app.js?v=52`) |
| Routing | Pages Function → private Worker → VPC Service/tunnel → loopback Nginx/API |
| Backend | AWS EC2 Sydney, Ubuntu 24.04 x86_64, **t3.small**, 2 vCPU / 2 GiB |
| Active release | `/opt/newbiegrader/releases/609bbf1f49c510d914c440763bb2304a45db376e` |
| Source artifact | SHA-256 `86831047a09274596fc491ff1d0e350a97d4b608137789e29bff58e68a1a1918` |
| File source | `GRADER_FILE_STORAGE=local`; `/api/version.system.problem_file_storage = local` |
| Staged generation | `/var/lib/newbiegrader/problem-files/g1-4e9ba14273bc/{public-files,private-files}` |
| Admission / queue | Open; done 53, error 0, queued 0, running 0 after the synthetic job |
| Services | API 320 MiB / 25% CPU; one worker 1 GiB / 100% CPU; tunnel active |
| Previous release | `f88364747037d800ae1abf3bb799fdde450d7c33` (AWS rollback target) |

## Changes delivered

- `backend_problem_files.py`: immutable SHA-256 blobs, atomic indexes, retained
  manifests, explicit public/private classification, strict ownership/path/
  symlink/hardlink/permission/checksum checks and no cloud fallback.
- `problem_store.py`: all test/PDF reads use local roots in local mode, including
  public samples; legacy inline sample bytes are ignored; no full private suite
  cache is retained.
- `server.py`: startup role validation, metadata-only admission, sample
  authorization before reads, `problem_file_storage` in `/api/version`, and
  fail-closed missing/corrupt files. Hidden paths are not exposed.
- `tools/import_problems_supabase.py`: live publishing requires local mode,
  rejects cloud uploads/prune and writes file bytes before Postgres metadata.
- `tools/publish_problem_files.py`, `tools/verify_backend_problem_files.py`,
  `tools/ec2_problem_file_canary.py`, `deploy/ec2/backup_state.py` and regression
  tests. No frontend change.

Judging engine, isolation, worker, dependencies, budgets, routing, auth, schema
and the frontend were not changed. `grader.py`, `judge_runner.py`,
`job_sandbox.py`, `job_resources.py`, `worker.py`, `requirements.lock` and
`requirements.txt` hashes match the previous release.

## Executed rollout

1. Rechecked Git, production services, queue, disk and memory. The active release
   was the recorded `f883647`; admission was open, queue was done 52 / error 0.
2. Installed the reviewed archive into a new immutable release directory and
   verified the archive hash plus all core source hashes. `current` was not
   switched yet.
3. Created a **new** file-migration controller
   (`/var/lib/newbiegrader/maintenance-reports/file-migration-609bbf1/`). It
   snapshotted the release, admission, queue, service budgets, protected config
   hashes and worker gate, armed a 45-minute independent rollback timer before
   pausing, paused admissions, drained to queued/running zero and stopped the
   singleton.
4. Ran bounded credential-free parity against the staged generation with the
   candidate production loaders: **2679 objects, 68 problems, 1178 cases,
   68 selected PDFs**, raw suite bytes equal, tests hashes equal, 0 network
   requests, 0 program executions, max RSS 118424 KiB.
5. Ran the gated native suite (same approved cgroup/approval convention, no
   Supabase credentials): **21/21 passed, 0 skipped** in 47.835 s. Peak synthetic
   job memory was 268435456 bytes; 8 intentional contained-OOM kills occurred
   inside job cgroups. The canary left no `.canary-*`, workspace or cgroup
   residue. Its temporary `TMPDIR` was moved outside the workspace root so the
   asset-root guard was exercised honestly rather than bypassed.
6. Re-ran parity after the canary: same counts, 0 network, max RSS 108680 KiB.
7. Created an off-host age-encrypted data backup with shared locks on public then
   private roots:
   `20261019T122951Z-file-data.tar.age`, **188,882,136 bytes**, SHA-256
   `fae766fadeab7a6ae0120804c799ac29a3bb43980b5bc90a2926718b770566c5`.
   Decryption was verified. It was restored into a disposable `0700` directory
   on EC2 and re-verified: **2679 objects / 68 problems / 1178 cases / 68 PDFs**;
   public/private index hashes matched the live generation
   (`4da9dedbbd696cb1...` / `bc92351152ad0270...`). The disposable restore was
   removed. EBS-only copies are not counted as off-host backup.
8. Added root-owned `0600` `/etc/newbiegrader/problem-files.env` and reviewed
   `30-problem-files.conf` drop-ins for API and worker. Switched `current` to the
   candidate, restarted the API while paused, confirmed local storage, ran the
   real worker `--check` with its isolation profile without claiming a job, then
   started exactly one worker.
9. Verification while paused: 206 public samples and 68 selected PDFs matched
   the staged bytes through loopback; six samples and three PDFs matched through
   public HTTPS; hidden sample names returned 404; API identity could read
   public but not private files; the worker could read private files; anonymous
   public smoke passed **15/15**.
10. Submitted one synthetic CE job
    (`265358a0-bb27-4040-9def-2a4c433c3529`, source
    `#error RELEASE_SYNTHETIC_FILE_CE_ONLY …`) for `hanoi` via the same durable
    `judge_queue_admit` RPC used by the API. Result: **one job, attempt 1,
    verdict CE, exactly one linked submission owned by the synthetic email**.
11. Reopened admission, repeated the public smoke **15/15**, then stopped the
    rollback timer only after final checks: one worker, tunnel active, no second
    worker, no job cgroup/workspace, no API/worker OOM, queue done 53 / error 0.
12. Encrypted configuration/UID/tunnel plus the new file-mode env and drop-ins:
    `20261019T124435Z-ae06c238.tar.age`; authenticated decryption verified.

## Evidence and limits

- Local implementation suite before deployment: 310 tests (307 passed, three
  private-fixture modules skipped), critical 230/230, JavaScript 76/76 with zero
  skips; compile, DOM/style guards and plagiarism self-test passed.
- A real authenticated `POST /api/submit` was **not** run: no legitimate test
  session existed and creating/altering auth users was outside authorization.
  The HTTP submit route was checked for authentication, CSRF and paused
  admission; the worker/judging path was exercised by the synthetic queued job
  and the 21-test native suite. Fresh Google/OTP login was not tested.
- No second real user, sustained load, full 68-reference execution, contest
  freeze/rejudge, or CPU-credit exhaustion was tested in this rollout.
- S04 descendant declared-memory verdict accounting remains open.
- Historical inline `samples_data` and submission feedback remain in PostgreSQL;
  local mode ignores inline testcase copies. Not all historical testcase bytes
  have been erased from Supabase.
- The first public health request after the API restart was cold (about 25.8 s);
  subsequent requests were fast. A transient 502 had also been seen in the
  earlier release. No root cause is claimed.

## Protection and recovery artifacts

Keep these private; do not copy credentials or private keys into Git.

- Off-host data backup: `~/.local/share/newbiegrader-private/ec2-backups/20261019T122951Z-file-data.tar.age`
- Configuration backup: `~/.local/share/newbiegrader-private/ec2-backups/20261019T124435Z-ae06c238.tar.age`
- Migration controller/state: `/var/lib/newbiegrader/maintenance-reports/file-migration-609bbf1/`
- Staged immutable data: `/var/lib/newbiegrader/problem-files/g1-4e9ba14273bc/`
- Original source/parity/catalog staging: protected local migration directory
  recorded by `/tmp/newbiegrader-backend-files-path` (do not overwrite it).

## Rollback

Application rollback stays on AWS:

```sh
sudo python3 /var/lib/newbiegrader/maintenance-reports/file-migration-609bbf1/controller.py rollback
```

It pauses/drains, stops the singleton, removes only the file-mode drop-ins,
restores `f88364747037d800ae1abf3bb799fdde450d7c33`, runs health/preflight,
restarts the worker and reopens admission. Keep the local data, UID ledger and
encrypted backups. Do not reuse the completed first-release controller.

Supabase Storage objects are **not deleted**. Deleting them requires explicit
approval for the exact manifest-bound scope; after deletion the old
Supabase-file release is no longer a valid rollback target.
