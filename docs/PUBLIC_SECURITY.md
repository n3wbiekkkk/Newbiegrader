# Public website security qualification

Verified 2026-10-23. Application release:
`6e178c0ed3568572c68e8830da693f0086675887`.
The deployed controls passed the scoped public-website checks below. This is
release evidence for the existing PC deployment, with the operator's retained
limitations; it is not a guarantee against every vulnerability or kernel escape.
See the [current record](releases/public-readiness-2026-10-23.json) and the
[previous security qualification](releases/public-security-2026-10-22.json).

## Browser and API boundary

Cloudflare Pages now applies CSP to static HTML as well as the API's existing
headers. Application scripts and API connections stay same-origin; only the
Turnstile script/frame additionally permit `challenges.cloudflare.com`.
Inline scripts, plugins,
base-URL injection and cross-origin framing are denied. Required Google fonts,
HTTPS avatars and same-origin PDF frames remain allowed. HSTS, MIME, referrer
and permissions headers were read back over production HTTPS. A real browser
loaded the catalog/task/PDF and blocked an injected inline script.

The backend API and Nginx listen on loopback. Pages reaches the private PC
Worker through a service binding and server-only bridge key, then the fixed VPC
service and tunnel. Public Worker/preview URLs are disabled. The live Worker
redacts query strings from logs/traces and disables automatic invocation logs;
retain those settings when deploying from a template. Nginx access logging is
off and the API filters authentication query values from access logs.

Anonymous admin/history/job/execution checks, CSRF, body limits, canonical OAuth
redirects and cookie flags passed through the real HTTPS chain. Six private-path
and access probes exposed no private bytes. Static unknown paths can return the
SPA's HTML with status 200; that is not a successful private-file download.

The private Worker now enforces trusted-IP limits before forwarding requests:
6,000 API, 600 authentication and 600 execution requests per minute, with shared
classroom IPs in mind. Existing per-account limits, one active job per ordinary
account and the queue bound remain. Rate counters are approximate and local to
Cloudflare locations; these are abuse controls, not a strict global quota or a
guarantee against a distributed attack. Missing/failing limiter bindings fail closed.

Email-code requests and the registration alias additionally require server-side
Turnstile verification with the exact production hostname and `email_request`
action. Tokens are removed before reaching the existing handler and reset after
every frontend attempt. Missing/invalid/replayed tokens are denied; provider
failures do not bypass the gate. Password login, OTP verification and Google
login retain their existing handlers. Production rejected a dummy token with
403, and the operator confirmed a real widget challenge passed in their browser.
The operator then ran the supplied same-origin probe in that browser: a fresh
real token reached the original handler (400 for the deliberately invalid email),
and replaying it returned 403. No verification email was sent by this probe.
This human-assisted check proves that measured gate path, without claiming a
fresh account signup or email-delivery test.

## Worker reliability and monitoring

Repeated alerts were traced to HTTP/2 connection termination during worker queue
polling, including GOAWAY after 19,999 stream IDs. The dedicated worker's pinned
PostgREST client now uses pooled, TLS-verified HTTP/1.1. API transport is unchanged.
No failed claim is automatically replayed, because the original RPC might already
have leased a job. A 20-request read-only check verified the actual worker adapter;
local regression coverage exercises real HTTP/1.1 connection-close turnover.

The watchdog retains its journal checks and now also tests the public HTTPS
anonymous identity endpoint through Pages, the private bridge and tunnel. All
nine checks passed after deployment, with zero matching journal error lines in
the preceding hour. This short observation is not proof that overnight connection
errors can never recur; scheduled monitoring remains enabled.

A separate unprivileged Discord presence service now checks local API health,
all four worker units and the public HTTPS identity path every 30 seconds. The
bot displays `https://newbiegrader.pages.dev` while healthy and Invisible/Offline otherwise.
It starts automatically at boot and retains the existing token through a systemd
credential; the API and judge accounts do not receive that credential. Its ceiling
is 64 MiB / 5% CPU, separate from unchanged judging budgets. The existing watchdog
sends transitions to the operator-selected channel. Presence sends no messages.
A Discord outage can make the bot offline while the website works, and abrupt
power/network loss may take minutes to become visibly offline. It supplements
monitoring; it is not an independent off-host uptime monitor. Real staging and
production Gateway readiness/health checks passed, with eight synthetic protocol,
credential and health regressions. The final label-only rollback restarted only
presence; API and all four worker process start times stayed unchanged.

## Untrusted code

Every web job retains its private numeric UID, capability drop, Landlock,
seccomp, cgroup, workspace limits and descendant cleanup. Four workers and all
CPU/memory budgets remain unchanged. With explicit operator approval, compiler
and runtime filters additionally deny SysV shared memory/semaphores/message
queues, Linux keyrings, BPF and `perf_event_open`, preventing their use to leave
persistent kernel objects. Programs requiring these APIs receive EPERM and may
report RE if they do not handle it. Ordinary Python/C/C++ code, threads,
processes and anonymous stream socketpairs remain supported within the limits.

The native host gate passed 12 probes, including the new syscall denial probe;
Linux critical tests passed 311 and the full suite passed 517 with zero skips.
Frontend tests passed 144, all 89 private reference validations passed and the
three CI jobs passed. Actual public Python/C/C++ submissions received AC17/17
and linked history was verified. This used an existing verified operator
session; a fresh Google/OTP/password login was not repeated, and no manual
verification email was sent.

## Dependencies and data

`certifi` was patched to 2026.10.19 for the
[compromised-CA advisory](https://github.com/advisories/GHSA-6q48-6c7w-9gw2).
The replacement CA bundle validated TLS to Supabase and Google before rollout.
The installed 36-package runtime matches the host lock, which has zero known
vulnerabilities in this audit. CI now audits both direct requirements and the
host lock; future findings require fresh review.

Live catalog checks confirmed RLS and no client SELECT grants on 12 application
tables, invoker-security views, server-only RPC execution and two private Storage
buckets. RLS-without-policy advisor notices are intentional deny-by-default for
these server-only tables, not a reason to add public policies. No database DDL
or authorization policy change was made. Supabase's leaked-password protection
warning remains: it does not screen this application's separately stored
passwords; provider OTP proof and the existing custom password verifier remain.

The reviewed source index passed secret scanning. A historical scan of 370
commits flagged five documentation/example values; review identified hashes,
numeric configuration and an RPC name, not credentials. History was preserved.
Private fixtures, references, credentials and operator notes are absent from the
root-controlled application release. All 226 release file hashes match Git.

After deployment, an encrypted backup was downloaded and authenticated off host,
with valid UID reservations and 12 readable application table exports. All 12
tables were restored into a disposable Unix-socket-only PostgreSQL 17 instance,
matched by row values and passed the real privilege checks after applying the
committed schema twice. The instance and plaintext database were removed.
This supplements the earlier protected-file restore rehearsal; it does not
prove complete hosted Auth/Storage/PITR recovery or transactional consistency
across separately exported tables.

## Explicitly retained limitations

The operator chose to keep the existing SSH configuration: password access and
all-interface listeners remain; firewall/router/network exposure still needs
operator management. No SSH/firewall policy was changed in this release.

The operator also chose to keep browser-only logout. A copied valid session or
remember cookie is not individually revoked by logout and can remain valid
until expiry or an account-version change. Server-side session revocation or
account-wide logout requires a separate product decision.

The host's cached package upgrade simulation reported 37 upgrades, no additions
or removals, and two packages held back. The operator explicitly deferred OS
updates to a later maintenance window. This release did not install those
updates or reboot the PC, and does not claim that the OS is fully patched.

Judging shares the PC's host kernel; no VM boundary was added. Per-job cgroups
bound whole-job memory but do not establish exact descendant memory accounting
for each test. Distributed abuse, sustained user capacity and every possible
attack were not exhaustively tested. Keep host/runtime patches, monitoring,
off-host backups and the [release checks](SECURITY_READINESS.md) current.
