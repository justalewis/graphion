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
ALLOWED_UPLOAD_EXTENSIONS = {".docx", ".md", ".markdown"}

VERSIONS_KEEP = 5

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
