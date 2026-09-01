# Deployment (Fly.io, Tailscale-only)

Graphion holds unpublished manuscripts under review, behind single-factor
Flask-Login with no rate limiting. This deployment therefore puts it on a
tailnet and gives it **no public IP at all**, so there is no internet-facing
attack surface to harden. You reach it from any device signed into your
Tailscale account.

## Shape

```
  your devices (tailnet)
        |  https
  tailscale serve  ──►  gunicorn on 127.0.0.1:8080  ──►  Flask app
        |                                                    |
   one Fly machine                              /data volume ─┘
                                                  content/  (canonical store)
                                                  data/graphion.db (index)
```

`content/` is the canonical store and SQLite only indexes it, so both live on
one persistent volume. A volume binds to a single machine in a single region,
which means **exactly one machine, no horizontal scaling.** That is the right
shape for a single-editor app, but it makes the volume a single point of failure
for irreplaceable journal source. Configure backups (below) before you rely on
this for real work.

Gunicorn listens only on loopback. Nothing but `tailscale serve`, inside the
same container, can reach it.

## Prerequisites

- A Fly.io account and `flyctl`.
- A Tailscale account with **MagicDNS** and **HTTPS certificates** enabled
  (admin console, DNS tab). `tailscale serve` needs both to issue an HTTPS name.
- A Tailscale auth key from <https://login.tailscale.com/admin/settings/keys>.
  Make it **reusable** so that recreating the volume does not strand you.

## First deploy

```bash
fly apps create graphion
fly volumes create graphion_data --size 10 --region ord
```

Set the secrets. `FLASK_SECRET_KEY` matters: `config.py` otherwise falls back to
the literal string `dev-key-change-me-before-deploy`, which would make session
cookies forgeable.

```bash
fly secrets set \
  FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" \
  TAILSCALE_AUTHKEY="tskey-auth-..." \
  GRAPHION_ADMIN_USER="justin" \
  GRAPHION_ADMIN_PASSWORD="a-long-random-password"
```

Optionally add Claude assistance (`stylize.py`, `llm_cleanup.py` both no-op
without it):

```bash
fly secrets set ANTHROPIC_API_KEY="sk-ant-..."
```

Then:

```bash
fly deploy
```

### Confirm there is no public IP

`fly launch` sometimes allocates addresses on its own. This deployment should
have none:

```bash
fly ips list
```

If anything is listed, release it:

```bash
fly ips release <address>
```

## Reaching it

The entrypoint logs the tailnet address on boot:

```bash
fly logs
```

Look for `[entrypoint] tailnet address: https://graphion.<your-tailnet>.ts.net`.
Open that from any device on your tailnet. Nothing else can route to it.

## First-run seeding

If `GRAPHION_ADMIN_USER` and `GRAPHION_ADMIN_PASSWORD` are set, the entrypoint
runs `seed.py` automatically the first time it finds no database. Otherwise do it
by hand:

```bash
fly ssh console -C "python /app/seed.py"
```

## Backups

The volume is the only copy of your journal source until you set this up.

1. Configure an rclone remote (Backblaze B2 or S3) and set it:

```bash
fly secrets set GRAPHION_BACKUP_REMOTE="b2:graphion-backups"
```

`rclone` is already in the image. Supply its config through the standard
`RCLONE_CONFIG_*` environment variables, also as Fly secrets.

2. With that set, `deploy/entrypoint.sh` runs `deploy/backup.py` every
   `GRAPHION_BACKUP_INTERVAL` seconds (default 86400).

Run one on demand:

```bash
fly ssh console -C "python /app/deploy/backup.py"
```

Each archive contains `content/` plus a consistent `data/graphion.db` snapshot
taken through SQLite's online backup API, so it is safe to run while the app is
serving. The last `GRAPHION_BACKUP_KEEP` archives (default 3) stay on the volume;
the rest are pruned after upload.

### Restoring

```bash
fly ssh console
rclone copy b2:graphion-backups/graphion-<stamp>.tar.gz /tmp/
tar -xzf /tmp/graphion-<stamp>.tar.gz -C /data --strip-components=0
```

The archive's internal layout (`content/`, `data/graphion.db`) matches the volume
layout at `/data`, so it extracts in place.

## Refreshing templates

The entrypoint seeds `/data/content` from the image with `cp -rn`, which never
clobbers. That protects template edits and the wordmarks the Journal Settings
page writes into `template/assets/`.

The trade-off: a **modified** committed template will not overwrite the copy
already on the volume. New files land automatically; changed ones do not. To take
an updated template deliberately:

```bash
fly ssh console
cp /app/content-seed/journals/lics/template/article.typ \
   /data/content/journals/lics/template/article.typ
```

Back up first if the volume copy has edits worth keeping.

## What is deliberately not installed

LibreOffice, Tesseract, verapdf, and pa11y are absent. They would add well over
1.5 GB, and they are pre-press tools rather than serving-path ones. Every module
that uses them degrades through its `available()` / `*_available()` probe, so the
UI simply greys those actions out. Run them locally when you need them.

Pandoc **is** installed (pinned by `PANDOC_VERSION` in the Dockerfile, since
Debian bookworm ships 2.17 and the app needs 3+). Typst arrives via `typst-py`.
The `fonts-ebgaramond` and `fonts-gfs-didot` packages back the body and display
font stacks in `content/journals/lics/template/article.typ`; without them Typst
silently falls back and the galley typography is wrong.

## Routine redeploy

```bash
git push          # from any workstation
fly deploy
```

Content and database live on the volume and are untouched by a redeploy.
