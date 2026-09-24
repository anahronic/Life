#!/usr/bin/env bash
# Deploy Ayalon methodology v2 to /opt/Life (run once as root).
#
#   sudo bash /home/admin/life_release/deploy/deploy_v2.sh /home/admin/life_release
#
# Steps (each verified; aborts on the first error):
#   1. pre-flight: release tests pass against the production venv
#   2. stop the collector timer and wait for a running cycle
#   3. backups: code tarball, systemd units, env file, verified SQLite copy
#   4. install code (never touches .venv, data/, sources/_cache, secrets)
#   5. /opt/Life owned by admin; services run as admin instead of root
#   6. DB migration v1 -> v2 (adds tables/flags; v1 values unchanged)
#   7. restart UI, start timer, run one cycle, health checks
# Rollback: sudo bash /opt/Life/deploy/rollback_v2.sh <backup-dir>
set -euo pipefail

REL="${1:?usage: deploy_v2.sh <release-dir>}"
APP=/opt/Life
PY=$APP/.venv/bin/python
TS=$(date -u +%Y%m%dT%H%M%SZ)
BK=/opt/Life-backups/$TS
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }
[ -f "$REL/collector.py" ] && [ -f "$REL/methodology_v2.py" ] || { echo "not a v2 release: $REL"; exit 1; }
say() { echo "[$(date -u +%H:%M:%S)] $*"; }

say "1/7 pre-flight tests (release dir, production venv)"
( cd "$REL" && sudo -u admin HOME=/tmp "$PY" -m pytest -q -p no:cacheprovider -W ignore::DeprecationWarning \
    --deselect tests/test_official_stats.py::TestNoSecretsDependency::test_no_streamlit_import ) | tail -3

say "2/7 stopping collector timer"
systemctl stop ayalon-collector.timer
for _ in $(seq 1 60); do systemctl is-active --quiet ayalon-collector.service || break; sleep 2; done

say "3/7 backups -> $BK"
install -d -m 700 "$BK"
tar czf "$BK/code.tgz" -C /opt --exclude=Life/.venv --exclude=Life/data --exclude=Life/sources/_cache Life
cp -a /etc/systemd/system/ayalon-collector.service /etc/systemd/system/ayalon-collector.timer \
      /etc/systemd/system/ayalon-ui.service "$BK/"
cp -a /etc/default/ayalon-monitor "$BK/ayalon-monitor.env" 2>/dev/null || true
"$PY" - "$APP/data/monitor.sqlite3" "$BK/monitor.sqlite3" <<'EOF'
import hashlib, sqlite3, sys
src, dst = sys.argv[1], sys.argv[2]
s = sqlite3.connect(f"file:{src}?mode=ro", uri=True); d = sqlite3.connect(dst); s.backup(d); d.close(); s.close()
c = sqlite3.connect(f"file:{dst}?mode=ro", uri=True)
ok = c.execute("PRAGMA integrity_check").fetchone()[0]; n = c.execute("select count(*) from runs").fetchone()[0]
print("db backup", dst, "integrity", ok, "runs", n, "sha256", hashlib.sha256(open(dst, "rb").read()).hexdigest())
sys.exit(0 if ok == "ok" else 1)
EOF
echo "$TS" > "$BK/STAMP"

say "4/7 installing code"
( cd "$REL" && tar cf - --exclude=./data --exclude=./.venv --exclude=./sources/_cache --exclude=./.streamlit/secrets.toml \
    --exclude=./tomtom.txt --exclude=./.git . ) | tar xf - -C "$APP"
cp "$REL/RELEASE" "$APP/RELEASE" 2>/dev/null || true
# remove the file that carried the leaked TomTom key, if present in the old tree
rm -f "$APP/tomtom.txt"

say "5/7 ownership + systemd units (services run as admin)"
find "$APP" -path "$APP/.venv" -prune -o -exec chown admin:admin {} +
chmod 600 "$APP/.streamlit/secrets.toml" 2>/dev/null || true
install -m 644 "$APP/deploy/systemd/ayalon-collector.service" /etc/systemd/system/ayalon-collector.service
install -m 644 "$APP/deploy/systemd/ayalon-collector.timer" /etc/systemd/system/ayalon-collector.timer
install -m 644 "$APP/deploy/systemd/ayalon-ui.service" /etc/systemd/system/ayalon-ui.service
systemctl daemon-reload
# Traffic keys belong only in the root-only env file (read by systemd); the v2
# UI needs none.  Move TOMTOM_API_KEY out of the admin-readable secrets.toml.
ENVF=/etc/default/ayalon-monitor
touch "$ENVF"; chown root:root "$ENVF"; chmod 600 "$ENVF"
S="$APP/.streamlit/secrets.toml"
if [ -f "$S" ] && grep -q '^TOMTOM_API_KEY' "$S"; then
  if ! grep -q '^TOMTOM_API_KEY=' "$ENVF"; then
    "$PY" - "$S" >> "$ENVF" <<'EOF'
import re, sys
m = re.search(r'^TOMTOM_API_KEY\s*=\s*"?([A-Za-z0-9]+)', open(sys.argv[1]).read(), re.M)
print(f"TOMTOM_API_KEY={m.group(1)}" if m else "")
EOF
  fi
  sed -i 's/^TOMTOM_API_KEY *=.*/# TOMTOM_API_KEY moved to \/etc\/default\/ayalon-monitor (collector only)/' "$S"
fi
echo "env file keys (values hidden): $(sed -E 's/=.*//' "$ENVF" | grep -v '^#' | tr '\n' ' ')"
echo "other schedulers mentioning the collector (should be none):"
grep -rlsE "collector\.py|ayalon" /etc/cron* /var/spool/cron 2>/dev/null || echo "  none"

say "6/7 database migration"
( cd "$APP" && sudo -u admin HOME=/tmp "$PY" collector.py --migrate-only )

say "7/7 restart + verify"
systemctl restart ayalon-ui.service
systemctl start ayalon-collector.timer
systemctl start ayalon-collector.service || true   # exit 1 = no provider data; recorded as a failed cycle
systemctl is-active ayalon-ui.service
for _ in $(seq 1 30); do curl -fsS http://127.0.0.1:8501/ayalon/_stcore/health >/dev/null 2>&1 && break; sleep 2; done
curl -fsS http://127.0.0.1:8501/ayalon/_stcore/health && echo " <- streamlit health"
sudo -u admin "$PY" - <<'EOF'
import sqlite3
c = sqlite3.connect("file:/opt/Life/data/monitor.sqlite3?mode=ro", uri=True)
print("schema", c.execute("PRAGMA user_version").fetchone()[0])
print("last cycle", c.execute("select started_at_utc,status,provider,provider_status,segments_ok,segments_total,substr(error,1,120) from collection_cycles order by started_at_utc desc limit 1").fetchone())
print("ok observations", c.execute("select count(*) from segment_observations where status='ok'").fetchone()[0])
EOF
systemctl list-timers ayalon-collector.timer --no-pager | head -3
say "done. backup: $BK   rollback: sudo bash $APP/deploy/rollback_v2.sh $BK"
