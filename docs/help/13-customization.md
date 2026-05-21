# Customization for other journals

Graphion ships with one example journal (LiCS) configured. The architecture is per-journal: each journal has its own template bundle, its own configuration, its own articles and issues. Adding a new journal is well-supported.

## The quick path: scaffold a new journal

```bash
python new_journal.py mhrj "Modern Hispanic Review Journal"
```

This creates:

1. A row in the `journals` table with the slug `mhrj` and the full name.
2. A template directory at `content/journals/mhrj/template/` — copied from the LiCS starter bundle (CSS, Pandoc HTML template, Pandoc Typst template, Lua filters, CSL, front-matter schema).
3. A new entry that appears on the dashboard.

After scaffolding, finish configuration in **Journal Settings** at `/journals/mhrj/settings`:

- **Brand:** short name, wordmark image upload, header label template
- **Front matter:** editorial team, board, mission statement, financial credit
- **ToC sections:** the labels articles get grouped by
- **CrossRef:** DOI prefix, member ID, depositor name + email

Articles upload via the dashboard's per-journal Upload DOCX button, exactly as for the LiCS example.

## What each template file controls

```
content/journals/<slug>/template/
  article.html.j2       — Pandoc HTML template (Pandoc's $var$ syntax)
  article.typ           — Pandoc Typst template (drives the PDF look)
  article.css           — Stylesheet for HTML + EPUB
  journal-filter.lua    — Per-journal Lua transformations
  figures-filter.lua    — Figure auto-numbering + cross-refs (usually unchanged)
  mla.csl               — Citation Style Language for citeproc
  front-matter-schema.yaml — Documents required/optional metadata fields
  assets/
    wordmark.png        — Brand mark for the cover
```

### Changing the visual identity

The biggest aesthetic choice is in `article.css` (HTML/EPUB look) and `article.typ` (PDF look). The LiCS starter uses:

- **EB Garamond serif** for body and headings
- **Warm cream paper** (`#fbf7ee`)
- **Maroon accent** (`#613c3b`)
- **Small-caps centered section heads** with a hairline rule above
- **Drop cap** on the opening section
- **Hanging-indent Works Cited**

To rebrand a journal, the typical edits are:

- **Color palette:** Search for `--ink`, `--paper`, `--accent` and the like at the top of `article.css`. The Typst template uses these as `rgb("#...")` literals near the top of `article.typ`.
- **Body font:** Change the `--serif` (CSS) and `text(font: ...)` (Typst) values. Adding a Google Fonts import at the top of CSS pulls in new web fonts.
- **Page trim:** `width: 6in, height: 9in` in Typst — change to US Letter (8.5 × 11) or another size.
- **Section heading style:** the `article h1` rule in CSS, and the `#show heading.where(level: 1)` rule in Typst.

### Changing the structural transformations

`journal-filter.lua` runs over the parsed Pandoc AST before rendering. The LiCS version:

- Adds the `opening` class to the first H1 (enables the drop cap in CSS)
- Adds the `references` class to the Works Cited heading (enables hanging-indent)
- Injects a `#dropcap[X]` raw Typst inline at the start of the first paragraph of the opening section

If your journal has different structural conventions — e.g., pull quotes in a special class, epigraph styling, footnote handling — add the transformations here.

### Changing the citation style

The journal's `*.csl` file is the citation stylesheet. Default is MLA 9. To use another style:

1. Download the appropriate CSL from <https://github.com/citation-style-language/styles> (Chicago, APA, IEEE, etc.).
2. Save it into the journal's template directory.
3. The renderer picks up the first `.csl` it finds. Delete the old one or rename it.

## What you can configure without editing files

These all live in the database, set via Journal Settings:

| Setting | Where it shows up |
|---|---|
| Short name | Running headers, wordmark text fallback |
| Wordmark image | Cover of every issue |
| Header label template | The italic running header (e.g., `*{short_name}* {volume}.{issue} / {season}`) |
| Editorial team | Front-matter page II |
| Editorial board | Front-matter page III (top) |
| Financial credit | Front-matter page III (bottom) |
| Mission statement | Front-matter pages IV–V |
| ToC section labels | How articles group on the contents page |
| CrossRef prefix, member ID, depositor identity | Deposit XML |

## Customizing the cover

The cover is rendered by `render_front_matter` in `conversion.py`. For the level of customization most journals need:

- **Default layout** (image wordmark + italic running header + year/vol/iss bottom-right): edit Journal Settings, upload your wordmark, and you're done.
- **More radical layouts** (a designed cover with multiple typographic elements, a custom rule pattern, a special-issue art piece): edit `render_front_matter` in `conversion.py`. The Typst the function emits is plain Typst code; modifying it is just editing a Python f-string.

For one-off layouts (e.g., a special-issue art cover), you can also override the cover entirely by replacing `_cover.pdf` in the issue directory after assembly. Be aware the next Assemble click will overwrite it.

## Multi-journal coexistence

Multiple journals coexist in the same Graphion install:

- Each appears on the dashboard.
- The Issues tab lists issues across all journals.
- The CrossRef tab shows per-journal config status side by side.
- Articles cannot move between journals (the slug is unique per journal, and the filesystem encodes journal in the path). To migrate, manually move the directory and update the DB row.

## When you've outgrown what configuration covers

Some changes require code edits, not just configuration. The roadmap doc (`docs/audit-and-roadmap.md`) tracks what's planned. For unplanned needs:

- **Codebase architecture** is documented in [Help → For Developers](11-developers).
- The cleanup pipeline is composable (one regex pass per `cleanups.py` function); adding a new pass is small.
- The Lint module is composable; new validation checks plug in trivially.
- Output formats can be added by writing a new emitter module (see `crossref.py`, `jats.py` for reference implementations).

## Sharing your customizations back

If you build something that other journals would benefit from (a different default template bundle, a new lint check, an extra output format), the project welcomes pull requests at the GitHub repo. The project is GPL-3.0; your contributions inherit the same license.
