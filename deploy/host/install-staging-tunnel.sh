#!/bin/sh
# Staging health endpoint only. Quick Tunnel is not a stable production origin.
set -eu
test "$(id -u)" = 0
test "$(uname -m)" = x86_64
# Preserve an existing host cloudflared installation and unrelated service.
if ! command -v cloudflared >/dev/null 2>&1; then
    tmp=$(mktemp -d)
    trap 'rm -rf "$tmp"' EXIT HUP INT TERM
    curl -fLsS --retry 2 -o "$tmp/cloudflared.deb" \
      https://github.com/cloudflare/cloudflared/releases/download/2026.10.1/cloudflared-linux-amd64.deb
    printf '%s  %s\n' 200573c872174ab449965655febadef8edfbb144ebcaa391b700b2dedbadb3cd "$tmp/cloudflared.deb" | sha256sum --check --status
    dpkg -i "$tmp/cloudflared.deb"
    ln -s /usr/bin/cloudflared /usr/local/bin/cloudflared
fi
install -m 0644 /opt/newbiegrader/current/deploy/host/staging-nginx.conf /etc/nginx/sites-available/newbiegrader-staging
ln -sfn /etc/nginx/sites-available/newbiegrader-staging /etc/nginx/sites-enabled/newbiegrader-staging
rm -f /etc/nginx/sites-enabled/default
nginx -t
systemctl unmask nginx.service
systemctl enable --now nginx.service
install -m 0644 /opt/newbiegrader/current/deploy/host/newbiegrader-staging-tunnel.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now newbiegrader-staging-tunnel.service
