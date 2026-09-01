# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

# Pandoc 3+ is a hard requirement (see docs/help/11-developers.md) and Debian
# bookworm only ships 2.17, so pull the release .deb directly.
ARG PANDOC_VERSION=3.1.11
ARG PANDOC_ARCH=amd64

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GRAPHION_CONTENT_DIR=/data/content \
    GRAPHION_DATA_DIR=/data/data \
    PORT=8080

# fonts-ebgaramond and fonts-gfs-didot back the body and display font stacks in
# content/journals/lics/template/article.typ. Without them Typst silently falls
# back and the galley typography is wrong, so they are not optional.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl gnupg sqlite3 rclone \
        fonts-ebgaramond fonts-gfs-didot fonts-dejavu fonts-liberation \
 && curl -fsSL -o /tmp/pandoc.deb \
        "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-${PANDOC_ARCH}.deb" \
 && dpkg -i /tmp/pandoc.deb && rm /tmp/pandoc.deb \
 && curl -fsSL https://pkgs.tailscale.com/stable/debian/bookworm.noarmor.gpg \
        -o /usr/share/keyrings/tailscale-archive-keyring.gpg \
 && curl -fsSL https://pkgs.tailscale.com/stable/debian/bookworm.tailscale-keyring.list \
        -o /etc/apt/sources.list.d/tailscale.list \
 && apt-get update && apt-get install -y --no-install-recommends tailscale \
 && apt-get purge -y gnupg && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# gunicorn is installed here rather than in requirements.txt so that local
# Windows development installs stay clean.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY . .

# Pristine copy of the repo's content/ tree. The volume mounts over /data, not
# over /app, so this survives as the seed source; see deploy/entrypoint.sh.
RUN cp -r /app/content /app/content-seed \
 && chmod +x /app/deploy/entrypoint.sh

# The optional pre-press tools (LibreOffice, Tesseract, verapdf, pa11y) are
# deliberately absent: they would add well over 1.5 GB and every module that
# uses them degrades gracefully through its available() probe.

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
