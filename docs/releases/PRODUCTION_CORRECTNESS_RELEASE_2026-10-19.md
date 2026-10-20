# Production correctness/cache deployment — 2026-10-19

Status: **DEPLOYED and accepted after explicit operator approval**. The original
`perf/local-mirror-two-workers` working tree is preserved. This release keeps one
worker; it does not deploy the experimental local mirror or two-worker services.

## Current production

| Component | Verified state |
| --- | --- |
| Frontend and same-origin API entry | `https://newbiegrader.pages.dev`, Cloudflare Pages/Function |
| Private route | Pages service binding → `newbiegrader-aws-production` Worker → existing VPC Service/tunnel → loopback Nginx/API |
| Backend | Ubuntu 24.04, x86_64, AWS Sydney **t3.small**, 2 vCPU / nominal 2 GiB |
| Active backend release | `/opt/newbiegrader/releases/f88364747037d800ae1abf3bb799fdde450d7c33` |
| Source artifact SHA-256 | `8b43de1e19148b5eee934e6d14fea553d0e3c8e5072d51f89385bcac569bf170` |
| Pages production deployment | `f826f65a-5f93-49f0-9ca5-4f2d286a2c85`, source commit `f88364747037d800ae1abf3bb799fdde450d7c33`, app.js **v52** |
| Database/auth/queue | Existing Supabase project; durable database queue; existing identity settings |
| Services and limits | API 320 MiB / 25% CPU; singleton worker 1 GiB / 100% CPU; declared submission cap 128 MiB |
| Admissions | Open; exactly one worker; template workers inactive |
| Vercel / JustRunMy | Neither is used for production. JustRunMy's stopped application/retained volume is historical recovery material, not an active fallback. No Vercel deployment was performed. |

Problem files/tests still use the existing Supabase source **at this deployment
checkpoint**. The operator's subsequent request to move file storage to the
backend is a separate migration; do not report that cutover as completed here.
See [current architecture](../PRODUCTION_ARCHITECTURE.md).

## Changes delivered

Implementation: `de34407` backend and `837366c` frontend/proxy, with the exact
review and synthetic benchmark in [the release review](SINGLE_WORKER_CORRECTNESS_CACHE.md).

- Validate each claimed problem version before execution; a mismatch/source
  failure is an infrastructure error, not a contestant verdict.
- Admit submissions from authorized metadata/hash without downloading hidden
  test bytes in the API. Optional queue diagnostics cannot turn a durable
  successful admission into a failed response.
- Invalidate problem caches on metadata updates and read the complete bounded
  catalog. Batch contest registration queries while preserving permissions,
  freeze/ranking behavior and complete registration pagination.
- Prevent credentialed/personalized responses entering the shared edge cache;
  respect origin privacy, Set-Cookie and Vary. Contest responses are private.
- Isolate browser caches and pending requests across identity/navigation changes;
  preserve refresh and pending-verdict invalidation. Keep escaping/Map/date
  optimizations and handle an unknown queue position honestly.
- Allow API-only startup within its existing small service budget while keeping
  worker startup checks fail closed.

Engine, sandbox, feedback policy, schema/RPCs, dependencies, service units,
protected env files, routing, secrets and CPU-credit mode were not changed.

## Executed rollout and verification

1. Scanned the exact source archive. Gitleaks found one heuristic match at
   `docs/audits/PRODUCTION_RELEASE_2026-10-18.md:14`: the adjacent API source
   fingerprint is a 64-character hex digest, not a credential. No other matches.
   AGENTS.md, agent.md, env files, keys, real tests and production data were absent.
   A pattern scan is not proof of absence of every possible secret.
2. Created a new encrypted read-only repeatable-read database snapshot and
   restored it into disposable PostgreSQL with network disabled: **51 table
   content comparisons, 58 relation/ACL/RLS definitions, 150 constraints and
   policies matched**. Removed the disposable container. No source DDL/data
   mutation. The local libpq service file required whitespace normalization
   around `=`; its protected original was retained, values were not changed.
3. Encrypted current API/worker configuration, UID ledger and tunnel state;
   separately encrypted Cloudflare configuration/access-key recovery material.
   Authenticated decryption passed; no secret was printed or put into Git.
4. Captured the original backend and Pages deployment, armed an independent
   20-minute backend rollback timer, paused admission, drained to queued=0 /
   running=0 and stopped the singleton. Queue counters were done=48 / error=0.
5. Staged the verified archive in a new root-owned release directory. Confirmed
   unchanged engine/isolation/worker/dependency hashes. Switched `current`,
   restarted API under paused admission, ran the actual worker `--check` using
   its isolation profile without claiming jobs, then started exactly one worker.
6. First public smoke attempts saw transient **502** after the API restart.
   Loopback API and Nginx returned 200; service OOM counters/restarts remained
   zero. Root cause is **UNVERIFIED**. A subsequent complete **15/15** public
   smoke passed before frontend publication. Do not count failed attempts as
   passing checks or infer a verified tunnel reconnection mechanism.
7. Compiled and deployed the Pages Function/static artifact with pinned Wrangler
   4.151.1. Readback confirmed the target commit and **unchanged** deployment
   configuration, secret names, bindings, compatibility date and Git integration.
8. After publication, anonymous HTTPS smoke passed **15/15**; actual static
   index/JS/CSS SHA-256s matched the release; three contest privacy checks
   (anonymous, synthetic invalid cookie, synthetic invalid Authorization) and
   metadata Vary check passed: **7/7 runtime checks** total. These invalid
   credentials do not simulate two legitimate users. No routing/key change.
9. Reopened admission. In native Chrome, the operator's existing legitimate
   session survived reload. Normal file-upload forms ran new synthetic Python,
   C and C++/STL playground files; all returned the exact expected marker.
   Observed end-to-end times: 8.64 / 5.63 / 9.11 seconds; runner wall times:
   0.2099 / 0.1923 / 0.1884 seconds. This is a functionality check, not a latency
   benchmark. Editor drafts were not replaced with test source.
10. Submitted a new intentional `#error RELEASE_SYNTHETIC_CE_ONLY` file through
    normal submit/poll. It completed CE and loaded from owner history. Read-only
    DB verification found **one job, attempt=1, exactly one linked submission,
    matching owner, verdict CE**. Hidden inputs were not executed by this file.
11. Final queue: **done=52, error=0, queued=0, running=0**. All four new jobs were
    synthetic. API, singleton worker and tunnel active; no second worker,
    remaining job cgroup/workspace or API/worker OOM. Protected configuration
    unchanged. Accepted the release and stopped the independent rollback timer.

Public HTTP vantage: ordinary curl with normal TLS validation from the macOS
operator network outside AWS VPC through Pages. Browser smoke used the existing
native Chrome profile; no cookie/token was extracted or forged. This round
verified an existing authenticated session, **not a fresh Google/OTP login**.

### Test evidence and limits

- This deployment round: **76/76 JavaScript**, zero skips; Pages Function bundle
  compiled; actual worker preflight passed; repeated public HTTPS 15/15 passed;
  runtime asset/privacy 7/7; four normal authenticated synthetic jobs passed.
- Earlier exact application implementation: Linux ARM64/root Docker **285
  Python run (282 passed, three private-fixture modules skipped)**, **205
  critical passed without skips**. Compilation/DOM/style/plagiarism checks passed.
- Native t3.small qualification: **17/17**, matched-deadline replay **6/6**; see
  [native qualification](TWO_GIB_HOST_READINESS.md) for contained OOM evidence.
- SQL schema is unchanged. Full 68 private reference solutions, live contest
  freeze/rejudge flows, a second real user/account switch, fresh Google/OTP,
  sustained load and CPU-credit exhaustion were not tested during rollout.
- S04 per-test descendant-memory verdict accounting remains open. Fixed aggregate
  safety containment is not a complete declared-memory verdict implementation.
- Network-namespace fallback warnings remain visible in custom playground stderr;
  mandatory seccomp/Landlock controls were not disabled. Existing native network
  canaries passed; this rollout did not modify isolation.
- Synthetic cold-admission p95 previously worsened despite fewer database/storage
  requests; no production speedup percentage or throughput guarantee is claimed.

## Recovery artifacts

Protected local directory: `~/.local/share/newbiegrader-private/single-worker-deploy-9be206b08a/`.
Remote protected controller/evidence:
`/var/lib/newbiegrader/maintenance-reports/release-f883647/`.
These contain no public distribution of credentials; do not copy their private
contents into documentation or a public repository.

- Database: `20261019T105234Z-postgres-snapshot.dump.age`, **795645 encrypted
  bytes**, dump 11.1 s; matching encrypted manifest and actual disposable restore
  comparison passed. Logical/table recovery is not hosted Auth/Storage recovery.
- Configuration/UID/tunnel before rollout: `20261019T105308Z-96bc69be.tar.age`.
  After the four canaries: `20261019T110914Z-6a6637c1.tar.age`; authenticated
  decryption passed for both. Keep the newer UID ledger, including allocations
  after rollout.
- Cloudflare: `cloudflare-recovery.tar.age` in the protected rollout directory;
  project metadata plus existing access-key/config recovery, decryption verified.

## Application rollback

Previous AWS backend:
`/opt/newbiegrader/releases/6cba18c68366993fed7fc7572c87368bbb773ea9`.
Previous Pages production deployment:
`d1b73f7f-f68e-46f7-8e3c-2cefc6482305`.

For an approved rollback:

1. Set only API admission to zero using a protected maintenance overlay; restart
   API and freshly drain queued/running jobs. Let existing jobs clean up normally.
2. Stop the singleton. Atomically repoint `/opt/newbiegrader/current` to the
   recorded previous AWS release; restart API/worker under paused admission.
   Run worker preflight and verify health/queue/isolation before reopening.
3. Roll Pages back to the exact previous **production** deployment through the
   Cloudflare Pages dashboard/API. Preserve current private bindings/keys; Pages
   rollback does not restore project configuration or database contents. See
   [official Pages rollback](https://developers.cloudflare.com/pages/configuration/rollbacks/).
4. Verify one worker, authentication/privacy and controlled synthetic completion,
   then reopen admission. Keep current UID reservations and durable job records.

Do not revive JustRunMy, reset the UID ledger, delete jobs, restore an older DB
snapshot over production, enable worker2 or change instance/credit mode as part
of application rollback. No manual application rollback was needed in this run.
