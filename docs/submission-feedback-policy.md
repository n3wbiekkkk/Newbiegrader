# Submission feedback policy

The maintainer explicitly approved this policy on 2026-10-18:
**show input / expected / actual for every failed practice case; keep contest
hidden tests closed.** This supersedes earlier sample-only practice instructions.
PDF samples and the direct `/sample/{name}` endpoint are unchanged.

| Context | Owner-visible feedback |
| --- | --- |
| Practice, problem outside upcoming/running contests | Failed WA/RE/TLE/MLE/OLE cases: input, expected, actual and diagnostic |
| Accepted private practice case | Verdict/measurements only |
| Contest submission | Existing samples-only policy; live show_samples=false hides samples too |
| Practice with contest parameter omitted, but problem belongs to upcoming/running contest | No extra failed-case disclosure; same samples/none restriction |
| Prior practice job/history while a new contest protects the problem | Re-evaluate current policy and withhold private I/O |
| Policy lookup outage or malformed/naive/reversed contest times | Fail closed: no test I/O |

## Implementation contract

- `REVEAL_PRACTICE = "practice-failures"` is selected by the server, never by a
  client-supplied reveal flag. Existing `judge_jobs.reveal` is text and accepts it;
  no production schema change is necessary.
- The engine requires explicit `reveal_failed=True` to opt into private-case
  diagnostics; ordinary CLI/contest calls keep the private diagnostic guard.
- `practice_feedback:true` is generated only for engine-produced failed practice
  results. It survives JSON persistence as policy provenance; historical rows
  without the marker are not retroactively reconstructed from today's fixtures.
- Practice disclosure checks bypass the 20-second contest visibility cache, so
  a contest created on another replica is checked with a fresh database read.
  This is a policy snapshot, not a promise to retract an already returned response.
- `_redact_results` and persistence both enforce the selected policy. A job with
  contest_id cannot persist practice disclosure even if its reveal field is
  incorrectly set. History and job polling re-check current contest policy.
- Owners and admins retain detail access. Eligible peers have the narrower
  source/results access described below. Public history lists contain no source
  or case data. The Supabase relations remain server-only; do not grant clients
  direct access merely because feedback is intentionally disclosed.
- Each I/O preview is limited to 2,000 characters, diagnostics/diff to the existing
  bound. Actual output after a limit/crash means bytes captured before stopping;
  it may be empty and is not proof the program completed.
- All feedback text is HTML-escaped. Copy controls and keyboard expansion work
  for the newly displayed cases as well as existing samples.

## Security consequences and limits

A participant can deliberately fail every practice case and retain the entire
suite. This is an intentional product decision, not a security guarantee that
practice fixtures stay confidential. Never reuse an already disclosed practice
suite as a secret contest suite. Changing visibility cannot erase downloads,
screenshots, a user's source or earlier cached responses. Current-policy reads
reduce new disclosure; they cannot retract prior disclosure.

S03 isolation, S04 aggregate resource limits, S05 identity trust and durable queue
rollout remain independent production gates. Revealing practice diagnostics does
not authorize filesystem reads or network access. Peer source access follows the
separate policy below; peer access never includes private test diagnostics.

## Peer submission inspection

The per-problem Submissions tab permits a logged-in student to inspect peers'
completed submissions for that same problem after one qualifying completed
judged attempt. AC, WA, TLE, MLE and OLE qualify; CE and RE do not. A mixed run
containing any CE or RE does not qualify. Queued/running/error jobs, playground
runs and attempts on another problem or account do not count. Another qualifying
attempt unlocks access even if later attempts fail with CE/RE. Recognized legacy
explicit verdicts can count when detailed evidence is absent; unknown or
malformed evidence fails closed. Stored `REJECTED` is an aggregate failure,
not proof that an attempt avoided CE/RE: inspect its verdict counts and tests.

The exclusions apply to the viewing student's qualifying attempt. An eligible
student can inspect a completed peer CE/RE submission as well as accepted or
unsuccessful submissions. Owners keep their existing practice-feedback access;
admins keep their existing inspection access.

Any upcoming or running contest containing the problem blocks peer inspection,
including old practice submissions and submissions from other ended contests.
The server reads all contest policy afresh for each authorization decision and
validates timezone-aware, ordered start/end dates. Missing policy storage,
outages and malformed dates fail closed. Unpublished problems remain private;
hidden problems are accessible to peers only through a started/ended contest
that makes the problem visible. A current contest still blocks peer inspection.
Contest pagination orders equal start times by ID, advances by the actual row
count and requires an empty page, including under smaller database response
caps. Malformed pages, later-page outages, or the 10,000-row/1,000-request safety
budget fail closed rather than authorizing access from partial contest policy.

Peer detail uses explicit field allowlists: source, author display name,
language/filename, verdict/score/counts and per-test verdict/time/memory. It never
returns test names, input, expected/actual output, diff, compiler/runtime
diagnostics, login email, or arbitrary persisted fields. Public submission lists
have a separate allowlist and never contain source or per-test results. Legacy
display names that fall back to an email address are replaced with a neutral
label. Source is student-authored text and may itself contain whatever the
author wrote. Source inspection does not copy code into the student's editor.
The dedicated `#/submission/<id>` page keeps source and per-test results separate
from the Submit/Run workspace and the viewer's latest judging result. It names
the author and submission, displays source immediately with numbered lines, and
offers copy and line wrapping. Background judging cannot replace that page.
Direct links, reloads and history navigation authorize the requested ID again;
leaving the route rejects delayed responses. Owners retain their already
authorized detailed feedback on this page; peers see only allowed measurements.

History responses are private and not stored by HTTP caches. The frontend
invalidates identity-specific cached answers and rendered inspected source on
identity changes, and rejects late or superseded detail responses. The API
always authorizes again when a submission is opened; the list's access message
is guidance, not an access token. A returned source can be retained by a student;
later policy changes cannot retract it.

### Database boundary

Eligibility uses persisted `submissions`, not process memory or the newest
50/100-row feed. The server filters by `user_email` and `problem`, orders by
`created_at`, and reads bounded pages until it finds a qualifying historical
attempt or exhausts that account/problem history. The existing
`submissions_history_filter (user_email, problem, created_at desc)` index supports
this lookup. Each page selects only the verdict evidence needed for the check;
it does not download source or private diagnostics. A plausible candidate's
persisted case results are then checked on the server to reject contradictory
CE/RE evidence; these private fields are never returned to peers. Pagination
advances by the rows actually returned, including when PostgREST's configured
response cap is smaller than the requested page, until an empty page. Eligibility
has no 50/100-row feed cutoff. A safety bound of 50,000 examined rows or 1,000
page requests returns 503 unavailable rather than declaring the student
ineligible or authorizing disclosure. Very large account/problem histories may
need more than one database request; no eligibility cache can bypass fresh
contest policy.

No schema migration, new table/RPC, client grant, or RLS change is required.
`submissions` remains service-role-only, and all access goes through the API.
Do not apply live database changes for this feature. Synthetic regressions are
in `tests/test_critical_peer_inspection.py` and `tests/test_peer_inspection.js`.

## Verification and release

Synthetic critical regressions are in `tests/test_critical_practice_feedback.py`:
local/database completion, actual RE stdout/stderr, WA I/O, accepted-case
redaction, contest parameter omission, upcoming/live contests, malformed policy,
current-policy history/job reads, ownership and contest persistence guard.
Existing F3 sample/none redaction regressions remain unchanged and mandatory.

Run on a disposable Linux/root environment with network disabled:
`python tools/run_critical_tests.py`, then the full suite and Node checks.
A branch push does not deploy the backend. Deploy only after the host isolation
and resource prerequisites in `docs/audits/JOB_ISOLATION.md` are verified.
