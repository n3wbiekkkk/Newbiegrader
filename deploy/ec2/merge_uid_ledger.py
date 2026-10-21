#!/usr/bin/env python3
"""Append old-host UID reservations from stdin. Never reset an existing ledger.

Run as root with the worker disabled; repeat with a final snapshot after draining
the old worker. Input is numeric reservation records, never credentials or jobs.
"""
import fcntl
import os
from pathlib import Path
import stat
import sys

FIRST, LAST = 1000000, 2147483647
LIMIT = 64 * 1024 * 1024


def records(data):
    if not data or not data.endswith(b"\n") or len(data) > LIMIT:
        raise ValueError("incomplete or oversized ledger")
    rows = data.splitlines()
    if any(not row.isdigit() for row in rows):
        raise ValueError("invalid ledger record")
    values = list(map(int, rows))
    if not all(FIRST <= value <= LAST for value in values) or any(
            before >= after for before, after in zip(values, values[1:])):
        raise ValueError("ledger must contain increasing reserved UIDs")
    return values


def append_reservations(directory, incoming):
    values = records(incoming)
    fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(fd)
        if info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o700:
            raise ValueError("unsafe ledger directory")
        fcntl.flock(fd, fcntl.LOCK_EX)
        flags = os.O_RDWR | os.O_APPEND | os.O_NOFOLLOW
        try:
            ledger = os.open('allocated-uids', flags | os.O_CREAT | os.O_EXCL, 0o600, dir_fd=fd)
            created = True
        except FileExistsError:
            ledger = os.open('allocated-uids', flags, dir_fd=fd)
            created = False
        try:
            info = os.fstat(ledger)
            if (info.st_uid != 0 or stat.S_IMODE(info.st_mode) != 0o600
                    or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > LIMIT):
                raise ValueError("unsafe ledger file")
            existing = os.read(ledger, LIMIT + 1)
            if not existing and not created:
                raise ValueError("empty existing ledger; refusing UID reuse")
            high = records(existing)[-1] if existing else FIRST - 1
            additions = [value for value in values if value > high]
            data = b''.join(f'{value}\n'.encode('ascii') for value in additions)
            while data:
                written = os.write(ledger, data)
                if written <= 0:
                    raise OSError("incomplete reservation append")
                data = data[written:]
            os.fsync(ledger)
            os.fsync(fd)
            return len(additions)
        finally:
            os.close(ledger)
    finally:
        os.close(fd)


def main():
    if os.geteuid() != 0 or Path('/etc/newbiegrader/worker-enabled').exists():
        raise SystemExit('Refused: root and disabled worker required')
    count = append_reservations('/var/lib/newbiegrader/sandbox-identities', sys.stdin.buffer.read(LIMIT + 1))
    print(f'UID reservations preserved; appended records: {count}; no ledger reset')


if __name__ == '__main__':
    main()
