# LiCS Editorial Style Guide

This file is the canonical editorial style for *Literacy in Composition Studies*. It is read by Graphion's "Stylize article (Claude)" button — Claude reads this guide and applies it to article manuscripts. Edit this file to change house style across all future stylize runs.

**Important to Claude**: preserve the author's content verbatim. Restructure formatting only. Never paraphrase, summarize, or invent. If something is ambiguous, prefer the convention in this guide over making up new structure.

## House typography (canonical LiCS print specification)

This is the **authoritative source of truth** for how LiCS articles look in print. Every editorial rule below — heading hierarchy, paragraph structure, block quote indentation, Works Cited rendering, footnote treatment — derives from this typography. When markdown structure choices are ambiguous, prefer the structure that maps cleanly to the typography table below.

Values are extracted from `Resources/Styles.xml` of a LiCS InDesign IDML export and implemented by the Typst template at `content/journals/lics/template/article.typ`.

| Element | Font | Size | Leading | Indent / spacing | InDesign paragraph style |
|---|---|---|---|---|---|
| Body | Minion Pro | 10pt | 15pt | 18pt (0.25") first-line indent, left-justified | *BodyText* / *Base* |
| Article title | Didot | 15pt centered | — | 18pt after | *ChapterTitle Nested* |
| Subtitle | Display italic | 12pt centered | — | — | (derived) |
| Author byline | Body italic | 10pt centered | — | em-dash separator between name and affiliation | (derived) |
| Section heading (H1 of body / `##`) | Didot | 13pt centered | — | 36pt before / 18pt after | *Article Sections* / *SubHead* |
| Subsection (H2 / `###`) | Display italic | 11pt centered | 12pt | (proportional) | *SubSection Heading* |
| Block quote | Body face | 10pt | 15pt | 36pt (0.5") left indent | *BlockQuote* |
| Nested block quote | Body face | 10pt | 15pt | 72pt (1") left indent | *block* |
| Pull quote | Minion Pro *Bold Cond Italic Caption* | 14pt | 14pt | left-justified, floated | *Pull Quotes* |
| Page numbers | Didot | 8pt | — | away-from-binding side | *PageNumbers* |
| Running header | Didot italic | 8pt | — | away-from-binding side | *RunningHeader* |
| Notes / endnotes | Body face | 10pt | 12pt | 18pt first-line indent | *Notes* |
| Works Cited | Body face | 10pt | 12pt | hanging indent 36pt (0.5") | *WorksCited* |
| Figure caption | Book Antiqua | 10pt Bold | — | indented paragraph | *caption* |
| Keywords / Abstract label | Display small-caps | 8pt | tracked 0.22em | centered | (derived) |

**Page geometry**: 6 × 9 inch trim. Margins: 0.85" top / 0.95" bottom / 0.75" left / 0.75" right.

**Font fallback policy**: Minion Pro and Didot are Adobe commercial faces; most installs don't have them. The Typst template uses fallback chains so any install renders something close:

- **Body**: `Minion Pro → EB Garamond → Garamond → Georgia`
- **Display**: `Didot → GFS Didot → Bodoni 72 → Bodoni → EB Garamond → Garamond`

EB Garamond ships with the Typst Python package and is always available. Installs with Adobe InDesign typically already have Minion Pro and Didot — those installs produce PDFs visually close to the hand-laid LiCS reference set.

**If LiCS changes its house typography** in a future redesign, this section is the canonical record. Update it first, then propagate to `article.typ` (PDF), `article.css` (HTML galley), and any other format-specific implementation files.

## Heading hierarchy

-   Section headings: `## H2` (e.g., `## Introduction`, `## Conclusion`)
-   Subsection headings: `### H3`
-   Sub-subsections: `#### H4` (rarely needed)
-   **Multi-line section headings**: when a long heading should break at a specific point (e.g., before a dependent clause or after a colon), use ` | ` (space, pipe, space) at each intended break point. The Lua filter converts every ` | ` token in a heading into a forced line break. Example: `## Facing What's Human: | From Dialogic Intertextuality | to Translingual Praxis` renders as three lines. Use sparingly; let the template wrap naturally unless the editor has a clear reason to override
-   Do not use H1 for body sections — that level is reserved for the title, which lives in YAML front matter (see "YAML front matter" section below for the schema per genre)
-   Works Cited heading is `### Works Cited` (H3 level — matches LiCS print convention). Rendered per the **canonical typography table** (Didot 13pt centered), NOT as italic flush-left
-   Notes / Endnotes heading is `### Notes` (same Didot centered treatment per the typography table)
-   Add a blank line above and below every heading

## Paragraph structure

-   One blank line between paragraphs
-   The first paragraph of the body renders with a multi-line drop cap (the originals use a 4–5 line cap). This is the template's job — no source markup. If the rendered output is missing the drop cap, that is a template/YAML problem, not a markdown source problem
-   The first paragraph is always flush left — no first-line indent. All subsequent paragraphs carry a standard first-line indent (handled by the template — no leading spaces in source)
-   No double-blank-lines (collapse to single)

## Works Cited

This is the most important section to fix because Word-style manuscripts commonly mangle it.

-   Each entry is its own paragraph, separated by a blank line
-   If you see entries running together (publisher of one entry followed by a comma and the surname of the next — e.g., `*Book.* U of Illinois P, Smith, Jane. ...`), SPLIT them into separate paragraphs and replace the comma with the closing punctuation of the first entry (period, or comma+year if year is known to be missing)
-   MLA 9 format (8th-ed updated)
-   Italicize book and journal titles with `*...*`
-   Article titles in straight `"..."` quotes (the template handles smart-quote rendering)
-   Page ranges with en-dash: `pp. 1–21` (use Unicode `–` or `–`, not double-hyphen)
-   DOIs as bare URLs in angle brackets: `<https://doi.org/10.21623/1.7.1.2>`
-   Each entry should be **detectable as a single sentence/period-terminated chunk** — that's how Pandoc splits paragraphs
-   **Hanging indent rendering**: the template renders each entry with a hanging indent (first line flush left, continuation lines indented). Do NOT add manual indentation in the source — write each entry as a flat paragraph
-   **Repeat-author marker for subsequent works by the same author**: LiCS house style uses `—-.` (Unicode em-dash followed by an ASCII hyphen and a period) at the start of the second and subsequent entries by the same author — not MLA's `---.` (three hyphens). Example:

```
Canagarajah, A. Suresh. *Translingual Practice: Global Englishes and Cosmopolitan Relations*. Routledge, 2012, <https://doi.org/10.4324/9780203073889>.

—-. "Weaving the Text: Changing Literacy Practices and Orientations." *College English*, vol. 82, no. 1, Sept. 2019, pp. 7–28, <https://doi.org/10.58680/ce201930302>.
```

-   **Entries with non-Latin scripts in the title**: see the "Non-Latin scripts" section below — keep the original-script title in place and provide an English gloss in `[brackets]` if the author provided one

## Tables

-   **Single-cell "rectangle" tables** (Word text boxes / callout boxes): convert to blockquote (`> content...`) — the template renders these as indented italic callouts
-   **Multi-cell data tables**: keep as Markdown tables. Prefer pipe tables (`| col | col |\n|---|---|`) for simple data; use grid tables (`+---+---+`) only when cells need multiple paragraphs
-   Strip any Microsoft Office HTML cruft (`<span style="mso-...">`) from cell content
-   Preserve column headers as the first row with a separator line below
-   Tables with 4+ columns are auto-rendered in landscape orientation by the template — no source markup needed
-   Tables with 2-3 columns are auto-shrunk to 8pt — no source markup needed

## Block quotes

-   Lines beginning with `> ` for the entire quote
-   Do not include surrounding quotation marks; the block quote treatment IS the marker
-   Multi-paragraph block quotes: blank line within, with each new paragraph also prefixed `>`
-   Block quote citation goes at the end of the last line: `> ... last sentence. (Author 42)`
-   **Nested block quotes**: when a quote contains another block quote (e.g., the author quotes someone who is quoting someone else), use Pandoc's nested-quote syntax — prefix lines of the inner quote with `> >` instead of `> `. The two indentation depths (36pt / 0.5" outer, 72pt / 1" inner) are documented in the canonical typography table at the top of this guide

## Epigraphs

An epigraph is a short quotation set off at the opening of an article (between the title block and the first body paragraph) or immediately under a section heading. It is rendered as an indented italic block with the attribution on the right, prefixed by two em-dashes.

-   Mark the epigraph as a standard `> ` block quote, with each line in italics via `*...*`
-   Attribution goes on its own line at the end of the block quote, prefixed by a double-dash `––`. The recommended form is two literal en-dashes (Unicode `––`); the template renders these as the long double-dash visible in print. Italicize the attribution
-   An epigraph sits between the section heading and the first body paragraph — leave a blank line above and below
-   Do NOT add a drop cap or any other treatment to the body paragraph that follows the epigraph; standard flush-left first paragraph applies

Example:

```
## Introduction

> *We shall know the truth and the truth will make us free.*
> *––East Bengal Language Committee Report*

The social function of literacy is a staple of conversation in writing studies. …
```

## Figures

Figures are images with one or two pieces of metadata: a bordered explanatory note (optional) and a caption paragraph. The pattern in LiCS print issues is consistent: the image appears flush against the body text margins; a bordered single-cell box containing an explanatory note may sit directly underneath the image; and a non-bordered caption paragraph ("Fig. N." or "Figure N:") follows the box. The caption is rendered per the canonical typography table — **bold indented paragraph in Book Antiqua 10pt** — NOT as a heading and NOT centered.

-   The image reference is a standard markdown image: `![alt text](path/to/image.png)`
-   An explanatory note that sits BELOW the image inside a border is encoded as a single-cell blockquote (`> ...`) immediately after the image, with no blank line between image and blockquote. The template renders the blockquote with a thin border below the image
-   The caption itself ("Fig. 1. ..." or "Figure 1: ...") is a regular paragraph on the line after the blockquote (or after the image, if there is no explanatory note). Preserve the author's caption style verbatim — some articles use `Fig. N.` and others use `Figure N:` and inconsistency between figures in the same article is permitted if that's what the author wrote
-   Do NOT manually number figures or "fix" inconsistencies in figure numbering style — the caption text is authored content
-   Body prose may reference figures by number (e.g., "as shown in Figure 1"); preserve these cross-references exactly

Example:

```
![Word clouds of frequent terms](figures/wordcloud-1.png)
> The left image represents the general corpus (n=257,001), and the right represents the reform sub-corpus (n=70,032). Words in the reform sub-corpus are color-coded for keyness as keywords.

Fig. 1. Word clouds of frequent terms in the state language debate.
```

## Non-Latin scripts

LiCS publishes scholarship that draws on languages written in non-Latin scripts (Bangla, Chinese, Arabic, Japanese, Cyrillic, Devanagari, etc.). These characters appear in body prose, block quotes, tables, footnotes, and Works Cited entries. Treat them uniformly.

-   Preserve the original-script characters as Unicode in the source, exactly as the author wrote them. Do NOT transliterate, romanize, or replace
-   Do NOT italicize the original-script characters. The template handles font fallback for non-Latin glyphs; italicizing them can confuse the font stack. (Italicize foreign-language *transliterations* if the author italicizes them — e.g., `*muhajirs*`, `*Volkgeist*` — but not the script itself)
-   If the author provides an English gloss in `[square brackets]` after a non-Latin title or phrase (common in Works Cited), preserve the brackets and the gloss verbatim. Italicize the gloss only if the original would have been italicized in English (e.g., a book title)
-   Footnotes may be entirely in a non-Latin script with no English translation — that is acceptable; preserve as-is
-   If non-Latin characters in the source appear as `???` or boxes, or look like garbled byte sequences, that indicates an encoding problem upstream (the docx was saved with the wrong encoding, or a copy-paste destroyed them). Do not try to "fix" by replacing with transliterations; flag for human review instead

Example:

```
This group—called *muhajirs* because they had immigrated to Pakistan…

Al-Helal, Bashir. ভাষা আন্দোলনের ইতিহাস [*History of the Language Movement*]. Agami Prokashoni, 2016.
```

## Inline formatting

-   *Italics* (`*...*`) for book and journal titles, foreign words, emphasis, named theoretical concepts
-   **Bold** (`**...**`) for section labels or key terms that aren't headings
-   "Curly quotes" — the template converts straight `"..."` to curly automatically
-   Use `–` (en-dash) for numerical ranges (pages, years): `1–21`, `2019–2024`
-   Use `—` (em-dash) for parenthetical breaks: `the practice — radical, queer, ongoing — continues`
-   Use `…` (Unicode ellipsis) instead of three dots `...`
-   Apostrophes: curly `'` not straight `'` (template converts)

## In-text citations

-   MLA author-page format: `(Smith 42)`, `(Lu and Horner 587)`
-   Multiple sources: `(Smith 42; Jones 87)` — semicolon-separated
-   Block quote citation: `(Author Page)` AFTER the closing period, on its own line if convenient
-   Quoted phrases with attribution: `"the practice continues" (Smith 42)`
-   **Short title for anonymous works or when the author is named in the prose**: `("Short Title" Page)` — for example, `("Report" 5)` when referring repeatedly to a single committee report whose author is institutional. Use straight quotes around the short title (template converts)
-   **Paragraph-number citation for unpaginated digital sources**: `(par 7)` or `(Author par 7)` instead of `(Author Page)`. Preserve author's capitalization (`par` vs `Par`)
-   **Two-em-dash epigraph attribution** (block quote opening a section): see Epigraphs section below

## Footnotes and endnotes

-   Use Pandoc footnote syntax: `[^1]` inline, `[^1]:` for the definition
-   Each `[^N]:` definition is its own paragraph (blank line before each)
-   Convert Pandoc Div-style footnotes (`::: {#footnote-N} ... :::`) to canonical `[^N]:` form
-   Footnote definitions go at the end of the article (Pandoc auto-renders them as endnotes; the LiCS template emits them as a "Notes" section)

## What to fix (common problems)

-   **Run-on Works Cited entries**: split into one entry per paragraph
-   **Broken tables**: collapsed onto one line, with blank lines between rows → repair to consecutive rows
-   **Word HTML cruft**: any `<span lang="..." style="mso-...">` survival should be stripped
-   **Stray pipe characters** in cell content (escaped `\|` or literal `|`) → remove
-   **Smart quote inconsistency**: normalize toward Unicode curly quotes
-   **Doubled spaces**: collapse to single
-   **Pandoc auto-generated heading IDs** (`{#section style="text-align: center;"}`): drop the inline attributes; let Pandoc auto-generate clean IDs
-   **Stray** `[?](#footnote-ref-N)` **back-arrows**: these are Pandoc HTML round-trip artifacts; remove them (Pandoc native footnotes generate back-arrows automatically)

## What to preserve

-   All citations, including parenthetical and block-quote attributions
-   All URLs and DOIs, exactly as given
-   Author voice and word choice — never paraphrase
-   Existing footnote markers and their content
-   Block quote contents verbatim (only fix the markup around them)
-   Image references (`![alt](path)`) exactly as written

## Pull-quotes

Articles sometimes feature pull-quotes: short, visually prominent excerpts from the body text, displayed as inset callouts. In LiCS print issues a pull-quote renders as a bold italic block in curly quotes, set in the LEFT column of a two-column carve-out, with body text wrapping around it on the right side of the page.

-   Mark pull-quotes with a Pandoc fenced div: `::: pullquote` on its own line, the quoted text on the next line(s), then `:::` on its own line to close
-   Pull-quote content is **a verbatim repetition of text already in the body** — it is a display callout, not new content. Do not invent pull-quote text and do not paraphrase
-   Place the `::: pullquote ... :::` block in the source roughly where it should appear visually (near the body sentence it duplicates). The template floats it to the left and wraps body around it
-   Do not include surrounding quotation marks in the source; the template adds the curly-quote treatment
-   Leave a blank line before and after the fenced div

Example:

```
Stillness is a major part of preferred gestural listening in schools, yet it too battles negative connotations of passiveness.

::: pullquote
Stillness is a major part of preferred gestural listening in schools, yet it too battles negative connotations of passiveness.
:::

In Watkins's writing about the development of scholarly "dispositions"…
```

## YAML front matter

The body markdown that Claude returns is wrapped with YAML front matter by the layout pipeline before being passed to the Typst template. Claude itself does NOT emit YAML (per "Output format" below), but the schema is documented here so that:

1.  Editors and the layout pipeline know which fields to populate per genre
2.  Claude can refuse to inline content that belongs in YAML (e.g., dumping a citation string into the body where the title block should be)
3.  Common rendering failures (see end of guide) can be diagnosed

The template is Typst, with the metadata flowing through a per-genre template function. Field names below are descriptive; the actual template may use slightly different keys — confirm with the template maintainer before changing.

**Per-genre fields**: see the schema block at the top of each "Genre: …" section below.

**Shared fields across all genres**:

-   `language`: defaults to `"en"`; set for non-English pieces

**Forced line breaks in `title` and `subtitle`**: long titles can be broken at specific points by inserting ` | ` (space, pipe, space) at each break. The Lua filter splits on these tokens and inserts forced line breaks. Example: `title: "Facing What's Human: | From Dialogic Intertextuality | to Translingual Praxis"` renders as three lines on the title page. Use only when a long title would wrap awkwardly in print; otherwise let the template wrap naturally.

The page header (`LiCS [issue] / [season year]`) and running header (article title or short title on inside pages) are generated by the layout tool downstream — these do NOT live in the article-level YAML and are not Claude's concern.

If a YAML field is missing, the template may render a placeholder rule, blank space, or default text in its place. The "Common rendering failures" section at the end lists the most frequent symptoms of missing or malformed YAML.

## Genre: Editors' Introduction

**YAML schema**:

```yaml
genre: editors_introduction
title: "Editors' Introduction to Issue 12.2"
# No author/byline fields — sign-off appears at end of body instead
```

**Body conventions**:

-   **No section headings.** The intro flows as one continuous sequence of paragraphs from opening to sign-off
-   **No Works Cited, no Notes section** — the intro does not cite externally in the formal sense; it references the issue's own pieces by author name and article title
-   **Article titles referenced inside the intro**: use straight `"..."` quotes around the article title (the template renders curly), and italicize special-issue titles or book titles with `*...*`
-   **Author names** on first reference: full name, sometimes with tribal or institutional affiliation in parentheses (e.g., `Jason Hockaday (Karuk)`). Preserve exactly as the editors wrote them
-   **Page citations to pieces in the same issue**: parenthetical `(48)` or `(50)` format, same as regular MLA — these refer to pages of the in-issue article being previewed
-   **Sign-off**: the final paragraph is the list of editor names, on its own line(s), prefixed with an em-dash `—` and italicized. Format as a single italicized line (or wrapped lines) starting with `—`. Example:

```
—*Alanna Frost, Brenda Glascott, Al Harahap, Brian Hendickson, Tara Lockhart, Juli Parrish, Katie Silvester, Lisa Termain, and Chris Warnick*
```

-   The sign-off is the LAST line of the document. Nothing follows it
-   Expected rendered visual: title in centered display small-caps; body opens with drop cap; signoff appears flush-right or slightly indented in italic

## Genre: Article

**YAML schema**:

```yaml
genre: article
title: "The Schooling of Gestural Listening"
author: "Laura Feibush"
affiliation: "Pennsylvania State University, Harrisburg"
keywords:
  - listening
  - gesture
  - literacy
  - embodiment
  - neurodivergence
  - pedagogy
# Optional fields:
# doi: "https://doi.org/..."
# acknowledgments: "..."
```

**Body conventions**:

-   **No** `**KEYWORDS**` **line in the body.** Keywords belong in YAML (see schema above). The template renders KEYWORDS as a centered small-caps display label with the keyword list centered below. Writing a literal `**KEYWORDS**` markdown line inline causes the template to render flush-left bold text instead of the proper display block
-   **Section headings**: use `## H2` as documented above. The template renders these in centered small-caps display style; do NOT write them in ALL CAPS in source — use normal title case and let the template style them (e.g., `## A Litany for Gestural Listening`, not `## A LITANY FOR GESTURAL LISTENING`). For long headings with intended line breaks, see "Heading hierarchy"
-   **Subsection headings**: `### H3`, rarely needed
-   **Italicized inline "leads"**: some articles use an italicized phrase or sentence at the start of a paragraph as a rhetorical lead-in (e.g., Feibush's litany petitions: *Gestural listening captures listening's dual material and metaphorical qualities.*). These are inline italics, NOT headings — keep them as `*...*` emphasis within the paragraph, with the paragraph continuing in roman immediately after
-   **Epigraphs**: see the Epigraphs section. Articles may open with an epigraph between the title block and the first body paragraph, or open a section with an epigraph between the heading and the first paragraph
-   **Pull-quotes**: see the Pull-quotes section
-   **Figures**: see the Figures section. Articles commonly include figures (charts, network graphs, photos) with bordered explanatory notes and captions
-   **Non-Latin scripts**: see the Non-Latin scripts section. Articles drawing on multilingual scholarship may include original-script characters in body prose, block quotes, footnotes, and Works Cited
-   **Block quote scene-setting**: articles sometimes open a section with an italicized narrative scene (e.g., a film description) set as a block quote. Mark as a standard `> ` block quote, with the entire scene italicized via `*...*` inside the block quote. The template renders this as indented italic
-   **Notes section**: numbered footnotes using `[^1]` syntax, definitions at end of document. The template auto-titles the rendered section "NOTES". Note bodies may be entirely in a non-Latin script with no English gloss; preserve as-is
-   **Works Cited**: standard `### Works Cited` heading at the very end of the document (after Notes, if present), one entry per paragraph, MLA 9 format. See the Works Cited section for hanging-indent rendering and the `—-.` repeat-author marker
-   **Anonymized student sources**: when an article cites student writing under a pseudonym, the Works Cited entry uses the pseudonym in brackets after `Anonymous student A`, e.g., `Anonymous student A (Dylan). "The Spazzy Kid."` — preserve exactly as the author wrote it

**Expected rendered visual**: title in centered display serif (large, may be small-caps or mixed-case caps-and-lowercase depending on author preference and template); byline directly under, smaller display serif with em-dash separator between name and affiliation; KEYWORDS label in centered small-caps display; keyword list centered below; centered drop cap on first body paragraph (first paragraph is flush-left, no first-line indent); section headings in centered small-caps display. The byline and title should be visually close in size — the title slightly larger, but not a dramatic step.

## Genre: Book Review

**YAML schema**:

```yaml
genre: book_review
title: "All Are Connected: From Traditional Chinese Medicine to Students' Literacy Practices"
reviewed_work: "Doing Difference Differently: Chinese International Students' Literacy Practices and Affordances"
reviewed_author: "Zhaozhe Wang"
reviewer: "Carina Jiaxing Shi"
affiliation: "University of Maryland, College Park"
```

The template uses these four fields to build the three-line title block:

1.  `title` → reviewer's essay-style title (display serif, centered)
2.  `Review of *{reviewed_work}* by {reviewed_author}` → italic display line, centered
3.  `{reviewer} — {affiliation}` → display serif byline, centered, em-dash separator

**CRITICAL**: do NOT put a Works Cited entry into the `title` field. The corrupted-title symptom (full citation string as the document title) means the YAML attacher took the Works Cited entry for the book under review and pasted it as `title`. The `title` field is the *reviewer's* essay-style title, NOT the bibliographic entry for the book.

**Body conventions**:

-   **No internal section headings.** Book reviews run as continuous prose from opening to close. Do not insert `## H2` headings
-   **Drop cap** on the first body paragraph is expected (template responsibility; see "Common rendering failures" below if missing)
-   **Non-Latin scripts**: see the "Non-Latin scripts" section above. Book reviews of non-Western scholarship frequently include original-script terms; the rules are the same as for articles
-   **In-text page citations to the book under review**: bare `(23)`, `(166)`, etc. — no author name needed since the book is the implicit referent. Citations to OTHER works use standard MLA `(Author Page)`
-   **Works Cited**: standard `### Works Cited` heading at the end. The book under review is itself one of the entries
-   **No Notes section** is typical, though footnotes are permitted if the reviewer used them — handle with the same `[^N]` syntax as articles

**Expected rendered visual**: three-line title block (essay title / "Review of [italic book title] by [author]" / reviewer + affiliation), all centered, all in display serif at similar sizes (the essay title slightly larger; may be small-caps or mixed case depending on template settings). Drop cap on flush-left first body paragraph. Works Cited heading in centered display small-caps.

## Common rendering failures

This section catalogs symptoms seen in past Typst renders and the YAML/markdown fix for each. If you (Claude or a human editor) see the symptom in a proof PDF, the fix is in the second column.

| Symptom in rendered PDF                                                                                                                                            | Likely cause                                                                                                                                                                   | Fix                                                                                                                                        |
|--------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------------------------------------------------|
| Title is a long Works Cited–style citation string (e.g., "Luibhéid, Eithne. *Abolitionist Intimacies*…Duke UP, 2025.") instead of the reviewer's essay-style title | The YAML `title` field was populated with the Works Cited entry for the book under review                                                                                      | Move that string to `reviewed_work` / `reviewed_author`; put the reviewer's essay title in `title`                                         |
| Two stray horizontal rules between byline and KEYWORDS / body                                                                                                      | Template inserted separators where it expected YAML fields (e.g., `affiliation`, `doi`) that were empty                                                                        | Either fill the missing YAML fields, or have the template author suppress the separator when the field is empty                            |
| KEYWORDS label is flush-left in plain bold instead of centered small-caps display                                                                                  | Body contains a literal `**KEYWORDS**` markdown line                                                                                                                           | Remove from body; populate YAML `keywords` array; let the template render the label and list                                               |
| First body paragraph has no drop cap                                                                                                                               | Template not applying its drop-cap show rule, OR the first block of the body isn't being recognized as a paragraph (e.g., a stray YAML attribute or comment is in front of it) | Confirm template has drop-cap rule active for the genre; confirm first body block is a plain paragraph                                     |
| First body paragraph has a first-line indent (it should be flush left)                                                                                             | Template's first-paragraph indent suppression rule not firing                                                                                                                  | Template fix; not a markdown source fix                                                                                                    |
| Works Cited heading rendered as italic flush-left "*Works Cited*" instead of centered display small-caps                                                           | Template H3 styling doesn't match the LiCS print convention                                                                                                                    | Template fix; the markdown source `### Works Cited` is correct                                                                             |
| Title and byline have wildly different sizes (huge justified title block, tiny italic byline)                                                                      | Almost always a sign that `title` got an oversized string dumped into it (see first row)                                                                                       | Fix the `title` field; the size disparity will resolve                                                                                     |
| Em-dash in byline rendered as hyphen or en-dash                                                                                                                    | YAML field probably used `-` or `--`; or the template join character is wrong                                                                                                  | Use a literal Unicode em-dash `—` in the YAML byline join, or have the template format `{reviewer} — {affiliation}` with a Unicode em-dash |
| Repeat-author marker in Works Cited renders as plain `---` (three hyphens) or `—.` (one em-dash + period) instead of `—-.` (em-dash + hyphen + period)             | Source used MLA-standard `---.` instead of LiCS house style `—-.`                                                                                                              | Replace `---.` with `—-.` at the start of repeat-author entries                                                                            |
| Non-Latin characters (Bangla, Chinese, Arabic, etc.) render as boxes (tofu) or in a fallback font that clashes with the body serif                                 | Template font stack doesn't include script-appropriate fallback                                                                                                                | Template fix; preserve the Unicode characters in source either way                                                                         |
| Non-Latin characters appear as `???` or garbled byte sequences                                                                                                     | Encoding problem upstream of the markdown source (docx saved in wrong encoding, broken copy-paste)                                                                             | Flag for human review; do not silently transliterate or substitute                                                                         |
| Pull-quote `::: pullquote ... :::` block renders as plain body text or as a block quote                                                                            | Typst show rule for the `pullquote` class isn't defined in the template                                                                                                        | Template fix; markdown source is correct                                                                                                   |
| Figure caption renders as a heading or centered display element instead of a normal indented paragraph                                                             | Source used `## Fig. 1.` or `### Figure 1:` (as a heading) when it should be a regular paragraph                                                                               | Convert the caption to a plain paragraph; never use heading syntax for "Fig. N." captions                                                  |
| Boxed explanatory note under a figure renders as plain paragraph (no border)                                                                                       | The note was placed with a blank line between image and note, or wasn't marked as a blockquote                                                                                 | Remove the blank line between the image and the `> ` blockquote that contains the note                                                     |
| Epigraph attribution shows as `--Author` (two ASCII hyphens) instead of `––Author` (two en-dashes)                                                                 | Source kept ASCII double-hyphens; template didn't convert                                                                                                                      | Replace `--` with literal `––` (two Unicode en-dashes) in the epigraph attribution line                                                    |
| Section heading wraps awkwardly mid-phrase across pages or columns instead of breaking at intended points                                                          | Source heading is a single long line with no encoded breaks                                                                                                                    | Encode intended line breaks in the H2 with two trailing spaces at each break point (see "Heading hierarchy")                               |

## Output format

Return ONLY the rewritten Markdown body. No YAML front matter (it's stripped before this prompt and re-attached after). No code fences. No "Here is the rewritten article" preamble. No closing remarks. Just the Markdown.
