# Submission feedback and test-suite follow-up — 2026-10-18

Branch: `fix/submission-feedback-and-testcases`, based on `eddbc6d`.
Later status: the owner approved practice disclosure and test publication.
See [PRACTICE_RELEASE.md](PRACTICE_RELEASE.md) for the completed Supabase
publication and updated policy; the checkpoint below predates those approvals.

Changes at this checkpoint are local pending release; pushing this branch does not deploy the
backend or publish ignored problem packages. No real user submissions were run.

## Submission feedback

- `grader.judge_test` retains up to 2,000 characters of partial stdout for public
  diagnostics on RE/TLE/MLE/OLE. Hidden cases and REVEAL_NONE retain no such output.
- `server.run_submission` adds public input/expected/actual on all failed
  verdicts, retaining the engine reason. Serial and parallel paths follow the
  same policy. API/history/job result/persistence redaction stays in place.
- `static/app.js` displays reason and available I/O for every failed public case;
  older history without I/O does not pretend the fields were empty. Hidden
  cases explicitly explain the withheld data, and ignore payload detail/I/O.
- Result copy buttons now receive their missing handlers. Result detail cells
  align left instead of inheriting the last numeric column's right alignment.
- JS/CSS assets bumped to v42/v24; engine version 2.0.2. Existing sample-before-
  hidden execution barrier, compiler isolation and contest reveal policy remain.

## Private problem changes — prepared, not published

- **204 additions**, three for each of **68 problems**: **974 → 1,178** cases.
- **198** inputs differ from the original after whitespace normalization. The six
  additions for `hanoi` and `binary_strings` check legal surrounding whitespace:
  all permitted scalar values already occur in their original suites. These six
  do not increase mathematical case coverage; no claim of new stress coverage.
- New expected outputs were computed with separate small-case oracles (including
  brute-force scheduling/subsets/queens/TSP/boat pairing and direct simulations),
  then all 204 compared to the trusted reference with each problem's checker.
- Found and corrected B09 below in the private reference and two existing hidden
  expected-output files. Neither public samples nor config/statement/PDF bytes
  changed. `forest_fire_spread` new inputs retain space-separated integer rows.
- These small cases supplement existing stress suites; they do not prove the
  reference/specification correct or meet every worst-case complexity bound.
- Source fixtures, reference, private generator, independent oracle and backups
  remain outside Git. Never force-add them or publish them in an issue/PR.

| Problem | Before | Added | Prepared total |
| --- | ---: | ---: | ---: |
| `arrange_tray` | 11 | 3 | 14 |
| `array_min_sum` | 14 | 3 | 17 |
| `bake_a_cake` | 17 | 3 | 20 |
| `balanced_brackets` | 15 | 3 | 18 |
| `binary_strings` | 15 | 3 | 18 |
| `blood_moon` | 15 | 3 | 18 |
| `boat_crossing` | 14 | 3 | 17 |
| `broken_stairs` | 14 | 3 | 17 |
| `candy_sales` | 15 | 3 | 18 |
| `club_vote` | 15 | 3 | 18 |
| `collatz_max` | 14 | 3 | 17 |
| `cookie_share` | 14 | 3 | 17 |
| `count_even_odd` | 14 | 3 | 17 |
| `count_islands` | 18 | 3 | 21 |
| `dec_to_bin` | 14 | 3 | 17 |
| `dec_to_hex` | 14 | 3 | 17 |
| `digit_sum` | 14 | 3 | 17 |
| `digital_root` | 14 | 3 | 17 |
| `dna` | 15 | 3 | 18 |
| `dont_love_you` | 11 | 3 | 14 |
| `exact_budget` | 14 | 3 | 17 |
| `fib_sum` | 14 | 3 | 17 |
| `find_max` | 14 | 3 | 17 |
| `flashback` | 15 | 3 | 18 |
| `forest_fire_spread` | 11 | 3 | 14 |
| `fraction_add` | 14 | 3 | 17 |
| `friend_network` | 15 | 3 | 18 |
| `gable_roof` | 15 | 3 | 18 |
| `hanoi` | 10 | 3 | 13 |
| `hex_to_rgb` | 15 | 3 | 18 |
| `hidden_digit_sum` | 14 | 3 | 17 |
| `infinite_tsukuyomi` | 11 | 3 | 14 |
| `kai_gai_codex` | 15 | 3 | 18 |
| `largest_rectangle` | 15 | 3 | 18 |
| `library_code` | 15 | 3 | 18 |
| `lower_bound` | 15 | 3 | 18 |
| `mana_crystal` | 15 | 3 | 18 |
| `maze_escape` | 15 | 3 | 18 |
| `maze_score` | 14 | 3 | 17 |
| `min_distance` | 14 | 3 | 17 |
| `mirror_pair` | 14 | 3 | 17 |
| `napprime` | 16 | 3 | 19 |
| `no_division` | 11 | 3 | 14 |
| `panda` | 15 | 3 | 18 |
| `parking_slots` | 15 | 3 | 18 |
| `payment` | 11 | 3 | 14 |
| `posn_server_passcode` | 16 | 3 | 19 |
| `power_recur` | 14 | 3 | 17 |
| `prime_check` | 14 | 3 | 17 |
| `queens_holes` | 14 | 3 | 17 |
| `riri_khaosan` | 15 | 3 | 18 |
| `rotation` | 15 | 3 | 18 |
| `shadow` | 15 | 3 | 18 |
| `sing_contest` | 15 | 3 | 18 |
| `snack_budget` | 14 | 3 | 17 |
| `spring_mine` | 15 | 3 | 18 |
| `stage_lights` | 15 | 3 | 18 |
| `stage_show` | 15 | 3 | 18 |
| `stone_game` | 15 | 3 | 18 |
| `sum_even` | 14 | 3 | 17 |
| `swordsmith` | 14 | 3 | 17 |
| `thai_time` | 15 | 3 | 18 |
| `ticket_queue` | 15 | 3 | 18 |
| `timetable` | 15 | 3 | 18 |
| `toll_maze` | 15 | 3 | 18 |
| `trapped_rain` | 15 | 3 | 18 |
| `tsp` | 15 | 3 | 18 |
| `warpz` | 15 | 3 | 18 |

## B09 — KAI-GAI reference rejects repeated A despite the statement

**Medium · CONFIRMED · FIXED locally; production correction pending.**

- Affected private files: `problems/kai_gai_codex/statement.md:9`, `:10`, `:12`;
  `examples/kai_gai_codex_ref.py:26` (`count_word`). Old evidence:
  `t[i + 1] == "A" and t[i + 2] == "I"` accepts just one A.
- Root cause: parser disagrees with documented examples `KAAIII` / `gAAiiii`.
- Impact: valid programs can receive WA on hidden fixtures generated from that
  reference. Two original hidden outputs disagree with an independent recursive
  decoder plus `[KG]A+I+` oracle. Remote original suite hashes match local backup;
  this establishes affected stored fixtures, not observed harm to a user.
- Minimal fix: consume one or more A before the I run; correct only the two
  affected existing hidden outputs. No rule/PDF/public example changes.
- Regression: four synthetic word checks, **2/4 before, 4/4 after**; all 18 current
  KAI-GAI fixtures and all 204 newly generated cases pass reference comparison.
- Remaining risk: the private reference regression is supplied by private
  fixtures, not the public synthetic CI checkout. Historical submissions have
  not been rejudged; any targeted rejudge requires separate review.

## B10 — Result copy controls are unbound and I/O inherits numeric alignment

**Low · CONFIRMED · FIXED locally.**

- `static/app.js:2113` (`renderResults`), `static/app.js:1276`
  (`bindCopyButtons`), `static/styles.css:517`.
- Evidence: renderResults created `data-copy` buttons without invoking their
  binder; detail td is also the last column and inherited `text-align:right`.
- Impact: copying failed-case data did nothing; code/data were harder to read.
- Minimal fix: bind after rendering; scope left alignment to detail cells.
- Regression: Node binding assertion passes; real browser with a synthetic
  clipboard verifies exact copied input, left alignment and no mobile overflow.
- Remaining risk: clipboard permission behavior varies; existing fallback is
  retained. Browser API calls were mocked, not a production end-to-end submission.

## Verification

Execution environment: disposable **Linux arm64/root**, kernel 6.8, Python 3.11,
Landlock ABI 4, network disabled. macOS host supplied source and Node/browser
checks. Docker used no privileged mode or added capabilities.

- Baseline critical suite: **117 passed, 0 skipped** (21.213 s).
- Updated critical suite: **119 passed, 0 skipped** (28.097 s).
- Full Python suite: **259 passed, 0 skipped** (109.445 s).
- Node: **33 passed**, zero skips; syntax/DOM/style guards passed.
- Full offline problem/reference validator: **68/68 passed**, 1,178 cases.
- Independent-oracle/reference checks: **204/204 passed**; KAI-GAI before/after
  regression recorded separately. No private values appear in public reports.
- Local browser: public RE reason/I/O, keyboard expansion, copied input, hidden
  canary absence, 390px viewport/no horizontal overflow and left alignment checked.
- Read-only remote preflight: correct Supabase project; **68/68 original suite
  hashes match**; **68 updated / 0 failed** in importer dry-run. Full metadata
  backup and the two affected Storage output objects saved privately with mode
  0600. Production still has **974** cases. Observed queued/running rows: zero at
  preflight only; this is not a maintenance lock or durable drain guarantee.
- Public GET vantage: audit Mac's current network; public IP/network category is
  unknown. `/api/version` reports engine 2.0.0, Supabase source, 68 problems.

Logs/backups/scripts:
`~/.local/share/newbiegrader-validation/submission-feedback-kc67osyx/`.
Browser screenshots:
`~/.local/share/newbiegrader-mcp/artifacts/feedback-mobile-20261018.png`.

## Release and rollback requirements

1. Review the branch diff. Push is authorized; no production DB mutation or
   backend deploy is covered by that instruction alone.
2. Host must satisfy UID mapping/Landlock/persistent identity ledger prerequisites
   in [JOB_ISOLATION.md](JOB_ISOLATION.md) before deploying this branch's backend.
3. For packages, approve a controlled maintenance window: pause admission/drain
   jobs, recheck base hashes, upload new test objects, correct only the two
   reviewed outputs and update only test manifest/hash/count/version fields.
   Preserve publication state/title/statement/PDF/samples. The existing full
   importer writes the row before assets and upserts unrelated metadata; do not
   use it unchecked for a live update. Storage/DB is not one transaction.
4. Verify all remote hashes/counts and judge isolated synthetic cases, then resume
   admission. New cases increase compute/downloads; monitor runtime and egress.
5. Roll back problem manifests and the two changed outputs from the private
   backup while drained; do not delete new assets as part of emergency rollback.
   Never reset the allocated-UID ledger. Existing submissions are not deleted or
   bulk-rejudged. Revert only the feedback commit to undo UI/engine diagnostics;
   no production rollback has been executed.

Next audit work: S04 aggregate resource enforcement and Python capacity math;
S05 identity pre-hijacking and B08 durable queue also remain launch gates.
