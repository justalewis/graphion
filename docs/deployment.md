# Deployment (Fly.io)

Graphion runs on a single Fly machine at `https://<app>.fly.dev`, served over
HTTPS with a persistent volume holding all journal content.

The app is publicly reachable. That is a deliberate trade-off for being able to
edit from any browser without installing anything, and it puts the whole weight
of access control on the login page. Read "What guards it" before deciding this
is acceptable for your content, and consider the Cloudflare Access upgrade at
the bottom if it is not.

## Shape

```
  browser (anywhere)
        |  https://<app>.fly.dev
  Fly edge proxy  (force_https, shared v4 + dedicated v6)
        |
  gunicorn on 0.0.0.0:8080  -->  Flask app
                                    |
   one Fly machine     /data volume -+
                         content/  (canonical store)
                         data/graphion.db (index)
```

`content/` is the canonical store and SQLite only indexes it, so both live on
one persistent volume. A volume binds to a single machine in a single region,
which means **exactly one machine, no horizontal scaling.** That is the right
shape for a single-editor app, but it makes the volume a single point of failure
for irreplaceable journal source. Configure backups before relying on this.

## What guards it

Every route except `/login` carries `@login_required`, so the login page is the
only unauthenticated surface. Three things protect it:

- **scrypt password hashing** through `werkzeug.security`, which is slow and
  salted by design, so offline guessing is expensive.
- **Rate limiting** on `/login`, keyed on both the caller address and the account
  name, so rotating addresses cannot walk one account and one address cannot
  spray many. Five failures in fifteen minutes returns HTTP 429. Tunable with
  `GRAPHION_LOGIN_MAX_ATTEMPTS` and `GRAPHION_LOGIN_WINDOW_SECONDS`.
- **Hardened session cookies**: `HttpOnly`, `SameSite=Lax`, and `Secure`
  whenever `GRAPHION_SECURE_COOKIES=1` (set in `fly.toml`).

What it does **not** have: multi-factor authentication, account lockout beyond
the sliding window, or any audit log of sign-in attempts.

The rate limiter keeps its counters in process memory. That is correct for the
single gunicorn worker configured in `deploy/entrypoint.sh`. Raising
`GUNICORN_WORKERS` gives each worker independent counters and weakens the cap
proportionally, and restarting the machine clears them entirely.

Assume the `.fly.dev` hostname will be discovered and probed. Use a long random
admin password; the throttle buys time, it does not replace password strength.

## Prerequisites

- A Fly.io account and `flyctl`.
- Nothing else. Pandoc, Typst, and the fonts are baked into the image.

## Deploying

```bash
fly apps create graphion
```

```bash
fly volumes create graphion_data --size 10 --region ord --yes
```

Allocate addresses so the Fly proxy can route to it:

```bash
fly ips allocate-v4 --shared
```

```bash
fly ips allocate-v6
```

Set the secrets. `FLASK_SECRET_KEY` matters: `config.py` otherwise falls back to
the literal string `dev-key-change-me-before-deploy`, which would make session
cookies forgeable.

```bash
fly secrets set FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

```bash
fly secrets set GRAPHION_ADMIN_USER="justin" GRAPHION_ADMIN_PASSWORD="a-long-random-password"
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

## First-run seeding

If `GRAPHION_ADMIN_USER` and `GRAPHION_ADMIN_PASSWORD` are set, the entrypoint
runs `seed.py` the first time it finds no database. Otherwise:

```bash
fly ssh console -C "python /app/seed.py"
```

Those two secrets are only read on first boot. Changing them later does not
change the stored password; see below.

## Rotating the admin password

Know where the password actually lives before changing it. There are three
copies and only one of them authenticates anyone:

| Location | What it is |
|---|---|
| Fly secret store | Encrypted; set by `fly secrets set`, never readable back |
| Container environment | Plaintext, readable by anyone with `fly ssh console` |
| `users.password_hash` in the database | The scrypt hash that actually logs you in |

`seed.py` reads `GRAPHION_ADMIN_PASSWORD` only on the boot where it finds no
database. Once the database exists that variable is inert: changing or unsetting
it does not change any password. The database is the source of truth.

To rotate, open a shell and run the helper. It prompts through `getpass`, so the
new password never reaches shell history, a process listing, or a terminal log:

```bash
fly ssh console
```

Then, on the machine:

```bash
python /app/change_password.py justin
```

Afterwards, drop the stale plaintext copy from the container environment, since
it no longer does anything and is a live credential sitting in `env`:

```bash
fly secrets unset GRAPHION_ADMIN_PASSWORD
```

### Signing out existing sessions

Changing a password does **not** sign anyone out. Flask-Login sessions are
signed with `FLASK_SECRET_KEY` and carry only a user id, so a cookie issued
before the change stays valid until it expires.

If you are rotating because you think the password leaked, rotate the signing
key too. That invalidates every outstanding session cookie at once:

```bash
fly secrets set FLASK_SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
```

Everyone, including you, has to sign in again afterwards.

## Backups

The volume is the only copy of your journal source until you set this up.

Configure an rclone remote (Backblaze B2 or S3) and set it:

```bash
fly secrets set GRAPHION_BACKUP_REMOTE="b2:graphion-backups"
```

`rclone` is already in the image. Supply its config through the standard
`RCLONE_CONFIG_*` environment variables, also as Fly secrets. With the remote
set, `deploy/entrypoint.sh` runs `deploy/backup.py` every
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

## What a deploy does and does not overwrite

The entrypoint treats the volume as two different kinds of thing.

**Article and issue content is data.** Everything under
`content/journals/*/issues/` is seeded no-clobber, so nothing an editor has
produced is ever overwritten by a deploy.

**Per-journal template bundles are source.** They are versioned in git and
shipped in the image, so they are refreshed from it on every boot. A deploy
carrying template changes therefore changes what renders, with no follow-up
step.

The one exception is `template/assets/`, which stays volume-owned: the Journal
Settings page writes uploaded wordmarks there, and a deploy must not discard
them.

This means **a template edited directly on the volume is replaced on the next
deploy.** Edit the bundle in git, where it is versioned and backed up, and let
the deploy carry it. Seeding templates no-clobber was the earlier behaviour, and
it meant a modified template never reached the volume: the deploy succeeded, the
galley rendered exactly as before, and nothing said why.

## Optional: put Cloudflare Access in front

If the public login page is more exposure than you want, the image already
carries `cloudflared` and the entrypoint starts it whenever
`CLOUDFLARE_TUNNEL_TOKEN` is set. That routes the app through a Cloudflare
Tunnel, where an Access policy can require an identity check (Google, or an
emailed one-time code) before any request reaches Graphion.

It requires a domain in a Cloudflare account. The setup, all in the Zero Trust
dashboard at <https://one.dash.cloudflare.com>:

1. **Networks, Tunnels, Create a tunnel, Cloudflared.** Name it `graphion` and
   copy the token out of the command it shows.
2. On the tunnel's **Public Hostname** tab: subdomain `graphion`, your domain,
   service type `HTTP`, URL `127.0.0.1:8080`.
3. **Access, Applications, Add an application, Self-hosted** on
   `graphion.<your-domain>`. Policy: Allow, include Emails, your address.

Then:

```bash
fly secrets set CLOUDFLARE_TUNNEL_TOKEN="eyJ..."
```

To make that the *only* way in, also drop the public addresses and remove the
`[http_service]` block from `fly.toml`, then set `GUNICORN_BIND` back to
`127.0.0.1:8080` so nothing but the tunnel can reach gunicorn:

```bash
fly ips list
```

```bash
fly ips release <address>
```

Verify by opening the hostname in a private window: you must land on a
Cloudflare login page, not Graphion's own.

## What the image carries, and what it does not

**The three external checkers are installed**: verapdf and epubcheck
(both Java, sharing one `default-jre-headless`) and pa11y (Node, driving
the system Chromium). They are there because
`/accessibility/<slug>/validate` runs a conformance pass over a whole
journal, which is the thing a journal actually asks for, and without them
in the image that pass could only ever be run on somebody's laptop. They
are installed above `COPY . .` so an edit to app source does not reinstall
the better part of a gigabyte.

**LibreOffice is installed too**, in its own layer; `preprocessors.py`
finds `soffice` for the optional DOCX-normalize pass.

**Tesseract is not.** It backs `ocr.py`, which reads a table that arrived
as a picture: an editing aid used on one article at a time rather than
anything a corpus pass needs. `ocr.available()` greys the button out.

### The machine is on 2 GB because of pa11y

`fly.toml` is `shared-cpu-1x` with `memory = "2gb"`. It ran on 1 GB until
the checkers went into the image. pa11y drives headless Chromium, which
wants several hundred megabytes and runs beside gunicorn, pdfplumber,
Typst and the LibreOffice layer; on 1 GB an OOM would kill the single
machine and take the whole app down rather than only the check. The
second gigabyte is roughly another $3 a month and buys a validation pass
over a whole journal that cannot knock the app over.

If you ever drop it back to 1 GB, the thing to know is that nothing
launches Chromium until somebody asks for a pa11y run, so the app will
look fine until the first validation pass and then fall over mid-run.

Two container flags go with Chromium and are not precautions.
`--no-sandbox` is passed because Chromium refuses to start as root and the
container runs as root; `--disable-dev-shm-usage` because Docker gives a
container 64 MB of `/dev/shm` and Chromium crashes partway through a page
without it. `validators.pa11y_needs_no_sandbox()` decides by asking
whether the process is root, so a developer's machine does not drop the
sandbox for no reason; `GRAPHION_PA11Y_NO_SANDBOX` forces it either way.

The JVM heap is capped at 512 MB through `JAVA_TOOL_OPTIONS`. That was
sized for the 1 GB machine and has been left alone: verapdf and epubcheck
read one file at a time and have not wanted more, and a cap that holds is
worth keeping whatever headroom sits above it. Raise it only if a large
galley starts failing with a heap error, which would show up as a
`fail` in the register rather than as an OOM.

It prints a "Picked up JAVA_TOOL_OPTIONS" line to stderr on every run,
which disturbs neither tool, since verapdf is read from stdout and
epubcheck writes its report to a file.

Pandoc **is** installed (pinned by `PANDOC_VERSION` in the Dockerfile, since
Debian bookworm ships 2.17 and the app needs 3+). Typst arrives via `typst-py`.
The `fonts-ebgaramond` and `fonts-gfs-didot` packages back the body and display
font stacks in `content/journals/lics/template/article.typ`.

Note that Debian registers EB Garamond as the family **"EB Garamond 12"**. Both
spellings are listed in the stack; Typst does not error on an unresolved family,
it silently falls back to Libertinus Serif, so a missing name shows up only as
the wrong typeface in the finished galley.

## Routine redeploy

```bash
git push
```

```bash
fly deploy
```

Content and database live on the volume and are untouched by a redeploy.
