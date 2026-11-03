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

Tests (618 functions, 660 cases once the parametrized ones expand: 142 in
`test_pdf_ingest.py`, 96 in `test_cleanups.py`, 43 in
`test_ingest_volume.py`, 42 in `test_lint.py`, 38 in `test_describe.py`,
36 in `test_register.py`, 29 in `test_teacher_resources.py`,
29 in `test_metadata_roundtrip.py`, 26 in `test_pdf_tags.py`,
24 in `test_math_alt.py`, 21 in `test_assess.py`,
18 in `test_acr.py`, 14 in `test_epub_a11y.py`,
13 in `test_template_bundles.py`, 12 in `test_validate_galleys.py`,
9 in `test_pdf_ua.py`, 8 in `test_accessibility_routes.py`,
6 in `test_standalone_html.py`, 5 in `test_validators.py`,
4 in `test_journal_filter.py`, 3 in `test_preprocessors.py`). Most of the suite
runs without Pandoc; `test_journal_filter.py` needs it, and
`test_math_alt.py` needs it for the filter round trip alone. Both skip
where it is absent:

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

It reports in two registers on purpose. The conformance a PDF arrives with
is a fact the file states, read off the catalog and the XMP. What
remediation would have to produce is a count of work, reported with the
reasoning attached so the number can be checked. What it cannot know is
reported too, because nothing can tell a photograph of a document from a
photograph of anything else, and `images-of-text` is the number that
decides whether an archive is finished.

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
its eight checks would have failed on the LiCS bundle as it stood.

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
  to a journal, which at present is `math-alt.lua` alone. The test for
  whether a filter goes here or in a bundle is whether a new journal should
  be able to start without it: `new_journal.py` clones a bundle, so anything
  it clones is something a journal can also drop.
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
