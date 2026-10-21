# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Real PostgreSQL concurrency canaries. ONLY the disposable CI test database.

CI: python tests/auth_concurrency.py
Local: python tests/auth_concurrency.py --container newbiegrader-email-sql
Never target production. No SMTP or real identities are involved.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--container")
    args = parser.parse_args()
    prefix = (["docker", "exec", args.container, "psql", "-U", "postgres", "-d", "newbiegrader_test"]
              if args.container else ["psql"])
    def query(sql):
        result = subprocess.run(prefix + ["-X", "-t", "-A", "-v", "ON_ERROR_STOP=1", "-c", sql],
                                check=True, capture_output=True, text=True, timeout=20)
        return result.stdout.strip()
    if query("select current_database()") != "newbiegrader_test":
        raise SystemExit("REFUSED: expected disposable database newbiegrader_test")
    nonce = uuid.uuid4().hex
    email_key = hashlib.sha256(nonce.encode()).hexdigest()
    network_key = hashlib.sha256((nonce + "network").encode()).hexdigest()
    budget_sql = "select public.auth_email_budget('%s','%s','request')" % (email_key, network_key)
    with ThreadPoolExecutor(max_workers=8) as pool:
        budget = list(pool.map(lambda _: json.loads(query(budget_sql)), range(8)))
    assert sum(r["allowed"] for r in budget) == 1, budget
    email = "concurrent-" + nonce + "@example.invalid"
    subject = "synthetic-google-" + nonce
    claim_sql = "select public.auth_google_identity('%s','%s','Synthetic')" % (email, subject)
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: json.loads(query(claim_sql)), range(8)))
    assert all(r["auth_version"] == 1 and r["email"] == email for r in claims)
    assert query("select count(*) from public.users where email = '%s'" % email) == "1"
    print(json.dumps({"budget_clients": 8, "allowed_sends": 1,
                      "google_claim_clients": 8, "identity_rows": 1, "auth_version": 1}))


if __name__ == "__main__":
    main()
