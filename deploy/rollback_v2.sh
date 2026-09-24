#!/usr/bin/env bash
# Restore the state saved by deploy_v2.sh (code, systemd units, database).
#
#   sudo bash /opt/Life/deploy/rollback_v2.sh /opt/Life-backups/<stamp> [--keep-db]
#
# --keep-db keeps the current database (v2 tables are ignored by v1 code);
# without it the pre-deploy database copy is restored and the current one is
# preserved next to it as monitor.sqlite3.rolled_back.<stamp>.
set -euo pipefail
BK="${1:?usage: rollback_v2.sh <backup-dir> [--keep-db]}"
KEEP_DB="${2:-}"
APP=/opt/Life
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }
[ -f "$BK/code.tgz" ] && [ -f "$BK/monitor.sqlite3" ] || { echo "incomplete backup dir: $BK"; exit 1; }
NOW=$(date -u +%Y%m%dT%H%M%SZ)

systemctl stop ayalon-collector.timer
for _ in $(seq 1 60); do systemctl is-active --quiet ayalon-collector.service || break; sleep 2; done

tar xzf "$BK/code.tgz" -C /opt
cp -a "$BK/ayalon-collector.service" "$BK/ayalon-collector.timer" "$BK/ayalon-ui.service" /etc/systemd/system/
systemctl daemon-reload

if [ "$KEEP_DB" != "--keep-db" ]; then
  mv "$APP/data/monitor.sqlite3" "$APP/data/monitor.sqlite3.rolled_back.$NOW"
  cp -a "$BK/monitor.sqlite3" "$APP/data/monitor.sqlite3"
  chown admin:admin "$APP/data/monitor.sqlite3"
fi

systemctl restart ayalon-ui.service
systemctl start ayalon-collector.timer
echo "rolled back to $(cat "$BK/STAMP")"
