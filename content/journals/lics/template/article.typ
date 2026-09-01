// LiCS Pandoc Typst template (classical typography, 6 x 9 book trim).
//
// Mirrors the standalone HTML design: EB Garamond, cream paper feel
// (but white print), small-caps centered section heads with a hairline
// rule above, justified body with first-line indent, italic running
// headers (verso = short-authors, recto = short-title), centered page
// counter in the footer, first-page suppression of both, and a drop cap
// on the first paragraph of the opening section.
//
// The drop cap is injected by the journal's Lua filter (typst output
// path only); it wraps the first character of the first body paragraph
// in `#dropcap[X]`. The helper below implements the visual treatment.

#let ink = rgb("#1a1612")
#let ink-soft = rgb("#4a4137")
#let rule-color = rgb("#b6a98c")

// Font stacks — defined early so page header/footer can reference them.
// Body type: 10pt Minion Pro per LiCS InDesign spec. Fallback chain
// favors free fonts since Minion Pro is Adobe-commercial and most
// installs won't have it; EB Garamond is a close visual match
// (humanist serif, similar x-height). Debian's fonts-ebgaramond
// registers the family as "EB Garamond 12", so both spellings are
// listed: without the second one the container silently falls back
// to Libertinus Serif and the galley is in the wrong face.
#let body-font = ("Minion Pro", "EB Garamond", "EB Garamond 12", "Garamond", "Georgia")
// Display type: 13-15pt Didot per LiCS InDesign spec. Same logic —
// fall back through GFS Didot (free), Bodoni (similar high-contrast
// modern), then EB Garamond as a last resort.
#let display-font = ("Didot", "GFS Didot", "Bodoni 72", "Bodoni", "EB Garamond", "EB Garamond 12", "Garamond")

#let short-title-val = "$short-title$"
#let short-authors-val = "$short-authors$"
#let footer-val = "$footer$"
#let start-page-val = $if(start-page)$$start-page$$else$1$endif$

// Pandoc's Typst writer emits `#horizontalrule` for Markdown `---`
// thematic-break separators, expecting the template to define it.
// We give it the same hairline centered look as the front-matter
// separator between metadata and body — visually appropriate for an
// inline section break in scholarly prose.
#let horizontalrule = {
  v(0.8em)
  align(center, line(length: 35%, stroke: 0.5pt + rule-color))
  v(0.8em)
}

// Drop cap helper. Typst doesn't natively wrap body text around a
// floated initial (no shape-aware reflow), so this approximates the
// classical scholarly-book opening: an enlarged first letter set
// across two lines, with the rest of the line tucked neatly to its
// right. Smaller than the previous version (2.4em vs 3.6em) and with
// a tighter baseline to prevent overlap with the line above.
#let dropcap(letter) = box(
  baseline: 0.5em,
  text(
    size: 2.4em,
    weight: 500,
    font: ("EB Garamond", "Garamond", "Georgia"),
    [#letter],
  ),
) + h(0.1em)

// Title uses Typst content syntax ([...]) so quoted titles like
// `"Facing the World" through Translingual...` don't blow up the Typst
// parser. Author and keywords have to be string arrays per Typst's
// document spec; we leave sentinels here and substitute them from
// Python after Pandoc emits the file, with proper backslash-escaping
// for embedded quotes.
#set document(
  $if(title)$title: [$title$],$endif$
  author: (GRAPHION_AUTHORS_PLACEHOLDER),
  keywords: (GRAPHION_KEYWORDS_PLACEHOLDER),
)

#set page(
  paper: "us-letter",
  width: 6in,
  height: 9in,
  margin: (top: 0.85in, bottom: 0.95in, left: 0.75in, right: 0.75in),
  header: context {
    let p = counter(page).at(here()).first()
    if p == start-page-val { return [] }
    if calc.even(p) {
      align(left, text(style: "italic", size: 8pt, fill: ink-soft, font: display-font, short-authors-val))
    } else {
      align(right, text(style: "italic", size: 8pt, fill: ink-soft, font: display-font, short-title-val))
    }
  },
  footer: context {
    let p = counter(page).at(here()).first()
    if p == start-page-val { return [] }
    let page-str = str(p)
    let label = if footer-val != "" { footer-val + "  ·  " + page-str } else { page-str }
    align(center, text(size: 8pt, fill: ink-soft, font: display-font, label))
  },
)

// Shift the page counter so the first page is labeled `start-page-val`.
#counter(page).update(start-page-val)

#set text(
  font: body-font,
  size: 10pt,
  fill: ink,
  lang: "en",
  features: ("kern", "liga", "onum"),
)
// Leading 15pt at 10pt body = 1.5x leading per LiCS InDesign
// (Properties → Leading = 15 on BodyText). Typst's `leading` is
// inter-line space (i.e., extra gap between lines), so 15pt - 10pt
// = 5pt extra, which is 0.5em.
#set par(
  justify: true,
  leading: 0.5em,
  first-line-indent: 18pt,
  linebreaks: "optimized",
)
// Disable word-level hyphenation across the document. Long words flow to
// the end of the line and break only at natural boundaries; justified
// lines may therefore have wider word spacing on some lines, which is
// the intended trade-off.
#set text(hyphenate: false)

// Section-h1: centered Didot 13pt — matches LiCS InDesign's "SubHead"
// / "Article Sections" paragraph style. Centered, no hairline rule
// (rule was a Graphion approximation; LiCS print doesn't use one).
// Spacing comes from "SubSection Heading" measurements: 36pt before,
// 18pt after, which at 10pt body is 3.6em / 1.8em.
#show heading.where(level: 1): it => {
  set par(first-line-indent: 0pt)
  v(1.8em)
  align(center, text(
    font: display-font,
    size: 13pt,
    weight: 400,
    it.body,
  ))
  v(0.9em)
}

// Section-h2: italic, centered, slightly smaller — matches LiCS
// "SubSection Heading" (11pt) treatment.
#show heading.where(level: 2): it => {
  set par(first-line-indent: 0pt)
  v(1.2em)
  align(center, text(
    font: display-font,
    size: 11pt,
    style: "italic",
    weight: 400,
    it.body,
  ))
  v(0.6em)
}

// Section-h3: italic, left-aligned, body-size — for finer subdivisions
// not present in LiCS print but useful for articles that need them.
#show heading.where(level: 3): it => {
  set par(first-line-indent: 0pt)
  v(0.8em)
  text(size: 10pt, style: "italic", weight: 400, fill: ink-soft, it.body)
  v(0.3em)
}

// First paragraph after a heading: no indent
#show heading: it => {
  it
  set par(first-line-indent: 0pt)
}

// Blockquotes: 36pt (0.5") left indent per LiCS InDesign "BlockQuote"
// paragraph style. Same point size as body (10pt), no border or italic
// — the indent itself is the visual marker.
#show quote.where(block: true): it => {
  set par(first-line-indent: 0pt, leading: 0.5em)
  v(0.6em)
  pad(left: 36pt, right: 18pt, text(size: 10pt, it.body))
  v(0.6em)
}

// Tables. Classical book treatment:
//   - Hairline rule above and below the entire table (1pt, ink color).
//   - No vertical borders (x: 0pt) — keeps the page airy.
//   - Light horizontal grid line between rows (0.5pt, rule color).
//   - Cells get reasonable padding so columns aren't cramped.
// Single-cell tables (the "rectangle" / callout-box shape that DOCX
// emits for text boxes) get just the top and bottom rules with no
// internal grid, so they read as a clean horizontal band rather than
// floating text. Multi-cell rectangles ("Canvas Discuss" boxes etc.)
// likewise get a top + bottom rule.
#set table(
  inset: 8pt,
  stroke: (
    top:    1pt   + ink,
    bottom: 1pt   + ink,
    left:   0pt,
    right:  0pt,
    x:      0pt,
    y:      0.5pt + rule-color,
  ),
)
#show table: it => {
  set text(size: 9.5pt)
  set par(first-line-indent: 0pt, leading: 0.55em, justify: false)
  v(0.4em)
  it
  v(0.4em)
}

// Links: subtle, ink color (no underline noise in print)
#show link: it => text(fill: rgb("#5a3a1f"), it)

// ---------- Title page ----------

// Title block matches LiCS InDesign "ChapterTitle Nested" paragraph
// style: Didot 15pt centered with 18pt space after. Subtitle is set
// in matching display face at 12pt italic. Author byline uses 10pt
// italic (body face) — short, readable, doesn't compete with title.
#align(center, {
  set par(first-line-indent: 0pt)
  v(0.4in)
  text(font: display-font, size: 15pt, weight: 400, [$title$])
  $if(subtitle)$
  v(0.4em)
  text(font: display-font, size: 12pt, style: "italic", fill: ink-soft, [$subtitle$])
  $endif$
  v(1em)
  $for(author)$
  text(style: "italic", size: 10pt, fill: ink-soft, [$author.name$$if(author.affiliation)$ \u{2014} $author.affiliation$$endif$])
  linebreak()
  $endfor$
  v(0.6em)
  line(length: 40%, stroke: 0.5pt + rule-color)
  v(0.6em)
})

// Labels use `upper()` rather than `smallcaps()` because Didot fonts
// (the display-font stack) don't ship OpenType small-caps glyphs.
// Typst's synthesized small-caps at 8pt with wide tracking renders as
// near-illegible dots; full-size caps at 8.5pt with slightly tighter
// tracking gives the same "label" feel and prints cleanly.
$if(keywords)$
#align(center, block(width: 80%, {
  set par(first-line-indent: 0pt)
  text(font: display-font, size: 8.5pt, tracking: 0.2em, fill: ink-soft, upper("Keywords"))
  v(0.3em)
  text(style: "italic", size: 9pt, fill: ink-soft, [$for(keywords)$$keywords$$sep$; $endfor$])
}))
#v(0.6em)
$endif$

$if(abstract)$
#align(center, block(width: 85%, {
  set par(first-line-indent: 0pt, justify: true, leading: 0.5em)
  text(font: display-font, size: 8.5pt, tracking: 0.2em, fill: ink-soft, upper("Abstract"))
  v(0.4em)
  text(size: 9.75pt, [$abstract$])
}))
#v(1em)
$endif$

// Horizontal rule between front matter (title, authors, keywords,
// abstract) and the article body. Matches the LiCS print layout:
// the body starts on the same page as the metadata, separated only
// by a hairline rule. We do NOT pagebreak here — that would push the
// body to page 2 unnecessarily and break the journal's expected
// "opening rule + drop cap + body" visual pattern.
#v(0.8em)
#align(center, line(length: 40%, stroke: 0.5pt + rule-color))
#v(1.2em)

// ---------- Body ----------

$body$
