#!/bin/sh
# Validate the four real worker units read-only; never claim a queue job.
set -eu
export SYSTEMD_PAGER=cat
test "$(id -u)" = 0
test ! -e /etc/newbiegrader/worker-enabled
for i in 1 2 3 4; do
    test "$(systemctl show "newbiegrader-worker@$i.service" -p ActiveState --value)" != active
    test ! -e "/run/systemd/system/newbiegrader-worker@$i.service.d/preflight.conf"
done
cleanup() {
    for i in 1 2 3 4; do
        rm -f "/run/systemd/system/newbiegrader-worker@$i.service.d/preflight.conf"
    done
    systemctl daemon-reload
}
trap cleanup EXIT HUP INT TERM
for i in 1 2 3 4; do
    folder="/run/systemd/system/newbiegrader-worker@$i.service.d"
    install -d -m 0755 "$folder"
    cat > "$folder/preflight.conf" <<'EOF'
[Service]
Type=oneshot
ExecCondition=
ExecStart=
ExecStart=/usr/local/lib/newbiegrader/venv/bin/python -u worker.py --check
Restart=no
EOF
done
systemctl daemon-reload
systemctl start newbiegrader-worker@1.service newbiegrader-worker@2.service newbiegrader-worker@3.service newbiegrader-worker@4.service
for i in 1 2 3 4; do
    unit="newbiegrader-worker@$i.service"
    test "$(systemctl show "$unit" -p Result --value)" = success
    test "$(systemctl show "$unit" -p ExecMainStatus --value)" = 0
    test "$(systemctl show "$unit" -p ActiveState --value)" = inactive
done
test ! -e /etc/newbiegrader/worker-enabled
printf '%s\n' 'PASS: four worker preflights; no production jobs claimed'
