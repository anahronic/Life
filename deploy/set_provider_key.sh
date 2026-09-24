#!/usr/bin/env bash
# Store a traffic-provider API key in /etc/default/ayalon-monitor without
# putting it on the command line or in shell history.
#
#   sudo bash /opt/Life/deploy/set_provider_key.sh HERE_API_KEY
#   sudo bash /opt/Life/deploy/set_provider_key.sh TOMTOM_API_KEY
#   (the key is read from the terminal, not echoed)
set -euo pipefail
NAME="${1:?usage: set_provider_key.sh HERE_API_KEY|TOMTOM_API_KEY}"
case "$NAME" in HERE_API_KEY|TOMTOM_API_KEY) ;; *) echo "unsupported: $NAME"; exit 1;; esac
[ "$(id -u)" -eq 0 ] || { echo "run as root (sudo)"; exit 1; }
F=/etc/default/ayalon-monitor
read -r -s -p "$NAME: " KEY; echo
[ ${#KEY} -ge 16 ] || { echo "key looks too short"; exit 1; }
touch "$F"; chmod 600 "$F"; chown root:root "$F"
cp -a "$F" "$F.bak.$(date -u +%Y%m%dT%H%M%SZ)"
grep -v "^${NAME}=" "$F" > "$F.tmp" || true
printf '%s=%s\n' "$NAME" "$KEY" >> "$F.tmp"
mv "$F.tmp" "$F"; chmod 600 "$F"
# Streamlit secrets copy (UI does not need traffic keys in v2): remove stale key
S=/opt/Life/.streamlit/secrets.toml
if [ "$NAME" = TOMTOM_API_KEY ] && [ -f "$S" ]; then
  sed -i "s/^TOMTOM_API_KEY *=.*/# TOMTOM_API_KEY removed: collector reads it from $F/" "$S"
fi
systemctl start ayalon-collector.service || true
sudo -u admin /opt/Life/.venv/bin/python - <<'EOF'
import sqlite3
c = sqlite3.connect("file:/opt/Life/data/monitor.sqlite3?mode=ro", uri=True)
print(c.execute("select started_at_utc,status,provider,provider_status,segments_ok,segments_total,substr(error,1,160) from collection_cycles order by started_at_utc desc limit 1").fetchone())
EOF
