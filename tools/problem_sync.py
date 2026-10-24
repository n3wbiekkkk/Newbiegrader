#!/usr/bin/env python3
"""Private authoring archive transfer. No HTTP endpoint, secrets or automatic merge."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import tempfile

ROOT = Path(__file__).resolve().parent.parent
MAX_FILE = 64 * 1024 * 1024
MAX_TOTAL = 1024 * 1024 * 1024
MANIFEST = 'problem-sync.json'
PACKAGE_FILES = {'config.json', 'statement.md', 'statement.pdf', 'statement.build.json',
                 'input_validator.py', 'solution.md', 'solution.py', 'solution.pdf',
                 'solution.cpp', 'solution.cpp.verify.json',
                 'solution.tex', 'solution.build.json', 'solution.verify.json'}


def allowed(name):
    p = PurePosixPath(name)
    if p.is_absolute() or str(p) != name or any(x in ('', '.', '..') for x in name.split('/')):
        return False
    parts = p.parts
    slug = r'[a-z0-9_]+'
    if len(parts) == 2 and parts[0] == 'examples':
        return bool(re.fullmatch(slug+r'_ref\.(py|cpp|c)', parts[1]))
    if len(parts) >= 3 and parts[0] == 'problems' and re.fullmatch(slug, parts[1]):
        return (len(parts) == 3 and parts[2] in PACKAGE_FILES) or (
            len(parts) == 4 and parts[2] == 'tests' and bool(re.fullmatch(r'[A-Za-z0-9_-]+\.(in|out)', parts[3])))
    return False


def pack(output, root=ROOT):
    output = Path(output)
    if output.exists():
        raise ValueError('archive already exists; choose a new filename')
    root = Path(root)
    paths = sorted(p for area in ('problems', 'examples') for p in (root/area).rglob('*')
                   if allowed(p.relative_to(root).as_posix()))
    if not paths:
        raise ValueError('no authoring packages found')
    blobs, total = {}, 0
    for p in paths:
        if p.is_symlink() or not p.is_file() or p.stat().st_size > MAX_FILE:
            raise ValueError('unsafe or oversized source file')
        total += p.stat().st_size
        if total > MAX_TOTAL:
            raise ValueError('archive exceeds total size limit')
        blobs[p.relative_to(root).as_posix()] = {'size': p.stat().st_size,
                                               'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}
    manifest = json.dumps({'version': 1, 'files': blobs}, sort_keys=True).encode()
    output.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'wb') as stream, tarfile.open(fileobj=stream, mode='w:gz') as archive:
            info = tarfile.TarInfo(MANIFEST)
            info.size = len(manifest)
            info.mode = 0o600
            archive.addfile(info, io.BytesIO(manifest))
            for name, expected in blobs.items():
                data = (root/name).read_bytes()
                if len(data) != expected['size'] or hashlib.sha256(data).hexdigest() != expected['sha256']:
                    raise ValueError('source changed while packing; retry after saving files')
                info = tarfile.TarInfo(name)
                info.mode = 0o600
                info.size = len(data)
                archive.addfile(info, io.BytesIO(data))
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    return len(blobs)


def verified_members(archive):
    members = archive.getmembers()
    if len(members) > 100000 or len({x.name for x in members}) != len(members):
        raise ValueError('duplicate entries or too many files')
    for entry in members:
        if not entry.isfile() or entry.size > MAX_FILE or (entry.name != MANIFEST and not allowed(entry.name)):
            raise ValueError('unsafe archive member')
    if sum(x.size for x in members) > MAX_TOTAL:
        raise ValueError('unpacked archive exceeds size limit')
    entry = archive.getmember(MANIFEST)
    if entry.size > 16*1024*1024:
        raise ValueError('manifest too large')
    manifest = json.load(archive.extractfile(entry))
    if manifest.get('version') != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('invalid manifest')
    expected = manifest['files']
    if set(expected) != {x.name for x in members if x.name != MANIFEST}:
        raise ValueError('manifest file list mismatch')
    for entry in members:
        if entry.name == MANIFEST:
            continue
        data = archive.extractfile(entry).read(MAX_FILE+1)
        if expected[entry.name] != {'size': len(data), 'sha256': hashlib.sha256(data).hexdigest()}:
            raise ValueError('authoring archive checksum mismatch')
    return members


def unpack(source, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('destination must not exist; unpack into a new staging folder')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # Validate everything before creating the destination; never extract links.
    with tarfile.open(source, 'r:gz') as archive:
        members = verified_members(archive)
        with tempfile.TemporaryDirectory(prefix='.problem-sync-', dir=destination.parent) as tmp:
            stage = Path(tmp)
            for entry in members:
                p = stage/entry.name
                p.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                with p.open('xb') as target:
                    os.chmod(p, 0o600)
                    target.write(archive.extractfile(entry).read(MAX_FILE+1))
            # Reserve the destination exclusively after validation. A racing
            # creator wins without being overwritten, even for an empty folder.
            destination.mkdir(mode=0o700)
            os.rename(stage, destination)
    return len(members)-1


def fetch(host, remote_path, output):
    if not re.fullmatch(r'[A-Za-z0-9_.@-]+', host) or host.startswith('-'):
        raise ValueError('invalid SSH host')
    if not re.fullmatch(r'/[A-Za-z0-9_./-]+', remote_path) or '..' in remote_path.split('/'):
        raise ValueError('remote archive path must be canonical and absolute')
    output = Path(output)
    if output.exists():
        raise ValueError('download destination already exists')
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.problem-sync-', dir=output.parent)
    os.close(fd)
    try:
        subprocess.run(['scp', '-o', 'StrictHostKeyChecking=yes', '--',
                        host+':'+remote_path, temporary], check=True)
        with tarfile.open(temporary, 'r:gz') as archive:
            verified_members(archive)
        # Hard-link creation is exclusive: never overwrite an existing file.
        os.link(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    p = sub.add_parser('pack'); p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('unpack'); p.add_argument('--archive', type=Path, required=True); p.add_argument('--destination', type=Path, required=True)
    p = sub.add_parser('fetch'); p.add_argument('--host', required=True); p.add_argument('--remote-path', required=True); p.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'pack':
        print('Private files packed:', pack(args.output))
    elif args.action == 'unpack':
        print('Verified files staged:', unpack(args.archive, args.destination))
        print('Compare and back up local work before merging; nothing was overwritten.')
    else:
        fetch(args.host, args.remote_path, args.output)
        print('Downloaded and checksum-verified private archive; unpack into a new staging folder.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, tarfile.TarError, subprocess.CalledProcessError) as exc:
        raise SystemExit(f'problem_sync: {exc}')
