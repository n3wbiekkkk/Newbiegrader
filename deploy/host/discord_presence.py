#!/usr/bin/env python3
"""Discord presence follows public HTTPS and the four workers; never sends messages.

The token is read from a systemd credential, never argv, env, or logs. No gateway
intents are requested. Existing REST watchdog delivery remains independent.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
from pathlib import Path
import random
import signal
import ssl
import stat
import subprocess
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request

from websockets.asyncio.client import connect
from websockets.exceptions import ConnectionClosed

LOG = logging.getLogger("newbiegrader.presence")
PERMANENT_CLOSE = {4004, 4010, 4011, 4012, 4013, 4014}
FRESH_SESSION_CLOSE = {4007, 4009}
IDENTIFY_GAP = 180  # At most 480 new sessions/day for this process, not 1,000.


class Reconnect(Exception):
    pass


class FatalGateway(Exception):
    pass


def gateway_url(value: str) -> str:
    parsed = urllib.parse.urlsplit(value)
    host = parsed.hostname or ""
    if parsed.scheme != "wss" or not (host == "gateway.discord.gg" or
            host.endswith(".discord.gg")) or parsed.username or parsed.password \
            or parsed.port not in (None, 443) or parsed.path not in ("", "/") \
            or parsed.query or parsed.fragment:
        raise ValueError("Invalid Discord gateway destination")
    return value.rstrip("/") + "/?v=10&encoding=json"


def read_token(path: Path) -> str:
    info = path.lstat()
    # systemd may deliver credentials as 0440 to root/the service's private GID.
    # Group write/execute, unrelated groups and all world access remain denied.
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o037 or (
            info.st_mode & 0o040 and info.st_gid not in (0, os.getegid())):
        raise ValueError("Discord credential must be a private regular file")
    token = json.loads(path.read_text(encoding="utf-8")).get("token", "")
    if not isinstance(token, str) or not token or any(c.isspace() for c in token):
        raise ValueError("Discord bot credential is missing or invalid")
    return token


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def get_json(url: str, token: str | None = None) -> dict:
    headers = {"Accept": "application/json", "Cache-Control": "no-cache",
               "User-Agent": "Newbiegrader-presence/1"}
    if token:
        if url != "https://discord.com/api/v10/gateway/bot":
            raise ValueError("Invalid authenticated destination")
        headers["Authorization"] = "Bot " + token
    request = urllib.request.Request(url, headers=headers)
    # Explicit TLS verification and no proxy/redirect-based credential forwarding.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}),
        NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context()))
    with opener.open(request, timeout=5) as response:
        if response.status != 200:
            raise ValueError("Non-200 response")
        body = response.read(65537)
    if len(body) > 65536:
        raise ValueError("Response exceeds bound")
    value = json.loads(body.decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Response is not an object")
    return value


def health_ok(public_url: str, units: list[str]) -> bool:
    try:
        p = urllib.parse.urlsplit(public_url)
        if p.scheme != "https" or not p.hostname or p.username or p.password \
                or p.path not in ("", "/") or p.query or p.fragment:
            return False
        expected = [f"newbiegrader-worker@{i}.service" for i in range(1, 5)]
        if units != expected:
            return False
        result = subprocess.run(["systemctl", "show", "--property=ActiveState", "--value", *units,
            "newbiegrader-api.service", "newbiegrader-tunnel.service"],
            capture_output=True, text=True, timeout=5)
        if result.returncode or result.stdout.split() != ["active"] * 6:
            return False
        local = get_json("http://127.0.0.1:8000/api/health")
        if local.get("ok") is not True or local.get("count") != 89:
            return False
        public = get_json(public_url.rstrip("/") + "/api/auth/me")
        return "user" in public and public["user"] is None
    except Exception:
        return False


def presence(online: bool) -> dict:
    return {"since": None, "activities": [{"name": "Newbiegrader website", "type": 3}]
            if online else [], "status": "online" if online else "invisible", "afk": False}


class Gateway:
    def __init__(self, token: str, check, interval: float = 30):
        self.token, self.check, self.interval = token, check, interval
        self.session_id = self.resume_url = None
        self.seq = None
        self.last_identify = -IDENTIFY_GAP
        self.connected_at = 0.0

    async def send(self, ws, op: int, data):
        await ws.send(json.dumps({"op": op, "d": data}, separators=(",", ":")))

    async def connection(self, ws):
        hello = json.loads(await asyncio.wait_for(ws.recv(), timeout=15))
        if hello.get("op") != 10:
            raise Reconnect()
        interval = float(hello["d"]["heartbeat_interval"]) / 1000
        if not 0.01 <= interval <= 120:
            raise Reconnect()
        ready = asyncio.Event()
        acknowledged = True

        async def receive():
            nonlocal acknowledged
            async for raw in ws:
                event = json.loads(raw)
                if isinstance(event.get("s"), int):
                    self.seq = event["s"]
                op, data = event.get("op"), event.get("d")
                if op == 11:
                    acknowledged = True
                elif op == 1:
                    await self.send(ws, 1, self.seq)
                elif op == 7:
                    raise Reconnect()
                elif op == 9:
                    if not data:
                        self.session_id = self.resume_url = None
                        self.seq = None
                    await asyncio.sleep(random.uniform(1, 5))
                    raise Reconnect()
                elif op == 0 and event.get("t") in ("READY", "RESUMED"):
                    if event["t"] == "READY":
                        gateway_url(data["resume_gateway_url"])
                        self.session_id = data["session_id"]
                        self.resume_url = data["resume_gateway_url"]
                    # A resumed session must also pass a fresh health check.
                    await self.send(ws, 3, presence(False))
                    self.connected_at = time.monotonic()
                    ready.set()
                    LOG.info("Discord gateway ready")
            raise Reconnect()

        async def heartbeat():
            nonlocal acknowledged
            await asyncio.sleep(interval * random.random())
            while True:
                if not acknowledged:
                    raise Reconnect()
                acknowledged = False
                await self.send(ws, 1, self.seq)
                await asyncio.sleep(interval)

        async def update_presence():
            await asyncio.wait_for(ready.wait(), timeout=30)
            previous = None
            while True:
                try:
                    healthy = await asyncio.wait_for(asyncio.to_thread(self.check), timeout=20)
                except Exception:
                    healthy = False
                if healthy != previous:
                    await self.send(ws, 3, presence(healthy))
                    LOG.info("Website presence: %s", "online" if healthy else "offline")
                    previous = healthy
                await asyncio.sleep(self.interval)

        tasks = [asyncio.create_task(f()) for f in (receive, heartbeat, update_presence)]
        try:
            if self.session_id is not None and self.seq is not None:
                await self.send(ws, 6, {"token": self.token, "session_id": self.session_id,
                                       "seq": self.seq})
            else:
                self.last_identify = time.monotonic()
                await self.send(ws, 2, {"token": self.token, "intents": 0,
                    "properties": {"os": "linux", "browser": "newbiegrader-health",
                                   "device": "newbiegrader-health"},
                    "presence": presence(False)})
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except asyncio.CancelledError:
            await ws.close(code=1000)
            raise
        except Exception:
            # A non-normal close retains a resumable session. Never log payloads.
            await ws.close(code=4000)
            raise
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def run(self):
        delay = 2.0
        while True:
            try:
                if self.session_id is None:
                    await asyncio.sleep(max(0, IDENTIFY_GAP -
                        (time.monotonic() - self.last_identify)))
                metadata = await asyncio.to_thread(get_json,
                    "https://discord.com/api/v10/gateway/bot", self.token)
                if not self.session_id:
                    budget = metadata["session_start_limit"]
                    if budget["remaining"] <= 0:
                        await asyncio.sleep(max(60, budget["reset_after"] / 1000))
                        continue
                url = gateway_url(self.resume_url or metadata["url"])
                async with connect(url, ssl=ssl.create_default_context(), proxy=None,
                        compression=None, ping_interval=None, open_timeout=15,
                        close_timeout=5, max_size=1024 * 1024, max_queue=4,
                        logger=logging.getLogger("newbiegrader.websocket")) as ws:
                    await self.connection(ws)
            except ConnectionClosed as exc:
                code = exc.rcvd.code if exc.rcvd else None
                if code in PERMANENT_CLOSE:
                    raise FatalGateway("Discord configuration rejected") from None
                if code in FRESH_SESSION_CLOSE:
                    self.session_id = self.resume_url = None
                    self.seq = None
            except urllib.error.HTTPError as exc:
                if exc.code in (401, 403):
                    raise FatalGateway("Discord credential rejected") from None
                if exc.code == 429:
                    try:
                        retry = float(exc.headers.get("Retry-After", "60"))
                    except ValueError:
                        retry = 60
                    await asyncio.sleep(max(1, min(3600, retry)))
                LOG.warning("Discord discovery unavailable")
            except (OSError, ValueError, KeyError, TimeoutError, Reconnect):
                LOG.warning("Discord connection unavailable; reconnect scheduled")
            if self.connected_at and time.monotonic() - self.connected_at > 120:
                delay = 2.0
                self.connected_at = 0.0
            await asyncio.sleep(delay + random.uniform(0, 1))
            delay = min(120, delay * 2)


async def main():
    path = Path(os.environ["CREDENTIALS_DIRECTORY"]) / "discord-alert"
    token = read_token(path)
    public = os.environ["NEWBIEGRADER_PUBLIC_URL"]
    units = os.environ.get("NEWBIEGRADER_WORKER_UNITS", "").split()
    bot = Gateway(token, lambda: health_ok(public, units))
    task = asyncio.create_task(bot.run())
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, task.cancel)
    with contextlib.suppress(asyncio.CancelledError):
        await task


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    # Wire-level WebSocket logs could contain the Identify token.
    logging.getLogger("websockets").setLevel(logging.CRITICAL)
    logging.getLogger("newbiegrader.websocket").setLevel(logging.CRITICAL)
    try:
        asyncio.run(main())
    except Exception as exc:
        where = traceback.extract_tb(exc.__traceback__)[-1]
        LOG.error("Discord presence stopped (%s at %s:%d)",
                  type(exc).__name__, where.name, where.lineno)
        raise SystemExit(1) from None
