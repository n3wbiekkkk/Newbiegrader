# Newbiegrader production readiness — 2026-10-18

## Release decision

**Do not open unrestricted public judging yet.** The existing architecture can
be retained. Small local corrections close several confirmed defects, but kernel
isolation and identity ownership remain launch gates. Initial audit work made no
production changes. After explicit approval, S01 permission SQL was applied and
verified in production; no application data, push or deployment was performed.

See [security findings](SECURITY_AUDIT.md) and [correctness/operations findings](BUG_AUDIT.md).
Status is scoped: a local regression pass is not a verified production rollout.

## Top 10 by realistic impact

| Rank | Finding | Severity / evidence | Current disposition |
| --- | --- | --- | --- |
| 1 | S01 anon view access bypasses protected RLS | High, production CONFIRMED | Fixed and verified in production after approval, 02:18 UTC |
| 2 | S03 equal UID reads/writes other job source | High, synthetic CONFIRMED | Per-job UID + Landlock fixed locally; production provisioning/rollout unverified |
| 3 | S04 parent-only memory and wrong runtime budget | High, mechanism CONFIRMED; OOM LIKELY | Runtime scheduling arithmetic fixed locally; aggregate containment open; 512 MB production host reported |
| 4 | S05 unverified-email pre-hijacking | High, synthetic CONFIRMED | Open; provider verification fix is only partial |
| 5 | S02 root chmod via substituted paths | High, synthetic CONFIRMED | Fixed locally, not deployed |
| 6 | S06 contest authorization fails open on outages/schema gaps | High, synthetic CONFIRMED | Fixed locally, not deployed |
| 7 | S07 parser vulnerabilities/unbounded request parsing | High, requirements and boundary CONFIRMED | Upgraded/bounded locally; production versions unknown |
| 8 | B08 local queue best-effort durability | High reliability, mode/fallback CONFIRMED | Existing DB queue not rolled out |
| 9 | S09 handoff token access logs/replay after restart | Medium, local logging path CONFIRMED | Uvicorn filtering/lock fixed; upstream logs/shared replay open |
| 10 | B01/B03/S12 frozen scores, unpublished metadata and private stats through other routes | Medium, synthetic CONFIRMED | Fixed locally, not deployed |

S13 now has a local fix for hidden data echoed through public test feedback;
it still needs release before higher concurrency/noncanonical test ordering.
Earlier stderr leakage is covered by existing regressions and is not ranked
above a demonstrated cross-job filesystem read/write route. Current Supabase
source does not place hidden tests on a local disk cache. A future readable
local-test mount would provide a more direct leak than stderr (conditional,
not demonstrated on production). No direct compiler-root execution is asserted.

## Prioritized plan

### P0 — before unrestricted public launch

1. **Completed after approval:** applied the scoped server-only permission
   migration below; verified anon/authenticated cannot read either view or direct
   problem metadata, while service_role access remains available.
2. Review and release local S02/S06/S07 fixes with the recorded gates. Dependency
   updates are substantial parser changes and need a staging smoke test before
   production approval, despite the offline suite passing.
3. S03 has a tested local UID/filesystem correction; provision and verify it as
   documented in [JOB_ISOLATION.md](JOB_ISOLATION.md). Enforce aggregate memory/pids
   and bounded workspace bytes, and budget actual language/compile ceilings (S04).
   Keep concurrency one until safe overlap is verified; one worker alone is not
   a security proof. Do not grant privileged/CAP_SYS_ADMIN to make a probe pass.
4. Verify runtime network posture and secret/mount isolation on the real host;
   use a properly restricted execution boundary or dedicated worker network.
   Compiler egress also needs consideration, not only runtime netns.
5. Close unverified-email identity ownership (S05), including account linking and
   existing-session migration. Until then avoid trusting account quotas or
   contest ownership as abuse-resistant.
6. Rehearse the existing database queue and approved cutover (B08); ensure accepted
   work is durably admitted and history/finish commit together. Correct the
   README durability promise if local fallback remains an intentional dev mode.

### P1 — soon after gates / before larger contests

- Release B01–B07/O01 fixes; independently smoke-test rejudge and plagiarism with
  synthetic records, never bulk-rejudge real rows during verification.
- Shared atomic login replay state before replicas; upstream auth-query log
  redaction; session revocation policy (S09/S10).
- Worker/custom-port healthcheck (O02), stuck-job/lease alerts and graceful drain.
- Restore rehearsal and retention budget; distinguish database backup from
  Storage objects and source/problem-version recovery. Do not delete user rows
  automatically as part of this patch.
- Admission/rate-limit verification through the real proxy chain and from direct
  ingress; central rate limiting for multiple replicas. Verified identities and
  per-problem contest query budgets for the verdict oracle (S11).
- Database aggregation for large/final standings, consistent snapshot results,
  count-byte budgets for problem cache/downloads, and bounded retry/backoff.

### P2 — improvements

- Add CSP/nosniff/referrer/frame policy to Cloudflare static responses after a
  browser check; API headers do not cover separately hosted static HTML.
- Pin release image digest/compiler and full dependency lock, immutable CI action
  SHAs; keep audit updates scheduled and assess applicability, not just counts.
- Add schema status/check/FK constraints only after auditing legacy rows; no
  destructive automatic cleanup. Fix remaining doc/environment drift.
- Replace real-problem module-level skips in the wider API suite with synthetic
  fixtures; the critical gate already refuses any skip without private packages.
- Record a complete redacted secret-history scan and incident drill; substring
  commit-history searches alone cannot establish secret absence.

## Recorded validation

Tests ran on Docker Linux arm64 / Python 3.11 / root from an isolated source copy,
with no `.env`, production credentials or network. The development flag
`GRADER_ALLOW_UNISOLATED_JUDGE=1` was used **only inside network-none test containers**.
It is not a public production recommendation. Node checks ran on the audit Mac. The initial audit candidate (before S03/S13) used Python 3.11.17 and
recorded this backend source fingerprint:
`49fc14829584bd6595a2ee2b86deb392c38fd591b800dc99ada823355994c1d1`.
Clean-image inspection found no `/app/.env` or `/app/problems`, and found the
packaged plagiarism module. Production mounted paths remain unverified.

| Gate | Baseline | Final branch |
| --- | --- | --- |
| Full Python suite | 221 passed, 0 skipped (83.744 s) | 242 passed, 0 skipped (86.687 s) |
| Critical Linux/root gate | 81 passed, 0 skipped (18.077 s) | 102 passed, 0 skipped (22.709 s) |
| Critical gate from clean Git archive without private problems | — | 102 passed, 0 skipped (17.441 s) |
| Node tests | 25 passed, 0 skipped | 25 passed, 0 skipped |
| JS syntax / DOM IDs / style tokens | Reviewed existing guards | Passed (140 IDs, 17 icon refs, 87 tokens) |
| Trusted offline problem package/reference checks | — | 68/68 passed, serial, network disabled |
| Packaged plagiarism module | Original Dockerfile omits module | Clean Docker build; packaged self-test 4/4 |
| PostgreSQL 17 | Original schema fails new privilege regression | Schema applied twice; queue and privilege/RLS tests pass |
| Dependency audit | 13 distinct parser advisory IDs; image inventory additionally 7 installer/packaging IDs | No known vulnerabilities in updated requirements **or final Linux image Python inventory** |

Negative-before-positive evidence: three path regressions, source/hash tests,
contest tests, Google verification, JTI capacity, terminal-source/TTL checks
failed before their respective fixes. An intermediate run found a cleanup
regression; it was corrected, not waived. Existing tests are not asserted to
cover all attacks or all production configurations.

Audit evidence/logs are local at
`~/.local/share/newbiegrader-validation/security-audit-8xjiasc2/` (no production
row contents or credentials saved by these tests). Baseline hashes are recorded
there. `review.diff` and ignored `AGENTS.md` are not part of these changes.

### Reproduce the critical gate safely

After committing/reviewing this audit branch, use a clean archive:

```sh
audit_context=$(mktemp -d)
git archive HEAD | tar -x -C "$audit_context"
docker build -t newbiegrader-audit-local "$audit_context"
docker run --rm --network none --memory 1g --pids-limit 256 \
  -v "$audit_context:/app:ro" -w /app \
  -e PYTHONPYCACHEPREFIX=/tmp/pycache -e GRADER_RUNNER_CHILD=1 \
  -e SESSION_SECRET=synthetic-audit-only \
  -e GRADER_ALLOW_UNISOLATED_JUDGE=1 -e GRADER_REQUIRE_NETNS=0 \
  newbiegrader-audit-local python tools/run_critical_tests.py
```

No production container, host Docker socket or home directory is mounted. This
gate runs without the private problem set and exits nonzero on any skip.

## Production permission change — approved, applied and verified

Migration `20261018021803_server_only_data_api_permissions` was applied on
2026-10-18 at 02:18 UTC to project `qblnlfzjublfnnsasgpe`, with 5 s lock and 30 s
statement timeouts. The approved block below was used; historical migrations were
not replayed. No application rows were inserted, updated or deleted.

Verified after commit:

- anon/authenticated have no table or column privileges on all 12 scoped relations.
- Actual SELECT attempts under each role on both views and problems are denied.
- Both views are invoker-rights; reports RLS remains on; direct problem policy is
  removed; Storage bucket remains private.
- Service-role read checks work (counts only, no user data retrieved).
- Both Security Definer View ERROR advisories disappeared. Remaining RLS-with-no-
  policy INFO messages describe the intended server-only deny-default tables.
- GET health/problems/stats/contests still return 200 from the audit Mac's current
  network; network classification remains unknown. Runtime code was not deployed.

Before/after ACLs and migration evidence are saved in the private audit directory
as `production-s01-preflight-20261018T021741.json` and
`production-s01-postflight-20261018.json`. Read-only verification did not exercise
authenticated user submissions or write paths against production.

The following is retained as the exact reviewed scope and recovery procedure.

Apply **only the 2026-10-18 block**, `supabase/schema.sql:480–493`, in a transaction,
after catalog preflight. Do not blindly replay historical schema migrations:
the older full file includes legacy queue updates with a different rollout scope.

Expected effects: deny direct anon/authenticated table/view reads and writes,
keep service-role API operations, make aggregate views invoker-rights, remove
the incomplete direct-problem policy, ensure reports RLS for new installations.
No row deletion or source rewriting. Existing reports RLS in production stays on.

```sql
begin;
alter table public.reports enable row level security;
alter view public.leaderboard_scores set (security_invoker = true);
alter view public.problem_stats set (security_invoker = true);
revoke all on public.submissions, public.profiles, public.reports, public.users,
  public.judge_jobs, public.contests, public.contest_registrations,
  public.contest_announcements, public.judge_quota_events, public.problems,
  public.leaderboard_scores, public.problem_stats from public, anon, authenticated;
grant all on public.submissions, public.profiles, public.reports, public.users,
  public.judge_jobs, public.contests, public.contest_registrations,
  public.contest_announcements, public.judge_quota_events, public.problems to service_role;
grant select on public.leaderboard_scores, public.problem_stats to service_role;
drop policy if exists problems_public_read on public.problems;
commit;
```

Preflight/after verification, read-only, with no row contents:

```sql
begin read only;
select c.relname,c.relrowsecurity,c.reloptions,c.relacl
from pg_class c join pg_namespace n on n.oid=c.relnamespace
where n.nspname='public' and c.relkind in ('r','v') order by c.relname;
select schemaname,tablename,policyname,roles,cmd,qual,with_check
from pg_policies where schemaname in ('public','storage');
select r, v, has_table_privilege(r,'public.'||v,'select') as can_select
from unnest(array['anon','authenticated','service_role']) r
cross join unnest(array['leaderboard_scores','problem_stats','problems']) v;
select id,public from storage.buckets where id='judge-assets';
rollback;
```

Expected after: anon/authenticated `can_select=false`; service_role true; views
`security_invoker=true`; bucket private. Check column grants too, as in
`tests/security_sql.sql`. Safe API GET health/problems/stats/contests must still
work. Authenticated synthetic job/history smoke tests belong on staging.

Rollback: before commit, `ROLLBACK`. After commit, preserve the preflight ACL and
policy output for an exact permission restoration review. **Do not disable
reports RLS or grant public access merely to fix an API service-role issue.**
If an explicitly approved legacy direct client truly requires the previous read
surface, this limited compatibility rollback reopens S01 and is unsafe for launch:

```sql
-- Requires separate approval: intentionally restores the former public leak.
begin;
alter view public.leaderboard_scores reset (security_invoker);
alter view public.problem_stats reset (security_invoker);
grant select on public.leaderboard_scores,public.problem_stats,public.problems
  to anon,authenticated;
drop policy if exists problems_public_read on public.problems;
create policy problems_public_read on public.problems for select to anon,authenticated
  using (is_published=true and hidden=false);
commit;
```

This is not a bit-for-bit ACL rollback: it restores only legacy SELECT, not
unnecessary write grants. Exact old ACL restoration must use the captured
preflight state. Prefer correcting backend role/configuration and keeping
least-privilege permissions closed.

## Missing host evidence: operator read-only commands

Run on the actual backend/worker host. Substitute the real container ID; never
paste `docker inspect` in full or dump `.Config.Env`/`/proc/*/environ` values.

```sh
docker inspect --format '{{.Image}}' CONTAINER
docker inspect --format '{{json .Mounts}}' CONTAINER
docker inspect --format '{{json .HostConfig.CapAdd}} {{json .HostConfig.CapDrop}} {{.HostConfig.Privileged}} {{json .HostConfig.SecurityOpt}}' CONTAINER
docker inspect --format '{{.HostConfig.PidMode}} {{.HostConfig.NetworkMode}} {{.HostConfig.ReadonlyRootfs}} {{.HostConfig.Memory}} {{.HostConfig.PidsLimit}}' CONTAINER
docker inspect --format '{{.State.Status}} {{.RestartCount}} {{json .State.Health.Status}}' CONTAINER
docker exec CONTAINER python -c 'import os,json; keys=["SUPABASE_KEY","SESSION_SECRET","GOOGLE_CLIENT_SECRET","SUPABASE_URL"]; print(json.dumps({k:bool(os.environ.get(k)) for k in keys})); print({k:os.environ.get(k, "<unset>") for k in ["GRADER_ROLE","GRADER_QUEUE_MODE","GRADER_PROBLEM_SOURCE","GRADER_ALLOW_UNISOLATED_JUDGE","GRADER_REQUIRE_NETNS","FORWARDED_ALLOW_IPS"]}); print("effective_uid",os.geteuid())'
docker exec CONTAINER python -c 'from pathlib import Path; import os,json; paths=["/app/.env","/run/secrets","/app/problems"]; print(json.dumps([{ "path":p,"exists":Path(p).exists(),"uid":Path(p).stat().st_uid if Path(p).exists() else None,"mode":oct(Path(p).stat().st_mode&0o777) if Path(p).exists() else None} for p in paths])); print("ptrace_scope",Path("/proc/sys/kernel/yama/ptrace_scope").read_text().strip() if Path("/proc/sys/kernel/yama/ptrace_scope").exists() else "unavailable")'
docker exec CONTAINER python -c 'from importlib.metadata import version; import json; print(json.dumps({p:version(p) for p in ["fastapi","starlette","python-multipart","uvicorn"]}))'
```

These distinguish: (a) explicit unisolated acknowledgement; (b) external
capabilities/privileged/network setup; (c) API-only/no active worker. Current GET
reports **combined**, so API-only would require a different worker/deployment
than the observed process. Also allow for a non-root/dev runtime or different
deployed code; do not force the evidence into only three possibilities.
No `unshare`, process memory reads, metadata-service requests or egress scans
should be run on production for this audit. Verify those with synthetic canaries
in a disposable replica of the host configuration.

Repeat public GETs from the intended external network and record the vantage:

```sh
curl --fail --silent --show-error https://grader.n.onjrnm.vip/api/health
curl --fail --silent --show-error https://grader.n.onjrnm.vip/api/version
```

Uvicorn can process forwarding headers before application policy; also verify
its `FORWARDED_ALLOW_IPS` setting and the actual appended proxy chain. Do not
assume application CIDR checks override an unsafe ASGI-server proxy setting.

Direct backend 200 from the audit Mac proves bypass of the Pages *path*, not an
authorization bypass. Backend still must enforce auth, body limits and rate
limits. Test proxy trust with a synthetic local request matrix, not forged
production login floods. Storage/network/host metadata reachability is unverified.

## Low-cost operational checklist

- [ ] Close anonymous views and verify API-only data access; audit new migrations
  under actual anon/authenticated roles and Supabase default grants.
- [ ] Capture image digest, role, caps, mounts, seccomp, UID, namespace and memory
  evidence; no Docker socket, host filesystem or secrets in submission mounts.
- [ ] Set measured language-aware capacity, per-job pids/memory/disk and deadline;
  reserve API/compiler RAM. Alert on OOM/restart/queue-age before adding workers.
- [ ] Use existing durable queue, lease fence and completion transaction; test
  worker death, retry, duplicate completion and accepted-job recovery on staging.
- [ ] Use trusted proxy CIDRs based on the actual socket peer; reject broad
  trust-all ranges. Confirm direct ingress cannot bypass required controls.
- [ ] Monitor HTTP 5xx/413/429, admission rejection, oldest queued age, job errors,
  retry/lease expiry, container RSS/pids/disk and Storage failures. Existing admin
  diagnostics plus host counters are sufficient initially; no paid stack required.
- [ ] Ensure logs contain no auth query values, source, stdin, expected output or
  credentials at app, host, proxy and collector layers; set bounded log retention.
- [ ] Keep recovery copies of PostgreSQL schema/data **and** private Storage
  objects/problem versions. Record RPO/RTO and a successful disposable restore.
- [ ] Document secret owners and rotation order: service-role key, Google client
  secret, SESSION_SECRET and deployment credentials. Rotate only with approval;
  never expose values in commands/logs. SESSION_SECRET rotation logs everyone out.
- [ ] Budget dominant costs: Supabase API/RPC polling, Storage cold-download egress,
  retained source/results/object versions and compile/worker CPU/RAM. Track counts
  and bytes first; caching/backoff reduces requests but must preserve authorization.
  No exact price estimate without usage/plan evidence.
- [ ] Emergency: block new submit/run/rejudge admissions at **backend ingress and
  edge**, drain or intentionally stop workers, preserve job status/leases and
  logs, then recover using mode-specific rules. Edge-only blocking is insufficient
  because direct backend access was observed. There is no verified maintenance
  toggle; do not invent one or set QUEUE_MAX=0 without checking its clamp.
- [ ] Keep an approved rollback image/config and release branch; rehearse rollback
  on staging. No automatic destructive database rollback or deletion of history.

## First three execution tasks and acceptance criteria

1. **Completed: close production Data API exposure with approved scoped SQL.** Acceptance:
   catalog shows no anon/authenticated table/column SELECT on views/problems;
   invoker flags true; service-role API health/problems/stats/contests work;
   before/after ACL snapshots retained; no data changed; security advisor errors
   for the two owner-rights views disappear.
2. **Establish a real per-job isolation and resource boundary.** Acceptance:
   overlapping synthetic jobs cannot read/write/signal each other; compiler and
   descendants never root; effective net isolation verified without privileged
   mode; parent+child memory, pids and workspace bytes enforce limits; one abusive
   job cannot invalidate a simultaneous benign verdict; host survives bounded tests.
3. **Repair identity ownership, then release the reviewed patch via staging.**
   Acceptance: attacker registering a victim email without ownership gets no
   victim identity; first verified Google login cannot inherit attacker credentials;
   existing-account/session migration and rollback reviewed; critical suite has
   zero skips, staging auth/submission/history/rejudge checks pass; durable queue
   restart/duplicate-finish rehearsal passes before public admission.

## Local rollback

No remote action is needed to abandon this branch: return to the previous branch
after preserving unrelated working files. To undo selected committed audit fixes,
use `git revert <audit-commit>` in reverse dependency order and rerun gates.
Do not reset main, delete `review.diff`, rotate credentials or deploy as part of
local rollback. Production migration rollback is a separate approval above.

Local implementation commits (oldest first):

- `7864a27` — refuse symlink targets during runtime permission setup.
- `bcb0ca1` — server-only relation permissions and real PostgreSQL ACL gate.
- `f0028bc` — patched parser/build dependencies and packaged-image audit/checker.
- `d160662` — request/auth/contest boundaries, source/hash and memory retention.

Concrete implementation rollback on a review branch (intentionally restores
the old flaws; does not revert any production permission change):

```sh
git revert d160662 f0028bc bcb0ca1 7864a27
```

The report-only commit can remain for the evidence trail. `main` still points to
`3014da34992cebcf7b5d00c303944accf12852da`. No commits were pushed.

**Single next action: fix aggregate resource accounting and the Python-aware
capacity budget (S04), then verify hard limits on the intended worker runtime.**

## Local isolation follow-up status

Branch `fix/p0-job-identities`, base `cc2106a`: S03 per-job UID/GID + mandatory
Landlock correction is commit `b982100`. S13 separately adds a sample/hidden
execution barrier, retains hidden parallelism and increments engine semantics
to 2.0.1. See [JOB_ISOLATION.md](JOB_ISOLATION.md) for UID ledger persistence,
reserved-namespace/range, kernel requirements and recovery cautions.

Combined final gates: critical 117 passed, no skips; full suite 257 passed, no skips (89.718 s); Node 25 passed; trusted reference packages 68/68 passed; byte compilation
and frontend guards passed. These are local Docker checks, not a GitHub Actions
run or a production smoke test. No deployment/push or production mutation was
performed in this follow-up. S04, S05, network/IPC and host provisioning remain open.
