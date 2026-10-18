# Production release verification — 2026-10-18

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
