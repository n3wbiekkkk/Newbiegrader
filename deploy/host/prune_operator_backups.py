#!/usr/bin/env python3
"""Review expired encrypted operator archives; explicit --execute deletes them.

The age identity, UID ledger, source releases and unrecognized filenames are
never eligible. Run on each operator-controlled backup destination separately.
"""
import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re


def expired_archives(directory, *, now=None, days=30):
    if directory.is_symlink() or not directory.is_dir() or directory.stat().st_mode & 0o077:
        raise ValueError('Backup directory must be private and not a symlink')
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    expired = []
    for path in sorted(directory.iterdir()):
        if path.is_symlink() or not path.is_file():
            continue
        if not re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-[a-zA-Z0-9_-]+\.tar\.age', path.name):
            continue
        try:
            stamp = datetime.strptime(path.name[:16], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if stamp < cutoff:
            expired.append(path)
    return expired


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, required=True)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args()
    paths = expired_archives(args.directory)
    for path in paths:
        print(('remove: ' if args.execute else 'would remove: ') + path.name)
        if args.execute:
            path.unlink()
    print(f'expired encrypted archives: {len(paths)}; execute={args.execute}')


if __name__ == '__main__':
    main()
