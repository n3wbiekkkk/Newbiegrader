#!/usr/bin/env python3
"""Reconcile erased accounts in an OFFLINE local database restored from backup.

Use a fresh, independently preserved deletion snapshot, never the copy inside
the old backup. This tool only connects through a private local Unix socket;
it cannot target the hosted production database. Dry-run rolls back by default.
It does not restore hosted Auth, rotate signing keys or reopen admission.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import uuid

OWNED_TABLES = ('submissions', 'profiles', 'judge_jobs', 'judge_quota_events',
                'contest_registrations', 'reports')
CREATOR_TABLES = ('contests', 'contest_announcements', 'admins')


def capture_query():
    """One MVCC snapshot; run read-only on the current database after quiescing."""
    return """select jsonb_build_object(
      'format', 1, 'captured_at', statement_timestamp(),
      'salt', (select jsonb_agg(t) from public.account_privacy_salt t),
      'blocks', (select coalesce(jsonb_agg(t),'[]') from public.account_deletion_blocks t),
      'work', (select coalesce(jsonb_agg(t),'[]') from public.account_deletion_work t),
      'audit', (select coalesce(jsonb_agg(t),'[]') from public.account_audit t)
    );"""


def timestamp(value):
    result = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp must include a timezone')
    return result.astimezone(dt.timezone.utc)


def validate_state(state, backup_at, *, now=None):
    now = now or dt.datetime.now(dt.timezone.utc)
    if not isinstance(state, dict) or type(state.get('format')) is not int or state['format'] != 1:
        raise ValueError('Unsupported deletion snapshot')
    captured = timestamp(state['captured_at'])
    backup = timestamp(backup_at)
    if not now - dt.timedelta(hours=24) <= captured <= now + dt.timedelta(minutes=5):
        raise ValueError('Deletion snapshot must be current (within 24 hours)')
    if not captured - dt.timedelta(days=30) <= backup <= captured:
        raise ValueError('Backup must precede deletion snapshot and be at most 30 days old')
    salts = state['salt']
    if (not isinstance(salts, list) or len(salts) != 1
            or salts[0].get('singleton') is not True
            or not isinstance(salts[0].get('salt'), str)
            or not 16 <= len(salts[0]['salt']) <= 256):
        raise ValueError('Missing or invalid privacy salt')
    for table, key in (('blocks', 'email_hash'), ('work', 'email'), ('audit', 'id')):
        rows = state[table]
        if not isinstance(rows, list) or len(rows) > 100000:
            raise ValueError('Invalid snapshot rows')
        seen = set()
        for row in rows:
            value = row[key]
            if not isinstance(value, str) or value in seen:
                raise ValueError('Invalid or duplicate snapshot identity')
            seen.add(value)
            if table == 'blocks':
                if not re.fullmatch('[a-f0-9]{64}', value):
                    raise ValueError('Invalid deletion hash')
                requested, expires = timestamp(row['requested_at']), timestamp(row['expires_at'])
                if requested > captured or expires <= requested:
                    raise ValueError('Invalid deletion interval')
            elif table == 'work':
                if (value != value.strip().lower() or '@' not in value or len(value) > 254
                        or timestamp(row['requested_at']) > captured):
                    raise ValueError('Invalid pending deletion')
                if row.get('auth_subject'):
                    uuid.UUID(row['auth_subject'])
            else:
                uuid.UUID(value)
                if timestamp(row['created_at']) > captured:
                    raise ValueError('Future audit event')
                if (row.get('event') != 'account_deleted' or not isinstance(row.get('counts'), dict)
                        or any(k not in (*OWNED_TABLES, 'web_sessions')
                               or type(v) is not int or v < 0 for k, v in row['counts'].items())):
                    raise ValueError('Audit must contain only deletion counts')
    # Even an expired block must survive if provider deletion is still pending.
    hashes = {r['email_hash'] for r in state['blocks']}
    salt = salts[0]['salt']
    if any(hashlib.sha256((salt + r['email']).encode()).hexdigest() not in hashes
           for r in state['work']):
        raise ValueError('Pending deletion is missing its matching block')
    return state


def reconciliation_sql(state, *, execute=False):
    # Hex encoding keeps all snapshot values out of SQL syntax, including quotes
    # and psql metacommands. No user-controlled table or column names are used.
    payload = json.dumps(state, ensure_ascii=False).encode().hex()
    locks = ','.join('public.' + t for t in (
        *OWNED_TABLES, *CREATOR_TABLES, 'users', 'web_sessions',
        'account_privacy_salt', 'account_deletion_blocks', 'account_deletion_work', 'account_audit'))
    sql = ["begin; set local lock_timeout='5s'; set local statement_timeout='120s';",
           f'lock table {locks} in access exclusive mode;',
           f"create temp table restore_state on commit drop as select convert_from(decode('{payload}','hex'),'UTF8')::jsonb as data;"]
    for source, target in (('salt', 'account_privacy_salt'), ('blocks', 'account_deletion_blocks'),
                           ('work', 'account_deletion_work'), ('audit', 'account_audit')):
        sql.extend((f'delete from public.{target};',
                    f"insert into public.{target} select t.* from restore_state s, jsonb_populate_recordset(null::public.{target},s.data->'{source}') t;"))
    identities = ['select email from public.users', 'select email from public.admins']
    identities += [f'select user_email from public.{t}' for t in OWNED_TABLES]
    identities += [f'select created_by from public.{t}' for t in CREATOR_TABLES]
    sql.append('create temp table restore_erased on commit drop as select distinct email from ('
               + ' union '.join(identities) + ") candidates(email) where email<>'' and ("
               'exists(select 1 from public.account_deletion_blocks b where b.email_hash=public.account_email_hash(email)) '
               'or exists(select 1 from public.account_deletion_work w where w.email=candidates.email));')
    sql.append('create temp table restore_counts(name text, removed bigint) on commit drop;')
    # Every old browser credential is removed, including surviving accounts.
    sql.append("with gone as (delete from public.web_sessions returning 1) insert into restore_counts select 'web_sessions',count(*) from gone;")
    for table in OWNED_TABLES:
        sql.append(f"with gone as (delete from public.{table} where user_email in (select email from restore_erased) returning 1) insert into restore_counts select '{table}',count(*) from gone;")
    for table in CREATOR_TABLES:
        sql.append(f"update public.{table} set created_by='' where created_by in (select email from restore_erased);")
    for table in ('admins', 'users'):
        sql.append(f"with gone as (delete from public.{table} where email in (select email from restore_erased) returning 1) insert into restore_counts select '{table}',count(*) from gone;")
    # Keep CURRENT pending work until the real provider deletion has succeeded.
    # Do not manufacture a completed-deletion audit or call Auth from a rehearsal.
    sql.append("select jsonb_build_object('execute'," + ('true' if execute else 'false')
               + ",'erased_identities',(select count(*) from restore_erased),"
               "'removed',(select jsonb_object_agg(name,removed) from restore_counts),"
               "'pending_provider_deletions',(select count(*) from public.account_deletion_work));")
    sql.append('commit;' if execute else 'rollback;')
    return '\n'.join(sql)


def private_path(path, *, directory=False):
    if path.is_symlink() or (not path.is_dir() if directory else not path.is_file()):
        raise ValueError('Private regular file/directory required')
    if path.stat().st_mode & 0o077 or path.stat().st_uid != os.getuid():
        raise ValueError('Path must be private and owned by the operator')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state', type=Path, required=True)
    parser.add_argument('--state-sha256', required=True)
    parser.add_argument('--backup-at', required=True)
    parser.add_argument('--socket', type=Path, required=True)
    parser.add_argument('--port', type=int, default=5432)
    parser.add_argument('--database', required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        private_path(args.state)
        private_path(args.state.parent, directory=True)
        private_path(args.socket, directory=True)
        if not args.socket.is_absolute() or not re.fullmatch('[A-Za-z0-9_]+', args.database):
            raise ValueError('Explicit local socket and simple database name required')
        if not 1 <= args.port <= 65535:
            raise ValueError('Invalid port')
        raw = args.state.read_bytes()
        if len(raw) > 20 * 1024 * 1024 or hashlib.sha256(raw).hexdigest() != args.state_sha256:
            raise ValueError('Deletion snapshot checksum mismatch or oversized file')
        state = validate_state(json.loads(raw), args.backup_at)
        # An inherited service/URI must not redirect this offline tool to a
        # network database. Never include raw database diagnostics or SQL in logs.
        env = {k: v for k, v in os.environ.items()
               if k in ('PATH', 'HOME', 'USER', 'LOGNAME', 'LANG', 'LC_ALL', 'TMPDIR')}
        result = subprocess.run(['psql', '-X', '-qAt', '-v', 'ON_ERROR_STOP=1',
                                 '-h', str(args.socket), '-p', str(args.port), '-d', args.database],
                                input=reconciliation_sql(state, execute=args.execute),
                                capture_output=True, text=True, timeout=150, env=env)
        if result.returncode:
            raise RuntimeError('Offline reconciliation failed; transaction was not committed')
        report = json.loads(result.stdout.strip())
        print(json.dumps(report))
    except Exception as exc:
        print('Restore reconciliation failed (' + type(exc).__name__ + '); do not reopen admission.', file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
