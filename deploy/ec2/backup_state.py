#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
"""Local age-encrypted EC2 configuration/UID backup over authenticated SSH.

No plaintext archive is written. The private backup identity stays on this Mac;
never upload it to EC2/Git. This does not back up Supabase application data.
"""
import argparse
from datetime import datetime, timezone
import os
from pathlib import Path
import subprocess
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host', default='ubuntu@13.211.125.108')
    parser.add_argument('--ssh-key', type=Path, default=Path.home()/'.ssh/newbiegrader-judge.pem')
    parser.add_argument('--directory', type=Path,
                        default=Path.home()/'.local/share/newbiegrader-private/ec2-backups')
    parser.add_argument('--include-tunnel', action='store_true',
                        help='Also encrypt the installed named-tunnel token and systemd unit')
    parser.add_argument('--ssh-host-key-alias', help='Existing verified known-host entry after an IP change')
    parser.add_argument('--include-problem-files-config', action='store_true',
                        help='Encrypt backend-file env and API/worker drop-ins; data backup is separate')
    args = parser.parse_args()
    os.umask(0o077)
    args.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if args.directory.is_symlink() or args.directory.stat().st_mode & 0o077:
        raise SystemExit('Backup directory must be private and not a symlink')
    identity = args.directory/'backup-identity.txt'
    if not identity.exists():
        subprocess.run(['age-keygen', '-o', str(identity)], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        identity.chmod(0o400)
    if identity.is_symlink() or identity.stat().st_mode & 0o077:
        raise SystemExit('Backup identity must be private and not a symlink')
    recipient = subprocess.check_output(['age-keygen', '-y', str(identity)], text=True).strip()
    target = args.directory/(datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'-'+uuid.uuid4().hex[:8]+'.tar.age')
    ssh = ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
           '-o', 'StrictHostKeyChecking=yes', '-i', str(args.ssh_key), args.host]
    if args.ssh_host_key_alias:
        ssh[1:1] = ['-o', 'HostKeyAlias=' + args.ssh_host_key_alias]
    # Fixed paths only. No SSH key, private backup identity or user data is sent.
    remote = ('sudo flock --shared /var/lib/newbiegrader/sandbox-identities '
              'tar -C / -cf - etc/newbiegrader/api.env etc/newbiegrader/worker.env '
              'var/lib/newbiegrader/sandbox-identities/allocated-uids '
              'etc/systemd/system/newbiegrader-api.service '
              'etc/systemd/system/newbiegrader-worker.service')
    if args.include_tunnel:
        remote += (' etc/newbiegrader/tunnel-token '
                   'etc/systemd/system/newbiegrader-tunnel.service')
    if args.include_problem_files_config:
        remote += (' etc/newbiegrader/problem-files.env '
                   'etc/systemd/system/newbiegrader-api.service.d/30-problem-files.conf '
                   'etc/systemd/system/newbiegrader-worker.service.d/30-problem-files.conf')
    source = subprocess.Popen(ssh+[remote], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    try:
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as output:
            encrypted = subprocess.run(['age', '-r', recipient], stdin=source.stdout,
                                       stdout=output, stderr=subprocess.DEVNULL)
    finally:
        source.stdout.close()
    if source.wait() != 0 or encrypted.returncode != 0:
        target.unlink(missing_ok=True)
        raise SystemExit('Encrypted backup failed; no plaintext archive saved')
    # Verify authenticated decryption without extracting/printing any secret.
    subprocess.run(['age', '--decrypt', '-i', str(identity), str(target)],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
    print('Encrypted off-host configuration/UID backup saved and decryption verified: '+str(target))
    print('Keep the private backup identity offline; Supabase DB/Storage backup is separate.')


if __name__ == '__main__':
    main()
