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

- **Python 3.11+**
- **Pandoc 3+** ([install instructions](https://pandoc.org/installing.html))
- A modern web browser

Typst, pypdfium2, bibtexparser, and friends install via pip.

### Install

```bash
git clone https://github.com/justalewis/stylus.git
cd stylus
pip install -r requirements.txt
```

### Initial setup

```bash
python seed.py
```

You'll be prompted for an admin username and password. Defaults
create the LiCS example journal so you can see a complete configuration.

### Run

```bash
python app.py
```

Open <http://127.0.0.1:5050>. Sign in with the admin credentials you
just created.

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
CSL stylesheet, wordmark image) under
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
- Editing the template bundle files directly (CSS, Typst, Lua filters)

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
