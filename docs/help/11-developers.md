# For developers

A walkthrough of the codebase for anyone extending it.

## Code organization

```
Graphion/
  app.py              ← Flask routes; the HTTP surface
  auth.py             ← Flask-Login wiring, user model
  db.py               ← Raw sqlite3, no ORM. Schema + migrations.
  config.py           ← Paths, secrets, upload limits.
  conversion.py       ← The big one. Stages 1, 3, 4 of the pipeline.
                        Article ingest, cleanup orchestration, render,
                        issue assembly, front-matter rendering.
  cleanups.py         ← Stage 2: deterministic Markdown cleanup passes.
  crossref.py         ← CrossRef deposit XML emitter, DOI assignment,
                        BibTeX parsing for structured citations.
  jats.py             ← JATS XML emitter.
  lint.py             ← Composable per-article validation checks.
  seed.py             ← Initial DB + LiCS journal + admin user seed.
  smoketest.py        ← End-to-end pipeline runner for development.
  render_pages.py     ← Rasterize a PDF to PNG (for previews).
  templates/          ← Jinja2 admin UI templates
  static/             ← CSS (Lewis Design System tokens + project stylesheet)
  content/            ← Journals, articles, issues — filesystem-first
  docs/               ← Markdown source for /help docs and roadmap
  tests/              ← pytest unit tests (cleanups + metadata round-trip)
```

## Adding a new feature

1. **Decide where it lives.** Pipeline → `conversion.py`. Output format → new module like `crossref.py`. UI surface → new route in `app.py` + template.
2. **Update schema if needed.** Add the column to `db.py`'s `_apply_migrations()` (additive only — never drop or reorder).
3. **Add the route + template.** Match the existing Jinja patterns.
4. **Wire it in the topbar nav** (`templates/base.html`) if it's a top-level destination, or in the article/issue action row if it's per-record.
5. **Add a test if it's not trivial.** `tests/test_cleanups.py` is a template for unit tests; route tests would be a new file.
6. **Document it** in `docs/help/` if it's user-facing.

## Conventions

- **No ORM.** Raw `sqlite3` with `Row` factory. Per Pinakes precedent.
- **No JS framework.** Vanilla JS where needed; ProseMirror via CDN ESM imports. CodeMirror via CDN.
- **Filesystem-first.** Article and issue content lives on disk. SQLite indexes; it doesn't own.
- **No-em-dash convention.** App-generated prose (UI copy, log entries, status messages) uses semicolons/colons/parentheses/commas instead of em-dashes.
- **Snapshots on write.** `_snapshot_version()` runs before any `article.md` write. Last 5 versions kept in `.versions/`.
- **Idempotent cleanups.** Every Stage 2 pass is a pure function `(text, log) -> text`. Running the full pipeline twice produces the same output.
- **YAML round-trip validation.** `write_article_metadata()` refuses to write YAML that fails `safe_load`. Defensive scalar-field whitespace normalization prevents wraparound corruption.
- **Width=10_000 on safe_dump.** Keeps YAML scalar values on one line to avoid ambiguous continuations.
- **Pandoc 3+.** Figure blocks (not Para[Image]). Filter handles both shapes for compatibility.
- **Typst via typst-py.** `typst.compile(input, output=, root=)`. The `root=CONTENT_DIR` lets templates reference paths under content/ (image assets).
- **Markdown to format: Pandoc.** HTML, EPUB, JATS, and Typst all flow through Pandoc with different `--to` flags and templates.

## Where the pipeline lives

```
app.py:upload_article       — POST /journals/<slug>/upload
  → conversion.ingest_docx       — Stage 1
  → conversion.run_cleanups      — Stage 2
  → DB insert article row

app.py:article_render       — POST /articles/<id>/render
  → conversion.render_all        — Stage 4

app.py:article_metadata     — POST /articles/<id>/metadata
  → conversion.write_article_metadata
  → conversion.render_all (auto-render)

app.py:issue_assemble       — POST /issues/<id>/assemble
  → conversion.assemble_issue    — Issue-level orchestration
    → for each article:
       set start-page in YAML
       conversion.render_pdf
       _pdf_page_count
       UPDATE articles SET start_page, end_page
    → conversion.render_front_matter (single Typst doc)
    → pypdf concatenation → issue.pdf
```

## Adding a new output format

Reference implementations: `crossref.py` (CrossRef), `jats.py` (JATS), and `conversion.render_epub` (Pandoc-mediated EPUB).

Pattern:

1. Create `<format>.py` with a `build_article_<format>(article_id) -> bytes` function (or `render_<format>(article_path, journal_slug) -> Path` if it's file-based).
2. Add a route in `app.py`: `/articles/<id>/<format>` returning a `Response` with the right MIME type and `Content-Disposition: attachment`.
3. Add a button to `templates/article.html`'s action row.
4. (Optional) for issue-level batches: add `/issues/<id>/<format>` similarly.
5. Document in `docs/help/07-output-formats.md`.

## Adding a new lint check

In `lint.py`:

```python
def check_my_new_thing(article: dict, fm: dict, body: str) -> LintResult:
    # inspect article / fm / body
    if not is_ok:
        return _warn("my-new-thing", "Summary line.", ["detail 1", "detail 2"])
    return _ok("my-new-thing", "All good.")
```

Then add it to `DEFAULT_CHECKS`. That's it.

## Adding a new cleanup pass

In `cleanups.py`:

```python
def my_pass(text: str, log: CleanupLog) -> str:
    new_text, count = ...  # transform
    log.record("my_pass", count)
    return new_text
```

Then add to `DEFAULT_PASSES`. Add a unit test in `tests/test_cleanups.py` with at least one input/output pair and an idempotence check.

## Adding a new journal

Three files + one DB row:

1. Create `content/journals/<slug>/template/` and populate:
   - `article.html.j2`
   - `article.typ`
   - `article.css`
   - `lics-filter.lua` (or rename to something journal-specific; update conversion.py to discover both)
   - `figures-filter.lua` (copy from LiCS bundle)
   - `mla.csl` or whichever CSL the journal uses
   - `front-matter-schema.yaml` (documentation)
2. Add the journal row in `seed.py` (so fresh installs get it) and via direct DB insert (so your dev DB picks it up).
3. Configure the journal's brand, depositor identity, and front-matter content via **Journal Settings** in the UI.

## Tests

Run all tests:

```
python -m pytest tests/ -q
```

Currently 24/24 passing. Unit-tested:

- `cleanups.py` — every cleanup pass with input/output pairs + idempotence checks.
- `conversion.py` metadata round-trip — YAML read/write with sanitization and field ordering.

Not yet unit-tested:

- HTTP routes (would benefit from Flask test client + a temporary DB).
- Typst rendering (would require typst binary in test environment).
- CrossRef / JATS XML output (could schema-validate against the official XSD).

## Deployment

Local-only currently. The Flask dev server is fine for single-user use on `127.0.0.1`. For multi-machine access:

1. Use a production WSGI server (gunicorn, waitress).
2. Reverse-proxy behind nginx or Caddy.
3. Set `FLASK_SECRET_KEY` from environment.
4. Persist `data/graphion.db` and `content/` on a backed-up volume.
5. Bundle Pandoc + Typst binaries in a Dockerfile if containerizing.

The roadmap doc (`docs/audit-and-roadmap.md`) tracks what's planned next.
