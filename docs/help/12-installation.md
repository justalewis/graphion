# Installation & setup

A start-from-scratch guide for getting Graphion running on your machine.

## Requirements

- **Operating system:** macOS, Linux, or Windows. The tool is developed on Windows 11; tested code paths handle path separators portably.
- **Python:** 3.11 or newer. Older Pythons (3.10 and below) are missing dataclass features the codebase relies on.
- **Pandoc:** 3.0 or newer. Required for ingest (DOCX → Markdown) and all output formats (HTML / EPUB / JATS / Typst input).
- **Disk:** A few hundred MB for dependencies. Each article averages 100 KB–2 MB depending on figures.
- **Browser:** Anything modern. The WYSIWYG editor imports ProseMirror modules via ESM from a CDN, so the first load needs internet; subsequent loads are cached.

## Installing Pandoc

Graphion uses Pandoc as a Python subprocess via `pypandoc`. You need the actual Pandoc binary on PATH.

**macOS** (Homebrew):

```bash
brew install pandoc
```

**Linux** (Debian/Ubuntu):

```bash
sudo apt install pandoc
```

Or download a `.deb` from the Pandoc releases page if your distro's package is older than 3.0.

**Windows:** Download the installer from <https://github.com/jgm/pandoc/releases>. The installer adds Pandoc to PATH automatically.

Verify:

```bash
pandoc --version
```

You should see `pandoc 3.x.x` or higher.

## Cloning and installing

```bash
git clone https://github.com/justalewis/stylus.git
cd stylus
python -m pip install -r requirements.txt
```

This installs Flask, Flask-Login, pypandoc, python-docx, PyYAML, mistune, lxml, requests, typst (which bundles the Typst rendering engine), pypdf, pypdfium2, bibtexparser, and a few smaller deps.

If you prefer a virtual environment (recommended):

```bash
python -m venv .venv
source .venv/bin/activate         # macOS/Linux
.venv\Scripts\activate            # Windows PowerShell
pip install -r requirements.txt
```

## First-run seed

```bash
python seed.py
```

The script will:

1. Create the SQLite database at `data/graphion.db`.
2. Apply the schema and any pending column migrations.
3. Register the LiCS example journal (or skip if you've removed the seed for it).
4. Prompt you for an admin username and password.

For non-interactive setup (CI, scripts):

```bash
python seed.py --user admin --pass changeme123 --email you@example.org
```

Then **change the password immediately** via the admin user record before deploying anywhere.

## Running

```bash
python app.py
```

The app boots a Flask development server on port 5050. Open:

<http://127.0.0.1:5050/>

Sign in with the admin credentials you just created.

## Why port 5050?

The original development environment also hosts a sibling app (Pinakes) on port 5000. Port 5050 stays out of the way. You can override via the environment variable:

```bash
PORT=8080 python app.py
```

## Verifying the install works

The repo ships with a smoke-test:

```bash
python smoketest.py
```

This drives the full pipeline against a sample DOCX (the placeholder in `_dropbox/`). It should produce HTML and PDF outputs under the article directory and print confirmation messages.

If smoketest passes, the install is healthy.

## Configuration knobs

Most config lives in the database (set via the Journal Settings UI). A few environment variables override defaults:

- `PORT` — port to bind (default 5050)
- `FLASK_SECRET_KEY` — session signing key (default: per-process random; set in production)
- `PANDOC_PATH` — path to the Pandoc binary (default: `pandoc` on PATH)
- `TYPST_PATH` — path to a Typst binary (default: the `typst` Python package's bundled engine)

## Updating

```bash
git pull
pip install -r requirements.txt    # in case requirements changed
python seed.py                     # runs migrations; safe to re-run
```

Schema migrations are additive (`ALTER TABLE ... ADD COLUMN`) and idempotent; existing data is never modified.

## Deployment beyond local dev

Graphion is designed as a single-user local tool. For multi-machine access:

1. Use a production WSGI server (`gunicorn`, `waitress`) instead of `app.run`.
2. Reverse-proxy behind nginx or Caddy with HTTPS.
3. Set `FLASK_SECRET_KEY` from environment.
4. Persist `data/graphion.db` and `content/` on a backed-up volume.
5. Optionally containerize: a `Dockerfile` that starts from `python:3.12-slim`, installs Pandoc, and adds the repo is straightforward.

There is no built-in multi-user authentication or role-based access control. If multiple people need to collaborate, run multiple instances or stick to OJS for the submission/review workflow and use Graphion only for layout.
