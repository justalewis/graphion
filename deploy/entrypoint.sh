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
# Optional, and unset by default: this app is served publicly through Fly.
# Providing CLOUDFLARE_TUNNEL_TOKEN additionally exposes it through a
# Cloudflare Tunnel, which is the upgrade path to putting a Cloudflare Access
# identity check in front of the login page. That needs a domain in a
# Cloudflare account; see docs/deployment.md.
if [ -n "${CLOUDFLARE_TUNNEL_TOKEN:-}" ]; then
  echo "[entrypoint] starting cloudflared tunnel"
  cloudflared tunnel --no-autoupdate --loglevel info \
      run --token "${CLOUDFLARE_TUNNEL_TOKEN}" &
else
  echo "[entrypoint] no CLOUDFLARE_TUNNEL_TOKEN; serving through Fly only"
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
# Binds 0.0.0.0 because Fly's edge proxy connects from outside the container's
# loopback interface. The app is public; /login is rate limited in app.py.
#
# One worker, many threads: SQLite has no WAL configured here, so concurrent
# writer *processes* would contend for the database lock. A single-editor app
# has no need for more. The long timeout covers Typst renders and issue
# assembly, which can run for minutes on a large issue.
exec gunicorn \
    --bind "${GUNICORN_BIND:-0.0.0.0:${PORT}}" \
    --workers "${GUNICORN_WORKERS:-1}" \
    --threads "${GUNICORN_THREADS:-8}" \
    --timeout "${GUNICORN_TIMEOUT:-300}" \
    --access-logfile - \
    --error-logfile - \
    wsgi:app
