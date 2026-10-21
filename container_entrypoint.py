#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Select the container's HTTP or dedicated-worker role."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    role = os.environ.get("GRADER_ROLE", "combined").strip().lower()
    if role == "worker":
        os.execv(sys.executable, [sys.executable, str(Path(__file__).with_name("worker.py"))])
    if role not in ("combined", "api"):
        raise SystemExit("GRADER_ROLE must be combined, api, or worker")
    try:
        port = int(os.environ.get("PORT", "8000"))
    except ValueError:
        raise SystemExit("PORT must be an integer between 1 and 65535")
    if not 1 <= port <= 65535:
        raise SystemExit("PORT must be an integer between 1 and 65535")
    os.execv(sys.executable, [sys.executable, "-m", "uvicorn", "server:app",
                             "--host", "0.0.0.0", "--port", str(port)])


if __name__ == "__main__":
    main()
