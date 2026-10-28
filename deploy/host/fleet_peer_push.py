#!/usr/bin/env python3
"""Push one selected node's numeric worker observations to a fixed private peer."""
import argparse
import json
import math
from pathlib import Path
import time
import urllib.request

FIELDS = ('active', 'ready', 'configured')


def node_metrics(raw, node, *, now=None):
    """Exclude optional hardware, application, queue and other-node metrics."""
    now = time.time() if now is None else now
    names = {f'newbiegrader_node_workers_{field}' for field in FIELDS}
    names.add('newbiegrader_node_snapshot_seconds')
    suffix = '{node="' + node + '"}'
    values = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) != 2 or not parts[0].endswith(suffix):
            continue
        name = parts[0][:-len(suffix)]
        if name not in names:
            continue
        if name in values:
            raise ValueError('duplicate node metric')
        value = float(parts[1])
        if not math.isfinite(value):
            raise ValueError('nonfinite node metric')
        values[name] = value
    if set(values) != names:
        raise ValueError('missing node metrics')
    counts = [values[f'newbiegrader_node_workers_{field}'] for field in FIELDS]
    active, ready, configured = counts
    if any(int(n) != n for n in counts) or not 0 <= ready <= active <= configured <= 128:
        raise ValueError('invalid node capacity')
    if not -5 <= now - values['newbiegrader_node_snapshot_seconds'] <= 45:
        raise ValueError('stale node metrics')
    return ''.join(name + suffix + ' ' + str(values[name]) + '\n' for name in sorted(names))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('--metrics')
    source.add_argument('--metrics-url')
    parser.add_argument('--node', required=True)
    parser.add_argument('--destination', required=True)
    args = parser.parse_args()
    # The root-owned unit fixes the destination. Receiver allows only this
    # tailnet source address, one exact path and a bounded PUT body.
    try:
        if args.metrics_url:
            request = urllib.request.Request(args.metrics_url,
                headers={'User-Agent': 'Newbiegrader-peer-relay/1'})
            with urllib.request.urlopen(request, timeout=4) as response:
                if response.status != 200 or response.geturl() != args.metrics_url:
                    raise ValueError('invalid remote metrics response')
                raw = response.read(2 * 1024 * 1024 + 1).decode('utf-8')
        else:
            with Path(args.metrics).open() as source:
                raw = source.read(2 * 1024 * 1024 + 1)
        if len(raw) > 2 * 1024 * 1024:
            raise ValueError('oversized metrics')
        body = node_metrics(raw, args.node).encode()
        request = urllib.request.Request(args.destination, data=body, method='PUT',
                                         headers={'Content-Type': 'text/plain'})
        with urllib.request.urlopen(request, timeout=4) as response:
            ok = response.status in (200, 201, 204)
    except (OSError, ValueError):
        ok = False
    # An unavailable primary is expected during failover; local observation must
    # continue so the backup API can still report its own fresh capacity.
    print(json.dumps({'peer_push_ok': ok}))


if __name__ == '__main__':
    main()
