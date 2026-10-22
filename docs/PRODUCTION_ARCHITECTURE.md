# Current production architecture

Updated 2026-10-20 after the operator-approved problem-file publication and
catalog renumbering. The backend application remains the existing
`f88a406-peer-learning-20261020` release; this catalog release did not deploy
application code.

- **Frontend:** Cloudflare Pages, `https://newbiegrader.pages.dev`; vanilla SPA.
- **API route:** same-origin Pages Function → private Cloudflare Worker/service
  binding → specific VPC Service → outbound Tunnel → loopback Nginx/FastAPI.
- **Backend:** AWS EC2 Sydney, Ubuntu 24.04 x86_64, **t3.small (2 vCPU / 2 GiB)**.
  Separate systemd API and **one** judge worker. Public FastAPI HTTP is not used.
- **Database, auth and durable queue:** existing Supabase project. No migration
  of user identities or relational data is part of the file-storage work.
- **Problem files:** problem PDFs, public samples and private tests are stored on
  backend disk under `/var/lib/newbiegrader/problem-files/g1-4e9ba14273bc/`
  and read with `GRADER_FILE_STORAGE=local` (release `609bbf1`). Supabase
  Storage objects are retained only as an explicitly selected recovery source;
  there is no runtime cloud-file fallback in local mode.
- **Catalog:** 89 problems / 1,594 cases / 89 selected PDFs, with 3,532 active
  logical file objects. Difficulty numbering: easy 1–47, medium 48–81, hard 82–89.
  Slug IDs remain stable; relational metadata remains in Supabase.
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
