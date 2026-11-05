# Auditing a course cartridge

A roadmap for reading an `.imscc` Common Cartridge, as Canvas, D2L and
Moodle export one, and reporting what in it would fail an accessibility
audit.

Written 5 November 2026, grounded in a real export rather than in the
specification: `engl102-evidence-literacy-2730124-20261104-185735.imscc`,
175 entries, 21.9 MB.

## 1. Why this fits here, and the one way it does not

Most of the engine already exists. A cartridge is a zip of HTML, files
and XML, and `assess.read_html` already reads a page the way `assess_pdf`
reads a PDF: images without alt, placeholder alt, alt that merely repeats
the caption, decorative claims, tables without headers, layout tables,
heading levels and skips, landmarks, language, untitled iframes, links
with no text, unlabelled controls, media without captions. Every PDF
inside a cartridge is already `assess_pdf`'s problem. The register, the
work rollup and the conformance report are all shaped around exactly this
kind of counting.

**The one way it does not fit is the deepest.** Graphion's answer to a
bad PDF is to re-publish it: ingest, reconstruct as Markdown, render a
conformant galley. There is no equivalent for a cartridge. Nobody wants
Graphion's re-typeset copy of their Canvas course, and re-importing a
rewritten cartridge would detach every page from its Canvas id, its
assignment, its gradebook column and its module. So this is
**report-only**. The deliverable is a worklist an instructor acts on
inside the LMS, not content Graphion holds.

That makes it smaller than it looks. No ingest, no galleys, no database
rows for course content, no republication. It is `/assess` with a
different unpacker and a different report.

**And a cartridge is not a course.** The LMS renders it: Canvas wraps
your HTML in its own chrome, applies its own stylesheet, and supplies its
own navigation, none of which is in the package. An audit of a cartridge
is an audit of the source. Say so on the page, or the report will be read
as a clean bill of health for something it never examined.

## 2. What is actually in one

Measured over the export above:

| | count |
|---|---|
| HTML pages | 63 |
| XML (manifest, `course_settings/`, discussions, assignments) | 68 |
| `.mp4` files | 18 |
| QTI question banks | 3 |
| caption tracks (`.vtt`, `.srt`) | **0** |

Read across those 63 pages: 26 `<img>`, **all 26 carrying an `alt`**; 12
`<table>`; 18 `<video>`; 13 `<iframe>` pointing at
`community.instructuremedia.com` (8), `olympic.hosted.panopto.com` (3)
and `www.youtube.com` (2).

Two findings fall straight out, and they set the priorities.

**The HTML is in good shape and the media is not.** Every image in this
course is described. There are 31 pieces of video between the embedded
files and the external players, and the package contains no caption track
for any of them. That is WCAG 1.2.2 and it is the whole audit for this
course.

**Most of the media is not in the cartridge.** Thirteen of those 31 are
iframes to three external hosts. The package can tell you a video is
embedded and where it lives; it cannot tell you whether that video is
captioned, because the captions live in Panopto, Instructure Media or
YouTube. **That question belongs to an API, not to a zip file**, which
is worth knowing before anyone builds cartridge parsing expecting it to
answer the thing that matters most.

## 3. What it can never know

By the rule the rest of this codebase follows: report what was read, name
what was not.

- **Whether captions are accurate.** A `.vtt` exists or it does not. That
  auto-captions are present and wrong is invisible here, and it is the
  commonest real failure.
- **Whether alt text is good.** Presence is checkable; sufficiency is not.
  This course reads as 26 of 26 described, which is the right answer to
  the question asked and not a statement about the writing.
- **Anything behind a link.** An external reading, a publisher platform, a
  library database. Count them, name them, audit none of them.
- **Images of text**, the same WCAG 1.4.5 hole as everywhere else: nothing
  can tell a photograph of a document from a photograph of anything else.
- **Colour contrast in an Office theme**, without rendering the file.
- **Keyboard operability of the rendered page**, which belongs to the LMS.
- **LTI tools**, which are somebody else's application entirely.

## 4. Stages

Each stage is usable on its own, in the order that puts findings in front
of a person soonest.

### Stage 0: read the package

Unzip to a temp directory the way `/assess` already does, parse
`imsmanifest.xml` for the resource list and the organization tree, and
report an inventory: how many of each kind, the module structure, and
what is referenced but absent. Canvas adds `course_settings/` with its
own XML for assignments, modules and pages; D2L and Moodle differ, so
read the manifest first and treat the vendor directory as an enrichment
that may not be there.

Deliverable: "what is in here", with nothing audited yet. Small.

### Stage 1: route HTML and PDF to the readers that exist

Every `.html` goes to `assess.read_html`, every `.pdf` to `assess_pdf`.
Roll up with the same `assess.rollup` discipline: one adder, counted per
course and per module.

This is the stage with the best ratio of value to new code, because
almost none of it is new code. Small to medium.

### Stage 2: the media census

The headline finding for the course measured above, and the reason to do
it early. For each `<video>`, `<audio>`, `<track>`, `<iframe>` and media
file: what it is, where it lives, and whether a caption track is present
**in the package**. Report external media as *unauditable from here* and
name the host, rather than implying it passed.

Medium. The honesty of the wording matters more than the parsing.

### Stage 3: Office documents

`.docx` and `.pptx` are common in cartridges and carry their own
accessibility surface: heading styles, image alt, table headers, slide
reading order, slide titles. `python-docx` and `python-pptx` are pip
installs. New readers, in the shape `read_html` already has.

Medium. Skip it if a given archive has none; this course had none.

### Stage 4: QTI and discussions

Quiz items and discussion prompts are HTML inside XML wrappers. Unwrap
and hand to `read_html`. Small, once Stage 1 exists.

### Stage 5: links

Every external link in the package, checked for whether it still
resolves. Link rot is the usability half of the question and the most
immediately actionable thing an instructor gets back. It is network-bound
and slow, so it is **a job**, not a request; the job runner already
exists and this is a second kind for it.

Medium. Rate-limit it and never follow a link twice.

### Stage 6: the report surface

A course-shaped page: by module, by item, with the work table and the
same current/stale discipline the register uses if results are stored at
all. Reuses `_register_tables.html` patterns.

Medium.

## 5. Where the fixes go

Not back into the cartridge. A repaired `.imscc` re-imported into Canvas
creates new pages with new ids and orphans everything attached to the
old ones.

The fixes go through the **Canvas API**, item by item, against the live
course: that is what `OC Canvas API Tool` already does. So the sensible
end state is that Graphion produces the audit and the worklist, and the
Canvas tool applies what is applicable. Keeping those separate also keeps
Graphion's "reads only, writes nothing" contract intact for the
assessment half.

The same split answers the media question from §2: whether a Panopto or
Instructure Media video is captioned is an API call, and the tool that
holds Canvas credentials should be the one to make it.

## 6. What to build first

Stages 0, 1 and 2, against the 35 cartridges already on this machine. That
gives a real audit of real courses, covers the two things this export
actually needed, and is mostly assembly of readers that already work.

Stage 5 is the one to do next if the audience is instructors rather than
compliance, because link rot is what they will act on the same afternoon.

---

# Remediating somebody else's cartridge

Added 5 November 2026. The audience is not the person who wrote the
course: it is an instructor at another institution who sends an export
and gets one back. That changes almost every decision below, and it is
the same argument `accessibility-service.md` makes for journals.

Measured over all 35 cartridges on this machine, as a sense of what
arrives: **1,199 PDFs**, 495 `.docx`, 208 legacy `.doc`, 74 `.pptx`,
1,126 images, 2,642 HTML pages, 31 media files and **0 caption tracks**.
PDFs are the payload by a distance, which is convenient, because PDF
machinery is the best-developed thing in this repository.

## 7. Full accessibility, honestly

Not automatically, and the line is sharp enough to write down.

**Everything mechanical can be fixed without asking anybody.** A missing
language attribute, a table header with no `scope`, a heading level that
skips, an untitled frame, a PDF with no `/Lang`, no `dc:title`, no
`/DisplayDocTitle`. These are failures of markup, not of authorship, and
over an archive they are most of the failure count: one plain typeset
chapter of Writing Spaces fails 1,462 verapdf checks across 11 rules, and
tagging answers most of them at once.

**Everything that requires writing words about the content cannot.** Alt
text, a long description, a caption track, a table summary, replacing
"click here" with something meaningful. Those can be drafted and must be
reviewed, which is what `undescribed_alt` and the description queue
already exist for: a machine-written description that is wrong is worse
than a marked gap, because it passes every checker and tells a reader
something false.

Working for somebody else makes that stricter rather than looser.
**Nobody here knows what the author meant.** A description of a figure in
a discipline you do not teach is a guess in a confident voice, and it
goes out under their name on their course. So drafts come back as drafts.

The promise is: **every mechanically fixable failure fixed, every
content-requiring gap drafted for the author to accept or rewrite, and
everything unfixable named.**

## 8. The guarantee is the product

"It will not change a word of your course" is what makes an instructor
willing to send you their work at all. It is worth more than a promise,
so make it a test.

**The invariant: the visible text of every page, document and slide is
identical before and after.** Extract it, normalise whitespace, compare.
Any pass that changes a word fails the run. Everything remediation adds
lives in an attribute, in metadata, or in structure, never in the prose.

That is the same shape as
`test_assessing_a_folder_leaves_it_exactly_as_it_was`, and it is built
**first**, before any fixing pass, so every pass is held to it from its
first commit.

Report it on the way out, too: *3,412 blocks of text compared, 0
changed*. An instructor who can see that number does not have to take
anybody's word for it.

Two honest footnotes. Normalising `<h3>` to `<h2>` keeps every word and
changes how the page looks, so appearance is not covered by the invariant
and is reported separately. And alt text added where there was none adds
no visible text, so it satisfies the invariant while still needing the
author's review.

## 9. Student data comes before any of it

A Canvas export can carry more than course design. Discussion topics can
contain replies, and a full export is not the same thing as a content
export. Taking in somebody else's course means taking in whatever they
included, and if that is student names, posts or grades, it is FERPA
material sitting on your disk.

So the first pass over an incoming cartridge is a **screen**: look for
submissions, gradebook data, user ids and discussion replies, and stop
with a plain message naming what was found. Do not audit it, do not
remediate it, do not keep it. Ask for a content-only export instead.

This belongs before Stage 0 of the audit, not somewhere in the middle. It
is the one failure here that is not about accessibility at all, and the
most expensive to get wrong.

## 10. PDFs, and the fork that matters most

Of the 1,199, each needs one of two completely different things.

**Metadata and declarations can be stamped in place.** `/Lang`,
`dc:title` in the XMP packet, `/DisplayDocTitle`, `/MarkInfo`. Every byte
of ink is unchanged and `pdf_tags.py` already reads and writes XMP
packets. Cheap, safe, and it clears several clauses per file.

**A structure tree cannot.** Tagging an untagged PDF means working out
what its paragraphs, headings, lists and tables are, and that is
reconstruction: `pdf_ingest` reading the geometry, then a fresh render.
The result is a new document that looks different from the one the
instructor uploaded.

For somebody else's teaching material that is usually the wrong trade,
and it must never happen silently. Offer both, default to stamping, and
where a file can only be fixed by rebuilding, say so and let the author
choose. A third-party publisher PDF they hold no right to re-typeset is a
reason on its own.

## 11. OCR

A scanned PDF has no text layer, so a screen reader finds nothing at all.
OCR adds one underneath the image. The page looks identical, so this
satisfies the invariant in section 8 and is the highest-value single fix
available for a scanned reading.

It is also the one most likely to produce confident nonsense. Tesseract
on a clean 300dpi scan is excellent and on a third-generation photocopy
it is not, and nothing downstream can tell which happened: the text layer
exists either way and every checker passes. So confidence is recorded per
page, pages below a threshold are listed as owing proofing, and the
report counts them apart from the ones that are done. `ocr.py` and the
Tesseract probe already exist; Tesseract is not in the production image.

## 12. What you hand back

Not a Canvas API integration. You will not hold credentials for a course
at another institution, and asking for them is asking for the keys to
their gradebook. The deliverable is files and a report, the way `/assess`
already works for a stranger's PDFs.

Three things go back:

1. **The remediated cartridge**, with the manifest intact.
2. **A change log**, file by file, naming every change made and every
   change declined with its reason. This is what makes the work auditable
   by somebody who was not there.
3. **A worklist of what is still owed**: drafted alt text for the author
   to accept or rewrite, uncaptioned media, OCR pages needing proofing,
   and anything that would have required rebuilding.

And a warning, prominently: **re-importing this into a live course does
not replace anything.** Canvas creates new pages with new ids and orphans
every assignment, module item and gradebook column pointing at the old
ones. A remediated cartridge is right for a fresh shell, a Commons
package, an archival copy, or a course handed on. For a course being
taught, the changes have to be applied item by item by somebody with
access, and that is the author.

## 13. Stages

Numbered on from the audit stages above.

- **R0: the student data screen.** Before anything else. Small, and the
  only one here that is not negotiable.
- **R1: the invariance harness.** Text extraction, normalisation and the
  before/after assertion over HTML, PDF, DOCX and PPTX, with the
  comparison count reported. Small, and the whole guarantee rests on it.
- **R2: HTML mechanical.** `lang`, table `scope` and header promotion,
  heading level normalisation, `role="presentation"` on layout tables.
  `filters/heading-levels.lua` already solves the level problem for
  galleys and the logic ports. Small to medium.
- **R3: PDF stamping.** `/Lang`, `dc:title`, `/DisplayDocTitle`,
  `/MarkInfo`, in place. `pdf_tags` already writes XMP. Small, and it
  touches 1,199 files.
- **R4: OCR.** Tesseract over pages with no text layer, confidence
  recorded, proofing owed. Medium. Needs Tesseract in the image.
- **R5: Office documents.** `python-docx` and `python-pptx` for alt text,
  heading styles, table headers and slide titles; legacy `.doc` converts
  through the LibreOffice already in the image. 777 files across these
  cartridges, so larger than it looks. Medium to large.
- **R6: the drafting queue.** Route every undescribed image into the
  existing description queue, and make its output something an author can
  accept or rewrite rather than something already applied. Medium.
- **R7: repack, change log and worklist.** Medium.

**R0, R1 and R3 are the first thing worth sending anybody**: a cartridge
screened for student data, whose PDFs now declare what they are, with a
proof that not a word moved.

---

## 14. Where this stands

Updated 5 November 2026. Written after building R0 to R3, so the numbers
below are measured rather than estimated.

**Built:** R0 and R1 in `cartridge.py` and `invariance.py`; R2 and R3 in
`remediate.py`. Nothing yet writes a cartridge back out, which is R7.

**R0 found student work on its first run**, which is the argument for
its position in the order. Four of the 35 cartridges here carried caption
transcripts of four students, one introducing herself by name, inside
`course_settings/media_tracks.xml`. Not a `.vtt`, not under a path naming
submissions, so a screen written over filenames called all 35 clean. They
have since been stripped; 33 remain and 32 screen clear.

**R1 caught two bugs that would have shipped**, both only after the unit
tests passed and the real archive was read.

lxml's HTML serialiser removes the `<meta http-equiv="Content-Type">` a
page arrived with and writes nothing in its place, so the output was
UTF-8 bytes with no declaration and the next reader fell back to
Latin-1: every curly quotation mark in the course became mojibake. It
failed 1,960 of 2,532 real pages. That is corruption of the deliverable,
not a reporting problem.

And lxml invents an `ns0:` prefix for a `dc:title` added to an existing
XMP packet unless the namespace map is bound on the element, so the field
was written, nothing could read it back, and the stamp reported success.

**R2 over 2,532 real pages:** 2,446 `lang` written, 421 `scope` set,
1,099 headings moved to close skips. 164 headerless tables and 201
untitled iframes reported rather than guessed at. Zero words moved, zero
pages non-idempotent, zero unparsed.

**R3 over the PDFs:** `/Lang`, `/DisplayDocTitle` and `dc:title` stamped
in place, with the structure tree, the ink and the rest of the XMP packet
untouched. Of 1,030 readable PDFs, 477 are tagged, 520 carry an Info
title, 340 a `dc:title`, 157 a `/Lang` and 7 declare PDF/UA.

One finding there changed the design. **An Info `/Title` is usually not a
title.** Of the nine distinct ones across these cartridges that have an
Info title and no XMP title, seven are "Microsoft Word - <filename>" and
one is a DOI. Moving those would make a screen reader announce
"Microsoft Word - research 2.docx" as the document's name, so
`remediate.looks_like_a_title` turns them down and the gap is reported
instead. The same shape as `assess.PLACEHOLDER_ALTS`, found the same way.

**And a second one worth keeping.** `filters/heading-levels.lua` forces a
galley's outline to start at level 1, because a galley is a whole
document. A Canvas page is not: Canvas renders the page title as the
`<h1>` itself, and across these 2,532 pages the first body heading is
`h2` on 1,574 and `h1` on only 210. Applying the galley rule would have
put a second `h1` on most pages in the archive. R2 keeps the author's
base level and closes only the skips below it.

**R7 is built, and it was moved ahead of R4 to R6 on purpose.** Everything
before it was reachable from nowhere: three modules and a thousand lines
with no route and no job kind, which is the same gap `assess.py` had until
`/assess` existed. `repack.py` turns them into something that can be
handed to a person, at `/remediate`, as a job.

**R4, OCR, is deferred and the measurement is why.** It was put third on
the strength of the journal back-catalogue, where 473 of 473 pages were
scans. Course cartridges are born-digital: across 919 PDFs and 13,317
pages, 81 pages (0.6 percent) and 11 PDFs (1.2 percent, really two
documents duplicated) have no text layer. And there is no tesseract on the
development machine, so it could not be run once, which after three bugs
found only by running the real archive is not a thing to ship. It stays
specified and waits for a folder of scans.

**R5 is built, and it turned out to be an audit and not a fix.** The 777
Office documents first counted across the cartridges were the same files
recurring across exports: 125 distinct `.docx`, 13 `.pptx`, 26 `.doc` and
4 `.xlsx`. Every `.docx` already carries a default language, because Word
always writes one, so the one fix planned was a no-op. What remains is all
content: a picture with no description is words, a table with no header
row is a claim about what the table means, a document with no Heading
styles is a claim about its structure, and a slide with no title is
words. So `remediate.audit_docx`, `audit_pptx` and `audit_legacy` report
and change nothing, which is also the safest thing to do to a Word file:
round-tripping one through a library can silently drop comments, tracked
changes and objects it does not model. Over all 164 distinct files, zero
were modified.

**The picture finding reversed the first measurement.** Counting whether a
picture has a description said 15 of 162 were undescribed. Counting what
the description says gives a very different answer. Of 151 pictures that
carry one across these files, 4 were empty, 108 were a filename, a path
(`/tmp/beautiful_ai_exports/<uuid>.jpg`) or a bare "Picture 3", and about
40 were Microsoft's machine-written "Description automatically generated",
one of which reads "A diagram of a diagram of a diagram". Perhaps five
read as written by a person. The audit now reports 123 pictures with no
real description and 35 more owed review, and it keeps the second apart
from the first: a machine-written description is present, so no checker
flags it, and it is often wrong, which makes it the one kind of answer
worse than a marked gap.

**Legacy formats are reported and never converted.** 26 distinct `.doc`
files cannot be inspected in place. Converting one makes it checkable and
renames it, so every reference to it inside the cartridge would point at a
name that no longer exists. A remediation that broke the links it was
trying to make usable would be worse than the gap.

**Next:** R6 (the drafting queue). R4 (OCR) still waits for a folder of
scans and a tesseract install.
