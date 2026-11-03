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

**Fixed, by raising the other bundle rather than changing which one is
copied.** LiCS now carries the skip link, the `<main>` landmark,
`aria-labelledby` pointing at its own headings, a `:focus-visible` outline
it had never had at all, and the licence in both the metadata and the
document. A journal added from here starts accessible whichever bundle it
starts from, and LiCS's own galleys stopped being the less accessible ones.

`tests/test_template_bundles.py` holds it, and holds it for bundles that do
not exist yet: it reads whatever is on disk under
`content/journals/*/template/` and checks each one, so a journal added
tomorrow is covered without anybody remembering to add it. Of the eight
things it checks, seven would have failed on the LiCS bundle as it stood.
Two of them pair the markup with the stylesheet, which is the half easiest
to get wrong in isolation: markup without the CSS puts a visible "Skip to
the article" link above every title, and CSS that hides it with no `:focus`
rule hides it from the keyboard reader it exists for.

Adding the licence to the template also made a dormant bug live. The LiCS
journal filter still walked the whole document with the URL filter, which
inserts soft break points so a long citation cannot run off the measure, so
`<wbr>` went straight through the licence href and the link pointed
nowhere. Writing Spaces had been fixed; LiCS had not, which is this
section's own point in miniature. Both filters now walk `doc.blocks`.

### 3.3 There was no corpus view, and no check was persisted (fixed)

Every accessibility surface in the app was per-article and route-only:

```
/articles/<id>/lint
/articles/<id>/validate-pdf      -> writes verapdf-report.json
/articles/<id>/validate-html     -> writes pa11y-report.json
/articles/<id>/verapdf-report
/articles/<id>/pa11y-report
```

There was no issue-level or journal-level rollup, and `lint.run()` results were
rendered and discarded: nothing recorded that a check ran, when, or against
which version of the article. The two validator reports were written to
disk but not dated, not tied to a content hash, and not aggregated.

So the question a journal will ask first, "where do we stand," could only be
answered by opening 115 pages and adding up by hand. An ACR answers the same
question, criterion by criterion and with a date on it, so the register is a
prerequisite for the evidence rather than a convenience.

`register.py` and the `check_runs` table are that register. Every lint run and
every validator run is stored against a sha256 of the file the check read, and
`/accessibility` rolls the result up per journal while `/accessibility/<slug>`
breaks it out by issue and article.

The hash is what makes a stored result evidence rather than a claim. A run
whose hash no longer matches the file is reported as taken against an older
version and counted as unanswered, never as a pass. A page that folded those
in would read better the longer nobody refreshed it, which is the shape of
failure this whole document is about: the numbers would improve on their own
and nothing would show why.

Three states sit beside the result and each is kept apart from it. An article
with no rendered galley owes a render, not a conformance failure. A check that
has never run is not a pass. A validator missing from PATH records a warning,
because verapdf absent is not the galley failing and either verdict would be a
claim nothing checked.

Run over Writing Spaces, one pass of the corpus lint route recorded 1,888
findings across 118 runs, 16 checks per article, and the journal reads 7 clean,
102 with warnings and 9 failing. verapdf and pa11y read 0 of 118 answered,
because neither has ever been run against this archive; that is the honest
number and it is the one the page was built to make visible.

What remains is the ACR itself. The register now holds dated, hash-tied
results, and nothing yet renders them as a conformance report against the
WCAG criteria a buyer asks about.

### 3.4 Nothing could assess content Graphion did not ingest (fixed)

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
did not exist was a mode that reads without writing and reports instead of
ingesting.

`assess.py` is that mode. `python assess.py <folder>` reports, per file, the
conformance it arrives with (tagged, declared PDF/UA part, `dc:title` in XMP,
`/Lang`), the work remediation would have to produce (figures still owing a
description, pages that are scans and need OCR first, ruled tables under
`--deep`, cover pages, clipped ink, link annotations that cannot reach a tag,
characters no reader can read), and a folder summary. It writes nothing: no
article directory, no database row, no file beside the PDF, which is the
whole point of pointing it at an archive before any agreement exists.

Two things it does are worth stating to a journal, because they are what
separates this from a scan that returns a score.

It tells work already done from work still owed. A tagged PDF states how many
figure elements it holds and how many carry a description, so a journal is
not quoted for its own back catalogue. Where there is no structure tree the
embedded rasters are the fallback, and where the two readings disagree both
numbers are printed rather than resolved into one.

It reports what it cannot know. How many figures carry text as a picture is
not in any total, and the summary says so, because that number is the
difference between an archive that is described and one that satisfies WCAG
1.4.5 and nothing but looking settles it.

Run over the Writing Spaces archive it reads the legacy `source.pdf` files
correctly: no PDF/UA declaration, no `dc:title`, no document language, the
series cover page ahead of the text, and on one chapter 88 characters across
three pages that the page draws and then clips away.

What is still missing from §3.3 is the other half: these readings are not
persisted, dated or tied to a content hash, so the pass answers "where does
this stand today" and cannot yet answer "what changed since the last run."

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

**Fixed, and the premise above was half wrong.** Pandoc 3.11 does write
some of it: `accessMode: textual`, `accessModeSufficient: textual`,
`accessibilityFeature: alternativeText, readingOrder, structuralNavigation,
tableOfContents` and `accessibilityHazard: none`, the same block for every
file it converts. Two of those are claims about content it has not read.
`alternativeText` is asserted whether or not a figure carries a
description, and `accessModeSufficient: textual` tells a reader who cannot
see the pictures that they are missing nothing. A false accessibility claim
is worse than a missing one, because the reader acts on it.

`epub_a11y.py` replaces that block with what the article can actually say,
reading the counts from `lint` so the EPUB and the accessibility page
cannot drift apart. It adds `accessibilitySummary`, which Pandoc does not
write and a catalogue prints verbatim, and it writes `dcterms:conformsTo`
with `a11y:certifiedBy` only where the article's checks bear the claim.
Over Writing Spaces that is 78 chapters claiming WCAG 2.1 AA conformance
and 37 withholding it, every one of the 37 because it sets words as a
picture, which is a Level AA failure however well the figure is described.

Pandoc's `--epub-metadata` could not carry any of it: the `<meta property>`
elements in that file are dropped and the defaults written instead, so the
package document is edited after the fact and the uncompressed `mimetype`
entry put back first.

Rendering an EPUB also turned up that it had never carried its figures.
Pandoc resolves a relative resource path against the working directory
rather than against the file it is reading, so `assets/figure-...` found
nothing and every image was dropped with a warning on stderr. One chapter
went from 22 KB and no pictures to 229 KB and five. The HTML galley never
showed this, because it sits in the article directory and a browser
resolves the same path for it.

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

- ~~A table for check results: which check, which article, which version,~~
  ~~what level, when.~~ Done: `check_runs` and `register.py`. It is a new
  table in `db.py`'s `SCHEMA`, not a column added in `_apply_migrations()`,
  which is what the migration rule in `CLAUDE.md` covers.
- ~~Record `verapdf` and `pa11y` runs the same way, including that they were~~
  ~~not run and why.~~ Done, and a tool that could not run records a warning
  rather than a verdict.
- ~~One page per journal that answers "where does this stand".~~ Done:
  `/accessibility` per journal, `/accessibility/<slug>` broken out by issue
  and article, with a corpus route that records lint and the galley
  declaration for every article in one pass.
- ~~Record the PDF/UA fallback as a check result rather than only a log~~
  ~~line.~~ Done, by reading the galley rather than by catching the compile:
  `register.record_pdfua()` asks `article.pdf` what it declares about its own
  conformance, through `assess.read_declaration()`. Five lines go on record
  per galley (tagged, the PDF/UA identifier, `dc:title` in XMP,
  `/DisplayDocTitle`, `/Lang`) and a `teacher-resources.pdf` is read into the
  same run. Reading the artifact answers for a galley rendered long before
  any of this existed, which is how the archive could be answered for without
  re-rendering 115 chapters, and it catches the shortfall however it arrived
  rather than only where this app did the compiling. What it cannot say is
  why; the render log still holds the reason Typst gave. All 115 rendered
  galleys declare all five, so nothing in the series is currently shipping
  through the fallback.
- ~~The per-journal page counts articles by check, not the units that cost~~
  ~~time.~~ Done. `lint.LintResult` carries `units`, the count behind its
  summary; `register` stores it beside the finding and `Rollup.work` totals
  it. Writing Spaces comes to 119 units outstanding: 115 figures carrying
  text as a picture, 2 whose alt text says only that they are undescribed,
  and 2 the prose refers to and the galley does not hold, against 201
  figures described by hand. Only an article whose lint run is current is
  counted, so the number cannot drift the flattering way while nobody
  re-runs anything, and `Work.note()` carries the coverage beside it.
  Tables are still not counted: `assess.py` can count them in a PDF, and
  nothing counts them in an article.
- ~~verapdf and pa11y have never run against this archive, so two of the~~
  ~~four columns read 0 of 118.~~ Half done: `validate_galleys.py` runs both
  over a journal and records each through `register`, with `--skip-current`
  so a second pass is cheap and an interrupted one resumes. Neither tool is
  installed here yet, so the columns are still empty; the runner refuses to
  start without them rather than writing a row that answers nothing.
- Still to do: an issue is a heading on the journal page rather than a route
  of its own, so there is no per-issue permalink to hand anyone.

This is the piece everything else depends on. It converts the per-article
checks into the thing a journal and an ACR both need, which is a dated,
aggregate statement with the shortfalls named.

### Stage 3: the assessment (about a week)

A read-only pass over content Graphion did not produce, so a journal can see
the size of the job before commissioning it.

- ~~Point it at a folder of PDFs. It writes nothing.~~ Done: `assess.py`.
- ~~Reuse `pdf_ingest`'s readers to count what drives the work~~ Done:
  figures, figures already described, image-only pages, clipped ink, cover
  pages, untagged link annotations, unreadable characters, and tables under
  `--deep`.
- ~~A per-item statement and an aggregate~~ Done, denominated in the units
  that cost time, with what cannot be read off the page named rather than
  left out of the total.
- Still to do: a journal's HTML, which this does not touch at all.
- Still to do: run `verapdf` over their existing PDFs and `pa11y` over their
  existing HTML, and report what is already there rather than assuming
  nothing is. `validators.py` wraps both; neither is wired into this pass,
  so what it reports about conformance is what the file declares rather than
  what a checker confirms, and it says so.
- Still to do: symbol-font pages, and articles whose structure had to be
  inferred rather than read. Both are knowable and neither is counted yet.

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

### Then: the evidence pack (done)

~~Generate the ACR from the register rather than typing it.~~ `acr.py` and
`/accessibility/<slug>/acr`. All 50 WCAG 2.1 Level A and AA criteria, each
with a support level derived from the register, the checks that back it
named on the row, and the date stamped.

Over Writing Spaces it comes out 11 Supports, 2 Partially Supports, 23 Not
Applicable and 14 Not Evaluated. The two shortfalls are the two this
document has been about: 1.1.1 at 117 of 118 and 1.4.5 at 81 of 118, which
is the images-of-text list.

Three rules decide every row, and each is there because the opposite is the
easy mistake. A criterion with no check behind it reads Not Evaluated and
never Supports, which is 14 of the 50 and is the honest shape of a generated
report; the rows that do carry a level carry a named check with them. Not
Applicable is a claim too, so it is read off the content (no media, no
forms, no scripts in any article) rather than assumed, and a journal whose
articles could not be read makes no applicability claims at all. And a level
is derived only from articles the register can currently speak for, so a run
taken against content that has since moved stops counting and the row says
how many it could not reach.

2.4.1 and 2.4.7 are backed by the template bundle rather than by a per
article run, through the same predicates `tests/test_template_bundles.py`
uses, so the report cannot claim a criterion that test would fail on.

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
