# Advanced tools

Graphion can integrate with several external tools to handle problem documents, validate output, generate alt text with AI, and submit to OJS. **All are optional.** Missing tools degrade gracefully — the corresponding buttons in the UI become disabled with an "install X to enable" hint. No installation is required to use Graphion's core pipeline.

## DOCX-side preprocessors

### Mammoth — alternate DOCX reader

When to use: text-box-heavy documents, complex tables, anything where Pandoc's output looks broken.

```bash
pip install mammoth
```

After install, the **upload form** shows a radio button: *Pandoc (default)* vs *Mammoth*. Pick Mammoth for documents that Pandoc mangles.

Mammoth converts DOCX → HTML internally, then we pipe that HTML through Pandoc to get Markdown. The HTML intermediate is saved as `article-mammoth.html` in the article directory for inspection.

### LibreOffice — DOCX normalization

When to use: documents saved by old Word versions, documents with weird autoformatting, anything where you want a clean re-save before ingest.

Install LibreOffice from <https://www.libreoffice.org/>. The `soffice` binary must be on your PATH (Windows installers add it automatically to `C:\Program Files\LibreOffice\program\`).

After install, the **upload form** shows a checkbox: *Round-trip through LibreOffice before ingest*. Check it to apply.

The normalization opens your DOCX in LibreOffice headless and re-saves it. The round-trip flattens many Word quirks: text boxes get incorporated into the document flow, autoformat junk is cleaned out, broken style references resolve.

### DOCX structural scan

Always runs; no install needed. At upload time, Graphion uses `python-docx` to inspect your DOCX and flash warnings about:

- Text boxes present
- Tables with merged cells, > 6 columns, or nested tables
- Images missing alt text
- Tracked changes left in the document

The warnings don't block upload — they're informational so you know what to expect.

## Alternate PDF rendering

### WeasyPrint

When to use: you want the PDF to look exactly like the HTML galley (same CSS, same fonts, same layout).

```bash
pip install weasyprint
```

WeasyPrint also needs native libraries — `cairo`, `pango`, `gdk-pixbuf`. On Windows, the WeasyPrint installer or [MSYS2 bundles](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html#windows) include them. On macOS: `brew install cairo pango gdk-pixbuf`. On Linux: `apt install python3-cffi libpango-1.0-0 libpangoft2-1.0-0`.

After install, the article page shows a *Render PDF (WeasyPrint)* button in the Advanced section. Output is written to `article-weasy.pdf` so it doesn't clobber the Typst-rendered `article.pdf`. The Typst path remains the default.

**Trade-offs**: WeasyPrint = HTML/PDF parity but less typographic refinement (no drop caps, weaker hyphenation, no tagged-PDF accessibility metadata). Typst = print-grade typography but separate template, possible HTML/PDF drift.

## Assessing an archive Graphion does not hold

*Assess* in the top bar, or `/assess`. Upload one PDF or a batch and it
reports what remediating them would take: how many figures are already
described and how many are still owed, how many pages would need OCR
first, whether each file carries a structure tree and how much of the
text that tree reaches, what each one declares about its own PDF/UA
conformance, and what sets type in a symbol font. Tick the verapdf box to
take a verdict as well, which is a different fact from a declaration.

Nothing is ingested. No article is created, no database row is written,
and the uploads are deleted when the page finishes rendering, so it is
safe to point at a folder somebody sent before any agreement exists.

Up to 25 files a pass, or 10 with verapdf on, because a browser request
has to finish. A whole back catalogue at once is the command line, which
has no cap and also reads HTML:

```bash
python assess.py path/to/folder --deep --validate
```

Add `--json` for the same readings as data, or `--recursive` for a tree
that is already laid out.

One number is deliberately missing, and it is the one that decides
whether an archive is finished: how many figures set their words as a
picture, which WCAG 1.4.5 is about. Nothing can tell a photograph of a
document from a photograph of anything else without looking, so that
count is got by hand and recorded per article in `images-of-text`.

## Taking a batch of PDFs in

Journal page → *Ingest a batch of PDFs*, or
`/journals/<slug>/ingest`. One PDF per chapter. Each is read, cleaned and
filed as a draft article, exactly as `ingest_volume.py` does it from a
terminal.

A chapter takes a few minutes, so this runs as a background job rather
than in the page: you get a job page to watch, and closing it does not
stop the run. *Jobs* in the top bar lists them. One job runs at a time
and the rest wait.

What the batch decides for itself:

- **Order** comes from the filename where it carries a chapter number
  (`19Irvin.pdf`). Where it does not, chapters sort by name and you set
  the order afterwards.
- **A collected volume** sitting beside its chapters is recognised by its
  length and left out, so a folder downloaded whole does not ingest the
  book as a 300 page article.
- **Repeated images** across the batch are read as the series' own mark
  rather than as figures.

What you decide:

- **Licence.** The default keeps whatever each chapter's own pages carry,
  and for an archive you did not publish it is the only safe choice. Only
  stamp one licence over a batch when you know the whole batch shares it:
  volume 1 of Writing Spaces does not, and one value across that run
  published the stricter terms over twelve chapters that permit
  derivatives.
- **Replace.** Off by default. A re-ingest rebuilds the body from the
  PDF, so alt text, long descriptions and the carried front matter fields
  ride through but anything else typed since the first ingest does not,
  and `.versions/` keeps only the last five.

Everything lands as a draft. Nothing is published by ingesting it, and
nothing is rendered until you ask. A chapter that will not open is
recorded on the job page by name and the rest of the batch carries on.

This is inference, not reading: where a PDF carries no structure tree,
the paragraphs, headings and emphasis come off the geometry of the page.
Run *Assess an archive* first if you want to know how much of a batch is
in that position before you commit to it.

## Accessibility validation

### verapdf — PDF/UA-1 compliance

Validates whether `article.pdf` meets the PDF/UA-1 formal accessibility standard. Required by some repositories.

Download from <https://verapdf.org/>. Add `verapdf` (the wrapper script) to your PATH.

Article page → Advanced → *Validate PDF/UA*. Result is flashed and the full JSON report is written to `verapdf-report.json` in the article directory.

### pa11y — HTML accessibility audit

Industry-standard HTML accessibility tester (used by BBC, GOV.UK, etc.).

```bash
npm install -g pa11y
```

(Requires Node.js.) Article page → Advanced → *Audit HTML accessibility*. Output: number of errors and warnings, full report in `pa11y-report.json`.

## AI-assisted cleanup

### Claude — Stylize article (one-button editorial polish)

The most useful AI feature in Graphion. **Article page → Advanced → Stylize article ★** sends your article body plus the journal's style guide to Claude in a single call. Claude applies every editorial convention in one pass:

- Splits run-on Works Cited entries into proper paragraphs
- Strips Microsoft Office HTML cruft (`<span style="mso-...">`)
- Normalizes quotes (curly), dashes (en for ranges, em for breaks), ellipses
- Repairs broken tables (collapsed-on-one-line, blank-lines-between-rows)
- Converts Pandoc Div-style footnotes to canonical `[^N]:` syntax
- Removes Pandoc HTML round-trip artifacts (`[?](#footnote-ref-N)` back-arrows, stray pipe characters)
- Restructures heading levels per the journal's convention
- Tightens paragraph structure (no doubled blanks, blank line around headings)

**How to customize per journal:** edit the file at `content/journals/<slug>/template/style-guide.md`. The default LiCS style guide ships with the repo. The guide is a plain Markdown file describing your editorial conventions — Claude reads it as context. You can:

- Change Works Cited format (MLA, APA, Chicago)
- Specify heading levels and capitalization
- Override quote / dash / ellipsis preferences
- Tell Claude what to fix and what to preserve

**Cost:** approximately $0.02–$0.05 per article (Haiku 4.5 pricing as of April 2026). The full article body is sent; Claude returns the rewritten body. The YAML front matter is preserved separately (never touched).

**Safety:** the original `article.md` is snapshotted to `.versions/` before the rewrite. If Claude misbehaves, use the **Snapshots** view to diff and restore.

**What it preserves:** the author's voice and word choice — Claude is explicitly instructed to never paraphrase or invent. Citations, URLs, footnote markers, block-quote contents are all kept verbatim.

### Claude (alt-text generation)

When to use: your article has images without alt text and you want concrete descriptions auto-generated.

```bash
pip install anthropic
export ANTHROPIC_API_KEY=sk-ant-…
```

(Get a key from <https://console.anthropic.com/>.) Restart the Flask app for the env var to apply.

Article page → Advanced → *Generate alt text (Claude)*. Graphion finds every `![](path)` in `article.md` with an empty alt field, sends the image to Claude vision, and writes the returned 1–2-sentence description back into the Markdown. Re-render to apply.

Cost: typically a few cents per article. Each image is one short API call.

The Claude integration also exposes `llm_cleanup.repair_mangled_table()` and `llm_cleanup.polish_paragraph()` as Python helpers — useful for scripted batch cleanups. Not yet wired to UI buttons.

## OCR for tables-as-images

### Tesseract

When to use: an author pasted a screenshot of a table from Excel/Sheets/etc. and you want to recover the text.

```bash
# Python wrapper:
pip install pytesseract Pillow
# Tesseract CLI (separate install):
#   Windows: https://github.com/UB-Mannheim/tesseract/wiki
#   macOS:   brew install tesseract
#   Linux:   apt install tesseract-ocr
```

Article page → Advanced → *OCR images (Tesseract)*. Graphion walks the article's `assets/` directory, OCRs every image, and writes the recognized text to `ocr-results.txt` per-image. Copy any tables from there into `article.md` as Markdown pipe tables.

`ocr.ocr_to_markdown_table(path)` is also available as a Python helper for one-shot table reconstruction (heuristic, works best for clean screenshots).

## OJS REST API integration

Direct galley submission to an OJS journal — closes the "download zip, log into OJS, upload, configure" loop.

Configure two env vars (or per-journal DB fields, planned):

```bash
export OJS_URL=https://your-ojs-site.org/index.php/your-journal/api/v1
export OJS_API_TOKEN=…   # generated in your OJS user profile
```

The `ojs_client` Python module exposes `upload_galley()` and `list_submissions()`. UI integration on the article page is currently a TODO; the module is callable from a Python REPL or a custom script.

OJS REST API surface evolves between versions; the client is built to be easy to patch. See `ojs_client.py` for endpoint paths used.

## Verifying what's installed

The article page's *Advanced* section shows each button greyed-out when its underlying tool isn't found, with a hover tooltip explaining what to install. The probes are cheap (no actual API calls), so the page renders quickly even when checking all five.

You can also check from a Python REPL:

```python
import preprocessors, validators, llm_cleanup, ocr, conversion
print(preprocessors.mammoth_available())
print(preprocessors.libreoffice_available())
print(conversion.weasyprint_available())
print(validators.verapdf_available())
print(validators.pa11y_available())
print(llm_cleanup.available())
print(ocr.available())
```
