#!/usr/bin/env python3
"""Publish an existing encrypted backup across mounts without overwriting files.

Requires a trusted expected SHA256. Copies bytes only; never decrypts archives.
The destination directory must already be private and controlled by the operator.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tempfile


def deliver(source, destination, expected_sha256):
    source, destination = Path(source), Path(destination)
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256):
        raise ValueError('Expected SHA256 must be 64 lowercase hexadecimal characters')
    if source.suffix != '.age' or destination.suffix != '.age':
        raise ValueError('Only encrypted .age archives may be delivered')
    parent = destination.parent
    info = parent.lstat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
        raise ValueError('Destination directory must be private and operator-owned')
    # Stage on the destination filesystem; link publication is atomic and
    # refuses existing files, including dangling symlinks. Source stays intact.
    temporary = None
    try:
        fd = os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, 'rb') as incoming:
            info = os.fstat(incoming.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise ValueError('Source must be a private regular encrypted archive')
            with tempfile.NamedTemporaryFile(dir=parent, prefix='.backup-', delete=False) as output:
                temporary = Path(output.name)
                os.fchmod(output.fileno(), 0o600)
                digest, size = hashlib.sha256(), 0
                while chunk := incoming.read(1024 * 1024):
                    output.write(chunk)
                    digest.update(chunk)
                    size += len(chunk)
                output.flush()
                os.fsync(output.fileno())
            if size != info.st_size or digest.hexdigest() != expected_sha256:
                raise ValueError('Source size or SHA256 mismatch')
        with temporary.open('rb') as copied:
            if hashlib.file_digest(copied, 'sha256').hexdigest() != expected_sha256:
                raise ValueError('Copied archive SHA256 mismatch')
        os.link(temporary, destination)
        temporary.unlink()
        temporary = None
        directory_fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        return {'bytes': size, 'sha256': expected_sha256, 'mode': '0600'}
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    print(json.dumps(deliver(args.source, args.destination, args.expected_sha256)))


if __name__ == '__main__':
    main()
