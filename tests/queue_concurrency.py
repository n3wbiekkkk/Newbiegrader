"""Concurrent queue/lease rehearsal against disposable PostgreSQL only.

python tests/queue_concurrency.py --container newbiegrader-ec2-sql
Never point this at production. No program is executed by these fixtures.
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
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
    if query("select count(*) from public.judge_jobs") != "0":
        raise SystemExit("REFUSED: disposable queue must start empty")
    nonce = uuid.uuid4().hex

    def admit(index):
        payload = json.dumps({"kind": "submit", "user_email": f"{nonce}-{index}@example.invalid",
                              "problem": "synthetic", "language": "python", "source": "pass"})
        return json.loads(query(f"select public.judge_queue_admit('{payload}',16,true,0,0)"))

    with ThreadPoolExecutor(max_workers=4) as pool:
        admitted = list(pool.map(admit, range(4)))
    ids = [row["job"]["id"] for row in admitted]
    assert len(set(ids)) == 4

    def claim(index):
        row = query(f"select public.judge_queue_claim('synthetic-{nonce}-{index}',60)")
        return (index, json.loads(row) if row else None)

    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = [(index, job) for index, job in pool.map(claim, range(8)) if job]
    assert len(claimed) == 4 and {job["id"] for _, job in claimed} == set(ids)
    index, old = claimed[0]
    # Simulate a crashed worker by expiring only its disposable lease. No wait,
    # production update, running submission or dangerous payload is involved.
    query(f"update public.judge_jobs set lease_until=now()-interval '1 second' where id='{old['id']}'")
    fresh = json.loads(query(f"select public.judge_queue_claim('synthetic-{nonce}-replacement',60)"))
    assert fresh["id"] == old["id"] and fresh["attempt"] == old["attempt"] + 1

    def finish(owner, attempt, error="synthetic worker stop"):
        return json.loads(query(f"select public.judge_queue_finish('{old['id']}','{owner}',{attempt},null,null,'{error}')"))

    assert finish(f"synthetic-{nonce}-{index}", old["attempt"])["applied"] is False
    assert finish(f"synthetic-{nonce}-replacement", fresh["attempt"])["applied"] is True
    before = query(f"select to_jsonb(j) from public.judge_jobs j where id='{old['id']}'")
    # Retried completion acknowledges the existing terminal state without
    # overwriting it. 'applied=true' is the RPC's documented idempotent ACK.
    assert finish(f"synthetic-{nonce}-replacement", fresh["attempt"], "different retry error")["applied"] is True
    assert query(f"select to_jsonb(j) from public.judge_jobs j where id='{old['id']}'") == before
    assert query("select count(*) from public.submissions") == "0"
    quoted = ",".join("'" + ident + "'" for ident in ids)
    query(f"delete from public.judge_jobs where id in ({quoted})")
    print(json.dumps({"admitted": 4, "claim_clients": 8, "distinct_claims": 4,
                      "expired_lease_recovered": True, "stale_finish_rejected": True,
                      "duplicate_finish_idempotent": True, "submission_rows": 0}))


if __name__ == "__main__":
    main()
