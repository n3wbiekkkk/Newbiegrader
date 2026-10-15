#!/usr/bin/env python3
"""Run the whole judge on this machine: no cloud, no database, no build step.

This starts the real server (`server.py`) against an in-memory stand-in for the SQL
database, so everything works locally — registration, login, submissions, verdicts,
history, contests, rejudge, plagiarism and the admin pages. Nothing is written
anywhere: the data lives in the process and disappears when you stop it.

    python3 tools/dev_server.py                 # http://127.0.0.1:8000
    python3 tools/dev_server.py --port 8090
    python3 tools/dev_server.py --admin me@example.com

Notes:

* Google sign-in is unavailable here (it needs a publicly reachable redirect URI).
  Use the email + password form with any address you like.
* The judge runs your code with resource limits, but macOS does not enforce every
  one of them and the privilege drop needs Linux+root, so treat it as unsandboxed.
* To use a real database instead, run `python3 server.py` with SUPABASE_URL and
  SUPABASE_KEY set, and no `--port` wrapper.
"""

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))


def main() -> int:
    ap = argparse.ArgumentParser(description="Newbiegrader local development server")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--admin", default="admin@example.com",
                    help="address that gets administrator rights (default: %(default)s)")
    args = ap.parse_args()

    # Environment must be set before server.py is imported: it reads these at import.
    os.environ["SESSION_SECRET"] = "dev-only-secret"
    os.environ["SESSION_SECURE"] = "false"
    os.environ["SESSION_SAMESITE"] = "lax"
    os.environ["ADMIN_EMAILS"] = args.admin
    os.environ["SUPABASE_URL"] = ""      # keep the real database out of the way
    os.environ["SUPABASE_KEY"] = ""

    try:
        from fake_supabase import FakeSupabase
    except ImportError:
        print("tests/fake_supabase.py is missing: run this from a full checkout", file=sys.stderr)
        return 1

    import server
    import uvicorn

    server._sb = FakeSupabase()          # must be assigned after importing server
    print(f"[dev] http://{args.host}:{args.port}  — in-memory database (nothing is saved)")
    print(f"[dev] admin account: {args.admin}  (register it on the login page)")
    print(f"[dev] judge: workers={server.JUDGE_WORKERS} tests-at-once={server.JUDGE_JOBS} "
          f"memory-cap={server.MEMORY_CAP_MB}MB")
    uvicorn.run(server.app, host=args.host, port=args.port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
