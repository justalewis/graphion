"""Configuration. Reads from environment, falls back to dev defaults."""
import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

# Content and data roots are env-overridable so a container can point them at a
# mounted volume; both default to the repo checkout for local development.
CONTENT_DIR = Path(os.environ.get("GRAPHION_CONTENT_DIR") or (BASE_DIR / "content")).resolve()
DATA_DIR = Path(os.environ.get("GRAPHION_DATA_DIR") or (BASE_DIR / "data")).resolve()
DB_PATH = DATA_DIR / "graphion.db"

SECRET_KEY = os.environ.get("FLASK_SECRET_KEY", "dev-key-change-me-before-deploy")

PANDOC_PATH = os.environ.get("PANDOC_PATH", "pandoc")
TYPST_PATH = os.environ.get("TYPST_PATH", "typst")

MAX_UPLOAD_BYTES = 25 * 1024 * 1024
ALLOWED_UPLOAD_EXTENSIONS = {".docx", ".md", ".markdown", ".pdf"}

# Two routes take a batch of files rather than one manuscript, so they need
# more room than a route that takes a single one. Flask's limit is per
# application, so `app.py` sets MAX_CONTENT_LENGTH to the larger of the two
# and holds every route but those to MAX_UPLOAD_BYTES itself: raising a
# limit for a batch must not quietly raise it everywhere.
MAX_BATCH_BYTES = 300 * 1024 * 1024

# How many files one browser pass will read. Reading a chapter costs about
# two seconds, so this is about fifty against the 300 second gunicorn
# timeout `deploy/entrypoint.sh` configures, which leaves room for the
# long tail. A whole archive is `python assess.py <folder>`, which has no
# cap because nothing is waiting on it.
MAX_ASSESS_FILES = 25

# verapdf is a JVM process at about thirteen seconds a file, so asking for
# a verdict costs an order of magnitude more than reading does and the cap
# comes down to match. Ten files is about 130 seconds.
MAX_ASSESS_VALIDATE_FILES = 10

# Batch ingest has no such ceiling, because it does not happen in the
# request: the upload is staged and a job reads it. This is a sanity bound
# on one upload rather than a timing one, and a volume of this series runs
# to about 25 chapters.
MAX_INGEST_FILES = 200

# Where a batch waits between being uploaded and being read. Under DATA_DIR
# rather than CONTENT_DIR because it is input and not content: `content/`
# is meant to stay legible to a successor editor, and a queue of raw
# uploads is not that. On Fly.io DATA_DIR is the mounted volume, so a
# queued batch survives a restart.
JOBS_DIR = DATA_DIR / "jobs"

# What a job leaves behind for a person to download. Separate from JOBS_DIR
# because staged input is deleted when a job ends and output must not be.
# It holds a remediated copy of somebody's course, so it is kept only until
# they discard it and is never archived by deploy/backup.py.
RESULTS_DIR = DATA_DIR / "results"

# A course cartridge with its media is routinely a few hundred megabytes: the
# ones measured here run to 373 MB. The limit is on what a request can
# carry, and the work happens in a job.
MAX_CARTRIDGE_BYTES = 800 * 1024 * 1024

VERSIONS_KEEP = 5

# Rendered PDFs declare PDF/UA-1 (ISO 14289-1) conformance, which is the
# standard educational content is audited against. Typst writes the
# conformance identifier, /Lang, and the ViewerPreferences /DisplayDocTitle
# entry only when the standard is requested; without it a galley fails
# clause 5 and WCAG 2.4.2 even when its tagging is otherwise sound.
# Typst validates the standard rather than merely declaring it, so a figure
# with no alt text aborts the compile; conversion.py falls back to an
# unconstrained render and logs why. Set to an empty string to turn it off.
PDF_UA_STANDARD = os.environ.get("GRAPHION_PDF_UA_STANDARD", "ua-1")

# Login throttling. /login is the only unauthenticated route, and the app is
# reachable from the public internet, so attempts have to be capped. The limiter
# is in-process, which is correct for the single gunicorn worker configured in
# deploy/entrypoint.sh; raising GUNICORN_WORKERS gives each worker its own
# counters and weakens the cap proportionally.
LOGIN_MAX_ATTEMPTS = int(os.environ.get("GRAPHION_LOGIN_MAX_ATTEMPTS", "5"))
LOGIN_WINDOW_SECONDS = int(os.environ.get("GRAPHION_LOGIN_WINDOW_SECONDS", "900"))

# Set wherever the app is served over HTTPS so the session cookie is never sent
# in the clear. Off by default so local http://127.0.0.1 development still works.
SECURE_COOKIES = os.environ.get("GRAPHION_SECURE_COOKIES", "0") == "1"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CONTENT_DIR.mkdir(parents=True, exist_ok=True)
