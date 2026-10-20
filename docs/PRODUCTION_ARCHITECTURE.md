# Current production architecture

Updated 2026-10-19 after the operator-approved correctness/cache rollout and the
backend problem-file migration.

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
- **Vercel:** not used in this production architecture.
- **JustRunMy:** retired from production; stopped legacy material is retained
  only as historical recovery evidence. Current application rollback stays on
  AWS. There is no automatic legacy-origin retry/fallback.

Current release IDs, commands executed, tests, backup and rollback evidence:
[backend problem-file release record](releases/PRODUCTION_BACKEND_FILES_2026-10-19.md)
and the earlier [correctness/cache record](releases/PRODUCTION_CORRECTNESS_RELEASE_2026-10-19.md).
Historical migration checkpoints in other documents describe their original
observation time; they do not override this current topology.
