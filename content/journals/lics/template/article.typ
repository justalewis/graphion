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

#let short-title-val = "$short-title$"
#let short-authors-val = "$short-authors$"
#let footer-val = "$footer$"
#let start-page-val = $if(start-page)$$start-page$$else$1$endif$

// Drop cap helper. Typst doesn't natively wrap body text around a
// floated initial (no shape-aware reflow), so this is a stylized
// initial: an oversized first letter that drops below the baseline,
// with subsequent body flowing at full width to its right and below.
// The visual effect approximates a scholarly-book opening even without
// true wrap-around.
#let dropcap(letter) = {
  text(
    size: 3.6em,
    weight: 500,
    baseline: 0.55em,
    font: ("EB Garamond", "Garamond", "Georgia"),
    [#letter]
  )
  h(0.05em)
}

#set document(
  $if(title)$title: "$title$",$endif$
  $if(author)$author: ($for(author)$"$author.name$"$sep$, $endfor$),$endif$
  $if(keywords)$keywords: ($for(keywords)$"$keywords$"$sep$, $endfor$),$endif$
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
      align(left, text(style: "italic", size: 9.5pt, fill: ink-soft, short-authors-val))
    } else {
      align(right, text(style: "italic", size: 9.5pt, fill: ink-soft, short-title-val))
    }
  },
  footer: context {
    let p = counter(page).at(here()).first()
    if p == start-page-val { return [] }
    let page-str = str(p)
    let label = if footer-val != "" { footer-val + "  ·  " + page-str } else { page-str }
    align(center, text(size: 9.5pt, fill: ink-soft, label))
  },
)

// Shift the page counter so the first page is labeled `start-page-val`.
#counter(page).update(start-page-val)

#set text(
  font: ("EB Garamond", "Garamond", "Georgia"),
  size: 11.25pt,
  fill: ink,
  lang: "en",
  features: ("kern", "liga", "onum"),
)
#set par(
  justify: true,
  leading: 0.62em,
  first-line-indent: 1.4em,
  linebreaks: "optimized",
)
// Disable word-level hyphenation across the document. Long words flow to
// the end of the line and break only at natural boundaries; justified
// lines may therefore have wider word spacing on some lines, which is
// the intended trade-off.
#set text(hyphenate: false)

// Section-h1: centered small-caps with a hairline rule above
#show heading.where(level: 1): it => {
  set par(first-line-indent: 0pt)
  v(1.6em)
  line(length: 100%, stroke: 0.5pt + rule-color)
  v(0.6em)
  align(center, text(
    size: 10.5pt,
    weight: 500,
    tracking: 0.18em,
    smallcaps(it.body),
  ))
  v(0.6em)
}

// Section-h2: italic, left-aligned
#show heading.where(level: 2): it => {
  set par(first-line-indent: 0pt)
  v(1em)
  text(size: 12pt, style: "italic", weight: 400, it.body)
  v(0.3em)
}

// Section-h3: italic, ink-soft, smaller
#show heading.where(level: 3): it => {
  set par(first-line-indent: 0pt)
  v(0.7em)
  text(size: 10.5pt, style: "italic", weight: 400, fill: ink-soft, it.body)
  v(0.2em)
}

// First paragraph after a heading: no indent
#show heading: it => {
  it
  set par(first-line-indent: 0pt)
}

// Blockquotes: smaller, indented, no border
#show quote.where(block: true): it => {
  set par(first-line-indent: 0pt, leading: 0.6em)
  v(0.6em)
  pad(left: 1.5em, right: 1em, text(size: 10pt, it.body))
  v(0.6em)
}

// Links: subtle, ink color (no underline noise in print)
#show link: it => text(fill: rgb("#5a3a1f"), it)

// ---------- Title page ----------

#align(center, {
  set par(first-line-indent: 0pt)
  v(0.4in)
  text(size: 22pt, weight: 500, [$title$])
  $if(subtitle)$
  v(0.4em)
  text(size: 14pt, style: "italic", fill: ink-soft, [$subtitle$])
  $endif$
  v(1.2em)
  $for(author)$
  text(style: "italic", size: 11pt, fill: ink-soft, [$author.name$$if(author.affiliation)$ \u{2014} $author.affiliation$$endif$])
  linebreak()
  $endfor$
  v(0.6em)
  line(length: 40%, stroke: 0.5pt + rule-color)
  v(0.8em)
})

$if(keywords)$
#align(center, block(width: 80%, {
  set par(first-line-indent: 0pt)
  text(size: 8pt, tracking: 0.22em, fill: ink-soft, smallcaps("Keywords"))
  v(0.3em)
  text(style: "italic", size: 9.5pt, fill: ink-soft, [$for(keywords)$$keywords$$sep$; $endfor$])
}))
#v(0.6em)
$endif$

$if(abstract)$
#align(center, block(width: 85%, {
  set par(first-line-indent: 0pt, justify: true, leading: 0.6em)
  text(size: 8pt, tracking: 0.22em, fill: ink-soft, smallcaps("Abstract"))
  v(0.4em)
  text(size: 9.75pt, [$abstract$])
}))
#v(1em)
$endif$

#pagebreak()

// ---------- Body ----------

$body$
