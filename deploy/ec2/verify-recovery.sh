#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# Copyright (C) 2026 Newbiegrader contributors
# Synthetic canary service only. Never stop or start the production worker.
set -eu
test "$(id -u)" = 0
test ! -e /etc/newbiegrader/worker-enabled
unit=newbiegrader-canary.service
override=/run/systemd/system/newbiegrader-canary.service.d/recovery.conf
marker=/var/lib/newbiegrader/recovery-marker.json
test "$(systemctl show "$unit" -p ActiveState --value)" != activating
api_pid=$(systemctl show newbiegrader-api.service -p MainPID --value)
test "$api_pid" -gt 0
install -d -m 0755 "$(dirname "$override")"
cleanup() {
  rm -f "$override" "$marker"
  systemctl daemon-reload
}
trap cleanup EXIT HUP INT TERM
rm -f "$marker"
cat > "$override" <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/local/lib/newbiegrader/venv/bin/python -u tools/ec2_canaries.py --recovery-hold
EOF
systemctl daemon-reload
systemctl start --no-block "$unit"
i=0
until test -s "$marker"; do
  i=$((i+1))
  test "$i" -le 15
  sleep 1
done
systemctl kill --kill-whom=main --signal=SIGKILL "$unit"
i=0
while test "$(systemctl show "$unit" -p ActiveState --value)" = activating; do
  i=$((i+1))
  test "$i" -le 15
  sleep 1
done
/usr/local/lib/newbiegrader/venv/bin/python - <<'PY'
import json
from pathlib import Path
record = json.loads(Path('/var/lib/newbiegrader/recovery-marker.json').read_text())
group = Path(record['cgroup'])
assert not group.exists() or 'populated 0' in (group/'cgroup.events').read_text().splitlines()
assert not Path(record['workspace']).exists()
assert not Path('/proc').joinpath(str(record['owner'])).exists()
print('PASS: manager crash removes canary descendants, cgroup and mounted workspace')
PY
test "$(systemctl show newbiegrader-api.service -p MainPID --value)" = "$api_pid"
curl -fsS -o /dev/null http://127.0.0.1:8000/api/health
printf '%s\n' 'PASS: independent API PID and health survived canary manager crash'
cleanup
trap - EXIT HUP INT TERM
systemctl reset-failed "$unit"
systemctl start "$unit"
printf '%s\n' 'PASS: full synthetic isolation suite ran again after service crash'
