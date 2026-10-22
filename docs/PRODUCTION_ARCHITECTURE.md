# Current production architecture

Updated 2026-10-22 after the difficulty renumbering, the EC2 application
release and the addition of the scheduled backup and the health watchdog.

- **Frontend:** Cloudflare Pages, `https://newbiegrader.pages.dev`; vanilla SPA.
- **API route:** same-origin Pages Function → private Cloudflare Worker/service
  binding → specific VPC Service → outbound Tunnel → loopback Nginx/FastAPI.
- **Backend:** AWS EC2 Sydney, Ubuntu 24.04 x86_64, **t3.small (2 vCPU / 2 GiB)**.
  Separate systemd API and **one** judge worker. Public FastAPI HTTP is not used.
  The instance exposes 2 vCPU on **one physical core**: two judge workers would
  share that core and each run about 2.1x slower, so the worker count stays at
  one and the unit allows it a single CPU.
- **Deployed release:** `d63e8dd6c4a519c81eb337b1a6d5cedf38189983`, source
  fingerprint `ffd2a32edbc212eaca7216d51d168726210ef0613bbaf1433a024dcb82a4b014`.
  The previous release is retained as the rollback target.
- **Database, auth and durable queue:** existing Supabase project. No migration
  of user identities or relational data is part of the file-storage work.
- **Problem files:** problem PDFs, public samples and private tests are stored on
  backend disk under `/var/lib/newbiegrader/problem-files/g1-4e9ba14273bc/`
  and read with `GRADER_FILE_STORAGE=local`. Supabase Storage objects are
  retained only as an explicitly selected recovery source; there is no runtime
  cloud-file fallback in local mode.
- **Catalog:** 89 problems / 1,594 cases / 89 selected PDFs. The numbers follow
  the calibrated level of each package: **easy 1–40, medium 41–78, hard 79–89**.
  Slug IDs remain stable; relational metadata remains in Supabase.
- **Scheduled backup:** `newbiegrader-backup.timer` runs daily and writes one
  age-encrypted archive to the private `judge-backups` Storage bucket. The
  archive holds the configuration, the sandbox UID ledger and every public
  table read through the service key; the schema, policies and grants come from
  the committed `supabase/schema.sql`. The age **private** identity stays on the
  operator machine, so the host only holds the recipient public key.
- **Health watchdog:** `newbiegrader-alert.timer` runs every five minutes and
  checks the API, the worker, the tunnel, the durable queue, the disk, the age
  of the last backup and the journal. It posts one message per transition into
  a broken state to a Discord bot channel. The webhook configuration is a
  root-owned 0600 file and never appears in the argument vector or the journal.
- **Vercel:** not used in this production architecture.
- **JustRunMy:** retired from production; stopped legacy material is retained
  only as historical recovery evidence. Current application rollback stays on
  AWS. There is no automatic legacy-origin retry/fallback.

See the [catalog number map](catalog/problem-numbers-2026-10-22.csv),
[backend file-storage guide](BACKEND_PROBLEM_FILES.md), and
[backup and restore guide](EC2_BACKUP_RESTORE.md). Detailed commands, tests and
release evidence are retained privately.
Historical migration checkpoints in other documents describe their original
observation time; they do not override this current topology.
