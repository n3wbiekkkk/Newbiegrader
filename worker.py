#!/usr/bin/env python3
"""Run dedicated database-backed judge workers without an HTTP listener."""
from __future__ import annotations

import asyncio
import os


def main() -> None:
    os.environ.setdefault("GRADER_ROLE", "worker")
    if os.environ["GRADER_ROLE"] != "worker":
        raise SystemExit("worker.py requires GRADER_ROLE=worker")
    import server

    try:
        asyncio.run(server.serve_workers())
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
