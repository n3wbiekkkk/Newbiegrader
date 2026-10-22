# Public website security qualification

Verified 2026-10-22. Application release:
`b290e8ca074e77b6ea681551fa74ed572e0cad8b`.
The deployed controls passed the scoped public-website checks below. This is
release evidence for the existing PC deployment, with the operator's retained
limitations; it is not a guarantee against every vulnerability or kernel escape.
See the [machine-readable record](releases/public-security-2026-10-22.json).

## Browser and API boundary

Cloudflare Pages now applies CSP to static HTML as well as the API's existing
headers. Scripts and API connections stay same-origin; inline scripts, plugins,
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
Linux critical tests passed 306 and the full suite passed 502 with zero skips.
Frontend tests passed 127, all 89 private reference validations passed and the
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
root-controlled application release. All 216 release file hashes match Git.

After verification, an encrypted backup was downloaded and authenticated off
host, with valid UID reservations and 12 readable application table exports.
This supplements the earlier protected-file restore rehearsal; it does not
prove complete hosted Database/Auth/Storage recovery.

## Explicitly retained limitations

The operator chose to keep the existing SSH configuration: password access and
all-interface listeners remain; firewall/router/network exposure still needs
operator management. No SSH/firewall policy was changed in this release.

The operator also chose to keep browser-only logout. A copied valid session or
remember cookie is not individually revoked by logout and can remain valid
until expiry or an account-version change. Server-side session revocation or
account-wide logout requires a separate product decision.

Judging shares the PC's host kernel; no VM boundary was added. Per-job cgroups
bound whole-job memory but do not establish exact descendant memory accounting
for each test. Distributed abuse, sustained user capacity and every possible
attack were not exhaustively tested. Keep host/runtime patches, monitoring,
off-host backups and the [release checks](SECURITY_READINESS.md) current.
