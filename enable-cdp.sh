#!/bin/bash
set -euo pipefail

CONF=/etc/chrome_dev.conf
PORT=9222

if [ "$(id -u)" -ne 0 ]; then
  exec sudo bash "$0" "$@"
fi

restart_ui() {
  echo "restarting ui (this logs the session out)..."
  if command -v restart >/dev/null 2>&1; then restart ui
  elif command -v initctl >/dev/null 2>&1; then initctl restart ui
  else stop ui; start ui; fi
}

if [ "${1:-}" = "--disable" ]; then
  sed -i '/^--remote-debugging-port=/d;/^--remote-allow-origins=/d' "$CONF"
  echo "removed CDP flags from $CONF"
  restart_ui
  exit 0
fi

cp -n "$CONF" "$CONF.ashland.bak" 2>/dev/null || true

if grep -q '^--remote-debugging-port=' "$CONF"; then
  echo "CDP already enabled in $CONF"
else
  printf -- '--remote-debugging-port=%s\n' "$PORT" >> "$CONF"
  printf -- '--remote-allow-origins=127.0.0.1\n' >> "$CONF"
  echo "added CDP flags to $CONF (backup: $CONF.ashland.bak)"
fi

if [ "${1:-}" = "--no-restart" ]; then
  echo "not restarting. Run:  sudo restart ui   when ready."
  exit 0
fi

restart_ui
sleep 6
if curl -s --max-time 3 "http://127.0.0.1:$PORT/json/version" >/dev/null; then
  echo "CDP is live on 127.0.0.1:$PORT  ->  ashland doctor"
else
  echo "UI restarted but port $PORT not up yet, give it a few seconds then: ashland doctor"
fi
