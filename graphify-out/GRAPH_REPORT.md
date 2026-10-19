# Graph Report - Newbiegrader  (2026-10-20)

## Corpus Check

- 165 files · ~182,436 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 38 file(s) not represented in the graph (top: .ttf 8, (none) 6, .example 6)

## Summary

- 2080 nodes · 4968 edges · 131 communities (84 shown, 47 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 206 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Community Hubs (Navigation)

- hashlib / CriticalBackendFiles
- .rows() / EmailAuth
- FakeSupabase / synthetic_problem()
- KernelIsolation / IsolationUnavailable
- server.py / _current_identity()
- ApiE2E / .login()
- CriticalRedaction / judge_test()
- tempfile / argparse
- app.js / bindEditorKeys()
- os / pathlib
- schema.sql / submissions
- Request / _is_admin()
- check_frontend.js / check_styles.js
- esc() / icon()
- get / _ensure_problems_fresh()
- _run_job() / _finish_job()
- problem_store.py / load_problem_supabase()
- submit() / _resolve_pid()
- init() / renderTasksTable()
- auth_email_verify() / auth_password()
- plagiarism.py / _fingerprints_from_norma
- json / time
- apiGet() / renderContest()
- validate_problem() / ProblemAuthoring
- load_problem() / SupabaseProblems
- CriticalJobIdentity / scope()
- run_one() / OutputCollectionTests
- build() / StatementLayout
- ctypes / restrict_filesystem()
- doSubmit() / selectProblem()
- load_test.py / main()
- email_auth.py / verify_code()
- ram_limit_mb() / CgroupDetection
- _compile() / prepare_command()
- make_statement_tex.py / re
- grader.py / test_judge_limits.py
- judge_env() / BoundedResult
- contest_detail() /_contest_window()
- test_optimization.js / slice()
- Backend problem-file sto / Current production archi
- _Query / ._execute()
- TrustedProxyIp / _http_request()
- RequestBodyLimit / RequestBoundaries
- run_load() / run_attempt()
- merge_uid_ledger.py / append_reservations()
- tests_hash() / manifest_for_problem()
- load_snapshot() / TestCase
- .table() / ProblemLoading
- OptimizationReview / .contest()
- Email identity remediati / Security release checks
- PerformanceQuickWins / _cxx_pch_flags()
- number_problems.py / main()
- Problem / serialize_problem()
- LoadHarnessTests / validate_target()
- _FakeBucket / ._store()
- CriticalPracticeFeedback / .execute()
- c() / cmd_run()
- judge_runner.py / test_critical_job_identi
- CriticalResourceHost / .inspect()
- Correctness and reliabil / Controlled feedback inva
- run_bounded() /_WindowsJob
- sandbox_identity() / CriticalCompilerRoot
- test_cloudflare_vpc_brid / ref_node_crypto
- test_email_auth.js / ref_node_path
- setContestEditorOpen() / renderContestProblemPick
- PreMigrationFallback / ._register()
- test_edge_proxy.js / assert
- RunnerTests / process_alive()
- fillTaskDetail() / renderContestProblems()
- AuthCookies / .login()
- IsolationPosture / .posture()
- test_removed_leaderboard / assert
- StatementPublishing / .publish()
- test_ui_privacy.js / assert
- test_auth_logo.js / ref_node_assert
- test_problem_loading.js / ref_node_fs
- test_job_polling.js / ref_node_test
- test_submission_feedback / ref_node_vm
- ContestPolicyAudit / .submission()
- check_job_resource_host. / inspect_host()
- problem_authoring.py / create_problem()
- Web-job isolation follow / Production release verif
- PeakSampler / _sample_rss_mb()
- AuthRetentionAudit / .test_concurrent_handoff
- [[proxy]].js / onRequest()
- renderPalette() / renderResumeCard()
- main() / public_sample_errors()
- Newbiegrader SPA index.h / Home view (hero, stats,
- FileBoundary / .test_local_synthetic_su
- Newbiegrader logo with w / Newbiegrader icon (file
- main() / query()
- test_api_e2e.py / _browser_origin()
- SmokeCredentialBoundary / .exercise()
- .test_real_http_bursts_k / respond()
- bootstrap.sh / DEBIAN_FRONTEND
- S04 runtime memory budge / S04 host prerequisites h
- _queue_depth() / _queue_depth_cached()
- Problem statement templa / Problem input validator
- HostAdmission / .test_host_slot_cannot_b
- fetch() / worker.js
- verify-recovery.sh / cleanup()
- verify-worker.sh / cleanup()
- Auth modal screenshot (d / Auth modal screenshot (l
- Queue modes (local vs da / B08 database-queue prepa
- Problem storage migratio / Supabase judge-assets pr
- Single-worker correctnes / Production correctness/c
- vercel.json / headers
- .setUp() / verify_code()
- CriticalVersion / .test_critical_fingerpri
- RemovedLeaderboard / .test_global_board_is_ab
- SIL OFL license for Anup / Anuphan font note (PDF w
- install-staging-tunnel.s / install-staging-tunnel.s
- Practice feedback / prob / Submission feedback and
- Problem authoring standa / Mandatory gates for new
- Problem browsing and PDF / Production performance q
- Statement errata (#48 Fo / Revised problem stories
- Controlled feedback disc / Submission feedback poli
- Load Handling Implementa / Load handling design rev
- Asynchronous judging / Verdicts (AC, WA, TLE, M
- Discord icon / GitHub icon
- _test_fence.sh / _test_fence.sh script
- Pinned Python dependenci
- Google sign-in logo sour
- GUST Font License
- SIL OFL license for Inco
- Email OTP HTML template

## God Nodes (most connected - your core abstractions)

1. `FakeSupabase` - 58 edges
2. `esc()` - 55 edges
3. `ApiE2E` - 53 edges
4. `synthetic_problem()` - 41 edges
5. `load_problem_supabase()` - 33 edges
6. `load_problem()` - 31 edges
7. `test_server()` - 31 edges
8. `SupabaseProblems` - 31 edges
9. `tests_hash()` - 28 edges
10. `_is_admin()` - 28 edges

## Surprising Connections (you probably didn't know these)

- `Synthetic security canary statement` --semantically_similar_to--> `Problem statement template`  [INFERRED] [semantically similar]
  tests/fixtures/security_canary/statement.md → tools/templates/problem/statement.md
- `verify_code()` --calls--> `InvalidCode`  [EXTRACTED]
  tests/test_critical_email_auth.py → email_auth.py
- `OutputCollectionTests` --uses--> `BoundedResult`  [INFERRED]
  tests/test_judge_runner.py → judge_runner.py
- `main()` --indirect_call--> `synthetic_problem()`  [INFERRED]
  tools/ec2_problem_file_canary.py → tests/critical_helpers.py
- `FileBoundary` --uses--> `FakeSupabase`  [INFERRED]
  tools/ec2_problem_file_canary.py → tests/fake_supabase.py

## Import Cycles

- None detected.

## Hyperedges (group relationships)

- **CI jobs gating merges** — github_workflows_ci_validate_job, github_workflows_ci_critical_security_job, github_workflows_ci_queue_sql_job [EXTRACTED 0.95]
- **Production topology: Cloudflare Pages, AWS EC2, Supabase** — docs_production_architecture_cloudflare_pages, docs_production_architecture_aws_ec2, docs_production_architecture_supabase [EXTRACTED 0.95]
- **Sandbox hardening audits** — docs_audits_job_isolation, docs_audits_network_filter, docs_audits_security_audit [INFERRED 0.75]
- **Bundled font licenses and notes** — tools_fonts_anuphan_note, tools_fonts_gust_font_license, tools_fonts_ofl_anuphan, tools_fonts_ofl_inconsolata, tools_fonts_thsarabunnew_note [INFERRED 0.85]
- **Email OTP identity verification flow** — docs_email_verification_setup_resend_smtp, docs_email_verification_setup_email_otp, docs_audits_email_identity_budgets [INFERRED 0.85]
- **Newbiegrader logo variants** — static_logo, static_logo_dark, static_logo_icon, static_logo_icon_dark [INFERRED 0.85]
- **Problem authoring templates** — tools_templates_problem_statement, tools_templates_problem_input_validator_py, tools_templates_problem_reference_py [INFERRED 0.85]
- **Production releases of 2026-10-19** — docs_releases_production_backend_files_2026_10_19_release, docs_releases_production_correctness_release_2026_10_19_release, docs_releases_production_performance_2026_10_19_release [INFERRED 0.85]
- **S04 memory/resource documentation set** — docs_audits_resource_setup, docs_audits_runtime_memory_budget, docs_audits_s04_host_handoff [INFERRED 0.85]

## Communities (131 total, 47 thin omitted)

### Community 0 - "hashlib / CriticalBackendFiles"

Cohesion: 0.05
Nodes (33): _atomic(), backend(), download(), encode(), FilesUnavailable,_index(), _lock(),_logical() (+25 more)

### Community 1 - ".rows() / EmailAuth"

Cohesion: 0.05
Nodes (10): _AuthRPC,_QueueRPC, _Resp, EmailAuth, signed_cookie(), verified_row(), DatabaseOwnership, DatabaseWorkerBackoff (+2 more)

### Community 2 - "FakeSupabase / synthetic_problem()"

Cohesion: 0.07
Nodes (4): synthetic_problem(), test_server(), FakeSupabase, CriticalReleaseCorrectness

### Community 3 - "KernelIsolation / IsolationUnavailable"

Cohesion: 0.05
Nodes (27): assert_healthy(),_empty_group(), initialize(), IsolationUnavailable, job_scope(), JobResources, _membership(),_number() (+19 more)

### Community 4 - "server.py / _current_identity()"

Cohesion: 0.04
Nodes (26): _announcements_supported(), _apply_problem_snapshot(), auth_finish(), auth_restore(), AuthQueryLogFilter,_csrf_origin_check(), _current_identity(), _has_session_cookie() (+18 more)

### Community 5 - "ApiE2E / .login()"

Cohesion: 0.08
Nodes (3): _sanitize_compile_error(), ApiE2E,_iso()

### Community 6 - "CriticalRedaction / judge_test()"

Cohesion: 0.06
Nodes (13): execute(), enforced_memory_mb(), judge_test(), mem_limit_mb(), memory_note(), over_memory_limit(), _derive_capacity(), job_mb() (+5 more)

### Community 7 - "tempfile / argparse"

Cohesion: 0.07
Nodes (10): main(), main(), verify_network_filter(), main(), EncryptedStateBackup, build(), find_header(), main() (+2 more)

### Community 8 - "app.js / bindEditorKeys()"

Cohesion: 0.05
Nodes (47): acknowledgeCookieNotice(), ADMIN_TABS, API, applyIndent(), bindEditorKeys(),_byPidIndex, commentToken(), CONTEST_STATUS_TH (+39 more)

### Community 9 - "os / pathlib"

Cohesion: 0.09
Nodes (7): main(), _allocate(), identity(),_state_directory(), main(), CriticalResult, main()

### Community 10 - "schema.sql / submissions"

Cohesion: 0.07
Nodes (38): auth_rate_buckets_expiry, contest_announcements, contest_announcements_contest_time, contest_registrations, contests, judge_jobs, judge_jobs_active_user, judge_jobs_claim_cover (+30 more)

### Community 11 - "Request / _is_admin()"

Cohesion: 0.11
Nodes (27): admin_plagiarism(), admin_rejudge(), _reveal_for_row(),_annc_note_missing_table(), auth_me(), contest_announcements(),_contest_or_404(), create_report() (+19 more)

### Community 12 - "check_frontend.js / check_styles.js"

Cohesion: 0.05
Nodes (30): APP_JS, fs, hrefRefs, html, htmlIds, iconCalls, INDEX_HTML, jsIds (+22 more)

### Community 13 - "esc() / icon()"

Cohesion: 0.10
Nodes (40): apiGetCached(), applyTheme(), badgeVerdict(), bindCopyButtons(), bindViewButtons(), byPidOf(), copyText(), detailHtml() (+32 more)

### Community 14 - "get / _ensure_problems_fresh()"

Cohesion: 0.10
Nodes (25): _acached(), admin_overview(), api_unknown(), auth_login(), _browse_cache_control(),_build_stats(),_contest_problem_sets(), _contest_result_frozen() (+17 more)

### Community 15 - "_run_job() / _finish_job()"

Cohesion: 0.08
Nodes (26): sample_names(),_bust_cache(),_finish_job(),_heartbeat_job(),_iso_now(), job_status(), _judge_isolation_posture(),_judge_worker() (+18 more)

### Community 16 - "problem_store.py / load_problem_supabase()"

Cohesion: 0.15
Nodes (25): _cache_get(), _cache_put(), cache_ttl_s(), _download(),_fetch_all_rows(), fetch_row(),_fetch_row(), get_problem() (+17 more)

### Community 17 - "submit() / _resolve_pid()"

Cohesion: 0.09
Nodes (18): _all_contest_rows(),_cached_contest_rows(), _contest_policy_rows(),_contests_listing(),_create_job(),_evict_oldest(),_live_hidden_pids(), _meta_or_404() (+10 more)

### Community 18 - "init() / renderTasksTable()"

Cohesion: 0.11
Nodes (32): buildFilterOptions(), clearGetCache(), clearLocalWorkspace(), doPasswordAuth(), fetchMyBest(), fetchStats(), init(), lastLang() (+24 more)

### Community 19 - "auth_email_verify() / auth_password()"

Cohesion: 0.09
Nodes (24): normalize_email(), auth_callback(), _auth_email(), auth_email_verify(), auth_logout(), auth_password(), auth_register(),_auth_rpc() (+16 more)

### Community 20 - "plagiarism.py / _fingerprints_from_norma"

Cohesion: 0.12
Nodes (16): _abstract(),_case(), _escaped(), fingerprints(),_fingerprints_from_normalized(), _gram_hash(), _is_c_family(),_keywords() (+8 more)

### Community 21 - "json / time"

Cohesion: 0.15
Nodes (12): main(), restore_files(), safe_key(), source_archive(), deadline(), download(), listing(), fixture() (+4 more)

### Community 22 - "apiGet() / renderContest()"

Cohesion: 0.17
Nodes (27): apiDelete(), apiFetch(), apiGet(), apiPostJson(), badge(), contestCardHtml(), contestRegister(), contestStatusBadge() (+19 more)

### Community 23 - "validate_problem() / ProblemAuthoring"

Cohesion: 0.14
Nodes (4): ProblemAuthoring, statement_contract_errors(), tokens(), validate_problem()

### Community 24 - "load_problem() / SupabaseProblems"

Cohesion: 0.15
Nodes (3): load_problem(), invalidate_cache(), SupabaseProblems

### Community 25 - "CriticalJobIdentity / scope()"

Cohesion: 0.09
Nodes (5): _Job, launch_scope(), scope(), CriticalJobIdentity, CriticalNetworkExecution

### Community 26 - "run_one() / OutputCollectionTests"

Cohesion: 0.13
Nodes (7): _cpu_children(), _is_job_tmp(),_run_cwd(), run_one(), _sig_name(), RuntimePaths, OutputCollectionTests

### Community 27 - "build() / StatementLayout"

Cohesion: 0.14
Nodes (9): StatementLayout, brand_header(), build(),_limits_line(), render_samples_table(), cell(), sample_font_size(), split_sample() (+1 more)

### Community 28 - "ctypes / restrict_filesystem()"

Cohesion: 0.14
Nodes (11): build_limits(),_fn(), _env_flag(), _set_no_new_privileges(), _install_network_filter(), landlock_abi(), _libc(),_network_filter_program() (+3 more)

### Community 29 - "doSubmit() / selectProblem()"

Cohesion: 0.17
Nodes (21): apiPostForm(), doSubmit(), draftFor(), forgetJob(), jobStateText(), keepNewest(), lastJobFor(), lsJson() (+13 more)

### Community 30 - "load_test.py / main()"

Cohesion: 0.14
Nodes (5): bounded_int(), load_accounts(), main(), positive_float(), summarize()

### Community 31 - "email_auth.py / verify_code()"

Cohesion: 0.18
Nodes (7): InvalidCode, _NoRedirect,_post(), request_code(), Unavailable, verify_code(), ProviderTransport

### Community 32 - "ram_limit_mb() / CgroupDetection"

Cohesion: 0.23
Nodes (5): cgroup_root(), cpu_quota(), ram_limit_mb(), _read_first(), CgroupDetection

### Community 33 - "_compile() / prepare_command()"

Cohesion: 0.18
Nodes (9): _compile(), CompileError, detect_language(), prepare_command(), prepare_workspace(), SandboxUnavailable, _effective(),_run_playground() (+1 more)

### Community 34 - "make_statement_tex.py / re"

Cohesion: 0.22
Nodes (11): _eng_wrap(), esc_plain(), has_thai(), _is_thai(), _latin_tex(), md_blocks(), normalize_pdf(), _runs() (+3 more)

### Community 35 - "grader.py / test_judge_limits.py"

Cohesion: 0.16
Nodes (8): C, check_decimal2(), check_exact(), check_float(), check_token(), _linewise_exact(), netns_available(), run_checker()

### Community 36 - "judge_env() / BoundedResult"

Cohesion: 0.14
Nodes (5): judge_env(), launch_environment(), BoundedResult, CriticalCompilerPlumbing, CriticalResourceSetup

### Community 37 - "contest_detail() /_contest_window()"

Cohesion: 0.16
Nodes (11): contest_detail(),_contest_public(),_contest_scoreboard(),_contest_started(),_contest_window(),_effective_reveal(),_is_registered(),_registered_contest_ids() (+3 more)

### Community 38 - "test_optimization.js / slice()"

Cohesion: 0.12
Nodes (7): assert, cacheHarness(), fs, slice(), source, {test}, vm

### Community 39 - "Backend problem-file sto / Current production archi"

Cohesion: 0.14
Nodes (16): Backend problem-file storage, public-files / private-files roots, publish/verify problem files tools, Cloudflare MCP add-on, Codex MCP setup, age-encrypted backups and restore rehearsal, EC2 backup/restore gate, Cloudflare connection to AWS production (+8 more)

### Community 42 - "RequestBodyLimit / RequestBoundaries"

Cohesion: 0.14
Nodes (6): RequestBodyLimit, replay(), RequestBoundaries, app(), exercise(), receive()

### Community 43 - "run_load() / run_attempt()"

Cohesion: 0.21
Nodes (6): Client, Metrics, NoRedirect, run_attempt(), run_load(), health_probe()

### Community 44 - "merge_uid_ledger.py / append_reservations()"

Cohesion: 0.20
Nodes (5): append_reservations(), main(), records(), LedgerMerge, LedgerRecords

### Community 45 - "tests_hash() / manifest_for_problem()"

Cohesion: 0.18
Nodes (4): tests_hash(), manifest_for_problem(), seed_fake(), import_one()

### Community 46 - "load_snapshot() / TestCase"

Cohesion: 0.18
Nodes (7): TestCase, invalidate_stale(), load_meta(), load_metadata_only(), load_snapshot(), load_tests_hash_map(), _row_to_problem()

### Community 49 - "Email identity remediati / Security release checks"

Cohesion: 0.18
Nodes (13): Shared email send/guess budgets, Email identity remediation (S05), Google login button verification, Email OTP ownership proof, Email verification setup (Thai), Resend SMTP via Supabase Auth, /api/version build_sha256, no_new_privs hardening (+5 more)

### Community 51 - "number_problems.py / main()"

Cohesion: 0.24
Nodes (9): order_key(), sort_problems(), assign_order(), cmd_assign(), cmd_check(), cmd_list(), load_all(), main() (+1 more)

### Community 52 - "Problem / serialize_problem()"

Cohesion: 0.18
Nodes (6): Problem, deserialize_problem(), serialize_problem(), _load_local_problems(),_problem_description(), SubmissionIntegrity

### Community 53 - "LoadHarnessTests / validate_target()"

Cohesion: 0.17
Nodes (5): LoadHarnessTests, request(), request(), job_durations(), validate_target()

### Community 56 - "c() / cmd_run()"

Cohesion: 0.29
Nodes (11): c(), cmd_info(), cmd_run(), report(), list_problems(), main(), show_diff(), _show_diff_head() (+3 more)

### Community 57 - "judge_runner.py / test_critical_job_identi"

Cohesion: 0.21
Nodes (5): _children(),_cleanup_linux(),_descendants(), _runner_env(), _supervise()

### Community 59 - "Correctness and reliabil / Controlled feedback inva"

Cohesion: 0.20
Nodes (9): grader.py judging engine, Newbiegrader online judge, server.py FastAPI app, B01 public history bypasses contest freeze, B02 scoreboard drops results beyond 5000, B03 contest metadata ignores unpublished flag, B04 stored source truncation, Correctness and reliability audit 2026-10-18 (+1 more)

### Community 60 - "run_bounded() /_WindowsJob"

Cohesion: 0.20
Nodes (3): run_bounded(),_WindowsJob, allocate()

### Community 61 - "sandbox_identity() / CriticalCompilerRoot"

Cohesion: 0.24
Nodes (3): _chmod_job_path(), sandbox_identity(), CriticalCompilerRoot

### Community 62 - "test_cloudflare_vpc_brid / ref_node_crypto"

Cohesion: 0.20
Nodes (9): assert, fetch(), fs, harness(), path, source, { test }, vm (+1 more)

### Community 63 - "test_email_auth.js / ref_node_path"

Cohesion: 0.20
Nodes (9): assert, code, fs, harness(), node(), path, source, { test } (+1 more)

### Community 64 - "setContestEditorOpen() / renderContestProblemPick"

Cohesion: 0.33
Nodes (11): applyContestDuration(), buildProblemSelect(), contestProblemIds(), nextHalfHourInput(), renderAdminTools(), renderContestProblemPicker(), setContestEditorOpen(), setContestProblems() (+3 more)

### Community 66 - "test_edge_proxy.js / assert"

Cohesion: 0.18
Nodes (6): assert, fs, path, { test }, vm, { webcrypto, timingSafeEqual }

### Community 68 - "fillTaskDetail() / renderContestProblems()"

Cohesion: 0.20
Nodes (10): diffBadge(), enterContestFrom(), fillTaskDetail(), loadSample(), openTask(), prefetchSamples(), renderContestBanner(), renderContestProblems() (+2 more)

### Community 71 - "test_removed_leaderboard / assert"

Cohesion: 0.20
Nodes (7): assert, fs, html, path, source, { test }, vm

### Community 73 - "test_ui_privacy.js / assert"

Cohesion: 0.20
Nodes (6): assert, fs, path, source, { test }, vm

### Community 74 - "test_auth_logo.js / ref_node_assert"

Cohesion: 0.22
Nodes (7): assert, css, fs, html, path, root, { test }

### Community 75 - "test_problem_loading.js / ref_node_fs"

Cohesion: 0.22
Nodes (6): assert, fs, path, source, { test }, vm

### Community 76 - "test_job_polling.js / ref_node_test"

Cohesion: 0.22
Nodes (6): app, assert, fs, pollingCode, { test }, vm

### Community 77 - "test_submission_feedback / ref_node_vm"

Cohesion: 0.22
Nodes (6): assert, context, fs, source, { test }, vm

### Community 79 - "check_job_resource_host. / inspect_host()"

Cohesion: 0.39
Nodes (4): inspect_host(), main(),_mount_path(),_read()

### Community 80 - "problem_authoring.py / create_problem()"

Cohesion: 0.36
Nodes (4): create_problem(), main(), problem_id(), sync_samples()

### Community 81 - "Web-job isolation follow / Production release verif"

Cohesion: 0.25
Nodes (8): Web-job isolation follow-up, Landlock filesystem restriction, Per-job UID/GID identity allocation, Compiler/runtime network restriction, Production readiness audit, Production release verification 2026-10-18, Newbiegrader security audit, Linux validation to do

### Community 82 - "PeakSampler / _sample_rss_mb()"

Cohesion: 0.25
Nodes (3): PeakSampler, sample(), _sample_rss_mb()

### Community 84 - "[[proxy]].js / onRequest()"

Cohesion: 0.48
Nodes (6): backendOrigin(), boundedBody(), EDGE_CACHE_PATHS, isAnonymousGet(), onRequest(), sameKey()

### Community 85 - "renderPalette() / renderResumeCard()"

Cohesion: 0.33
Nodes (7): closePalette(), noLabel(), openPalette(), paletteMatches(), relTime(), renderPalette(), renderResumeCard()

### Community 86 - "main() / public_sample_errors()"

Cohesion: 0.29
Nodes (4): main(), _join(), parse_samples(), public_sample_errors()

### Community 87 - "Newbiegrader SPA index.h / Home view (hero, stats, "

Cohesion: 0.33
Nodes (6): Newbiegrader SPA index.html, Home view (hero, stats, starter problems), Inline SVG icon sprite, Tasks view (filter bar, tag sidebar), Topbar navigation and auth controls, styles.css

### Community 89 - "Newbiegrader logo with w / Newbiegrader icon (file "

Cohesion: 0.40
Nodes (5): Newbiegrader brand identity: document, terminal prompt, green check (judged), Newbiegrader logo with wordmark (light-mode), Newbiegrader logo with wordmark (dark-mode, white), Newbiegrader icon (file with terminal prompt and green checkmark), Newbiegrader icon (dark-mode variant)

### Community 90 - "main() / query()"

Cohesion: 0.70
Nodes (5): main(), admit(), claim(), finish(), query()

### Community 93 - ".test_real_http_bursts_k / respond()"

Cohesion: 0.60
Nodes (3): do_GET(), do_POST(), respond()

### Community 94 - "bootstrap.sh / DEBIAN_FRONTEND"

Cohesion: 0.50
Nodes (3): DEBIAN_FRONTEND, bootstrap.sh script, UV_PYTHON_INSTALL_DIR

### Community 95 - "S04 runtime memory budge / S04 host prerequisites h"

Cohesion: 0.50
Nodes (4): S04 resource-limit setup follow-up, S04 runtime memory budget correction, Enforced address-space budget in _derive_capacity, S04 host prerequisites handoff

### Community 97 - "Problem statement templa / Problem input validator "

Cohesion: 0.67
Nodes (4): Synthetic security canary statement, Problem input validator template, Problem reference solution template, Problem statement template

### Community 102 - "Auth modal screenshot (d / Auth modal screenshot (l"

Cohesion: 1.00
Nodes (3): Auth modal screenshot (dark): signup tab with email and Continue with Google, Auth modal screenshot (light): login tab with email, password, remember me, forgot password, Continue with Google, Google G logo

### Community 103 - "Queue modes (local vs da / B08 database-queue prepa"

Cohesion: 0.67
Nodes (3): B08 database-queue preparation, Load handling and rollout, Queue modes (local vs database) and roles

### Community 104 - "Problem storage migratio / Supabase judge-assets pr"

Cohesion: 0.67
Nodes (3): Supabase judge-assets private bucket, Problem storage migration to Supabase, Production backend problem-file deployment 2026-10-19

### Community 105 - "Single-worker correctnes / Production correctness/c"

Cohesion: 0.67
Nodes (3): Production correctness/cache deployment 2026-10-19, Single-worker correctness/cache release review, Two-GiB host readiness and single-worker release gate

### Community 110 - "SIL OFL license for Anup / Anuphan font note (PDF w"

Cohesion: 0.67
Nodes (3): Anuphan font note (PDF wordmark), SIL OFL license for Anuphan, TH Sarabun New font note (GPL with embedding exception)

## Knowledge Gaps

- **62 isolated node(s):** `DEBIAN_FRONTEND`, `UV_PYTHON_INSTALL_DIR`, `queue-sql CI job (Postgres 17)`, `validate CI job`, `grader.py judging engine` (+57 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 683 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **47 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions

_Questions this graph is uniquely positioned to answer:_

- **Why does `FakeSupabase` connect `FakeSupabase / synthetic_problem()` to `hashlib / CriticalBackendFiles`, `.rows() / EmailAuth`, `ApiE2E / .login()`, `CriticalRedaction / judge_test()`, `os / pathlib`, `load_problem() / SupabaseProblems`, `tests_hash() / manifest_for_problem()`, `.table() / ProblemLoading`, `OptimizationReview / .contest()`, `PerformanceQuickWins / _cxx_pch_flags()`, `_FakeBucket / ._store()`, `CriticalPracticeFeedback / .execute()`, `PreMigrationFallback / ._register()`, `AuthCookies / .login()`, `StatementPublishing / .publish()`, `ContestPolicyAudit / .submission()`, `FileBoundary / .test_local_synthetic_su`, `test_api_e2e.py / _browser_origin()`, `.setUp() / verify_code()`?**
  _High betweenness centrality (0.094) - this node is a cross-community bridge._
- **Are the 19 inferred relationships involving `FakeSupabase` (e.g. with `ApiE2E` and `PreMigrationFallback`) actually correct?**
  _`FakeSupabase` has 19 INFERRED edges - model-reasoned connections that need verification._
- **What connects `DEBIAN_FRONTEND`, `UV_PYTHON_INSTALL_DIR`, `queue-sql CI job (Postgres 17)` to the rest of the system?**
  _62 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `hashlib / CriticalBackendFiles` be split into smaller, more focused modules?**
  _Cohesion score 0.05277777777777778 - nodes in this community are weakly interconnected._
- **Why does `ApiE2E` connect `ApiE2E / .login()` to `FakeSupabase / synthetic_problem()`, `test_api_e2e.py / _browser_origin()`, `tests_hash() / manifest_for_problem()`?**
  _High betweenness centrality (0.045) - this node is a cross-community bridge._
- **Should `.rows() / EmailAuth` be split into smaller, more focused modules?**
  _Cohesion score 0.05277777777777778 - nodes in this community are weakly interconnected._
- **Why does `synthetic_problem()` connect `FakeSupabase / synthetic_problem()` to `hashlib / CriticalBackendFiles`, `_compile() / prepare_command()`, `RunnerTests / process_alive()`, `judge_env() / BoundedResult`, `KernelIsolation / IsolationUnavailable`, `tempfile / argparse`, `os / pathlib`, `tests_hash() / manifest_for_problem()`, `.table() / ProblemLoading`, `PerformanceQuickWins / _cxx_pch_flags()`, `Problem / serialize_problem()`, `load_problem() / SupabaseProblems`, `judge_runner.py / test_critical_job_identi`, `run_one() / OutputCollectionTests`, `CriticalJobIdentity / scope()`?**
  _High betweenness centrality (0.030) - this node is a cross-community bridge._
