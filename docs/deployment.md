# Deployment (Fly.io behind Cloudflare Access)

Graphion holds unpublished manuscripts under review, behind single-factor
Flask-Login with no rate limiting. This deployment therefore never exposes it
directly. Fly allocates **no public IP**; `cloudflared` dials out to Cloudflare's
edge, and every request arriving through that tunnel must clear a **Cloudflare
Access** identity check before it reaches the app.

The point of this shape over a VPN is that it needs **no client software**. Any
browser, any device: you get a login page, then Graphion.

## Shape

```
  browser (anywhere, no client software)
        |  https://graphion.<your-domain>
  Cloudflare edge
        |  Access policy: identity check happens HERE
  Cloudflare Tunnel  <-- outbound-only, dialed by cloudflared
        |
  cloudflared  -->  gunicorn on 127.0.0.1:8080  -->  Flask app
                                                        |
   one Fly machine                        /data volume --+
                                            content/  (canonical store)
                                            data/graphion.db (index)
```

Two independent layers guard the app: Cloudflare Access at the edge, and
Graphion's own Flask-Login behind it. Gunicorn binds loopback only, so
`cloudflared` in the same container is the sole thing that can reach it.

`content/` is the canonical store and SQLite only indexes it, so both live on
one persistent volume. A volume binds to a single machine in a single region,
which means **exactly one machine, no horizontal scaling.** That is the right
shape for a single-editor app, but it makes the volume a single point of failure
for irreplaceable journal source. Configure backups (below) before relying on
this for real work.

## Prerequisites

- A Fly.io account and `flyctl`.
- A Cloudflare account with **a domain in it**. This is the one hard
  prerequisite: a named tunnel hostname has to live on a zone you control. A
  cheap domain is fine; it never has to host anything else.
- Cloudflare Zero Trust enabled on that account. The free plan covers up to
  50 users, which is ample here.

## Cloudflare setup

All of this happens in the Zero Trust dashboard at
<https://one.dash.cloudflare.com>. Nothing is installed anywhere.

### 1. Create the tunnel

**Networks, then Tunnels, then Create a tunnel, then Cloudflared.** Name it
`graphion`.

Skip the install instructions it offers; the image already carries
`cloudflared`. Copy the **token** out of the command it displays (the long
string after `--token`). That becomes `CLOUDFLARE_TUNNEL_TOKEN`. Treat it as a
credential: it authorizes a connection into your Cloudflare account.

### 2. Route a hostname to the app

On the tunnel's **Public Hostname** tab, add:

| Field | Value |
|---|---|
| Subdomain | `graphion` |
| Domain | your domain |
| Service type | `HTTP` |
| URL | `127.0.0.1:8080` |

### 3. Gate it with Access

**Access, then Applications, then Add an application, then Self-hosted.**

- Application domain: `graphion.<your-domain>`
- Add a policy: action **Allow**, include **Emails**, and list your own address.
- Under login methods, **One-time PIN** needs no identity provider at all;
  Cloudflare emails you a code. Add Google or another IdP later if you prefer.

Without this step the tunnel hostname is open to the world. Do not skip it, and
verify it below.

## Fly setup

```bash
fly apps create graphion
```

```bash
fly volumes create graphion_data --size 10 --region ord
```

Set the secrets. `FLASK_SECRET_KEY` matters: `config.py` otherwise falls back to
the literal string `dev-key-change-me-before-deploy`, which would make session
cookies forgeable.

```bash
fly secrets set FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')" CLOUDFLARE_TUNNEL_TOKEN="eyJ..." GRAPHION_ADMIN_USER="justin" GRAPHION_ADMIN_PASSWORD="a-long-random-password"
```

Optionally add Claude assistance (`stylize.py` and `llm_cleanup.py` both no-op
without it):

```bash
fly secrets set ANTHROPIC_API_KEY="sk-ant-..."
```

Then deploy:

```bash
fly deploy
```

### Confirm there is no public IP

`fly launch` sometimes allocates addresses on its own. This deployment should
have none:

```bash
fly ips list
```

Release anything listed:

```bash
fly ips release <address>
```

## Verify the gate

This step catches a misconfigured Access policy, and it is worth repeating every
time you change one.

Open `https://graphion.<your-domain>` in a **private browsing window**. You must
land on a Cloudflare Access login page. If Graphion's own login screen appears
instead, the Access policy is not attached to that hostname and the app is
publicly reachable. Fix that before uploading anything.

## First-run seeding

If `GRAPHION_ADMIN_USER` and `GRAPHION_ADMIN_PASSWORD` are set, the entrypoint
runs `seed.py` automatically the first time it finds no database. Otherwise:

```bash
fly ssh console -C "python /app/seed.py"
```

## Known limit: the 100-second edge timeout

Cloudflare's free and Pro plans cut off any proxied request that runs longer
than **100 seconds**, returning error 524. Gunicorn here is configured with a
300-second timeout, so the app is willing to wait; Cloudflare is not.

Single-article renders finish well inside that. **Issue assembly is the
operation at risk**: `conversion.assemble_issue` re-renders every article, counts
pages, renders front matter, and concatenates the result, which on a full issue
can exceed 100 seconds.

If assembly times out in the browser, run it from a shell instead, where nothing
is proxied. Replace `1` with the issue id:

```bash
fly ssh console -C "python -c 'import conversion; conversion.assemble_issue(1)'"
```

The real fix is to make assembly a background job the UI polls. Worth adding to
`docs/audit-and-roadmap.md` if it becomes a routine annoyance.

Uploads are unaffected: Cloudflare's free-plan body limit is 100 MB and
`config.py` caps uploads at 25 MB.

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

Each archive holds `content/` plus a consistent `data/graphion.db` snapshot taken
through SQLite's online backup API, so it is safe to run while the app serves.
The last `GRAPHION_BACKUP_KEEP` archives (default 3) stay on the volume; the rest
are pruned after upload.

### Restoring

Open a shell on the machine:

```bash
fly ssh console
```

Then, on the machine, pull the archive down and extract it in place:

```bash
rclone copy b2:graphion-backups/graphion-STAMP.tar.gz /tmp/ && tar -xzf /tmp/graphion-STAMP.tar.gz -C /data
```

The archive's internal layout (`content/`, `data/graphion.db`) matches the volume
layout at `/data`.

## Refreshing templates

The entrypoint seeds `/data/content` from the image with `cp -rn`, which never
clobbers. That protects template edits and the wordmarks the Journal Settings
page writes into `template/assets/`.

The trade-off: a **modified** committed template will not overwrite the copy
already on the volume. New files land automatically; changed ones do not. To take
an updated template deliberately:

```bash
fly ssh console -C "cp /app/content-seed/journals/lics/template/article.typ /data/content/journals/lics/template/article.typ"
```

Back up first if the volume copy holds edits worth keeping.

## What is deliberately not installed

LibreOffice, Tesseract, verapdf, and pa11y are absent. They would add well over
1.5 GB, and they are pre-press tools rather than serving-path ones. Every module
that uses them degrades through its `available()` or `*_available()` probe, so
the UI simply greys those actions out. Run them locally when you need them.

Pandoc **is** installed (pinned by `PANDOC_VERSION` in the Dockerfile, since
Debian bookworm ships 2.17 and the app needs 3+). Typst arrives via `typst-py`.
The `fonts-ebgaramond` and `fonts-gfs-didot` packages back the body and display
font stacks in `content/journals/lics/template/article.typ`; without them Typst
silently falls back and the galley typography is wrong.

## Routine redeploy

```bash
git push
```

```bash
fly deploy
```

Content and database live on the volume and are untouched by a redeploy.
