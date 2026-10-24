#!/usr/bin/env python3
"""Host-side encrypted backup for a Newbiegrader host.

The age *private* identity never leaves the operator's machine. This script
only needs the age *recipient* public key, so the host can encrypt a backup
that only the operator can decrypt. That keeps the existing rule intact
("the private backup identity stays on this Mac") while still allowing a
scheduled, unattended backup.

What goes in (one encrypted archive):
  * configuration: /etc/newbiegrader/*.env, the worker gate, the named-tunnel
    token and the installed systemd units and drop-ins
  * the sandbox UID ledger, so a restored host never reuses an identity
  * the application data: every public table read through the PostgREST API
    with the service key the host already holds. The schema, the RLS policies,
    the grants and the constraints are not dumped here on purpose: they live
    in the committed supabase/schema.sql, so a restored database is rebuilt
    from the repository and the data is restored from this archive.

Where it goes: a private Supabase Storage bucket, separate from the problem
assets. Uploads are private and never receive a public URL.

    python3 deploy/host/newbiegrader-backup.py --dry-run
    python3 deploy/host/newbiegrader-backup.py --bucket judge-backups
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

RECIPIENT_FILE = Path("/etc/newbiegrader/backup-recipient")
ENV_FILE = Path("/etc/newbiegrader/api.env")
SCHEMA_FILE = Path("supabase/schema.sql")
MARKER_FILE = Path("/var/lib/newbiegrader/last-backup")
STAGING = Path("/var/lib/newbiegrader/backup-staging")
PAGE = 1000

CONFIG_FILES = (
    "etc/newbiegrader/api.env",
    "etc/newbiegrader/worker.env",
    "etc/newbiegrader/host.env",
    "etc/newbiegrader/backup-recipient",
    "etc/newbiegrader/alert-webhook",
    "etc/newbiegrader/problem-files.env",
    "etc/newbiegrader/worker-enabled",
    "etc/newbiegrader/tunnel-token",
    "etc/systemd/system/newbiegrader-api.service",
    "etc/systemd/system/newbiegrader-worker.service",
    "etc/systemd/system/newbiegrader-worker@.service",
    "etc/systemd/system/newbiegrader-tunnel.service",
    "etc/systemd/system/newbiegrader-canary.service",
    "etc/systemd/system/newbiegrader-judge.slice",
    "etc/systemd/system/newbiegrader-backup.service",
    "etc/systemd/system/newbiegrader-backup.timer",
    "etc/systemd/system/newbiegrader-alert.service",
    "etc/systemd/system/newbiegrader-alert.timer",
    "etc/systemd/system/newbiegrader-discord-presence.service",
    "etc/systemd/system/newbiegrader-health.service",
    "etc/systemd/system/newbiegrader-health.timer",
    "etc/systemd/sleep.conf.d/60-newbiegrader-server.conf",
)
UID_LEDGER = "var/lib/newbiegrader/sandbox-identities/allocated-uids"


def read_env(path: Path) -> dict:
    values = {}
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def public_tables(schema: Path) -> list[str]:
    """Tables declared in the committed schema. The schema is the source of
    truth for structure; this only lists what to read. The schema writes the
    name with and without the `public.` prefix, so both forms are accepted."""
    names = []
    try:
        text = schema.read_text(encoding="utf-8")
    except OSError:
        return names
    pattern = re.compile(
        r"create\s+table\s+(?:if\s+not\s+exists\s+)?(?:public\.)?([a-z_][a-z0-9_]*)\s*\(",
        re.IGNORECASE)
    for match in pattern.finditer(text):
        name = match.group(1).lower()
        # Ephemeral credentials must not be resurrected by data restoration.
        if name != "web_sessions" and name not in names:
            names.append(name)
    return names


def fetch_table(base: str, key: str, table: str) -> list:
    """Read one table through PostgREST with the service key."""
    rows = []
    offset = 0
    while True:
        query = urllib.parse.urlencode({"select": "*"})
        url = f"{base.rstrip('/')}/rest/v1/{table}?{query}"
        request = urllib.request.Request(
            url, headers={"apikey": key, "Authorization": "Bearer " + key,
                          "Range": f"{offset}-{offset + PAGE - 1}",
                          "Range-Unit": "items"})
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                chunk = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read()[:200].decode("utf-8", "replace")
            raise RuntimeError(f"{table}: HTTP {exc.code} {body}") from exc
        if not isinstance(chunk, list):
            chunk = []
        rows.extend(chunk)
        if len(chunk) < PAGE:
            break
        offset += PAGE
    return rows


def collect_data(base: str, key: str, schema: Path, staging: Path) -> dict:
    tables = public_tables(schema)
    if not tables:
        raise SystemExit("no tables found in the schema file")
    summary = {}
    dump = staging / "data"
    dump.mkdir(parents=True, exist_ok=True)
    for table in tables:
        rows = fetch_table(base, key, table)
        (dump / f"{table}.json").write_text(
            json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        summary[table] = len(rows)
    return summary


def build_archive(staging: Path, output: Path) -> None:
    with tarfile.open(output, "w") as archive:
        archive.add(staging, arcname="payload")


def encrypt(plain: Path, target: Path, recipient: str) -> str:
    digest = hashlib.sha256()
    with plain.open("rb") as source, target.open("wb") as sink:
        process = subprocess.run(["age", "-r", recipient], stdin=source,
                                 stdout=sink, stderr=subprocess.PIPE)
    if process.returncode != 0:
        raise SystemExit(f"age failed: {process.stderr.decode('utf-8', 'replace')[:200]}")
    with target.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def upload(base: str, key: str, bucket: str, local: Path, name: str) -> None:
    url = f"{base.rstrip('/')}/storage/v1/object/{bucket}/{urllib.parse.quote(name)}"
    request = urllib.request.Request(
        url, data=local.read_bytes(), method="POST",
        headers={"apikey": key, "Authorization": "Bearer " + key,
                 "Content-Type": "application/octet-stream",
                 "x-upsert": "true"})
    with urllib.request.urlopen(request, timeout=300) as response:
        response.read()


def backup_timestamp(name: str):
    """Only our encrypted backup filenames are eligible for automatic removal."""
    if not re.fullmatch(r"[0-9]{8}T[0-9]{6}Z-backup\.tar\.age", name):
        return None
    try:
        return dt.datetime.strptime(name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def prune(base: str, key: str, bucket: str, keep: int, days: int = 30) -> list[str]:
    headers = {"apikey": key, "Authorization": "Bearer " + key,
               "Content-Type": "application/json"}
    objects = []
    for offset in range(0, 100000, 1000):
        request = urllib.request.Request(
            f"{base.rstrip('/')}/storage/v1/object/list/{bucket}",
            data=json.dumps({"prefix": "", "limit": 1000, "offset": offset,
                             "sortBy": {"column": "name", "order": "asc"}}).encode(),
            method="POST", headers=headers)
        with urllib.request.urlopen(request, timeout=60) as response:
            batch = json.loads(response.read().decode("utf-8"))
        if not isinstance(batch, list):
            raise RuntimeError("invalid backup listing")
        objects.extend(batch)
        if len(batch) < 1000:
            break
    else:
        raise RuntimeError("backup listing exceeds safety limit")
    now = dt.datetime.now(dt.timezone.utc)
    names = sorted({row['name'] for row in objects if isinstance(row, dict)
                    and backup_timestamp(row.get('name', '')) is not None})
    stale = {name for name in names if backup_timestamp(name) < now - dt.timedelta(days=days)}
    if keep > 0:
        stale.update(names[:-keep])
    # List every object before mutating the bucket: offset pagination stays stable.
    for name in sorted(stale):
        remove = urllib.request.Request(
            f"{base.rstrip('/')}/storage/v1/object/{bucket}",
            data=json.dumps({"prefixes": [name]}).encode(),
            method="DELETE", headers=headers)
        with urllib.request.urlopen(remove, timeout=60) as response:
            response.read()
    return sorted(stale)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default="judge-backups")
    parser.add_argument("--keep", type=int, default=14,
                        help="how many encrypted backups to retain in the bucket")
    parser.add_argument("--retention-days", type=int, default=30,
                        help="maximum backup age; enforced independently of --keep")
    parser.add_argument("--dry-run", action="store_true",
                        help="collect and encrypt locally, but upload nothing")
    parser.add_argument("--schema", type=Path, default=SCHEMA_FILE)
    parser.add_argument("--env-file", type=Path, default=ENV_FILE)
    parser.add_argument("--recipient-file", type=Path, default=RECIPIENT_FILE)
    parser.add_argument("--marker-file", type=Path, default=MARKER_FILE)
    parser.add_argument("--staging", type=Path, default=STAGING)
    args = parser.parse_args(argv)
    if args.retention_days < 1 or args.retention_days > 30 or args.keep < 0:
        parser.error("retention-days must be 1-30; keep must be nonnegative")

    os.umask(0o077)
    env = read_env(args.env_file)
    base, key = env.get("SUPABASE_URL"), env.get("SUPABASE_KEY")
    if not base or not key:
        raise SystemExit(f"{args.env_file} has no SUPABASE_URL/SUPABASE_KEY")
    if not args.recipient_file.exists():
        raise SystemExit(
            f"{args.recipient_file} is missing. Put the age recipient public key there "
            "(age-keygen -y on the operator machine). The private identity stays there.")
    recipient = args.recipient_file.read_text(encoding="utf-8").strip()
    if not recipient.startswith("age1"):
        raise SystemExit(f"{args.recipient_file} does not contain an age recipient key")
    if not shutil.which("age"):
        raise SystemExit("age is not installed on this host (apt-get install age)")

    args.staging.mkdir(parents=True, exist_ok=True, mode=0o700)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    work = Path(tempfile.mkdtemp(prefix="backup-", dir=str(args.staging)))
    try:
        payload = work / "payload"
        payload.mkdir()
        included, missing = [], []
        extra = [str(path.relative_to("/")) for path in Path("/etc/newbiegrader").glob("worker-*.env")]
        extra += [str(path.relative_to("/")) for path in Path("/etc/systemd/system").glob("newbiegrader-*.service.d/*.conf")]
        for relative in CONFIG_FILES + (UID_LEDGER,) + tuple(sorted(extra)):
            source = Path("/") / relative
            if source.exists():
                target = payload / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
                included.append(relative)
            else:
                missing.append(relative)
        print(f"configuration: {len(included)} file(s) included"
              + (f", missing: {', '.join(missing)}" if missing else ""))

        summary = collect_data(base, key, args.schema, payload)
        total = sum(summary.values())
        print(f"data: {total} row(s) across {len(summary)} table(s)")
        for table, count in sorted(summary.items()):
            print(f"  {table:<28} {count}")

        plain = work / "payload.tar"
        build_archive(payload, plain)
        print(f"archive: {plain.stat().st_size} bytes")

        encrypted = work / "payload.tar.age"
        digest = encrypt(plain, encrypted, recipient)
        print(f"encrypted: {encrypted.stat().st_size} bytes sha256={digest[:16]}")

        name = f"{stamp}-backup.tar.age"
        if args.dry_run:
            print(f"dry-run: would upload {name} to bucket {args.bucket}")
        else:
            upload(base, key, args.bucket, encrypted, name)
            print(f"uploaded: {args.bucket}/{name}")
            removed = prune(base, key, args.bucket, args.keep, args.retention_days)
            if removed:
                print(f"pruned {len(removed)} old backup(s)")
            args.marker_file.write_text(
                dt.datetime.now(dt.timezone.utc).isoformat(), encoding="utf-8")
            os.chmod(args.marker_file, 0o600)
            print(f"marker: {args.marker_file}")
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
