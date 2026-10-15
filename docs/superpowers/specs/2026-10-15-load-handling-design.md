# Load handling revisions

The approved goal is to improve Newbiegrader's ability to handle submission bursts, review the changes before committing, and then recommend server capacity. Preserve FastAPI, the vanilla frontend, Supabase, the standard-library judge, existing API contracts, visibility checks, sandbox limits, and hidden-test redaction. Do not upgrade paid infrastructure or deploy unreviewed changes.

## Execution

Execute submissions and playground runs in supervised subprocesses, reusing the existing judge functions. A timeout or cancellation must terminate and reap the job and its descendants before releasing execution capacity. Bound stdout and stderr while reading. Avoid Python preexec callbacks from threaded processes without removing sandbox restrictions.

Use one host-wide CPU/memory budget for compilation and tests across submissions, playground runs, and rejudges. Start with serial tests per submission and conservatively cap active jobs from CPU and RAM, reserving memory for the API, worker supervisors, and compilers. Explicit environment overrides must still respect physical safety limits.

## Queue and roles

Keep local mode backward compatible. Add an explicit database queue mode using PostgreSQL RPCs: atomic admission and claiming, service-role-only privileges, leases and heartbeats, recovery of expired ownership only, priority for student submissions, and fenced/idempotent completion. Database mode must fail closed when its migration or database is unavailable rather than silently accepting memory-only work. Allow combined, API-only, and worker-only roles; require a stable SESSION_SECRET and database mode for separated roles. The API-only role must never launch judge work, including playground runs.

Queue and per-user admission must be atomic, including local mode. Rejudge batches use remaining capacity. Shared status comes from the database, not stale process caches. Preserve 202 submission responses, ownership checks, terminal errors, history behavior, and playground's direct result response. Persist feedback with the existing sample redaction policy.

## API, frontend, and measurement

Offload blocking database calls from async request handlers. Replace fixed polling with bounded adaptive delays and jitter, preserving resume and terminal handling. Add an opt-in load harness that targets local/test installations by default, reports API latency, queue wait, throughput and failures, and does not write production data implicitly.

Document migration and role rollout, limits, and server-sizing recommendations. Run all repository checks, meaningful concurrency/timeout/output/lease regressions, and an independent review before the final commit. Linux-specific execution behavior needs Linux evidence or an explicit limitation in the handoff.
