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
checked. No database credential, user identity, submission, source, test data or
compiler diagnostic is included. This is operational observation, not a fresh
provider-login test or an end-to-end guarantee that every worker can judge.

Use root-owned directories; snapshots should be root:API-group 0640. The reader
rejects symlinks, nonregular files, extra hard links, group/world-writable files,
oversized documents, duplicate nodes and inconsistent counts. Public responses
use an explicit field allowlist. The collector must remain root-controlled.

Node exporters bind only their Tailscale addresses. Prometheus scrapes both
nodes every 15 seconds and stores up to 15 days / 2 GB of metrics. Its HTTP API
binds loopback. Grafana is provisioned with both nodes, refreshes every 30 seconds,
and allows private-tailnet read-only viewing; administration requires a separate
root-managed credential. Homepage provides current per-node capacity and links.
Do not publish Docker ports on every interface or mount the Docker socket into
the dashboard containers.

## Current allocation (25 October 2026)

| Node | Responsibility | Worker allocation |
| --- | --- | --- |
| ubuntu-pc | Native judge workers, private Homepage, Prometheus and Grafana | 10 × one CPU / 1 GiB, aggregate 10 CPUs / 10 GiB |
| homeserver | FastAPI, Nginx/private tunnel, durable-queue workers, account retention, backups and existing alerts/presence | 2 × one CPU / 1 GiB, aggregate two CPUs / 2 GiB; API separate one CPU / 320 MiB |

Both machines have an OS exporter and a bounded fleet observer. The homeserver
has only about 3.2 GiB physical RAM. Three full 1 GiB worker allocations plus the
API and OS do not fit; retain two without reducing job controls or relying on
swap. The PC monitoring containers share an additional 1.5 GiB / 1.5 CPU ceiling.
This is a bounded resource allocation, not a sustained simultaneous-user result.

PC Server Mode starts workers and the monitoring stack. Desktop Mode stops
workers and Docker/monitor containers; minimal OS telemetry remains available so
the other node can observe the PC and report zero ready PC workers. Central
monitor dashboards are unavailable while their PC host is in Desktop Mode or
offline. The homeserver API and two workers continue independently.

Nextcloud and AdGuard remain stopped with their existing data retained; this
rollout does not migrate them or change DNS. Existing external alert routing is
preserved. Prometheus alert rules are visible locally; no new notification
receiver is configured by this monitoring stack.

For recovery, preserve the newest UID ledger and current session key, back up
configuration, pause/drain before switching application releases, and qualify the
new release before reopening. Monitor configuration and Grafana state need their
own backup; graph history can be rebuilt, but it is not a database backup.
