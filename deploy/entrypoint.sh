#!/usr/bin/env bash
# Container entrypoint: seed the volume, join the tailnet, serve the app.
set -euo pipefail

VOLUME_ROOT="${GRAPHION_VOLUME_ROOT:-/data}"
CONTENT_DIR="${GRAPHION_CONTENT_DIR:-$VOLUME_ROOT/content}"
DATA_DIR="${GRAPHION_DATA_DIR:-$VOLUME_ROOT/data}"
TS_SOCK=/var/run/tailscale/tailscaled.sock

mkdir -p "$CONTENT_DIR" "$DATA_DIR" "$VOLUME_ROOT/tailscale" \
         "$VOLUME_ROOT/backups" /var/run/tailscale

# ---------------------------------------------------------------- volume seed
# -n never clobbers. Template files added in git arrive as new files on the next
# deploy, while anything already on the volume survives: edited templates, and
# the wordmarks the Journal Settings page writes into template/assets/.
#
# The trade-off is that a *modified* committed template will not overwrite the
# volume copy. To take those updates, see "Refreshing templates" in
# docs/deployment.md.
echo "[entrypoint] seeding $CONTENT_DIR from image (no-clobber)"
cp -rn /app/content-seed/. "$CONTENT_DIR/" 2>/dev/null || true

# ------------------------------------------------------------------ tailscale
# Userspace networking needs no TUN device and no NET_ADMIN capability.
# Inbound tailnet traffic reaches the app through `tailscale serve`, which
# means gunicorn never listens on anything but loopback.
if [ -n "${TAILSCALE_AUTHKEY:-}" ]; then
  echo "[entrypoint] starting tailscaled (userspace networking)"
  /usr/sbin/tailscaled \
      --state="$VOLUME_ROOT/tailscale/tailscaled.state" \
      --socket="$TS_SOCK" \
      --tun=userspace-networking &

  for _ in $(seq 1 40); do
    [ -S "$TS_SOCK" ] && break
    sleep 0.5
  done

  # State lives on the volume, so this is a no-op on every restart after the
  # first and the auth key is only actually consumed once.
  tailscale --socket="$TS_SOCK" up \
      --authkey="${TAILSCALE_AUTHKEY}" \
      --hostname="${TAILSCALE_HOSTNAME:-graphion}"

  # Publish on the tailnet over HTTPS. Requires MagicDNS and HTTPS certificates
  # enabled for the tailnet (Tailscale admin console, DNS tab).
  tailscale --socket="$TS_SOCK" serve --bg "${PORT}"
  TS_NAME="$(tailscale --socket="$TS_SOCK" status --json 2>/dev/null | python -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' || true)"
  echo "[entrypoint] tailnet address: https://${TS_NAME:-unknown, run tailscale status}"
else
  echo "[entrypoint] WARNING: TAILSCALE_AUTHKEY unset; app will be unreachable" >&2
fi

# ----------------------------------------------------------------- first boot
if [ ! -f "$DATA_DIR/graphion.db" ]; then
  if [ -n "${GRAPHION_ADMIN_USER:-}" ] && [ -n "${GRAPHION_ADMIN_PASSWORD:-}" ]; then
    echo "[entrypoint] no database found; seeding"
    python seed.py --user "$GRAPHION_ADMIN_USER" --pass "$GRAPHION_ADMIN_PASSWORD"
  else
    echo "[entrypoint] no database and no admin credentials set." >&2
    echo "[entrypoint] run: fly ssh console -C 'python /app/seed.py'" >&2
  fi
fi

# -------------------------------------------------------------------- backups
if [ -n "${GRAPHION_BACKUP_REMOTE:-}" ]; then
  echo "[entrypoint] backup loop every ${GRAPHION_BACKUP_INTERVAL:-86400}s -> $GRAPHION_BACKUP_REMOTE"
  (
    while true; do
      sleep "${GRAPHION_BACKUP_INTERVAL:-86400}"
      python /app/deploy/backup.py || echo "[backup] FAILED" >&2
    done
  ) &
fi

# ---------------------------------------------------------------------- serve
# One worker, many threads: SQLite has no WAL configured here, so concurrent
# writer *processes* would contend for the database lock. A single-editor app
# has no need for more. The long timeout covers Typst renders and issue
# assembly, which can run for minutes on a large issue.
exec gunicorn \
    --bind "127.0.0.1:${PORT}" \
    --workers "${GUNICORN_WORKERS:-1}" \
    --threads "${GUNICORN_THREADS:-8}" \
    --timeout "${GUNICORN_TIMEOUT:-300}" \
    --access-logfile - \
    --error-logfile - \
    wsgi:app
