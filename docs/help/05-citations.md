# Citations & bibliography

Two ways to handle references, depending on how much structure you want.

## Option A: prose references in the body (default)

Write a `# Works Cited` heading near the end of your article followed by one paragraph per reference, MLA-formatted by hand. In-text citations look like `(Smith 42)` or `(Jones and Lee 87)`. Nothing more is required.

What this gets you:

- A rendered Works Cited section with hanging-indent (the journal's CSS does this).
- CrossRef deposit XML with `<unstructured_citation>` entries (one per Works Cited paragraph).

What this *doesn't* get you:

- Linkable reference IDs (each `<citation>` carries the prose text but not the structured fields like `<doi>`, `<article-title>`, etc.).
- Indexer-friendly structured citations in CrossRef and JATS.
- Automatic Works Cited regeneration if the style changes.

This is fine for most articles you're laying out from manuscripts that already use prose citations.

## Option B: structured bibliography via BibTeX

Drop a `references.bib` into the article via the **Bibliography (BibTeX)** uploader on the article home page (or place the file directly at `content/journals/<slug>/issues/<issue>/articles/<article>/references.bib`).

**Don't have a `.bib` file from a reference manager?** The top-nav **Bib Builder** takes a pasted prose Works Cited list (MLA, APA, or Chicago) and emits a `.bib`. It's a heuristic — review the output before uploading — but it's much faster than typing entries by hand. The article's bibliography uploader links to it directly. Patterns the parser recognizes:

- Authors in either `Last, First` (MLA) or `Last, F. M.` (APA) form, with `et al.` and the MLA repeat-dash (`---.`) supported.
- Italicized book or journal titles (`*Title*`) and double-quoted article titles.
- Volume/issue in MLA (`vol. 57, no. 4`), Chicago (`57, no. 4`), and APA (`57(4)`) forms.
- Page ranges with or without the `pp.` prefix.
- DOIs (`https://doi.org/...` or `doi:...`) and bare URLs.

Anything that doesn't classify cleanly drops into a `note` field so the citation isn't lost.

Write in-text citations using Pandoc citation syntax:

```markdown
As Crawford notes [@crawford2021, p. 7], the supply chain ...

Earlier work by @hao2023 and @tacheva2023ai established ...
```

On render, the tool passes `--citeproc --bibliography=references.bib --csl=<journal>/mla-9.csl` to Pandoc. Citations resolve to MLA-formatted in-text references, and a Works Cited section is generated automatically. Don't write a manual Works Cited heading in the body when using this mode.

What this gets you:

- **Structured CrossRef citations** with `<journal_title>`, `<author>`, `<volume>`, `<first_page>`, `<cYear>`, `<article_title>`, `<doi>`, etc.
- **Structured JATS `<element-citation>`** with `<person-group>`, `<source>`, `<fpage>`, `<lpage>`, `<pub-id>`.
- Citation linking in indexer downstream tools.
- Style switches: replace `mla-9.csl` with another CSL (Chicago, APA, etc.) and re-render — the bibliography reformats automatically.

### BibTeX format reminder

```bibtex
@article{crawford2021,
  author  = {Crawford, Kate},
  title   = {Atlas of {AI}: Power, Politics and the Planetary Costs of Artificial Intelligence},
  journal = {Yale University Press},
  year    = {2021}
}

@article{tacheva2023ai,
  author  = {Tacheva, Jasmina and Ramasubramanian, Srividya},
  title   = {{AI} Empire: Unraveling the Interlocking Systems of Oppression},
  journal = {Big Data and Society},
  volume  = {10},
  number  = {2},
  year    = {2023},
  pages   = {1--14},
  doi     = {10.1177/20539517231219240}
}
```

Notes:

- The key (e.g., `crawford2021`) is the citation handle. Keep it stable; it shows up in the XML.
- Braces `{AI}` are BibTeX brace protection — they prevent lowercasing. The tool strips them when emitting CrossRef/JATS.
- Page ranges use double-dash (`1--14`); the tool splits to `<first_page>` and `<last_page>` for CrossRef and `<fpage>` / `<lpage>` for JATS.

## Citation style

By default, LiCS uses **MLA 9** (the most current MLA Handbook style at time of writing). The CSL file lives in the journal's template directory.

**To switch styles, the easy way:** go to **Journal Settings**, scroll to *Citation style*, pick from the dropdown:

- MLA 9
- APA 7
- Chicago 17 (author-date)
- Chicago 17 (notes-bibliography)
- IEEE

On save, the tool copies the selected CSL into the journal's template directory and removes any prior one. Re-render any open articles to apply the new style.

**To use a style not in the bundled list:**

1. Download the CSL from <https://github.com/citation-style-language/styles>.
2. Drop it into `content/journals/<slug>/template/`.
3. In Journal Settings, set the citation style to *Custom (managed by file in template/)*.
4. The renderer picks up whatever `.csl` is in the template directory.

The bundled set covers the most common cases in humanities and adjacent fields. To extend the bundled list, drop a new `.csl` into the repo's top-level `csl/` directory and add an entry to `BUNDLED_STYLES` in `citation_styles.py`.

## When to use which option

- **You're laying out an inherited manuscript with prose citations.** Stay with option A. Edit the Works Cited entries in place.
- **You're producing a new article and want indexer-friendly metadata.** Use option B. The author can hand you a `.bib` from their reference manager (Zotero, Mendeley, BibDesk, JabRef).
- **You want to switch styles mid-production.** Option B. With a CSL change, every article re-renders to the new style on the next Render click.

## What the lint pass checks

The citation-coverage check is a heuristic that extracts surname-shaped tokens from the body and from the Works Cited section, then reports mismatches. It's a weak heuristic by design (it can't tell a citation from a parenthetical aside). When you use the BibTeX path, the check is mostly skipped because Pandoc resolves citations directly.

Better, ultimately: the BibTeX system makes the lint check largely unnecessary — Pandoc itself errors on unresolved keys, and the auto-generated Works Cited can never drift from the in-text citations.
