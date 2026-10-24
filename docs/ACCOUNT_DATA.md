# Account data and public-readiness rollout

Status on 2026-10-24: the maintainer applied the lifecycle SQL and the compatible
backend `c3ba9ad` is active, with queue 50 and daily account retention. See
[the activation record](releases/account-lifecycle-2026-10-24.json). Public rollout
qualification remains incomplete: unused-email signup was deferred by the
operator, bulk delivery is unqualified, and off-host backup retention and erasure
reconciliation still require completion.
The Thai [privacy page](../static/privacy.html), [terms](../static/terms.html)
and [FAQ](../static/faq.html) explicitly identify the features awaiting activation.

## Approved policy

- Registration has no minimum age. Where guardian authorization is legally
  required, the minor/guardian must contact the operator. There is no automated
  age or guardian-authority verification; a generic checkbox is not evidence.
- Account records remain until deletion. Source, submission history, completed
  job payloads and problem reports expire after one year, with daily cleanup.
  A still-active job/lease is preserved until it finishes.
- Deletion audit contains only a random event ID, time and per-table counts;
  it expires after 90 days. A salted email hash blocks identity recreation for
  90 days. Pending deletion work retains its email/provider subject until recovery
  completes, including when a provider outage lasts beyond that period.
- Encrypted backups expire after 30 days, with scheduled cleanup. The current
  private identity and append-only UID ledger are operational state, not expired
  backup archives. Never remove them with a backup cleanup command.
- Peer source visibility remains as specified in
  [submission feedback](submission-feedback-policy.md). Stored failed-practice
  feedback can contain bounded private I/O; accepted private cases and contest
  feedback keep their existing disclosure boundaries. Exports omit all per-case
  results and compiler/runtime detail, even when an owner could view them online.

## API contracts

`GET /api/profile/export` requires a current revocable browser session. It exports
only rows owned by that identity, with explicit field allowlists. Included data:
account email/name/creation time, profile preferences, source and summary results,
job status metadata, contest registrations and submitted reports. Provider IDs,
password/session hashes, per-case results, diagnostics and other users' rows are
excluded. It downloads JSON with `private, no-store`; database failure returns
503 rather than partial data. Exports exceeding 10,000 rows in a table or 20 MiB
return 413 and direct the owner to the operator.

`DELETE /api/profile` requires the same session, normal origin/CSRF checks,
database queue mode, and JSON `{"confirmation":"<current account email>"}`.
An effective admin must first have another administrator remove their privileges;
a bootstrap admin also requires an operator configuration change.

Deletion follows these steps:

1. Under the admission and identity locks, refuse queued/running jobs or live
   leases with 409. Otherwise block identity recreation, record recoverable work,
   clear credentials and revoke every browser/remember family atomically.
2. Delete the mapped Supabase Auth user through the server-only Admin API. Legacy
   accounts without a mapping are resolved by exact email on the server, with a
   bounded provider lookup. A missing provider user is idempotent success.
3. Atomically remove owned submissions (including source/results), profiles,
   users, sessions, jobs, quota events, registrations and reports. Anonymize
   organizer `created_by` references; retain the contests/announcements themselves.
   Store a counts-only audit. Statistics derived from submissions consequently
   decrease. Concurrent completion requests do not duplicate audit events.

Provider or finish failure returns 503 and leaves the account revoked and pending;
it does not claim erasure. The daily `account_retention.py` recovery retries the
provider deletion before finishing application deletion. Supabase and PostgreSQL
are separate systems, so this is recoverable sequencing, not a distributed atomic
transaction. No production user is deleted by the test suite.

`GET /api/admin/account-audit` is admin-only and returns the latest 100 deletion
events with a nested numeric field allowlist. It never returns an email or source.

Guests receive only status/count from `/api/health`; authenticated observers retain
the visibility-filtered slug list. `/api/problems` continues to require login.
`/api/version` remains a public release diagnostic and includes test-set hashes.

## Queue behavior

The active host and env examples set `GRADER_QUEUE_MAX=50`, meaning
50 waiting jobs in addition to the four executing workers. This changes backlog
capacity, not CPU/RAM budgets or a measured number of concurrent learners. The
live API and all four worker configurations were read back at 50 during activation; CPU/RAM budgets and the signing key were preserved.

Only a 503 carrying `X-Newbiegrader-Admission: rejected-queue-full` permits the
frontend to resend. It honors `Retry-After`, increases the delay, adds jitter and
stops after five retries. Changing account/problem cancels the pending send.
Unclassified 503s, network errors and ambiguous responses never replay a POST.

## Activation gate

1. Review `supabase/account_lifecycle.sql` and the candidate diff. The maintainer
   applies this append-only, idempotent patch through the Supabase SQL Editor.
   It creates backend-only tables/RPCs and replaces identity/admission functions
   with deletion guards. Applying SQL alone neither schedules retention nor
   activates the HTTP endpoints.
2. Follow the [host rollout](HOST_DEPLOYMENT.md): fresh encrypted backup, pause
   admission, drain actual jobs/live leases, qualify the immutable candidate,
   and switch compatible backend before pushing its frontend to Pages. Preserve
   signing key, protected problem files and the latest UID ledger.
3. Install `newbiegrader-account-retention.service` and `.timer` in the systemd
   unit directory. First run `account_retention.py` without `--execute` and review
   the counts. Review expired-row counts before enabling real cleanup, then run
   the service, enable the daily timer and inspect its exit status/journal.
   A failed maintenance unit is an operational failure requiring investigation;
   the existing worker watchdog does not automatically certify this new timer.
4. Update the scheduled backup script and verify age pruning on the private
   bucket. Inventory every off-host destination. Review
   `prune_operator_backups.py --directory <private-backup-directory>` before its
   `--execute` run; schedule/repeat it daily on every destination. Unknown archive
   names are intentionally excluded and require separate operator review.
   Do not advertise enforced 30-day deletion while any destination is unmanaged.
5. Check `/api/version` fingerprint against the candidate and run native worker
   preflights and real Python/C/C++ HTTPS submissions with linked history.
   Rehearse deletion on a disposable account only, including a second device;
   confirm Auth deletion and the admin audit. Do not use the real email canary
   account for destructive tests.
6. Complete fresh unused-email signup, Google sign-in, recovery, two-device
   logout and real Turnstile paths. Review sender/provider quotas and actual
   delivery/bounces before a 50-message test. The operator explicitly retained
   the existing Gmail sender; one delivered OTP does not qualify 50-message
   deliverability or establish a verified custom domain.
7. Replace the public pages' preparation notice only after these gates pass.
   Record the exact commit, fingerprint, times, failures and skips in a new release
   record. The earlier 2.0.8 record qualifies its own fingerprint only.

## Rollback and restoration

Keep the additive tables, deletion guards and maintenance job during application
rollback. Never roll back to an identity/queue implementation that ignores pending
or completed deletion blocks. If no compatible rollback is available, keep
admission/authentication closed while correcting the candidate.

Before restoring an older application-data backup, preserve the latest deletion
blocks, privacy salt and pending work independently. Reconcile restored accounts
and owned rows against that deletion state before reopening, so a restore cannot
resurrect erased accounts. Do not overwrite the current salt with an unrelated
freshly generated one. If up-to-date deletion state cannot be recovered, stop the
restore gate and have the operator resolve missing deletion requests. Existing
backup rehearsals do not prove this new erasure-reconciliation path.
Restore no old browser sessions and follow the
[session recovery guide](SESSION_REVOCATION.md#backup-and-restore).

Help: [maintainer](https://github.com/n3wbiekkkk) or
[newbiegrader.team@gmail.com](mailto:newbiegrader.team@gmail.com). Never send
passwords, OTPs or private submissions in a public issue.
