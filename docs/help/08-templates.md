# Templates & customization

Each journal has a **template bundle** under `content/journals/<slug>/template/`. The bundle is what makes the journal's output look like *that journal*. Adding or customizing a journal means working with these files.

## What's in the bundle

```
content/journals/<slug>/template/
  article.html.j2        — Pandoc HTML template (Pandoc's $-syntax)
  article.typ            — Pandoc Typst template (for PDF)
  article.css            — Stylesheet for HTML and EPUB
  lics-filter.lua        — Per-journal Lua transformations
  figures-filter.lua     — Figure auto-numbering + cross-references
  mla.csl                — Citation Style Language for citeproc
  front-matter-schema.yaml — Documents required/optional metadata fields
  assets/
    wordmark.png         — Committed brand asset (for the cover)
```

The bundle is versioned in git alongside the application code. Changing the template is a commit, not a database edit.

## To add a new journal

1. Create the directory: `content/journals/<new-slug>/template/`.
2. Copy a starter set of files into it (the LiCS bundle is the reference).
3. Register the journal: insert a row in the `journals` table or extend `seed.py` to insert it.
4. Edit the bundle's files to match the journal's design.
5. Restart the Flask app.

Articles for the new journal go under `content/journals/<new-slug>/issues/...` or `_unfiled/`.

## Customizing the HTML

`article.html.j2` uses Pandoc's `$variable$` syntax for substitutions. Available variables: `$title$`, `$subtitle$`, `$author$`, `$abstract$`, `$keywords$`, `$body$`, plus anything else in the YAML front matter.

`article.css` provides the visual styling. The CSS is loaded by both the HTML galley and the EPUB. The LiCS CSS uses warm-cream paper, EB Garamond serif, small-caps section heads, drop cap, hanging-indent works cited.

If you want a different look, edit `article.css`. Common edits:

- Color palette: search for `--ink`, `--paper`, `--accent`, etc. at the top.
- Font: change the `--serif` variable.
- Page width: change `--measure`.
- Section heading style: edit the `article h1` rule.

## Customizing the PDF

`article.typ` is the Pandoc Typst template. Pandoc substitutes article metadata into it, then writes the resulting `.typ` to disk. The Typst Python wrapper compiles that to PDF.

Common edits:

- **Page trim:** change `width: 6in, height: 9in` in `#set page(...)`.
- **Margins:** the `margin: (top: ..., ...)` parameter on the same `#set page` call.
- **Running header content:** the `header: context { ... }` block.
- **Footer content:** the `footer: context { ... }` block.
- **Title block, section-h1, body paragraph styling:** `#show` rules near the top.

Typst is documented at <https://typst.app/docs>. The syntax is more programming-language-ish than LaTeX.

## Customizing the Lua filter

`lics-filter.lua` runs over the parsed Pandoc AST before rendering. It does journal-specific transformations:

- Adds the `opening` class to the first H1 section (enables the drop cap in CSS).
- Adds the `references` class to the Works Cited heading (enables hanging-indent styling).
- Injects a `#dropcap[X]` raw Typst inline at the start of the first paragraph of the opening section (for the Typst path only; HTML uses CSS `::first-letter` instead).

`figures-filter.lua` handles figure numbering and cross-references; this is journal-agnostic but lives in the per-journal bundle for now.

If you need a new journal-specific transformation (a special pull-quote class, an epigraph layout, etc.), add it to the journal's Lua filter.

## Front-matter customization

The front-matter rendering lives in `conversion.py:render_front_matter()`. It produces a single multi-page Typst document with:

- Cover (wordmark + journal name + year/vol/iss)
- Editorial Team (from `editorial_team_json` on the journal)
- Editorial Board + financial credit (from `editorial_board_json` + `financial_credit_md`)
- Mission statement (from `mission_statement_md`)
- Editors' introduction (from a `kind=editorial` article)
- ToC (grouped by article `section` field)

Most journals will customize via the **Journal Settings** form (no code changes needed). For deeper changes — different ordering of front-matter sections, a different cover layout, etc. — edit `render_front_matter()` in `conversion.py` or the Typst it emits.

## Multi-journal

The tool supports multiple journals. Each gets its own template bundle, its own journal row, its own issues, its own articles. The CrossRef tab shows all journals side by side.

Articles cannot move between journals (the slug is unique per journal, and the directory structure encodes the journal). To migrate an article, you'd manually move the directory and update the DB row.
