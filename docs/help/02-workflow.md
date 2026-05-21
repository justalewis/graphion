# Workflow: start to finish

This is the full pipeline an article and issue move through, from manuscript handed off by the author to published galleys + CrossRef deposit.

## Per-article

```
.docx manuscript
   ↓ (Upload DOCX on the journal page)
Stage 1: ingest
  • Pandoc converts docx → article-raw.md (clean Markdown, extracted media)
  • python-docx pulls the Title-styled paragraph for the article title
  • Tracked changes are accepted by default (configurable on upload)
   ↓
Stage 2: cleanup
  • Strip Word highlight (.mark) and underline (.underline) wrappers
  • Reassemble multi-line headings split by |
  • Normalize dashes and quotes
  • Extract author/affiliation/keywords/abstract from preamble
  • Build a YAML front-matter block on top
  • Result: article.md (canonical source)
   ↓
Stage 3: edit (optional)
  • Edit metadata in a form (title, authors with ORCIDs, abstract, keywords,
    short title, short authors, footer, DOI, ToC section)
  • Or edit the body via WYSIWYG (ProseMirror) or raw Markdown (CodeMirror)
  • Run lint to surface ORCID/DOI/citation/alt-text/cleanup issues
   ↓
Stage 4: render
  • HTML — Pandoc + journal's template → article.html
  • PDF — Pandoc Typst template → article.typ → typst → article.pdf
    (6×9 book trim, EB Garamond, running headers, drop cap, etc.)
  • EPUB — Pandoc → article.epub
  • Renders re-run automatically when you save metadata
```

## Per-issue

```
Articles assigned to the issue (each has start-page set during assembly)
   ↓ (Assemble issue on the issue page)
For each article in order:
  • Set start-page in YAML
  • Re-render article PDF (Typst counter shifts to start-page)
  • Count rendered pages
  • Update DB with start_page and end_page
   ↓
Front matter rendered as a single PDF:
  • Cover (I)        — wordmark + journal name + year/vol/iss
  • Editorial team (II)
  • Editorial board + financial credit (III)
  • Mission statement (IV–V)
  • Editors' introduction (VI–VII)
  • Table of contents (VIII)
  All paginated with roman numerals; first page suppresses header/footer.
   ↓
Concatenate front matter + article PDFs into issue.pdf via pypdf.
   ↓
Download deposits:
  • CrossRef XML (per-article or per-issue batch)
  • JATS XML (per-article)
  • EPUB (per-article)
```

## Filesystem layout

```
content/
  journals/
    lics/
      template/                      ← journal design + assets
        article.css                  (semantic OJS-style HTML CSS)
        article.html.j2              (Pandoc HTML template)
        article.typ                  (Pandoc Typst template)
        lics-filter.lua              (journal-specific transformations)
        figures-filter.lua           (figure numbering + xrefs)
        mla.csl                      (citation style for citeproc)
        assets/
          wordmark.png               (committed brand asset)
      issues/
        v13-n1-2026/
          _issue.yaml                ← issue's canonical metadata
          articles/
            fernandes-2026/
              source.docx            (original upload, gitignored)
              article-raw.md         (pandoc output, gitignored)
              article.md             (canonical source, committed)
              references.bib         (optional BibTeX bibliography)
              article.html           (rendered, gitignored)
              article.pdf            (rendered, gitignored)
              article.epub           (rendered, gitignored)
              .versions/             (snapshots before each save)
              assets/                (figures extracted from docx)
              conversion.log         (timestamped trace of stages)
          issue.pdf                  (assembled, gitignored)
          _front_matter.pdf          (front matter only)
          issue-toc.json             (pagination map)
      _unfiled/
        my-new-article/             (articles not yet in an issue)
```

The filesystem is **self-documenting**: a successor editor can navigate it without the database. Each article's working files all live in one directory.

## Decision points editors make

- **When to clean up by hand vs. re-ingest:** if the cleanup pipeline missed something specific to the manuscript, fix it in the editor. If it missed something *systematic*, file an issue so the cleanup module learns about it.
- **When to use WYSIWYG vs. Markdown:** WYSIWYG for prose edits and structural changes (headings, lists, formatting); Markdown when you need raw control or want to paste in a citation block.
- **When to assemble:** as soon as the issue's article lineup is stable. Assembly sets each article's `start_page` so cross-references work. Re-assembling is fine and idempotent.
- **When to deposit:** after the issue is assembled and lint reports green. Manual upload to CrossRef admin at doi.crossref.org with the downloaded XML.
