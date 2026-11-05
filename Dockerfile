# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm

# Pandoc 3+ is a hard requirement (see docs/help/11-developers.md) and Debian
# bookworm only ships 2.17, so pull the release .deb directly.
ARG PANDOC_VERSION=3.1.11
ARG PANDOC_ARCH=amd64

# cloudflared carries the outbound-only tunnel to Cloudflare's edge. Pinned
# rather than :latest so a rebuild is reproducible.
ARG CLOUDFLARED_VERSION=2026.8.3

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    GRAPHION_CONTENT_DIR=/data/content \
    GRAPHION_DATA_DIR=/data/data \
    PORT=8080

# fonts-ebgaramond and fonts-gfs-didot back the body and display font stacks in
# content/journals/lics/template/article.typ. Without them Typst silently falls
# back and the galley typography is wrong, so they are not optional.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl sqlite3 rclone \
        fonts-ebgaramond fonts-gfs-didot fonts-dejavu fonts-liberation \
 && curl -fsSL -o /tmp/pandoc.deb \
        "https://github.com/jgm/pandoc/releases/download/${PANDOC_VERSION}/pandoc-${PANDOC_VERSION}-1-${PANDOC_ARCH}.deb" \
 && dpkg -i /tmp/pandoc.deb && rm /tmp/pandoc.deb \
 && curl -fsSL -o /tmp/cloudflared.deb \
        "https://github.com/cloudflare/cloudflared/releases/download/${CLOUDFLARED_VERSION}/cloudflared-linux-amd64.deb" \
 && dpkg -i /tmp/cloudflared.deb && rm /tmp/cloudflared.deb \
 && rm -rf /var/lib/apt/lists/*

# libreoffice-writer provides the `soffice` binary that preprocessors.py looks
# up via shutil.which("soffice"). It backs the optional DOCX-normalize pass:
# round-tripping a manuscript through headless LibreOffice flattens text boxes
# and cleans autoformat junk before Pandoc ingest. Isolated in its own layer
# because it is by far the heaviest thing in this image (~600 MB installed);
# keeping it separate means edits to the pandoc/cloudflared layer above don't
# reinstall it. --no-install-recommends drops the docs, help, JRE, and clip-art
# bundles, none of which the headless conversion pass touches.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libreoffice-writer \
 && rm -rf /var/lib/apt/lists/*

# ---------- the three external checkers ----------
#
# `register.py` carries five kinds of check and three of them are external
# tools. Without these in the image, `/accessibility/<slug>/validate` greys
# all three out and the job refuses to start, which is the design working
# rather than failing, and it also means the pass a journal most wants
# could only ever be run on somebody's laptop.
#
# They sit above `COPY . .` on purpose: this is the better part of a
# gigabyte and an edit to app source must not reinstall it.

# verapdf and epubcheck are both Java, so one headless JRE serves both.
# --no-install-recommends on the LibreOffice layer above dropped the JRE it
# would otherwise have pulled; soffice can now find this one, which is
# harmless for the headless conversion pass and is why the heap is capped
# globally below rather than per tool.
#
# JAVA_TOOL_OPTIONS is honoured by the JVM itself rather than by a launcher
# script, so it reaches verapdf and epubcheck however they are invoked. It
# prints a "Picked up JAVA_TOOL_OPTIONS" line to stderr on every run; both
# tools are read from stdout or from a report file, so neither is disturbed
# by it. 512 MB is sized for a 1 GB machine, not for the tools' appetite.
ENV JAVA_TOOL_OPTIONS=-Xmx512m

# The installer zip has shipped both flat and inside a versioned
# directory, so the jar is found rather than named. The symlink is what
# `validators.verapdf_available()` looks for, since that is
# `shutil.which("verapdf")` and an install off PATH reads as absent. The
# `test -x` at the end fails the build if the pack indices in that XML
# have gone stale and selected something other than the CLI.
COPY deploy/verapdf-install.xml /tmp/verapdf-install.xml
RUN apt-get update && apt-get install -y --no-install-recommends \
        default-jre-headless unzip \
 && rm -rf /var/lib/apt/lists/* \
 && curl -fsSL -o /tmp/verapdf.zip \
        "https://software.verapdf.org/releases/verapdf-installer.zip" \
 && unzip -q /tmp/verapdf.zip -d /tmp/verapdf \
 && java -jar "$(find /tmp/verapdf -name 'verapdf-izpack-installer-*.jar' | head -1)" \
        /tmp/verapdf-install.xml \
 && ln -s /opt/verapdf/verapdf /usr/local/bin/verapdf \
 && rm -rf /tmp/verapdf /tmp/verapdf.zip /tmp/verapdf-install.xml \
 && test -x /opt/verapdf/verapdf

# The jar keeps its lib/ where the release put it, which is what
# `validators.epubcheck_argv` assumes when it runs the path as given, so
# the archive is unpacked rather than having the jar lifted out of it. The
# `test -f` is the build's check on the asset name: a release that renames
# its zip would otherwise leave EPUBCHECK_PATH pointing at nothing and the
# probe saying no, with the image built and shipped.
ARG EPUBCHECK_VERSION=5.4.0
ENV EPUBCHECK_PATH=/opt/epubcheck-${EPUBCHECK_VERSION}/epubcheck.jar
RUN curl -fsSL -o /tmp/epubcheck.zip \
        "https://github.com/w3c/epubcheck/releases/download/v${EPUBCHECK_VERSION}/epubcheck-${EPUBCHECK_VERSION}.zip" \
 && unzip -q /tmp/epubcheck.zip -d /opt \
 && rm /tmp/epubcheck.zip \
 && test -f "${EPUBCHECK_PATH}"

# pa11y drives headless Chromium through puppeteer. The system browser is
# installed from apt and puppeteer is told to use it: left to itself it
# downloads a second Chromium of its own during `npm install`, which is
# another 300 MB of the same thing.
#
# Memory is the live constraint here, not disk. Chromium wants several
# hundred megabytes and this runs on a 1 GB shared-cpu-1x beside gunicorn,
# Typst and LibreOffice; see docs/deployment.md, which says what to raise
# and when. Nothing launches Chromium unless somebody asks for a pa11y
# run, so the cost is paid per check rather than at boot.
ENV PUPPETEER_SKIP_DOWNLOAD=1 \
    PUPPETEER_EXECUTABLE_PATH=/usr/bin/chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
        nodejs npm chromium \
 && npm install -g pa11y \
 && npm cache clean --force \
 && rm -rf /var/lib/apt/lists/* \
 && command -v pa11y \
 && test -x /usr/bin/chromium

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

# Tesseract is still deliberately absent. It backs `ocr.py`, which is for
# reading a table that arrived as a picture, and that is an editing aid
# used on one article at a time rather than something a corpus pass needs;
# `ocr.available()` greys the button out where it is missing. The three
# checkers above earned their weight differently: a conformance pass over
# a whole journal is the thing a journal asks for, and without them in the
# image it could only ever be run on somebody's laptop.

ENTRYPOINT ["/app/deploy/entrypoint.sh"]
