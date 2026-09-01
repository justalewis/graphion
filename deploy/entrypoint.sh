#!/usr/bin/env bash
# Container entrypoint: seed the volume, open the tunnel, serve the app.
set -euo pipefail

VOLUME_ROOT="${GRAPHION_VOLUME_ROOT:-/data}"
CONTENT_DIR="${GRAPHION_CONTENT_DIR:-$VOLUME_ROOT/content}"
DATA_DIR="${GRAPHION_DATA_DIR:-$VOLUME_ROOT/data}"

mkdir -p "$CONTENT_DIR" "$DATA_DIR" "$VOLUME_ROOT/backups"

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

# ----------------------------------------------------------------- the tunnel
# cloudflared dials out to Cloudflare's edge; nothing dials in, which is why
# this app needs no public IP and no inbound firewall rule. The hostname
# mapping (graphion.<domain> -> http://127.0.0.1:$PORT) and the Access policy
# that gates it live in the Zero Trust dashboard, not in this image.
#
# Access is what authenticates visitors. Confirm the policy is actually
# attached before trusting this: docs/deployment.md, "Verify the gate".
if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
  echo "[entrypoint] starting cloudflared tunnel"
  cloudflared tunnel --no-autoupdate --loglevel info \
      run --token "${CLOUDFLARE_TUNNEL_TOKEN}" &
else
  echo "[entrypoint] WARNING: CLOUDFLARE_TUNNEL_TOKEN unset; app unreachable" >&2
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
# Bound to loopback: cloudflared is in this same container and is the only
# thing that can reach gunicorn.
#
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
