# Email identity remediation — deployed, live OTP verification pending

2026-10-18 · Branch `fix/verified-email-auth` · Base `9385811`.

**S05: High, CONFIRMED in the prior synthetic reproduction. The correction is
deployed; final real end-to-end OTP verification remains OPEN.** The operator
approved the reviewed production migration, Auth configuration and release.
The sections below retain local test evidence and the planned rollout gates;
the production checkpoint at the end records which gates have actually passed.

## Changes and evidence

| Path | Change / root cause addressed |
| --- | --- |
| `server.py:2043` | Signup/recovery requests email proof and returns 202; does not reserve `public.users`, retain a chosen password, or grant a user session. |
| `server.py:2067` | A signed, 10-minute email challenge plus a successful provider OTP check precede setting a newly chosen password. Provider subject is bound transactionally. |
| `server.py:2103` | Legacy unverified passwords cannot authenticate; recovery requires inbox proof. Existing verified-password login remains available. |
| `server.py:1594`, `server.py:1611` | Every route receives only a currently verified identity with matching DB version. Old unversioned sessions are refused; DB failure closes protected access. Logout remains available. |
| `server.py:1736`, `server.py:1786` | Remember restoration and OAuth handoff recheck current identity/version. Signing salts change to reject older remember/handoff tokens. |
| `server.py:1692`, `supabase/schema.sql:612` | Trusted Google claim pins a subject and clears any unverified legacy password. A verified password account is not automatically linked by matching email. |
| `email_auth.py:68` | Stateless server-to-server adapter checks email, confirmation and UUID subject; provider tokens/error bodies never reach application cookies/responses/logs. Redirects and insecure transport are refused. |
| `server.py:2024`, `supabase/schema.sql:523` | Shared transaction-based send/guess budgets across API replicas, separate from existing in-memory password flood limits. No plaintext email/code in the budget table. |
| `static/app.js:1649`, `static/index.html:337` | Existing form gains request/verify/recovery steps; no preselected signup password is sent. Explicit remember opt-in remains. Asset is `app.js?v=45`. |
| `supabase/schema.sql:496` | Add four identity columns, two unique subject indexes, a private RLS budget table, three invoker RPCs restricted to `service_role`. Existing history owners and user rows are not rewritten. |

### Current budgets

- Requests: one per email per 60 seconds, five per email per hour, 50 per effective
  network per hour, 100 globally per 24 hours (initial Gmail test sender).
- Verification attempts: eight per email / 15 minutes, 100 per effective network /
  15 minutes, 1,000 globally per hour. Windows start on first admitted attempt.
- A mail/provider failure still consumes budget. This avoids using failures to
  bypass controls. Fixed windows do not guarantee a rolling long-window bound.
- With unconfigured trusted proxies, one proxy may appear as a shared network;
  this can limit a class together. Do not trust arbitrary forwarding headers.
- Direct Supabase Auth requests can bypass the application's budgets: keep
  provider-side rate limits and plan CAPTCHA before public signup. A publishable
  key is not an access-control secret. No claim of comprehensive bot protection.

## Tests actually run

Host: Apple Silicon macOS; Python tests in Linux aarch64 Docker, Python 3.11,
root/default container capabilities, external network disabled. No privileged
mode, real user submissions, live OTP verification or production mutation.

- Clean baseline: auth 13 passed; critical 143 passed, zero skips; full discovery
  213 ran, three module skips.
- Candidate: full discovery 235 ran, **232 passed / three module skips**;
  critical **165 passed / zero skips** (includes 22 synthetic email/identity tests).
- New tests include legacy takeover prevention, no identity on pending signup,
  mailbox-bound proof, bad/expired/replayed codes, concurrent consumption with a
  synthetic single-use provider, stale session/remember/handoff revocation,
  real application middleware order, Google subject policy, missing migration /
  provider configuration, outages, normalization and CSRF.
- JavaScript: 40 passed, zero skips; six new auth-form regressions. Syntax,
  frontend ID/icon guard, style token guard and Python byte compilation passed.
  Packaged plagiarism self-test passed 4/4; problem validator explicitly skipped
  because private `problems/` was absent (no claim of validating 68 packages).
- PostgreSQL 17 disposable container: schema applied twice; `auth_sql.sql`,
  `queue_sql.sql`, `security_sql.sql` passed. Eight independent SQL clients:
  same-email sends had exactly one winner; concurrent same-Google-subject claims
  created exactly one identity at version 1.
- Packaged Docker image built successfully; all 22 email regressions passed
  against packaged modules with synthetic tests mounted read-only.
- Playwright: actual local SPA at desktop and 390px mobile, API responses mocked;
  request opens OTP/new-password fields and locks email, one request issued,
  no horizontal overflow observed, zero actual emails sent by that browser test.
  Screenshots are local evidence, not production screenshots.

Skipped modules: `test_api_e2e`, `test_judge_limits`, `test_problems_supabase`,
all because private `problems/` is absent from the clean snapshot. Their fixture
login helpers were adapted to seed explicitly verified synthetic identities;
those private-problem suites have NOT been rerun in full in this step. Three
selected existing API auth cases (account rate limits, remember restoration /
logout, cookieless CSRF) additionally passed against the synthetic package. The
first compatibility harness imported the app with Secure cookies then used HTTP;
that harness mismatch was corrected by setting local HTTP cookie configuration
before import, without relaxing assertions or changing application code. The critical
identity tests do not depend on those skips or on private problems.

The provider's real single-use/expiry behavior is not proved by a mock. A real
operator-owned OTP verification test remains a rollout gate, with no OTP/link
printed or sent through chat.

## Rollout gates and reviewable SQL

1. Review the appended block beginning `-- 2026-10-18: verified email identities.`
   in `supabase/schema.sql`, including ACLs and budgets. Maintainer approval and
   database backup are required before applying it through SQL Editor.
2. Check legacy count and canonical-email collisions without returning accounts:

   ```sql
   select count(*) as accounts from public.users;
   select count(*) as noncanonical_emails from public.users
     where email <> lower(btrim(email));
   select count(*) as duplicate_canonical_groups from (
     select lower(btrim(email)) from public.users group by 1 having count(*) > 1
   ) q;
   ```

   Stop on noncanonical rows or collisions; do not bulk relabel ownership.
   Do not mark existing rows verified. Do not log/export hashes to the terminal.
3. Put the project's publishable key in backend `SUPABASE_AUTH_KEY`; retain the
   separate service-role client for DB operations. SMTP App Password stays only
   in Supabase. Never put either provider credentials or service-role keys in SPA.
4. Change both Magic Link and Confirm Sign Up templates to
   `tools/templates/auth/email_otp.html`, set OTP
   expiration to 600 seconds, keep minimum resend >=60 seconds and provider limits.
   The delivery test alone did not establish that these settings were applied.
5. After a reviewed release, all existing sessions must sign in again. The three
   previously observed legacy password accounts need inbox proof and newly chosen
   passwords; their history keys stay unchanged. Reserved admin addresses use
   trusted Google login or an operator-reviewed recovery path, not public signup.
6. Deploy backend before frontend. Until frontend deployment, the older signup UI
   does not understand 202/pending; schedule a short maintenance window instead of
   advertising uninterrupted signup. No deployment is authorized by this document.
7. Verify the full real OTP flow using only an operator-owned test account, then
   reject bad/reused/expired codes and old cookies without printing them. Check
   no-store responses and the public proxy path. Real Google OAuth is not rerun
   by the synthetic tests above.

### Remote verification follow-up

The first final preflight was refused with “MCP authentication required”. On
2026-10-18 the operator requested `codex mcp login supabase`; OAuth reconnection
completed successfully without adding a duplicate server or changing project
scope. The existing MCP tools then returned the correct project URL and actual
read-only counts: **3 accounts, 0 noncanonical emails, 0 duplicate canonical-email
groups**. No account values or hashes were returned. No production writes occurred.
This resolved the MCP blocker. The subsequently approved rollout is recorded
below; these counts describe the pre-migration checkpoint.

Safe post-migration metadata checks (read-only, no account values):

```sql
select count(*) filter (where email_verified_at is null) as unverified,
       count(*) filter (where auth_version > 0) as versioned from public.users;
select has_table_privilege('anon','public.auth_rate_buckets','select') as anon_read,
       has_function_privilege('authenticated',
         'public.auth_email_complete(text,uuid,text,text)','execute') as public_claim,
       has_function_privilege('service_role',
         'public.auth_email_complete(text,uuid,text,text)','execute') as backend_claim;
```

Expected: existing accounts remain unverified immediately after migration;
`anon_read=false`, `public_claim=false`, `backend_claim=true`.

## Remaining risk and rollback

- No explicit Google/password linking UI is added. A verified password account
  without that Google subject must use password/OTP; matching email alone is
  refused. A Google third-party email without authoritative hosted-domain proof
  must use inbox OTP. Google email changes/subject conflicts need manual review;
  they never silently move historical ownership.
- One uncached identity lookup per authenticated request adds DB traffic/latency;
  this is the cost of immediate credential-version checks in the current design.
  Password attempt buckets remain in-memory; logout still cannot revoke a stolen
  current-version stateless cookie. Cross-replica OAuth handoff replay remains a
  separate known issue. This patch does not claim to fix all session risks.
- Provider tokens are discarded locally, but Supabase may retain Auth session/user
  metadata; configure provider retention as an operations task.
- Gmail remains a limited testing sender. Domain-backed transactional delivery,
  provider abuse controls and recipient diversity remain production gates.
- Hard aggregate judge resource isolation (S04), durable queue cutover (B08),
  backups/recovery and the rest of the audit remain outside this auth patch.
- Before any release, local changes can be discarded by switching to the previous
  branch after preserving desired work:

  ```sh
  git switch fix/p0-runtime-enforcement
  ```

  This switches back to the previous local checkout without rewriting commits.
  After release, pause authentication before
  rollback. Preserve added identity columns, hashes and versions: reverting to old
  auth code reopens S05 and must not be used as an unattended recovery procedure.
  No production rollback or deletion of identity data is proposed automatically.


## Approved rollout preflight: provider OTP length

The production dashboard showed **8-digit OTPs**, not the 6 digits assumed by the
candidate. A new synthetic regression failed against the six-digit API (HTTP
400), then the API, form validation, HTML limit and synthetic fixtures were
aligned to eight digits. Provider length was preserved; it was not reduced.
The dashboard was reloaded after saving and showed expiry **600 seconds** and
length **8**. Both Magic Link and Confirm Sign Up templates must use the reviewed
OTP body: upstream `auth/internal/api/magic_link.go` signs up new/unconfirmed
users through the confirmation path (lines 77–119); changing only Magic Link
would leave first-time users receiving a link instead of the code form expects.

After this compatibility correction, Linux/root synthetic critical tests passed
**166/166**, full discovery ran **236 (233 passed, 3 private-problem module skips)**,
and JavaScript passed **40/40**. The production account backup was encrypted with
OpenSSL CMS AES-256-GCM, held outside Git with a private recovery key (0600), and
successfully decrypted in memory for a three-row completeness check. No plaintext
backup file or account/hash values were printed. This is an affected-table backup,
not a claim of complete database/Storage disaster recovery.

## Approved production rollout — 2026-10-18

- Applied migration `20261018125146_verified_email_identities_and_shared_otp_budgets`
  from the reviewed appended schema block. Three existing accounts remained
  unverified at version zero. The original four account fields matched the
  encrypted backup after migration; no history ownership was rewritten.
- Actual metadata checks: all three Auth RPCs are SECURITY INVOKER; `anon` and
  `authenticated` cannot execute them, `service_role` can. Budget-table RLS is
  enabled, and neither public role can select it. Public HTTP probes using the
  publishable key returned 401 / SQLSTATE 42501 for users, budgets and a budget
  RPC with invalid synthetic inputs. `/auth/v1/settings` returned 200 as a control.
- Supabase Auth dashboard reloads confirmed 8-digit OTPs, 600-second expiry,
  minimum resend interval 60 seconds and provider email limit 30/hour. Both email
  templates persisted the versioned OTP body. Email confirmation is enabled;
  anonymous access and manual linking remain disabled. Provider email is still
  Gmail SMTP; no SMTP credential was added to the judge container.
- Set only `SUPABASE_AUTH_KEY` on the backend, using the project's active
  publishable key. Filtered readback confirmed exactly one matching variable;
  existing environment variables were retained. No credential value is recorded.
- Backend source `8acd34f9e7fb3a2289b6c4cff3966aa92b4fd239` built and deployed
  successfully. Actual `/api/version` through Cloudflare reported build
  `fdc5c71305a959372441e517bb10c148eb2de3a38113c19e4fd5b89d3f76683f`,
  engine 2.0.6, local queue, Supabase problem source and 68 problems.
  A trusted process probe found the new Auth module and publishable key, and the
  persistent UID directory remained 0700 with a nonempty allocation ledger.
- [PR #10](https://github.com/n3wbiekkkk/Newbiegrader/pull/10) was merged by the
  operator at 12:55:47 UTC as `55372ab27dab98c99198e5dab1e4ebde73903180`.
  This happened before backend deployment completion was verified, so the planned
  backend-first ordering was not established. Both components are now observed
  on the new release. Main CI run
  [39129343995](https://github.com/n3wbiekkkk/Newbiegrader/actions/runs/39129343995)
  succeeded; the PR's validation, critical, SQL and Pages checks also succeeded.
- Production SPA loaded `/app.js?v=45`; the code field has maxlength 8 and
  pattern `[0-9]{8}`, with the recovery control present. Health and anonymous
  Auth-me returned 200 with Auth-me `no-store`; profile, admin, arbitrary job and
  arbitrary history requests were denied (401/403). A synthetic verify request
  without a challenge returned 400 and `no-store`, without sending email.
- Browser HTTP vantage: the audit Mac's current network, through public
  `https://newbiegrader.pages.dev`; public IP/network classification was not
  established. These observations do not establish direct backend reachability.
- Before deployment, persisted queue counts and the sandbox-process probe were
  zero. Production uses a local in-memory queue: this was not an atomic admission
  pause/drain and does not prove no request arrived between probes and restart.
- Requested one real OTP for the operator-owned test mailbox in native Chrome.
  The form reached the pending-code/new-password step. The operator must enter
  and submit the code and new password themselves; no OTP/password is read or
  transmitted through chat. Successful provider consumption, actual expiry and
  actual replay rejection remain unverified at this checkpoint. A pending-form
  response alone is not proof of delivery or successful identity verification.

### Recovery evidence and remaining gates

The affected-table backup is held outside Git under the operator's private local
data directory with a 0600 recovery key, 0700 parent and ciphertext manifest.
The encrypted object was decrypted in memory and its three-row shape checked;
no plaintext file or account values were printed. This is not a full PostgreSQL
restore drill. Supabase's project overview reported no platform backup.

Do not mark the public service ready solely because this release is deployed.
Real OTP verification, broader recipient delivery/provider abuse controls,
complete DB/Storage recovery, S04 aggregate resource isolation and B08 durable
queue operations remain outstanding. Keep legacy accounts unverified until
their owners prove mailbox control; do not fall back to old password-only code.
