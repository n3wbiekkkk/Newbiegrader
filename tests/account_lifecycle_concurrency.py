"""Deletion/admission races in disposable PostgreSQL; never execute user code."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--container')
    args = parser.parse_args()
    prefix = (['docker', 'exec', args.container, 'psql', '-U', 'postgres', '-d', 'newbiegrader_test']
              if args.container else ['psql'])
    def query(sql):
        result = subprocess.run(prefix + ['-X', '-t', '-A', '-v', 'ON_ERROR_STOP=1', '-c', sql],
                                check=True, capture_output=True, text=True, timeout=20)
        return result.stdout.strip()
    if query('select current_database()') != 'newbiegrader_test':
        raise SystemExit('REFUSED: expected disposable database newbiegrader_test')
    for _ in range(20):
        email = 'erase-race-' + uuid.uuid4().hex + '@example.invalid'
        query("insert into public.users(email,password_hash,email_verified_at,auth_version) "
              f"values('{email}','pbkdf2$synthetic',now(),1)")
        payload = json.dumps({'user_email': email, 'kind': 'submit', 'problem': 'synthetic',
                              'language': 'python', 'source': 'pass'})
        statements = [f"select public.account_delete_begin('{email}')",
                      f"select public.judge_queue_admit('{payload}',1000,true,0,0)"]
        with ThreadPoolExecutor(max_workers=2) as pool:
            deleted, admitted = list(pool.map(lambda sql: json.loads(query(sql)), statements))
        if deleted.get('pending'):
            assert admitted.get('status_code') == 403, (deleted, admitted)
            assert query(f"select count(*) from public.judge_jobs where user_email='{email}'") == '0'
            # Two completion callers converge and retain exactly one audit event.
            before = int(query('select count(*) from public.account_audit'))
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: json.loads(query(
                    f"select public.account_delete_finish('{email}')")), range(2)))
            assert all(r.get('ok') for r in results), results
            assert int(query('select count(*) from public.account_audit')) == before + 1
        else:
            assert deleted.get('busy') and admitted.get('job'), (deleted, admitted)
            assert query(f"select count(*) from public.account_deletion_work where email='{email}'") == '0'
            query(f"delete from public.judge_jobs where user_email='{email}'")
            query(f"delete from public.users where email='{email}'")
    print(json.dumps({'deletion_admission_races': 20, 'invariant': 'pending deletion or admitted job, never both'}))


if __name__ == '__main__':
    main()
