#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
# Run as root on the authorized Ubuntu 24.04 instance; no secrets as arguments.
set -eu
test "$(id -u)" = 0
. /etc/os-release
test "$ID" = ubuntu && test "$VERSION_ID" = 24.04
test "$(uname -m)" = x86_64
export DEBIAN_FRONTEND=noninteractive
# Prevent the package's default public welcome server from starting.
if ! command -v nginx >/dev/null 2>&1; then systemctl mask nginx.service; fi
apt-get update -q
apt-get install -y --no-install-recommends python3-venv gcc g++ nginx curl ca-certificates rsync
id newbiegrader-api >/dev/null 2>&1 || useradd --system --home /nonexistent --shell /usr/sbin/nologin newbiegrader-api
id newbiegrader-tunnel >/dev/null 2>&1 || useradd --system --home /nonexistent --shell /usr/sbin/nologin newbiegrader-tunnel
install -d -m 0755 /opt/newbiegrader/releases /usr/local/lib/newbiegrader /var/lib/newbiegrader
install -d -m 0700 /etc/newbiegrader /var/lib/newbiegrader/sandbox-identities /var/lib/newbiegrader/capacity
install -d -m 0755 /var/lib/newbiegrader/workspaces /etc/systemd/journald.conf.d
python3 -m venv /usr/local/lib/newbiegrader/bootstrap
/usr/local/lib/newbiegrader/bootstrap/bin/pip install --disable-pip-version-check 'uv==0.13.1'
export UV_PYTHON_INSTALL_DIR=/usr/local/lib/newbiegrader/python
/usr/local/lib/newbiegrader/bootstrap/bin/uv python install 3.11.17
if ! test -x /usr/local/lib/newbiegrader/venv/bin/python; then
    /usr/local/lib/newbiegrader/bootstrap/bin/uv venv --python 3.11.17 /usr/local/lib/newbiegrader/venv
fi
cat > /etc/systemd/journald.conf.d/60-newbiegrader-bounds.conf <<'EOF'
[Journal]
SystemMaxUse=200M
RuntimeMaxUse=32M
MaxRetentionSec=7day
RateLimitIntervalSec=30s
RateLimitBurst=1000
EOF
systemctl restart systemd-journald
# Preserve SSH and expose no application ports. AWS SG rules are separate.
ufw default deny incoming
ufw default allow outgoing
ufw allow OpenSSH
ufw --force enable
printf '%s\n' 'Bootstrap complete; application services have not been started.'
