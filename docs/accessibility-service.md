# Accessibility remediation as a service

Scoping note, written 2026-11-01. What Graphion would need before its
accessibility work could be offered to journals other than LiCS and Writing
Spaces, and what the service around it would have to say out loud.

The Writing Spaces remediation produced 115 conformant chapters, 201
hand-written figure descriptions, and six tagged bound volumes out of a series
of print PDFs. Almost none of that capability is addressable by anyone else,
because it is distributed between one journal's
template bundle, a set of per-article routes with no corpus view, and the
accumulated knowledge in `CLAUDE.md`. This note sorts out which parts are real
tooling, which parts are one journal's configuration, and which parts were
labour that no amount of tooling removes.

---

## 1. What the requirement is

### The rule the question starts from

The DOJ's Title II web rule (28 CFR Part 35) adopts **WCAG 2.1 Level AA** as
the technical standard for state and local government web content and mobile
apps. The compliance dates are:

| Entity | Date |
|---|---|
| Public entity serving 50,000 or more | **April 26, 2027** |
| Public entity under 50,000, and any special district government | **April 26, 2028** |

Those are the extended dates. The original rule set April 2026; an interim
final rule published in April 2026 moved both by a year, leaving the
substantive requirements untouched. So 2027 and 2028 are current, and anyone
working from a university web page that still says April 2026 is reading a
stale deadline.

### Who it reaches

A public university is a Title II public entity, and the rule covers web
content the entity "provides or makes available," including through
arrangements with others. A journal hosted by a public university library, run
out of a department, or served from an OJS instance on university
infrastructure is that university's web content. Most journals in rhet/comp
sit in exactly that position. A journal at a private institution does not, and
a journal at a private institution with federal funding has a different set of
questions (Section 504, Section 508 if it is federal content) that this note
does not cover.

### The two exceptions that decide what the work is

Both exceptions turn on the date a document was posted, which is why they
leave a journal's oldest content alone and its newest content exposed.

**Preexisting conventional electronic documents.** PDFs, word processing
files, spreadsheets and presentations posted *before* the compliance date
generally do not have to conform. The exception dies if the document is still
used to apply for or access a service, or if a new or substantially updated
version is posted.

**Archived web content.** Content is exempt only if it meets all four
conditions: created before the compliance date (or reproducing pre-existing
physical media), kept only for reference, research or recordkeeping, in a
designated archive area, and unchanged since being archived. Any edit removes
the exception.

Read together: **a journal's back catalogue is largely exempt, and its next
issue is not.** The compelled work is forward-looking, and the back catalogue
is a choice. The choice is often still worth making, for three reasons that
have nothing to do with the deadline:

- The exemption covers the *document*, not the pages around it. Article
  landing pages, tables of contents, issue indexes and search results are
  ordinary web content with no exemption at all.
- Touching an exempt document un-exempts it. A journal that corrects a typo
  in a 2019 article has just acquired an obligation for that article.
- A reader using a screen reader does not care which side of April 2027 an
  article was posted.

### What else is in force

**The European Accessibility Act** has applied to ebooks sold to consumers in
the EU since **28 June 2025**, with EPUB Accessibility 1.1 (ISO/IEC 23761) and
WCAG 2.1 as the benchmarks, plus accessibility metadata in the package
document and a published accessibility statement. Any journal distributing
EPUB into the EU is already past its date. Graphion emits EPUB and emits none
of that metadata; see §3.6.

### What institutions ask for as evidence

An **Accessibility Conformance Report**, which is a completed VPAT (current
template: VPAT 2.5Rev, April 2025). Libraries and procurement offices ask for
one by name, several require version 2.5 or later, and at least one state
checklist fails any report dated more than a year old. An ACR is a measurement
and a set of claims, not a certificate, and the claims are the evaluator's.
Whoever signs one is the person a journal's library will come back to; §6 is
about what that commits you to.

---

## 2. What Graphion already does

The roadmap's "no accessibility validation" entry
(`docs/audit-and-roadmap.md` §3.7) predates most of what follows and should be
read as stale.

**The PDF galley is validated, not declared.** `conversion._compile_typst()`
(`conversion.py:1388`) compiles with `pdf_standards` set from
`config.PDF_UA_STANDARD`, and Typst validates the standard rather than
asserting it, so content that cannot conform aborts the compile. The fallback
to an unconstrained render is logged with the reason, so a galley that lost its
conformance leaves a record.

**A bound issue carries the tagging rather than claiming it.**
`pdf_tags.concatenate_tagged()` rebuilds the structure tree, the `/ParentTree`,
the `/IDTree` and the annotation round trip from the parts, walks every page's
`/StructParents` back into the tree it built, and stamps `pdfuaid:part` only
when every part declared it, no annotation was dropped, every page resolves,
and every link reaches its own tag. `MergeReport` names what fell short.

**The checks that exist are the right ones.** `lint.py` holds
`check_alt_text`, `check_math_alt_text`, `check_images_of_text`,
`check_figure_coverage` and `check_unreadable_characters`. Each one was written
against a failure that shipped, and each one keeps a shortfall countable rather
than closing over it: an undescribed figure is reported as undescribed, a
caption carried as alt text is reported as a caption, an equation nothing can
read aloud is reported against the ones that can be, and a figure whose words
are a picture is counted against WCAG 1.4.5 even though the galley conforms and
the figure is described.

**Editorial work survives re-ingest.** `conversion.carry_alt_text()` and
`carry_editor_fields()` match hand-written descriptions back by asset path and
carry `images-of-text`, `teacher-resources` and `math-alt` through a rebuild.
The 201 descriptions in the Writing Spaces archive exist because that path
exists.

**Legacy PDF structure is reconstructed rather than guessed at.**
`pdf_ingest.py` infers paragraphs, heads, emphasis and word breaks from page
geometry learned per document, drops clipped ink by reading the content
stream's own clipping path, finds tables by their rules, places uncaptioned
figures by the hole they left in the text block, and translates symbol-font
characters that would otherwise reach a screen reader as meaningless private
use codepoints.

What carries over to another journal is less the feature list than the habit
behind it: nothing in the pipeline claims conformance it has not checked, and
a shortfall that cannot be fixed stays counted instead of being absorbed. An
ACR asks for exactly that, criterion by criterion, which is the part a vendor
selling a scan cannot supply.

---

## 3. What is missing

In rough order of how badly each one bites.

### 3.1 Math silently cost the galley its conformance (fixed)

Verified on this checkout, Pandoc 3.11 and the bundled Typst:

- Typst refuses math under PDF/UA-1. A document containing `$x^2 + y$` fails
  to compile with `PDF/UA-1 error: missing alt text`.
- Pandoc's Typst writer emits bare `$...$` with no alt text.
- So `_compile_typst` caught the failure, fell back to an unconstrained
  render, and wrote the log line.
- `lint.check_alt_text` could not see it, because it matches Markdown image
  syntax. The article linted clean.

**An article with one equation shipped without the conformance identifier and
no check reported it.** It had never fired, because neither LiCS nor Writing
Spaces sets math; there is no `$$` anywhere in the content tree. It was a hard
blocker for any journal that has equations, which includes most of the social
sciences. The galley rendered, it looked right, and it failed an audit.

(The HTML galley was always fine. Pandoc 3.11 emits real MathML by default,
with the TeX preserved in `<annotation>`.)

This is now closed, in `math_alt.py` and `filters/math-alt.lua`. It took two
fixes rather than one, and the second is the one to read if you only read one,
because the same decision comes up again in §3.4 and in anything this service
would price.

The easy half is the lint check. `lint.check_math_alt_text` finds the
equations and reports how many have no spoken description, which makes an
invisible failure countable.

The hard half is the alt text itself, because an equation's alt text is a
spoken rendering and not a transcription of the TeX. Handing Typst the raw TeX
would satisfy the validator and tell a listener nothing: `x^2` read literally
is "x caret 2". So `math_alt.speak()` translates, over a vocabulary of symbols
that read one way and no other, and declines everything else. A compound
numerator gets an explicit end marker, because the page shows a grouping that
speech does not. A tilde is left out of the vocabulary entirely: it reads "is
similar to" in geometry and "is distributed as" in statistics, and the
expression cannot say which.

Declining is the whole design and not a limitation of it. A formula read half
right is present and wrong in a galley that passes every audit, which is the
one failure no checker and no client can catch. What declines gets a
placeholder instead, so the galley conforms, and `check_math_alt_text` goes on
counting what is owed; an author's own reading, kept by hand in the article's
`math-alt` front matter, always wins. That is the `undescribed_alt` trade
exactly, and it is what an automated scan sold as a conformance report does
not do: the tool reports what it could not read.

One decision here belongs with §3.2, because it is the same lesson. The filter
is app level rather than per journal. How a caption is set is a journal's
design; whether a formula can be read aloud is not, and `new_journal.py` clones
a bundle, so anything in a bundle is something a new journal can drop.

### 3.2 The accessible template belongs to one journal, not to Graphion

The two template bundles are not equivalent. Writing Spaces has a skip link, a
`<main>` landmark, `aria-labelledby` pointing at real heading ids, and an
unconditional licence statement. LiCS has none of those: no `<main>`, no skip
link, `aria-label` on sections instead of `aria-labelledby`, and no licence
block.

`new_journal.py` clones the **LiCS** bundle by default
(`STARTER_JOURNAL_SLUG = "lics"`). So every new journal starts from the less
accessible of the two, and the remediation knowledge sits in a template that
nothing propagates.

Fixing it is a day's work and it reaches every journal added from here on.
A skip link and a landmark are WCAG 2.4.1; `aria-label` on a section that has
a visible heading is a worse construction than `aria-labelledby` pointing at
it, because it replaces the heading text with a duplicate string that can
drift. Whatever the accessible markup is, it belongs in whichever bundle
`new_journal.py` copies, and the divergence between bundles belongs in a test.

### 3.3 There is no corpus view, and no check is persisted

Every accessibility surface in the app is per-article and route-only:

```
/articles/<id>/lint
/articles/<id>/validate-pdf      -> writes verapdf-report.json
/articles/<id>/validate-html     -> writes pa11y-report.json
/articles/<id>/verapdf-report
/articles/<id>/pa11y-report
```

There is no issue-level or journal-level rollup, and `lint.run()` results are
rendered and discarded: nothing records that a check ran, when, or against
which version of the article. The two validator reports are written to disk
but are not dated, not tied to a content hash, and not aggregated.

So the question a journal will ask first, "where do we stand," can only be
answered by opening 115 pages and adding up by hand. An ACR answers the same
question, criterion by criterion and with a date on it, so the register this
gap describes is a prerequisite for the evidence rather than a convenience.

### 3.4 Nothing can assess content Graphion did not ingest

Every check in `lint.py` takes an article row and reads `article.md`. There is
no way to point the tool at a folder of a journal's existing PDFs or at a live
journal site and get back a statement of where it stands.

`ingest_volume.py --dry-run` is the nearest thing, and it plans an ingest
rather than reporting a state: it answers "what would I do with these files,"
not "what is wrong with them and what would fixing it cost." Those are
different questions and the second one is the one a journal pays for. A journal
cannot commission remediation it cannot see the size of, and the size is
knowable from the files: how many figures, how many are already described, how
many tables, how many pages are image-only, how many set symbol fonts, how
many clip their ink, whether the existing PDFs declare any tagging at all.

Most of the reading needed for this already exists in `pdf_ingest.py`. What
does not exist is a mode that reads without writing and reports instead of
ingesting.

### 3.5 Tables stop at what a pipe table can express

Confirmed against Pandoc 3.11: the HTML writer emits `<th>` with no `scope`
attribute. More structurally, a Markdown pipe table has exactly one header
row and no way to mark a row header or a two-level header, so a table that
needs either is lossy in the source before Pandoc ever sees it.

For prose journals this has not mattered; the archive's tables are simple
enough that assistive technology infers the association. For any journal with
real data tables it is a wall, and it is a WCAG 1.3.1 failure that no current
check reports. Graphion's own table handling is good (`drop_lines_inside_tables`
exists precisely because interleaved cells are worse than a missing table), but
good extraction into a format that cannot express the structure is still lossy.

One thing here is unverified and should be checked before anything is promised
about tables. A `#table` with a `table.header` row does compile under
PDF/UA-1, which is how the math test in §3.1 was isolated, but a clean compile
only says Typst was satisfied; it does not say the header cells carry
`/Scope`. Confirming that needs a verapdf run and a look at the objects.

### 3.6 The EPUB carries no accessibility metadata

`conversion.render_epub()` (`conversion.py:1665`) passes `--standalone`, the
journal CSS, the figures filter, citations and author metadata. It writes none
of the EPUB Accessibility 1.1 discoverability metadata, all of which is
required:

- `schema:accessMode`
- `schema:accessibilityFeature`
- `schema:accessibilityHazard`

and, recommended, `schema:accessibilitySummary` and
`schema:accessModeSufficient`. A conformance claim additionally needs
`dcterms:conformsTo` with the exact string `EPUB Accessibility 1.1 - WCAG 2.1
Level AA` and an `a11y:certifiedBy` naming the evaluator.

Half a day of work. Without it a library catalogue has nothing to tell a
reader about the file, and this is the one item in this list whose date has
already passed.

### 3.7 There is no surface for writing alt text

The 201 descriptions in the Writing Spaces archive were written by hand into
article front matter. There is no queue, no image-beside-the-field view, no
progress count, and no way to see at a glance which figures in a volume are
still carrying their caption or an `undescribed_alt` placeholder.

Everything else in this document is engineering that happens once. Describing
figures is per-figure labour on every job, and it is the only line item a
quote would be denominated in. Tooling cannot write the descriptions. It can
cut the time each one takes, which over 201 of them is the difference between
a week and a month.

### 3.8 Smaller gaps, named so they are not discovered later

- **Language of parts (WCAG 3.1.2).** `lang` is set at the document level in
  both templates. A quoted passage in another language carries no markup, and
  nothing in the pipeline could add it without being told.
- **Contrast (1.4.3, 1.4.11).** A property of each journal's `article.css`.
  Nothing checks it, and `pa11y` would only catch it if run, which is
  optional.
- **The validators are optional and advisory.** `verapdf_available()` and
  `pa11y_available()` grey out the UI when the tools are absent. For a service
  they are not optional; they are the evidence.
- **Reading order in the tagged PDF.** `pdf_ingest` reconstructs it and
  `pdf_tags` verifies every page is reachable from the structure tree, which
  is not the same as verifying the tagged order matches the printed order. The
  figure-placement and table-anchor work in `pdf_ingest` is exactly about this,
  and it degrades with a note rather than silently, which is right, but nothing
  checks the result.
- **Heading hierarchy.** No check for a skipped level, which the roadmap
  flagged and which never got written.
- **Long descriptions.** A complex figure (a five-stage flowchart, a
  whiteboard collage) needs more than alt text, and there is no slot for one in
  the front matter or either template.

---

## 4. What the buildout looks like

Four stages. Each one ends in something usable on its own, and they are in
dependency order rather than value order: you cannot honestly hand a journal a
report before Graphion's own output is defensible.

### Stage 1: make the output defensible (about a week)

Everything in §3.1, §3.2, §3.5 and §3.6. Concretely:

- ~~A lint check for math in the body~~ and ~~alt text on each equation~~.
  Both done: `math_alt.py`, `filters/math-alt.lua`,
  `lint.check_math_alt_text`. About half a day, and it closed the only gap
  here that was costing conformance rather than evidence.
- Move the accessible markup into the bundle `new_journal.py` clones, and add a
  test that fails when a bundle loses a landmark or the skip link.
- `scope` on table headers via a filter, and a decision recorded about what
  Graphion does with a table that needs a row header.
- EPUB accessibility metadata, with the conformance string only where the
  checks support the claim.

### Stage 2: the register (about a week)

Persist every check with a timestamp and a content hash, and roll it up.

- New tables for check results, additive per the migration rule in
  `CLAUDE.md`: which check, which article, which version, what level, when.
- Record `verapdf` and `pa11y` runs the same way, including that they were not
  run and why.
- Record the PDF/UA fallback as a check result rather than only a log line,
  since that log is currently the only trace that a galley lost conformance.
- One page per journal and per issue that answers "where does this stand":
  articles conformant, figures described, figures owed, images of text,
  equations, tables, when each was last verified.

This is the piece everything else depends on. It converts the per-article
checks into the thing a journal and an ACR both need, which is a dated,
aggregate statement with the shortfalls named.

### Stage 3: the assessment (about a week)

A read-only pass over content Graphion did not produce, so a journal can see
the size of the job before commissioning it.

- Point it at a folder of PDFs or a journal's HTML. It writes nothing.
- Reuse `pdf_ingest`'s readers to count what drives the work: figures, figures
  with any existing description, tables, ruled versus unruled, image-only
  pages, symbol-font pages, clipped pages, cover pages, pages whose structure
  had to be inferred.
- Run `verapdf` over their existing PDFs and `pa11y` over their existing HTML,
  and report what is already there rather than assuming nothing is.
- Output a per-item statement and an aggregate, denominated in the units that
  cost time: figures to describe, tables to rebuild, pages to proofread after
  OCR, articles that need structure inferred rather than read.

### Stage 4: the description queue (about four days)

- One figure at a time: the image, the printed caption, the current alt text,
  the article it came from, a field.
- Draft from the caption where there is one, which is what ingest already
  does, and mark it as a draft so `check_alt_text` keeps counting it.
- Keyboard-driven, with a progress count per volume.
- Write through the existing front matter path so `carry_alt_text` protects
  the result from the next re-ingest.
- A second lane for `images-of-text`, which is a different judgement and
  currently a hand-maintained list.

### Then: the evidence pack (two or three days)

Generate the ACR from the register rather than typing it. A VPAT 2.5Rev with
each criterion's support level backed by a named check and a date, the
shortfalls listed as shortfalls, and the evaluation date stamped. The point of
generating it is that it cannot drift from what the checks actually found.

Roughly five to six weeks of focused work for all of it. Stages 1 and 2 come
first because a report generated before them would be describing output that
cannot yet back it up.

---

## 5. What none of this fixes

Worth saying in the first conversation with any journal, because every item
here is labour rather than engineering, and a service that implies otherwise
will be wrong about its own quote.

- **Alt text is writing.** 201 descriptions, by hand, over 49 chapters. The
  pipeline can draft from a caption, carry a description through a rebuild, and
  count what is owed. It cannot decide what is in a photograph.
- **Describing a figure does not fix an image of text.** Writing alt text
  satisfies 1.1.1 and leaves 1.4.5 exactly where it was. 113 of Writing
  Spaces' 196 figures carry text as a picture, and the fix is transcription
  into the chapter, which is editorial work on each one.
- **Image-only PDFs need OCR and then proofreading.** OCR output is a draft.
- **A long description is a paragraph, not a field.** Beyond the missing slot
  in §3.8, somebody has to sit with the flowchart and work out which of its
  five stages a listener needs in what order.
- **WCAG applies to the journal's site, not just its galleys.** Graphion makes
  articles. A journal on OJS has an OJS problem that no amount of galley
  quality touches, and the article landing pages are the part with no
  exemption. Be explicit about the boundary or the first engagement will
  discover it.
- **Two journals is not a sample.** Every heuristic in `pdf_ingest` was
  learned from six volumes of one series. The module degrades with a note
  rather than silently, which is the right design, but a new publisher's
  typesetting will produce notes nobody has seen yet, and the first job for a
  new series should be priced as calibration.

---

## 6. Standing behind the claims

An ACR is the evaluator's assertion. Signing one means saying what was
checked, by what, when, and what fell short, and being willing to be wrong in
public about it.

Graphion is already built for that. Typst validates PDF/UA rather
than declaring it. `concatenate_tagged` stamps `pdfuaid:part` only when every
part earned it and names the parts that did not. `check_alt_text` reports a
caption carried as alt text as a caption. `check_images_of_text` keeps counting
a shortfall the galley has already passed. `math_alt.speak` declines a formula
it cannot read one way rather than reading it nearly right. Every one of those
keeps a claim and the thing it claims apart, which is the discipline an ACR is
asking for.

Two consequences follow:

- **Report the shortfalls in the deliverable.** A journal that gets back "115
  of 115 conformant, 201 figures described, 113 still carrying text as a
  picture, 4 equations whose spoken rendering is mechanical" has something it
  can act on and defend. One that gets back a green check has bought nothing.
- **Date everything.** A state checklist already fails any ACR over a year
  old, and a re-render can lose conformance an earlier run had. Without the
  Stage 2 register, "we checked that" is a recollection; with it, the date and
  the article version are on the record.

---

## Sources

- [ADA Title II web rule fact sheet](https://www.ada.gov/resources/2024-03-08-web-rule/)
  (deadlines, covered entities, the WCAG 2.1 AA standard, and the archived
  content / preexisting document / third-party content exceptions)
- [EdTech Magazine on the deadline extension](https://edtechmagazine.com/higher/article/2025/06/guide-ada-title-ii-accessibility-rule-perfcon)
  and [Jackson Lewis on the April 2026 interim final rule](https://www.jacksonlewis.com/insights/doj-extends-public-entities-compliance-deadline-ada-related-website-accessibility-hhss-may-2026-deadline-still-looms)
- [W3C EPUB Accessibility 1.1](https://www.w3.org/TR/epub-a11y-11/)
  (required discoverability metadata and the exact `dcterms:conformsTo` string)
- [IPA overview of the European Accessibility Act for publishers](https://internationalpublishers.org/the-european-accessibility-act-for-non-eu-members/)
- [Elsevier's published ACR directory](https://www.elsevier.com/about/accessibility/acr),
  as a model for what a publisher-side conformance report looks like
- [Massachusetts ACR review checklist](https://www.mass.gov/info-details/accessibility-conformance-report-review)
  (the one-year currency requirement)

Deadlines and exception wording should be checked against the Federal Register
notice itself before any of this goes in front of a journal. The dates moved
once already.
