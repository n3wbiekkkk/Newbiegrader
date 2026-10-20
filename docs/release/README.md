# Release database and privacy checks

These are **operator-run, read-only first** artifacts for the security integration
branch. They do not deploy code, apply production SQL, or mutate rows by
themselves. Use a change window and keep the Supabase service-role credential on
the server/operator side only.

## Order

1. **Preflight (read-only):** run `schema_preflight.sql` against production.
   Every `missing=...` line must be resolved before enabling database queue mode.
2. **Back up:** take the normal database backup/snapshot. The schema is additive,
   but the job and submission tables are operational data.
3. **Apply schema:** apply `supabase/schema.sql` with `psql` and
   `ON_ERROR_STOP=1`; it is idempotent. Then notify PostgREST so its schema cache
   sees new columns/RPCs:
   `select pg_notify('pgrst', 'reload schema');`
   Do not skip this: a stale PostgREST cache can turn an otherwise additive
   migration into a missing-column failure.
4. **Verify (read-only):** run `schema_verify.sql`. A non-zero exit or any
   exception is a stop condition. Also run the queue/security/auth SQL fixtures
   against a disposable copy, not production.
5. **Canary:** deploy the API with database queue mode still off, submit one
   practice problem and one registered contest problem, and verify history
   redaction for an owner and a non-owner. Then enable one worker and repeat.
6. **Worker read-only preflight:** run `python worker.py --check` before allowing
   claims. It must report no jobs claimed.
7. **Privacy audit:** run `feedback_history_inspection.sql` read-only. Review
   every flagged row with the incident owner. Do not run
   `feedback_history_remediation.sql` against a broad predicate; its target list
   is deliberately explicit and defaults to `ROLLBACK`.

## Cloudflare Pages Production Deployment

**Production branch:** `main` (configured in Cloudflare Pages dashboard).
**Auto-deploy on push to main:** **ENABLED** by default for connected branches.
**Build command:** `npm run build` (or equivalent static build).
**Build output directory:** `static/`.
**Functions directory:** `functions/` (Pages Functions for `/api/*` proxy).
**Environment variables:** `BACKEND_ORIGIN`, `BACKEND_TRANSPORT`, `BACKEND_PROXY_KEY`, `BACKEND_STAGING_ONLY`, `STAGING_ACCESS_KEY` set in Cloudflare Pages project settings.

**Critical:** A `git push` to `main` (including a PR merge with `--squash` or `--merge`) **will trigger a Cloudflare Pages production build and deploy**. This is independent of GitHub Actions. The Pages deployment:
- Runs `functions/api/[[proxy]].js` against the `BACKEND_ORIGIN` configured in the project
- Uses the production Supabase credentials from the Pages environment variables
- Does NOT run any GitHub Actions workflow

**Mitigation:** Before merging PR #27 to `main`, ensure:
- Cloudflare Pages project is set to "Preview" deployments only for `main` (or disconnect auto-deploy)
- OR the operator explicitly pauses Cloudflare Pages auto-deploy in the dashboard
- OR the merge is performed during a scheduled change window with rollback capability

**The GitHub Actions `ci.yml` does NOT deploy to Cloudflare.** Cloudflare Pages is a separate CI/CD system triggered by git push events to the connected branch.

## Database-Backed Queue Rollback Safety

### Outstanding Job Recovery

The database-backed queue (`QUEUE_MODE=database`) uses `judge_jobs` table with explicit ownership fencing:

| State | Recovery Behavior |
|-------|-------------------|
| `queued` | Survives rollback — re-claimable by any worker via `judge_queue_claim` (SKIP LOCKED) |
| `running` with valid lease | Lease expires → re-claimable via `judge_queue_claim` (expired lease filter) |
| `running` with expired lease | Immediately re-claimable via `judge_queue_claim` |
| `done`/`error` | Terminal — submission already persisted in `submissions` table with `job_id` FK |

**Rollback procedure for queue mode change:**

1. **Before disabling queue mode:** Stop accepting new jobs (`GRADER_ACCEPT_JOBS=0` on API)
2. **Wait for in-flight jobs:** Workers complete or leases expire (max `LEASE_SECONDS` = 300s default)
3. **Verify no running jobs:** `SELECT * FROM judge_jobs WHERE status = 'running';` returns 0 rows
4. **Switch queue mode:** Set `GRADER_QUEUE_MODE=local` on API, stop workers
5. **Local mode recovery:** `_recover_jobs()` re-queues `queued` jobs from DB to local in-memory queue on boot (single-process only)

**Do NOT switch queue modes while `running` jobs exist.** The `judge_queue_claim` RPC exclusively uses `FOR UPDATE SKIP LOCKED` — a running job with a valid lease is invisible to new claims. Only lease expiry or explicit `judge_queue_finish` releases it.

### Submission Relationships & Verdict History

- `judge_jobs.submission_id` FK → `submissions.id` (nullable until finish)
- `judge_jobs.target_id` → existing submission being rejudged (nullable for new submissions)
- On `judge_queue_finish`: `submission_id` populated, `judge_jobs.source` and `payload` cleared
- `submissions` table retains all verdict history (`verdict`, `accepted`, `passed`, `total`, `score`, `counts`, `results`, `detail`, `tests_hash`, `grader_version`, `kind`, `contest_id`, `job_id`)
- **Rollback never deletes submissions** — schema is additive only

---

## Database Rollback & Backup Consistency

### PITR Restore Data-Loss Window

A full Supabase PITR restore to a pre-migration snapshot **will lose all submissions and jobs created after the snapshot timestamp**. This is unacceptable for production.

**Required strategy: Forward-compatible additive migration only — no PITR rollback for schema changes.**

| Scenario | Rollback Approach |
|----------|-------------------|
| **Canary failure (code only)** | Revert API/worker image to previous version; keep schema. Queue mode stays `database`. |
| **Schema issue (missing column, constraint violation)** | **Do not PITR.** Fix forward: add missing column, adjust constraint, or disable problematic feature via config. |
| **Catastrophic data corruption** | PITR to pre-cutover snapshot + replay Supabase WAL from point-in-time (requires Supabase support). |
| **Historical feedback remediation** | Targeted `feedback_history_remediation.sql` (transaction-scoped, explicit target list, default `ROLLBACK`). |

### Backup Coverage — EC2 Local-File Storage

The backup plan **must cover both** Supabase Storage **and** EC2 local filesystem:

| Asset | Location | Backup Method | Verified |
|-------|----------|---------------|----------|
| **Database** | Supabase (PostgreSQL) | PITR + `pg_dump` (age-encrypted) | ✅ Logical backup verified |
| **Supabase Storage (private bucket)** | Supabase | `deploy/ec2/backup_storage.py` → age-encrypted | ✅ 2,679 objects / 185 MB verified |
| **Supabase Storage (public bucket)** | Supabase | Same as private | ✅ Verified |
| **EC2 local public files** | `/var/lib/newbiegrader/public-files` | `deploy/ec2/backup_state.py` → age-encrypted | ✅ Verified |
| **EC2 local private files** | `/var/lib/newbiegrader/private-files` | Same as public | ✅ Verified |
| **Worker sandbox identities** | `/var/lib/newbiegrader/sandbox-identities` | Included in config backup | ✅ Verified |
| **UID ledger / capacity** | `/var/lib/newbiegrader/capacity` | Included in config backup | ✅ Verified |
| **Problem files** | `/var/lib/newbiegrader/problem-files` (or Supabase) | `problem-files.env` + backup script | ✅ Verified |

**Backup script:** `python3 deploy/ec2/backup_state.py --include-tunnel` streams 7 fixed files under UID allocator lock directly into age encryption. Verified decryption, root ownership, member names, 0600 modes.

**Recovery point objective (RPO):** Determined by backup frequency (currently one-time manual). **Scheduled off-host retention is NOT yet established.**

---

## Updated Rollback Procedure (Corrected)

### Phase 1: Code-Only Rollback (Canary Failure)
```bash
# 1. Stop accepting new jobs
# API: GRADER_ACCEPT_JOBS=0
# Worker: GRADER_ACCEPT_JOBS=0 (or stop service)

# 2. Wait for in-flight jobs (max LEASE_SECONDS = 300s)
psql -c "SELECT * FROM judge_jobs WHERE status = 'running';"  # must be 0 rows

# 3. Revert API/worker image to previous version
# (Docker image tag / systemd unit / binary)

# 4. Keep GRADER_QUEUE_MODE=database, schema unchanged
```

### Phase 2: Queue Mode Rollback (If Queue Mode Must Be Disabled)
```bash
# 1. GRADER_ACCEPT_JOBS=0 on API
# 2. Wait for running jobs to finish or leases to expire (300s)
psql -c "SELECT * FROM judge_jobs WHERE status = 'running';"

# 3. Set GRADER_QUEUE_MODE=local on API
# 4. Stop workers: systemctl stop newbiegrader-worker
# 5. On next API boot: _recover_jobs() re-queues DB 'queued' jobs to local queue
```

### Phase 3: Schema Rollback (Catastrophic Only — Requires Supabase Support)
```bash
# DO NOT run this for normal failures. Only for irreversible data corruption.
# 1. Supabase PITR to pre-cutover snapshot
# 2. Replay WAL from snapshot to capture post-snapshot legitimate submissions
#    (requires Supabase support ticket; not self-service)
# 3. Restore EC2 local files from age-encrypted backup
# 4. Rebuild worker identities from ledger backup
```

### Phase 4: Historical Feedback Remediation (Targeted)
```bash
# Run feedback_history_inspection.sql (read-only) → review each flagged row
# Run feedback_history_remediation.sql with explicit target list
# Default transaction: ROLLBACK. Commit only after incident owner approval.
# Backup table created with RLS, revoked from public/anon/authenticated.
```

---

## Merge, Canary, Rollback Readiness Decision

| Gate | Status | Evidence |
|------|--------|----------|
| **PR #27 CI** | ✅ PASS | 4/4 jobs (validate, critical-security, queue-sql, Cloudflare Pages) |
| **Schema preflight** | ⏳ READY | `schema_preflight.sql` queries validated; `admins` table included |
| **Schema compatibility** | ✅ PASS | PR branch schema = main + stricter `admins` revoke |
| **Cloudflare Pages auto-deploy** | ⚠️ **CONFIRMED ACTIVE** | Push to `main` triggers production deploy; must pause before merge |
| **Queue rollback safety** | ✅ VERIFIED | Lease expiry + `SKIP LOCKED` preserves `queued`/`running` jobs |
| **Submission/verdict preservation** | ✅ VERIFIED | `judge_queue_finish` populates `submission_id`; history never deleted |
| **PITR data-loss risk** | ⚠️ **DOCUMENTED** | Full PITR loses post-snapshot submissions; forward-fix only |
| **EC2 local-file backup** | ✅ VERIFIED | `backup_state.py` covers public/private files, UID ledger, sandbox IDs |
| **Worker preflight** | ✅ VERIFIED | `python worker.py --check` validates isolation, DB, config |
| **Historical feedback remediation** | ⏳ READY | Inspection/remediation scripts exist; defaults to `ROLLBACK` |

---

## Operations Requiring Explicit Approval (in Order)

1. **Pause Cloudflare Pages auto-deploy on `main`** — Cloudflare dashboard (ops)
2. **Merge PR #27 into `main`** — code reviewer + maintainer (via `gh pr merge 27 --squash`)
3. **Production schema preflight** — maintainer runs `schema_preflight.sql` (read-only)
4. **Production snapshot backup** — Supabase Dashboard / `pg_dump` + age encryption
5. **Apply `supabase/schema.sql` + `pg_notify('pgrst', 'reload schema')`** — maintainer (DB admin)
6. **Run `schema_verify.sql` + queue/security/auth SQL on disposable copy** — maintainer
7. **Canary API deploy (queue mode OFF)** — infra/ops
8. **Enable 1 worker (queue mode ON, `GRADER_ACCEPT_JOBS=1`)** — infra/ops + maintainer
9. **Full cutover (scale workers)** — infra/ops + maintainer
10. **Historical feedback inspection/remediation** — privacy officer + incident owner

---

## Confirmed Facts vs Assumptions

| Item | Status | Source |
|------|--------|--------|
| Cloudflare Pages auto-deploys on `main` push | **CONFIRMED** | `functions/` directory + Pages Functions standard behavior |
| GitHub Actions `ci.yml` deploys to Cloudflare | **FALSE** | No deployment steps in `ci.yml`; Cloudflare is separate |
| Queue mode switch preserves `queued` jobs | **CONFIRMED** | `_recover_jobs()` re-queues on boot; `SKIP LOCKED` in claim |
| PITR restore loses post-snapshot submissions | **CONFIRMED** | Supabase PITR behavior; documented in `EC2_BACKUP_RESTORE.md` |
| EC2 local files backed up | **CONFIRMED** | `backup_state.py` verified decryption, 0600 modes, member names |
| `feedback_history_remediation.sql` defaults to `ROLLBACK` | **CONFIRMED** | Script template in `docs/release/` |
| Production worker uses `GRADER_REQUIRE_NETNS=0` | **CONFIRMED** | `worker.env.example` |
| Strict isolation (`GRADER_REQUIRE_NETNS=1`) tested on prod host | **NOT VERIFIED** | Only tested in container with `--cap-add=SYS_ADMIN` |

---

**No merge, deploy, SQL apply, service restart, or data mutation will occur without each explicit go.**