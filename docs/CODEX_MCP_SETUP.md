# Codex MCP setup — Newbiegrader

This is a dated integration/setup record, not a production deployment runbook.
Server versions, tool counts and plan observations below describe that checkpoint.
Use [the documentation index](README.md) for current host and release guidance;
the configured development MCP project does not determine the production project.

Verified on 2026-10-17 (Asia/Bangkok), macOS 27.0.1 / Apple Silicon.
Initial setup branch: `chore/codex-mcp-setup`.
Context7 was removed, including its local Codex OAuth credentials, at the user's request.

## Cloudflare add-on — verified 2026-10-19

Followed the Codex section of the official
[Cloudflare agent setup instructions](https://developers.cloudflare.com/agent-setup/prompt.md).
Existing MCP entries were preserved and the Codex configuration was backed up
privately before adding one `cloudflare` entry; no duplicate was created.

- Installed all **19 Cloudflare skills** under `~/.codex/skills/` using the
  Codex skill installer from official `cloudflare/skills`, pinned to commit
  `86505e44f87d801aa1864a3c4109e9a8ae5c409f`. No project AGENTS.md was changed
  or tracked. Skills load automatically on a subsequent turn/session.
- Registered `https://mcp.cloudflare.com/mcp` in `~/.codex/config.toml` and
  completed Codex-managed OAuth. Actual CLI status: enabled / OAuth. Separate
  Codex app-server verification: **connected**, four tools (`docs`, `search`,
  `execute`, `whoami`). No model/agent turn was started by that protocol probe.
- Safe integration calls actually succeeded: documentation search, authenticated
  identity lookup, API schema search and a read-only account tunnel inventory
  returning HTTP 200. Later staging-only resource changes are recorded in the
  private migration record; this authentication does not approve production cutover.
- Requested OAuth scopes cover account/user read, Workers scripts read/write/
  bind, Pages metadata/read/write, tunnel read/write and connectivity directory
  read/bind/admin, plus offline refresh. Default broad authorization was stopped
  before consent and replaced with this explicit scope request. No DNS, billing,
  database, WAF or credential-rotation scope was requested.
- Existing pinned Wrangler **4.151.1** also authenticated. `whoami` verified
  account/user read, Workers scripts write, Pages write, connectivity admin and
  offline refresh. Credentials are an encrypted file whose key is in macOS
  Keychain. Missing-unrelated-scope warnings are intentional; do not broaden
  permissions merely to silence them.

The MCP connection is account-scoped, not repository-scoped. Resource ownership,
specific VPC targets and the production approval gate constrain this work; the
connection itself does not technically prevent every other account operation.
No API token, tunnel token or OAuth credential was written to the repository.
Cloudflare account dashboard confirmed Workers **Free / $0 current plan**; no
upgrade was performed. VPC remains free during open beta, not a promise of
permanent free pricing or uptime.

The running conversation may retain its previous tool catalog. Open a new Codex
session or refresh MCP connections to expose the new server directly; the
installed app-server already loaded and exercised it successfully. Authentication
does not need to be repeated merely because a conversation's tool list is stale.

Removal: `codex mcp logout cloudflare`, then `codex mcp remove cloudflare`.
Installed Cloudflare skills are separate; review and remove only the 19 named
directories from this pinned installation if desired. Preserve `.system` and
other skills. Private setup logs/backups remain outside Git under
`~/.local/share/newbiegrader-private/` and must not be pasted into reports.

## Installed servers and authentication

| Server | Official implementation | Authentication | Verified tools |
| --- | --- | --- | ---: |
| Supabase | Hosted MCP, server version `0.14.0` | Codex-managed OAuth | 23 |
| GitHub | `github/github-mcp-server`, native Darwin arm64 `v2.0.2` | Existing GitHub CLI OAuth credential retrieved from its credential store at launch | 44 |
| Playwright | Microsoft's `@playwright/mcp@0.0.83`, local stdio | No external account required | 45 |

All three connected successfully through the installed Codex app-server and returned tool catalogs.
Tool counts describe the observed versions and feature selections, not a guarantee about future releases.
No Supabase service-role key or GitHub token was added to the repository or Codex configuration.
Existing Codex settings and other MCP entries were preserved; no duplicate server was installed.

### Supabase project scope

The configured project ref is `qblnlfzjublfnnsasgpe`, derived from the local
`SUPABASE_URL` hostname and independently verified by the authenticated MCP
`get_project_url` response. Only the URL hostname was extracted; no key value
was used or displayed for this check.
`agent.md:62` currently lists a different ref, `synyixryyoytbdaxnmph`; that
documented ref returned a permission error during verification and was replaced
in the MCP configuration. This verifies the local development target, not the
environment variables of a production deployment.

Endpoint:

```text
https://mcp.supabase.com/mcp?project_ref=qblnlfzjublfnnsasgpe&features=database,docs,debugging,development,functions,branching,storage
```

The connection is write-capable: `read_only=true` is not set. Discovered tools
include schema inspection, SQL execution, migrations, advisors, logs, Edge
Functions, storage configuration, and development branches. Project scoping
removes account-wide project-management tools such as listing/creating projects.
Those tools cannot also be enabled while preserving this project restriction.
Feature availability, including database branching, still depends on the account's
plan and permissions; paid features were not exercised.

Authentication command:

```sh
codex mcp login supabase
```

Complete the provider's sign-in/consent in a browser with an account authorized
for this project. Codex manages OAuth credentials using its existing credential
store configuration; this setup did not inspect or export those credentials.
Changing the endpoint/project ref can require a new OAuth login.

### GitHub repository and credential scope

Target repository: `n3wbiekkkk/Newbiegrader` (public; default branch `main`).
Both GitHub's authenticated user API and MCP `get_me` returned `n3wbiekkkk`.
The GitHub CLI's cached account label differs; API identity was used for
verification. The repository metadata reports push/admin permissions.

Enabled toolsets: `context,repos,git,issues,pull_requests`. These expose repository
reads, branches, file/commit operations, issues, pull requests, and reviews.
Write operations were discovered but not executed against GitHub.

The launcher invokes `gh auth token --hostname github.com`, captures its output
without logging it, sets `GITHUB_PERSONAL_ACCESS_TOKEN` only in the server's
process environment, then executes the official native server. Authentication
fails closed if GitHub CLI cannot supply a credential. No token is stored in
the launcher, command arguments, or `config.toml`.

**Repository-only authorization is not enforced.** The reused credential retains
its existing account permissions. No repository allowlist was found in the
installed server's CLI options. For an enforced boundary, an administrator must
provision a credential restricted to the selected repository (for example a
fine-grained PAT) and replace the credential source. This setup did not create,
expand, rotate, or revoke account permissions.

### Playwright local and staging use

The server starts headless Chromium with an isolated browser profile and
`vision,pdf,devtools` capabilities. Core tools support navigation, forms,
interactions, screenshots, and browser automation. Localhost and staging URLs
are supported; only a synthetic localhost page was tested in this setup.

No personal browser profile or authenticated browser session is attached.
The browser sandbox and default filesystem restrictions were retained. Neither
`--no-sandbox` nor `--allow-unrestricted-file-access` is configured. No origin
allowlist is set; network access is not restricted to this repository's domains.

## Configuration and installation locations

| Location | Purpose |
| --- | --- |
| `~/.codex/config.toml` | Global MCP entries, timeouts, approval defaults; mode `0600` |
| `~/.local/share/newbiegrader-mcp/` | Private installation root; mode `0700` |
| `…/bin/github-mcp-server` | Official GitHub native binary |
| `…/bin/github-newbiegrader-mcp` | Credential-store launcher; mode `0700` |
| `…/node/package.json`, `…/node/package-lock.json` | Pinned Playwright MCP and verification SDK dependencies |
| `…/artifacts/` | Synthetic browser snapshots, screenshot and PDF |
| `…/verification/` | Tool inventories, safe test reports and local verification scripts |
| `…/backups/config.toml.before-20261017-180820` | Original Codex configuration backup; mode `0600` |
| `~/Library/Caches/ms-playwright/` | Downloaded Chromium and headless shell |

Paths abbreviated with `…` are under `~/.local/share/newbiegrader-mcp`.
The global entries use absolute paths for this machine and the repository as
their working directory. No repository `.codex/config.toml` or application
dependency file was added.

Observed tooling:

| Tool | Version/status |
| --- | --- |
| Codex CLI | `0.163.0` |
| Node.js | `24.15.0` |
| npm / npx | `11.12.1` |
| Homebrew | `7.0.9-135-gaac1fb8` |
| Docker CLI / running daemon | `29.9.0` / `29.5.2`, Linux arm64 |
| Git | `2.56.0` |
| MCP verification SDK | `@modelcontextprotocol/sdk@1.32.1` |
| Playwright dependency | `1.64.0-alpha-1790635538000` (the official MCP package's dependency) |
| Browser | Chrome for Testing `155.0.8059.12`, Chromium revision `1247` |

No Homebrew, Docker or Codex upgrade was needed. The GitHub release archive's
SHA256 was verified against the official release asset digest before extracting
the native binary:

```text
5d9b38511bffc84d2272eb6189129eb721c8900e45784d8ea7eaf25f8d3dd835
```

Playwright MCP and the verification SDK were installed under the private prefix:

```sh
npm install --prefix "$HOME/.local/share/newbiegrader-mcp/node" --save-exact \
  @playwright/mcp@0.0.83 @modelcontextprotocol/sdk@1.32.1
node "$HOME/.local/share/newbiegrader-mcp/node/node_modules/playwright/cli.js" install chromium
```

The installed MCP references the actual Chromium executable explicitly. After
upgrading Playwright, reinstall its matching browser and update that executable
path before testing. Docker is available but is not used by these installations.

## Permissions and confirmation boundaries

| Server | `default_tools_approval_mode` | Intent |
| --- | --- | --- |
| Supabase | `writes` | Read tools can run; tools not marked read-only require confirmation |
| GitHub | `writes` | Read tools can run; remote changes require confirmation |
| Playwright | `auto` | Autonomous local/staging browser tests |

Supabase uses a 60-second startup timeout, GitHub 45 seconds, and Playwright
60 seconds. All three use a 120-second tool timeout.

These are Codex tool approval defaults, not service-side access controls.
Keep the user's confirmation requirement for production database mutations,
destructive actions, deployment changes, permission escalation, secret rotation,
and pushes. Browser automation can also make changes through a website; `auto`
does not authorize production writes. `execute_sql` is marked as a write-capable
tool even when supplied a SELECT, so Codex can request confirmation for it.

## Verification results

All tests below actually ran on this Mac; none was skipped.

| Check | Result | Scope |
| --- | --- | --- |
| Codex strict-config app-server startup and tool discovery | PASS | Three servers connected; 23/44/45 tools; no catalog errors |
| Supabase OAuth and target project | PASS | `get_project_url` matched the configured ref |
| Supabase schema and migration metadata | PASS | `list_tables(public, verbose=false)` and `list_migrations` |
| GitHub authentication | PASS | MCP `get_me` matched the authenticated API identity |
| GitHub repository read | PASS | MCP `list_branches` on Newbiegrader |
| Playwright browser workflow | PASS | Navigate, fill form, click, evaluate synthetic result, screenshot, PDF, close |
| Existing global configuration preservation | PASS | Parsed TOML comparison with backup, excluding the three new entries |
| Context7 removal | PASS | Codex logout/remove succeeded; no Context7 entry remains |

No application rows, hidden tests or real submissions were retrieved. No secret
values were displayed or included in verification reports.
No SQL mutation, migration application, remote commit, issue/PR write, deployment,
or push was performed. Write permissions are configured and write tools were
discovered; write behavior was not integration-tested.

Verification reports and scripts live outside Git:

```sh
python3.12 "$HOME/.local/share/newbiegrader-mcp/verification/codex_probe.py"
python3.12 "$HOME/.local/share/newbiegrader-mcp/verification/supabase_integration.py"
node "$HOME/.local/share/newbiegrader-mcp/verification/stdio_integration.mjs"
```

The Supabase script reads only project/schema/migration metadata. The browser
script serves a constant synthetic fixture on loopback and writes artifacts to
the private installation directory. It does not start the judge or run a
submission. The local Codex probe uses an ephemeral read-only thread without an
LLM turn; it does not change the running conversation's tool list.

### Final `codex mcp list` snapshot

Below are the Name, Status and Auth columns of the actual command output.
The full wide output is saved locally in
`~/.local/share/newbiegrader-mcp/verification/codex-mcp-list.txt`.

```text
Name         Status    Auth
code-review  disabled  Unsupported
codex_app    disabled  Unsupported
cua_repl     enabled   Unsupported
github       enabled   Unsupported
node_repl    enabled   Unsupported
playwright   enabled   Unsupported

Name      Status   Auth
mxterm    enabled  Unknown
supabase  enabled  OAuth
```

`Unsupported` for a stdio server describes Codex-managed OAuth support, not a
failed GitHub login. GitHub authentication was independently verified through
the actual MCP tool. The pre-existing servers were retained and were not audited
or otherwise verified as part of this setup.

## Activation and troubleshooting

1. Open a new Codex session in this repository to load the updated global MCP
   configuration. Use `/mcp` in the interactive CLI to inspect connections.
   Existing conversations may retain their original tool inventory; the separate
   Codex app-server verification already confirmed compatibility.
2. Run `codex mcp list` and `codex mcp get supabase` / `github` / `playwright` to
   inspect entries. Avoid sharing credential stores or raw authentication URLs.
3. For Supabase `authenticationRequired`, run `codex mcp login supabase` and
   complete browser consent. For permission errors, check the local project ref
   and the provider account's access; successful OAuth alone does not prove
   project authorization. Do not remove project scoping to work around access.
4. If GitHub credentials expire, use `gh auth status` and
   `gh auth login --hostname github.com`, then restart the MCP server. Never run
   `gh auth token` with its output displayed or copied into configuration.
   Verify identity with `gh api user --jq .login` if its cached label differs.
5. If the browser executable is missing, rerun the pinned Playwright browser
   install, check `verification/playwright-browser-path.txt`, and update the
   configured path. Do not disable the browser sandbox to hide startup errors.
6. The official Playwright MCP currently depends on an alpha Playwright build;
   retain the lockfile and repeat the synthetic workflow after upgrades.
7. `codex --strict-config mcp list` is unsupported by this CLI version. Normal
   `codex mcp list` and a separate strict-config app-server were used instead.

## Removal and rollback

Remove only these integrations (leave existing servers intact):

```sh
codex mcp logout supabase
codex mcp remove supabase
codex mcp remove github
codex mcp remove playwright
```

This logs out the local Supabase MCP credential; provider-side app grants may
remain. GitHub CLI authentication is shared with existing tooling, so do not
log it out merely to remove MCP. Context7 is already absent.

After removal, the private installation directory can be archived or removed
manually if no longer needed; it contains the original config backup and test
artifacts. Browser caches may be shared with other Playwright projects and
should not be deleted automatically. Prefer targeted removal over restoring an
old global config, which could overwrite later unrelated settings.

## Official references

- [Codex MCP configuration](https://developers.openai.com/codex/mcp/)
- [Supabase MCP setup, project scoping and feature groups](https://supabase.com/docs/guides/ai-tools/mcp)
- [Official GitHub MCP server](https://github.com/github/github-mcp-server)
- [GitHub's Codex installation guide](https://github.com/github/github-mcp-server/blob/main/docs/installation-guides/install-codex.md)
- [Microsoft Playwright MCP](https://github.com/microsoft/playwright-mcp)
