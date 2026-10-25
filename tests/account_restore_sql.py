#!/usr/bin/env python3
"""Real PostgreSQL erasure reconciliation, synthetic data, rollback cleanup."""
import datetime as dt
import hashlib
import json
from pathlib import Path
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from deploy.host.reconcile_account_restore import capture_query, reconciliation_sql, validate_state


def sql(query):
    result = subprocess.run(['psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1'],
                            input=query, text=True, capture_output=True, timeout=120)
    if result.returncode:
        # All inputs in this file are synthetic. Do not reuse this diagnostic
        # wrapper with real snapshots, whose SQL can contain personal data.
        raise RuntimeError(result.stderr)
    return result.stdout.strip()


def check(condition, message):
    if not condition:
        raise AssertionError(message)


def main():
    check(sql('select current_database();') == 'newbiegrader_test',
          'REFUSED: expected disposable database newbiegrader_test')
    # Everything runs inside one connection and transaction. Reconciliation's
    # BEGIN/COMMIT wrappers are removed here so cleanup always rolls back.
    setup = """
    begin;
    insert into public.users(email,name,password_hash,email_verified_at,auth_version)
      values ('restore-erased@example.invalid','Erased','pbkdf2$old',now(),1),
             ('restore-pending@example.invalid','Pending','pbkdf2$old',now(),1),
             ('restore-survivor@example.invalid','Survivor','pbkdf2$old',now(),1);
    insert into public.submissions(problem,language,user_email,verdict,code,results)
      select 'restore-case','python',email,'AC','PRIVATE_SOURCE','[{"expected":"PRIVATE_CASE"}]'
      from public.users where email like 'restore-%@example.invalid';
    insert into public.web_sessions(token_hash,user_email,auth_version,expires_at,activated,provider)
      values(repeat('c',64),'restore-erased@example.invalid',1,now()+interval '1 day',true,'password'),
            (repeat('d',64),'restore-survivor@example.invalid',1,now()+interval '1 day',true,'password');
    insert into public.profiles(user_email) values('restore-erased@example.invalid');
    insert into public.judge_jobs(problem,language,user_email,status,source,lease_until)
      values('restore-case','python','restore-erased@example.invalid','running','OLD_SOURCE',now()+interval '1 hour');
    insert into public.judge_quota_events(user_email,kind) values('restore-erased@example.invalid','submit');
    insert into public.reports(problem,user_email,message) values('restore-case','restore-erased@example.invalid','OLD_REPORT');
    insert into public.contests(id,starts_at,ends_at,created_by)
      values('restore-contest',now(),now()+interval '1 day','restore-erased@example.invalid');
    insert into public.contest_registrations(contest_id,user_email)
      values('restore-contest','restore-erased@example.invalid');
    insert into public.contest_announcements(id,contest_id,created_by)
      values('00000000-0000-0000-0000-00000000aaaa','restore-contest','restore-erased@example.invalid');
    insert into public.admins(email,created_by) values('restore-erased@example.invalid','restore-erased@example.invalid');
    -- Deliberately wrong OLD salt and stale deletion work from the backup.
    update public.account_privacy_salt set salt='old-unrelated-salt';
    insert into public.account_deletion_work(email) values('stale-backup-work@example.invalid');
    """
    now = dt.datetime.now(dt.timezone.utc)
    salt = 'current-independent-synthetic-salt'
    def block(email, age):
        return {'email_hash': hashlib.sha256((salt + email).encode()).hexdigest(),
                'requested_at': (now - dt.timedelta(days=age)).isoformat(),
                'expires_at': (now + dt.timedelta(days=90-age)).isoformat()}
    state = {'format': 1, 'captured_at': now.isoformat(),
             'salt': [{'singleton': True, 'salt': salt}],
             'blocks': [block('restore-erased@example.invalid', 1), block('restore-pending@example.invalid', 100)],
             'work': [{'email': 'restore-pending@example.invalid',
                       'auth_subject': '00000000-0000-0000-0000-00000000bbbb',
                       'requested_at': (now - dt.timedelta(days=100)).isoformat()}],
             'audit': [{'id': '00000000-0000-0000-0000-00000000cccc',
                        'created_at': (now-dt.timedelta(hours=1)).isoformat(),
                        'event': 'account_deleted', 'counts': {'submissions': 1}}]}
    validate_state(state, (now - dt.timedelta(days=2)).isoformat())
    reconcile = reconciliation_sql(state).removeprefix('begin;').removesuffix('rollback;')
    assertions = """
    do $$ begin
      if exists(select 1 from public.users where email in ('restore-erased@example.invalid','restore-pending@example.invalid')) then raise exception 'erased account resurrected'; end if;
      if exists(select 1 from public.submissions where user_email in ('restore-erased@example.invalid','restore-pending@example.invalid')) then raise exception 'private history resurrected'; end if;
      if not exists(select 1 from public.submissions where user_email='restore-survivor@example.invalid') then raise exception 'survivor history removed'; end if;
      if exists(select 1 from public.web_sessions) then raise exception 'old browser credentials survived'; end if;
      if (public.auth_session_identity(repeat('c',64),'session',array[]::text[])->>'valid')::boolean then raise exception 'old session valid'; end if;
      if exists(select 1 from public.judge_jobs where user_email='restore-erased@example.invalid') then raise exception 'old leased job resurrected'; end if;
      if exists(select 1 from public.profiles where user_email='restore-erased@example.invalid') or exists(select 1 from public.reports where user_email='restore-erased@example.invalid') or exists(select 1 from public.judge_quota_events where user_email='restore-erased@example.invalid') or exists(select 1 from public.contest_registrations where user_email='restore-erased@example.invalid') or exists(select 1 from public.admins where email='restore-erased@example.invalid') then raise exception 'owned rows survived'; end if;
      if not exists(select 1 from public.contests where id='restore-contest' and created_by='') or not exists(select 1 from public.contest_announcements where contest_id='restore-contest' and created_by='') then raise exception 'organizer anonymization failed'; end if;
      if not exists(select 1 from public.account_deletion_work where email='restore-pending@example.invalid' and auth_subject='00000000-0000-0000-0000-00000000bbbb') then raise exception 'provider recovery state lost'; end if;
      if exists(select 1 from public.account_deletion_work where email='stale-backup-work@example.invalid') then raise exception 'stale work imported'; end if;
      if not public.account_is_deleted('restore-pending@example.invalid') or not public.account_is_deleted('restore-erased@example.invalid') then raise exception 'login deletion guard lost'; end if;
      if not exists(select 1 from public.account_audit where id='00000000-0000-0000-0000-00000000cccc') then raise exception 'current audit lost'; end if;
      begin
        perform public.auth_google_identity('restore-erased@example.invalid','old-google','Old');
        raise exception 'Google recreated restored account';
      exception when raise_exception then
        if sqlerrm='Google recreated restored account' then raise; end if;
      end;
      begin
        perform public.auth_email_complete('restore-erased@example.invalid','00000000-0000-0000-0000-00000000dddd','pbkdf2$old','Old');
        raise exception 'OTP recreated restored account';
      exception when raise_exception then
        if sqlerrm='OTP recreated restored account' then raise; end if;
      end;
    end $$;
    """
    # Second run must also be safe; latest pending work and audit are retained.
    sql(setup + reconcile + assertions + '\ndrop table restore_state,restore_erased,restore_counts;\n'
        + reconcile + assertions + '\nrollback;')
    # Real query output, not a hand-written fixture shape.
    captured = json.loads(sql(capture_query()))
    validate_state(captured, (now - dt.timedelta(days=2)).isoformat())
    print('PASS: offline restore erasure, all old sessions, provider recovery, audit, login guards and repeat execution')


if __name__ == '__main__':
    main()
