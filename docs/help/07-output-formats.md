# Output formats

The tool produces five output formats from each article's Markdown source. All are derivative; the Markdown is canonical.

## HTML

`/articles/<id>/html` — a self-contained HTML5 galley using the journal's `article.css` and `article.html.j2` Pandoc template.

Structure (LiCS):

```html
<article class="ojs-article-frame">
  <header class="article-meta">
    <h1>Title</h1>
    <p class="byline">Author — Affiliation</p>
    ...
  </header>
  <aside class="keywords">...</aside>
  <section class="abstract">...</section>
  <section class="level1 opening">
    <h1 class="opening">Introduction</h1>
    <p>Body text with drop cap...</p>
    ...
  </section>
  <section class="level1 references" id="works-cited">
    <h1>Works Cited</h1>
    ...
  </section>
</article>
```

Best for: web reading, uploading as the OJS HTML galley, archival.

## Tagged PDF (Typst)

`/articles/<id>/pdf` — a 6×9 book-trim PDF rendered via Pandoc-to-Typst-to-typst-py. Tagged (accessible), with running headers (verso = short authors, recto = short title), centered page counter, drop cap on the opening section, hanging-indent works cited, small-caps section headings.

Best for: print archival, download distribution, OJS PDF galley.

For continuous-pagination across an issue, each article gets `start-page` set during issue assembly so its page counter begins at the right number.

## EPUB

`/articles/<id>/epub` — Pandoc-emitted EPUB3 with the journal's CSS as the stylesheet. Render on demand the first time you click the link; cached as `article.epub` for subsequent downloads.

Best for: e-reader distribution, libraries, accessibility consumers who prefer reflowable text.

## JATS XML

`/articles/<id>/jats.xml` — JATS-archiving-1.3 conformant XML. Contains:

- `<journal-meta>` — journal title, ISSN
- `<article-meta>` — DOI, title, authors (with given-names + surname + ORCID + affiliation), pub-date, volume, issue, fpage/lpage, abstract, kwd-group
- `<body>` — Pandoc-rendered JATS body (sections, paragraphs, blockquotes, lists, inline formatting)
- `<back><ref-list>` — structured `<element-citation>` from `references.bib` if present, else `<mixed-citation>` from the Works Cited prose

Best for:

- **PubMed Central** (PMC) submission — JATS is the lingua franca of academic indexing.
- **JISC Sherpa, DOAJ, Crossref, Scopus** — all expect or prefer JATS.
- **Archival** — long-term content preservation in a standards-based format.

## CrossRef deposit XML

`/articles/<id>/crossref.xml` — CrossRef 5.3.1 conformant XML for DOI deposit.

Per-article XML contains the article's metadata plus citations (structured if BibTeX, unstructured if Markdown).

Issue-level XML at `/issues/<id>/crossref.xml` batches all the issue's articles into one `<doi_batch>` for a single upload.

Best for: depositing DOIs at CrossRef. Manual upload to <https://doi.crossref.org> from the Submission tab. DOIs are minted on successful deposit.

## Triggering renders

- Click **Render** on the article home — produces HTML and PDF.
- Click **Assemble issue** — for every article, sets `start-page`, re-renders the PDF, counts pages, then builds the issue front matter PDF and concatenates everything into `issue.pdf`.
- Saving metadata via the form auto-runs Render (so the rendered files reflect current metadata).
- EPUB and JATS render on first download request and are cached.

## What gets gitignored, what gets committed

The canonical source — `article.md` — is committed. Generated outputs (`article.html`, `article.pdf`, `article.epub`, `article.typ`, `_front_matter.pdf`, `_cover.pdf`, `_cover.typ`, `issue.pdf`) are gitignored; they can always be regenerated from the source.

Article assets (figures, source.docx) are also gitignored per-article. Template assets (the journal's wordmark, CSS, Lua filters, CSL) are committed.

The DB (`data/stylus.db`) is gitignored. To reproduce a project state from git, restore the DB by walking the filesystem.
