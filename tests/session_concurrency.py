"""Real multi-connection session races; disposable CI database ONLY."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser(); parser.add_argument('--container'); args = parser.parse_args()
    prefix = (['docker','exec',args.container,'psql','-U','postgres','-d','newbiegrader_test']
              if args.container else ['psql'])
    def query(sql):
        result = subprocess.run(prefix + ['-X','-qAt','-v','ON_ERROR_STOP=1','-c',sql],
            capture_output=True,text=True,check=True,timeout=30)
        return result.stdout.strip()
    def value(sql): return json.loads(query('select ' + sql))
    if query('select current_database()') != 'newbiegrader_test':
        raise SystemExit('REFUSED: expected disposable newbiegrader_test')
    nonce = uuid.uuid4().hex; email = 'session-' + nonce + '@example.invalid'
    subject = str(uuid.uuid4())
    value(f"public.auth_google_identity('{email}','synthetic-{nonce}','Synthetic')")
    hashed = lambda label: hashlib.sha256((nonce + label).encode()).hexdigest()
    def start(label, pending=False, version=1):
        return value(f"public.auth_session_start('{hashed(label)}','{email}',{version},true,"
                     f"{'true' if pending else 'false'},'google','',array[]::text[])")
    def identity(label, mode='session'):
        return value(f"public.auth_session_identity('{hashed(label)}','{mode}',array[]::text[])")
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert all(r['valid'] for r in pool.map(lambda i: start('device'+str(i)),range(8)))
    assert start('pending',True)['valid']
    with ThreadPoolExecutor(max_workers=8) as pool:
        finishes = list(pool.map(lambda _: identity('pending','finish'),range(32)))
    assert sum(r['valid'] for r in finishes)==1,'Concurrent OAuth consumption had multiple winners'
    with ThreadPoolExecutor(max_workers=8) as pool:
        revoked = list(pool.map(lambda _: value(f"public.auth_session_revoke(array['{hashed('pending')}'])"),range(8)))
    assert all(r['ok'] for r in revoked)
    with ThreadPoolExecutor(max_workers=8) as pool:
        assert not any(r['valid'] for r in pool.map(lambda _: identity('pending'),range(16)))
    assert identity('device0')['valid'],'Revocation affected another device'
    def replace(_):
        return value(f"public.auth_email_complete('{email}','{subject}','pbkdf2$synthetic','Owner')")
    with ThreadPoolExecutor(max_workers=8) as pool:
        tasks=[pool.submit(start,'racing'+str(i)) for i in range(7)]
        tasks.append(pool.submit(replace,0));results=[f.result() for f in tasks]
    assert results[-1]['auth_version']==2
    assert all(not identity('device'+str(i))['valid'] for i in range(8))
    assert all(not identity('racing'+str(i))['valid'] for i in range(7))
    assert start('fresh',version=2)['valid']
    print(json.dumps({'parallel_device_logins':8,'parallel_handoff_attempts':32,'handoff_winners':1,
        'idempotent_parallel_revokes':8,'post_revoke_checks_denied':16,
        'password_change_racing_logins':7,'stale_credential_sessions_denied':True}))


if __name__=='__main__': main()
