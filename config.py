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

DATA_DIR.mkdir(parents=True, exist_ok=True)
CONTENT_DIR.mkdir(parents=True, exist_ok=True)
