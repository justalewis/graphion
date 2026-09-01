# Articles

Each article is a directory of files under a journal. Here's what you do with one.

## Uploading

From the dashboard click **Upload DOCX** next to the journal, or **Upload new DOCX** from the journal's own page. The form takes:

- **Source file** — `.docx` (Word), `.md`, or `.markdown`. Required.
- Optional slug (auto-derived from the filename if blank). The slug becomes the article's directory name and must be unique per journal.
- Optional title hint (overridden by the docx's Title-styled paragraph if present).
- **Short title** and **short authors** (required) — these become the running headers in the PDF.
- Tracked changes: accept or reject (accept is the default).
- **Ingest engine** (radio button): *Pandoc* (default) vs. *Mammoth*. Mammoth is offered if installed and often handles text-box-heavy DOCX better than Pandoc.
- **Round-trip through LibreOffice** (checkbox): if LibreOffice is on PATH, open + re-save the DOCX before ingest to flatten text boxes and clean autoformat junk.

What happens on submit:

1. The source is copied into the article directory as `source.docx` (or saved as `article-raw.md` for direct Markdown uploads).
2. If `.docx`: Pandoc (or Mammoth) converts it to Markdown, extracting embedded media into `assets/`.
3. python-docx scans the source and flashes warnings about text boxes, merged-cell tables, nested tables, missing alt text, or tracked changes left in the document.
4. python-docx reads the docx Title style separately (Pandoc doesn't preserve it).
5. The cleanup pipeline runs: strip Word highlight/underline wrappers, normalize dashes/quotes, repair Pandoc Div-style footnotes, split collapsed grid tables, convert single-cell callout tables to blockquotes, extract preamble into YAML front matter.
6. The result is `article.md`, the canonical source from this point forward.

## The article home page

The redesigned article page has four top-level zones:

1. **Breadcrumb** — Dashboard › journal › issue (if assigned) › article slug.
2. **Status strip** — at-a-glance state: last rendered time, sections / images / tables / words counts, missing-image flag, bibliography chip, CSS override chip.
3. **Action grid** — four labeled clusters:
   - **Edit ▾** dropdown: Metadata / Rich (TinyMCE) / Lite (ProseMirror) / Markdown.
   - **Render** — big primary button, keyboard shortcut `R`. Subtitle: `→ HTML · PDF · EPUB`.
   - **Outputs** — appears once rendered: View HTML, View PDF, **Download ▾** dropdown grouped *For readers* / *For indexers* / *For OJS submission*.
   - **Tools** — Run lint + **Advanced ▾** dropdown: alternate render engines, validators, OCR, AI assist.
4. **Tabs**: Overview · Preview · Logs · Settings (keyboard shortcuts `1`-`4`).
   - *Overview* shows recent activity and snapshot count.
   - *Preview* embeds the rendered HTML in an iframe.
   - *Logs* contains the full conversion log.
   - *Settings* holds Bibliography (BibTeX) upload, per-article CSS override, and the **Danger zone** (Re-clean from source, Delete article).

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

Three editor options, all backed by the same `article.md`:

- **Rich (TinyMCE).** Full Word-like toolbar with tables (real cell-level editing), color picker, font controls, alignment, lists, images, find/replace, source view. Recommended for table-heavy articles or editors who prefer Word-style UI. Round-trip note: TinyMCE works in HTML; on save we convert HTML → Markdown via Pandoc with `grid_tables` enabled, so multi-paragraph cells and tables survive. The paste handler strips Microsoft Office `mso-*` style cruft automatically.
- **Lite (ProseMirror).** Lightweight, fast-loading WYSIWYG. Toolbar: bold, italic, code, link, H1–H3, paragraph, bulleted/numbered lists, blockquote, image upload, undo/redo. Best for plain prose; **warning**: does not support grid tables — opens and saves of articles with tables will mangle them. The Edit menu surfaces a warning chip (⚠) if the current article contains tables.
- **Markdown (CodeMirror).** Split-pane source editor with synced live preview. Bidirectional scroll-sync between source and preview, click-in-preview to jump cursor to the corresponding line. Toggle sync with `Ctrl+Shift+L`. Best for power users who want full source control. Insert image button on the toolbar uploads to `assets/` and inserts at cursor.

Each save snapshots the previous `article.md` into `.versions/article-{timestamp}.md` (last 5 kept).

## Per-article CSS override

Need one article to look slightly different from the rest of the journal — a special-issue piece, a tribute, a layout experiment? Drop a per-article stylesheet via the **Per-article CSS override** dropdown on the article home page.

The uploaded `article-override.css` loads *after* the journal's `article.css`, so it cascade-overrides rules you specify without forcing you to redefine the rest of the design. Example: change just the accent color and section-heading font for one article.

Affects the HTML galley and the EPUB. **The tagged PDF is rendered via Typst and isn't affected** — for one-off PDF customization, edit the journal template's Typst directly or duplicate the journal as a sibling and customize the duplicate's template.

Remove the override at any time via the **Remove override** button. The file lives at `article-override.css` in the article directory; deleting it manually has the same effect.

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

If `references.bib` exists, Pandoc invocations include `--citeproc --bibliography=references.bib --csl=<journal>/mla-9.csl`. Body citations like `[@smith2023]` resolve and a Works Cited section is auto-generated.

## Status, publishing, archiving

`status` is a metadata flag that drives the badge color in lists. The current model is intentionally lightweight; there's no enforced lock or audit trail. A formal publish workflow that locks metadata and archives a snapshot is on the roadmap.
