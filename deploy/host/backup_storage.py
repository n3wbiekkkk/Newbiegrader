#!/usr/bin/env python3
"""Encrypted read-only judge-assets backup and isolated file-byte recovery check.

Not a database backup or a Supabase Storage service restore. Source credentials
stay on host. No plaintext archive is saved; local restore files are private and
deleted after verification. Run on the authorized FileVault-protected Mac.
"""
import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from urllib.parse import quote
import uuid


MAX_BYTES = 256 * 1024 * 1024
MAX_OBJECT = 16 * 1024 * 1024
MAX_OBJECTS = 10000


def safe_key(name):
    if not isinstance(name, str) or not name or len(name) > 1024 or '\\' in name \
            or any(c in name for c in ('\x00', '\n', '\r')) \
            or any(p in ('', '.', '..') for p in name.split('/')) \
            or PurePosixPath(name).is_absolute():
        raise ValueError('Unsafe archive key')
    return name


def source_archive():
    if not sys.platform.startswith('linux'):
        raise RuntimeError('Archive source requires the trusted Linux operator service')
    import httpx
    # Fixed project/bucket. Never send the credential to a configurable URL.
    origin = 'https://qblnlfzjublfnnsasgpe.supabase.co'
    if str(os.environ.get('SUPABASE_URL', '')).rstrip('/') != origin:
        raise RuntimeError('Unexpected source project')
    key = os.environ.get('SUPABASE_KEY')
    if not key:
        raise RuntimeError('Missing source credential')
    started = time.monotonic()
    with httpx.Client(base_url=origin + '/storage/v1/', timeout=30,
                      headers={'apikey': key, 'Authorization': 'Bearer ' + key}) as client:
        def deadline():
            if time.monotonic() - started > 1200:
                raise RuntimeError('Storage backup deadline exceeded')

        def listing():
            pending, seen, result = [''], set(), {}
            while pending:
                prefix = pending.pop()
                if prefix in seen or len(seen) > MAX_OBJECTS:
                    raise ValueError('Invalid Storage directory listing')
                seen.add(prefix)
                offset = 0
                while True:
                    deadline()
                    response = client.post('object/list/judge-assets', json={
                        'prefix': prefix, 'limit': 1000, 'offset': offset,
                        'sortBy': {'column': 'name', 'order': 'asc'}})
                    response.raise_for_status()
                    rows = response.json()
                    if not isinstance(rows, list) or len(rows) > 1000:
                        raise ValueError('Invalid Storage response')
                    for row in rows:
                        name = safe_key((prefix + '/' if prefix else '') + row['name'])
                        if row.get('id') is None:
                            pending.append(name)
                            continue
                        size = int(row['metadata']['size'])
                        if name in result or not 0 <= size <= MAX_OBJECT:
                            raise ValueError('Invalid Storage object')
                        result[name] = {'size': size, 'id': row['id'], 'updated_at': row.get('updated_at')}
                        if len(result) > MAX_OBJECTS:
                            raise ValueError('Object budget exceeded')
                    if len(rows) < 1000:
                        break
                    offset += len(rows)
                    if offset > MAX_OBJECTS:
                        raise ValueError('Listing budget exceeded')
            if not result or sum(v['size'] for v in result.values()) > MAX_BYTES:
                raise ValueError('Storage byte budget exceeded or empty source')
            return result

        before = listing()
        print('Storage inventory: objects=' + str(len(before)) + ', bytes='
              + str(sum(v['size'] for v in before.values())), file=sys.stderr, flush=True)

        def download(name):
            deadline()
            data = bytearray()
            with client.stream('GET', 'object/judge-assets/' + quote(name, safe='/')) as response:
                response.raise_for_status()
                for chunk in response.iter_bytes(65536):
                    deadline()
                    data.extend(chunk)
                    if len(data) > before[name]['size']:
                        raise ValueError('Object size changed during backup')
            if len(data) != before[name]['size']:
                raise ValueError('Incomplete object download')
            return bytes(data)

        manifest = {}
        with tarfile.open(fileobj=sys.stdout.buffer, mode='w|') as archive, \
                ThreadPoolExecutor(max_workers=8) as pool:
            names = iter(sorted(before))
            pending = deque()
            for _ in range(8):
                name = next(names, None)
                if name is not None:
                    pending.append((name, pool.submit(download, name)))
            while pending:
                name, future = pending.popleft()
                data = future.result()
                info = tarfile.TarInfo('objects/' + name)
                info.size, info.mode = len(data), 0o600
                archive.addfile(info, io.BytesIO(data))
                manifest[name] = {**before[name], 'sha256': hashlib.sha256(data).hexdigest()}
                following = next(names, None)
                if following is not None:
                    pending.append((following, pool.submit(download, following)))
                if len(manifest) % 250 == 0:
                    print('Storage objects archived: ' + str(len(manifest)), file=sys.stderr, flush=True)
            if listing() != before:
                raise ValueError('Storage inventory changed; do not use this partial backup')
            body = json.dumps({'bucket': 'judge-assets', 'objects': manifest,
                               'created_at': datetime.now(timezone.utc).isoformat()}, sort_keys=True).encode()
            info = tarfile.TarInfo('manifest.json')
            info.size, info.mode = len(body), 0o600
            archive.addfile(info, io.BytesIO(body))


def restore_files(stream, directory):
    """Recover regular bytes only; reject symlinks/traversal/duplicates/bad hashes."""
    recovered, manifest, total = {}, None, 0
    with tarfile.open(fileobj=stream, mode='r|') as archive:
        for info in archive:
            if not info.isfile() or info.size < 0:
                raise ValueError('Only regular backup files are accepted')
            if info.name == 'manifest.json':
                if manifest is not None or info.size > 16 * 1024 * 1024:
                    raise ValueError('Invalid backup manifest')
                manifest = json.load(archive.extractfile(info))
                continue
            if not info.name.startswith('objects/') or manifest is not None:
                raise ValueError('Invalid backup member order')
            name = safe_key(info.name[len('objects/'):])
            if name in recovered or len(recovered) >= MAX_OBJECTS or info.size > MAX_OBJECT:
                raise ValueError('Duplicate or oversized backup member')
            total += info.size
            if total > MAX_BYTES:
                raise ValueError('Backup byte budget exceeded')
            target = directory / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
            digest, size = hashlib.sha256(), 0
            with os.fdopen(fd, 'wb') as output, archive.extractfile(info) as source:
                while chunk := source.read(65536):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
            if size != info.size:
                raise ValueError('Incomplete restored object')
            recovered[name] = {'size': size, 'sha256': digest.hexdigest()}
    if not manifest or manifest.get('bucket') != 'judge-assets' or not recovered \
            or set(manifest['objects']) != set(recovered):
        raise ValueError('Backup manifest/object set mismatch')
    for name, item in recovered.items():
        expected = manifest['objects'][name]
        if any(item[k] != expected[k] for k in ('size', 'sha256')) \
                or hashlib.sha256((directory / name).read_bytes()).hexdigest() != expected['sha256']:
            raise ValueError('Restored object checksum mismatch')
    return {'objects': len(recovered), 'bytes': total, 'all_restored_hashes_match': True}


def main():
    if sys.argv[1:] == ['--archive-source']:
        return source_archive()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', required=True)
    parser.add_argument('--ssh-key', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin' or 'FileVault is On.' not in subprocess.check_output(['fdesetup', 'status'], text=True):
        raise RuntimeError('Run this recovery rehearsal on the authorized FileVault-protected Mac')
    os.umask(0o077)
    directory = Path.home()/'.local/share/newbiegrader-private/host-backups'
    identity = directory/'backup-identity.txt'
    if directory.is_symlink() or directory.stat().st_mode & 0o077 \
            or not stat.S_ISREG(identity.lstat().st_mode) or identity.stat().st_mode & 0o077:
        raise ValueError('Private backup identity/directory required')
    recipient = subprocess.check_output(['age-keygen', '-y', str(identity)], text=True).strip()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:8]
    target = directory/(stamp + '-storage.tar.age')
    ssh = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
           '-o', 'StrictHostKeyChecking=yes', '-i', str(args.ssh_key), args.host,
           'sudo systemd-run --pipe --wait --collect --quiet '
           '--unit=newbiegrader-storage-backup '
           '-p User=newbiegrader-api -p Group=newbiegrader-api '
           '-p EnvironmentFile=/etc/newbiegrader/api.env '
           '-p NoNewPrivileges=yes -p ProtectSystem=strict -p ProtectHome=yes '
           '-p PrivateTmp=yes -p MemoryMax=256M -p MemorySwapMax=0 '
           '-p TasksMax=32 -p CPUQuota=25% -p RuntimeMaxSec=1200 '
           '/usr/local/lib/newbiegrader/venv/bin/python - --archive-source']
    started = time.monotonic()
    # The trusted script travels over stdin; credentials remain in the host file.
    with (directory/(stamp + '-storage-progress.log')).open('wb') as progress:
        source = subprocess.Popen(ssh, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=progress)
        try:
            source.stdin.write(Path(__file__).read_bytes())
            source.stdin.close()
            with target.open('xb') as encrypted:
                result = subprocess.run(['age', '-r', recipient], stdin=source.stdout,
                                        stdout=encrypted, stderr=subprocess.DEVNULL)
            source.stdout.close()
            if source.wait() != 0 or result.returncode:
                raise RuntimeError('Source/encryption failed')
            decrypted = subprocess.Popen(['age', '--decrypt', '-i', str(identity), str(target)],
                                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            try:
                with tempfile.TemporaryDirectory(prefix='storage-restore-', dir=directory) as tmp:
                    report = restore_files(decrypted.stdout, Path(tmp))
                decrypted.stdout.close()
                if decrypted.wait() != 0:
                    raise RuntimeError('Authenticated decryption failed')
            finally:
                if decrypted.poll() is None:
                    decrypted.kill()
                    decrypted.wait()
        except BaseException:
            if source.poll() is None:
                source.kill()
                source.wait()
            target.unlink(missing_ok=True)
            raise
    print(json.dumps({**report, 'archive': str(target), 'seconds': round(time.monotonic()-started, 1),
                      'restore_scope': 'file bytes only; not database/Storage service recovery',
                      'plaintext_restore_removed': True}))


if __name__ == '__main__':
    try:
        main()
    except Exception as exc:
        print('Storage backup/recovery failed (' + type(exc).__name__
              + '); partial archive removed; no credential/object content printed', file=sys.stderr)
        raise SystemExit(1) from None
