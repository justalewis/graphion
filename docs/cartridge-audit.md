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
