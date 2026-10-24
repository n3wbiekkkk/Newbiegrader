# Security Policy

## Reporting

Report suspected vulnerabilities privately to newbiegrader.team@gmail.com.
Include the affected version, a minimal reproduction and the likely impact.
Do not include credentials, personal data, private submissions or hidden test
bytes in a public issue. Coordinate any testing against production first.

## System and scope

Newbiegrader is a Thai programming judge. The browser/Cloudflare Pages frontend
proxies to a separate FastAPI backend. Supabase holds identities, browser-session
families, history and the durable queue. Linux workers execute untrusted Python,
C and C++ under the trusted judging engine. Protected problem files and backend
credentials are private assets. Check /api/version and the maintained deployment
documents; a source branch alone does not establish the running release.

## Trust boundaries and invariants

- Treat code, uploads, custom input, reports and browser requests as untrusted.
- Enforce current session revocation, CSRF/origin checks, account ownership,
  problem visibility and contest policy on every protected operation.
- Keep provider/service credentials and opaque session hashes server-side.
  Fail closed on identity/storage failure; never restore revoked sessions.
- Preserve durable admission bounds, per-account limits, leases and completion
  fencing. Do not replay an ambiguous admission or lease-claim request.
- Keep untrusted execution credential-free and preserve private job identities,
  cgroups, Landlock, seccomp, resource limits and descendant cleanup.
- Exports must exclude private judge data and other users' information. Account
  deletion must revoke every family and complete provider/application erasure
  before claiming success; retain only the documented minimal audit.

## Finding context

Eligible signed-in peer source inspection and bounded failed-practice feedback
are intentional under docs/submission-feedback-policy.md. Disclosure beyond that
policy, including contest/private I/O or other users' email, remains reportable.
Assess realistic reachable impact; tests and policy statements are not proof
that a control works. This policy introduces no finding-class exclusions.

## Limitations

Local queue mode is single-process and best-effort. Production isolation needs
the Linux host qualification; macOS checks do not establish that boundary.
Read docs/PUBLIC_SECURITY.md and docs/ACCOUNT_DATA.md for dated qualification,
pending rollout gates and recovery limitations. These are not blanket waivers.
