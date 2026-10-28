#!/usr/bin/env python3
"""Health watchdog for a Newbiegrader host: report only when something breaks.

Runs on the host and inspects the local stack only: the API on loopback, the
systemd units, the queue diagnostics, the disk and the age of the last
successful backup. A webhook posts one message per *transition* into the
broken state, so a long outage does not become a notification storm.

The webhook URL is read from a root-owned 0600 file and never appears in the
argument vector, the environment or the journal.

    python3 deploy/host/newbiegrader-alert.py --check-only   # report, no webhook
    python3 deploy/host/newbiegrader-alert.py --dry-run      # print the payload
    python3 deploy/host/newbiegrader-alert.py                 # alert on transition
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import ipaddress
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

DEFAULT_WEBHOOK_FILE = Path("/etc/newbiegrader/alert-webhook")
DEFAULT_STATE_FILE = Path("/var/lib/newbiegrader/alert-state.json")
DEFAULT_BACKUP_MARKER = Path("/var/lib/newbiegrader/last-backup")
API_BASE = "http://127.0.0.1:8000"
EXPECTED_PROBLEMS = 100
BACKUP_MAX_AGE_H = 30
RETENTION_MAX_AGE_H = 36
JOURNAL_ERROR_PATTERNS = (
    "worker unavailable",
    "judge database unavailable",
    "queue claim failed",
    "PRIVILEGE_DROP_FAILED",
    "SandboxUnavailable",
    "email verification provider unavailable",
    "email verification provider rate limited",
)


def _read_secret(path: Path) -> dict:
    """Read the webhook configuration from a private root file.

    The file holds either the URL alone, or a JSON object with a "url" and an
    optional "to" (the LINE recipient). The URL never appears in the argument
    vector, the environment or the journal.
    """
    info = path.lstat()
    if not os.path.isfile(path) or path.is_symlink():
        raise SystemExit(f"Alert webhook must be a regular file: {path}")
    if info.st_mode & 0o077:
        raise SystemExit(f"Alert webhook must not be group/world readable: {path}")
    if os.geteuid() == 0 and info.st_uid != 0:
        raise SystemExit(f"Alert webhook must be owned by root: {path}")
    raw = path.read_text(encoding="utf-8").strip()
    if not raw:
        raise SystemExit(f"Alert webhook file is empty: {path}")
    if raw.startswith("{"):
        try:
            data = json.loads(raw)
        except ValueError as exc:
            raise SystemExit(f"Alert webhook file is not valid JSON: {exc}") from exc
        url = str(data.get("url") or "").strip()
        if not url:
            raise SystemExit("Alert webhook file has no url")
        return {"url": url, "to": str(data.get("to") or "").strip(),
                "token": str(data.get("token") or "").strip(),
                "label": str(data.get("label") or "").strip(),
                "routes": _validate_routes(data.get("routes"))}
    return {"url": raw, "to": "", "token": "", "label": ""}


def _validate_routes(routes) -> dict:
    if routes is None:
        return {}
    if not isinstance(routes, dict) or set(routes) != {"newbiegrader", "homeserver"}:
        raise SystemExit("Alert routes must define newbiegrader and homeserver")
    clean = {}
    for scope, route in routes.items():
        if not isinstance(route, dict) or not isinstance(route.get("url"), str):
            raise SystemExit("Invalid alert route")
        url = route["url"]
        parsed = urllib.parse.urlsplit(url)
        if (parsed.scheme != "https" or parsed.hostname != "discord.com" or parsed.port not in (None, 443)
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or not re.fullmatch(r"/api/v10/channels/[0-9]+/messages", parsed.path)):
            raise SystemExit("Alert routes must use Discord channel message endpoints")
        clean[scope] = {"url": url}
    if clean["newbiegrader"]["url"] == clean["homeserver"]["url"]:
        raise SystemExit("Alert routes must use separate channels")
    return clean


def _secret_label(path: Path) -> str:
    """The operator's name for this host, if the webhook file carries one."""
    try:
        return _read_secret(path).get("label", "")
    except (SystemExit, OSError):
        return ""


def _get_json(url: str, timeout: float = 15.0):
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _public_identity(base: str) -> None:
    """Exercise the public Pages/binding/key/tunnel chain without a session."""
    url = urllib.parse.urlsplit(base)
    if url.scheme != "https" or not url.hostname or url.username or url.password \
            or url.path not in ("", "/") or url.query or url.fragment:
        raise ValueError("public URL must be an HTTPS origin")
    request = urllib.request.Request(base.rstrip("/") + "/api/auth/me", headers={
        "Accept": "application/json", "Cache-Control": "no-cache",
        "User-Agent": "Newbiegrader-watchdog/1"})
    with urllib.request.urlopen(request, timeout=15) as response:
        if response.status != 200 or response.geturl() != request.full_url:
            raise ValueError("public API returned a non-200 response")
        body = response.read(65537)
        if len(body) > 65536:
            raise ValueError("public API response too large")
        payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict) or "user" not in payload or payload["user"] is not None:
        raise ValueError("public API did not return the anonymous identity contract")


def _post_json(url: str, payload: dict, token: str = "", timeout: float = 20.0) -> None:
    """Deliver the alert.

    The webhook kind is derived from the URL, so one stored secret reaches a
    Discord bot, a Discord channel webhook, Slack, a LINE bot or any endpoint
    that accepts a JSON body, without the operator editing this script.
    """
    body, headers = _format_for(url, payload, token)
    request = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "User-Agent": "newbiegrader-alert/1", **headers})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        response.read()


def _format_for(url: str, payload: dict, token: str = "") -> tuple[dict, dict]:
    """Return (body, extra headers) for the webhook kind behind this URL.

    Discord is reached over its REST API, not a gateway: the bot only has to
    be a member of the server with permission to post in the channel, and no
    long-lived bot process has to stay connected for an alert to be delivered.
    """
    text = payload.get("text", "")
    lowered = url.lower()
    if "discord.com/api" in lowered or "discordapp.com/api" in lowered:
        body = {"allowed_mentions": {"parse": []}}
        if payload.get("embed"):
            body["embeds"] = [payload["embed"]]
        else:
            body["content"] = text
        if "/channels/" in lowered:
            # Discord bot: POST to a channel with the bot token.
            headers = {"Authorization": f"Bot {token}"} if token else {}
            return body, headers
        # Discord channel webhook: the token is already part of the URL.
        return body, {}
    if "hooks.slack.com" in lowered:
        return {"text": text}, {}
    if "api.line.me" in lowered:
        # LINE Messaging API: a channel access token is in the URL and the body
        # needs a recipient and a message array.
        line_token = url.rstrip("/").rsplit("/", 1)[-1]
        return {"to": payload.get("line_to", ""),
                "messages": [{"type": "text", "text": text}]}, \
            {"Authorization": f"Bearer {line_token}"}
    if "notify.line.me" in lowered:
        return {"message": text}, {}
    return {"text": text, "detail": payload}, {}


def _systemctl(*args: str) -> str:
    try:
        result = subprocess.run(["systemctl", *args], capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"unavailable: {type(exc).__name__}"
    return (result.stdout or result.stderr or "").strip()


def _service_state(unit: str) -> str:
    return _systemctl("show", unit, "-p", "ActiveState", "--value")


def _queue_diagnostics() -> tuple:
    """Ask the durable queue how deep it is, using the credentials the host
    already holds. A database outage must be visible even when the API still
    serves a cached catalog."""
    env = _read_env_file(Path("/etc/newbiegrader/api.env"))
    url = env.get("SUPABASE_URL")
    key = env.get("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError("api.env has no SUPABASE_URL/SUPABASE_KEY")
    request = urllib.request.Request(
        url.rstrip("/") + "/rest/v1/rpc/judge_queue_diagnostics", data=b"", method="POST",
        headers={"apikey": key, "Authorization": "Bearer " + key,
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload.get("queued"), payload.get("running")


def _read_env_file(path: Path) -> dict:
    values = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def _worker_units() -> list[str]:
    units = os.environ.get("NEWBIEGRADER_WORKER_UNITS", "newbiegrader-worker.service").split()
    return units if units and all(re.fullmatch(
        r"newbiegrader-worker(?:@[1-9][0-9]*)?\.service", unit) for unit in units) else []


def _journal_hits(since_minutes: int) -> list[str]:
    units = _worker_units()
    if not units:
        return ["invalid worker unit configuration"]
    filters = [argument for unit in units for argument in ("-u", unit)]
    try:
        result = subprocess.run(
            ["journalctl", *filters, "-u", "newbiegrader-api.service",
             "--since", f"{since_minutes} minutes ago", "--no-pager", "-o", "cat"],
            capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as exc:
        return [f"journal unavailable: {type(exc).__name__}"]
    hits = []
    for line in (result.stdout or "").splitlines():
        for pattern in JOURNAL_ERROR_PATTERNS:
            if pattern in line:
                hits.append(line.strip()[:200])
                break
    return hits


def _backup_age_hours(marker: Path) -> float | None:
    try:
        stamp = marker.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    try:
        moment = dt.datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=dt.timezone.utc)
    delta = dt.datetime.now(dt.timezone.utc) - moment
    return round(delta.total_seconds() / 3600.0, 2)


def _retention_health() -> tuple[bool, str]:
    """A successful backup does not prove that account retention ran."""
    timer = _service_state("newbiegrader-account-retention.timer")
    raw = _systemctl("show", "newbiegrader-account-retention.service",
                     "-p", "Result", "-p", "ExecMainStatus", "-p", "ExecMainExitTimestampMonotonic")
    fields = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    try:
        exited = int(fields["ExecMainExitTimestampMonotonic"]) / 1_000_000
        age = (time.monotonic() - exited) / 3600
        ok = (timer == "active" and fields["Result"] == "success"
              and fields["ExecMainStatus"] == "0" and exited > 0
              and 0 <= age <= RETENTION_MAX_AGE_H)
        return ok, (f"timer={timer} result={fields['Result']} exit={fields['ExecMainStatus']} "
                    f"last completion {age:.1f}h ago (limit {RETENTION_MAX_AGE_H}h)")
    except (KeyError, ValueError):
        return False, "retention completion unavailable"


def _extra_health_checks(raw: str) -> list[dict]:
    """Optional private-service checks are owned by the homeserver repository."""
    if not raw:
        return []
    try:
        from private_service_health import collect_checks as private_checks
        return private_checks(raw)
    except Exception:
        return [{"name": "optional health configuration", "ok": False,
                 "detail": "private service health integration unavailable"}]


def _primary_probe(url: str) -> None:
    """An optional root-configured tailnet probe detects masked primary outages."""
    parts = urllib.parse.urlsplit(url)
    address = ipaddress.ip_address(parts.hostname or '')
    if parts.scheme != 'http' or address not in ipaddress.ip_network('100.64.0.0/10') or parts.port != 9187 \
            or parts.path != '/health' or parts.query or parts.fragment or parts.username or parts.password:
        raise ValueError('invalid primary health destination')
    request = urllib.request.Request(url, headers={'Accept': 'application/json',
        'User-Agent': 'Newbiegrader-primary-watchdog/1', 'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=5) as response:
        raw = response.read(2049)
        if response.status != 200 or response.geturl() != url or len(raw) > 2048:
            raise ValueError('primary health unavailable')
        value = json.loads(raw)
    if value.get('ok') is not True or type(value.get('count')) is not int or value['count'] <= 0:
        raise ValueError('primary not ready')


def collect_checks() -> list[dict]:
    """Every check returns {name, ok, detail}. No check may raise."""
    checks: list[dict] = []

    def add(name: str, ok: bool, detail: str) -> None:
        checks.append({"name": name, "ok": bool(ok), "detail": str(detail)[:300]})

    # 1. The API answers and knows the whole catalog.
    try:
        health = _get_json(f"{API_BASE}/api/health")
        add("api health", health.get("ok") is True
            and health.get("count") == EXPECTED_PROBLEMS,
            f"ok={health.get('ok')} count={health.get('count')}")
    except Exception as exc:
        add("api health", False, f"{type(exc).__name__}: {exc}")

    # 2. The API is in the expected role and the queue is durable.
    try:
        version = _get_json(f"{API_BASE}/api/version")
        system = version.get("system") or {}
        add("api role and queue", system.get("role") == "api"
            and system.get("queue_mode") == "database",
            f"role={system.get('role')} queue={system.get('queue_mode')} "
            f"workers={system.get('judge_workers')}")
    except Exception as exc:
        add("api role and queue", False, f"{type(exc).__name__}: {exc}")

    # 3. The judge worker is up.
    units = _worker_units()
    valid = bool(units)
    states = {unit: _service_state(unit) for unit in units} if valid else {}
    add("judge worker", valid and all(state == "active" for state in states.values()),
        ", ".join(f"{unit}={state}" for unit, state in states.items())
        if valid else "invalid worker unit configuration")

    # 4. The tunnel that publishes the site is up.
    tunnel = _service_state("newbiegrader-tunnel.service")
    add("cloudflare tunnel", tunnel == "active", f"ActiveState={tunnel}")

    # 5. The durable queue is reachable. A database outage is invisible from
    #    the API alone once the catalog is cached, so ask the queue directly.
    try:
        queued, running = _queue_diagnostics()
        add("durable queue", True, f"queued={queued} running={running}")
    except Exception as exc:
        add("durable queue", False, f"{type(exc).__name__}: {exc}")

    # 6. The disk still has room for the next backup and the workspace.
    try:
        usage = shutil.disk_usage("/var/lib/newbiegrader")
        free_gb = round(usage.free / (1024 ** 3), 2)
        add("disk space", free_gb >= 2.0, f"{free_gb} GB free on /var/lib/newbiegrader")
    except OSError as exc:
        add("disk space", False, f"{type(exc).__name__}: {exc}")

    # 7. A backup exists and is recent enough.
    age = _backup_age_hours(DEFAULT_BACKUP_MARKER)
    if age is None:
        add("backup freshness", False, "no successful backup recorded")
    else:
        add("backup freshness", age <= BACKUP_MAX_AGE_H,
            f"last backup {age}h ago (limit {BACKUP_MAX_AGE_H}h)")

    try:
        ok, detail = _retention_health()
        add("account retention", ok, detail)
    except Exception as exc:
        add("account retention", False, type(exc).__name__ + ": maintenance status unavailable")

    # 8. The journal shows no repeating infrastructure failure.
    hits = _journal_hits(60)
    add("journal errors", not hits, f"{len(hits)} error lines in the last hour")

    # Optional for local-only hosts; production enables this fixed HTTPS origin.
    # A cached health route can pass even when a bridge key is misconfigured.
    public_url = os.environ.get("NEWBIEGRADER_PUBLIC_URL", "").strip()
    if public_url:
        try:
            _public_identity(public_url)
            add("public HTTPS", True, "anonymous identity reachable through public transport")
        except Exception as exc:
            add("public HTTPS", False, type(exc).__name__ + ": public transport unavailable")

    primary = os.environ.get("NEWBIEGRADER_PRIMARY_HEALTH_URL", "")
    if primary:
        try:
            _primary_probe(primary)
            add("primary backend", True, "primary API ready")
        except Exception:
            add("primary backend", False, "primary API unavailable; verify backup operation")
    checks.extend(_extra_health_checks(os.environ.get("NEWBIEGRADER_EXTRA_HEALTH_URLS", "")))
    return checks


# Only application-owned checks go to the learner community. Other services
# and unknown future host checks stay in the private homeserver destination.
CHECK_MESSAGES = {
    "primary backend": ("เครื่องหลัก Newbiegrader", "เว็บไซต์อาจกำลังใช้ homeserver สำรอง",
                        "ตรวจไฟ เครือข่าย API และ tunnel ของเครื่องหลัก"),
    "api health": ("ระบบเว็บ", "เว็บอาจใช้งานไม่ได้หรือรายการโจทย์ไม่ครบ", "ตรวจ API และรายการโจทย์"),
    "api role and queue": ("การตั้งค่าตรวจคำตอบ", "ระบบรับงานอาจทำงานไม่ถูกต้อง", "ตรวจ role และคิวฐานข้อมูลของ API"),
    "judge worker": ("ตัวตรวจคำตอบ", "คำตอบที่ส่งมาอาจรอคิวนานขึ้น", "ตรวจ worker ที่หยุดทำงาน"),
    "cloudflare tunnel": ("การเชื่อมต่อเว็บไซต์", "ผู้ใช้อาจเข้าเว็บไม่ได้", "ตรวจบริการ tunnel และเครือข่าย"),
    "durable queue": ("คิวตรวจคำตอบ", "อาจรับงานหรือดึงงานตรวจไม่ได้", "ตรวจการเชื่อมต่อฐานข้อมูล"),
    "disk space": ("พื้นที่เก็บข้อมูล Newbiegrader", "พื้นที่สำหรับงานตรวจและสำรองข้อมูลเหลือน้อย", "ตรวจพื้นที่ดิสก์ของ Newbiegrader"),
    "backup freshness": ("สำรองข้อมูล Newbiegrader", "ยังยืนยันสำเนาสำรองล่าสุดไม่ได้", "ตรวจงาน backup และเวลาที่สำเร็จล่าสุด"),
    "account retention": ("งานดูแลข้อมูลบัญชี", "งานล้างข้อมูลตามกำหนดยังไม่สำเร็จ", "ตรวจ timer และผลการทำงาน retention"),
    "journal errors": ("ข้อผิดพลาดระบบตรวจ", "พบข้อผิดพลาดในบันทึกช่วง 1 ชั่วโมงล่าสุด", "ตรวจ log ของ API และ worker"),
    "public HTTPS": ("เว็บไซต์จากภายนอก", "เส้นทางเข้าเว็บไซต์อาจขัดข้อง", "ตรวจ Pages, tunnel และ API"),
}


def _check_scope(name: str) -> str:
    return "newbiegrader" if name in CHECK_MESSAGES else "homeserver"


def _display(value: str, limit: int = 80) -> str:
    # Keep a label on one line and prevent labels from introducing Markdown.
    return re.sub(r"[\\`*_~<>@]", "", " ".join(str(value).split()))[:limit]


def _check_message(name: str) -> tuple[str, str, str]:
    if name in CHECK_MESSAGES:
        return CHECK_MESSAGES[name]
    if name.startswith("service "):
        return (_display(name[8:]), "บริการยังไม่พร้อมใช้งานผ่าน HTTPS",
                "ตรวจบริการ โหมดเครื่อง และการเชื่อมต่อ Tailscale")
    if name == "optional health configuration":
        return ("การตั้งค่าตรวจบริการส่วนตัว", "ยังตรวจสถานะบริการส่วนตัวไม่ได้",
                "ตรวจ configuration และโมดูล private service health")
    return (_display(name), "พบสถานะผิดปกติ", "ตรวจสถานะบริการและบันทึกของเครื่อง")


def build_payload(checks: list[dict], state: dict, label: str = "",
                  scope: str = "newbiegrader") -> dict:
    broken = [c for c in checks if not c["ok"]]
    previous = state.get("broken", [])
    where = label or socket.gethostname()
    title = "Newbiegrader" if scope == "newbiegrader" else "ระบบส่วนตัว / Homeserver"
    status = f"🔴 **{title} · พบปัญหา {len(broken)} รายการ**" if broken else f"🟢 **{title} · กลับมาปกติแล้ว**"
    lines = [status, f"🖥️ **เครื่อง:** {_display(where)}", ""]
    names = [c["name"] for c in broken] if broken else previous
    for name in names:
        heading, impact, action = _check_message(name)
        block = ([f"❌ **{heading}**", f"ผลกระทบ: {impact}", f"แนะนำ: {action}", ""]
                 if broken else [f"✅ {heading}"])
        # Discord content has a 2,000-character limit. Reserve room for footer.
        if len("\n".join(lines + block)) > 1750:
            lines.append("… ดูรายการเพิ่มเติมในบันทึก watchdog ของเครื่อง")
            break
        lines.extend(block)
    if not broken:
        lines.extend(["", "รายการตรวจในหมวดนี้ผ่านทั้งหมดแล้ว"])
    moment = dt.datetime.now(dt.timezone(dt.timedelta(hours=7)))
    lines.extend(["", f"🕒 {moment:%d/%m/%Y %H:%M:%S} (เวลาไทย)"])
    return {
        "text": "\n".join(lines), "host": where, "scope": scope,
        "embed": {
            "title": status.replace("**", ""),
            "description": "\n".join(lines[1:-2]).strip(),
            "color": 0xE74C3C if broken else 0x2ECC71,
            "footer": {"text": lines[-1]},
        },
        "broken": [c["name"] for c in broken], "checks": checks,
        "previous_state": previous,
    }


def notify_routes(checks: list[dict], state: dict, secret: dict, *,
                  label: str = "", dry_run: bool = False) -> tuple[dict, bool]:
    """Acknowledge each destination separately, after successful delivery only."""
    saved = {}
    failed = False
    for scope in ("newbiegrader", "homeserver"):
        selected = [c for c in checks if _check_scope(c["name"]) == scope]
        previous = state.get("routes", {}).get(scope)
        if previous is None:
            # Migrate an already-reported legacy incident without repeating it.
            previous = {"broken": [n for n in state.get("broken", [])
                                    if _check_scope(n) == scope]}
        before = sorted(previous.get("broken", []))
        broken = sorted(c["name"] for c in selected if not c["ok"])
        saved[scope] = {"broken": before, "notified": False}
        if broken == before:
            continue
        payload = build_payload(selected, previous, label or secret.get("label", ""), scope)
        if dry_run:
            print(json.dumps({"route": scope, "text": payload["text"]}, ensure_ascii=False))
            continue
        routes = secret.get("routes") or {}
        route = routes.get(scope) if routes else secret
        if not route:
            print(f"alert delivery failed ({scope}): destination missing", file=sys.stderr)
            failed = True
            continue
        payload["line_to"] = secret.get("to", "")
        try:
            _post_json(route["url"], payload, secret.get("token", ""))
        except (urllib.error.URLError, OSError) as exc:
            # Exception text may contain credential-bearing webhook URLs.
            print(f"alert delivery failed ({scope}): {type(exc).__name__}", file=sys.stderr)
            failed = True
            continue
        saved[scope] = {"broken": broken, "notified": True}
        print(f"alert sent ({scope}, {len(broken)} failing check(s))")
    return {"routes": saved,
            "broken": sorted(n for route in saved.values() for n in route["broken"])}, failed


def _load_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, sort_keys=True), encoding="utf-8")
    os.chmod(tmp, 0o600)
    tmp.replace(path)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--webhook-file", type=Path, default=DEFAULT_WEBHOOK_FILE)
    parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    parser.add_argument("--check-only", action="store_true",
                        help="report the checks and exit without contacting a webhook")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the webhook payload instead of sending it")
    parser.add_argument("--label", default="",
                        help="how this host is named in the message (default: the "
                             "label in the webhook file, else the hostname)")
    args = parser.parse_args(argv)

    checks = collect_checks()
    broken = sorted(c["name"] for c in checks if not c["ok"])
    state = _load_state(args.state_file)
    healthy = not broken

    for check in checks:
        mark = "ok  " if check["ok"] else "FAIL"
        print(f"{mark} {check['name']}: {check['detail']}")

    if args.check_only:
        return 0 if healthy else 1
    # A preview never changes notification acknowledgements or contacts Discord.
    if args.dry_run:
        notify_routes(checks, state, {}, label=args.label, dry_run=True)
        return 0 if healthy else 1
    secret = _read_secret(args.webhook_file)
    updated, failed = notify_routes(checks, state, secret, label=args.label)
    _save_state(args.state_file, updated)
    return 0 if healthy and not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
