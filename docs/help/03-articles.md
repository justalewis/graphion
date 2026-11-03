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

If the DOCX contains a picture Pandoc could not place (typically an image inside a text box), the upload saves it to `assets/media/` and flashes a warning naming the file; place it with **Insert image** in the Markdown editor.

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
- **Running headers & pagination:** short title, short authors, footer text, start page, and **Hide page numbers (author proofs)**, which leaves the folio off every PDF page for proofs sent before the issue order is set. Assembling the issue turns page numbers back on.
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

Click **Run lint** for a one-shot validation pass with 16 checks:

- required fields (title, short-title, short-authors, author)
- ORCID format
- DOI format (`10.NNNN/...` shape)
- Short title length
- Short title matching the full title (catches a typo that shows only in the running header)
- Short authors length
- Hyperlink well-formedness
- Works Cited section presence
- In-text citations matching Works Cited surnames (heuristic; the BibTeX system is more authoritative)
- Leftover cleanup-pass artifacts
- Characters no reader can read (private use and control codepoints, which arrive from symbol fonts)
- Image alt text presence
- Equations with no spoken description (see [Figures](06-figures.md#equations))
- Figures carrying text as a picture, from the `images-of-text` list
- Figure coverage (an article that refers to figures it does not contain)
- Figure cross-references (every `@fig:X` resolves to a defined image)

Results are pass/warn/fail. Warnings don't block publishing — they advise.

Every run is recorded, with the date and a hash of the `article.md` it read.
The **Accessibility** page in the top nav rolls those up per journal, so
"where does this journal stand" is one page rather than one article at a
time, and it carries a button that checks every article in a journal in one
pass. The two validators, **Validate PDF/UA** and **Audit HTML**, are
recorded the same way when you run them per article.

Those two call external tools, verapdf and pa11y, and neither is bundled.
With the tool missing, the button tells you so and records nothing, because
a row saying it could not run would be the newest run for that check and
would hide whatever a real run had found. To check a whole journal at once,
run `python validate_galleys.py <journal-slug>` from a terminal; it is a
script rather than a button because each tool can take a couple of minutes
an article.

The PDF galley answers for itself. Every render reads the finished
`article.pdf` back and records what it declares about its own conformance:
whether it is tagged, whether it carries the PDF/UA-1 identifier, whether its
XMP metadata holds a title, whether it opens showing that title rather than
the filename, and whether it states a language. Typst checks PDF/UA instead
of merely claiming it, so one undescribed figure makes it refuse; the render
falls back so you still get a galley, and this is the line that tells you
afterwards that it did. The reason Typst gave is in the article's **Logs**
tab. An article that renders a separate teacher galley has that one read too.

Each issue heading on the journal page is a link to that issue's own page,
which carries the same tables for its articles alone. That is the address
to send somebody when the question is about one volume rather than a
journal.

The journal page links to a **conformance report**: all 50 WCAG 2.1 Level
A and AA criteria with a support level against each, the checks that back
it named on the row, and the date. It is generated from the register rather
than typed, so it cannot say anything the checks did not find, and it is
the document an institution asks for before adopting a journal. Roughly a
third of the criteria read "Not Evaluated", because no machine can check
them; that is the honest shape of a generated report rather than a gap in
it. Print the page to hand it to somebody.

A recorded result counts only while the file it read is unchanged. Edit the
article and its last lint shows as *older version*, not as a pass; the page
would otherwise look better the longer nobody re-ran anything.

The journal page also totals the work itself, under **What is still owed**.
A pass or a warning tells you an article has something outstanding; it does
not tell you how much, and how much is usually the first thing you want to
know. So the figures with no alt text, the ones whose alt text says only
that they are undescribed, the ones carrying text as a picture, the
equations with no spoken description and the figures the prose refers to
and the galley does not hold are all added up across the journal, with the
figures already described by hand beside them. Only articles whose lint is
current are counted, and the note under the table says how many are not.

## Rendering

Click **Render** to regenerate HTML and PDF. Both run sequentially via Pandoc (HTML) and Pandoc-to-Typst-then-typst-py (PDF). EPUB and JATS are rendered on demand the first time you request them.

If `references.bib` exists, Pandoc invocations include `--citeproc --bibliography=references.bib --csl=<journal>/mla-9.csl`. Body citations like `[@smith2023]` resolve and a Works Cited section is auto-generated.

## Status, publishing, archiving

`status` is a metadata flag that drives the badge color in lists. The current model is intentionally lightweight; there's no enforced lock or audit trail. A formal publish workflow that locks metadata and archives a snapshot is on the roadmap.
