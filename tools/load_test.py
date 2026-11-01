"""Opt-in HTTP load measurement for a disposable Newbiegrader test installation.

No database connection or third-party dependency. Run --help for safeguards and
options. Never use production accounts, cookies, or a production-backed server.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
import datetime as dt
import http.cookiejar
import ipaddress
import json
import math
import os
from pathlib import Path
import random
import socket
import statistics
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

ROOT = Path(__file__).resolve().parents[1]


def validate_target(target: str, allow_remote: bool) -> str:
    """Reject implicit remote targets, URL secrets, and ambiguous API roots."""
    try:
        parsed = urllib.parse.urlsplit(target)
        port = parsed.port  # Validate invalid ports before opening any connection.
        hostname = parsed.hostname
        if (parsed.scheme not in {"http", "https"} or not hostname
                or parsed.username is not None or parsed.password is not None
                or parsed.query or parsed.fragment or parsed.path not in {"", "/"}
                or any(char.isspace() for char in target) or "\\" in target
                or port == 0):
            raise ValueError
    except ValueError:
        raise ValueError("target must be an HTTP(S) origin without credentials, path, query, or fragment") from None
    try:
        loopback = ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        loopback = hostname.lower() == "localhost"
    if not loopback and not allow_remote:
        raise ValueError("remote targets require --allow-remote and a disposable test installation")
    return target.rstrip("/")


def load_accounts(env_name: str) -> list[dict]:
    """Credentials stay in memory and never appear in validation messages."""
    try:
        accounts = json.loads(os.environ.get(env_name, ""))
        if not isinstance(accounts, list) or not accounts:
            raise ValueError
        emails = set()
        for account in accounts:
            if (not isinstance(account, dict) or not isinstance(account.get("email"), str)
                    or "@" not in account["email"] or not isinstance(account.get("password"), str)
                    or not 8 <= len(account["password"]) <= 128):
                raise ValueError
            email = account["email"].strip().lower()
            if email in emails:
                raise ValueError
            emails.add(email)
        return accounts
    except (ValueError, TypeError):
        raise ValueError("accounts environment variable must contain a nonempty JSON list of unique email/password objects") from None


def summarize(samples: list[float]) -> dict:
    if not samples:
        return {"count": 0}
    ordered = sorted(samples)

    def percentile(fraction):
        index = (len(ordered) - 1) * fraction
        lo = math.floor(index)
        hi = math.ceil(index)
        return ordered[lo] + (ordered[hi] - ordered[lo]) * (index - lo)

    return {"count": len(ordered), "mean_s": statistics.fmean(ordered),
            "p50_s": percentile(0.5), "p95_s": percentile(0.95),
            "p99_s": percentile(0.99), "max_s": ordered[-1]}


def job_durations(job: dict, *, first_running_s: float | None, elapsed_s: float) -> dict:
    try:
        created, started, finished = (dt.datetime.fromisoformat(
            str(job[key]).replace("Z", "+00:00")) for key in ("created_at", "started_at", "finished_at"))
        wait = (started - created).total_seconds()
        service = (finished - started).total_seconds()
        if wait < 0 or service < 0:
            raise ValueError
        return {"queue_wait_s": wait, "service_s": service, "timing_source": "server"}
    except (KeyError, ValueError, TypeError):
        return {"queue_wait_s": first_running_s,
                "service_s": max(0, elapsed_s - first_running_s) if first_running_s is not None else None,
                "timing_source": "poll_estimate" if first_running_s is not None else "unavailable"}


@dataclass
class Response:
    status: int
    data: dict
    elapsed_s: float
    error: str = ""


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.latencies = defaultdict(list)
        self.responses = Counter()
        self.errors = Counter()

    def record(self, kind: str, response: Response):
        with self.lock:
            if not response.error and 200 <= response.status < 300:
                self.latencies[kind].append(response.elapsed_s)
            self.responses[f"{kind}:{response.status}"] += 1
            if response.error:
                self.errors[f"{kind}:{response.error}"] += 1

    def report(self):
        with self.lock:
            return {"api_latency": {kind: summarize(values) for kind, values in self.latencies.items()},
                    "http_status_counts": dict(self.responses), "request_errors": dict(self.errors)}


class NoRedirect(urllib.request.HTTPRedirectHandler):
    # Never forward session cookies/passwords to a redirect target, including
    # a remote origin reached through an initially local target.
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class Client:
    def __init__(self, target: str, timeout: float, metrics: Metrics):
        self.target = target
        self.timeout = timeout
        self.metrics = metrics
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({}), NoRedirect(),
            urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    def request(self, kind: str, path: str, *, fields=None, body=None, timeout=None) -> Response:
        # The server's CSRF check requires unsafe browser-cookie requests to
        # carry Origin; this harness authenticates with session cookies, so it
        # sends the target's own origin (validate_target guarantees target is
        # a bare origin, never a URL with path/query/credentials).
        headers = {"Accept": "application/json", "Origin": self.target}
        data = None
        if fields is not None:
            headers["Content-Type"] = "application/x-www-form-urlencoded"
            data = urllib.parse.urlencode(fields).encode("utf-8")
        elif body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.target + path, data=data, headers=headers)
        started = time.monotonic()
        status, payload, error = 0, {}, ""
        try:
            with self.opener.open(request, timeout=timeout or self.timeout) as response:
                status = response.status
                # Bound response consumption; only metadata is retained/reported.
                raw = response.read(2 * 1024 * 1024 + 1)
                if len(raw) > 2 * 1024 * 1024:
                    error = "response_too_large"
                else:
                    payload = json.loads(raw)
                    if not isinstance(payload, dict):
                        payload, error = {}, "invalid_json_object"
        except urllib.error.HTTPError as exc:
            status, error = exc.code, f"http_{exc.code}"
            exc.close()
        except (TimeoutError, socket.timeout):
            error = "request_timeout"
        except (urllib.error.URLError, OSError):
            error = "connection_error"
        except (ValueError, UnicodeError):
            error = "invalid_json"
        result = Response(status, payload, time.monotonic() - started, error)
        self.metrics.record(kind, result)
        return result


def run_attempt(client: Client, args, source: str, playground: bool, *, workload=None) -> dict:
    started = time.monotonic()
    deadline = started + args.job_timeout
    item = workload or {}
    expected = item.get("expected_playground_verdict", "OK") if playground else item.get("expected_verdict", "AC")
    outcome = {"kind": "playground" if playground else "submission", "admitted": False,
               "completed": False, "correct": False, "error": "", "fatal": False,
               "expected_verdict": expected, "timing_source": "unavailable"}
    fields = {"problem": item.get("problem", args.problem),
              "language": item.get("language", args.language), "code": source}
    outcome["language"] = fields["language"]
    if playground:
        fields["input"] = item.get("stdin", args.stdin)
        # /api/run holds this request while a durable worker executes the job.
        # Its entire queue/execution budget must survive beyond admission's timeout.
        response = client.request("playground", "/api/run", fields=fields, timeout=args.job_timeout)
        outcome["admitted"] = response.status == 200 and not response.error
        outcome["completed"] = outcome["admitted"]
        verdict = str(response.data.get("verdict", "unknown"))
        outcome["verdict"] = verdict
        outcome["correct"] = outcome["completed"] and verdict == expected
        outcome["error"] = response.error or ("playground_execution_error" if not outcome["correct"] else "")
        outcome["fatal"] = bool(response.error) and response.status not in (400, 401, 403, 404, 409, 413, 422, 429)
        if response.status in (429, 503):
            outcome["rejection_status"] = response.status
        outcome["end_to_end_s"] = time.monotonic() - started
        return outcome
    response = client.request("submit", "/api/submit", fields=fields,
                              timeout=min(client.timeout, args.job_timeout))
    if response.status != 202 or response.error:
        outcome["error"] = response.error or "unexpected_submit_status"
        # A failed/ambiguous POST may already have created a durable job. End
        # this actor rather than issuing another attempt under that account.
        outcome["fatal"] = response.status not in (400, 401, 403, 404, 409, 413, 422, 429)
        if response.status in (429, 503):
            outcome["rejection_status"] = response.status
    else:
        jid = response.data.get("job_id")
        if not isinstance(jid, str) or not jid:
            outcome["error"], outcome["fatal"] = "missing_job_id", True
        else:
            outcome["admitted"] = True
            first_running = None
            delay = args.poll_interval
            while time.monotonic() < deadline:
                response = client.request("status", "/api/jobs/" + urllib.parse.quote(jid, safe=""),
                    timeout=min(client.timeout, max(0.001, deadline - time.monotonic())))
                if response.error:
                    outcome["error"], outcome["fatal"] = response.error, True
                    break
                job = response.data
                status = job.get("status")
                elapsed = time.monotonic() - started
                if status == "running" and first_running is None:
                    first_running = elapsed
                    delay = args.poll_interval
                if status in {"done", "error"}:
                    result = job.get("result")
                    if status == "done" and (not isinstance(result, dict) or not isinstance(result.get("verdict"), str)):
                        outcome["error"] = "invalid_job_result"
                        break
                    outcome["completed"] = status == "done"
                    outcome["verdict"] = str((result or {}).get("verdict", "unknown")) if isinstance(result, dict) else "unknown"
                    outcome["correct"] = outcome["completed"] and outcome["verdict"] == expected
                    outcome["error"] = ("terminal_job_error" if status == "error" else
                                        "unexpected_verdict" if not outcome["correct"] else "")
                    outcome.update(job_durations(job, first_running_s=first_running, elapsed_s=elapsed))
                    break
                if status not in {"queued", "running"}:
                    outcome["error"], outcome["fatal"] = "invalid_job_status", True
                    break
                time.sleep(min(max(0, deadline - time.monotonic()),
                               getattr(args, "poll_max_interval", 2.0),
                               delay * random.uniform(0.8, 1.2)))
                delay = min(getattr(args, "poll_max_interval", 2.0), delay * 1.4)
            else:
                outcome["error"], outcome["fatal"] = "job_timeout", True
    outcome["end_to_end_s"] = time.monotonic() - started
    return outcome


def read_source(path: Path) -> str:
    if path.stat().st_size > 256 * 1024:
        raise ValueError("source exceeds 262144 bytes")
    source = path.read_text(encoding="utf-8")
    if not source.strip() or len(source.encode("utf-8")) > 256 * 1024:
        raise ValueError("source must contain between 1 and 262144 bytes of code")
    return source


def load_workload(path: Path) -> list[dict]:
    if path.stat().st_size > 1024 * 1024:
        raise ValueError("workload JSON exceeds 1 MiB")
    rows = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError("workload must be a JSON list of 1-100 entries")
    result = []
    for row in rows:
        if (not isinstance(row, dict) or row.get("language") not in ("python", "c", "cpp")
                or not isinstance(row.get("problem"), str) or not row["problem"]
                or not isinstance(row.get("source"), str) or not row["source"]
                or type(row.get("weight", 1)) not in (int, float)
                or not 0 < row.get("weight", 1) <= 10000
                or not isinstance(row.get("stdin", ""), str)
                or len(row.get("stdin", "").encode()) > 256 * 1024
                or row.get("expected_verdict", "AC") not in ("AC", "REJECTED", "WA", "TLE", "MLE", "OLE", "RE", "CE")
                or row.get("expected_playground_verdict", "OK") not in ("OK", "TLE", "MLE", "OLE", "RE", "CE")):
            raise ValueError("invalid workload entry")
        source_path = Path(row["source"])
        if not source_path.is_absolute():
            source_path = path.parent / source_path
        # These are operator-selected local files; URL strings are never fetched.
        result.append({**row, "source": read_source(source_path), "weight": row.get("weight", 1)})
    return result


def run_load(args, accounts: list[dict], source: str) -> dict:
    metrics = Metrics()
    clients = [Client(args.target, args.request_timeout, metrics) for _ in accounts]
    for client, account in zip(clients, accounts):
        # Disposable verified accounts are seeded in the test database by its
        # operator. Registration now starts OTP delivery and cannot log in here.
        response = client.request("auth", "/api/auth/password", body={**account, "name": "Load test"})
        if response.error or response.status != 200:
            return {"setup_error": response.error or "authentication_failed", **metrics.report()}
    stop = threading.Event()
    outcomes, actor_errors = [], Counter()
    outcome_lock = threading.Lock()
    workloads = getattr(args, "workloads", None)
    duration = getattr(args, "duration", None)

    def health_probe():
        client = Client(args.target, args.request_timeout, metrics)
        while not stop.is_set():
            response = client.request("health", "/api/health")
            if response.status == 200 and not response.error and response.data.get("ok") is not True:
                with metrics.lock:
                    metrics.errors["health:unhealthy_payload"] += 1
            stop.wait(args.health_interval * random.uniform(0.8, 1.2))

    def attempt(index, sequence):
        client = clients[index]
        item = random.choices(workloads, weights=[row["weight"] for row in workloads])[0] if workloads else None
        problem = item["problem"] if item else args.problem
        if getattr(args, "browse", False):
            for kind, path in (("catalog", "/api/problems"),
                               ("detail", "/api/problems/" + urllib.parse.quote(problem, safe=""))):
                if deadline is not None and time.monotonic() >= deadline:
                    return False
                response = client.request(kind, path)
                if response.error or response.status != 200:
                    with outcome_lock:
                        actor_errors["browse_failed"] += 1
                    return True
        if deadline is not None and time.monotonic() >= deadline:
            return False
        outcome = run_attempt(client, args, item["source"] if item else source,
            bool(args.playground_every and sequence % args.playground_every == 0), workload=item)
        with outcome_lock:
            outcomes.append(outcome)
        return outcome["fatal"]

    probes = [threading.Thread(target=health_probe, daemon=True) for _ in range(args.health_clients)]
    started = time.monotonic()
    deadline = started + duration if duration else None
    for probe in probes:
        probe.start()
    try:
        with ThreadPoolExecutor(max_workers=len(clients)) as pool:
            if duration:
                def actor(index):
                    ramp = getattr(args, "ramp_seconds", 0) * index / max(1, len(clients) - 1)
                    if ramp:
                        stop.wait(ramp)
                    sequence = index + 1
                    while time.monotonic() < deadline:
                        if attempt(index, sequence):
                            with outcome_lock:
                                actor_errors["actor_stopped"] += 1
                            break
                        sequence += len(clients)
                        delay = getattr(args, "think_time", 0)
                        if delay:
                            stop.wait(min(delay * random.uniform(0.8, 1.2), max(0, deadline - time.monotonic())))
                list(pool.map(actor, range(len(clients))))
            else:
                for burst in range(args.bursts):
                    pending = [pool.submit(attempt, index, burst * len(clients) + index + 1)
                               for index in range(len(clients))]
                    stopped = [future.result() for future in pending]
                    # No new burst can safely reuse an account whose last POST
                    # or job state was ambiguous, even when other actors finished.
                    if any(stopped):
                        actor_errors["actor_stopped"] += sum(stopped)
                        break
                    if burst + 1 < args.bursts:
                        stop.wait(args.burst_interval)
    finally:
        elapsed = time.monotonic() - started
        stop.set()
        for probe in probes:
            probe.join(timeout=args.request_timeout + 1)
    completed = sum(outcome["completed"] for outcome in outcomes)
    report = {"duration_s": elapsed, "requested_duration_s": duration,
              "duration_reached": elapsed >= duration if duration else None,
              "drain_s": max(0, elapsed - duration) if duration else 0,
              "requested_users": len(clients), "attempts": len(outcomes),
              "admitted": sum(outcome["admitted"] for outcome in outcomes),
              "completed": completed, "correct": sum(outcome["correct"] for outcome in outcomes),
              "throughput_completed_per_s": completed / max(elapsed, 0.001),
              "actor_errors": dict(actor_errors),
              "http_rejections": dict(Counter(str(outcome["rejection_status"]) for outcome in outcomes if "rejection_status" in outcome)),
              "outcome_errors": dict(Counter(outcome["error"] for outcome in outcomes if outcome["error"])),
              "timing_sources": dict(Counter(outcome["timing_source"] for outcome in outcomes)),
              "verdicts": dict(Counter(outcome["verdict"] for outcome in outcomes if "verdict" in outcome)),
              **metrics.report()}
    report["languages"] = {}
    for language in sorted({outcome["language"] for outcome in outcomes}):
        selected = [outcome for outcome in outcomes if outcome["language"] == language]
        report["languages"][language] = {
            "attempts": len(selected), "completed": sum(outcome["completed"] for outcome in selected),
            "correct": sum(outcome["correct"] for outcome in selected),
            "completed_end_to_end_s": summarize([outcome["end_to_end_s"] for outcome in selected if outcome["completed"]])}
    for kind in ("submission", "playground"):
        selected = [outcome for outcome in outcomes if outcome["kind"] == kind]
        report[kind] = {"attempts": len(selected), "completed": sum(outcome["completed"] for outcome in selected)}
        for key in ("end_to_end_s", "queue_wait_s", "service_s"):
            report[kind][key] = summarize([outcome[key] for outcome in selected if outcome.get(key) is not None])
        report[kind]["completed_end_to_end_s"] = summarize([
            outcome["end_to_end_s"] for outcome in selected if outcome["completed"]])
    return report


def bounded_int(maximum):
    def parse(raw):
        value = int(raw)
        if not 1 <= value <= maximum:
            raise argparse.ArgumentTypeError(f"must be between 1 and {maximum}")
        return value
    return parse


def positive_float(raw):
    value = float(raw)
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("must be a finite positive number")
    return value


def nonnegative_float(raw):
    value = float(raw)
    if not math.isfinite(value) or value < 0:
        raise argparse.ArgumentTypeError("must be a finite nonnegative number")
    return value


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true", help="explicitly start HTTP load")
    parser.add_argument("--test-installation", action="store_true",
                        help="confirm the target uses a disposable test database and accounts, never production")
    parser.add_argument("--target", default="http://127.0.0.1:8000")
    parser.add_argument("--allow-remote", action="store_true", help="explicit authorization to load a remote test installation")
    auth = parser.add_mutually_exclusive_group()
    auth.add_argument("--register", action="store_true", help="unsupported: registration starts email verification; seed test accounts instead")
    auth.add_argument("--accounts-env", default="NG_LOAD_ACCOUNTS", help="environment variable with JSON email/password objects")
    parser.add_argument("--users", type=bounded_int(100), default=4, help="concurrent users per burst (max 100)")
    parser.add_argument("--duration", type=positive_float, help="seconds of independent-user sustained load, then bounded job drain")
    parser.add_argument("--think-time", type=nonnegative_float, default=0, help="mean per-user pause between jobs in duration mode")
    parser.add_argument("--ramp-seconds", type=nonnegative_float, default=0, help="spread user starts across this interval")
    parser.add_argument("--browse", action="store_true", help="read catalog and problem detail before each job")
    parser.add_argument("--workload", type=Path, help="local JSON list of weighted language/problem/source/expected-verdict entries")
    parser.add_argument("--bursts", type=bounded_int(1000), default=3)
    parser.add_argument("--burst-interval", type=positive_float, default=0.5, help="seconds between completed bursts")
    parser.add_argument("--health-clients", type=bounded_int(20), default=2)
    parser.add_argument("--health-interval", type=positive_float, default=0.25)
    parser.add_argument("--poll-interval", type=positive_float, default=0.25, help="initial status polling interval, then backs off to 2s")
    parser.add_argument("--poll-max-interval", type=positive_float, default=2.0,
                        help="status polling cap in seconds (max 2; use 1 for frontend-like active polling)")
    parser.add_argument("--request-timeout", type=positive_float, default=10.0)
    parser.add_argument("--job-timeout", type=positive_float, default=240.0)
    parser.add_argument("--problem", default="thai_time")
    parser.add_argument("--language", choices=("python", "c", "cpp"), default="python")
    parser.add_argument("--source", type=Path, default=ROOT / "examples" / "thai_time_ref.py")
    parser.add_argument("--playground-every", type=bounded_int(100000), help="replace every Nth attempt with /api/run")
    parser.add_argument("--stdin", default="6 AM\n", help="playground input")
    args = parser.parse_args(argv)
    if not args.execute or not args.test_installation:
        parser.error("requires --execute --test-installation; confirm a disposable database before running")
    if args.register:
        parser.error("--register is incompatible with OTP signup; seed verified disposable accounts and use --accounts-env")
    if args.duration and args.ramp_seconds >= args.duration:
        parser.error("--ramp-seconds must be shorter than --duration")
    try:
        args.target = validate_target(args.target, args.allow_remote)
        if args.poll_max_interval > 2:
            raise ValueError("--poll-max-interval must be at most 2 seconds")
        if args.poll_interval > args.poll_max_interval:
            raise ValueError("--poll-interval must not exceed --poll-max-interval")
        accounts = load_accounts(args.accounts_env)
        if len(accounts) < args.users:
            raise ValueError("accounts environment variable has fewer accounts than --users")
        accounts = accounts[:args.users]
        args.workloads = load_workload(args.workload) if args.workload else None
        source = "" if args.workloads else read_source(args.source)
    except OSError:
        parser.error("source file cannot be read")
    except (ValueError, UnicodeError) as exc:
        parser.error(str(exc))
    report = run_load(args, accounts, source)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 1 if (report.get("setup_error") or report.get("outcome_errors")
                 or report.get("request_errors") or report.get("actor_errors")
                 or not report.get("attempts") or report.get("duration_reached") is False) else 0


if __name__ == "__main__":
    raise SystemExit(main())
