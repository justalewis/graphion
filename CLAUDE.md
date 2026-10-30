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

Tests (288 functions: 88 in `test_cleanups.py`, 28 in
`test_teacher_resources.py`, 76 in `test_pdf_ingest.py`, 40 in
`test_ingest_volume.py`, 28 in
`test_lint.py`, 10 in `test_metadata_roundtrip.py`, 6 in
`test_standalone_html.py`, 5 in `test_pdf_ua.py`, 4 in
`test_journal_filter.py`, 3 in `test_preprocessors.py`). Most of the suite
runs without Pandoc; `test_journal_filter.py` needs it and skips where it is
absent:

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
registered in `DEFAULT_PASSES` (`cleanups.py:1444`). Running the pipeline twice
must produce identical output.
Any new pass needs a unit test in `tests/test_cleanups.py` with at least one
input/output pair plus an idempotence assertion.

**`run_cleanups()` is not the same thing, and it is not idempotent.** The
passes are pure; the function around them rebuilds `article.md` from
`article-raw.md`, so it discards everything written to the front matter after
the first run: the volume facts `ingest_volume.py` stamps in, and any metadata
an editor has typed. Every caller re-applies that itself. The re-clean route in
`app.py` reads the front matter, runs the cleanups, and writes the metadata back
(`app.py:2104`); `ingest_volume.py` is safe only because it enriches after
cleaning, not before. Re-running it over already-ingested articles reverts them,
and the only thing that gets the metadata back is `.versions/`.

**Lint checks** follow the same shape in `lint.py`: return `_ok(...)` or
`_warn(...)`, then register in `DEFAULT_CHECKS` (`lint.py:405`).

**Galleys are PDF/UA-1.** `conversion._compile_typst()` compiles every PDF
with `pdf_standards` set from `config.PDF_UA_STANDARD`, which is what emits
the conformance identifier and the ViewerPreferences `/DisplayDocTitle` entry
that an accessibility audit checks for (ISO 14289-1 clause 5; WCAG 2.4.2).
Typst validates the standard rather than merely declaring it, so content that
cannot conform aborts the compile. The helper falls back to an unconstrained
render and logs why, so an editor never loses a galley to this. The usual
cause is an image with no alt text, which `lint.check_alt_text` fails on
first. Assembled issues are a separate case: concatenating with pypdf drops
the structure tree, so `issue.pdf` deliberately does not claim conformance.

**PDF ingest infers structure; it does not read it.** A DOCX still knows what
a paragraph is, so Pandoc can be handed the file. A PDF knows only where ink
sits, so `pdf_ingest.py` reconstructs paragraphs from the first-line indent,
heads from type size and centring, emphasis from font names, and word breaks
from a vocabulary built out of the document itself. Every one of those is a
judgement that can be wrong, so the upload route says so to the editor, and
new heuristics need a case in `tests/test_pdf_ingest.py`. The geometry is
learned per document rather than hardcoded: a series that redesigns between
volumes should degrade, not silently misread. Use pdfplumber, not PyMuPDF,
which is AGPL and would reach the whole deployed app.

**Text set in a symbol font is not text.** A symbol font stores pictures at
ordinary character codes, so extracting a Wingdings run gives punctuation:
byte 0x7B is an open circle and arrives as `{`, byte 0x4A is a smiling face
and arrives as `J`. Others land in the private use area as U+F0xx, which is
worse, because a private use codepoint means nothing to a screen reader and
Typst validates PDF/UA rather than declaring it, so one of them aborts the
compile and the chapter ships without the conformance identifier. Only the
font knows which is which and the font name is gone by Stage 2, so
`SYMBOL_FONT_CHARS` and `translate_symbol_char()` do the substitution in
`pdf_ingest.py`, during line assembly, where it is still in hand. Every
entry was read off the page it came from; subsetted archive encodings need
not agree with a published chart. Match on the whole family after the
subset prefix, never a substring: `OpenSymbol` and `SymbolMT` decode their
bullet correctly already and must be left alone. `table.extract()` strips
the font off, so `_symbol_translations()` rebuilds the mapping from the
chars inside the table's box; a code that appears there both as symbol and
as text is left alone, since the extracted string carries no positions.
`lint.check_unreadable_characters` is the backstop for whatever a new
source brings in that the table does not know.

**Figures come out too, and the caption is the hard part.** `extract()` takes
an `assets_dir`; given one it writes every embedded raster there and places it
in the body. pypdf is asked for the rasters because it resolves the stream
filters and names the format; pdfplumber reads the captions, since the lines
are already being read there. A figure is paired with a caption by page and by
order down the page.

Three things about captions are easy to get wrong, and each cost this archive
figures. A caption is set a point smaller than the body, which is also what a
footnote is, so `classify` reads one as the other: a caption therefore has to
start its own block (`is_caption` in `assemble`) or it is appended to whatever
footnote precedes it, and it has to be emitted in place in
`blocks_to_markdown` or it is collected to the end of the chapter with the
notes. And punctuation cannot tell a caption from a reference to one, because
the archive writes all three of "Figure 4.1: ", "Figure 3.3. " and
"Figure 15.1 "; what separates them is the capital that follows, since a
caption continues with the figure's name and prose continues with a verb
("Figure 7.6 shows that").

The label itself is abbreviated three ways, consistently within a volume and
not across the series: volume 2 prints "Fig. 1." over all seventeen of its
captions, volume 6 prints "Fig 1.0", and the rest print "Figure 1". Matching
only the long form read volume 2 as a book that captions nothing and sent
twenty of its twenty-two figures to the undescribed pile with their
descriptions sitting in the text above them, so `_FIGURE_CAPTION_RE` takes
all three. The capital-letter test still does the work of telling a caption
from a reference, which is what keeps "Fig. 1, we see that" out.

A caption may also be set in italic, so it arrives wrapped in emphasis
and a pattern anchored at the start never sees the label. `unemphasize`
takes off wrapping that covers the whole line, and only that: emphasis
inside a caption is the caption's own. One figure in volume 2 was
printing after the Works Cited for want of this. `_caption_key` strips
it too, and that is the half that actually places the figure:
recognising the caption only gets it into `caption_at`, while the key
is matched between the caption as the page prints it and the caption as
the block holds it, and only the block has been through `_line_text`.

A chapter can print more captions than it has images: `beyond-black-on-white`
captions five figures and embeds one, because the other four are set as live
type rather than placed as pictures. Pairing is by page and by order down the
page for that reason, never by counting captions off against images.

A figure goes in as an image and a hard line break above its caption, in one
paragraph, and never as a lone image in one. A lone image becomes a Pandoc
Figure, and the figures filter numbers every Figure from 1 in document order,
which would print "Figure 1." over a caption reading "Figure 7.1" and leave
every "see Figure 7.3" in the prose pointing at the wrong picture. A
reconstruction keeps the printed numbering.

**Tables are found by their rules, never by the alignment of their text.**
`TABLE_SETTINGS` asks pdfplumber for the "lines" strategy only. This archive
rules its tables, and the "text" strategy reads a page of ordinary prose as a
48-row table. Missing an unruled table is the better failure, because a table
that was never found leaves the prose alone.

`drop_lines_inside_tables` is the half that matters. Read across its columns,
a two-column table interleaves its cells into prose: chapter 11 of volume 5
came through with "detailing as being the most import- lab procedures ant
while", one word cut in half with a cell from the next column inside it. That
is worse than a missing figure, because it is present and wrong, and no
conformance check sees it: the text is there, so the galley passes. The lines
a table is made of come out of the prose and the table goes in as a pipe
table, whose header row is what lets a screen reader name the column a cell
is in. It runs before the vocabulary is built, so shredded cells do not teach
it their fragments as words.

A table is paired with its caption in reading order, which is where this
differs from the figures. A figure and its caption share a page by
definition, since the caption is set under the picture; a table's caption is
set above it and the two part company across a page break, as both of chapter
11's did. pdfplumber also reports the cells inside a table as further tables,
so anything inside another's box is dropped.

Alt text comes from the caption with its label and any source credit removed.
The archive sets the credit two ways, in brackets at the end and as a
trailing sentence ("Photo by Jenae Cohn", "Menu image courtesy of Mistie
Cohn"), and `_CREDIT_TAIL_RE` takes the second only where it names itself a
credit: a bare "by" belongs to the description far more often, as in "chord
changes for 'Heart of Gold' by Neil Young". A caption that is nothing but a
credit keeps it, since an empty alt costs the galley its conformance and is
no better for a reader than the credit is.

That is a starting point, not an answer: a caption says what a figure is
called and alt text says what is in it. A figure whose page printed no caption
gets `undescribed_alt()` rather than an empty string, because empty alt text
costs the galley its PDF/UA conformance and leaving the figure out costs the
reader the figure. `lint.check_alt_text` warns on both kinds so the writing
still owed is countable, and `lint.check_figure_coverage` catches an article
that refers to figures it does not contain, which `check_alt_text` cannot see
and reads as a pass.

Writing alt text satisfies WCAG 1.1.1 and leaves 1.4.5 exactly where it
was. 113 of this series' 196 figures carry text as a picture, which is a
property of what the books are: a technical writing volume teaches a genre
by showing one, and volume 2 reproduces student essays as collages. Nothing
can tell a photograph of a document from a photograph of anything else
without looking, so each one is listed by hand in the article's
`images-of-text` front matter and `lint.check_images_of_text` warns on the
list. A warning, not a failure: the galley conforms and the figure is
described, and what is wanted is that the shortfall stays countable rather
than being closed over by the alt text.

`ingest_volume.py` runs a folder of chapter PDFs through that in one pass.
It never fetches anything: the volume is downloaded by hand and the runner
is pointed at the folder, so a mass download cannot happen by accident and
`--dry-run` shows the whole plan before anything is written. Chapters land
as drafts. `ingest_pdf` stamps `source-file` into the front matter, which is
how a chapter is recognised as already taken in; matching on the slug alone
fails, because a slug is built from the title and the same PDF ingested with
and without a manifest lands under two of them.

The archive has renamed its chapters twice over the life of the series, so
`parse_filename` reads three conventions: a chapter number followed by
surnames (`19Irvin.pdf`, volumes 4 to 6), a surname and an abbreviated title
(`bunn--how-to-read.pdf`, volumes 1 and 2), and a bare surname
(`gagich.pdf`, volume 3). Only the first carries chapter order, so the
earlier volumes need a manifest to sit in order within a volume. Volumes 5
and 6 are numbered and need none.

Every volume folder also holds the collected book as one PDF beside its
chapters, and the runner plans it, reports it, and then does not ingest it:
reading a few hundred typeset pages as a single article is a long ingest
producing a draft nobody wants. `COLLECTED_RE` catches five of the six by
name, but volume 6 names its copy for the volume's theme
(`technical.pdf`), so length decides it. A chapter in this archive runs 5
to 29 pages and matter 1 to 8, while a collected volume runs 219 to 410, so
`COLLECTED_MIN_PAGES` sits at 100 with room either side. File size does not
separate them; the longest chapter outweighs the shortest volume. A
manifest entry naming a file overrides the skip, and a PDF that will not
open is left in the plan for ingest to report by name.

**An article can render as two galleys.** `teacher-resources: separate` in
the front matter splits a chapter at its `Teacher Resources` heading, so the
material addressed to instructors renders as its own document
(`teacher-resources.pdf` / `.html`) beside the chapter. It is opt-in per
article, not per journal, because it is a property of how a piece is
written. `article.md` stays the one canonical copy: the split writes derived
`.chapter.md` / `.teacher.md` intermediates, which are gitignored. Footnote
definitions move to whichever half refers to them, since Markdown collects
them at the end of the document, behind the teacher material. `render_pdf`
and `render_html` take a `part`, pass it to the filters as
`graphion-part`, and write to separate intermediates; the Writing Spaces
filter uses it to keep the drop cap out of the teacher galley. Both galleys
are served from the article page; see `serve_teacher_pdf` in `app.py`.

**A volume shares one licence.** `ingest_volume.py` writes `license` and
`license-url` over every chapter in a run, rather than leaving each to the
notice printed on its own opening page: a chapter whose footnote failed to
extract would otherwise publish with no licence recorded. The HTML galley
carries it as `rel="license"`, a `dcterms.rights` meta, and a visible
statement closing the document. The PDF gets a colophon, but only when
`conversion.should_print_license()` finds the body silent: a published
chapter prints its own terms as a footnote on its opening page and ingest
recovers that, so printing the metadata licence as well would state it twice
on one galley. Recovering it is not the same as guaranteeing it, which is
what the colophon is for. A Lua filter that walks the whole document reaches
metadata too, which is how soft break points for long URLs ended up inside
the licence href; walk `doc.blocks`, not `doc`.

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

- `app.py` (2672 lines) is the whole HTTP surface. `conversion.py` (2156) is the
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

**The volume holds two kinds of thing.** `deploy/entrypoint.sh` refreshes
per-journal template bundles from the image on every boot, because they are
versioned source; it seeds article and issue content no-clobber, because that is
data an editor produced. `template/assets/` is volume-owned so uploaded
wordmarks survive. A template edited on the volume is replaced by the next
deploy; edit it in git.

## Committing

The remote is `https://github.com/justalewis/graphion.git`. Work is only portable
across machines once it is pushed, so commit and push before switching
workstations. Never commit `data/graphion.db`, rendered galleys, or anything
under `content/**/_unfiled/`; `.gitignore` already covers these.
