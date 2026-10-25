#!/usr/bin/env python3
"""Review expired encrypted operator archives; explicit --execute deletes them.

The age identity, UID ledger, source releases and unrecognized filenames are
never eligible. Run on each operator-controlled backup destination separately.
"""
import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
import re


def reviewed_archives(directory, manifest, *, now=None, days=30):
    """Historical names require an explicit, checksummed operator inventory.

    Validate the entire deletion set before unlinking any file. The manifest
    never automatically enrolls new unknown files, identities or UID ledgers.
    Missing files are harmless on repeated runs; changed files fail closed.
    """
    expired_archives(directory, now=now, days=days)  # Validate the private root.
    if manifest.is_symlink() or not manifest.is_file() or manifest.stat().st_mode & 0o077:
        raise ValueError('Reviewed manifest must be a private regular file')
    state = json.loads(manifest.read_text(encoding='utf-8'))
    if state.get('format') != 1 or not isinstance(state.get('archives'), list):
        raise ValueError('Invalid archive manifest')
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=days)
    root = directory.resolve()
    result, seen = [], set()
    for row in state['archives']:
        relative = row['path']
        parts = Path(relative).parts
        if (not isinstance(relative, str) or not parts or Path(relative).is_absolute()
                or '..' in parts or '.' in parts or relative in seen
                or not relative.endswith(('.tar.age', '.json.age', '.dump.age', '.cms'))
                or any('backup-identity' in p or 'allocated-uids' in p for p in parts)):
            raise ValueError('Unsafe or duplicate reviewed archive path')
        seen.add(relative)
        stamp = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
        if stamp.tzinfo is None or not re.fullmatch('[a-f0-9]{64}', row['sha256']):
            raise ValueError('Invalid archive date/checksum')
        path = directory / relative
        for i in range(1, len(parts)+1):
            if directory.joinpath(*parts[:i]).is_symlink():
                raise ValueError('Symlink in reviewed archive path')
        if not path.exists():
            continue
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError('Reviewed archive escaped private root')
        if stamp >= cutoff:
            continue
        before = path.stat()
        digest = hashlib.sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024*1024), b''):
                digest.update(chunk)
        after = path.stat()
        if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns) \
                or digest.hexdigest() != row['sha256']:
            raise ValueError('Reviewed archive changed; deletion refused')
        result.append(path)
    # Reviewed directories also cover future canonical exports, so a daily
    # schedule does not stop protecting files created after this inventory.
    for relative in state.get('canonical_directories', []):
        parts = Path(relative).parts
        if (not parts or Path(relative).is_absolute() or '..' in parts
                or any(directory.joinpath(*parts[:i]).is_symlink() for i in range(1, len(parts)+1))):
            raise ValueError('Unsafe canonical archive directory')
        result.extend(path for path in expired_archives(directory / relative, now=now, days=days)
                      if re.fullmatch(r'[0-9]{8}T[0-9]{6}Z-backup\.tar\.age', path.name))
    return sorted(set(result))


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
    parser.add_argument('--manifest', type=Path,
                        help='Reviewed historical filenames, dates and SHA256; excludes unlisted files')
    args = parser.parse_args()
    paths = (reviewed_archives(args.directory, args.manifest) if args.manifest
             else expired_archives(args.directory))
    for path in paths:
        print(('remove: ' if args.execute else 'would remove: ') + path.name)
        if args.execute:
            path.unlink()
    print(f'expired encrypted archives: {len(paths)}; execute={args.execute}')


if __name__ == '__main__':
    main()
