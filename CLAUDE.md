# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this is

Graphion is a single-editor publishing workstation for scholarly journals.
Markdown source in; accessible HTML, tagged PDF, EPUB, JATS XML, and CrossRef
deposit XML out. Flask + SQLite + Pandoc + Typst. Originally built for
*Literacy in Composition Studies* (LiCS), now multi-journal.

Read these before making structural changes; do not duplicate their content here:

- `README.md` for the product overview, install, and output formats.
- `docs/help/11-developers.md` for the full architecture walkthrough, module map,
  pipeline stages, and step-by-step recipes (new output format, new lint check,
  new cleanup pass, new journal).
- `docs/audit-and-roadmap.md` for what is planned next.
- `docs/deployment.md` for the Fly.io deployment, the volume layout, backups,
  and the login hardening.

## Running it

```bash
pip install -r requirements.txt
python seed.py     # first run only; prompts for admin username + password
python app.py      # http://127.0.0.1:5050
```

Tests (767 functions, 822 cases once the parametrized ones expand: 142 in
`test_pdf_ingest.py`, 96 in `test_cleanups.py`, 64 in `test_assess.py`,
50 in `test_lint.py`, 46 in `test_ingest_volume.py`, 38 in
`test_describe.py`, 36 in `test_register.py`, 23 in
`test_stated_headings.py`, 14 in `test_structure.py`,
29 in `test_teacher_resources.py`,
29 in `test_metadata_roundtrip.py`, 26 in `test_pdf_tags.py`,
24 in `test_math_alt.py`,
18 in `test_acr.py`, 14 in `test_epub_a11y.py`,
34 in `test_template_bundles.py`, 12 in `test_validate_galleys.py`,
9 in `test_pdf_ua.py`, 8 in `test_accessibility_routes.py`,
37 in `test_reading_order.py`,
8 in `test_heading_levels.py`, 7 in `test_fig_alt.py`,
6 in `test_standalone_html.py`,
5 in `test_validators.py`,
4 in `test_journal_filter.py`, 3 in `test_preprocessors.py`). Most of the suite
runs without Pandoc; `test_journal_filter.py`, `test_fig_alt.py` and
`test_heading_levels.py` need it, and `test_math_alt.py` needs it for the
filter round trip alone. All skip where it is absent. `test_assess.py` runs verapdf and pa11y where they
are on PATH and says less where they are not, which is how the no-write
contract gets tested against a real subprocess:

```bash
python -m pytest tests/ -q
```

End-to-end pipeline check during development:

```bash
python smoketest.py
```

## Fresh environment checklist

`data/graphion.db` and every rendered artifact under `content/` are gitignored,
so a clean clone has no database and no galleys. Before anything will run:

1. `pip install -r requirements.txt`
2. **Pandoc 3+ must be on PATH.** It is not a pip dependency. Without it, ingest
   and every render path fails. Override the binary with `PANDOC_PATH`.
3. `python seed.py` to create `data/graphion.db`, the LiCS journal row, and an
   admin user.

Typst arrives through `typst-py` (pip), so it needs no separate install.
LibreOffice, Tesseract, verapdf, and pa11y are optional and only gate optional
features; see "Optional dependencies" below.

Do not assume a sandbox or CI runner has Pandoc. Check before writing code that
depends on a render succeeding.

## Conventions that are easy to violate

**No em-dashes in app-generated prose.** UI copy, log entries, flash messages,
and status strings use semicolons, colons, parentheses, or commas instead. This
is a deliberate house style; treat it as a lint rule when writing any
user-visible string.

**Filesystem-first.** Article and issue content lives on disk under `content/`.
SQLite indexes it; SQLite does not own it. The layout is meant to stay legible
to a successor editor after this app is gone. Never move canonical content into
the database.

**Migrations are additive only.** Schema changes go in `db.py::_apply_migrations()`
as new entries appended to the bottom of the `additions` dict. Never drop,
rename, or reorder a column. The function is idempotent and skips columns that
already exist.

**No ORM.** Raw `sqlite3` with a `Row` factory, through the `cursor()`
contextmanager and the `query_one` / `query_all` / `execute` helpers in `db.py`.

**No JS framework.** Vanilla JS. ProseMirror and CodeMirror load as ESM from CDN.

**Cleanup passes are pure and idempotent.** Every Stage 2 pass in `cleanups.py`
has the signature `(text: str, log: CleanupLog) -> str`, records its work via
`log.record(name, count)` (an optional `note=` argument exists), and is
registered in `DEFAULT_PASSES` (`cleanups.py:1587`). Running the pipeline twice
must produce identical output.
Any new pass needs a unit test in `tests/test_cleanups.py` with at least one
input/output pair plus an idempotence assertion.

Two ways a pass goes wrong are worth knowing, because `unfragment_works_cited`
did both. It merges a paragraph in the Works Cited into the entry above it
unless the paragraph looks like a new entry, and the first row of a pipe table
does not look like one, so a table that came to rest after the Works Cited was
joined to the last citation: Pandoc then read the citation as the table's
header row and printed it inside a cell, leaving the Works Cited one entry
short. The stop pattern has to name everything that ends the section, tables
and figures included. And the heading pattern ends `\s*$`, which takes the
blank line after the heading with it, so the reassembly below put a fresh one
back and the pass gained a line on every run. An idempotence assertion written
against the shape the pass actually meets is what catches that; one written
against a two-entry bibliography does not.

**`run_cleanups()` is not the same thing, and it is not idempotent.** The
passes are pure; the function around them rebuilds `article.md` from
`article-raw.md`, so it discards everything written to the front matter after
the first run: the volume facts `ingest_volume.py` stamps in, and any metadata
an editor has typed. Every caller re-applies that itself. The re-clean route in
`app.py` reads the front matter, runs the cleanups, and writes the metadata back
(`app.py:2104`); `ingest_volume.py` is safe only because it enriches after
cleaning, not before. Re-running it over already-ingested articles reverts them,
and the only thing that gets the metadata back is `.versions/`.

**Alt text has the same exposure and is carried, not re-applied.** A
description an editor wrote lives in the body, so a second ingest rewrites it
away exactly as the front matter is, and nothing above the pipeline holds a
copy. Re-ingesting volume 6 chapter 15 to pick up a caption fix replaced all
seven of its descriptions with machine text, which is the one thing in a
galley that cannot be regenerated: a caption says what a figure is called and
alt text says what is in it, and only the first of those is on the page. 201
of the 203 figures across 50 chapters of the Writing Spaces archive are
described by hand; the figure read 200 for as long as the pattern below could
not see a description holding a bracket. `conversion.carry_alt_text()` matches them back by asset path, which is
stable because the filenames are built from the page the raster sits on, and
both `ingest_pdf` and `run_cleanups` call it before they write. An
`undescribed_alt` placeholder is not carried, so a run that has since found a
caption may improve on it and `lint.check_alt_text` goes on counting what is
still owed. Any new path that rebuilds the body has to call it too.

Two things about that match are easy to get wrong, and the archive holds
one of each. The alt is read with a lazy pattern rather than a class
excluding `]`, because a description may carry a bracket of its own:
`the-complexity-of-simplicity` describes a photograph as "labelled
[desk]". A class stopping at the first `]` does not match such an image
at all, so the carry reads no description off it and writes none onto it,
saying nothing either way; `lint._IMAGE_RE` already spells it lazily. And
a caption that footnotes its source hands the next run an alt ending
`[^5]`, which is what triggered that and is wrong by itself: alt text is
read aloud with no way to reach a note, and the marker is a second
reference to one the caption already carries, which Pandoc answers by
setting the note twice. `caption_alt_text` strips a footnote reference and
only that, since `[desk]` is a description's own bracket.

**A description can be in either slot, and one function knows which.** Use
`conversion._carried_description()`; do not write the regex. A figure that
has been through `pair_figure_captions` keeps the printed caption in the
bracket and the description in `fig-alt`, so a reader that looks only at the
bracket counts captions as descriptions and misses the placeholders beside
them. That one-line reader has been written three times in this codebase and
been wrong every time: it is what let the original bracket defect through,
what had `verify_all.py` reporting 203 descriptions and 1 placeholder where
the truth was 201 and 3, and what reported three descriptions altered during
the figure-placement work when they had merely changed slots. It looks
obvious and it is wrong for exactly the figures that have captions.
`lint.check_alt_text` calls it rather than matching the bracket itself,
which is the difference between reporting a description as still owed and
reporting one that has already been written into the other slot; the archive
holds no figure in that shape today, so no run would have caught it and
`test_both_slots_are_read_the_same_way` is what holds it instead.

At the time of writing the archive holds 203 figures across 50 chapters, 201
of them described by hand and 2 still carrying a placeholder.
`_carried_description` is what that was counted with, and the number now
comes off `register`'s work table rather than out of a one-off script, so it
is a reading anybody can repeat.

**A figure is read one way and written one way, and `describe.py` is the
reason that now matters.** The queue takes a figure's state from
`lint.figure_state` and writes a description with
`conversion.with_description`, keeping no reading of its own. Two readings of
one figure is the failure with no symptom: the register reports a description
as owed, the queue never shows the figure, nobody writes it, and where that
surfaces is a reader hearing nothing. `figure_state` is `check_alt_text`'s own
loop lifted out, so the two cannot drift; the four states are exhaustive and
disjoint and `lint.OWED` names the three that are work.

Why the queue had to exist is in the numbers. 201 of the archive's 203
descriptions were written in a text editor, because `article_figures` could
not see the figures: it matches an image on a line of its own, and PDF ingest
writes a figure and the caption printed under it as one paragraph joined by a
hard line break, so the trailing backslash put every reconstructed figure
outside the pattern. 34 of 204 images matched and 38 of the 51 articles
holding figures showed an empty page. The caption group was also a class
excluding `]`, which drops a description carrying a bracket, for the reason
`_BODY_IMAGE_RE` is lazy. `_rewrite` has to put the hard break back, or the
caption parts from the figure it belongs to. The two pages write different
slots on purpose now: `article_figures` owns the bracket and the `#fig:`
label, the queue owns the description, and only the queue knows which slot a
given figure keeps one in.

`lint.printed_caption` is the caption an editor sees beside the field, and it
reads the label through `conversion._CAPTION_START_RE`, which knows all three
of this series' abbreviations. Matching only "Figure 1" lost 13 of the
archive's 167 captions, twice over: `check_alt_text` could not see that the
alt text was still the printed caption, and the queue had nothing to put on
the screen. `describe.caption_of` adds the one case that is not a line on the
page at all, a figure through `pair_figure_captions`, where Pandoc reads the
bracket as the caption; saying the page printed none there hides the caption
in the one slot the editor is not writing in. 168 of 203 figures have a
caption to show.

**And until `filters/fig-alt.lua` existed, the description in that slot
reached no galley at all.** Pandoc 3.11 writes a `fig-alt` attribute into
HTML as `data-fig-alt`, which no assistive technology reads, and its Typst
writer drops it, so every writer took the alt text from the bracket. On a
figure through `pair_figure_captions` the bracket is the printed caption,
so the HTML, EPUB and PDF galleys all published the caption as the alt
text, with `<figcaption aria-hidden="true">` hiding the visible caption
because it duplicated it: a reader heard what the figure was called, once,
and never what was in it. `an-introduction-to-and-strategies-for-multimodal-composing`
is the one article in the archive in that shape, and its `article.pdf`
carries the caption in the `/Alt` of its eighth figure to this day. It was
about to stop being rare, because the description queue writes `fig-alt`
for every paired figure.

The filter moves the attribute's value into the image's own inlines, which
is what every writer turns into alt text, and leaves the Figure's caption
alone, which is what becomes the `<figcaption>` or the printed caption.
Pandoc then drops the `aria-hidden` by itself, since the two no longer say
the same thing. It is app level beside `math-alt.lua` by the same test: how
a caption is set is a journal's design and whether a figure can be read
aloud is not. Every path that renders Markdown through Pandoc needs it, so
`_fig_alt_filter_args()` is called from `render_html`, `render_pdf`,
`render_epub` and `_md_to_typst_fragment`. An empty attribute is dropped
and declines rather than writing an empty alt, which would cost the galley
its conformance.

**A description is prose typed into a web form and it lands in Markdown.** A
newline closes the image and leaves the rest standing in the body as a
paragraph, and `](` closes the link early. Neither fails a check: the words
are all there and the galley renders. `conversion._single_line` collapses the
whitespace and spaces the `](` apart. Both substitutions read the same aloud,
which is the test any of them has to pass; the attribute slot also turns a
quotation mark and a closing brace into something that cannot end it.

**An empty `images-of-text` is a record and a missing one is not.** Absent
means nobody has looked at the chapter's figures; empty means somebody looked
and found none carrying text as a picture. `conversion._KEEP_WHEN_EMPTY` is
why `write_article_metadata` keeps that one empty field where it drops every
other, `carry_editor_fields` carries it through a re-ingest, and
`check_images_of_text` reads the difference and counts
`figures-judged-for-text` beside it so the rollup can say how much of the zero
is an open question. Collapsing the two leaves a number nobody can read, and
it leaves the lane unfinishable for a chapter whose honest answer is none: it
is the same hole `register.UNRUN` exists to keep out of the register, where no
is a finding and nobody asked is not. 37 of the 50 chapters holding figures
have an answer on record.

Three fields in the front matter have that exposure too, and
`conversion.carry_editor_fields()` carries them for the same reason, from
`ingest_pdf`, so they ride through inside `article-raw.md` and survive the
rebuild. `images-of-text` is the costliest: the list is kept by hand
because nothing can tell a photograph of a document from a photograph of
anything else without looking, and losing it fails no check and changes no
galley, so the chapter simply reads as one with no images of text and
`lint.check_images_of_text` warns about nothing. `teacher-resources` decides
whether the chapter renders as two galleys, which is a property of how the
piece is written rather than anything the page states. `math-alt` is what an
equation says aloud, and it is the same shape again: a lost one leaves the
galley conformant and a reader hearing that there is a formula rather than
hearing the formula. The volume facts are
deliberately not carried: `ingest_volume.py` stamps those after cleaning, so
carrying them here would let a stale value look like a recovered one, and
the licence is the field in this archive that least tolerates being rounded
off. Reading the front matter before a re-ingest and writing it back is what
a caller has to do for those; `ingest_volume.py` re-reads at line 365, after
`run_cleanups`, so what it re-applies is whatever ingest produced.

**Lint checks** follow the same shape in `lint.py`: return `_ok(...)` or
`_warn(...)`, then register in `DEFAULT_CHECKS` (`lint.py:614`).

**`assess.py` answers the question that comes before ingest, and it writes
nothing.** Every check in `lint.py` takes an article row and reads
`article.md`, so all of them run on content Graphion already holds. Taking
content in is `ingest_pdf`, which is slow and destructive and the wrong
thing to point at a stranger's back catalogue, so what a journal asks first,
which is what remediating its archive would cost, could not be answered
without first committing to the archive. `assess.py` reads instead: no
article directory, no database row, no file beside the PDF. A run over a
folder someone sent leaves the folder as it was, and
`test_assessing_a_folder_leaves_it_exactly_as_it_was` is what holds that.

It reports in three registers on purpose. The conformance a PDF arrives
with is a fact the file states, read off the catalog and the XMP. What a
checker makes of that statement is a second fact and not the same one, so
`--validate` runs verapdf over the PDFs and pa11y over any HTML beside
them, and `Assessment.contradicted` is the case to read first: a file that
declares PDF/UA-1 and does not pass it has already been through somebody's
pipeline, so what it is short of is usually narrow and nobody has been
told. And what remediation would have to produce is a count of work,
reported with the reasoning attached so the number can be checked. What it
cannot know is reported too, because nothing can tell a photograph of a
document from a photograph of anything else, and `images-of-text` is the
number that decides whether an archive is finished.

Three things keep the checker register from saying more than it found.
A verdict is read off `validationResult[0].compliant` and not off the exit
code, because verapdf exits non-zero both for a file that does not comply
and for one it could not process, and only the first of those is about the
document. A tool that is not on PATH leaves the verdict None, which is
never counted either way; `validate_galleys.py` refuses to start in that
case rather than recording it, because a register row is the newest answer
for its kind and a non-answer there would bury a real one, and nothing here
is stored so there is nothing to bury. And a failed-check count is a size,
not a quantity of work: one plain typeset chapter of this archive fails
1,462 checks across 11 rules, of which 727 are runs of text with no
language and 678 are content neither tagged nor marked as an artifact, and
tagging the document answers both at once. The rules are carried, capped at
`MAX_FAILED_CLAUSES`, and the instances stay beside each one rather than
being summed anywhere.

Both tools write their report to stdout, which is what lets them be called
from a pass that leaves the folder alone;
`test_assessing_a_folder_leaves_it_exactly_as_it_was` runs with them on as
well as off, because a subprocess is where a file would appear beside the
one it read.

**`assess.read_html` reads a page the way `assess_pdf` reads a PDF**, and
reading is not behind `--validate`, because it costs what reading a file
costs. HTML states itself more plainly: an `<img>` either carries an `alt`
or it does not, so there is no structure tree to disagree with a raster
count and these numbers are exact where the PDF's are a reading. The
uncertainty moves rather than going away. A figure set as a CSS background
is not in the markup at all, so an archive that sets its figures that way
reads here as one with no figures, and whether the words in a picture are
words is as unreadable here as it is there.

**A table that is a page layout owes no headers.** Three chapters here
reproduce an annotated draft, the essay in one column and a reviewer's
margin balloons in the other, drawn as ruled boxes of live type.
`find_page_tables` reads those boxes as tables on purpose, because that is
what stops the draft and the comments interleaving into each other line by
line, and `is_bare_table_label` exists because volume 1 chapter 6 prints a
bare "Fig 2" over each box. So 24 of the archive's 65 rendered tables carry
no header cell, and reporting them as a 1.3.1 shortfall quotes a journal
for naming columns that are not columns. `assess._is_layout_table` reads a
declaration first and the cells second, the way `_is_decorative` reads an
image: measured over those 65, the 41 with a header cell have a longest
cell of 124 characters at the median and 1,419 at the most, and the 24 with
none have a longest cell of 673 at the least, so `PROSE_CELL` sits at 300
in the gap. The inference is only reached where there is no header at all.

The remedy an audit would name is not available here, and that is worth
knowing before somebody tries it again. `role="presentation"` on the table
is what drops the semantics a screen reader announces, and a Lua filter
emits it cleanly, but pa11y then fails all three chapters on WCAG F92,
"role is presentation but contains child elements with semantic meaning",
and it goes on failing with the `<colgroup>` suppressed, because `<tbody>`,
`<tr>` and `<td>` are the remaining children. ARIA says the role propagates
to a table's required owned elements and the screen readers honour it, so
this is the checker being stricter than the spec; the point is that the
galleys cannot carry the fix and keep a clean pa11y run, and which of those
to serve is an editor's call. The alternative is to stop emitting a table
for these at all, which changes `article.md` for three chapters and loses
the two-column arrangement the book prints.

Six states, and two of them are claims rather than omissions, so neither
counts as work. `alt=""` says the image carries nothing a reader needs,
which is right for a rule and wrong for a figure, and an archive that
emptied every alt to quiet a checker looks identical to a described one on
a count of failures alone. And an alt that is word for word the caption
beside it can have got there either way round: Pandoc makes a `<figure>`
of a lone image and uses its alt as the `<figcaption>`, which is how 31 of
this archive's own hand-written descriptions appear twice on the page.
Counting those as owed would quote a journal for work it has already paid
for. The label is what separates the two, since a caption names a figure
and carries its number, and `lint.looks_like_a_caption` is the one place
that test lives, as `lint.alt_is_caption` is the one place the window for
comparing an alt with a caption lives.

**A symbol font is counted in fonts, not in characters.**
`assess._page_symbol_fonts` finds them two ways and both are needed. A
family `pdf_ingest.symbol_family` knows catches a run that lands on
ordinary punctuation, which no codepoint test can see: a Wingdings open
circle extracts as an opening brace. A character in the private use area
catches a font nobody here has seen, since that codepoint is unreadable
whatever set it. The reading is asked of `symbol_family` rather than of
`_SYMBOL_FAMILIES` behind it, for the reason `_carried_description` is one
function, and `page.chars` hands back more than one character for a
ligature, so a codepoint test written for one raises on the first `fi` it
meets.

What is reported is the font, because only the font knows which picture
sits at which code and the font name is gone by Stage 2, so an unmapped
family is one reading somebody does off the page and writes into
`SYMBOL_FONT_CHARS` once, whether it sets nine characters or nine hundred.
Reporting the characters as work would be the inflation a failed-check
count already threatened above. Over this series 13 of 118 chapters set
symbol type on 21 pages in two families, both already translated, and 28
of those characters landed in the private use area.

**A structure tree is what a reconstruction could be checked against, and
`structure.py` is what reads one.** All 118 originals here carry a tree,
which is why counting that one exists answers nothing; 101 carry one that
reaches the text, at a median of 97.8% of the characters, and the other 17
tag the publisher's cover page and leave the chapter alone.
`Outline.usable` gates on that coverage rather than on existence, and
`coverage` is None where no text was read, because a zero there would be a
number reported for a reading that never happened.

**The RoleMap throws the headings away, and the file still holds them.**
InDesign exports a style that has to map two ways twice, once to its real
type and once flattened to `/P`, and the document uses the flattened one,
so `Header_A` maps to `/P` while `Header_A_1` maps to `/H2`. Applying the
RoleMap faithfully reads a chapter as having no headings at all, which is
the shape 18 of these files are in. `structure.heading_levels()` pairs a
flattened style with its numbered twin and reads the level back off the
file's own map; a name that merely ends in a number is not a twin, since
promoting `Sidebar` because `Sidebar_2` exists would invent a level. It is
the discipline `learn_layout` already follows: learned per document, never
hardcoded.

What that measured is the reason to read a tree at all. Over the 39
chapters whose tree reaches the text and names headings, **262 of 784
stated headings were missing from `article.md`**, and H5 was gone almost
entirely, 90 of 92, because that level is set at body size in italic and
`classify` read it as emphasis inside a paragraph. Ingest invented
nothing; it lost depth. `introduction-to-primary-research` states 48
headings and published 13. Every galley involved is PDF/UA-1 and
pa11y-clean, because conformance asks that a heading be marked up
correctly and not that a document keep its headings, which is why nothing
had reported it.

**So ingest reads the tree where it reaches the text.**
`pdf_ingest.apply_stated_headings` marks a line from the file's own
heading elements and `classify` lets that level win, which is the point:
size and position are exactly what miss `Header_B`. The join is the
marked content id and nothing else, so `Line` carries the ids its
characters sit in; matching on how a line looks would be the same guess
again. `extract(read_structure=False)` reads a file the way this module
read every file before, which is what the comparison was run with.

Four things that had to be got right, each of which is a test.

The marking happens **after** `strip_furniture`, because a file can call
its running heads a heading level and mean it: 21 of these originals map a
`Running_Headers` style to a heading, so the author's name and the folio
are stated headings. The furniture rule still decides what is furniture.

A level is the **book's**, where the chapter title is the top and the
galley prints that from the front matter, so `blocks_to_markdown` shifts
the shallowest level left in the body down to one. Volume 6 calls its
section heads H2; without the shift every one of them renders a level
below the title with nothing in between, and the galley's own template
already puts a body `#` at `<h2>`.

Emphasis wrapping the whole of a stated head comes off, through the
`unemphasize` the captions already use, because volume 6 names its fourth
level `Header_D_Italics` and that is how the page sets a level rather
than something a reader is meant to hear.

And two heads in a row no longer merge where the levels differ. That
merge is older than all of this and loses a chapter a heading; with
nothing stated both sides are None and it behaves as it always did.

The level rides in the block kind (`head`, `head2`, `head3`) rather than
in a third field, so the pair `assemble` has always returned is the pair
it still returns and every test that builds blocks still builds them.
`head_level()` is the one reader of that. Over fifteen sampled chapters
the heading count goes from 136 to 267 against 337 stated; what is still
short is the chapter title and the byline, which belong in the front
matter, and anything a cover page carried.

One walker, in `structure.walk`. `assess._read_structure` counts figures
and headings off its elements rather than walking the tree a second time,
for the reason `_carried_description` is one function; the two readings
agreed on this archive's figure counts before they were collapsed, which
is how that was checked rather than assumed.

**Where a structure tree exists, it decides, and the obvious subtraction is
wrong for exactly the files that have one.** A tagged PDF states how many
`/Figure` elements it holds and how many carry an `/Alt`, so what is owed is
the difference between those two. Taking the raster count as the base
instead looks equivalent: it is not, because the two readings count
different things. Volume 2's `critical-thinking-in-college-writing` tags six
figures, describes one, and embeds a single raster that clears the size
floor, the other five being vector art or too small; read the wrong way
round that chapter owes nothing, read from the tree it owes five, and five
is what the page shows. This was found by running the pass over the
archive rather than over its fixtures, which is the only way it could
have been. The raster count stays as the fallback for an untagged file,
which states nothing, and the two counts are both reported when they
disagree rather than silently resolved.

**`_may_clip` is a prefilter and not a determination.** It matches the least
a page must contain for the clip operator to be there at all, which over
this series is 197 pages against the 15 that actually clip, so reporting its
hits as clipped ink is wrong thirteen times in fourteen. Call
`pdf_ingest.clipped_glyphs`, which runs `_may_clip` itself and spares most
pages the second parse anyway. The first version of `assess.py` reported a
Typst galley as clipping ink for want of this.

The unreadable-character count calls `lint.check_unreadable_characters`
rather than carrying its own copy of the pattern. One function knows, for
the reason `_carried_description` exists.

**`register.py` records what was checked, when, and against which bytes, and
a result that is not current does not count.** `lint.run()` rendered its
results into a page and discarded them, and the two validator reports landed
beside the galley with no date and nothing saying which version of the
article they described, so "where does this journal stand" meant opening 115
pages. The register stores each run against a sha256 of the file the check
read, and `register.standing()` compares that hash with the file now on disk.

That comparison is the feature. A stored pass whose hash no longer matches is
`stale`, not `pass`, and `Rollup` counts it under `unanswered` beside the runs
that never happened. Reporting the latest row's level instead would make the
page read better the longer nobody refreshed it, with every number wrong in
the flattering direction and nothing on the page to show it; an accessibility
conformance report built on that would be citing checks that ran before the
content moved. `Standing.settled` is the one predicate every count goes
through, and `Standing.tone` decides the colour in Python so a template cannot
quietly answer it differently.

Three more distinctions are load-bearing and each would be easy to collapse.
A run is identified by its `run_id` rather than reconstructed as the newest
row per check name, because those differ the moment the set of checks changes:
a check retired from `DEFAULT_CHECKS` is forever the newest of its name, and
would go on reporting a finding nothing is looking for. `absent` is not
`fail`, because an article with no `article.pdf` owes a render rather than a
conformance failure, and folding the two would overstate remediation and
understate what already conforms; 3 of Writing Spaces' 118 articles are in
that state. And a validator that could not run records `unrun`, which is not
an answer at all: `Standing.settled` reads the level as well as the state and
`KindRollup` counts it among the unanswered. It recorded `warn` until a
corpus pass was written, and writing one made the flaw plain. On a machine
with neither tool installed, a pass over 118 articles would have reported
every one as checked, warnings and all, with nothing having executed; the
page would have read 118 of 118 answered. That is the failure this module
exists to prevent, in the one place it was not looking for it.

**The fourth kind reads the galley instead of being handed a verdict.**
Lint, verapdf and pa11y pass their results to `register`;
`register.record_pdfua()` opens `article.pdf` itself and asks what it declares
about its own conformance, through `assess.read_declaration()`. That is the
question `_compile_typst`'s fallback used to answer in a render log and nowhere
a count could reach. Typst validates PDF/UA rather than stamping it, so one
undescribed figure or one bare equation aborts the compile; the fallback then
writes the galley unconstrained, which is how an editor keeps a galley out of
it, and what ships is readable and unconformant with a log line as its only
trace.

Reading the artifact answers more than catching the compile would. A galley
rendered before any of this existed states its conformance as plainly as one
rendered this morning, so the archive could be answered for without
re-rendering 115 chapters. And the shortfall is caught however it arrived,
which it had to be: the six issue front matters that silently lost the
standard did so for want of a title and not for want of alt text. What the
artifact cannot say is why, and the render log still holds that.

Five lines go on record per galley, and the title is two fields of which one
counts: clause 5 reads `dc:title` in the XMP packet, the Info dictionary's
`/Title` is a different entry, and the summary says so where it finds exactly
that pairing. A `teacher-resources.pdf` is read into the same run, since a
second galley that lost the standard is the same hole as the first; that
leaves the run dated to `article.pdf` alone, which is the soft edge here and
is worth more than leaving the teacher galley unread. A file pypdf cannot open
records `warn`, by the rule a validator missing from PATH already follows. Run
over the archive, all 115 rendered galleys declare all five and 66 of them
carry a teacher galley that declares them too, so nothing in this series is
currently shipping through the fallback.

`assess.read_declaration()` is that reading: `assess_pdf()` without the
page-by-page counting that follows it, so there is one reader and not two.
What a packet declares is read by `pdf_tags`, beside the code that writes
one, for the reason `_carried_description` exists.

The hash is taken by the caller, before the check runs, and passed to
`record_*`. Hashing inside the write would date the run to whenever the
writing happened, which is after the reading. It is exact for one writer and
assumes the single gunicorn worker `deploy/entrypoint.sh` configures, which is
the assumption the login limiter already makes. `record_pdfua` is the one
exception and hashes for itself, because it is also the reader and there is no
gap between the two for the bytes to move in.

`check_runs` is a new table, so it goes in `db.py`'s `SCHEMA` as
`CREATE TABLE IF NOT EXISTS`, the way `conversions` does, and not in
`_apply_migrations()`, which adds columns to tables that exist. Its
`article_id` foreign key carries `ON DELETE CASCADE` on purpose: a deleted
article has to take its recorded runs with it.

Standings are read by hashing on every page load rather than cached. Measured
over the archive that is 348 files and 61 MB for 118 articles: 0.5s of hashing
and 0.8s of lookups, four to an article, and a cache keyed on mtime would be
the weak evidence this exists to replace. Two kinds read `article.pdf`, so
`standing()` hashes each file once per call rather than once per kind. The
corpus route runs the two in-process checks, lint and the declaration:
verapdf and pa11y are subprocesses with a 120s timeout each, so a pass over
118 articles belongs in a job runner rather than in a request.

**A level says whether, and a journal asks how much first.**
`lint.LintResult` carries `units`, the count behind its summary, and
`register` stores that beside the finding so an archive can be totalled.
`Rollup.work` adds the units up; `WORK_ROWS` declares which ones a page
shows and what to call them. Over Writing Spaces it comes to 119 units
outstanding: 115 figures carrying text as a picture, 2 whose alt text says
only that they are undescribed, and 2 the prose refers to and the galley
does not hold, against 201 figures already described by hand.

Three rules hold it together. A unit name belongs to exactly one check,
because the rollup sums a name across articles and two checks both
reporting `figures` would double every figure in the archive;
`check_images_of_text` reads the same images `check_alt_text` counts and
deliberately does not count them again, and
`test_no_two_checks_claim_the_same_unit` runs every check over the same
bodies to hold that. A passing result carries its units too, or the
denominator is only the articles with something wrong with them. And only
an article whose lint run is current is totalled, by the rule the rest of
the register runs on: a work total drawn from runs taken against content
that has since moved would drift the flattering way and say nothing about
it, so `Work.note()` carries the coverage next to the number.

`units_json` is a column added to `check_runs` by `_apply_migrations()`,
which is where a column on an existing table goes; the table itself was new
and so went in `SCHEMA`. A row written before it reads back as no units
rather than as zero.

The counts were always worked out and then written into a sentence, which is
why `assess.py` read one back with a regex over `lint`'s own prose. It takes
the number off `units` now, and that was the last place in this codebase
reading a number out of its own output.

**A tool that is not installed is not a result.** `validate_galleys.py`
runs verapdf and pa11y over a journal and records each through `register`.
It is a script rather than a route because each is a subprocess with a 120
second timeout, so a pass over 118 articles is an hour at best; the corpus
route runs only the two in-process checks for the same reason.

It refuses to start where a tool is missing, and the reason is what makes
refusing cheap. A recorded run is the newest run for its kind, so a pass
with verapdf uninstalled would write "not checked" over every verdict a
real pass had left, and `register.latest_run` would hand that back as the
current answer: results that cost an hour to get, replaced by rows that
answer nothing. The two validator routes in `app.py` call `available()`
first for the same reason, since the button has the same exposure one
article at a time.

A tool that is installed and then cannot answer is a different fact and is
recorded. A galley verapdf times out on has told you something about the
galley; a laptop without verapdf has told you something about the laptop,
and only the first belongs in a register about content.

`--skip-current` leaves out an article whose run is already current, which
is what makes a second pass cheap and an interrupted one resumable. A stale
run and an `unrun` one are both back in the plan, since neither is an
answer. The report JSON lands beside the galley exactly where the
per-article button writes it, so the article page shows what the pass
found.

**Neither tool is an executable on Windows, so call the path and not the
name.** verapdf installs a `verapdf.BAT` launcher and npm writes a
`pa11y.CMD` shim. `shutil.which` finds both through PATHEXT, and
`CreateProcess` runs neither from the bare name, so
`subprocess.run(["verapdf", ...])` raises FileNotFoundError while
`verapdf_available()` says the tool is there. That pairing is the worst of
the three answers available, because the probe gates the call: the register
would have taken 115 crashes from a tool it had just confirmed was
installed. `run_verapdf` passes the path `shutil.which` returned, which
`run_pa11y` already did. Installed here at `C:/Users/jlewis2/verapdf`,
which is not on the system PATH; the shell that runs the pass has to put it
there.

**Galleys are PDF/UA-1.** `conversion._compile_typst()` compiles every PDF
with `pdf_standards` set from `config.PDF_UA_STANDARD`, which is what emits
the conformance identifier and the ViewerPreferences `/DisplayDocTitle` entry
that an accessibility audit checks for (ISO 14289-1 clause 5; WCAG 2.4.2).
Typst validates the standard rather than merely declaring it, so content that
cannot conform aborts the compile. The helper falls back to an unconstrained
render and logs why, so an editor never loses a galley to this, and
`register.record_pdfua()` reads the galley afterwards so the fallback is
counted rather than left in a log nobody totals. The usual cause is an image
with no alt text, which `lint.check_alt_text` fails on first. A bound issue is as conformant as its parts and no more, which is what
`pdf_tags.py` is for.

**An equation is the other thing Typst refuses, and it refused silently.**
A `math.equation` carrying no `alt` aborts the compile the way an undescribed
figure does, and Pandoc's Typst writer emits a bare `$...$`, so one formula
anywhere in an article sent `_compile_typst` down the fallback path above and
the galley shipped with no conformance identifier. Nothing reported it either:
`lint.check_alt_text` matches Markdown image syntax, an equation is not an
image, and the article linted clean. It had
never fired only because neither journal here had set an equation yet, so a
journal with mathematics in it would have hit this on its first article.

`filters/math-alt.lua` puts the `alt` on, by wrapping each equation in a
content block that sets it. That leaves Pandoc to write the math, which
matters: the TeX to Typst translation (`\frac{a}{b}` to `frac(a, b)`,
`\bar{x}` to `macron(x)`) is Pandoc's, and a second copy of it in a filter
would be a worse one. The filter is app level rather than per journal, unlike
the figures and journal filters beside it at the call sites, because how a
caption is set is a journal's design and whether a formula can be read aloud
is not; the accessible half of the HTML template living in one bundle is
already how this codebase learned that a per journal copy is a copy that does
not travel.

What the equation says aloud is decided in `math_alt.py`, and the filter only
emits a sentinel holding the expression hex encoded, which
`conversion._fill_math_alt` substitutes. Python owns it because
`lint.check_math_alt_text` reports the same descriptions the galley carries,
and two copies of that judgement would drift apart; hex because the sentinel
has to survive a Typst string literal and a formula is mostly backslashes and
quotation marks. Any new path that renders Markdown to Typst needs
`_math_alt_filter_args()` and `_fill_math_alt()` both, or it is back where
this started. `_md_to_typst_fragment` has them, because the issue front
matter is where this codebase has already lost conformance once without
noticing.

`speak()` reads only a vocabulary it can read one way and returns None for
everything else, which is the point of it rather than a shortfall. A formula
read half right is present and wrong in a galley that passes every audit: a
reader told "a over b over c" for a nested fraction has been told something
false, and no checker can see it. So a compound numerator carries an explicit
end marker, since the page shows a grouping that speech does not, and
anything outside the vocabulary declines whole rather than in part. The tilde
is the plainest case for leaving a symbol out: it reads "is similar to" in
geometry and "is distributed as" in statistics, the expression cannot say
which, and so it declines. An expression that declines gets
`math_alt.undescribed()`, which keeps the galley conformant and leaves
`lint.check_math_alt_text` counting what is owed, exactly as
`undescribed_alt` does for a figure whose page printed no caption.

An author's own reading always wins and is kept by hand in the article's
`math-alt` front matter, keyed by the expression as written and matched on
whitespace alone. Write the key in single-quoted YAML, where a backslash is
literal; double quotes need every one of them doubled, and getting that wrong
aborts the render with a YAML parse error rather than losing the key quietly.
It is the third entry in `CARRIED_FIELDS`, for the reason the other two are
there: nothing can derive it, and losing it fails no check and changes no
galley to look at.

The HTML, EPUB and JATS galleys need none of this. Pandoc's writers emit real
MathML with an `application/x-tex` annotation, so the filter is gated on
`FORMAT == "typst"` and a raw Typst inline in the HTML would be a
regression.

**An issue has an address.** `/accessibility/<slug>/issues/<id>` carries
the same rollup, work table and article list for one issue, and the
heading on the journal page links to it. It was a heading and nothing
else, so "volume 2 stands here" could only be said by sending somebody the
whole journal and telling them where to scroll.

`app._issue_label()` names an issue, once, because the journal page groups
its headings by that string and the issue page titles itself with it: two
copies would drift and the first thing a reader would notice is a heading
that does not match the page it opened. The three tables are macros in
`templates/_register_tables.html` for the same reason, and the register
styling moved into `static/style.css`, where it should have been before a
broken `.tally` selector survived being written into two templates.

**The conformance report is derived, so it cannot say more than the checks
found.** `acr.py` and `/accessibility/<slug>/acr` put all 50 WCAG 2.1 Level
A and AA criteria on a page with a support level against each, the checks
that back it named on the row, and the date stamped. An ACR typed by hand
is a snapshot of somebody's belief on the afternoon they wrote it and
starts drifting immediately; this one goes stale visibly, because a run
taken against content that has since changed stops counting and the
coverage drops rather than the levels quietly staying good.

Three rules decide every row and each is there because the opposite is the
easy mistake.

A criterion with no check behind it reads `Not Evaluated` and never
`Supports`. That is 14 of the 50, which is the honest shape of a generated
report rather than a shortfall in it: most of WCAG cannot be checked by a
machine, and a report that quietly filled those in would be harder to catch
than a hand-typed one because it would look systematic. The rows that do
carry a level carry a named check with them.

`Not Applicable` is a claim too, so it is made from evidence. The criteria
about captions, pointer gestures and form errors do not engage a
publication with no media, no forms and no scripts, but that is a fact
about the content, so `acr.survey()` reads it off every article's source
and a journal whose articles could not be read makes no applicability
claims at all. 2.1.1, 2.1.2 and 2.4.3 are deliberately not in that set: a
galley with no scripts still has links, and a link is functionality, so the
honest answer is that nobody has tabbed through one.

And a level is derived only from the articles the register can currently
speak for, with the count said on the row. "115 of 115 pass" under a
journal of 118 would otherwise leave a reader working out where the other
three went.

2.4.1 and 2.4.7 are backed by the template bundle rather than by a per
article run, and `tests/test_template_bundles.py` reads them through the
same predicates in `acr.py`, so the report cannot claim a criterion that
test would fail on. Over Writing Spaces the report comes out 11 Supports,
2 Partially Supports, 23 Not Applicable, 14 Not Evaluated, the two
shortfalls being 1.1.1 at 117 of 118 and 1.4.5 at 81 of 118.

**The EPUB declares what a reader can do with it, and Pandoc's version of
that is two claims it has not checked.** Pandoc 3 writes an accessibility
block into every EPUB it converts: `accessMode: textual`,
`accessModeSufficient: textual`, `accessibilityFeature: alternativeText,
readingOrder, structuralNavigation, tableOfContents`, and
`accessibilityHazard: none`. The same block every time. `alternativeText`
is asserted whether or not a single figure carries a description, and
`accessModeSufficient: textual` says a reader who cannot see the pictures
is missing nothing. For a chapter with an undescribed figure both are
false, and a false accessibility claim is worse than a missing one: it
tells a reader the book will work for them, and they find out afterwards.

`epub_a11y.describe()` works each value out from the article and
`epub_a11y.stamp()` replaces Pandoc's block rather than adding to it, so
two `accessModeSufficient` values never sit side by side contradicting each
other. The counts come from `lint`, which already works them out for the
accessibility page, so what the EPUB says and what the page reports cannot
drift. `MathML` names the markup, which Pandoc emits either way; whether a
formula also carries a reading is what the conformance claim turns on.

`dcterms:conformsTo` is written only where the article's own checks bear
it, with `a11y:certifiedBy` naming who says so. WCAG 2.1 AA includes 1.4.5,
so a chapter that sets words as a picture does not conform however well the
figure is described, and it gets the discoverability metadata, which every
publication owes, and no claim. Over Writing Spaces that is 78 claiming and
37 withholding, all 37 for 1.4.5. `accessibilitySummary` is written either
way and says what is not true as well as what is, because a catalogue
prints it verbatim.

Pandoc's `--epub-metadata` cannot carry any of this: the `<meta property>`
elements in that file are dropped and the defaults written instead. So the
package document is edited after Pandoc has written it, which means
rebuilding the zip, which means putting `mimetype` back first and
uncompressed. That is what a reading system checks before it trusts
anything else in the container, and a rewrite that deflates it produces a
file that opens nowhere while every other test passes.

**The EPUB had never carried its figures.** Pandoc resolves a relative
resource path against the working directory rather than against the file it
is reading, so a body saying `assets/figure-p007-1.jpg` found nothing and
every image was dropped with a warning on stderr. `--resource-path` set to
the article directory fixes it; one chapter went from 22 KB and no pictures
to 229 KB and five. Nothing had noticed because the EPUB renders on demand
and none had ever been rendered in this archive, and because the HTML
galley sits in the article directory, where a browser resolves the same
path correctly.

**The accessible markup belongs to the bundles, not to the journal that
got remediated.** Writing Spaces had a skip link, a `<main>` landmark,
`aria-labelledby` pointing at real headings and a licence statement; LiCS
had none of them, named its sections with `aria-label`, and had no
`:focus-visible` rule at all, so tabbing a galley showed nothing.
`new_journal.py` clones LiCS, so every journal added would have started
from the worse of the two and the remediation would have stayed where
nothing copies it.

The fix raised LiCS rather than switching which bundle is cloned, because
that also fixes the galleys LiCS is already publishing.
`tests/test_template_bundles.py` reads whatever is under
`content/journals/*/template/` and checks each one, so the contract covers
a journal added tomorrow without anybody remembering to add it. Seven of
the eight checks it held at the time would have failed on the LiCS bundle
as it stood.

**Contrast is checked there too, because pa11y cannot reach it.** Both
bundles declare their colours once as custom properties and override them
per media query, so the variables are the palette and `acr.palettes` reads
them without needing a cascade engine. pa11y does compute contrast and
backs 1.4.3 in the report, but it renders a page with default preferences,
so whatever a bundle declares for `prefers-color-scheme: dark` is exercised
by nothing: Writing Spaces carries a dark palette and a print one, and LiCS
carries neither. `text_contrast_failures` checks every palette's text
entries against `--paper` at 4.5:1 and names the palette and the entry in a
failure, so "the stylesheet is wrong" is not the whole of the report.
Measured today, LiCS reads 9.3 to 16.8 and Writing Spaces 7.0 to 18.4
light, 8.5 to 14.7 dark.

Only text is asserted on. A rule or a frame edge is left alone because
1.4.11 asks 3:1 of a meaningful graphic and a decorative hairline is
neither: LiCS sets `--rule` at about 2:1 against its paper, and reporting
that would quote a journal for a line nobody has to see. A palette entry
naming another variable is left unresolved rather than scored, by the rule
`register.UNRUN` follows.

Writing an `_MEDIA_RE` for the stylesheet is what broke `survey()` while
this was being added. `acr.py` already had one, the pattern that decides
whether a journal publishes video or audio at all, and a second definition
of that name silently replaced it, so every applicability claim about media
turned on whether the stylesheet held an `@media` block. The pattern for
the stylesheet is `_CSS_MEDIA_RE`, and
`test_content_that_does_engage_a_criterion_is_not_waved_through` is what
caught it, which is the third time a name collision has done real damage in
this codebase after `_read_images` and the one-line description reader.

Two of those checks pair the markup with the stylesheet, and that pairing
is the point of them: markup without the CSS puts a visible "Skip to the
article" link above every title, and CSS that takes it off screen with no
`:focus` rule hides it from the one reader it exists for. `aria-label` on a
section that has a visible heading is the other half: it replaces the
heading text with a second copy that can drift from the first, so a section
with a heading names itself by that heading and a footer without one keeps
`aria-label`.

Adding the licence to the LiCS template made a dormant bug live, which is
this whole item in miniature. The LiCS journal filter still walked the
whole document with the URL filter, and that filter inserts soft break
points into long URLs, so `<wbr>` went through the licence href and the
link pointed nowhere. Writing Spaces had been fixed for exactly this and
LiCS had not. Both now walk `doc.blocks`, and a Pandoc-gated test renders
each bundle and reads the hrefs back.

**A bound issue is tagged by merging, not by re-rendering.** Adding a page to
a pypdf writer copies the page. The structure tree, the `/ParentTree` that
reaches it from each page, and `/MarkInfo` all hang off the source catalog and
none of them comes with a page, so the obvious concatenation of conformant
galleys is one untagged file. Those are the four failures an audit reported
against every `issue.pdf` in this series while all 115 articles in them
passed: not tagged, no document title, no XMP metadata, link annotation not
tagged. The missing title is worth knowing about, because the old code did
set one. It set `/Title` in the Info dictionary, and clause 5 reads `dc:title`
in XMP, which a concatenation carries no trace of.
`pdf_tags.concatenate_tagged()` rebuilds both trees from the parts instead.
Each source's elements are copied with `/Pg` repointed at the page that page
became, its `/ParentTree` keys shifted past every source before it, and each
copied page's `/StructParents` shifted to match, so what the bound file
carries is the tagging Typst already validated chapter by chapter. Compiling
the whole issue as one Typst document would also have worked and is the wrong
trade: the bound issue would then be a second rendering of each chapter rather
than the one the standalone galley serves.

Four things do not survive a plain copy and each one fails silently. A
`/ParentTree` key is a per-document counter, so two sources both begin at 0
and the second overwrites the first; every page of the first then resolves
into the second's elements, which no checker sees and a screen reader reads as
the wrong paragraph. An `/OBJR` is the entry that makes a link annotation
tagged, and it names the annotation object, which the page copy replaced with
a new one; a dangling `/OBJR` is itself a conformance error, so one that
cannot be repointed is dropped and counted rather than written out.
Repointing it is only half of a tagged link, and having only that half is
the quietest shape in this file: a checker satisfies ISO 32000 7.18.5 from
the annotation inwards, through its own `/StructParent` into the parent tree,
expecting the element that holds the `/OBJR`. `/StructParent` is the same
per-document counter as a page's `/StructParents`, so shifting pages and not
annotations leaves every link indexing whichever element its own chapter
happened to number. All 61 links in the series bound that way: the `/OBJR`
resolved, the merge counted each one tagged, and an audit reported every one
untagged, which is how `issue.pdf` still failed the fourth of the four
failures above while the report said PDF/UA-1. The count of tagged
annotations cannot stand in for the round trip, so the merge now walks it
from the annotation and `MergeReport.unresolved_annotations` names the pages.
And an
element `/ID` has to be unique across a document, while Typst numbers them per
chapter from the same origin, so each source's ids are prefixed and the
`/IDTree` is rebuilt over the prefixed names, sorted.

Before it writes, the merge follows every page's `/StructParents` back into
the tree it just built. The keys and the pages come from the same offsets, so
they agree by construction, and the check is there because this is the one
failure with no symptom: an unreachable page renders identically, reports
itself as tagged, and reaches a screen reader with nothing above it.
`MergeReport.unresolved_pages` numbers any that do not resolve, and
`assemble_issue` reports them.

The merge carries conformance; it cannot create it. `concatenate_tagged`
stamps `pdfuaid:part` only where every part declared it, no part arrived
untagged, no annotation was dropped, every page resolves, and every link
reaches its own tag from its annotation. A part that
falls short is named in the report `assemble_issue` passes out as
`AssemblyResult.notes` and the assemble route flashes. That gate is what
found the other half of this bug: the issue front matter set no
`document(title:)`, so `_compile_typst` fell back to an unconstrained render
for all six volumes, and nothing said so because `render_front_matter` passed
no log path. Three roman-numbered pages per issue were tagged and claimed
nothing, and no merge can claim it on their behalf. Both halves are fixed; the
front matter now sets a title and passes `log_to`, so a future fallback is on
the record.

**PDF ingest infers structure; it does not read it.** A DOCX still knows what
a paragraph is, so Pandoc can be handed the file. A PDF knows only where ink
sits, so `pdf_ingest.py` reconstructs paragraphs from the first-line indent,
heads from type size and centring, emphasis from font names, and word breaks
from a vocabulary built out of the document itself. Every one of those is a
judgement that can be wrong, so the upload route says so to the editor, and
new heuristics need a case in `tests/test_pdf_ingest.py`. The geometry is
learned per document rather than hardcoded: a series that redesigns between
volumes should degrade, not silently misread. Use pdfplumber, not PyMuPDF,
which is AGPL and would reach the whole deployed app.

**Ink a page clips away was never printed.** A content stream can set a
clipping path with `W` or `W*` and then draw past it, and what falls outside
the path does not appear on the page. pdfminer parses both operators and does
nothing with them, since `do_W` and `do_W_a` are empty method bodies, so every
clipped glyph is reported as though it were ink. Volume 1's chapter 6
reproduces draft Word pages inside ruled boxes and lets the text overflow the
box; the overflow and the prose beside it sit at baselines within pdfplumber's
3pt tolerance, so `extract_text_lines` read the two as one line and the
chapter published `IW ue sseindc etrheliys h ocpaeu tai olenssaorny`, two
texts merged character by character in x order. The same chapter published a
duplicate of several passages, the clipped overflow collected after the Works
Cited, and the bare `Fig 2` to `Fig 5` labels that Word prints over its own
text frames and the book prints nowhere.

So the question each glyph has to answer is not where it sits but whether the
page printed it, and the content stream answers that directly.
`clipped_glyphs` reads the clip with an interpreter of its own,
`drop_clipped_ink` filters the page, and `extract` calls it at the top of the
page loop and counts what it dropped into a note. Nothing is inferred from the
look of the page. The obvious reading of this defect is that the two streams
are columns to be separated by the horizontal gaps between their characters;
they are not columns, because they overlap in x, so there is no boundary to
find.

Two coarser attributions pass on that chapter and destroy others. Every glyph
of the figure carries `tag='PlacedPDF'` and no body glyph does, so taking the
union of the clips set inside each marked-content section and dropping that
section's glyphs outside it looks sound; `11Cicchino` page 11 is a ruled table
whose cells each set their own clip, the union covers only some of them, and
1,760 printed characters of the table fall outside it. Dropping anything
outside any clip on the page is worse. `antlitz--taking-flight` page 10 and
`purdy--wikipedia-is-good-for-you` page 9 set a clip for an image while no
marked-content section is open, so the whole body of each page is untagged and
outside it, which costs 1,118 and 1,614 characters of ordinary prose. Only
per-glyph attribution survives the series, and that needs the interpreter.

The reader has to get four things right, and each of them cost something in
testing. The clip is part of the graphics state and pdfminer's is not: `do_q`
and `do_Q` stack the matrix, the text state and the graphics state, so the
clip is carried in overrides of both, or a frame set for one figure goes on
clipping the rest of the page. `curpath` holds the operands as the stream
wrote them, in user space, because applying the CTM is the device's job, so
the reader applies it itself. A clip that is not a rectangle comes out too
large, since a curve contributes its control points and their box contains the
curve. And `outside_clip` asks whether the clip removes a glyph altogether
rather than whether it touches it, because a box reported a fraction of a
point past the frame it sits in is far commoner than one the frame genuinely
halves. Those last two err in the same direction on purpose: a clip read too
large is the better failure, because the ink it keeps was drawn where the page
prints nothing and costs a reader a stray character, while one read too small
drops a word that was printed.

`drop_clipped_ink` runs before `find_page_tables`, not merely before line
assembly. Volume 2's chapter 3 was carrying 71 characters of a comment balloon
that the page truncates inside a detected table, so the galley printed inside
a cell text the book does not show. That is the failure
`drop_lines_inside_tables` exists to prevent, and it is invisible for the same
reason.

The second parse roughly doubles the cost of a page, so `_may_clip` reads the
raw stream for `W` followed by a non-alphanumeric byte, which is the least a
page must contain for the operator to be there at all. It matches 197 of the
series' 1,965 pages and misses none of the 15 that clip, so nine pages in ten
skip the second reading; an ordinary chapter costs about 3% more, and chapter
6, which clips on ten pages, about 75%. Matching more than the operator only
costs a parse. Matching less would lose a page, which is why the test is on
the byte and not on `W\s+n`.

Both readings have to be of the same page for a glyph box to mean anything, so
`clipped_glyphs` compares its own glyph count with `len(page.chars)` and
returns nothing when they disagree. They never disagreed across this series,
and a page where they ever do comes through as it always did.

**The chapter does not always begin on page one.** The standalone chapter
download in volumes 1 to 3 opens on a page the bound book does not have: the
series boilerplate, the publisher's copyright page with its CIP block, and
the licence, printed above the chapter so a reader who found the chapter
alone can tell what it came from. Read as content it does real damage, and
all of it quiet. `extract_front_matter` consumes the title and byline from
that page, so the chapter's own title and byline are left in the body and the
galley prints them twice; the boilerplate lands in `abstract`, which the
template prints under an **Overview** head, with the byline running inline
inside it and the list of download sites flattened to prose; and the CIP
block arrives as a footnote. 49 of the series' chapters published that way.
`is_cover_page` wants two of its three marker groups present, because a
chapter may well discuss a Creative Commons licence and none of them prints
a CIP block to discuss, and `count_cover_pages` looks only at the first page
or two, because a cover page that is not at the front is not one. The drop
happens before `learn_layout`, so the cover's own type cannot vote on what
the body size is, and before `build_vocabulary`, so
"Cataloging-in-Publication" is never a word the chapter knows. Volumes 4 to 6
set no such page and are untouched.

**A footnote is not always numbered.** The series marks the licence note on a
chapter's opening page with an asterisk, which falls past `_NOTE_RE` and was
written out as it was read. Markdown then reads the asterisk as a list marker,
and 69 chapters printed their licence as a bulleted item in the middle of the
text. `escape_list_marker` escapes a leading bullet or numbered-list marker
on a note that is not written out as a footnote definition, which leaves the
printed text as the page set it. Where it puts the backslash matters: a
backslash escapes punctuation and nothing else, so it goes in front of a
bullet and after the digits of a number, and in front of a digit it is not
an escape at all and Pandoc prints it. The licence belongs in the body: a
published chapter prints its own terms and `should_print_license()` relies
on finding them.

**A numbered note nothing refers to is not a footnote.** Some chapters print
an endnote section headed "Note" or "Notes" at the end, and `_NOTE_RE` reads
its numbered item exactly as it reads a footnote at the foot of a page, so
`blocks_to_markdown` lifted the text out from under its own heading and
wrote it as a Markdown definition. Pandoc drops a definition nothing
references, with a warning on stderr and nothing in the document, so four
notes across volume 2 printed in neither galley: the acknowledgement in
`the-complexity-of-simplicity` crediting by name the student who
photographed the whiteboard work the chapter is built on, both of
`everything-changes`, and one of `reading-games` whose own text says it is
speaking in a footnote. Three of the four are an author crediting other
people, which is the part of a chapter a pipeline has least business
dropping. So a numbered note stays where the page put it unless something
refers to it, counted over the blocks and over the abstract as well, since
that is front matter rather than a block and a reference in it does resolve
(`12-laflen` carries one). Two of the four are footnotes whose superscript
marker was never read rather than endnotes, and there is no raised digit in
those chapters for `_superscript_runs` to find, so they are kept near where
they were printed without being reattached to a sentence. That is the same
trade as `undescribed_alt`: in the document imperfectly beats absent.

**Text set in a symbol font is not text.** A symbol font stores pictures at
ordinary character codes, so extracting a Wingdings run gives punctuation:
byte 0x7B is an open circle and arrives as `{`, byte 0x4A is a smiling face
and arrives as `J`. Others land in the private use area as U+F0xx, which is
worse, because a private use codepoint means nothing to a screen reader and
Typst validates PDF/UA rather than declaring it, so one of them aborts the
compile and the chapter ships without the conformance identifier. Only the
font knows which is which and the font name is gone by Stage 2, so
`SYMBOL_FONT_CHARS` and `translate_symbol_char()` do the substitution in
`pdf_ingest.py`, during line assembly, where it is still in hand. Every
entry was read off the page it came from; subsetted archive encodings need
not agree with a published chart. Match on the whole family after the
subset prefix, never a substring: `OpenSymbol` and `SymbolMT` decode their
bullet correctly already and must be left alone. `table.extract()` strips
the font off, so `_symbol_translations()` rebuilds the mapping from the
chars inside the table's box; a code that appears there both as symbol and
as text is left alone, since the extracted string carries no positions.
`lint.check_unreadable_characters` is the backstop for whatever a new
source brings in that the table does not know.

**Figures come out too, and the caption is the hard part.** `extract()` takes
an `assets_dir`; given one it writes every embedded raster there and places it
in the body. An image qualifies by `big_enough()`, which measures each
side against its own floor: `MIN_FIGURE_PX` for the longer, a much smaller
`MIN_FIGURE_THIN_PX` for the shorter. Testing both sides against the one
number threw away a five-stage flowchart 315 by 34, because a figure set to
the full text measure is often short and this archive's measure is about
315pt. Size rejects a rule; the furniture rule rejects a publisher's mark,
which is why relaxing the floor does not let every volume's cover thumbnail
back in. A raster is re-encoded to PNG unless its own suffix is already
a web format, and PNG has no CMYK, so `for_png()` converts a press image on
the way out. Without it PIL raises and `extract_figures`' `except` drops the
figure in silence, which is how volume 6 lost a flowchart; 50 of the series'
figures are CMYK, and only that one needed re-encoding because the rest are
JPEGs written through as bytes. Name the modes that carry alpha rather than
testing for an "A" in the mode string, since LAB has one. pypdf is asked for the rasters because it resolves the stream
filters and names the format; pdfplumber reads the captions, since the lines
are already being read there. A figure is paired with a caption by page and by
order down the page.

Three things about captions are easy to get wrong, and each cost this archive
figures. A caption is set a point smaller than the body, which is also what a
footnote is, so `classify` reads one as the other: a caption therefore has to
start its own block (`is_caption` in `assemble`) or it is appended to whatever
footnote precedes it, and it has to be emitted in place in
`blocks_to_markdown` or it is collected to the end of the chapter with the
notes. And punctuation cannot tell a caption from a reference to one, because
the archive writes all three of "Figure 4.1: ", "Figure 3.3. " and
"Figure 15.1 "; what separates them is the capital that follows, since a
caption continues with the figure's name and prose continues with a verb
("Figure 7.6 shows that"). The capital is still required but not first,
because four captions in the series name a quoted title and put a left
quotation mark there instead: `16-vankooten`'s Figures 1 and 2 both begin
with "A College Collage", `14-blakesley`'s Figure 2 and
`assessing-source-credibility`'s Figure 3 the same way. Those two figures of
`16-vankooten` were the ones that looked uncaptioned, and the cost was not
the caption but what followed from it, below. Measured over the archive, 172
captions follow their label with a capital, 4 with a quotation mark, and the
12 lines that are prose referring to a figure all continue in lower case, so
admitting the quotation mark lets none of them through. `is_table_caption`
has the same shape and the archive holds no instance of it.

The label itself is abbreviated three ways, consistently within a volume and
not across the series: volume 2 prints "Fig. 1." over all seventeen of its
captions, volume 6 prints "Fig 1.0", and the rest print "Figure 1". Matching
only the long form read volume 2 as a book that captions nothing and sent
twenty of its twenty-two figures to the undescribed pile with their
descriptions sitting in the text above them, so `_FIGURE_CAPTION_RE` takes
all three. The capital-letter test still does the work of telling a caption
from a reference, which is what keeps "Fig. 1, we see that" out.

A caption may also be set in italic, so it arrives wrapped in emphasis
and a pattern anchored at the start never sees the label. `unemphasize`
takes off wrapping that covers the whole line, and only that: emphasis
inside a caption is the caption's own. One figure in volume 2 was
printing after the Works Cited for want of this. `_caption_key` strips
it too, and that is the half that actually places the figure:
recognising the caption only gets it into `caption_at`, while the key
is matched between the caption as the page prints it and the caption as
the block holds it, and only the block has been through `_line_text`.

A chapter can print more captions than it has images: `beyond-black-on-white`
captions five figures and embeds one, because the other four are set as live
type rather than placed as pictures. Pairing is by page and by order down the
page for that reason, never by counting captions off against images.

A figure goes in as an image and a hard line break above its caption, in one
paragraph, and never as a lone image in one. A lone image becomes a Pandoc
Figure, and the figures filter numbers every Figure from 1 in document order,
which would print "Figure 1." over a caption reading "Figure 7.1" and leave
every "see Figure 7.3" in the prose pointing at the wrong picture. A
reconstruction keeps the printed numbering.

**A figure whose page printed no caption is placed by the hole it left.**
With no caption to be paired with it has no position either, so it used to
follow the last captioned figure before it or close the document. 35 figures
in 14 chapters came out that way, and volume 2's
`the-complexity-of-simplicity` captions none of its seven collages, so there
was no last captioned figure and all seven closed the document together,
printing after the Works Cited in a chapter whose own prose calls them a
visual essay embedded in the following pages.

A figure is set into the text block, so the lines part around it and leave a
gap many times `layout.line_pitch`. That gap is a record of where in the
prose it stood and it is in the lines already being read, so nothing has to
make pypdf and pdfplumber agree about which image on a page is which.

The gap means nothing on its own, and this is the part to keep. A captioned
figure parts the text identically, so does a table, and so does a section
ending partway down its page: over those fourteen chapters a gap rule alone
catches 22 of the 24 stranded-figure pages and 59 of the 236 pages that
strand nothing. Placing a figure on that evidence would be the failure this
module least wants, present and wrong, and nothing downstream can see a
picture sitting in the wrong paragraph. So
`figure_anchors_from_holes()` counts a hole only where nothing else on the
page could have left it: no caption line, no table, and exactly as many
holes as the page has uncaptioned figures. The anchor is the line above the
hole, or the last line of the page before where the hole is at the head of
the page, and `_anchor_position` places it by the same tiers and the same
reading-order floor the tables use. 13 of the 35 are placed and 22 keep the
old behaviour with the reason in the notes, which is the right way round:
volume 6's `15-bennett` sets five of its figures on a design spread whose
only lines are the series wordmark forwards and reversed, and the table test
declines that page.

Recognising a caption comes first. Three of the seven chapters this moved
were stranding figures only because `_FIGURE_CAPTION_RE` turned down a
quoted title, and reading the hole for them placed the image in the prose
and left the caption behind as a loose paragraph after the licence note,
which is worse than where it started. A figure placed this way still carries
`undescribed_alt`, because where a figure sits and what is in it are
different questions and only the first is answerable from the page.

**Tables are found by their rules, never by the alignment of their text.**
`TABLE_SETTINGS` asks pdfplumber for the "lines" strategy only. This archive
rules its tables, and the "text" strategy reads a page of ordinary prose as a
48-row table. Missing an unruled table is the better failure, because a table
that was never found leaves the prose alone.

`drop_lines_inside_tables` is the half that matters. Read across its columns,
a two-column table interleaves its cells into prose: chapter 11 of volume 5
came through with "detailing as being the most import- lab procedures ant
while", one word cut in half with a cell from the next column inside it. That
is worse than a missing figure, because it is present and wrong, and no
conformance check sees it: the text is there, so the galley passes. The lines
a table is made of come out of the prose and the table goes in as a pipe
table, whose header row is what lets a screen reader name the column a cell
is in. It runs before the vocabulary is built, so shredded cells do not teach
it their fragments as words.

A table's caption has to stay with its table, and `blocks_to_markdown` is
where that is decided. The series sets a table caption the same size as a
figure caption, which is the same size as a footnote, so `classify` reads it
as a note and the note branch collects it at the end of the chapter. Testing
only `is_figure_caption` there left volume 6's fifth chapter printing "Table
5.1", "Table 5.2" and "Table 5.4" in a row on its last page, each one pages
away from the table it names, while `place_tables` had put every table in the
right place.

A table the series did not caption has nothing to be paired with, and the end
of the chapter is a poor guess: chapter 2 of volume 1 introduces its table
with "Let's break down the writing situation in college:" on page 6 and had
it printing after the Works Cited on page 14. `drop_lines_inside_tables`
therefore keeps the line left standing immediately above each table as that
table's anchor, which is the only record of where in the prose the table
stood, and `_anchor_position` matches it back: the whole anchor first, then
its last few words, for a line that has been through `join_lines` by then
and sits inside a paragraph. A caption still wins where there is one; the
anchor is the fallback, and a word broken across the line break defeats it,
which drops the table to the end with the note that says so.

The order of those matters, and matching on the tail alone put volume 1
chapter 6's zero draft after the Conclusion. The line above that table is
the "Zero Draft" head, so the tail is the whole of two words, and five
blocks in the chapter contain them: the head, the paragraphs either side of
it, and one in the Discussion saying what a zero draft is for. The search
ran backwards and took the last. Matched whole, the head is the only block
that is those two words, which is the general case: the line above a table
is often a head, and a head is a block whose text is exactly that line.

Between the two sits a third tier, a block that merely *begins* with the
anchor, which is what a head reads as once something has been joined to it.
Volume 5 chapter 22 prints "Rhetorical Reading Rubric" over its rubric and
"Activities to Incorporate 'Writing to Learn'" under it, and with the
table's own lines gone those two heads are consecutive lines, so `assemble`
joins them into one and no block is the anchor any more. The merged head is
then the nearest thing to it, and that is where the table goes. Without the
tier the anchor fell through to the tail, which matches a paragraph a page
earlier that mentions the rubric by name, so fixing the zero draft alone
moved this table a section too early. The merge itself is older than any of
this and loses the chapter a heading; it is the same shape as the caption
and label merges above, and it has not been fixed.

A short tail is weak however it is searched, so `_anchor_position` takes a
`floor`,
the position the table before it took. Tables arrive in page order and their
anchors are lines in reading order, so among several candidates the first at
or after the floor is the one in reading order. It is a tie-break, not a
rule: where nothing matches at or after the floor the last match is still
taken, since a mis-ordered table beats one at the end of the chapter, and
`place_tables` counts those separately and says so. That count is the thing
the notes were missing. `anchored` counts the tables an anchor resolved for,
not the ones put where the page printed them, so the run reported all twelve
of that chapter's as anchored while one was pages from its head.

A table is paired with its caption in reading order, which is where this
differs from the figures. A figure and its caption share a page by
definition, since the caption is set under the picture; a table's caption is
set above it and the two part company across a page break, as both of chapter
11's did. pdfplumber also reports the cells inside a table as further tables,
so anything inside another's box is dropped.

Pairing the nth table with the nth caption means both counts have to be
right, and two things threw them out. A table too long for its page is set
again at the top of the next one with its header repeated and no caption,
because the caption was printed over the first part, so counting it against
the next caption in the chapter shifts every table after it one caption
along: that is how the second half of volume 6 chapter 15's Table 15.2 came
to stand under the label of the teacher activity's Table 1, with the
activity's own tables one label out behind it. `continues_previous` leaves it
out of the count and lets it take its anchor instead, which is the last line
of the page it carries on from and therefore the part it continues. A
repeated header on the next page is not enough on its own, since volume 6
chapter 5 sets Tables 5.2 and 5.3 on facing pages under the same four column
names; what separates them is that 5.3's page prints its caption above it and
a continuation's page prints none. Seven tables in the series continue this
way and that pair is the only one the test has to turn down.

The other is a label with no description after it. `is_table_caption` wants a
capital to follow, which is what tells a caption from a reference to one, so
the bare "Table 1" that is all volume 3's `vieregge` prints over its only
table matched nothing and the table fell to its anchor, coming to rest two
paragraphs and a block quote below the label naming it. `is_bare_table_label`
counts it, and it tests the word, because volume 1 chapter 6 sets a bare
"Fig 2" over each of its draft boxes and those boxes are read as tables.

Alt text comes from the caption with its label and any source credit removed.
The archive sets the credit two ways, in brackets at the end and as a
trailing sentence ("Photo by Jenae Cohn", "Menu image courtesy of Mistie
Cohn"), and `_CREDIT_TAIL_RE` takes the second only where it names itself a
credit: a bare "by" belongs to the description far more often, as in "chord
changes for 'Heart of Gold' by Neil Young". A caption that is nothing but a
credit keeps it, since an empty alt costs the galley its conformance and is
no better for a reader than the credit is.

That is a starting point, not an answer: a caption says what a figure is
called and alt text says what is in it. A figure whose page printed no caption
gets `undescribed_alt()` rather than an empty string, because empty alt text
costs the galley its PDF/UA conformance and leaving the figure out costs the
reader the figure. `lint.check_alt_text` warns on both kinds so the writing
still owed is countable, and `lint.check_figure_coverage` catches an article
that refers to figures it does not contain, which `check_alt_text` cannot see
and reads as a pass.

Writing alt text satisfies WCAG 1.1.1 and leaves 1.4.5 exactly where it
was. 115 of this series' 203 figures carry text as a picture, across 37 of
its chapters, which is a property of what the books are: a technical writing volume teaches a genre
by showing one, and volume 2 reproduces student essays as collages. Nothing
can tell a photograph of a document from a photograph of anything else
without looking, so each one is listed by hand in the article's
`images-of-text` front matter and `lint.check_images_of_text` warns on the
list. A warning, not a failure: the galley conforms and the figure is
described, and what is wanted is that the shortfall stays countable rather
than being closed over by the alt text.

`ingest_volume.py` runs a folder of chapter PDFs through that in one pass.
It never fetches anything: the volume is downloaded by hand and the runner
is pointed at the folder, so a mass download cannot happen by accident and
`--dry-run` shows the whole plan before anything is written. Chapters land
as drafts. `ingest_pdf` stamps `source-file` into the front matter, which is
how a chapter is recognised as already taken in; matching on the slug alone
fails, because a slug is built from the title and the same PDF ingested with
and without a manifest lands under two of them.

The archive has renamed its chapters twice over the life of the series, so
`parse_filename` reads three conventions: a chapter number followed by
surnames (`19Irvin.pdf`, volumes 4 to 6), a surname and an abbreviated title
(`bunn--how-to-read.pdf`, volumes 1 and 2), and a bare surname
(`gagich.pdf`, volume 3). Only the first carries chapter order, so the
earlier volumes need a manifest to sit in order within a volume. Volumes 5
and 6 are numbered and need none.

Every volume folder also holds the collected book as one PDF beside its
chapters, and the runner plans it, reports it, and then does not ingest it:
reading a few hundred typeset pages as a single article is a long ingest
producing a draft nobody wants. `COLLECTED_RE` catches five of the six by
name, but volume 6 names its copy for the volume's theme
(`technical.pdf`), so length decides it. A chapter in this archive runs 5
to 29 pages and matter 1 to 8, while a collected volume runs 219 to 410, so
`COLLECTED_MIN_PAGES` sits at 100 with room either side. File size does not
separate them; the longest chapter outweighs the shortest volume. A
manifest entry naming a file overrides the skip, and a PDF that will not
open is left in the plan for ingest to report by name.

**`--replace` wrote a second copy and repointed the row at it.**
`ingest_one` found the existing article, by `(volume, source-file)` the way
`existing_sources` intends, and then called
`conversion.article_dir(journal, None, slug)`, whose `None` names the
`_unfiled` directory. So a replace over the whole of volume 2 reported 21
chapters replaced, wrote 21 fresh drafts under `_unfiled`, pointed all 21
database rows at those, and never touched the published text or the
galleys beside it. That is the shape with no symptom: the run says it
worked, the article page serves a draft with no galleys, and the files
that were actually published are orphaned from the row that names them.
`replace_dir` writes where the article lives, and makes `assets` and
`.versions` there, because a path out of the database has only ever been
a directory. A row whose directory is gone falls back to the draft, since
rebuilding an article somewhere nothing files it is the worse of the two.

**A sentence is not a heading, whichever style the file set it in.** Volume
2's `walk-talk-cook-eat` is written as a dialogue and sets its stage
directions in `Header_C`, which is the style the series uses for a third
level section head and which its RoleMap maps straight to `/H3`. So the
file states that "Marvin types it in." is a heading, while that chapter's
own heads, "Discussion" and "Works Cited", are H1s in the same series.
Reading the tree faithfully published twelve stage directions as headings,
which is a worse galley than the sixteen it was missing: a reader
navigating by heading hears "Marvin types it in" announced as a section,
and the levels are incoherent anyway, three deep under nothing.
`states_a_sentence` is the one place that judgement lives, and it needed
two tests rather than one. A full stop is what ends a sentence, and the
stop alone was wrong: measured over the 18 stated headings in this archive
that end in one, 12 are those stage directions and 6 are real heads, since
`on-the-other-hand` heads five sections "Step 1:" to "Step 5:" and ends
each with a stop. Turning them all down would have cost six real headings
to stop twelve false ones, which is the trade the measurement exists to
catch and a fixture would not have. What separates them is the case: a
title capitalises its substantial words and a sentence does not, so
"Step 5: Imagine Hostile Audiences." parts from "Marvin types it in." The
stage directions capitalise at most a quarter of their long words and the
real heads all of them, so `TITLE_CASE_SHARE` sits at a half in the gap.
Only words of four letters or more vote, because a title leaves its
function words alone, and the first word never votes, because a sentence
capitalises that too; a line with no long word left reads as a title
rather than being turned down on no evidence.

Terminal punctuation in general is not the test: a head may ask a
question and `writing-eyeball-to-eyeball` closes on "What Difference Does
a Mindful Collaboration Make?". An ellipsis is not a full stop either,
spaced or not, which is two more heads here. Emphasis comes off first, for
the reason the captions do, since a stage direction is set in italic and
arrives wrapped, and it goes back on where the line is kept as body,
because there the italic is the direction's own and a reader is meant to
hear it.

**And it is asked in `flush`, because a heading wraps.**
`apply_stated_headings` marks lines and decides nothing: asked of one
physical line, the test let five of the twelve stage directions through,
the long ones, since the first line of a wrapped sentence carries no full
stop at all. `assemble`'s `flush` holds the text `join_lines` has already
put back together, which is the only place the whole heading exists; it is
also after the hyphen is rejoined, and
`annoying-ways-people-use-sources` breaks "Useless" across the line in a
head. So the stated level is applied there or turned into body there, and
`assemble` fills `declined_heads` in the optional `report` so `extract`
can say so in a note. An out parameter rather than a second return value,
because the pair `assemble` returns is what every caller and every test
builds, and a stated head overruled is something to say out loud rather
than something to act on. This is the one place ingest overrules what a
file states about itself, so it names the lines and the reason.

**A book's levels are not a conformant outline, and `filters/heading-levels.lua`
is what closes the gap.** PDF/UA wants a heading outline that starts at
level 1 and skips nothing. Reading the structure trees made both live at
once, and both are the book being reproduced faithfully:
`on-the-other-hand` sets its sections in `Header_A` and its five steps in
`Header_C` with no `Header_B` between, so the chapter goes from a first
level to a third, and `the-complexity-of-simplicity` does the same at
"Study Guide". Typst validates rather than declares, so each aborted the
compile and `_compile_typst` shipped the galley unconstrained. Four
galleys lost the conformance identifier the first time these headings
reached a render, and `register.record_pdfua` is what would have counted
it.

The other two were the teacher halves of `3-ilyasova` and `4-zhou`, and
they fail differently: "the first heading must be of level 1". A split
article renders two documents out of one body, and the teacher
intermediate drops the `Teacher Resources` heading because the template
prints it as that galley's title, so the document opens on whatever sat
under it. That was a `#` before and is a `##` now, which is the same
recovery working correctly and costing the galley its conformance.

So this is a filter rather than a fix to `blocks_to_markdown`. The
constraint belongs to the document being rendered, one `article.md`
renders as two of them, and the canonical copy keeps the levels the book
states. Each galley is normalised on its own way out, by
`_heading_levels_filter_args()` from `render_html`, `render_pdf`,
`render_epub` and `_md_to_typst_fragment`, which is the same four call
sites `fig-alt.lua` needs and for the same reason.

The transform is a stack of the levels seen, and the depth written is the
stack's height, so a heading deeper than the one before it goes exactly
one deeper and nesting survives. Ranking the distinct levels instead does
not work: a chapter can hold every level and still skip one positionally,
which is a `#` followed by a `###` with the `##` elsewhere in the
document. `test_a_positional_skip_is_caught_where_ranking_would_miss_it`
is what holds that.

What it does not fix is that chapter's one split head. The page sets a
marginal pull quote down the side, and its lines interleave in reading
order with the two lines of the heading, so nothing is adjacent to be
merged and the galley carries "Uncle Barry and His Encyclopedia of Use-"
and "less Information" as two. That interleaving is older than any of
this; the same lines were in the same order before, as paragraphs rather
than heads, which is where reading the tree made a pre-existing defect
legible rather than causing one. Separating a marginal column from the
text block is the fix and it is not written.

**Nothing checked the order until `structure.reading_order` did, and the
order is where this module's worst defects live.** Every check in `lint.py`
reads what the reconstruction produced and asks whether it is well formed.
None of them could ask whether it is in the right order, because the words
are all present either way: the galley renders, lint passes, verapdf
passes, pa11y passes, and a reader meets a pull quote spliced through a
heading. That is the whole history above. Two texts merged character by
character inside a clipped figure. A two-column table read across its
columns as "detailing as being the most import- lab procedures ant while".
Seven figures closing a document after the Works Cited. Every one of them
was found by a person reading a galley and noticing.

A tagged PDF states the order, and that is the only thing a reconstruction
can be checked against. Any other reading of what order a page should come
out in is the same inference that produced the reconstruction, so it would
agree with itself and prove nothing.

**Descents, not an agreement figure.** `order_descents` counts the places
where consecutive output text runs backwards through the file's order, and
does not score the chapter as a whole. The defect is local and a
whole-chapter figure buries it: the interleaved pull quote in
`annoying-ways-people-use-sources` is sixteen lines out of five hundred, so
as a share of the pairs that could be out of order it is 0.02%, which no
threshold separates from a clean chapter, and as a count of places where
the text jumps backwards it is sixteen against zero. `Descent` carries the
gap and the words either side, because the number says there is a problem
and only the words say what it is.

**The tree decides what is body flow, and the answer is inherited.** The
first version asked `pdf_ingest` to guess from how a line read, and it was
wrong three ways over the archive, each one a chapter reporting a fault
that was not there. A caption sits in its own branch, so
`introduction-to-primary-research` jumped back 734 marked ids after
"Fig. 2: A sample timeline for Jared's research project" with nothing
wrong. `is_figure_caption` then missed "Figs. 2-6." for want of a plural.
And every one of `7-welhausen`'s ten descents was a footnote, which this
series prints with no stop after the number, so `_NOTE_RE` could not see
them either.

`NOT_BODY_FLOW` and `carries_body_flow` read it off the file instead, and
both the role and the style are tested, because the RoleMap flattens:
`why-blog-searching-for-writing-on-the-web` holds its caption as role `/P`
with style `/Caption`, the same export trick that hides the heading levels.
The flag is inherited and `walk` works it out as it goes, because an
element on its own cannot answer: a `/P` inside a `/Note` is still a note,
and the text usually sits in a `/Span` below that again. Testing the
element alone left all ten of those footnote descents standing. A line the
file places nowhere in the body flow is reported unplaced, never as text in
the wrong place, and `share_placed` is the evidence behind the count.

**Measured at ingest, reported by lint, and that split is deliberate.**
`pdf_ingest.measure_reading_order` runs over the lines on their way into
`assemble`, where both orders are already in memory and the comparison
costs nothing. Those lines are past `strip_furniture` and past the front
matter, and `assemble` only groups lines already adjacent, so their order
going in is their order coming out; what moves afterwards moves on purpose,
since `blocks_to_markdown` collects the notes to the end because Markdown
requires it there and the figures and tables are placed by anchor.
Comparing the finished Markdown would report every one of those as a fault.

`lint.check_reading_order` then reads the number off the front matter and
works none of it out again. Reading a structure tree in a lint check would
cost a pdfplumber pass over the source on every corpus run, and the route
that runs these checks over a whole journal exists because lint and the
declaration are cheap enough for a request. A note would have been the
other option and it reaches nobody: `conversion.py:561` writes the ingest
notes into `conversion.log`, no route serves that file and no template
shows them, so every note this module leaves is already unread.

A chapter with no record has not been checked, which is not the same as a
chapter with nothing wrong, so it passes with the gap said out loud and
counts nothing: `chapters-order-checked` is what separates the two, by the
rule `register.UNRUN` exists for and the one `check_images_of_text` draws
beside its own zero. The units are recorded and deliberately kept out of
`WORK_ROWS`, because a descent is a place for somebody to look and not an
hour of editorial labour, and summing it with the figures still to be
described would make the one number a journal asks for mean two things at
once.

**What it found, and what it cannot see.** `8-diab` reports 18 descents at
a worst of 349, and reading them shows two columns interleaving and
merging mid-word: "The author divided the parts of the rhe-" then "target
students and teachers". That is the same defect
`drop_lines_inside_tables` was written for, live and undetected in a
chapter nobody had looked at.

The limitation is the files with no usable tree. 18 of the 115 state no
order at all, and volume 1's chapter 6, which is the worst reconstruction
in this archive by a distance, is one of them: its tree covers the
publisher's cover page. So the check is blind in exactly the place the
reconstruction is weakest, and a chapter reporting no descents may simply
be a chapter nothing could be asked about. That is why the count of
chapters checked is reported next to the count of descents rather than
underneath it.

**Two columns with no rule between them are split by asking the file.**
Pages 12 and 13 of volume 5's `8-diab` reproduce a student's draft at 11pt
beside a reviewer's commentary at 9pt, and rule nothing. pdfplumber reads a
line of ink across the whole measure, so the two came out alternating word
by word: "purpose) into three separate paragraphs in the US who might un-
which helps the reader locate each easily, intentionally contribute to thus
read, comprehend, and use the text". No check saw it, which is why
`lint.check_reading_order` exists; it reported the chapter at 18 descents
against a median of 0 and that is how this was found.

Neither path above reaches it. `find_page_tables` asks for ruled lines and
the page has one, a decorative rule in the margin, so there is no box. And
`infer_column_rules` wants a frame, horizontal rules running between two
verticals, which is the shape a Word table leaves and not this.

The geometry cannot be read instead, and that is worth knowing before
somebody tries it. The page alternates between two columns and full-width
prose four times, so no gutter holds down its height and there is no region
to find. A test on the obvious signal, a wide horizontal gap where the type
size changes, fires on 335 lines across 69 pages of this archive, of which
67 need nothing: the comment balloons of volumes 1 and 2 are already
repaired by the ruled-table path, and `1-rose` sets a Wingdings checkbox
form that reads the same way.

So `column_runs` asks the tree. Two characters printed side by side whose
elements sit hundreds of places apart in the file's stated order are not
neighbours, whatever the ink says, and the split goes between them. It
repairs the other chapter the check flagged as well:
`annoying-ways-people-use-sources` ran its marginal gloss through the
middle of a sentence, publishing "Everyone in the car hears it: buh-BUMP.
*dropping in a quotation* The driver insists to the passengers, "But
*without introducing it* that armadillo", and the body sentence now comes
through whole with the gloss beside it.
`COLUMN_ORDER_JUMP` is 100, measured over this chapter: an inline link or a
run of italic is its own element and jumps 3 to 23, while the columns jump
319 to 350. It is gated on the page and not the document, because whether
the tree reaches the text is a per-page question and a page it does not
reach has to come through exactly as it did before.

**Sorting the lines into that order was built next and taken out.** It
looked like the other half of the same fix, and it did close the chapter
from 33 descents to 2 and rejoin four words broken across the column break.
It also changed nineteen chapters that have no column anywhere, relocating
a paragraph in each with no word lost.
`how-to-read-like-a-writer` prints "I came to realize that all writing
consists of a series of choices" as a display line and its tree places it
elsewhere, so the sort moved the continuation of "re-read entire para-"
away from the word it finishes and put the display line there instead. The
two orders differ for reasons that are not errors. Deciding where a line
ends is safe; deciding where the text goes is not, and a file's stated
order is not authority enough for it.

What this does not fix is the paragraphing, and that is pre-existing.
`starts_para` fires on every indented line, because in this series a
paragraph's first line is indented and its turn lines are flush. The quoted
draft is indented as a whole, 18pt from a learned `body_left` of 58.5, so
every line of it reads as a paragraph start and comes out as its own block.
The published galley already did that; what changed is that the words are
no longer shredded and nothing is missing.

One measurement trap, because it cost an hour. Comparing an `extract` body
against a published `article.md` reads as a 72-word loss that is not there:
`extract` places no figures without an `assets_dir`, and this chapter's two
figure descriptions are hand-written and long. Exclude the image markup
from both sides, and the split is exactly word for word neutral.

**A tree states where its figures sit, and sometimes that is the exporter
talking.** `structure.stated_placements` reads it: for each `/Figure` and
`/Table`, the reading-order position of the body text it follows, numbered
by `reading_order` itself so the two cannot drift. It was read in order to
check the placement decisions in this module, since a figure beside the
wrong paragraph renders identically and nothing has ever looked.

The reading is sound and the check is not built, because the premise needed
qualifying first and the qualification is the finding.
`the-complexity-of-simplicity` states all seven of its collages after a
Works Cited entry at 97% of the text, which is exactly the defect
`figure_anchors_from_holes` was written to repair; the galley now spreads
them through the prose at 4 to 87%, where the chapter's own words put them.
There the tree is wrong and this module is right, so a check that trusted
it would report the correct answer as a fault.

`collects_figures_at_one_place` is the gate, and what it tests is a run of
figures sharing one stated position, not a position near the end. Being
late was the first guess and it let `15-bennett` through, which states six
of its seven at 75% while the galley has them at 6 to 11%: one is late and
one is not, and both are a run the exporter gave a single place. Two
sharing is ordinary, since a page can print a pair side by side. Measured
over the 41 chapters here that state more than one figure, the largest run
runs [1 x22, 2 x10, 3 x2, 4 x2, 5 x2, 6 x2, 7 x1], and as a share of the
chapter's figures the seven worst sit at 80 to 88% against a next value of
67%, so `GROUPED_SHARE` is 75.

So the placements can be trusted for 34 of those 41 and the check remains
specified rather than written. What it still needs is not plumbing: it is
ground truth for the chapters where the tree and the galley disagree
without a grouping artefact, which means somebody looking at the book. The
plumbing is worth naming too, since it is not free: a block would have to
carry the reading-order span of the lines that made it, through
`assemble`'s `report`, and `place_figures` would have to say which block
index it chose and why.

**An article can render as two galleys.** `teacher-resources: separate` in
the front matter splits a chapter at its `Teacher Resources` heading, so the
material addressed to instructors renders as its own document
(`teacher-resources.pdf` / `.html`) beside the chapter. It is opt-in per
article, not per journal, because it is a property of how a piece is
written. `article.md` stays the one canonical copy: the split writes derived
`.chapter.md` / `.teacher.md` intermediates, which are gitignored. Footnote
definitions move to whichever half refers to them, since Markdown collects
them at the end of the document, behind the teacher material. `render_pdf`
and `render_html` take a `part`, pass it to the filters as
`graphion-part`, and write to separate intermediates; the Writing Spaces
filter uses it to keep the drop cap out of the teacher galley. Both galleys
are served from the article page; see `serve_teacher_pdf` in `app.py`.

**A volume usually shares one licence, and one of them does not.**
`ingest_volume.py` writes `license` and `license-url` over every chapter in a
run, rather than leaving each to the notice printed on its own opening page: a
chapter whose footnote failed to extract would otherwise publish with no
licence recorded. That is right for five of the six volumes and wrong for
volume 1, which prints Share Alike over twelve chapters and No Derivative
Works over five. Stamping one value across the run published the stricter of
the two over chapters that permit derivatives, in galleys that told a reader
so; the licence a work is under is not a detail a pipeline may round off. So
a manifest entry's `license` / `license-url` overrides the run's, which is
the only way the runner can know, and `docs/manifests/` holds the two
manifests the earlier volumes need anyway for chapter order. Volumes 1 and 2
are under the 3.0 **United States** licences, not 4.0 International, and the
jurisdiction is part of the URL (`/by-nc-sa/3.0/us/`). The chapter's own
footnote names its deed ("To view a copy of this license, visit ..."), which
is the authority to check a recorded value against; across the series 108 of
115 chapters print one, and the 7 that do not are collective front matter
plus `22-thaiss-wade`, which relies on the colophon.

The HTML galley carries the field as `rel="license"`, a `dcterms.rights`
meta, and a visible statement closing the document, all unconditionally
(`article.html.j2:88`), so a wrong value there is published prose and not
just metadata. The PDF gets a colophon, but only when
`conversion.should_print_license()` finds the body silent: a published
chapter prints its own terms as a footnote on its opening page and ingest
recovers that, so printing the metadata licence as well would state it twice
on one galley. Recovering it is not the same as guaranteeing it, which is
what the colophon is for. A Lua filter that walks the whole document reaches
metadata too, which is how soft break points for long URLs ended up inside
the licence href; walk `doc.blocks`, not `doc`.

**YAML round-trips are validated.** `write_article_metadata()` refuses to write
YAML that fails `safe_load`, and normalizes whitespace in scalar fields to
prevent wraparound corruption. `safe_dump` uses `width=10_000` to keep scalars
on one line. Do not lower that width.

**Snapshot before write.** `_snapshot_version()` runs before any `article.md`
write; the last 5 versions are kept under `.versions/` (`VERSIONS_KEEP` in
`config.py`).

## Optional dependencies degrade, they do not crash

The app probes for optional tooling and greys out UI rather than failing at
startup. Two probe shapes exist; match the one already used by the module:

- Single-dependency modules expose `available()`: `stylize.py`, `llm_cleanup.py`,
  `ocr.py`.
- Multi-tool wrappers expose one probe per tool: `preprocessors.py`
  (`mammoth_available()`, `libreoffice_available()`), `validators.py`
  (`verapdf_available()`, `pa11y_available()`).
- `ojs_client.py` has no probe; it is configured by journal settings or env vars
  and defers its `requests` import.

Anything touching Claude (`stylize.py`, `llm_cleanup.py`) requires
`ANTHROPIC_API_KEY` in the environment and must stay optional.

## Layout notes

- `app.py` (3152 lines) is the whole HTTP surface. `conversion.py` (2687) is the
  pipeline. Those two hold most of the complexity.
- `describe.py` (422) is the description queue behind
  `/accessibility/<slug>/describe`. It owns no judgement of its own: a
  figure's state comes from `lint.figure_state` and a description is
  written by `conversion.with_description`, so what it holds is the order
  the work is done in and the counts an editor works to.
- `structure.py` (371) is what reads a PDF's own structure tree: the walk,
  the join to the page on the marked-content id, and the heading level a
  RoleMap flattened. It is the only tree walker now; `assess` counts
  figures and headings off its elements, and `pdf_ingest` takes its
  headings from `heading_map()` where the tree reaches the text.
- `epub_a11y.py` is the only module that touches EPUB package structure,
  for the same reason `pdf_tags.py` is the only one that touches PDF
  object structure: rewriting a container is a thing to do in one place.
  It imports `lint` inside `describe()` rather than at the top, because
  `conversion` imports this module and `lint` imports `conversion`.
- `pdf_tags.py` (713) is the only module that touches PDF object structure
  directly; it binds rendered galleys into a tagged issue. It reaches into
  pypdf's `_add_object` and `_root_object` because pypdf exposes no public API
  for a structure tree or the catalog's `/Lang`. It also reads an XMP packet
  back (`xmp_packet_text`, `declared_ua_part`, `declared_title`), beside the
  `_xmp_packet` that writes one, so the reading cannot drift from the
  writing; `assess.py` calls those rather than keeping a pattern of its own.
  Its pdfuaid:part pattern takes an element or a quoted attribute and nothing
  else, because the looser one `assess.py` used to hold reads a digit out of
  a neighbouring attribute, and a conformance claim invented that way is the
  failure with no symptom. Across the 311 PDFs here the two readings agree,
  so the choice decides the next source's reading rather than this one's.
- Per-journal template bundles live at `content/journals/<slug>/template/`:
  CSS, Pandoc HTML template, Typst template, Lua filters, CSL stylesheet,
  wordmark, and the Claude `style-guide.md`. The LiCS bundle is the worked
  example; `new_journal.py <slug> "Name"` clones it.
- `filters/` holds the Pandoc Lua filters that belong to the app rather than
  to a journal: `math-alt.lua`, which puts alt text on every equation,
  `fig-alt.lua`, which puts a figure's description where a writer will turn
  it into alt text, and `heading-levels.lua`, which makes a galley's
  outline start at level 1 and skip nothing. The test for whether a filter
  goes here or in a bundle is whether a new journal should be able to start
  without it: `new_journal.py` clones a bundle, so anything it clones is
  something a journal can also drop. How a caption is set and how deep a
  book sets its sections are a journal's design; whether a figure can be
  read aloud, a formula heard, or an outline navigated is not.
- Typst compiles with `root=CONTENT_DIR` so templates can reference image assets
  under `content/`.
- Pandoc 3 emits Figure blocks rather than `Para[Image]`; the figures filter
  handles both shapes.

## Deployment

Production runs on Fly.io at a public `.fly.dev` hostname; see
`docs/deployment.md`. Three things follow from that and are easy to get wrong:

- **Paths are env-driven.** `GRAPHION_CONTENT_DIR` and `GRAPHION_DATA_DIR`
  (`config.py`) point at a mounted volume in the container. Never hardcode
  `BASE_DIR / "content"`; import `CONTENT_DIR` and `DATA_DIR` from `config`.
- **The production path never touches `app.py`'s `__main__` block.** Gunicorn
  imports `wsgi:app`. Flask's debugger stays off anywhere but loopback, which is
  what the `loopback` check at the bottom of `app.py` enforces; do not weaken it.

- **`/login` is the only unauthenticated route, and it is public.** It is rate
  limited per address and per account in `app.py`; the counters are in-process,
  so they assume the single gunicorn worker that `deploy/entrypoint.sh`
  configures. Do not raise `GUNICORN_WORKERS` without replacing the limiter,
  and do not add an unauthenticated route without thinking about exposure.

Shell scripts and the Dockerfile must keep LF endings (`.gitattributes` pins
this). A CRLF shebang makes the container fail to start.

`.dockerignore` is not `.gitignore`. Ignore rules do not apply to paths git
already tracks, so a pattern that is harmless in one can silently drop a
committed source file from the build context in the other.

**The volume holds two kinds of thing.** `deploy/entrypoint.sh` refreshes
per-journal template bundles from the image on every boot, because they are
versioned source; it seeds article and issue content no-clobber, because that is
data an editor produced. `template/assets/` is volume-owned so uploaded
wordmarks survive. A template edited on the volume is replaced by the next
deploy; edit it in git.

## Committing

The remote is `https://github.com/justalewis/graphion.git`. Work is only portable
across machines once it is pushed, so commit and push before switching
workstations. Never commit `data/graphion.db`, rendered galleys, or anything
under `content/**/_unfiled/`; `.gitignore` already covers these.
