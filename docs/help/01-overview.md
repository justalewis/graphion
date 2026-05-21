# Overview

LiCS-Pipeline (working codename **Stylus**) is a single-editor publishing workstation for scholarly journals. Its job is to take a Word manuscript handed off by an author and turn it into a clean, well-typeset, indexable, deposit-ready issue with as little manual layout work as possible.

## Who this is for

You are most likely:

- a journal's **layout/design editor** doing production work for an issue,
- a **managing editor** wanting to see the article's structure and metadata at a glance, or
- a **technical editor** preparing CrossRef deposits or JATS for indexers.

You do not need to know Markdown, Pandoc, or Typst to use it — though knowing those will let you go deeper if you want. Most editorial tasks happen through forms.

## What this tool does

In plain terms:

1. You upload a Word `.docx`. The tool converts it to clean Markdown and pulls out title, authors, abstract, keywords automatically.
2. You edit metadata in a form (or fix the Markdown directly in a WYSIWYG editor, or as raw Markdown for power users).
3. You click Render. The tool produces a publication-grade HTML galley and a tagged PDF (6×9 book trim by default for LiCS, with running headers, drop cap on the opening section, hanging-indent works cited).
4. You assemble articles into an issue. The tool produces an issue PDF with continuous pagination (roman numerals across the front matter, arabic restarting at 1 for article 1), a generated cover, masthead, mission statement, editors' introduction, and table of contents.
5. You download CrossRef XML and JATS XML for deposit, EPUB for e-reader distribution, and HTML/PDF for the public galleys.

## What this tool deliberately does *not* do

- **Author submission & peer review.** That's what OJS, Janeway, and Scholastica are for. Stylus assumes the manuscript has already been accepted.
- **Multi-user role-based access.** Single editor at a time. Not built for distributed teams.
- **Hosting the public reader-facing journal site.** It produces galleys and metadata; you host them on OJS or wherever your journal lives publicly.
- **Replacing your designer.** The journal's template bundle (CSS, Typst, Lua filters) is itself a design artifact — it just lives in a repo where it can be reviewed, versioned, and iterated on.

## How it's built

Stack: **Flask + SQLite + Pandoc + Typst**. Article content lives on the filesystem; SQLite is just an index. The journal's design lives in a per-journal template bundle (`content/journals/<slug>/template/`). Outputs are rendered on demand; nothing is precomputed or cached except snapshots of your prior edits.

The tool is single-user, runs locally, and ships as a small Flask app. There's no SaaS to log into; you run it on your machine.

## Where to go next

- **[Workflow](workflow)** — the full pipeline from manuscript to deposit.
- **[Articles](articles)** — what you do with each article along the way.
- **[Issues & front matter](issues-and-front-matter)** — how an issue is assembled.
- **[Citations & bibliography](citations)** — Markdown citation syntax + BibTeX + MLA.
- **[Output formats](output-formats)** — HTML, PDF, EPUB, JATS, CrossRef.
- **[Troubleshooting](troubleshooting)** — when things go wrong.
