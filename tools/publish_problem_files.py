#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Publish a verified private Storage backup onto backend disk, no network/writes to Supabase.

Use root-owned/private source files outside Git/static/workspaces. The source
manifest is the authenticated/decrypted backup manifest, not an uploaded user file.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import backend_problem_files as files


def publish_backup(manifest_path, objects, catalog_path=None):
    manifest_path, objects = Path(manifest_path), Path(objects)
    if manifest_path.is_symlink() or objects.resolve() != objects:
        raise files.FilesUnavailable('noncanonical backup source')
    info = manifest_path.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_uid not in (0, os.geteuid()) or info.st_mode & 0o077:
        raise files.FilesUnavailable('backup manifest must be private')
    manifest = json.loads(manifest_path.read_bytes())
    bucket = manifest['bucket']
    entries = manifest['objects']
    if not isinstance(entries, dict) or not entries:
        raise files.FilesUnavailable('empty or invalid source manifest')

    public_samples = set()
    if catalog_path is not None:
        catalog_path = Path(catalog_path)
        s = catalog_path.lstat()
        if not stat.S_ISREG(s.st_mode) or s.st_uid not in (0, os.geteuid()) or s.st_mode & 0o077:
            raise files.FilesUnavailable('source catalog must be private')
        for row in json.loads(catalog_path.read_bytes())['rows']:
            for name in row.get('samples') or []:
                for suffix in ('in', 'out'):
                    path = f"{row['slug']}/tests/{name}.{suffix}"
                    files._logical(bucket, path)
                    if path not in entries:
                        raise files.FilesUnavailable('public sample is missing from backup')
                    public_samples.add(path)

    def jobs():
        for name, entry in sorted(entries.items()):
            files._logical(bucket, name)
            path = objects / name
            # Reject symlink ancestors and untrusted writable source directories.
            if path.resolve() != path or not path.is_relative_to(objects):
                raise files.FilesUnavailable('unsafe backup object path')
            for parent in [path.parent, *path.parent.parents]:
                if parent == objects.parent:
                    break
                s = parent.lstat()
                if s.st_uid not in (0, os.geteuid()) or s.st_mode & 0o022:
                    raise files.FilesUnavailable('unsafe source directory')
            raw = files._read(path.parent, path.name, files.MAX_FILE)
            if len(raw) != entry['size'] or hashlib.sha256(raw).hexdigest() != entry['sha256']:
                raise files.FilesUnavailable('source backup checksum mismatch')
            yield name, raw, 'application/pdf' if name.endswith('.pdf') else 'application/octet-stream'
    result = files.publish(bucket, jobs(), public_samples)
    result['source_manifest_sha256'] = hashlib.sha256(manifest_path.read_bytes()).hexdigest()
    return result


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest', type=Path, required=True)
    ap.add_argument('--objects', type=Path, required=True)
    ap.add_argument('--catalog', type=Path, required=True, help='private matching read-only metadata export')
    ap.add_argument('--publish', action='store_true', required=True)
    args = ap.parse_args(argv)
    try:
        result = publish_backup(args.manifest, args.objects, args.catalog)
        result['verified'] = files.validate(verify_bytes=True)
    except Exception:
        print('Backend file publication failed; inspect protected source/configuration; no source writes.', file=sys.stderr)
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
