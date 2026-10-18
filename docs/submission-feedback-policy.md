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
- Detail reads retain owner/admin authorization. Public history lists contain no
  case data. The Supabase relations remain server-only; do not grant clients
  direct access merely because a practice failure is intentionally disclosed.
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
not authorize filesystem reads, network access or other users' source/history.

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
