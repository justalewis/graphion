# Overview

**Graphion** is a single-editor publishing workstation for scholarly journals. Its job is to take a Word manuscript handed off by an author and turn it into a clean, well-typeset, indexable, deposit-ready issue with as little manual layout work as possible.

## Who this is for

You are most likely:

- a journal's **layout/design editor** doing production work for an issue,
- a **managing editor** wanting to see the article's structure and metadata at a glance, or
- a **technical editor** preparing CrossRef deposits or JATS for indexers.

You do not need to know Markdown, Pandoc, or Typst to use it — though knowing those will let you go deeper if you want. Most editorial tasks happen through forms.

## What this tool does

In plain terms:

1. You upload a Word `.docx` (or a `.md` file you authored yourself). The tool converts it to clean Markdown and pulls out title, authors, abstract, keywords automatically. A pre-render scan warns you about text boxes, merged-cell tables, and other Word shapes that may need attention.
2. You edit metadata in a form, or fix the body via one of three editors:
   - **Rich (TinyMCE)** — full Word-like toolbar with tables, colors, alignment; recommended for table-heavy articles.
   - **Lite (ProseMirror)** — fast, simple WYSIWYG for plain prose.
   - **Markdown** — split-pane source editor with synced live preview, scroll-sync, and click-to-jump between source and preview.
3. (Optional) You click **Stylize article (Claude)**. The AI applies your journal's style guide in one pass: splits run-on Works Cited entries, strips Word HTML cruft, normalizes quotes and dashes, repairs broken tables, fixes footnote anchors, tightens paragraph structure.
4. You click **Render**. The tool produces a publication-grade HTML galley and a tagged PDF (6×9 book trim by default for LiCS, with running headers, drop cap on the opening paragraph, hanging-indent Works Cited, auto-landscape pages for wide data tables).
5. You assemble articles into an issue. The tool produces an issue PDF with continuous pagination (roman numerals across the front matter, arabic restarting at 1 for article 1), a generated cover, masthead, mission statement, editors' introduction, and table of contents.
6. You download CrossRef XML and JATS XML for deposit, EPUB for e-reader distribution, HTML/PDF for the public galleys, and a single **OJS package ZIP** that bundles HTML + CSS + assets for one-click upload to your OJS galley submission flow.

## What this tool deliberately does *not* do

- **Author submission & peer review.** That's what OJS, Janeway, and Scholastica are for. Graphion assumes the manuscript has already been accepted.
- **Multi-user role-based access.** Single editor at a time. Not built for distributed teams.
- **Hosting the public reader-facing journal site.** It produces galleys and metadata; you host them on OJS or wherever your journal lives publicly.
- **Replacing your designer.** The journal's template bundle (CSS, Typst, Lua filters) is itself a design artifact — it just lives in a repo where it can be reviewed, versioned, and iterated on.

## How it's built

Stack: **Flask + SQLite + Pandoc + Typst**. Article content lives on the filesystem; SQLite is just an index. The journal's design lives in a per-journal template bundle (`content/journals/<slug>/template/`). Outputs are rendered on demand; nothing is precomputed or cached except snapshots of your prior edits.

The tool is single-editor and ships as a small Flask app. You can run it locally on your own machine, or host one shared instance that editors reach in a browser; both are the same application, and the [Quickstart](quickstart) covers the hosted case. "Single-editor" describes the permission model rather than the installation: there are no roles, and everyone who signs in has the same full access.

## What's new (most recent additions)

- **Stylize article (Claude)** button. One click applies your journal's editorial conventions across the whole article — splits Works Cited, fixes tables, strips Word junk, normalizes typography. See [Advanced Tools](advanced-tools).
- **Three editor options**. Rich (TinyMCE), Lite (ProseMirror), Markdown (CodeMirror with synced preview).
- **`.md` upload** alongside `.docx` for users who hand-author or come from Writage.
- **Optional integrations**: Mammoth (alternate DOCX reader), LibreOffice (DOCX normalize), WeasyPrint (alternate PDF render), Tesseract (image OCR), verapdf (PDF/UA validation), pa11y (HTML accessibility audit). All gracefully degrade if not installed.
- **Auto-landscape for wide tables** (4+ columns) and 8pt auto-shrink for 2-3 column tables in the PDF.
- **Snapshot + diff** view for every save. Roll back any AI or editor change.
- **Bib Builder** from prose Works Cited (no `.bib` file needed).
- **Keyboard shortcuts**: `R` render, `E` rich edit, `M` markdown edit, `1`-`4` tabs, `Esc` close menus.

## Where to go next

- **[Workflow](workflow)** — the full pipeline from manuscript to deposit.
- **[Articles](articles)** — what you do with each article along the way.
- **[Issues & front matter](issues-and-front-matter)** — how an issue is assembled.
- **[Citations & bibliography](citations)** — Markdown citation syntax + BibTeX + MLA + Bib Builder.
- **[Output formats](output-formats)** — HTML, PDF, EPUB, JATS, CrossRef, OJS ZIP.
- **[Advanced tools](advanced-tools)** — Mammoth, LibreOffice, WeasyPrint, Claude, OCR, validators.
- **[Troubleshooting](troubleshooting)** — when things go wrong.
