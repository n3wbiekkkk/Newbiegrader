# Observed worker fleet and private monitoring

The serving API's cgroup budget describes its local allocation. It cannot infer
workers on another host from `GRADER_JUDGE_WORKERS` or from the number of jobs
currently running. Increasing that setting does not add remote execution slots.

An optional `GRADER_FLEET_STATUS_FILE` points to a root-maintained JSON snapshot.
With it configured, `/api/version` reports observed ready capacity in
`system.judge_workers`, retains the local derived allocation in
`system.local_judge_workers`, and supplies an allowlisted `system.worker_fleet`.
The admin overview uses the same reader for its worker count. Execution,
admission, account quotas, leases, memory allowances and sandbox budgets continue
to use their existing local settings; the display never controls admission.

If the configured snapshot is missing, unsafe, malformed, future-dated or older
than 45 seconds, the count is unknown (`null`); the frontend displays a dash.
An unavailable/stale peer contributes zero verified ready workers while retaining
its configured capacity. The API does not replace missing observations with a
hardcoded fleet total. Without the optional setting, legacy local reporting is
preserved.

## Collection

`deploy/host/fleet_snapshot.py` runs as a short systemd oneshot every 15 seconds.
Its root-only configuration specifies:

- `id`: a stable node label; `units`: the selected worker service names.
- `metrics_file`: a node_exporter textfile collector path.
- `output`: the snapshot path; `output_gid`: the API service account's group ID.
- `peers`: fixed private metrics URLs, each with an ID and configured worker count.

It observes local active supervisors and marks readiness conservatively when
recent worker transport errors or unreadable journals prevent confirmation.
It writes numeric node metrics atomically and reads bounded peer responses.
Peer collection timestamps, finite integral counts and configured bounds are
checked. No database credential, user identity, source, test data or compiler diagnostic
is included in exported metrics. An optional privileged collector reads bounded
allowlisted job/submission fields and exports aggregate queue counts, recent
processing percentiles, verdict counts and infrastructure errors. It never
passes credentials to child processes. This is operational observation, not a fresh
provider-login test or an end-to-end guarantee that every worker can judge.

Use root-owned directories; snapshots should be root:API-group 0640. The reader
rejects symlinks, nonregular files, extra hard links, group/world-writable files,
oversized documents, duplicate nodes and inconsistent counts. Public responses
use an explicit field allowlist. The collector must remain root-controlled.

## Repository ownership

General homeserver configuration is maintained in the separate `homeserver`
repository: Homepage, Prometheus/Grafana, Uptime Kuma, hardware sensors, private
application probes, Nextcloud and Server/Desktop mode. Its configuration and
private operator reports are not shipped in this application repository.

`fleet_snapshot.py`, `judge_metrics.py`, the API snapshot reader and the
Newbiegrader watchdog remain here because they implement application-specific
worker/queue contracts. Optional `app_health`, `hardware_metrics` and
`private_service_health` modules are installed from the homeserver repository
into the root-controlled operator runtime directory. Set `hardware_metrics: true`
to enable the sensor plugin; `apps` enables the private-app exporter. Missing or
failed exporters report unavailable without breaking worker fleet observation.
An enabled but unavailable watchdog plugin fails its optional health check.
No external module is required for an ordinary Newbiegrader deployment.

## Current judge allocation

| Node | Application responsibility | Worker allocation |
| --- | --- | --- |
| promma-server | Primary API, Nginx/tunnel and durable workers | 4 × one CPU / 1 GiB; API separate one CPU / 320 MiB |
| ubuntu-pc | Native judge workers | 10 × one CPU / 1 GiB, aggregate 10 CPUs / 10 GiB |
| homeserver | Warm backup API/tunnel, durable workers, retention, backups and watchdog | 2 × one CPU / 1 GiB; API separate one CPU / 320 MiB |

PC Desktop Mode or an offline PC contributes zero observed ready workers; the
primary and homeserver APIs and their six workers continue independently. General monitor and
cloud services share the PC, but their budgets are maintained separately. This
allocation is not a sustained simultaneous-user qualification.

## Shared-tailnet observation

The primary's device share permits incoming peer connections but cannot initiate
connections to the homeserver. The homeserver therefore pushes four numeric node-worker metrics for each
selected node with `fleet_peer_push.py` after collection. Its own observations
come from the local metrics file; auxiliary-PC observations are read from the
fixed private PC metrics URL with `--metrics-url` and relayed to a separate exact
receiver path. This avoids the primary's blocked direct primary-to-PC observation
path while preserving the PC's original collection timestamp.
No hardware, application, queue, identity or other-node fields are sent. The
primary receiver permits a bounded PUT to one exact path from the selected peer
Tailscale address. Freshness, integral capacity and configured bounds still apply
when the observer reads that file; stale pushes cannot keep a peer online.

`newbiegrader-fleet-metrics.service` runs a separate unprivileged Nginx instance
on the primary's private tailnet address. It serves only aggregate metrics and
anonymous primary health, with an exact-path peer upload. A missing tailnet
address restarts this observer listener without preventing the main loopback
API Nginx from starting. It is not a second general API listener.

Validate the private metrics Nginx config as its actual `www-data` service user.
The unit runs that preflight before startup. Running `nginx -t` as root without a
`user` directive can change its private temporary-directory ownership to nginx's
default account, causing later peer uploads to fail. Keep the temporary directories
owned by the service account with mode 0700; no executor permission is changed.
