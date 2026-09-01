# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

Graphion is a single-editor publishing workstation for scholarly journals.
Markdown source in; accessible HTML, tagged PDF, EPUB, JATS XML, and CrossRef
deposit XML out. Flask + SQLite + Pandoc + Typst. Originally built for
*Literacy in Composition Studies* (LiCS), now multi-journal.

Read these before making structural changes; do not duplicate their content here:

- `README.md` for the product overview, install, and output formats.
- `docs/help/11-developers.md` for the full architecture walkthrough, module map,
  pipeline stages, and step-by-step recipes (new output format, new lint check,
  new cleanup pass, new journal).
- `docs/audit-and-roadmap.md` for what is planned next.
- `docs/deployment.md` for the Fly.io deployment, the volume layout, backups,
  and the login hardening.

## Running it

```bash
pip install -r requirements.txt
python seed.py     # first run only; prompts for admin username + password
python app.py      # http://127.0.0.1:5050
```

Tests (24 functions: 19 in `test_cleanups.py`, 5 in `test_metadata_roundtrip.py`):

```bash
python -m pytest tests/ -q
```

End-to-end pipeline check during development:

```bash
python smoketest.py
```

## Fresh environment checklist

`data/graphion.db` and every rendered artifact under `content/` are gitignored,
so a clean clone has no database and no galleys. Before anything will run:

1. `pip install -r requirements.txt`
2. **Pandoc 3+ must be on PATH.** It is not a pip dependency. Without it, ingest
   and every render path fails. Override the binary with `PANDOC_PATH`.
3. `python seed.py` to create `data/graphion.db`, the LiCS journal row, and an
   admin user.

Typst arrives through `typst-py` (pip), so it needs no separate install.
LibreOffice, Tesseract, verapdf, and pa11y are optional and only gate optional
features; see "Optional dependencies" below.

Do not assume a sandbox or CI runner has Pandoc. Check before writing code that
depends on a render succeeding.

## Conventions that are easy to violate

**No em-dashes in app-generated prose.** UI copy, log entries, flash messages,
and status strings use semicolons, colons, parentheses, or commas instead. This
is a deliberate house style; treat it as a lint rule when writing any
user-visible string.

**Filesystem-first.** Article and issue content lives on disk under `content/`.
SQLite indexes it; SQLite does not own it. The layout is meant to stay legible
to a successor editor after this app is gone. Never move canonical content into
the database.

**Migrations are additive only.** Schema changes go in `db.py::_apply_migrations()`
as new entries appended to the bottom of the `additions` dict. Never drop,
rename, or reorder a column. The function is idempotent and skips columns that
already exist.

**No ORM.** Raw `sqlite3` with a `Row` factory, through the `cursor()`
contextmanager and the `query_one` / `query_all` / `execute` helpers in `db.py`.

**No JS framework.** Vanilla JS. ProseMirror and CodeMirror load as ESM from CDN.

**Cleanup passes are pure and idempotent.** Every Stage 2 pass in `cleanups.py`
has the signature `(text: str, log: CleanupLog) -> str`, records its work via
`log.record(name, count)` (an optional `note=` argument exists), and is
registered in `DEFAULT_PASSES` (`cleanups.py:889`). Running the pipeline twice
must produce identical output.
Any new pass needs a unit test in `tests/test_cleanups.py` with at least one
input/output pair plus an idempotence assertion.

**Lint checks** follow the same shape in `lint.py`: return `_ok(...)` or
`_warn(...)`, then register in `DEFAULT_CHECKS` (`lint.py:303`).

**YAML round-trips are validated.** `write_article_metadata()` refuses to write
YAML that fails `safe_load`, and normalizes whitespace in scalar fields to
prevent wraparound corruption. `safe_dump` uses `width=10_000` to keep scalars
on one line. Do not lower that width.

**Snapshot before write.** `_snapshot_version()` runs before any `article.md`
write; the last 5 versions are kept under `.versions/` (`VERSIONS_KEEP` in
`config.py`).

## Optional dependencies degrade, they do not crash

The app probes for optional tooling and greys out UI rather than failing at
startup. Two probe shapes exist; match the one already used by the module:

- Single-dependency modules expose `available()`: `stylize.py`, `llm_cleanup.py`,
  `ocr.py`.
- Multi-tool wrappers expose one probe per tool: `preprocessors.py`
  (`mammoth_available()`, `libreoffice_available()`), `validators.py`
  (`verapdf_available()`, `pa11y_available()`).
- `ojs_client.py` has no probe; it is configured by journal settings or env vars
  and defers its `requests` import.

Anything touching Claude (`stylize.py`, `llm_cleanup.py`) requires
`ANTHROPIC_API_KEY` in the environment and must stay optional.

## Layout notes

- `app.py` (2253 lines) is the whole HTTP surface. `conversion.py` (1638) is the
  pipeline. Those two hold most of the complexity.
- Per-journal template bundles live at `content/journals/<slug>/template/`:
  CSS, Pandoc HTML template, Typst template, Lua filters, CSL stylesheet,
  wordmark, and the Claude `style-guide.md`. The LiCS bundle is the worked
  example; `new_journal.py <slug> "Name"` clones it.
- Typst compiles with `root=CONTENT_DIR` so templates can reference image assets
  under `content/`.
- Pandoc 3 emits Figure blocks rather than `Para[Image]`; the figures filter
  handles both shapes.

## Deployment

Production runs on Fly.io at a public `.fly.dev` hostname; see
`docs/deployment.md`. Three things follow from that and are easy to get wrong:

- **Paths are env-driven.** `GRAPHION_CONTENT_DIR` and `GRAPHION_DATA_DIR`
  (`config.py`) point at a mounted volume in the container. Never hardcode
  `BASE_DIR / "content"`; import `CONTENT_DIR` and `DATA_DIR` from `config`.
- **The production path never touches `app.py`'s `__main__` block.** Gunicorn
  imports `wsgi:app`. Flask's debugger stays off anywhere but loopback, which is
  what the `loopback` check at the bottom of `app.py` enforces; do not weaken it.

- **`/login` is the only unauthenticated route, and it is public.** It is rate
  limited per address and per account in `app.py`; the counters are in-process,
  so they assume the single gunicorn worker that `deploy/entrypoint.sh`
  configures. Do not raise `GUNICORN_WORKERS` without replacing the limiter,
  and do not add an unauthenticated route without thinking about exposure.

Shell scripts and the Dockerfile must keep LF endings (`.gitattributes` pins
this). A CRLF shebang makes the container fail to start.

`.dockerignore` is not `.gitignore`. Ignore rules do not apply to paths git
already tracks, so a pattern that is harmless in one can silently drop a
committed source file from the build context in the other.

## Committing

The remote is `https://github.com/justalewis/graphion.git`. Work is only portable
across machines once it is pushed, so commit and push before switching
workstations. Never commit `data/graphion.db`, rendered galleys, or anything
under `content/**/_unfiled/`; `.gitignore` already covers these.
