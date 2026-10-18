# Practice feedback / problem-data release — 2026-10-18

Subsequent backend deployment and actual-host verification are recorded in
[PRODUCTION_RELEASE_2026-10-18.md](PRODUCTION_RELEASE_2026-10-18.md).
The undeployed statements below describe the earlier checkpoint.

This records subsequent explicit maintainer approvals and supersedes the
sample-only practice checkpoint in SUBMISSION_FEEDBACK.md. It does not authorize
or claim a backend deployment. Latest working branch: `fix/practice-failure-feedback`.

## Approvals and final behavior

The maintainer approved:

1. 204 new judge cases and two KAI-GAI expected-output corrections in Supabase.
   They subsequently confirmed there are no current users. No hard production
   admission lock was available or claimed; the release used copy-on-write assets
   and atomic version-checked manifest changes instead of overwriting live files.
2. Input/expected/actual for **every failed practice case**, including formerly
   private cases, with contest data remaining closed to participants.

Code references:

- `grader.py:1066` opts into private diagnostics only with explicit
  `reveal_failed=True`; default engine/contest behavior stays restrictive.
- `server.py:1398` chooses practice policy only when the problem belongs to no
  upcoming/running contest. Omitted contest parameter is not a bypass. Eligibility
  bypasses cached contest rows; errors/invalid times withhold I/O.
- `server.py:2444` attaches bounded I/O and server-generated practice provenance
  only to failed cases; accepted private cases remain redacted.
- `server.py:625`, `:1279`, `:1289` enforce output/storage policy; contest_id
  prevents practice storage even if an internal reveal field is wrong.
- `server.py:2925`, `:3074` recheck current policy when an owner reads a finished
  job or history. Ownership/authentication checks remain. Legacy records without
  stored I/O are not reconstructed with a potentially different current suite.
- `static/app.js:2139` renders escaped case data/reason, with an accurate practice
  label. Asset version v43; engine 2.0.4. CSS v24 retains the prior alignment fix.

See [submission-feedback-policy.md](../submission-feedback-policy.md) for the
full policy, consequences and tooling contract. An owner can deliberately fail
all practice cases and retain them. Reusing previously disclosed practice data
as secret contest data cannot be made safe by a later visibility change.

## Production problem-data changes — VERIFIED

**204 additions / 68 problems; 974 → 1,178 active cases.** Independent local
oracles and trusted references were compared before publishing; all 68 complete
packages passed. Public samples, PDFs, titles, numbers, checker, limits,
publication flags and existing submission rows were not modified.

Publication used a private, rehearsed scoped publisher:

- Read-only preflight matched all 68 original suite hashes and backed up all
  problem rows. The two affected original Storage output objects were backed up.
- Offline FakeSupabase rehearsal verified 68 version-checked row switches,
  idempotent reruns, 412 distinct object paths and unchanged unrelated columns.
- Zero queued/running durable job rows observed before and during publication.
  Local queue fallback is an existing uncertainty; zero rows is not a drain lock.
- Uploaded **412 create-only objects**, reading every one back byte-for-byte
  before exposing its name. No previously referenced object was overwritten.
- For KAI-GAI, two corrected fixtures received fresh numeric storage test names;
  their retired objects remain intact. This preserves the old suite for a worker
  that has already read an old manifest. Compute the new hash using the published
  names rather than pretending filenames do not participate in the suite hash.
- Each problem row switched only `hidden_tests`, `tests_hash`, `tests_count`,
  `updated_at`, guarded by both prior hash and updated_at. A concurrent metadata
  change would abort that switch; orphan new assets do not alter the old suite.
- Verified all 68 final rows, total 1,178, unchanged other metadata and successful
  KAI-GAI loading/hash validation through the existing Supabase loader.
- Public backend GET `/api/version`: **68 problems, 1,178 cases, 0 hash mismatches**
  against the release manifest. `/api/health` 200; public sample 01 returned 200;
  a new private case's direct `/sample/` path returned 404.
- HTTP vantage: audit Mac's current network; public IP/network category unknown.
  No real production submission was executed. Engine still **2.0.0**: test-data
  publication is independent of a backend code release.

Private evidence/backups:
`~/.local/share/newbiegrader-validation/submission-feedback-kc67osyx/`:
`publication.log`, `publication-public-api.json`,
`remote-problems-before.json`, `remote-problems-publication-backup.json`,
`published-test-versions.json`, `publish_testcases.py`, `rollback_testcases.py`,
original problem/reference
backup, generation/oracle and verification logs. Backup rows/outputs are mode
0600. Fixtures, solutions, credentials and the publisher are not in public Git.

The private publication mapping in `publish_testcases.py` is part of the release
artifact. Local authoring fixtures retain canonical contiguous names; two
published runtime names differ intentionally. Before any future full import,
reconcile that mapping with Supabase, the authoritative deployed source. Do not
blindly run the legacy importer: it upserts unrelated metadata and switches the
row before uploading assets. General immutable package publication remains an
operations/tooling improvement; this release did not change the loader or schema.

## Verification of code

Disposable Linux arm64/root, Python 3.11, kernel 6.8 / Landlock ABI 4, network
none, default container capabilities. No real user programs were run.

- Full suite: **272 passed, zero skips** (115.413 s).
- Critical: **132 passed, zero skips** (29.232 s), including nine new practice
  policy tests and the added anonymous/unmarked-provenance assertions, recorded
  in `practice-critical-release.log`.
- Node **34 passed**, zero skips; syntax/DOM/style checks passed.
- Full offline problem validator: **68/68 passed**, 1,178 cases.
- Real local browser with mocked API responses: failed practice I/O visible,
  contest canary absent; existing copy/keyboard/mobile alignment checks passed.
  External font fetching was deliberately blocked in this test browser, so the
  screenshot uses fallback fonts; this is not a production font outage finding.
- New tests: `tests/test_critical_practice_feedback.py:80`, `:97`, `:105`, `:113`,
  `:122`, `:130`, `:137`, `:151`, `:158`. Existing sample/none F3 regressions stay
  mandatory. The old practice API assertion now checks all failed I/O explicitly;
  contest API secrecy assertions were retained.

## Remaining gates and rollback

- Branch pushes are authorized and do not merge main or deploy the backend.
  Public practice failure I/O is **not live** until the backend is reviewed and
  released. The current production engine is still 2.0.0.
- S03 UID mapping / Landlock / persistent allocator state, S04 hard aggregate
  memory/pids/CPU/workspace limits, S05 identity ownership and B08 durable queue
  remain unresolved production gates. S04 scheduling arithmetic was fixed in
  `2302a0e`, not hard process-tree enforcement.
- Changing practice policy cannot revoke already disclosed data. Identity
  pre-hijacking can still compromise ownership; no claim of complete security.
- New cases increase judge work; the 204 small additions are not proof of stress
  coverage. Six check legal whitespace for domains already fully enumerated.
- Data rollback: restore only the four manifest/version fields from the private
  prepublication backup, conditional on the release hash still matching. Keep
  all objects, including retired old ones. This restores two known incorrect
  old KAI-GAI expectations, so use only for a reviewed incident rollback; do not
  automatically rejudge historical submissions or delete rows.
- Prepared rollback verification: `python3 PRIVATE_EVIDENCE/rollback_testcases.py`
  ran read-only, matched all 68 release versions and performed zero writes.
  `--apply` would mutate production and requires a reviewed incident decision.
- Code rollback: revert the practice-policy commit on its branch and rerun gates;
  no production code rollback was performed. Preserve the UID ledger through
  any future deployment/rollback. Never add privileged/CAP_SYS_ADMIN as a shortcut.
