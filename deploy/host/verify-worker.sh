#!/bin/sh
# Validate the actual worker unit/credentials without claiming a production job.
set -eu
export SYSTEMD_PAGER=cat
test "$(id -u)" = 0
test ! -e /etc/newbiegrader/worker-enabled
test "$(systemctl show newbiegrader-worker.service -p ActiveState --value)" != active
override=/run/systemd/system/newbiegrader-worker.service.d/preflight.conf
install -d -m 0755 "$(dirname "$override")"
cleanup() {
  rm -f "$override"
  systemctl daemon-reload
}
trap cleanup EXIT HUP INT TERM
cat > "$override" <<'EOF'
[Service]
Type=oneshot
ExecCondition=
ExecStart=
ExecStart=/usr/local/lib/newbiegrader/venv/bin/python -u worker.py --check
Restart=no
EOF
systemctl daemon-reload
if systemctl is-failed --quiet newbiegrader-worker.service; then
  systemctl reset-failed newbiegrader-worker.service
fi
systemctl start newbiegrader-worker.service
systemctl show newbiegrader-worker.service -p Result -p ExecMainStatus -p ActiveState
test ! -e /etc/newbiegrader/worker-enabled
