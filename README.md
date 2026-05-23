# Graphion

A single-editor publishing workstation for scholarly journals.
Markdown source in, **structured accessible HTML + tagged PDF + EPUB +
JATS XML + CrossRef deposit XML** out. Built for the layout/design
editor's workflow: take a manuscript handed off by an author, produce
publication-grade galleys with as little manual layout work as possible.

Originally developed for *Literacy in Composition Studies* (LiCS), now
generic enough to host other journals.

```
.docx manuscript
    ↓ ingest (Pandoc + python-docx)
clean Markdown with YAML front matter
    ↓ edit (form / WYSIWYG / Markdown)
    ↓ render (Pandoc + Typst)
HTML + tagged PDF + EPUB + JATS + CrossRef deposit
```

---

## Why this exists

Two problems it tries to solve:

1. **Accessibility.** Most scholarly content in rhet/comp lives in
   unstructured PDFs or HTML that fails screen-reader navigation,
   tagged-PDF compliance, and proper heading hierarchy. Graphion
   produces **semantic HTML5** (OJS-galley-style with `<article>`,
   `<section>`, `<aside>`, ARIA labels, alt text on figures,
   hanging-indent works cited via `class="references"`) and
   **tagged PDFs** via Typst's native tagging support, with
   document-level structure preserved so screen readers can navigate
   sections, headings, and figures.

2. **Scholarly infrastructure.** The same Markdown source emits
   **JATS XML** (the lingua franca of academic indexing) with
   structured `<contrib>`/`<aff>`/`<pub-id>`/`<element-citation>`,
   and **CrossRef deposit XML** with structured `<citation>` elements
   when a `references.bib` is provided. ORCIDs flow through to both.
   DOIs auto-assign from a journal-configured pattern. This means an
   article can be deposited to CrossRef, indexed by PubMed Central,
   listed on DOAJ, and resolved by reference linkers — all from the
   same canonical Markdown.

---

## Quickstart

### Prerequisites

- **Python 3.11+** (3.12 recommended)
- **Pandoc 3+** ([install instructions](https://pandoc.org/installing.html))
- A modern web browser

Typst (the PDF engine), pypdf, bibtexparser, and friends install via pip.

### Before you start

Install [Python 3.11+](https://www.python.org/downloads/) and [git](https://git-scm.com/downloads). On Windows, tick **"Add Python to PATH"** in the Python installer. Then open a terminal — **cmd** or **PowerShell** on Windows, **Terminal** on macOS — and check both are wired up:

```bash
python --version
git --version
```

If both print a version number you're ready. If you'd prefer a guided setup that runs these checks and walks through the install for you, clone the repo and run `python graphion-install.py`.

### Install (10 minutes, basic)

```bash
git clone https://github.com/justalewis/graphion.git
cd graphion
pip install -r requirements.txt
python seed.py            # prompts for an admin username + password
python app.py             # opens at http://127.0.0.1:5050
```

That gives you a fully working editor with HTML, PDF, EPUB, JATS, and CrossRef output. Optional integrations (Claude AI assistance, alternate PDF engines, accessibility validators, OCR) are described in the [Advanced Tools guide](docs/help/14-advanced-tools.md) and the [Installation guide](docs/help/12-installation.md).

If you'd rather have a script handle the checks and walk you through each step, run `python graphion-install.py` after cloning instead of the commands above.

### Quick install of optional integrations (Windows only, one-shot)

```cmd
:: Run as Administrator:
powershell -ExecutionPolicy Bypass -File .\install-graphion-deps.ps1
```

That installs Chocolatey if needed, then LibreOffice, Tesseract OCR, Node.js, Java 21, GTK3 runtime, verapdf, and pa11y. See the [Installation guide](docs/help/12-installation.md) for per-platform manual instructions.

### Enabling Claude AI assistance

Get an API key from <https://console.anthropic.com/>. In the shell where you run `python app.py`:

```bash
# macOS / Linux:
export ANTHROPIC_API_KEY=sk-ant-your-key-here

# Windows cmd:
set ANTHROPIC_API_KEY=sk-ant-your-key-here

# Windows PowerShell:
$env:ANTHROPIC_API_KEY = "sk-ant-your-key-here"
```

To make it permanent on Windows: `setx ANTHROPIC_API_KEY "sk-ant-..."` then **close and reopen the terminal**. On macOS/Linux, add the `export` line to your shell rc file.

Once set, the **Stylize article ★** button (Article page → Tools → Advanced) applies the journal's style guide to the article body in one Claude call: splits Works Cited entries, fixes tables, strips Word HTML cruft, normalizes typography. The per-journal style guide lives at `content/journals/<slug>/template/style-guide.md` — edit once, use forever.

### First article

1. From the dashboard, click **Upload DOCX** next to a journal
2. Upload a `.docx`. Fill in the **Short title** and **Short authors**
   (required for running headers).
3. Edit the metadata (form-based; no YAML required).
4. Click **Render**. HTML and PDF are produced.
5. Download EPUB, JATS XML, or CrossRef XML as needed.

The in-app **Help** section walks through every step.

---

## What you get out

| Format | What it is | What it's for |
|---|---|---|
| **HTML** | Semantic HTML5 with the journal's CSS | Web reading, OJS galley upload |
| **Tagged PDF** | Typst-rendered 6×9 with running headers, drop cap, hanging-indent works cited | Print archival, OJS PDF galley |
| **EPUB** | Pandoc-emitted EPUB3 with the journal's stylesheet | E-readers, library distribution |
| **JATS XML** | JATS-archiving-1.3 conformant | PubMed Central, DOAJ, JISC Sherpa |
| **CrossRef XML** | CrossRef 5.3.1 deposit XML | DOI registration |

---

## For other journals

The architecture is per-journal: each journal has its own template
bundle (CSS, Pandoc HTML template, Pandoc Typst template, Lua filters,
CSL stylesheet, wordmark image, **Claude style guide**) under
`content/journals/<slug>/template/`. The LiCS bundle ships as a
working example.

To add a new journal:

```bash
python new_journal.py <slug> "Full Journal Name"
```

This creates the template directory by copying the LiCS starter, then
inserts a row in the `journals` table. You then customize via:

- **Journal Settings** in the web UI (editorial team, board, mission,
  CrossRef config, header label template, wordmark upload)
- Editing the template bundle files directly (CSS, Typst, Lua filters,
  style guide)

### Adopting an existing print design (recommended if you have an IDML)

If your journal already has a print layout in InDesign, you can derive
your journal's typography directly from the IDML file:

1. **In InDesign**: File → Save As → format **InDesign Markup (IDML)**.
2. **Extract `Resources/Styles.xml`** from the IDML (it's a zip under the hood).
3. **Survey the paragraph styles** with the one-liner Python script in
   the [Installation guide](docs/help/12-installation.md#deriving-typography-from-an-existing-indesign-layout).
4. **Map values** (font, point size, leading, indent) into your
   journal's `template/article.typ` and `template/style-guide.md`.

A walkthrough with the exact commands, mapping table, and value-by-value
guidance is in the install guide:
**[Deriving typography from an existing InDesign layout](docs/help/12-installation.md#deriving-typography-from-an-existing-indesign-layout)**.

The LiCS bundle in this repo was derived this way — the typography
values in `content/journals/lics/template/article.typ` and the
canonical typography table in `content/journals/lics/template/style-guide.md`
both come from a LiCS InDesign IDML export. It's a 30-minute workflow
that pays for itself on every future article you lay out.

See **[Help → Templates & Customization](docs/help/08-templates.md)**
for the full guide, and **[Help → For Developers](docs/help/11-developers.md)**
for codebase architecture.

---

## Documentation

The `/help` route in the running app surfaces the docs with a sidebar
and inline rendering. The source lives in `docs/help/`:

- [01 Overview](docs/help/01-overview.md)
- [02 Workflow (start to finish)](docs/help/02-workflow.md)
- [03 Articles](docs/help/03-articles.md)
- [04 Issues & Front Matter](docs/help/04-issues-and-front-matter.md)
- [05 Citations & Bibliography](docs/help/05-citations.md)
- [06 Figures](docs/help/06-figures.md)
- [07 Output Formats](docs/help/07-output-formats.md)
- [08 Templates & Customization](docs/help/08-templates.md)
- [09 CrossRef Deposit](docs/help/09-crossref.md)
- [10 Troubleshooting & FAQ](docs/help/10-troubleshooting.md)
- [11 For Developers](docs/help/11-developers.md)

Roadmap and competitive audit: [docs/audit-and-roadmap.md](docs/audit-and-roadmap.md).

---

## Stack

- **Flask** + **Flask-Login** + **SQLite** — single-user editorial app
- **Pandoc** — Markdown to HTML/EPUB/JATS conversion + citation processing
- **Typst** (via `typst-py`) — book-quality PDF rendering
- **lxml** — CrossRef and JATS XML emission
- **mistune** — in-app help docs rendering
- **ProseMirror** (via ESM CDN) — WYSIWYG editor
- **bibtexparser** — BibTeX → structured citations
- **pypdf** — concatenating front matter + articles for issue assembly

Article content lives on the filesystem; SQLite indexes. The filesystem
layout under `content/` is self-documenting — a successor editor can
find the source files even if this app is gone.

---

## License

GPL-3.0. See [LICENSE](LICENSE) for the full text.

If you redistribute or modify this code, your modifications must be
shared under GPL-3.0 too. If you only use the tool to produce
publications and don't redistribute the code itself, no obligations
apply.

---

## Acknowledgments

Built with help from [Claude Code](https://claude.com/claude-code).
The classical typography template approximates the design language of
*Literacy in Composition Studies*' print issues; the
[Lewis Design System](https://github.com/justalewis/lewis-design-system)
supplies the admin UI tokens.
