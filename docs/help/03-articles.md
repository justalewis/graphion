# Articles

Each article is a directory of files under a journal. Here's what you do with one.

## Uploading

From a journal page, click **Upload DOCX**. The form takes:

- The `.docx` file (required)
- Optional slug (auto-derived from the filename if blank). The slug becomes the article's directory name and must be unique per journal.
- Optional title hint (overridden by the docx's Title-styled paragraph if present).
- **Short title** and **short authors** (required) — these become the running headers in the PDF.
- Tracked changes: accept or reject (accept is the default).

What happens on submit:

1. The docx is copied into the article directory as `source.docx`.
2. Pandoc converts it to Markdown, extracting embedded media into `assets/`.
3. python-docx reads the docx Title style separately (Pandoc doesn't preserve it).
4. The cleanup pipeline runs: strip Word highlight/underline wrappers, normalize dashes/quotes, extract the preamble into YAML front matter.
5. The result is `article.md`, the canonical source from this point forward.

## The article home page

You'll see:

- Title and status badge.
- An action row: **Edit metadata** · Edit (WYSIWYG) · Edit Markdown · Run lint · Render · View HTML · View PDF · Download EPUB · Download JATS XML · Download CrossRef XML.
- A **Bibliography (BibTeX)** drop-target to upload `references.bib`.
- The conversion log, a timestamped trace of every stage and save that's run.

## Editing metadata

The metadata form is form-based — you don't see YAML. Sections:

- **Identification:** Title, subtitle, DOI, status (draft / revising / final / published), ToC section (ARTICLES / SYMPOSIUM / BOOK REVIEWS or whatever the journal configures).
- **Authors:** repeating rows of Name / Affiliation / ORCID, with up/down/remove buttons. Drag-and-drop reorder is not yet supported; use arrows.
- **Content:** abstract (textarea) and keywords (comma- or semicolon-separated).
- **Running headers & pagination:** short title, short authors, footer text, start page.
- **Issue assignment (advanced):** override the inherited journal/volume/issue/year if needed.

On save, the form serializes back to YAML in `article.md` (preserving the body) and **auto-runs Render** so HTML and PDF reflect the new metadata immediately.

A safety net: scalar fields (title, subtitle, short-title, short-authors, footer, doi, journal, status) get any embedded whitespace collapsed before write so the YAML round-trips cleanly. Round-trip validation refuses to write unparseable YAML.

## Editing the body

Two editors, same backing file:

- **WYSIWYG (ProseMirror).** Better for non-technical editors. Toolbar: bold, italic, code, link, H1–H3, paragraph, bulleted/numbered lists, blockquote, undo/redo. Keyboard shortcuts (Ctrl+B, Ctrl+I, Ctrl+S). Serializes back to Markdown on save.
- **Markdown (CodeMirror).** Better for power users who want raw control. Live preview pane on the right.

Each save snapshots the previous `article.md` into `.versions/article-{timestamp}.md` (last 5 kept).

## Linting

Click **Run lint** for a one-shot validation pass with 11 checks:

- required fields (title, short-title, short-authors, author)
- ORCID format
- DOI format (`10.NNNN/...` shape)
- Short title length
- Short authors length
- Hyperlink well-formedness
- Works Cited section presence
- In-text citations matching Works Cited surnames (heuristic; the BibTeX system is more authoritative)
- Leftover cleanup-pass artifacts
- Image alt text presence
- Figure cross-references (every `@fig:X` resolves to a defined image)

Results are pass/warn/fail. Warnings don't block publishing — they advise.

## Rendering

Click **Render** to regenerate HTML and PDF. Both run sequentially via Pandoc (HTML) and Pandoc-to-Typst-then-typst-py (PDF). EPUB and JATS are rendered on demand the first time you request them.

If `references.bib` exists, Pandoc invocations include `--citeproc --bibliography=references.bib --csl=<journal>/mla.csl`. Body citations like `[@smith2023]` resolve and a Works Cited section is auto-generated.

## Status, publishing, archiving

`status` is a metadata flag that drives the badge color in lists. The current model is intentionally lightweight; there's no enforced lock or audit trail. A formal publish workflow that locks metadata and archives a snapshot is on the roadmap.
