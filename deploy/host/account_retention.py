#!/usr/bin/env python3
"""Trusted host maintenance; dry-run by default. Never exports credentials."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from account_deletion import AccountDeletion
import importlib.util

spec = importlib.util.spec_from_file_location("host_backup", Path(__file__).with_name("newbiegrader-backup.py"))
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


def maintain(client, settings, *, execute=False):
    rows = client.table('account_deletion_work').select('email,auth_subject').limit(100).execute().data or []
    if not execute:
        return {'execute': False, 'pending_deletions': len(rows)}
    finished = failed = 0
    for row in rows:
        try:
            deletion = AccountDeletion(client, settings['SUPABASE_URL'], settings['SUPABASE_KEY'])
            deletion.resume(row['email'], row.get('auth_subject'))
            finished += 1
        except Exception:
            failed += 1
    result = client.rpc('account_retention_prune', {}).execute().data
    counts = {key: value for key, value in result.items()
              if key in ('jobs', 'submissions') and type(value) is int and value >= 0}
    return {'finished': finished, 'failed': failed, 'retention': counts}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    try:
        settings = backup.read_env(Path('/etc/newbiegrader/api.env'))
        from supabase import create_client
        client = create_client(settings['SUPABASE_URL'], settings['SUPABASE_KEY'])
        result = maintain(client, settings, execute=args.execute)
    except Exception:
        print('Account maintenance unavailable; no success recorded.', file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result))
    if result.get('failed'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
