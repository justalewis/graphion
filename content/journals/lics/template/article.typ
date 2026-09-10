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
//
// Minion Pro is the LiCS InDesign body face, but it is deliberately NOT in
// this stack. Typst matches a family by name and then takes the closest style
// it can find inside it, so a machine carrying a single stray Minion Pro file
// (a lone MinionPro-BoldCnIt.otf, say, dropped in by an Adobe installer)
// renders the entire galley in bold condensed italic, silently. Galleys have
// to be reproducible across whatever fonts an editor happens to have, and the
// production container ships EB Garamond, so that leads instead.
//
// Debian registers the family as "EB Garamond 12"; both spellings are listed
// because without the second the container falls through to Libertinus Serif.
#let body-font = ("EB Garamond", "EB Garamond 12", "Garamond", "Georgia")
// Display type: 13-15pt Didot per LiCS InDesign spec. Same logic —
// fall back through GFS Didot (free), Bodoni (similar high-contrast
// modern), then EB Garamond as a last resort.
#let display-font = ("Didot", "GFS Didot", "Bodoni 72", "Bodoni", "EB Garamond", "EB Garamond 12", "Garamond")

#let short-title-val = "$short-title$"
#let short-authors-val = "$short-authors$"
#let footer-val = "$footer$"
#let start-page-val = $if(start-page)$$start-page$$else$1$endif$

// Article "kind" comes through from the YAML front matter. The template
// treats "review" (book reviews) specially: no forced page break after
// the front matter, and no running header on the first page (which is
// also the opening body page, so the design's usual "front matter is
// clean" rule loses its anchor). Any other value, including the default
// "article", takes the classical page-per-front-matter layout.
#let is-review-val = "$if(kind)$$kind$$endif$" == "review"

// `body-started` gates the running header and footer. The header/footer
// live on the initial `#set page` at the top (a second mid-document
// `#set page` triggers an implicit page break in Typst, which was why
// book reviews with no abstract still landed a mostly-empty page 1),
// so a flag is needed to keep them invisible while the front matter is
// laid out. The flag flips right after the abstract's if-block, i.e.,
// after any explicit pagebreak but before the `$body$` substitution.
#let body-started = state("body-started", false)

// Running-head inputs. `journal-short` is not stored in the article's
// YAML; conversion.render_pdf passes it at render time from the journals
// row (short_name, else an initialism of the full name), so the stored
// article.md stays untouched.
#let journal-short-val = "$journal-short$"
#let volume-val = "$volume$"
#let issue-val = "$issue$"
#let title-content = [$if(title)$$title$$endif$]

// Verso carries the journal locator, e.g. "LiCS / Vol. 13 / No. 2".
// Missing pieces drop out rather than leaving a dangling separator, so a
// journal with no issue number still gets a clean header.
#let verso-label = {
  let parts = ()
  if journal-short-val != "" { parts.push(journal-short-val) }
  if volume-val != "" { parts.push("Vol. " + volume-val) }
  if issue-val != "" { parts.push("No. " + issue-val) }
  parts.join("  /  ")
}

// Recto carries the article. Short title is preferred because a full
// scholarly title overruns the 4.5in measure and wraps into the margin;
// the full title is only a fallback for articles that never set one.
#let recto-label = if short-title-val != "" { [#short-title-val] } else { title-content }

// A scene break is a centered asterisk: that is what the manuscript carries
// and what the author meant. It was rendering as a rule across the measure,
// which reads as a section divider rather than the pause it stands for.
#let scene-break = {
  v(0.9em)
  align(center, text(size: 11pt, fill: ink-soft, "*"))
  v(0.9em)
}

// Pandoc names this differently by version, and both have to be covered.
// Older writers emit the value `#horizontalrule`, expecting the template to
// define it. Pandoc 3.11 emits a call to `#divider()`, which is a Typst
// built-in that draws a full-width line, so leaving it alone silently
// reinstated exactly the rule we were trying to replace.
#let horizontalrule = scene-break
#let divider() = scene-break

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

// Running header and footer are declared here rather than after the
// abstract, because Typst treats any mid-document `#set page(...)` that
// changes page furniture as an implicit page break: on book reviews
// (no abstract, no explicit break) that implicit break was leaving a
// mostly-empty page 1 with the body pushed to page 2. Both callbacks
// query the `body-started` state so the front matter still renders
// without header or folio.
#set page(
  paper: "us-letter",
  width: 6in,
  height: 9in,
  margin: (top: 0.85in, bottom: 0.95in, left: 0.75in, right: 0.75in),
  header: context {
    let started = body-started.at(here())
    let p = counter(page).at(here()).first()
    if not started {
      none
    } else if is-review-val and p == 1 {
      // Reviews start the body on page 1 alongside the title block;
      // a running header on that page would sit above the title.
      none
    } else if calc.even(p) {
      align(left, text(
        style: "italic", size: 8pt, fill: ink-soft, font: display-font,
        verso-label,
      ))
    } else {
      align(right, text(
        style: "italic", size: 8pt, fill: ink-soft, font: display-font,
        recto-label,
      ))
    }
  },
  footer: context {
    let started = body-started.at(here())
    // Reviews carry the folio from page 1 because that page holds body
    // content already; articles hold their folios back until the body
    // starts (title / abstract pages stay clean).
    if not started and not is-review-val {
      none
    } else {
      let p = counter(page).at(here()).first()
      let styled(s) = text(size: 8pt, fill: ink-soft, font: display-font, s)
      let folio = styled(str(p))
      if calc.even(p) {
        align(left, if footer-val != "" { folio + styled("  ·  " + footer-val) } else { folio })
      } else {
        align(right, if footer-val != "" { styled(footer-val + "  ·  ") + folio } else { folio })
      }
    }
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
// `breakable: false` keeps a two-line heading from splitting across a
// page boundary; `sticky: true` keeps the heading attached to the text
// that follows so it cannot strand alone at the foot of a page. Both are
// needed: without the first, a long heading breaks mid-phrase across the
// spread; without the second, it sits orphaned above a page break.
#show heading.where(level: 1): it => block(
  breakable: false, sticky: true, width: 100%,
  // One body line of space above and below. The spacing lives on the block
  // rather than in v() calls inside it so a two-line title cannot pick up a
  // gap in its middle; `leading` keeps its own lines set close together.
  above: 1.5em, below: 1.5em,
  {
    set par(first-line-indent: 0pt, leading: 0.35em, justify: false)
    align(center, text(
      font: display-font,
      size: 13pt,
      weight: 400,
      it.body,
    ))
  },
)

// Section-h2: italic, centered, slightly smaller — matches LiCS
// "SubSection Heading" (11pt) treatment.
#show heading.where(level: 2): it => block(
  breakable: false, sticky: true, width: 100%,
  above: 1.5em, below: 1.5em,
  {
    set par(first-line-indent: 0pt, leading: 0.35em, justify: false)
    align(center, text(
      font: display-font,
      size: 11pt,
      style: "italic",
      weight: 400,
      it.body,
    ))
  },
)

// Section-h3: italic, left-aligned, body-size — for finer subdivisions
// not present in LiCS print but useful for articles that need them.
#show heading.where(level: 3): it => block(
  breakable: false, sticky: true, width: 100%,
  above: 1.2em, below: 0.6em,
  {
    set par(first-line-indent: 0pt, leading: 0.35em, justify: false)
    text(size: 10pt, style: "italic", weight: 400, fill: ink-soft, it.body)
  },
)

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

// Figures. The image sits centered with its caption below, separated by a
// hairline rule, and the whole block is kept off a page break so an image can
// never part from its caption.
//
// Typst's own figure numbering is switched off: figures-filter.lua has already
// numbered them in document order and prefixed the caption with "FIGURE N.",
// so leaving Typst's on would render "Figure 1: FIGURE 1. ...".
#set figure(supplement: none, numbering: none, gap: 0pt)
#show figure: it => block(breakable: false, width: 100%, {
  set par(first-line-indent: 0pt, justify: false)
  v(1em)
  align(center, it.body)
  v(0.6em)
  line(length: 100%, stroke: 0.5pt + rule-color)
  v(0.5em)
  set par(justify: true)
  text(size: 9pt, fill: ink-soft, it.caption)
  v(1.1em)
})

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

// The body opens on its own page. The abstract frequently runs past the
// bottom of the title page, so keeping them together left the opening
// section starting partway down whichever page the abstract happened to
// end on. This pagebreak is inside the abstract branch: pieces with no
// abstract (book reviews, notes, short forewords) flow the body directly
// under the title block instead of leaving the rest of page 1 blank.
#pagebreak()
$endif$

// Body starts here. Flip `body-started` so the header/footer set up
// on the initial `#set page` at the top of this file begin rendering.
// The page counter is not reset: it keeps running through the front
// matter, so folios still line up with what issue assembly recorded
// for this article.
#body-started.update(true)

// ---------- Body ----------

$body$
