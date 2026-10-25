#!/usr/bin/env python3
"""Observe service/peer health; optional privileged metrics export aggregates only."""
import argparse
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.request


def local_node(config, now):
    units = config["units"]
    result = subprocess.run(["systemctl", "show", *units, "-p", "ActiveState", "-p", "MainPID"],
                            text=True, capture_output=True, timeout=5, check=True)
    active = sum("ActiveState=active" in block and "MainPID=0" not in block
                 for block in result.stdout.strip().split("\n\n"))
    # An active supervisor can be backing off after database/claim failures.
    journal = subprocess.run(["journalctl", "--since=-30sec", "--no-pager", "-o", "cat",
                              *[arg for unit in units for arg in ("-u", unit)]],
                             capture_output=True, text=True, timeout=5)
    ready = active if journal.returncode == 0 and "worker unavailable:" not in journal.stdout else 0
    return {"id": config["id"], "configured_workers": len(units),
            "active_workers": active, "ready_workers": ready,
            "online": True, "checked_at": now}


def peer_node(peer, now):
    unavailable = {"id": peer["id"], "configured_workers": peer["workers"],
                   "active_workers": 0, "ready_workers": 0, "online": False, "checked_at": now}
    try:
        request = urllib.request.Request(peer["url"], headers={"User-Agent": "Newbiegrader-fleet-observer/1"})
        with urllib.request.urlopen(request, timeout=3) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            return unavailable
        values = {}
        label = '{node="' + peer["id"] + '"}'
        for line in raw.decode("utf-8").splitlines():
            parts = line.split()
            if len(parts) == 2 and parts[0].endswith(label):
                key = parts[0][:-len(label)]
                if key in ("newbiegrader_node_workers_active", "newbiegrader_node_workers_ready",
                           "newbiegrader_node_snapshot_seconds"):
                    values[key] = float(parts[1])
        active = values["newbiegrader_node_workers_active"]
        ready = values["newbiegrader_node_workers_ready"]
        stamp = values["newbiegrader_node_snapshot_seconds"]
        if (not all(math.isfinite(v) for v in (active, ready, stamp))
                or not -5 <= now - stamp <= 45
                or not 0 <= ready <= active <= peer["workers"]
                or int(active) != active or int(ready) != ready):
            return unavailable
        return {**unavailable, "online": True, "active_workers": int(active),
                "ready_workers": int(ready), "checked_at": stamp}
    except (OSError, ValueError, KeyError, UnicodeError):
        return unavailable


def app_metrics(config):
    lines = []
    for name, app in config.get("apps", {}).items():
        if not re.fullmatch(r"[a-z0-9_-]{1,32}", name):
            continue
        started = time.monotonic()
        ok = False
        try:
            request = urllib.request.Request(app["url"], headers={
                "User-Agent": "Newbiegrader-fleet-observer/1", "Accept": "application/json"})
            with urllib.request.urlopen(request, timeout=3) as response:
                raw = response.read(16385)
            if len(raw) > 16384:
                raise ValueError("oversized health response")
            value = json.loads(raw)
            if app["kind"] == "nextcloud":
                ok = (value.get("installed") is True and value.get("maintenance") is False
                      and value.get("needsDbUpgrade") is False)
            elif app["kind"] == "grader":
                ok = value.get("ok") is True and value.get("count") == 100
        except (OSError, ValueError, TypeError, KeyError, AttributeError):
            pass
        labels = '{node=' + json.dumps(config["id"]) + ',app=' + json.dumps(name) + '}'
        lines.extend(['newbiegrader_app_up'+labels+' '+str(int(ok)),
                      'newbiegrader_app_response_seconds'+labels+' '+str(time.monotonic()-started)])
    return lines


def atomic(path, content, mode, gid=None):
    path = Path(path)
    fd, temp = tempfile.mkstemp(prefix=".snapshot-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            stream.write(content)
            os.fchmod(stream.fileno(), mode)
            if gid is not None:
                os.fchown(stream.fileno(), 0, gid)
        os.replace(temp, path)
    finally:
        Path(temp).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text())
    now = time.time()
    node = local_node(config, now)
    label = '{node="' + node["id"] + '"}'
    metrics = "\n".join([
        'newbiegrader_node_workers_active' + label + ' ' + str(node['active_workers']),
        'newbiegrader_node_workers_ready' + label + ' ' + str(node['ready_workers']),
        'newbiegrader_node_workers_configured' + label + ' ' + str(node['configured_workers']),
        'newbiegrader_node_snapshot_seconds' + label + ' ' + str(now),
    ]) + "\n"
    metrics += "\n".join(app_metrics(config)) + "\n"
    import hardware_metrics
    metrics += "\n".join(hardware_metrics.collect(config["id"])) + "\n"
    if config.get("judge_metrics"):
        import judge_metrics
        metrics += "\n".join(judge_metrics.collect(config["judge_metrics"], now)) + "\n"
    atomic(config["metrics_file"], metrics, 0o644)
    nodes = [node] + [peer_node(peer, now) for peer in config["peers"]]
    snapshot = {"schema": 1, "checked_at": now, "nodes": sorted(nodes, key=lambda n: n["id"])}
    atomic(config["output"], json.dumps(snapshot), 0o640, config["output_gid"])
    print(json.dumps({"nodes": [{"id": n["id"], "ready": n["ready_workers"], "online": n["online"]} for n in nodes]}))


if __name__ == "__main__":
    main()
