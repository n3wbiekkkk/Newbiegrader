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

## Rollback

- The schema changes are additive; keep the old application image and disable
  database queue mode first if the canary fails.
- Do not drop columns, tables, functions, or policies during rollback. Restore
  the pre-change database snapshot only under the approved backup/restore
  procedure.
- If a worker is stuck, stop claiming new jobs, let leases expire, and inspect
  `judge_jobs` before restarting. Never delete a `running` row without first
  recording its lease and source state.
- Revert code by deploying the previous immutable image; no shared-history
  rewrite, force-push, or destructive Supabase operation is part of rollback.

## Historical feedback

The read paths now re-evaluate live contest policy and redact before storing and
returning feedback. Historical rows created by older code are not purged
automatically. `feedback_history_inspection.sql` identifies candidates;
`feedback_history_remediation.sql` is a target-specific, transaction-scoped
template with a durable backup table and a default `ROLLBACK`. It preserves
public sample fields and test/verdict/timing metadata while removing hidden
inputs, expected/actual output, diffs, and diagnostics.

Never treat the synthetic fixture output in this repository as production
evidence. The production row set, policy decision, and execution authorization
remain maintainer-owned.
