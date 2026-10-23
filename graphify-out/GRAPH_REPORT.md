# Graph Report - Newbiegrader  (2026-10-23)

## Corpus Check
- 166 files · ~194,073 words
- Verdict: corpus is large enough that graph structure adds value.
- Unclassified: 48 file(s) not represented in the graph (top: .service 9, .ttf 8, .example 7)

## Summary
- 2652 nodes · 6323 edges · 157 communities (106 shown, 51 thin omitted)
- Extraction: 96% EXTRACTED · 4% INFERRED · 0% AMBIGUOUS · INFERRED: 256 edges (avg confidence: 0.86)
- Token cost: 0 input · 0 output

## Graph Freshness
- Built from commit: `aecab169`
- Run `git rev-parse HEAD` and compare to check if the graph is stale.
- Run `graphify update .` after code changes (no API cost).

## Community Hubs (Navigation)
- CriticalBackendFiles
- QueueAdmission
- unittest
- CriticalJobResources
- _origin_allowed
- ApiE2E
- judge_test
- tempfile
- app.js
- grader.py
- schema.sql
- _db_err
- check_frontend.js
- esc
- get
- server.py
- problem_store.py
- _resolve_pid
- init
- Request
- plagiarism.py
- validate_problem.py
- apiGet
- validate_problem
- SupabaseProblems
- _compile
- run_one
- build
- ctypes
- doSubmit
- load_test.py
- newbiegrader-alert.py
- ram_limit_mb
- judge_execution.py
- make_statement_tex.py
- .rows
- judge_env
- _contest_window
- test_optimization.js
- docs/README.md
- _Query
- TrustedProxyIp
- RequestBoundaries
- .connection
- os
- tests_hash
- json
- FakeSupabase
- OptimizationReview
- Security release checks
- PerformanceQuickWins
- number_problems.py
- test_critical_database_transport.py
- historyTable
- _FakeBucket
- CriticalPracticeFeedback
- load_problem
- judge_runner.py
- CriticalResourceHost
- Newbiegrader online judge
- run_bounded
- sandbox_identity
- test_cloudflare_vpc_bridge.js
- test_email_auth.js
- setContestEditorOpen
- PreMigrationFallback
- test_edge_proxy.js
- RunnerTests
- router
- AuthCookies
- IsolationPosture
- test_removed_leaderboard.js
- StatementPublishing
- test_ui_privacy.js
- ref_node_path
- test_problem_loading.js
- ref_node_assert
- ref_node_test
- ContestPolicyAudit
- _is_admin
- create_problem
- hashlib
- _sample_rss_mb
- SpawnFailureIsNeverAVerdict
- [[proxy]].js
- import_problems_supabase.py
- parse_samples
- Newbiegrader SPA index.html
- IsolationUnavailable
- Newbiegrader logo with wordmark (light-mode)
- AdminManagement
- KernelIsolation
- test_admin_reload.js
- CriticalJobIdentity
- AlertWatchdog
- test_peer_inspection.js
- Dependency licences
- Problem statement template
- HostAdmission
- ref_node_vm
- PresenceGateway
- test_edge_abuse.js
- Auth modal screenshot (dark): signup tab with email and Continue with Google
- test_verdict_labels.js
- Native backend deployment
- AggregateCache
- vercel.json
- test_editor_gutter.js
- CriticalVersion
- RemovedLeaderboard
- SIL OFL license for Anuphan
- Verdicts
- SmokeCredentialBoundary
- Public website security qualification
- bindEditorKeys
- turnstile.js
- session_revocation.sql
- fetch
- Asynchronous judging
- Discord icon
- _test_fence.sh
- Pinned Python dependencies (fastapi, starlette, uvicorn, supabase, itsdangerous)
- Google sign-in logo source
- GUST Font License
- SIL OFL license for Inconsolata
- Email OTP HTML template
- ref_node_fs
- CriticalReleaseCorrectness
- benchmark_hotpaths.py
- main
- EncryptedBackup
- Revocable website sessions
- run_isolated
- legacy_schema.sql
- HostUnits
- bootstrap.sh
- verify-worker.sh
- verify-workers.sh
- HOST_CLOUDFLARE_SETUP.md
- Documentation
- verify-recovery.sh
- Backend backup and recovery
- feedback_history_remediation.sql
- AuthQueryLogFilter
- _source_fingerprint
- install-staging-tunnel.sh
- Contests

## God Nodes (most connected - your core abstractions)
1. `FakeSupabase` - 72 edges
2. `esc()` - 59 edges
3. `ApiE2E` - 53 edges
4. `synthetic_problem()` - 44 edges
5. `_is_admin()` - 41 edges
6. `test_server()` - 38 edges
7. `load_problem()` - 33 edges
8. `load_problem_supabase()` - 33 edges
9. `SupabaseProblems` - 32 edges
10. `Problem` - 28 edges

## Surprising Connections (you probably didn't know these)
- `Container base image and OS packages` --references--> `curl()`  [INFERRED]
  docs/DEPENDENCY_LICENSES.md → tests/test_critical_host_smoke.py
- `Synthetic security canary statement` --semantically_similar_to--> `Problem statement template`  [INFERRED] [semantically similar]
  tests/fixtures/security_canary/statement.md → tools/templates/problem/statement.md
- `main()` --calls--> `validate()`  [INFERRED]
  tools/import_problems_supabase.py → backend_problem_files.py
- `replay()` --calls--> `receive()`  [INFERRED]
  server.py → deploy/host/discord_presence.py
- `attach()` --calls--> `IsolationUnavailable`  [EXTRACTED]
  tests/test_critical_job_resources.py → job_resources.py

## Import Cycles
- None detected.

## Hyperedges (group relationships)
- **CI jobs gating merges** — github_workflows_ci_validate_job, github_workflows_ci_critical_security_job, github_workflows_ci_queue_sql_job [EXTRACTED 0.95]
- **Production topology: Cloudflare Pages, AWS EC2, Supabase** — docs_production_architecture_cloudflare_pages, docs_production_architecture_aws_ec2, docs_production_architecture_supabase [EXTRACTED 0.95]
- **Bundled font licenses and notes** — tools_fonts_anuphan_note, tools_fonts_gust_font_license, tools_fonts_ofl_anuphan, tools_fonts_ofl_inconsolata, tools_fonts_thsarabunnew_note [INFERRED 0.85]
- **Newbiegrader logo variants** — static_logo, static_logo_dark, static_logo_icon, static_logo_icon_dark [INFERRED 0.85]
- **Problem authoring templates** — tools_templates_problem_statement, tools_templates_problem_input_validator_py, tools_templates_problem_reference_py [INFERRED 0.85]

## Communities (157 total, 51 thin omitted)

### Community 0 - "CriticalBackendFiles"
Cohesion: 0.09
Nodes (17): _atomic(), backend(), download(), encode(), FilesUnavailable, _index(), _lock(), _logical() (+9 more)

### Community 1 - "QueueAdmission"
Cohesion: 0.06
Nodes (9): refresh(), _AuthRPC, _QueueRPC, _Resp, DatabaseOwnership, DatabaseWorkerBackoff, slot(), job() (+1 more)

### Community 2 - "unittest"
Cohesion: 0.08
Nodes (4): synthetic_problem(), test_server(), _browser_origin(), PublicHeaders

### Community 3 - "CriticalJobResources"
Cohesion: 0.15
Nodes (5): assert_healthy(), job_scope(), JobResources, required(), CriticalJobResources

### Community 4 - "_origin_allowed"
Cohesion: 0.17
Nodes (8): _csrf_origin_check(), _has_session_cookie(), _is_dev_mode(), _is_loopback_origin(), _origin_allowed(), _origin_tuple(), _security_headers(), _trusted_origins()

### Community 5 - "ApiE2E"
Cohesion: 0.08
Nodes (3): _sanitize_compile_error(), ApiE2E, _iso()

### Community 6 - "judge_test"
Cohesion: 0.06
Nodes (12): execute(), enforced_memory_mb(), judge_test(), mem_limit_mb(), memory_note(), over_memory_limit(), _derive_capacity(), job_mb() (+4 more)

### Community 7 - "tempfile"
Cohesion: 0.08
Nodes (14): main(), main(), main(), main(), main(), admit(), claim(), finish() (+6 more)

### Community 8 - "app.js"
Cohesion: 0.05
Nodes (52): acknowledgeCookieNotice(), ADMIN_TABS, API, apiPostForm(), _byPidIndex, clearGetCache(), clearSubmissionInspection(), closePalette() (+44 more)

### Community 9 - "grader.py"
Cohesion: 0.06
Nodes (12): C, netns_available(), judge_python(), inspect_host(), main(), _mount_path(), _read(), main() (+4 more)

### Community 10 - "schema.sql"
Cohesion: 0.06
Nodes (39): auth_rate_buckets_expiry, contest_announcements, contest_announcements_contest_time, contest_registrations, contests, judge_jobs, judge_jobs_active_user, judge_jobs_claim_cover (+31 more)

### Community 11 - "_db_err"
Cohesion: 0.08
Nodes (26): _annc_note_missing_table(), _announcements_supported(), contest_announcements(), contest_detail(), _contest_or_404(), _contest_public(), _contest_rows(), _contest_started() (+18 more)

### Community 12 - "check_frontend.js"
Cohesion: 0.05
Nodes (30): APP_JS, fs, hrefRefs, html, htmlIds, iconCalls, INDEX_HTML, jsIds (+22 more)

### Community 13 - "esc"
Cohesion: 0.11
Nodes (41): applyTheme(), badgeVerdict(), bindCopyButtons(), contestCardHtml(), copyText(), detailHtml(), diffBadge(), diffHtml() (+33 more)

### Community 14 - "get"
Cohesion: 0.09
Nodes (20): _acached(), _admin_history_row(), admin_overview(), admin_submissions(), api_unknown(), auth_login(), auth_me(), _build_stats() (+12 more)

### Community 15 - "server.py"
Cohesion: 0.06
Nodes (36): _apply_problem_snapshot(), _bust_cache(), _cookie_secure(), _finish_job(), _hash_password(), _heartbeat_job(), _host_slot(), _iso_now() (+28 more)

### Community 16 - "problem_store.py"
Cohesion: 0.11
Nodes (34): Problem, TestCase, _cache_get(), _cache_put(), cache_ttl_s(), deserialize_problem(), _download(), _fetch_all_rows() (+26 more)

### Community 17 - "_resolve_pid"
Cohesion: 0.08
Nodes (23): sample_names(), admin_rejudge(), _browse_cache_control(), _contests_listing(), _create_job(), _ensure_problems_fresh(), _evict_oldest(), list_reports() (+15 more)

### Community 18 - "init"
Cohesion: 0.22
Nodes (13): applyHomeFilter(), buildFilterOptions(), fetchStats(), init(), lastLang(), loadProblemsCache(), problemRowsForIdentity(), problemsCacheAgeMs() (+5 more)

### Community 19 - "Request"
Cohesion: 0.11
Nodes (32): normalize_email(), auth_callback(), _auth_email(), auth_email_verify(), auth_finish(), auth_logout(), auth_password(), auth_register() (+24 more)

### Community 20 - "plagiarism.py"
Cohesion: 0.11
Nodes (16): _abstract(), _case(), _escaped(), fingerprints(), _fingerprints_from_normalized(), _gram_hash(), _is_c_family(), _keywords() (+8 more)

### Community 21 - "validate_problem.py"
Cohesion: 0.11
Nodes (7): EncryptedStateBackup, build_record(), check_build(), digest(), renderer_source(), canon(), _read_no()

### Community 22 - "apiGet"
Cohesion: 0.17
Nodes (28): addAdminByEmail(), apiDelete(), apiFetch(), apiGet(), apiPostJson(), clearLocalWorkspace(), contestRegister(), loadAdminContests() (+20 more)

### Community 23 - "validate_problem"
Cohesion: 0.14
Nodes (4): ProblemAuthoring, statement_contract_errors(), tokens(), validate_problem()

### Community 24 - "SupabaseProblems"
Cohesion: 0.14
Nodes (4): invalidate_cache(), serialize_problem(), run_submission(), SupabaseProblems

### Community 25 - "_compile"
Cohesion: 0.13
Nodes (8): _compile(), CompileError, prepare_workspace(), SandboxUnavailable, _Job, launch_scope(), scope(), CriticalNetworkExecution

### Community 26 - "run_one"
Cohesion: 0.10
Nodes (8): _cpu_children(), _is_job_tmp(), _run_cwd(), run_one(), _sig_name(), BoundedResult, RuntimePaths, OutputCollectionTests

### Community 27 - "build"
Cohesion: 0.14
Nodes (9): StatementLayout, brand_header(), build(), _limits_line(), render_samples_table(), cell(), sample_font_size(), split_sample() (+1 more)

### Community 28 - "ctypes"
Cohesion: 0.13
Nodes (11): build_limits(), _fn(), _env_flag(), _set_no_new_privileges(), _install_network_filter(), landlock_abi(), _libc(), _network_filter_program() (+3 more)

### Community 29 - "doSubmit"
Cohesion: 0.15
Nodes (22): doSubmit(), draftFor(), enterContestFrom(), forgetJob(), jobStateText(), keepNewest(), lastJobFor(), lsJson() (+14 more)

### Community 30 - "load_test.py"
Cohesion: 0.05
Nodes (27): check_decimal2(), check_exact(), check_float(), check_token(), _linewise_exact(), run_checker(), CheckerEquivalence, decimal_contract() (+19 more)

### Community 31 - "newbiegrader-alert.py"
Cohesion: 0.07
Nodes (26): _backup_age_hours(), build_payload(), collect_checks(), _format_for(), _get_json(), _journal_hits(), _load_state(), main() (+18 more)

### Community 32 - "ram_limit_mb"
Cohesion: 0.23
Nodes (5): cgroup_root(), cpu_quota(), ram_limit_mb(), _read_first(), CgroupDetection

### Community 33 - "judge_execution.py"
Cohesion: 0.15
Nodes (11): detect_language(), prepare_command(), _effective(), _plain_text(), _redact_results(), _run_playground(), run_submission(), Settings (+3 more)

### Community 34 - "make_statement_tex.py"
Cohesion: 0.22
Nodes (11): _eng_wrap(), esc_plain(), has_thai(), _is_thai(), _latin_tex(), md_blocks(), normalize_pdf(), _runs() (+3 more)

### Community 35 - ".rows"
Cohesion: 0.06
Nodes (7): request(), EmailAuth, signed_cookie(), verified_row(), CriticalPeerInspection, table(), SessionRevocation

### Community 36 - "judge_env"
Cohesion: 0.15
Nodes (4): judge_env(), launch_environment(), CriticalCompilerPlumbing, CriticalResourceSetup

### Community 37 - "_contest_window"
Cohesion: 0.08
Nodes (21): _reveal_for_row(), _all_contest_rows(), _cached_contest_rows(), _completed_peer_submission(), _contest_policy_rows(), _contest_result_frozen(), _contest_scoreboard(), _contest_times_valid() (+13 more)

### Community 38 - "test_optimization.js"
Cohesion: 0.12
Nodes (7): assert, cacheHarness(), fs, slice(), source, {test}, vm

### Community 39 - "docs/README.md"
Cohesion: 0.16
Nodes (18): Backend problem-file storage, public-files / private-files roots, publish/verify problem files tools, Cloudflare MCP add-on, Codex MCP setup, Load handling and rollout, Queue modes (local vs database) and roles, Problem authoring standard (making-problems) (+10 more)

### Community 40 - "_Query"
Cohesion: 0.06
Nodes (4): _Query, _RetryClient, _RetryUpdateClient, SubmissionStoreRetry

### Community 42 - "RequestBoundaries"
Cohesion: 0.22
Nodes (3): RequestBoundaries, app(), exercise()

### Community 43 - ".connection"
Cohesion: 0.08
Nodes (18): FatalGateway, Gateway, heartbeat(), receive(), update_presence(), gateway_url(), get_json(), health_ok() (+10 more)

### Community 44 - "os"
Cohesion: 0.07
Nodes (14): main(), append_reservations(), main(), records(), main(), _allocate(), identity(), _state_directory() (+6 more)

### Community 45 - "tests_hash"
Cohesion: 0.12
Nodes (5): tests_hash(), manifest_for_problem(), SubmissionIntegrity, seed_fake(), import_one()

### Community 46 - "json"
Cohesion: 0.11
Nodes (9): build_archive(), collect_data(), encrypt(), fetch_table(), main(), prune(), public_tables(), read_env() (+1 more)

### Community 47 - "FakeSupabase"
Cohesion: 0.07
Nodes (4): FakeSupabase, AuthRetentionAudit, ProblemLoading, FileBoundary

### Community 49 - "Security release checks"
Cohesion: 0.22
Nodes (10): Email OTP ownership proof, Email verification setup (Thai), Resend SMTP via Supabase Auth, /api/version build_sha256, no_new_privs hardening, Security release checks, CI Workflow, critical-security CI job (+2 more)

### Community 51 - "number_problems.py"
Cohesion: 0.11
Nodes (16): band_for_level(), order_key(), sort_problems(), CatalogNumberMap, read_map(), assign_order(), cmd_assign(), cmd_check() (+8 more)

### Community 52 - "test_critical_database_transport.py"
Cohesion: 0.10
Nodes (4): create_database_client(), WorkerPostgrestClient, WorkerSupabaseClient, DatabaseTransport

### Community 53 - "historyTable"
Cohesion: 0.16
Nodes (19): adminHistoryTable(), apiGetCached(), bindViewButtons(), byPidOf(), historyTable(), loadHistory(), loadMyReports(), loadTaskMine() (+11 more)

### Community 56 - "load_problem"
Cohesion: 0.16
Nodes (14): c(), cmd_info(), cmd_run(), report(), list_problems(), _load_level(), load_problem(), main() (+6 more)

### Community 57 - "judge_runner.py"
Cohesion: 0.38
Nodes (4): _children(), _cleanup_linux(), _descendants(), _runner_env()

### Community 59 - "Newbiegrader online judge"
Cohesion: 0.40
Nodes (3): grader.py judging engine, Newbiegrader online judge, server.py FastAPI app

### Community 60 - "run_bounded"
Cohesion: 0.13
Nodes (5): run_bounded(), _WindowsJob, attach(), controlled(), counters()

### Community 61 - "sandbox_identity"
Cohesion: 0.23
Nodes (3): _chmod_job_path(), sandbox_identity(), CriticalCompilerRoot

### Community 62 - "test_cloudflare_vpc_bridge.js"
Cohesion: 0.20
Nodes (9): assert, fetch(), fs, harness(), path, source, { test }, vm (+1 more)

### Community 63 - "test_email_auth.js"
Cohesion: 0.20
Nodes (9): assert, code, fs, harness(), node(), path, source, { test } (+1 more)

### Community 64 - "setContestEditorOpen"
Cohesion: 0.33
Nodes (11): applyContestDuration(), buildProblemSelect(), contestProblemIds(), nextHalfHourInput(), renderAdminTools(), renderContestProblemPicker(), setContestEditorOpen(), setContestProblems() (+3 more)

### Community 66 - "test_edge_proxy.js"
Cohesion: 0.18
Nodes (6): assert, fs, path, { test }, vm, { webcrypto, timingSafeEqual }

### Community 68 - "router"
Cohesion: 0.16
Nodes (20): badge(), contestStatusBadge(), contestWindowText(), currentRouteRender(), durationText(), isUnconfiguredMessage(), loadSubmission(), _nav() (+12 more)

### Community 71 - "test_removed_leaderboard.js"
Cohesion: 0.20
Nodes (7): assert, fs, html, path, source, { test }, vm

### Community 72 - "StatementPublishing"
Cohesion: 0.20
Nodes (3): StatementPublishing, import_statement_one(), _upload_many()

### Community 73 - "test_ui_privacy.js"
Cohesion: 0.20
Nodes (6): assert, fs, path, source, { test }, vm

### Community 74 - "ref_node_path"
Cohesion: 0.22
Nodes (7): assert, css, fs, html, path, root, { test }

### Community 75 - "test_problem_loading.js"
Cohesion: 0.25
Nodes (6): assert, fs, path, source, { test }, vm

### Community 76 - "ref_node_assert"
Cohesion: 0.22
Nodes (6): app, assert, fs, pollingCode, { test }, vm

### Community 77 - "ref_node_test"
Cohesion: 0.22
Nodes (6): assert, context, fs, source, { test }, vm

### Community 79 - "_is_admin"
Cohesion: 0.17
Nodes (12): admin_add_admin(), _admin_cache_loop(), _admin_email_valid(), admin_list_admins(), admin_plagiarism(), admin_remove_admin(), _admin_rows_sync(), delete_contest() (+4 more)

### Community 80 - "create_problem"
Cohesion: 0.32
Nodes (4): create_problem(), main(), problem_id(), sync_samples()

### Community 81 - "hashlib"
Cohesion: 0.25
Nodes (8): restore_files(), safe_key(), source_archive(), deadline(), download(), listing(), fixture(), StorageRecovery

### Community 82 - "_sample_rss_mb"
Cohesion: 0.17
Nodes (4): PeakSampler, sample(), _sample_rss_mb(), ExecutionStartupTests

### Community 83 - "SpawnFailureIsNeverAVerdict"
Cohesion: 0.12
Nodes (3): _supervise(), SpawnFailureIsNeverAVerdict, _FakeProcess

### Community 84 - "[[proxy]].js"
Cohesion: 0.48
Nodes (6): backendOrigin(), boundedBody(), EDGE_CACHE_PATHS, isAnonymousGet(), onRequest(), sameKey()

### Community 85 - "import_problems_supabase.py"
Cohesion: 0.17
Nodes (10): _client(), _dry_only(), import_numbers_only(), _local_slugs(), main(), _park_numbers(), _prune_storage(), _upload_object() (+2 more)

### Community 87 - "Newbiegrader SPA index.html"
Cohesion: 0.33
Nodes (6): Newbiegrader SPA index.html, Home view (hero, stats, starter problems), Inline SVG icon sprite, Tasks view (filter bar, tag sidebar), Topbar navigation and auth controls, styles.css

### Community 88 - "IsolationUnavailable"
Cohesion: 0.24
Nodes (9): _empty_group(), initialize(), IsolationUnavailable, _membership(), _number(), _private_directory(), _read(), _verify_workspace() (+1 more)

### Community 89 - "Newbiegrader logo with wordmark (light-mode)"
Cohesion: 0.40
Nodes (5): Newbiegrader brand identity: document, terminal prompt, green check (judged), Newbiegrader logo with wordmark (light-mode), Newbiegrader logo with wordmark (dark-mode, white), Newbiegrader icon (file with terminal prompt and green checkmark), Newbiegrader icon (dark-mode variant)

### Community 91 - "KernelIsolation"
Cohesion: 0.20
Nodes (5): KernelIsolation, playground(), main(), authorize(), main()

### Community 92 - "test_admin_reload.js"
Cohesion: 0.15
Nodes (11): admin, anonymous, assert, fs, harness(), node(), path, regular (+3 more)

### Community 95 - "test_peer_inspection.js"
Cohesion: 0.17
Nodes (10): assert, fs, harness(), load(), loadAppSection(), path, peer, source (+2 more)

### Community 96 - "Dependency licences"
Cohesion: 0.18
Nodes (10): Bundled fonts (`tools/fonts/`), Dependency licences, Direct dependencies (`requirements.txt`), Full production tree (`deploy/host/requirements.lock`), JavaScript, LaTeX packages, Method, Python packages (+2 more)

### Community 97 - "Problem statement template"
Cohesion: 0.67
Nodes (4): Synthetic security canary statement, Problem input validator template, Problem reference solution template, Problem statement template

### Community 99 - "ref_node_vm"
Cohesion: 0.22
Nodes (8): assert, fs, harness(), node(), path, source, { test }, vm

### Community 101 - "test_edge_abuse.js"
Cohesion: 0.20
Nodes (8): assert, fs, key, path, source, { test }, vm, { webcrypto, timingSafeEqual }

### Community 102 - "Auth modal screenshot (dark): signup tab with email and Continue with Google"
Cohesion: 1.00
Nodes (3): Auth modal screenshot (dark): signup tab with email and Continue with Google, Auth modal screenshot (light): login tab with email, password, remember me, forgot password, Continue with Google, Google G logo

### Community 103 - "test_verdict_labels.js"
Cohesion: 0.20
Nodes (9): assert, context, end, fs, path, source, start, { test } (+1 more)

### Community 104 - "Native backend deployment"
Cohesion: 0.22
Nodes (9): Automatic recovery and availability, Discord website presence, Host and resource allocation, Native backend deployment, Session schema and release activation, Staging and activation, Submission startup latency, Watchdog configuration (+1 more)

### Community 107 - "test_editor_gutter.js"
Cohesion: 0.22
Nodes (7): assert, fs, html, path, source, { test }, vm

### Community 110 - "SIL OFL license for Anuphan"
Cohesion: 0.67
Nodes (3): Anuphan font note (PDF wordmark), SIL OFL license for Anuphan, TH Sarabun New font note (GPL with embedding exception)

### Community 112 - "SmokeCredentialBoundary"
Cohesion: 0.39
Nodes (3): Container base image and OS packages, SmokeCredentialBoundary, curl()

### Community 113 - "Public website security qualification"
Cohesion: 0.25
Nodes (7): Browser and API boundary, Dependencies and data, Explicitly retained limitations, Public website security qualification, Revocable sessions, Untrusted code, Worker reliability and monitoring

### Community 114 - "bindEditorKeys"
Cohesion: 0.39
Nodes (8): applyIndent(), bindEditorKeys(), commentToken(), lineRange(), newlineIndent(), setEditorValue(), syncEditorGutter(), toggleComment()

### Community 115 - "turnstile.js"
Cohesion: 0.46
Nodes (7): config(), ensureWidget(), loadScript(), message(), prepare(), reset(), token()

### Community 116 - "session_revocation.sql"
Cohesion: 0.39
Nodes (4): public.auth_session_start(), public.web_sessions, web_sessions_expiry, web_sessions_user

### Community 117 - "fetch"
Cohesion: 0.62
Nodes (6): apiError(), canonicalPath(), emailBotGuard(), fetch(), rateGuard(), sameKey()

### Community 131 - "ref_node_fs"
Cohesion: 0.29
Nodes (5): app, assert, fs, { test }, vm

### Community 133 - "benchmark_hotpaths.py"
Cohesion: 0.43
Nodes (4): cache_burst(), load_functions(), main(), timing()

### Community 134 - "main"
Cohesion: 0.60
Nodes (6): main(), identity(), query(), replace(), start(), value()

### Community 136 - "Revocable website sessions"
Cohesion: 0.40
Nodes (5): Activation and rollback, Backup and restore, Database boundary, Request and logout behavior, Revocable website sessions

### Community 137 - "run_isolated"
Cohesion: 0.60
Nodes (4): run_isolated(), execute(), cancel(), payload()

### Community 138 - "legacy_schema.sql"
Cohesion: 0.40
Nodes (4): profiles, reports, submissions, users

### Community 140 - "bootstrap.sh"
Cohesion: 0.50
Nodes (3): DEBIAN_FRONTEND, bootstrap.sh script, UV_PYTHON_INSTALL_DIR

### Community 143 - "HOST_CLOUDFLARE_SETUP.md"
Cohesion: 0.50
Nodes (3): API abuse protection, Email-request bot verification, Private Cloudflare transport

### Community 144 - "Documentation"
Cohesion: 0.50
Nodes (4): Checkpoint records, Documentation, Operating the current deployment, Problems, files and user access

### Community 146 - "Backend backup and recovery"
Cohesion: 0.67
Nodes (3): Backend backup and recovery, Coverage, Recovery rehearsal

## Knowledge Gaps
- **41 isolated node(s):** `DEBIAN_FRONTEND`, `UV_PYTHON_INSTALL_DIR`, `SYSTEMD_PAGER`, `SYSTEMD_PAGER`, `Queue modes (local vs database) and roles` (+36 more)
  These have ≤1 connection - possible missing edges or undocumented components. (Counts symbols only; 903 node(s) total have ≤1 connection when file, concept and rationale nodes are included.)
- **51 thin communities (<3 nodes) omitted from report** — run `graphify query` to explore isolated nodes.

## Suggested Questions
_Questions this graph is uniquely positioned to answer:_

- **Why does `FakeSupabase` connect `FakeSupabase` to `CriticalBackendFiles`, `QueueAdmission`, `unittest`, `ApiE2E`, `judge_test`, `grader.py`, `SupabaseProblems`, `newbiegrader-alert.py`, `.rows`, `tests_hash`, `OptimizationReview`, `PerformanceQuickWins`, `_FakeBucket`, `CriticalPracticeFeedback`, `PreMigrationFallback`, `AuthCookies`, `StatementPublishing`, `ContestPolicyAudit`, `_is_admin`, `AdminManagement`?**
  _High betweenness centrality (0.076) - this node is a cross-community bridge._
- **Are the 23 inferred relationships involving `FakeSupabase` (e.g. with `AdminManagement` and `ApiE2E`) actually correct?**
  _`FakeSupabase` has 23 INFERRED edges - model-reasoned connections that need verification._
- **What connects `DEBIAN_FRONTEND`, `UV_PYTHON_INSTALL_DIR`, `SYSTEMD_PAGER` to the rest of the system?**
  _41 weakly-connected nodes found - possible documentation gaps or missing edges._
- **Should `CriticalBackendFiles` be split into smaller, more focused modules?**
  _Cohesion score 0.09494949494949495 - nodes in this community are weakly interconnected._
- **Why does `SmokeCredentialBoundary` connect `SmokeCredentialBoundary` to `json`?**
  _High betweenness centrality (0.054) - this node is a cross-community bridge._
- **Should `QueueAdmission` be split into smaller, more focused modules?**
  _Cohesion score 0.06015037593984962 - nodes in this community are weakly interconnected._
- **Should `unittest` be split into smaller, more focused modules?**
  _Cohesion score 0.08037974683544304 - nodes in this community are weakly interconnected._