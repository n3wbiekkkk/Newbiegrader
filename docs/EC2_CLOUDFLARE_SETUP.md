# Cloudflare connection preparation — not deployed

As of 2026-10-19 the operator explicitly declined Wrangler OAuth / named tunnel /
VPC Service creation. No such resource, binding, Worker deployment or production
Pages change has been performed. These files are reviewable preparation only.
Do not interpret the commands below as approval to execute them.

## Current staging

The existing EC2 runs cloudflared 2026.10.1, pinned and checksum-verified, under
`newbiegrader-staging-tunnel.service`. It connects outbound using HTTP/2. Nginx
listens only on 127.0.0.1:8080 and exposes only `/api/health`. API/auth/jobs paths
are unavailable through this listener. Cookies/authorization are cleared even
for health requests. The actual external health probe returned HTTP 200 / 68
problems; `/api/auth/me` and `/api/submit` returned 404 from the audit Mac.

Quick Tunnel names change on recreation and have no uptime guarantee. They are
for development/testing, not a reliable permanent origin. Never point production
Pages at this temporary URL as a shortcut.

## Prepared option without a purchased domain

Pages `/api/*` → HTTPS `workers.dev` bridge → fixed HTTP VPC Service → named
Cloudflare Tunnel → EC2 loopback Nginx → FastAPI.

No control of `pages.dev` DNS is assumed. No EC2 application port is exposed.
Workers VPC is currently **beta**, available on Free/Paid plans and free during
open beta; normal Workers request/compute limits still apply. Pricing and product
status must be rechecked before adoption. This option does not provide a 100%
availability promise. A custom domain with a conventional named Tunnel remains
another option if the operator later obtains one.

### After explicit connection approval

1. Use `npx --yes wrangler@4.151.1 login` on the audit Mac. Review OAuth scopes
   on Cloudflare; do not create or paste broad API tokens into chat. Verify with
   `npx --yes wrangler@4.151.1 whoami`.
2. In Cloudflare's Workers VPC dashboard, create a named tunnel dedicated to
   Newbiegrader. Store its token on EC2 as `/etc/newbiegrader/tunnel-token`,
   root:root 0600, through SSH stdin. Never put the token in argv, Git, logs,
   screenshots, a browser URL or an environment variable. The prepared service
   uses systemd `LoadCredential` and cloudflared `--token-file`.
3. Create a **specific HTTP VPC Service**, host `localhost`, HTTP port **8080**,
   on that tunnel. Do not bind the entire network or register port 8000. The
   staging service reaches only health. Creating the VPC Service requires the
   Connectivity Directory Admin role; binding requires the Bind role.
4. Stop the temporary staging tunnel before starting the named one (both use
   loopback metrics port 20241). Install the reviewed
   `deploy/ec2/newbiegrader-tunnel.service.example` as a real service file.
   Keep root-only token access; systemd supplies its per-service credential copy.
5. Copy `deploy/ec2/cloudflare/wrangler.jsonc.example` to a local
   `wrangler.jsonc`, replace only its VPC Service ID and leave `API_ENABLED=0`.
   From that directory deploy with
   `npx --yes wrangler@4.151.1 deploy --config wrangler.jsonc`. Use only the
   existing Free plan; stop if account setup requires paid features or terms
   requiring operator acceptance. Do not change the production Pages project.
6. Verify the stable bridge URL returns 200 only for GET/HEAD health; auth,
   jobs, submit, run and unrelated paths must return 404. Restart the named
   tunnel and repeat against the **same** URL. Verify worker and API remain
   healthy, no backend listener became public, and no queue RPC was claimed.

### Separate final cutover approval

The bridge's full API mode is not enabled by connection approval. First complete
the migration gates in `EC2_MIGRATION.md`. At approved cutover:

- Create a random server-side shared key (at least 32 characters), install it as
  Worker and Pages `BACKEND_PROXY_KEY` secrets without printing it. The browser
  never receives this key. The Pages Function strips any client-supplied copy.
- Install the reviewed loopback-only production Nginx listener on port **8081**.
  Change the specific VPC Service port only after the shared-key gate is tested;
  set the bridge `API_ENABLED=1`. Requests without the key must return 403.
- Retain manual redirects, cookies and query strings through both proxies.
  Verify Google login/OTP/cookies/CSRF and client-IP handling through the actual
  Pages chain. Use operator-owned test identities, never real user submissions.
- Set Pages `BACKEND_ORIGIN` to the stable bridge HTTPS origin and redeploy the
  reviewed proxy. Keep the original JustRunMy origin available for rollback.
- Do not add catch-all fallback to the old worker on execution failure; it can
  duplicate judging or diverge queue ownership.

The VPC service fixes its destination. The bridge rejects unrelated paths and
removes the shared key before forwarding; Nginx bounds actual streamed bodies
to 1 MiB. Uvicorn disables automatic proxy-header interpretation; the backend
trusts only the immediate loopback peer and receives a single Pages client IP.
Review direct-bridge spoofing tests before enabling its API mode.

## Removal / rollback

Before connection: no named resource exists to remove. Stop the current temporary
health tunnel with `sudo systemctl disable --now newbiegrader-staging-tunnel` if
staging is no longer needed; this does not affect the live Pages→JustRunMy route.

After an approved migration: pause new admission, drain/fence the AWS queue,
restore the Pages origin and old worker according to `EC2_MIGRATION.md`. Disable
the bridge API mode. Delete a named tunnel/VPC Service/Worker only after checking
bindings and obtaining approval for irreversible removal; preserve rollback
configuration and credentials until the rollback window closes.

## Official references

- [Workers VPC setup](https://developers.cloudflare.com/workers-vpc/get-started/)
- [Specific VPC Services and roles](https://developers.cloudflare.com/workers-vpc/configuration/vpc-services/)
- [VPC beta pricing](https://developers.cloudflare.com/workers-vpc/platform/pricing/)
- [Quick Tunnel limitations](https://developers.cloudflare.com/tunnel/get-started/quick-tunnels/)
