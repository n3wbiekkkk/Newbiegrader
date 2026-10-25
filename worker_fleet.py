"""Bounded, allowlisted display of observed fleet capacity, not admission control."""
import json
import math
import os
from pathlib import Path
import re
import stat
import time

MAX_AGE_S = 45
MAX_BYTES = 16384
NODE_ID = re.compile(r"[a-z0-9][a-z0-9-]{0,47}\Z")


def validate_snapshot(value, *, now=None):
    now = time.time() if now is None else now
    if not isinstance(value, dict) or value.get("schema") != 1:
        raise ValueError("invalid fleet schema")
    checked = value.get("checked_at")
    if type(checked) not in (int, float) or not math.isfinite(checked) or not -5 <= now - checked <= MAX_AGE_S:
        raise ValueError("stale fleet snapshot")
    nodes = value.get("nodes")
    if not isinstance(nodes, list) or not 1 <= len(nodes) <= 16:
        raise ValueError("invalid fleet nodes")
    result, seen = [], set()
    for node in nodes:
        if not isinstance(node, dict):
            raise ValueError("invalid fleet node")
        name = node.get("id")
        if not isinstance(name, str) or not NODE_ID.fullmatch(name) or name in seen:
            raise ValueError("invalid or duplicate node id")
        seen.add(name)
        configured, active, ready = (node.get(k) for k in
                                     ("configured_workers", "active_workers", "ready_workers"))
        if any(type(n) is not int for n in (configured, active, ready)) or not 0 <= ready <= active <= configured <= 128:
            raise ValueError("invalid fleet capacity")
        online = node.get("online")
        sampled = node.get("checked_at")
        if type(online) is not bool or type(sampled) not in (int, float) or not math.isfinite(sampled):
            raise ValueError("invalid node health")
        fresh = -5 <= now - sampled <= MAX_AGE_S
        healthy = online and fresh
        result.append({"id": name, "online": healthy,
                       "configured_workers": configured,
                       "active_workers": active if healthy else 0,
                       "ready_workers": ready if healthy else 0,
                       "checked_at": sampled})
    return {"status": "ok", "scope": "fleet", "checked_at": checked,
            "workers": sum(n["ready_workers"] for n in result),
            "active_workers": sum(n["active_workers"] for n in result),
            "configured_workers": sum(n["configured_workers"] for n in result),
            "nodes": result}


def read_snapshot(path, *, now=None):
    """A failed configured observer is unknown, never a static fallback count."""
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            info = os.fstat(fd)
            if (not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.geteuid())
                    or info.st_mode & 0o022 or info.st_nlink != 1 or info.st_size > MAX_BYTES):
                raise ValueError("unsafe fleet snapshot")
            with os.fdopen(fd, "rb", closefd=False) as stream:
                data = stream.read(MAX_BYTES + 1)
            if len(data) > MAX_BYTES:
                raise ValueError("oversized fleet snapshot")
            return validate_snapshot(json.loads(data), now=now)
        finally:
            os.close(fd)
    except (OSError, ValueError, TypeError, UnicodeError):
        return {"status": "unavailable", "scope": "fleet", "workers": None,
                "active_workers": None, "configured_workers": None, "nodes": []}
