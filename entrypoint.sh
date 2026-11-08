#!/bin/sh
# Rechte für /data setzen und danach ohne root-Rechte laufen (Unraid: 99:100)
set -e
PUID="${PUID:-99}"
PGID="${PGID:-100}"
mkdir -p "$DATA_DIR"
if [ "$(id -u)" = "0" ]; then
  chown -R "$PUID:$PGID" "$DATA_DIR"
  exec setpriv --reuid="$PUID" --regid="$PGID" --clear-groups \
    gunicorn -w 1 --threads 16 -b "0.0.0.0:${PORT}" --timeout 120 app.main:app
fi
exec gunicorn -w 1 --threads 16 -b "0.0.0.0:${PORT}" --timeout 120 app.main:app
