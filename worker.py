#!/usr/bin/env python3
"""Run dedicated database-backed judge workers without an HTTP listener."""
from __future__ import annotations

import argparse
import asyncio
import os


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true",
                        help="validate isolation/database read-only, then exit without claiming jobs")
    args = parser.parse_args(argv)
    os.environ.setdefault("GRADER_ROLE", "worker")
    if os.environ["GRADER_ROLE"] != "worker":
        raise SystemExit("worker.py requires GRADER_ROLE=worker")
    import server

    try:
        asyncio.run(server.validate_runtime() if args.check else server.serve_workers())
        if args.check:
            print("Worker preflight passed; no jobs claimed")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
