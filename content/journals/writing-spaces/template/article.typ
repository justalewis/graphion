// Writing Spaces Pandoc Typst template (6 x 9 trade book trim).
//
// Geometry is measured off the published series PDFs rather than guessed
// (Writing Spaces 5, chapter 1, as distributed by the WAC Clearinghouse):
//
//   page        432 x 648pt (6 x 9in)
//   text block  x 58.5 to 376.3pt, so 58.5pt left and 55.7pt right
//   body        11pt on a 13.2pt baseline, justified, hyphenated
//   indent      14.4pt first line, no space between paragraphs
//   drop cap    3 lines, opening the first body paragraph
//   heads       12pt small caps, centred
//   title       chapter number hanging at 76.5pt, title small caps at 90pt
//   overview    centred head, full-measure text, then a 142pt centred rule
//   running     verso: folio then short authors; recto: short title then folio
//   margin tab  the volume label, rotated, in the outer margin
//
// Adobe Garamond Pro and Minion Pro set the printed series. Neither ships
// here, so both stacks lead with free faces chosen to sit close and fall
// through to what the production container actually carries. A stack that
// names a licensed face it may not find is how a galley silently comes out
// in the wrong style, so nothing here names Minion or AGaramond.

#import "@preview/droplet:0.3.1": dropcap as droplet-dropcap

#let ink = rgb("#111111")
#let ink-soft = rgb("#5c5c5c")
#let rule-color = rgb("#8d8d8d")

// EB Garamond stands in for Adobe Garamond: same humanist Garamond model,
// old-style figures, and the production container already ships it.
#let body-font = ("EB Garamond", "EB Garamond 12", "Garamond", "Georgia")

// The display stack carries every small-capped line: the chapter title and
// all four kinds of head. That constrains it more than taste does.
//
// Typst does not synthesize small caps. It substitutes real `smcp` glyphs or
// it silently leaves the words in upper and lower case, with no warning and
// no visible error, so a face without the table does not approximate this
// design, it loses it. Confirmed by rendering on this machine: Georgia,
// Cambria, Constantia and Palatino Linotype carry small caps; the "Garamond"
// Windows ships (Monotype's) does not, and it is early in the body stack.
//
// So the display stack leads with EB Garamond, which carries small caps and
// is what the container has, and every fallback behind it is a face checked
// to carry them. Source Serif would be the closer stand-in for the series'
// Minion, being another Slimbach humanist, but its small-caps coverage is
// not guaranteed across releases, and small caps matter more here than the
// precise shape of the display face.
#let display-font = (
  "EB Garamond", "EB Garamond 12", "Constantia", "Cambria",
  "Georgia", "Palatino Linotype",
)

// Filled in from Python with proper escaping (conversion._fill_typst_authors),
// because a value carrying a quotation mark ends the string literal early and
// fails the whole render.
#let short-title-val = GRAPHION_SHORT_TITLE_STRING
#let short-authors-val = GRAPHION_SHORT_AUTHORS_STRING
#let footer-val = GRAPHION_FOOTER_STRING

#let start-page-val = $if(start-page)$$start-page$$else$1$endif$
// Author proofs go out before pagination is settled; assembly clears the flag.
#let hide-folios = $if(hide-page-numbers)$true$else$false$endif$
#let folio-style = "$if(page-numbering)$$page-numbering$$else$1$endif$"

// Book-series fields. A journal article has a volume and an issue; a Writing
// Spaces chapter has a volume title and a chapter number, and the front
// matter schema in this bundle carries both.
#let has-chapter-number = $if(chapter-number)$true$else$false$endif$
#let chapter-number-content = [$if(chapter-number)$$chapter-number$$endif$]
#let has-volume-label = $if(volume-title)$true$else$false$endif$
#let volume-label-content = [$if(volume-title)$$volume-title$$endif$]

#let title-content = [$if(title)$$title$$endif$]
#let recto-label = if short-title-val != "" { [#short-title-val] } else { title-content }
#let verso-label = if short-authors-val != "" { [#short-authors-val] } else { [] }

// Gates the running head, the folio and the margin tab, so the chapter's
// opening page stays clean while the rest of the chapter carries furniture.
// The header callbacks live on the initial `#set page` because a second
// mid-document `#set page` that changes furniture forces a page break.
//
// Do not write that state's name in a comment: Pandoc's template engine does
// not know Typst comment syntax and expands the token wherever it appears.
#let body-started = state("body-started", false)

// A scene break is a centred asterisk, not a rule across the measure.
#let scene-break = {
  v(0.8em)
  align(center, text(size: 11pt, fill: ink-soft, "*"))
  v(0.8em)
}
#let horizontalrule = scene-break
#let divider() = scene-break

// The filter hands over the whole opening paragraph; droplet sets its first
// letter large and flows the rest beside it.
//
// The height is given as a length rather than a line count. Asked for three
// lines, droplet scales the glyph so its bounds fill three whole line boxes,
// which at a 13.2pt baseline is a 57pt cap: noticeably heavier than the
// series sets. The printed cap is 50.8pt type, so its inked height is about
// 35.6pt, which spans 2.7 baselines and therefore still clears three lines of
// text, exactly as the printed page does.
#let dropcap(body) = droplet-dropcap(
  height: 35.6pt,
  gap: 2pt,
  font: body-font,
  body,
)

#set document(
  $if(title)$title: [$title$],$endif$
  author: (GRAPHION_AUTHORS_PLACEHOLDER),
  keywords: (GRAPHION_KEYWORDS_PLACEHOLDER),
)

#set page(
  width: 6in,
  height: 9in,
  margin: (top: 56.5pt, bottom: 63pt, left: 58.5pt, right: 55.7pt),
  header-ascent: 10pt,
  footer-descent: 18pt,
  header: context {
    let started = body-started.at(here())
    let p = counter(page).at(here()).first()
    if not started or p == start-page-val {
      // The opening page carries the chapter title; a running head would sit
      // on top of it. Its folio goes in the footer instead.
      none
    } else {
      let styled(s) = text(size: 9pt, fill: ink, font: body-font, s)
      let folio = if hide-folios { [] } else { styled(numbering(folio-style, p)) }
      if calc.even(p) {
        align(left, folio + h(1em) + styled(emph(verso-label)))
      } else {
        align(right, styled(emph(recto-label)) + h(1em) + folio)
      }
    }
  },
  footer: context {
    let p = counter(page).at(here()).first()
    let started = body-started.at(here())
    // Only the opening page foots a folio; every later page carries it in the
    // running head, so footing it again would print it twice.
    if hide-folios or not started or p != start-page-val {
      if footer-val != "" and started {
        align(center, text(size: 8pt, fill: ink-soft, font: body-font, footer-val))
      } else {
        none
      }
    } else {
      let folio = text(size: 9pt, fill: ink, font: body-font, numbering(folio-style, p))
      align(if calc.even(p) { left } else { right }, folio)
    }
  },
  // The volume label, rotated into the outer margin, with a hairline between
  // it and the text block. Verso reads upward out of the left margin; recto
  // reads downward out of the right, so the label always runs away from the
  // spine. All four numbers are measured off the printed series: the label
  // centres on x 32.1 (verso) / 398.6 (recto) and y 99.9, and the rule drops
  // from y 57 to y 179.4 at x 40.2 / 390.
  //
  // The label is rotated about the centre of a fixed box and placed by that
  // centre, because anchoring a rotated box by a corner moves it as the
  // string length changes, and a volume title is not a fixed width.
  background: context {
    let started = body-started.at(here())
    let p = counter(page).at(here()).first()
    if not (started and has-volume-label and p != start-page-val) {
      none
    } else {
      let label = box(width: 90pt, height: 12pt, align(center + horizon, text(
        size: 9pt, fill: ink-soft, font: display-font, tracking: 0.08em,
        smallcaps(volume-label-content),
      )))
      let rule = line(
        angle: 90deg, length: 122.4pt, stroke: 0.4pt + rule-color,
      )
      if calc.even(p) {
        place(top + left, dx: 40.2pt, dy: 57pt, rule)
        place(top + left, dx: 32.1pt - 45pt, dy: 99.9pt - 6pt,
          rotate(-90deg, origin: center + horizon, reflow: false, label))
      } else {
        place(top + left, dx: 390pt, dy: 57pt, rule)
        place(top + left, dx: 398.6pt - 45pt, dy: 99.9pt - 6pt,
          rotate(90deg, origin: center + horizon, reflow: false, label))
      }
    }
  },
)

#counter(page).update(start-page-val)

#set text(
  font: body-font,
  size: 11pt,
  fill: ink,
  lang: "en",
  features: ("kern", "liga", "onum"),
)
// The series sets justified and hyphenated text; its lines break mid-word
// (com-/plete, writ-/ing) rather than opening up the word spacing, which is
// the opposite of the LiCS house setting and deliberate here.
#set text(hyphenate: true)
// 11pt on a 13.2pt baseline, held exactly. Typst derives a line's height from
// the font's own ascender and descender, so leading given in em lands on a
// different baseline in every face, and the face here is not guaranteed:
// where EB Garamond is missing the stack falls through. Pinning top-edge and
// bottom-edge to explicit lengths makes every line box exactly 1em tall
// whatever the font, so baseline-to-baseline is simply 11pt + leading.
#set text(top-edge: 0.75em, bottom-edge: -0.25em)
// Paragraph spacing equals leading: paragraphs are marked by the 14.4pt
// first-line indent alone, with no blank space between them.
#set par(
  justify: true,
  leading: 2.2pt,
  spacing: 2.2pt,
  first-line-indent: 14.4pt,
  linebreaks: "optimized",
)

// Section heads: 12pt small caps, centred. The series runs every structural
// head at one size (Overview, the named body sections, Works Cited,
// Discussion Questions), so levels 1 and 2 differ only in the space around
// them. `sticky` keeps a head attached to the text beneath it; `breakable:
// false` keeps a two-line head from splitting across the spread.
#let section-head(it, size: 12pt, above: 1.8em, below: 1.0em) = block(
  breakable: false, sticky: true, width: 100%,
  above: above, below: below,
  {
    set par(first-line-indent: 0pt, leading: 0.25em, justify: false)
    // Body copy in this series hyphenates; display type never does. Without
    // this a two-line head breaks mid-word ("by Taylor Lu-/cas"), which the
    // printed series does not do anywhere.
    set text(hyphenate: false)
    align(center, text(font: display-font, size: size, weight: 600, smallcaps(it.body)))
  },
)

#show heading.where(level: 1): it => section-head(it)
#show heading.where(level: 2): it => section-head(it, size: 11pt, above: 1.4em, below: 0.8em)
#show heading.where(level: 3): it => block(
  breakable: false, sticky: true, width: 100%,
  above: 1.2em, below: 0.5em,
  {
    set par(first-line-indent: 0pt, justify: false)
    text(size: 11pt, style: "italic", fill: ink-soft, it.body)
  },
)

// First paragraph after any head runs flush, as in the printed series.
#show heading: it => {
  it
  set par(first-line-indent: 0pt)
}

// Block quotations: indented both sides at body size, no rule and no italic.
// The indent is the only marker, and the space above and below is set once on
// the block so it cannot stack unevenly against paragraph spacing.
#show quote.where(block: true): it => block(above: 0.9em, below: 0.9em, {
  set par(first-line-indent: 0pt, leading: 0.2em, justify: true)
  pad(left: 28pt, right: 14pt, text(size: 11pt, it.body))
})

// Lists: hanging indent with the marker clear of the text column, which is
// how the series sets its Discussion Questions and Recommended Activities.
#set enum(indent: 10pt, body-indent: 8pt, spacing: 0.9em)
#set list(indent: 10pt, body-indent: 8pt, spacing: 0.9em)

#set table(
  inset: 7pt,
  stroke: (top: 0.8pt + ink, bottom: 0.8pt + ink, left: 0pt, right: 0pt, x: 0pt, y: 0.4pt + rule-color),
)
#show table: it => {
  set text(size: 10pt)
  set par(first-line-indent: 0pt, leading: 0.3em, justify: false)
  v(0.4em)
  it
  v(0.4em)
}

// figures-filter.lua has already numbered figures and prefixed the caption,
// so Typst's own numbering stays off or captions read "Figure 1: FIGURE 1."
#set figure(supplement: none, numbering: none, gap: 0pt)
#show figure: it => block(breakable: false, width: 100%, {
  set par(first-line-indent: 0pt, justify: false)
  v(0.9em)
  align(center, it.body)
  v(0.5em)
  set par(justify: true)
  text(size: 9.5pt, fill: ink-soft, it.caption)
  v(1em)
})

// Footnotes run at 9pt on a 10.8pt baseline under a 72pt rule, which is where
// the series puts its CC licence note on the opening page.
#set footnote.entry(
  separator: line(length: 72pt, stroke: 0.4pt + ink),
  gap: 0.5em,
  indent: 0pt,
)
#show footnote.entry: it => {
  set par(first-line-indent: 0pt, leading: 0.15em, justify: true)
  set text(size: 9pt)
  it
}

#show link: it => text(fill: ink, it)

// ---------- Chapter opening ----------

// The chapter number hangs to the left of the title's first line and the
// title's turn lines align under its opening word. Printed measurement puts
// the number at 76.5pt and the title at 90pt against a 58.5pt text edge, so
// both sit inside the measure rather than on it.
//
// The printed first line is 20pt and its turn lines 18pt, an InDesign nested
// style. Typst cannot vary size per line within one paragraph, so the title
// is set at 18pt throughout and only the hanging number keeps the 20pt.
#block(width: 100%, above: 0pt, below: 0pt, {
  set par(first-line-indent: 0pt, justify: false, leading: 0.35em)
  set text(hyphenate: false)
  v(0.28in)
  grid(
    columns: (31.5pt, 1fr),
    align: (left + top, left + top),
    if has-chapter-number {
      // 18pt in from the text edge, so the number hangs beside the title
      // without reaching the measure.
      pad(left: 18pt, text(font: display-font, size: 20pt, weight: 400, chapter-number-content))
    } else { [] },
    text(font: display-font, size: 18pt, weight: 400, smallcaps(title-content)),
  )
  $if(subtitle)$
  v(0.5em)
  pad(left: 31.5pt, text(font: display-font, size: 13pt, style: "italic", fill: ink-soft, [$subtitle$]))
  $endif$
})

// Byline. Pandoc's template language can join a list with a single separator,
// so its loop construct gives "A, B, C" but never "A, B, and C", which is
// what the series prints. The author tuple Python substitutes for the
// document metadata is reused here instead, so the serial "and" is built in
// Typst, where the length of the list is actually known.
//
// Do not write that loop construct literally in a comment: Pandoc does not
// know Typst comment syntax and expands the directive wherever it appears,
// which opens a block with no close and fails the render with nothing more
// useful than "unexpected end of input".
//
// One author substitutes as a bare string rather than a one-element array,
// which is valid for `document.author` but is not an array, so the type is
// normalised before anything indexes it.
#let author-raw = (GRAPHION_AUTHORS_PLACEHOLDER)
#let author-names = {
  let raw = if type(author-raw) == str { (author-raw,) } else { author-raw }
  raw.map(n => n.trim()).filter(n => n != "")
}
#let byline = if author-names.len() == 0 {
  []
} else if author-names.len() == 1 {
  author-names.at(0)
} else if author-names.len() == 2 {
  author-names.join(" and ")
} else {
  author-names.slice(0, -1).join(", ") + ", and " + author-names.last()
}

#block(width: 100%, above: 2.0em, below: 0pt, {
  set par(first-line-indent: 0pt, justify: false, leading: 0.3em)
  align(center, text(size: 12pt, style: "italic", byline))
})

$if(abstract)$
// The Overview sits on the opening page with the body running on beneath it,
// separated by a short centred rule. It is not an abstract page: the series
// never breaks between the two.
#block(width: 100%, above: 2.2em, below: 0.9em, {
  set par(first-line-indent: 0pt, justify: false)
  align(center, text(font: display-font, size: 12pt, weight: 600, smallcaps("Overview")))
})
#block(width: 100%, {
  set par(first-line-indent: 0pt, justify: true, leading: 0.2em)
  text(size: 11pt, [$abstract$])
})
#block(width: 100%, above: 1.8em, below: 1.8em,
  align(center, box(width: 142.4pt, line(length: 100%, stroke: 0.5pt + ink))))
$endif$

// Furniture starts with the body: the opening page keeps its folio in the
// footer and carries no running head or margin tab.
#body-started.update(true)

// ---------- Body ----------

$body$
