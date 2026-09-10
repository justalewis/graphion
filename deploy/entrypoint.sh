#!/usr/bin/env bash
# Container entrypoint: seed the volume, open the tunnel, serve the app.
set -euo pipefail

VOLUME_ROOT="${GRAPHION_VOLUME_ROOT:-/data}"
CONTENT_DIR="${GRAPHION_CONTENT_DIR:-$VOLUME_ROOT/content}"
DATA_DIR="${GRAPHION_DATA_DIR:-$VOLUME_ROOT/data}"

mkdir -p "$CONTENT_DIR" "$DATA_DIR" "$VOLUME_ROOT/backups"

# ---------------------------------------------------------------- volume seed
# Article and issue content is data: it lives on the volume and is seeded
# no-clobber, so nothing an editor has produced is ever overwritten.
echo "[entrypoint] seeding $CONTENT_DIR from image (no-clobber)"
cp -rn /app/content-seed/. "$CONTENT_DIR/" 2>/dev/null || true

# Per-journal template bundles are source rather than data: they are versioned
# in git and shipped in the image, so they are refreshed on every boot. Seeding
# them no-clobber like the rest meant a *modified* template never reached the
# volume, and a deploy carrying template changes silently rendered exactly as
# before, which is a difficult failure to spot from the outside.
#
# template/assets/ is the exception. The Journal Settings page writes uploaded
# wordmarks there, so that directory stays volume-owned and no-clobber.
#
# A template edited directly on the volume is therefore replaced on the next
# deploy. Edit the bundle in git, which is where it is versioned and backed up.
for seed_template in /app/content-seed/journals/*/template; do
  [ -d "$seed_template" ] || continue
  slug=$(basename "$(dirname "$seed_template")")
  destination="$CONTENT_DIR/journals/$slug/template"
  mkdir -p "$destination"
  find "$seed_template" -maxdepth 1 -type f -exec cp -f {} "$destination/" \;
  if [ -d "$seed_template/assets" ]; then
    mkdir -p "$destination/assets"
    cp -rn "$seed_template/assets/." "$destination/assets/" 2>/dev/null || true
  fi
  echo "[entrypoint] refreshed template bundle: $slug"
done

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
