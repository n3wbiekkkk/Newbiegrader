# Production release verification — 2026-10-18

Later runtime-hardening checkpoint: engine **2.0.6**, deployed backend commit
`6d7ba08`; see the follow-up at the end of this file. Earlier 2.0.4 facts below
remain historical evidence, not the current backend version.

This checkpoint supersedes the **not deployed / host unverified** statements in
JOB_ISOLATION.md and PRACTICE_RELEASE.md. It does not close the remaining security
findings or establish readiness for unrestricted public submissions.

## Released artifacts

- Backend: `83e5c2a71e2280bdc01585f7534a8fa7f22c16b8`, engine **2.0.4**.
- Source fingerprint, identical in the clean local image and live API:
  `489ba62dc55cbba35194a7437653efafb289e7a9b4bb81b325f82a19964d08ec`.
- GitHub main was already merged as `57b0be6`; its tree exactly matched the tested
  commit. No second merge or frontend push was necessary.
- Live Pages assets match the tested files byte-for-byte: `app.js?v=43`,
  `styles.css?v=24`. The browser successfully loads the homepage and proxied API.
- All **68** live suite hashes match the approved publication manifest;
  **1,178** active cases. No problem-data or database-permission change this run.

## Actual host evidence — CONFIRMED

Read-only operator probes ran through the official JustRunMy MCP in app `69356`
(`grader`, HTTPS port 8000), before deploying application code.

- Linux x86_64, kernel `6.12.95+deb13-amd64`, Python 3.11.15, root supervisor.
- Landlock **ABI 6**; a bounded child successfully drops supplementary groups,
  GID and UID to 1,000,000. The allocator's entire UID/GID range is mapped.
- No named container accounts/groups occupy that range. PID 1 is the application
  supervisor. Namespace IDs were recorded; no host-side namespace comparison was
  available. This does **not** prove host-wide UID reservation or isolation from
  other tenants using the initial user namespace; provider confirmation remains
  needed.
- Effective/bounding capabilities `00000000a80425fb` exclude CAP_SYS_ADMIN;
  seccomp filtering is active (mode 2). The exact provider profile and privileged
  setting were not exposed by its MCP. No capability/security option was added.
- No `/app/.env`, Docker socket or secret-file volume observed. Credential
  presence was checked by **name only**: SUPABASE_URL, SUPABASE_KEY,
  SESSION_SECRET, GOOGLE_CLIENT_SECRET. Values were not printed or committed.
- Child network-namespace creation fails. Existing production settings were
  `GRADER_REQUIRE_NETNS=false`, `GRADER_ALLOW_UNISOLATED_JUDGE=true`; unchanged.
  Filesystem/identity isolation is verified separately, not network isolation.
- Actual cgroup: 512 MiB memory, 0.5 CPU, pids.max 38,451. New scheduler reports
  one worker/test at a time, declared memory cap **85 MiB**, reserve 170 MiB,
  estimated job budget 340 MiB. These are not per-job process-tree guarantees.

## Persistent identity state — CONFIGURED AND VERIFIED

Initially the provider listed no persistent volumes. Added volume `65068` at
`/var/lib/newbiegrader`, then recreated the existing container to attach it.
The trusted allocator created root-owned `sandbox-identities/` (0700) and
`allocated-uids` (0600), reserving UID 1,000,000 without executing a submission.

After backend deployment recreated the container, the ledger's original digest
was unchanged and the next trusted allocation returned **1,000,001**. The parent
was still a mount point. This verifies persistence across that replacement;
it is not a backup/restore or provider disaster-recovery test. Never delete,
reset, or restore an older ledger while old processes/files can survive.

Before the initial restart, durable queued/running counts were both zero and no
judge child process was observed. The local in-memory queue was not introspected;
this was **not** proof of an atomic admission lock or full local-queue drain.
The maintainer had confirmed there were no current users and authorized release.

## Verification performed this run

- Clean packaged image, disposable Linux arm64/root, Python 3.11, 0.5 CPU,
  512 MiB, network none: **48 tests passed, zero skips**, 18.277 seconds.
  Includes compiler, cross-job identity/filesystem, practice feedback and
  contest/hidden-data redaction tests. Initial harness discovery failed because
  `/app` was absent from PYTHONPATH; fixed the external harness and reran all 48.
- Seven bounded synthetic canaries passed both in that image and on the real
  production host: Python/C/C++ STL accepted; compiler denied a synthetic
  root-only header; runtime denied a synthetic world-readable file outside its
  workspace; failed practice I/O available; reveal-none canary absent.
  Used an operator process with database initialization disabled, not real user
  jobs. **Zero database writes and zero real user submissions** in these probes.
- Node polling/feedback tests: **16 passed, zero skips**; JS syntax, DOM/icon
  references and style-token guards passed.
- Full suite rerun in disposable Linux arm64/root/Python 3.11, 2 CPU / 1,536 MiB:
  **272 passed, zero skips**, 102.491 seconds. The initial run had one harness
  error because `supabase/schema.sql` was not mounted; added that read-only
  fixture and reran the entire suite. No application/test assertions changed.
  Offline package/reference validator **68/68 passed**; plagiarism self-test
  **4/4 passed**; Python byte compilation passed. These larger-container tests
  are not production load tests.
- Direct backend and normal Pages browser GETs: health/version **200**,
  anonymous admin **403**, job/history **401**, private sample path **404**.
  Pages Python-client GETs intermittently returned **403**; normal browser GETs
  passed, including asset SHA-256 checks. Their cause is unverified; do not
  misclassify those edge responses as backend authorization evidence.
- GET vantage: audit Mac's current network; public IP/network category unknown.
  Direct backend reachability is confirmed **from this vantage only**.

Private evidence: `~/.local/share/newbiegrader-validation/production-preflight-zo1po1pe/`
and filtered provider records under `~/.local/share/newbiegrader-private/`.
Credentials remain outside the repository with owner-only permissions.

## Remaining risks and recovery

- **S04:** no per-job hard aggregate memory/pids/CPU/workspace bound. The large
  container PID ceiling and network access remain material public-host risks.
- **S05:** identity ownership/pre-hijacking remains open.
- **B08:** production still uses combined/local queue; restart durability and
  multi-replica coordination are not established. No queue-mode cutover occurred.
- Host UID reservation, exact container security profile, network egress controls,
  backups/restores and stable performance under hostile load remain unverified.
- Practice data deliberately disclosed to its owner cannot later become secret
  merely by using the same problem in a contest.
- Prior provider image ID **96852** was recorded before deployment. An approved
  incident rollback may select that image and restart, retaining the persistent
  volume/ledger. It restores known older security behavior: do not call it a
  security fix. No rollback was executed, no image/volume/data was deleted, and
  no production environment value was changed.

Next priority: enforce and test hard aggregate limits for every judge job (S04),
then resolve the remaining public-host gates before accepting untrusted traffic.

## Runtime hardening follow-up — production VERIFIED

- `b1531ba`: `grader.py:787` refuses Linux/root launch when any required rlimit
  fails; `tests/test_critical_resource_setup.py:18` covers 14 injected failures.
  CONFIRMED corrected setup path; **S04 aggregate enforcement remains OPEN**.
- `6d7ba08`: `job_sandbox.py:195`, `grader.py:872`, `server.py:825` add mandatory
  inherited network syscall filtering and fail-closed worker startup. Compiler
  and runtime denied network endpoint creation in synthetic canaries even with
  netns unavailable. Anonymous Unix stream pairs remain for local IPC/asyncio.
  No namespace, capability or privileged setting was added.
- Production now reports **2.0.6**, code fingerprint
  `9d693b95bc193fdf23a5957fd9942df6118387c773b403cc8406f872921d4e86`.
  Eight synthetic operator canaries passed on actual x86_64 / Landlock ABI 6:
  Python/C/C++ STL, private-header/outside-file denial, practice/contest policy,
  and socket creation denial. No real user workloads or database writes.
- Actual volume remains mounted; state directory/ledger root-owned 0700/0600
  and nonempty. memory.events reported zero OOM kills at observation, not a
  hostile-load containment result. No credential values were exposed.
- PR #8 passed all GitHub checks and merged as `bd246eb`. Backend deployment
  used the tested `6d7ba08` source. The prior image for incident review is **96894**;
  retain the identity volume/ledger if rollback is needed. No rollback executed.
- `83493ad` adds idle/outage queue backoff (`server.py:1114`, regression
  `tests/test_queue_admission.py:31`) and accurate README guarantees. It is
  prepared for the future database-mode rollout; production remains **local**.
  The subsequent repository code fingerprint is
  `70caa654913a07aada6ac6d59d04cac501e2bf62e1f0e38ee8fea0cc9bc46ff6`;
  do not confuse that with the deployed network-release fingerprint above.
- Final local full suite **283 passed, zero skips**, 105.627 s; critical **143
  passed, zero skips**, 25.188 s; Node **34 passed**; validator **68/68**;
  byte compilation/plagiarism passed. Final clean image at 0.5 CPU / 512 MiB
  also passed all eight canaries. No security assertion was disabled.
- Disposable PostgreSQL 17: schema twice and queue/security SQL assertions pass;
  four actual concurrent consumers produced one claim; expired lease recovered
  and stale attempt refused. Production RPC bodies/privileges match, and the
  backend's diagnostics call returned 200 with zero queued/running rows.
  See QUEUE_ROLLOUT.md; zero durable rows is not an atomic local drain.
- S05 still OPEN. Three legacy password accounts were counted without printing
  identities/hashes. Maintainer confirmed no mail provider; SMTP/OTP setup and
  migration acceptance criteria are prepared in `docs/EMAIL_VERIFICATION_SETUP.md`.
  No email was sent, provider configured, account migrated or production schema
  changed. Existing accounts must not be auto-marked verified.

Primary remaining gates: provider-supported aggregate job/storage bounds,
verified email plus legacy session migration, and actual pause/drain before
database-queue cutover. Remaining session/replay, healthcheck, backup/restore,
retention, contest-query budgets and static-header work is not claimed complete.

Private evidence: `~/.local/share/newbiegrader-validation/runtime-enforcement-hlp2u8fm/`.
