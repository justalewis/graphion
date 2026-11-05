"""What remediating a journal's back catalogue would take, read without
ingesting it.

Every accessibility check in this codebase takes an article row and reads
`article.md`, so all of them run on content Graphion already holds. Taking
content in is `ingest_pdf`, which infers structure, writes an article
directory, and creates a draft; it is slow, it is destructive, and it is
the wrong thing to point at a stranger's back catalogue. So the question a
journal asks first, which is what remediating its archive would cost,
could not be answered at all without committing to the archive.

This answers it by reading. Nothing here writes: no article directory, no
database row, no file beside the PDF. A run over a folder someone sent
leaves the folder as it was.

What it reports divides in three, and the divisions are the point. The
conformance a PDF arrives with is a fact the file states, so it is read
off the catalog and the XMP and reported as read. What a checker makes of
that statement is a second fact and not the same one: six volumes of this
archive bound galleys that each declared PDF/UA-1 into issues that were
not tagged at all, so a declaration is where a check begins. verapdf and
pa11y answer that, and `--validate` is what runs them, because a JVM at
about 13 seconds a file and a headless browser beside it are not
something to do to a folder by accident. And what remediation would have
to produce is an estimate, because it is a count of work: a figure needs
a description somebody writes, a page with no text layer needs OCR and
then proofing. Those are reported as counts with the reasoning attached,
so a number can be checked rather than believed.

A checker's instance counts belong to the first register and not the
last. One untagged chapter here fails 1,462 checks across 11 rules, and
678 of those are content neither tagged nor marked as an artifact, which
tagging the document answers at once. Reporting that as 1,462 of anything
would be the inflation this module exists to avoid, in the one place a
number arrives already looking like work.

What it cannot know is reported too. Nothing here can tell how many
figures carry text as a picture, because nothing can tell a photograph of
a document from a photograph of anything else without looking, and that
number is the difference between an archive that is described and one
that satisfies WCAG 1.4.5. A report that left it out would read as though
the work were smaller than it is.

The readers are the pipeline's own, deliberately. pypdf resolves the
stream filters and the catalog; pdfplumber reads the text. An assessment
that read the page some other way would be predicting a pipeline other
than the one that would do the work.

HTML beside the PDFs is read the same way, and it is read more plainly.
An `<img>` either carries an `alt` or it does not, and there is no
structure tree to disagree with a raster count, so these numbers are exact
where the PDF's are a reading. The uncertainty moves instead: a figure set
as a CSS background is not in the markup at all, so an archive that sets
its figures that way reads here as one with no figures. `lint` owns the
judgements the two share, because the same figure must not be a draft in
one and described in the other.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pdf_ingest
import pdf_tags
import structure
import validators

# What a file declares about itself is read by `pdf_tags`, which is also
# what writes an XMP packet when it binds an issue. One module for both, so
# the reading cannot drift from the writing, and so the merge gate and this
# pass cannot answer the same question differently; this pass held a looser
# copy of the pdfuaid:part pattern until the two were collapsed.

# An image on most of a document's pages is furniture: a series wordmark,
# a rule, a publisher's device. `ingest_volume.image_digests` makes this
# call across a whole volume, where it is sound, because a figure does not
# repeat across chapters. One PDF is weaker evidence, so the threshold is
# conservative and the count is reported separately rather than folded
# into the figure total.
FURNITURE_MIN_PAGES = 3

# How many failed rules to carry per file, and how many of those to name in
# the prose. A file that is simply untagged fails ten or a dozen rules at
# once, and which ones they are is what makes the verdict actionable; the
# raw report carries every failing instance behind them, which for one
# chapter here is 1,462 entries, and none of that is kept.
MAX_FAILED_CLAUSES = 12
NAMED_IN_NOTES = 6
# Likewise for pa11y, whose issues repeat one code down a page.
MAX_NAMED_CODES = 10
# How long a table cell has to run before it is prose rather than a value.
# See `_is_layout_table` for what this was measured against.
PROSE_CELL = 300


@dataclass
class SymbolFont:
    """One font that sets pictures where a reader expects text."""

    family: str
    characters: int = 0
    pages: int = 0
    known: bool = False


@dataclass
class FailedClause:
    """One rule of ISO 14289-1 that a checker says the file breaks."""

    clause: str
    test_number: int
    description: str
    instances: int
    tags: tuple = ()

    @property
    def label(self) -> str:
        return f"{self.clause}-{self.test_number}"


@dataclass
class Assessment:
    """One PDF, read."""

    path: Path
    readable: bool = True
    error: str = ""
    pages: int = 0

    # Conformance as the file states it.
    tagged: bool = False
    declared_ua_part: Optional[int] = None
    xmp_title: str = ""
    info_title: str = ""
    lang: str = ""
    display_doctitle: bool = False

    # What a checker makes of that, which is a different fact. None means
    # nobody asked, or the tool could not answer; it is never read as a
    # verdict either way.
    verapdf: Optional[bool] = None
    verapdf_note: str = ""
    failed_clauses: list = field(default_factory=list)
    failed_clause_count: int = 0

    # Work remediation would have to produce.
    figures: int = 0
    furniture_images: int = 0
    tagged_figures: int = 0
    described_figures: int = 0
    pages_needing_ocr: int = 0
    pages_with_no_text: int = 0
    tables: Optional[int] = None
    clipping_pages: int = 0
    clipped_glyphs: int = 0
    cover_pages: int = 0
    link_annotations: int = 0
    untagged_links: int = 0
    unreadable_characters: int = 0
    symbol_pages: int = 0
    symbol_fonts: list = field(default_factory=list)
    tree_elements: int = 0
    tree_headings: int = 0
    text_chars: int = 0
    marked_chars: int = 0

    notes: list = field(default_factory=list)

    @property
    def conformant(self) -> bool:
        """Whether the file already claims what an audit looks for.

        Claiming is not passing. `pdf_tags` exists because six volumes of
        this archive bound galleys that each declared PDF/UA-1 into issues
        that were not tagged at all, so a declaration is the beginning of
        a check and not the end of one.
        """
        return bool(self.tagged and self.declared_ua_part and self.xmp_title)

    @property
    def tree_coverage(self) -> Optional[float]:
        """How much of the text sits inside the structure tree.

        Whether a tree exists is nearly free information: all 118 originals
        in this series carry one. What separates a tree worth reading from
        one worth nothing is how much of the chapter it reaches, and the
        archive's own split is wide enough that the question answers itself
        per file.

        None where no text was read, which is not zero. A file pdfplumber
        could not open has told you nothing about its tree, and reporting
        that as no coverage would be the one kind of claim this module
        exists to refuse.
        """
        if not self.text_chars:
            return None
        return self.marked_chars / self.text_chars * 100.0

    @property
    def tree_usable(self) -> bool:
        """Whether the tree covers enough of the text to be read from."""
        coverage = self.tree_coverage
        return (self.tagged and coverage is not None
                and coverage >= structure.USABLE_COVERAGE)

    @property
    def checked(self) -> bool:
        """Whether a checker reached a verdict on this file."""
        return self.verapdf is not None

    @property
    def contradicted(self) -> bool:
        """Declares conformance, and a checker says otherwise.

        The case the checker register exists for, and the one to read
        first in a prospect's archive: a file that states PDF/UA-1 has
        already been through somebody's pipeline, so what it is short of
        is usually narrow and nobody has been told.
        """
        return bool(self.conformant) and self.verapdf is False

    @property
    def undescribed_figures(self) -> int:
        """Figures still owing a description.

        Where the document has a structure tree, the tree decides: it
        states how many figures it holds and how many of those carry an
        `/Alt`, and that is the document speaking about itself. The raster
        count is the fallback for an untagged file, which states nothing.

        Subtracting the described count from the raster count instead
        looks equivalent and is not, for exactly the files that are
        tagged. A Writing Spaces `source.pdf` tags six figures, describes
        one, and embeds a single raster the scan recognises, because the
        other five are vector art or sit under the size floor. Read the
        wrong way round that chapter owes nothing; read this way it owes
        five, which is what the page shows.
        """
        if self.tagged_figures:
            return max(0, self.tagged_figures - self.described_figures)
        return self.figures

    @property
    def figures_found(self) -> int:
        """The count this reports, from whichever reading is authoritative."""
        return self.tagged_figures or self.figures


# An alt text that is a label rather than a description. The filename of
# the image itself is the commonest, and is caught by comparison rather
# than by this list; these are the words a converter writes when it has
# nothing to say. Matched whole and lowercased, so a description opening
# "Photograph of a whiteboard" is not caught by "photograph".
PLACEHOLDER_ALTS = frozenset({
    "image", "images", "img", "picture", "photo", "photograph", "graphic",
    "figure", "fig", "illustration", "untitled", "screenshot", "diagram",
    "chart", "graph", "logo", "icon", "alt", "alt text", "description",
    "placeholder", "no description", "image description",
})


@dataclass
class HtmlAssessment:
    """One HTML page, read, and then checked if asked.

    The same two registers the PDF side keeps, and a third thing worth
    knowing about the first: HTML states what it is far more plainly than a
    PDF does. An `<img>` either carries an `alt` or it does not, and there
    is no structure tree to disagree with a raster count. So these numbers
    are exact where the PDF's are a reading, and the uncertainty moves
    somewhere else: a figure set as a CSS background is not in the markup at
    all, and an archive that sets its figures that way reads here as one
    with no figures.

    What no reading settles is the same thing it is for a PDF: whether the
    words in a picture are words. That is WCAG 1.4.5, it is the number that
    decides whether an archive is finished, and nothing but looking answers
    it.
    """

    path: Path
    readable: bool = True
    error: str = ""

    # What the page states about itself.
    lang: str = ""
    title: str = ""
    has_main: bool = False
    headings: int = 0
    h1s: int = 0
    skipped_heading_levels: int = 0

    # Work remediation would have to produce.
    images: int = 0
    images_no_alt: int = 0
    images_placeholder_alt: int = 0
    images_caption_as_alt: int = 0
    images_alt_doubles_as_caption: int = 0
    images_decorative: int = 0
    images_described: int = 0
    svgs: int = 0
    svgs_unnamed: int = 0
    iframes_untitled: int = 0
    media: int = 0
    media_without_captions: int = 0
    tables: int = 0
    tables_without_headers: int = 0
    tables_laid_out: int = 0
    equations: int = 0
    links: int = 0
    links_without_text: int = 0
    controls_unlabelled: int = 0

    # What a checker makes of it.
    clean: Optional[bool] = None
    pa11y_note: str = ""
    errors: int = 0
    warnings: int = 0
    notices: int = 0
    codes: list = field(default_factory=list)

    notes: list = field(default_factory=list)

    @property
    def checked(self) -> bool:
        """Whether pa11y reached a verdict on this page."""
        return self.clean is not None

    @property
    def images_owed(self) -> int:
        """Images that still need somebody to write something.

        `alt=""` is not here. It is a claim that the image carries nothing
        a reader needs, which is the right answer for a rule or an
        ornament, and counting it as work would quote a journal for its own
        decoration. It is counted on its own line instead, because an
        archive that emptied every alt to quiet a checker looks identical
        to a described one on a count of failures alone.
        """
        return (self.images_no_alt + self.images_placeholder_alt
                + self.images_caption_as_alt)


def _verdict(report: dict) -> Optional[bool]:
    """Compliance as the report states it, or None where it states none.

    Read off the report rather than off the exit code. verapdf exits
    non-zero both for a file that is not compliant and for a file it could
    not process, and only the first of those is a verdict; taking the exit
    code would turn a tool failure into a finding about the document.
    """
    try:
        results = report["report"]["jobs"][0]["validationResult"]
    except (KeyError, IndexError, TypeError):
        return None
    if not results:
        return None
    return all(bool(result.get("compliant")) for result in results)


def _failed_clauses(report: dict) -> list:
    """The rules verapdf says the file breaks, compacted.

    The raw report carries every failing instance. For one untagged chapter
    of this archive that is 1,462 of them across 11 rules, which would make
    the assessment larger than the file it describes, and it invites the
    reading this module most wants to avoid: 678 of those instances are
    content neither tagged nor marked as an artifact, and tagging the
    document answers all 678 at once. The rules are the useful unit, and
    the instance count stays beside each one as a size rather than as work.
    """
    try:
        jobs = report["report"]["jobs"]
    except (KeyError, TypeError):
        return []
    out = []
    for job in jobs or []:
        for result in job.get("validationResult") or []:
            details = result.get("details") or {}
            for summary in details.get("ruleSummaries") or []:
                if str(summary.get("ruleStatus") or "FAILED").upper() == "PASSED":
                    continue
                out.append(FailedClause(
                    clause=str(summary.get("clause") or ""),
                    test_number=int(summary.get("testNumber") or 0),
                    description=str(summary.get("description") or ""),
                    instances=int(summary.get("failedChecks") or 0),
                    tags=tuple(str(t) for t in (summary.get("tags") or ())),
                ))
    out.sort(key=lambda clause: -clause.instances)
    return out


def _run_verapdf(assessment: Assessment, path: Path) -> None:
    """Check what the file declares, rather than taking it.

    `conformant` reads the statement: a structure tree, a declared part, a
    dc:title. This reads the verdict, and the two are different facts. Six
    volumes of this archive bound galleys that each declared PDF/UA-1 into
    issues that were not tagged at all, which is what `contradicted` is for.

    A tool that is not on PATH leaves `verapdf` None, which is not a verdict
    and is never counted as one. `validate_galleys.py` refuses to start in
    that case instead of recording it, because a register row is the newest
    answer for its kind and a non-answer written there would bury a real
    one. Nothing here is stored, so there is nothing to bury, and the rest
    of the reading is still worth having.
    """
    if not validators.verapdf_available():
        assessment.verapdf_note = (
            "verapdf is not on PATH, so nothing checked what this file "
            "declares about itself.")
        return
    _passed, raw = validators.run_verapdf(path)
    if not isinstance(raw, dict):
        assessment.verapdf_note = "verapdf returned nothing readable."
        return
    if raw.get("error"):
        assessment.verapdf_note = str(raw["error"])
        return
    verdict = _verdict(raw)
    if verdict is None:
        assessment.verapdf_note = (
            "verapdf ran and reported no validation result, so this file "
            "has not been checked.")
        return
    assessment.verapdf = verdict
    clauses = _failed_clauses(raw)
    assessment.failed_clause_count = len(clauses)
    assessment.failed_clauses = clauses[:MAX_FAILED_CLAUSES]


def _text_after(element) -> str:
    """Whatever the page prints after this element, inside its parent.

    A figure and its caption are commonly one paragraph: the image, a line
    break, and the caption under it. That is how Graphion's own galleys set
    one, because it is how the reconstruction writes it, and `<figcaption>`
    is the other way a page says the same thing. Both are read, and the
    first that answers wins.
    """
    parts = [element.tail or ""]
    for sibling in element.itersiblings():
        parts.append(sibling.text_content())
        parts.append(sibling.tail or "")
    return " ".join(" ".join(parts).split())[:400]


def _caption_near(image) -> str:
    """The caption this image is set under, from wherever the page keeps it."""
    figure = next(image.iterancestors("figure"), None)
    if figure is not None:
        caption = figure.find(".//figcaption")
        if caption is not None:
            return " ".join(caption.text_content().split())[:400]
    return _text_after(image)


def _is_decorative(element) -> bool:
    """Whether the markup says this image carries nothing a reader needs.

    Three ways of saying one thing, and all three are claims rather than
    omissions: an empty alt, a presentational role, and `aria-hidden`. A
    reader skips the image either way, so an archive that reached for one
    of these to quiet a checker reads the same as one whose rules really
    are rules, and that is what the separate count is for.
    """
    if element.get("aria-hidden") == "true":
        return True
    if (element.get("role") or "").lower() in ("presentation", "none"):
        return True
    return element.get("alt") == ""


def _is_placeholder_alt(alt: str, src: str) -> bool:
    """Whether this alt text names the image rather than describing it.

    The filename is the commonest, and it is what a converter writes when
    the source had nothing: `alt="image001.jpg"` tells a reader the number
    of a file they cannot see. Compared with separators flattened, because
    a converter that tidies the stem into words has still said nothing.
    """
    def _flatten(text: str) -> str:
        return " ".join(text.replace("_", " ").replace("-", " ").split())

    raw = " ".join(alt.lower().split())
    flat = _flatten(raw)
    if raw in PLACEHOLDER_ALTS or flat in PLACEHOLDER_ALTS:
        return True
    name = (src or "").rsplit("/", 1)[-1].lower()
    if not name:
        return False
    stem = name.rsplit(".", 1)[0]
    # Both spellings of both, because a converter writes the filename as it
    # found it and a tidier one writes the stem as words, and neither has
    # said anything about the picture.
    return raw in (name, stem, _flatten(name), _flatten(stem)) or flat in (
        name, stem, _flatten(name), _flatten(stem))


def _is_layout_table(table) -> bool:
    """Whether this table is a page laid out in columns rather than data.

    A declaration first and an inference second, the way `_is_decorative`
    reads an image. `role="presentation"` is the markup saying so, and a
    page that says it is taken at its word.

    Graphion's own galleys do not say it, and that is a finding rather than
    an oversight. A filter emitting the role on exactly these tables makes
    pa11y fail them on WCAG F92, "role is presentation but contains child
    elements with semantic meaning", and it goes on failing with the
    `<colgroup>` suppressed, because `<tbody>`, `<tr>` and `<td>` are the
    children it means. ARIA says the role propagates to a table's required
    owned elements and the screen readers honour it, so the checker is
    stricter than the spec, and `docs/accessibility-service.md` carries the
    choice that leaves.

    Where nothing is declared the cells answer, because a cell holding
    running prose is not a value. Measured over this archive's 65 rendered
    tables, the 41 with a header cell have a longest cell of 124 characters
    at the median and 1,419 at the most, and the 24 with none have a
    longest cell of 673 at the least; `PROSE_CELL` sits in that gap with
    room on both sides. The inference is only reached for a table that has
    no header cell at all, which is already unusual for data.
    """
    if (table.get("role") or "").lower() in ("presentation", "none"):
        return True
    return any(len(" ".join(cell.text_content().split())) >= PROSE_CELL
               for cell in table.xpath(".//td"))


def _named(element) -> bool:
    """Whether this element carries an accessible name of any kind."""
    if (element.get("aria-label") or "").strip():
        return True
    if (element.get("aria-labelledby") or "").strip():
        return True
    if (element.get("title") or "").strip():
        return True
    child = element.find(".//title")
    return child is not None and bool((child.text or "").strip())


def _read_html_shell(assessment: HtmlAssessment, tree) -> None:
    """What the page states about itself: language, title, landmark, heads."""
    root = tree.getroottree().getroot()
    assessment.lang = str(root.get("lang") or root.get("xml:lang") or "").strip()
    title = tree.find(".//title")
    if title is not None:
        assessment.title = " ".join((title.text or "").split())
    assessment.has_main = (tree.find(".//main") is not None
                           or tree.xpath("//*[@role='main']") != [])

    levels = []
    for heading in tree.xpath("//h1|//h2|//h3|//h4|//h5|//h6"):
        levels.append(int(heading.tag[1]))
    assessment.headings = len(levels)
    assessment.h1s = levels.count(1)
    # A level skipped is a reader stepping from a section head into a
    # sub-sub-head with nothing between, which is what a heading outline is
    # for. Counted rather than judged: a page may well open at h2 inside a
    # site that sets the h1 elsewhere.
    for before, after in zip(levels, levels[1:]):
        if after > before + 1:
            assessment.skipped_heading_levels += 1


def _read_html_images(page: HtmlAssessment, tree) -> None:
    """Every image, in the five states an alt text can be in.

    The same five `lint.figure_state` keeps for a figure in Markdown, and
    the caption test is `lint.alt_is_caption` rather than a second copy of
    it: a window that differed between the two would report one figure as a
    draft here and as described there.
    """
    import lint

    for image in tree.xpath("//img"):
        page.images += 1
        alt = image.get("alt")
        if alt is None:
            page.images_no_alt += 1
            continue
        if _is_decorative(image):
            page.images_decorative += 1
            continue
        alt = " ".join(alt.split())
        if _is_placeholder_alt(alt, image.get("src") or ""):
            page.images_placeholder_alt += 1
            continue
        caption = _caption_near(image)
        if lint.alt_is_caption(alt, caption):
            # The markup states these two cases identically and the label is
            # what separates them. A caption names a figure and carries its
            # number, so an alt that matches a labelled caption is the
            # caption copied into the alt slot, which is work. An alt that
            # matches an unlabelled one is as likely to be a description the
            # renderer also printed: Pandoc makes a `<figure>` of a lone
            # image and uses its alt as the `<figcaption>`, which is how 32
            # of this archive's own hand-written descriptions appear twice
            # on the page. Counting those as owed would quote a journal for
            # work it has already paid for.
            if lint.looks_like_a_caption(caption):
                page.images_caption_as_alt += 1
            else:
                page.images_alt_doubles_as_caption += 1
            continue
        page.images_described += 1

    for svg in tree.xpath("//svg"):
        page.svgs += 1
        if not _is_decorative(svg) and not _named(svg):
            page.svgs_unnamed += 1


def _read_html_elements(page: HtmlAssessment, tree) -> None:
    """The rest of what the markup states plainly."""
    for frame in tree.xpath("//iframe"):
        if not (frame.get("title") or "").strip():
            page.iframes_untitled += 1

    for player in tree.xpath("//video|//audio"):
        page.media += 1
        tracks = [t for t in player.findall(".//track")
                  if (t.get("kind") or "").lower() in ("captions", "subtitles")]
        if not tracks:
            page.media_without_captions += 1

    for table in tree.xpath("//table"):
        page.tables += 1
        # The header row is what lets a screen reader name the column a
        # cell is in, which is the same reason ingest writes a pipe table
        # rather than loose lines. A table that is a page layout owes no
        # headers and is counted apart: reporting it as a shortfall would
        # quote a journal for naming columns that are not columns.
        if table.find(".//th") is not None:
            continue
        if _is_layout_table(table):
            page.tables_laid_out += 1
        else:
            page.tables_without_headers += 1

    # MathML is read aloud by a screen reader, so an equation marked up
    # this way owes nothing. Counted as a fact rather than as work, for the
    # reason `filters/math-alt.lua` is gated on the Typst writer: the HTML
    # and EPUB galleys need none of it. An equation set as a picture is
    # already among the images above, where it belongs.
    page.equations = len(tree.xpath("//math"))

    for link in tree.xpath("//a[@href]"):
        page.links += 1
        if " ".join(link.text_content().split()):
            continue
        if _named(link):
            continue
        if any((img.get("alt") or "").strip() for img in link.xpath(".//img")):
            continue
        page.links_without_text += 1

    labelled_ids = {
        (label.get("for") or "").strip()
        for label in tree.xpath("//label[@for]")
    }
    for control in tree.xpath("//input|//select|//textarea"):
        kind = (control.get("type") or "").lower()
        if kind in ("hidden", "submit", "button", "reset", "image"):
            continue
        if _named(control):
            continue
        if (control.get("id") or "").strip() in labelled_ids:
            continue
        if next(control.iterancestors("label"), None) is not None:
            continue
        page.controls_unlabelled += 1


def read_html(path: Path) -> HtmlAssessment:
    """Read one HTML page. Writes nothing.

    Parsed with lxml's HTML parser, which is already a dependency and is
    what `jats.py` and `crossref.py` use. Tolerant on purpose: this is
    pointed at pages somebody else produced, and a page that will not parse
    strictly is a page a browser still renders.
    """
    from lxml import html as lxml_html

    page = HtmlAssessment(path=Path(path))
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        page.readable = False
        page.error = f"{type(exc).__name__}: {exc}"
        return page
    if not text.strip():
        page.readable = False
        page.error = "the file is empty"
        return page
    try:
        tree = lxml_html.document_fromstring(text)
    except Exception as exc:
        page.readable = False
        page.error = f"{type(exc).__name__}: {exc}"
        return page

    _read_html_shell(page, tree)
    _read_html_images(page, tree)
    _read_html_elements(page, tree)
    return page


def _run_pa11y(page: HtmlAssessment, validate: bool) -> None:
    """What a checker makes of the page, where one was asked to look."""
    import collections

    if not validate:
        page.pa11y_note = "Not checked; pa11y is what would."
        return
    if not validators.pa11y_available():
        page.pa11y_note = "pa11y is not on PATH, so this page was not checked."
        return
    clean, issues = validators.run_pa11y(page.path)
    if issues and isinstance(issues[0], dict) and issues[0].get("error"):
        page.pa11y_note = str(issues[0]["error"])
        return
    page.clean = bool(clean)
    counts: collections.Counter = collections.Counter()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        kind = str(issue.get("type") or "")
        if kind == "error":
            page.errors += 1
        elif kind == "warning":
            page.warnings += 1
        elif kind == "notice":
            page.notices += 1
        counts[str(issue.get("code") or "")] += 1
    page.codes = counts.most_common(MAX_NAMED_CODES)


def assess_html(path: Path, validate: bool = False) -> HtmlAssessment:
    """Read one HTML page, and check it where asked. Writes nothing.

    Reading is always done, because it costs what reading a file costs.
    `validate` is what starts pa11y, which launches a headless browser, and
    it is the same flag that starts verapdf over the PDFs beside it.
    """
    page = read_html(path)
    if page.readable:
        _run_pa11y(page, validate)
    _add_html_notes(page)
    return page


def _add_html_notes(page: HtmlAssessment) -> None:
    """What the counts mean, and what no reading of a page can settle."""
    if not page.readable:
        return

    missing = []
    if not page.lang:
        missing.append("no language on the html element")
    if not page.title:
        missing.append("no title")
    if not page.has_main:
        missing.append("no main landmark")
    if page.headings and not page.h1s:
        missing.append("no h1")
    if missing:
        page.notes.append("Arrives with " + "; ".join(missing) + ".")
    if page.skipped_heading_levels:
        page.notes.append(
            f"{page.skipped_heading_levels} place(s) where the heading "
            f"outline skips a level. A page may open at h2 inside a site "
            f"that sets the h1 elsewhere, so this is counted and not "
            f"failed.")

    if page.images:
        if page.images_described:
            page.notes.append(
                f"{page.images_described} of {page.images} image(s) already "
                f"carry a description, so that much is not work still owed.")
        if page.images_no_alt:
            page.notes.append(
                f"{page.images_no_alt} image(s) carry no alt attribute at "
                f"all, so a reader is told the file name or nothing.")
        if page.images_placeholder_alt:
            page.notes.append(
                f"{page.images_placeholder_alt} image(s) have alt text that "
                f"names the image rather than describing it, which is what a "
                f"converter writes when the source said nothing.")
        if page.images_caption_as_alt:
            page.notes.append(
                f"{page.images_caption_as_alt} image(s) carry their own "
                f"caption as alt text. That is a reasonable starting point "
                f"and it is not a description: a caption says what a figure "
                f"is called.")
        if page.images_alt_doubles_as_caption:
            page.notes.append(
                f"{page.images_alt_doubles_as_caption} image(s) carry the "
                f"same text as alt text and as the caption printed with "
                f"them, and the markup cannot say which way round it went. "
                f"A caption copied into the alt slot is work still owed; a "
                f"description the renderer also printed as the caption is "
                f"work already done. They are counted here and in neither "
                f"total.")
        if page.images_decorative:
            page.notes.append(
                f"{page.images_decorative} image(s) are marked as carrying "
                f"nothing a reader needs. That is the right answer for a "
                f"rule or an ornament and the wrong one for a figure, and "
                f"only looking tells the two apart.")
        page.notes.append(
            "How many of these set their words as a picture is not in any "
            "count here and cannot be read off the markup (WCAG 1.4.5). Nor "
            "is a figure set as a CSS background image, which is not in the "
            "markup at all.")
    if page.svgs_unnamed:
        page.notes.append(
            f"{page.svgs_unnamed} of {page.svgs} inline SVG(s) carry no "
            f"accessible name and are not marked decorative, so they reach a "
            f"reader as nothing.")
    if page.media_without_captions:
        page.notes.append(
            f"{page.media_without_captions} of {page.media} media element(s) "
            f"carry no captions track. Captioning is transcription and then "
            f"timing, which is a different order of work from the rest.")
    if page.tables_without_headers:
        page.notes.append(
            f"{page.tables_without_headers} of {page.tables} table(s) carry "
            f"no header cell, so nothing names the column a cell is in.")
    if page.tables_laid_out:
        page.notes.append(
            f"{page.tables_laid_out} of {page.tables} table(s) hold running "
            f"prose rather than values and are read as a page laid out in "
            f"columns, which owes no headers. One that says so with "
            f"role=\"presentation\" is read out of the way; one that does "
            f"not is a table a reader is told they have entered.")
    if page.iframes_untitled:
        page.notes.append(
            f"{page.iframes_untitled} iframe(s) carry no title, so a reader "
            f"moving between frames is told nothing about what is in one.")
    if page.links_without_text:
        page.notes.append(
            f"{page.links_without_text} of {page.links} link(s) carry no "
            f"text a reader can hear.")
    if page.controls_unlabelled:
        page.notes.append(
            f"{page.controls_unlabelled} form control(s) carry no label.")
    if page.equations:
        page.notes.append(
            f"{page.equations} equation(s) are marked up as MathML, which a "
            f"screen reader reads, so they owe nothing. An equation set as a "
            f"picture is among the images above.")

    if not page.checked and page.pa11y_note:
        page.notes.append(page.pa11y_note)


def _read_catalog(assessment: Assessment, reader) -> None:
    """The conformance the file states, read off the catalog and the XMP."""
    root = reader.trailer["/Root"]
    assessment.tagged = "/StructTreeRoot" in root
    assessment.lang = str(root.get("/Lang") or "")
    prefs = root.get("/ViewerPreferences") or {}
    assessment.display_doctitle = bool(prefs.get("/DisplayDocTitle"))
    try:
        assessment.info_title = str((reader.metadata or {}).get("/Title") or "")
    except Exception:
        assessment.info_title = ""
    packet = pdf_tags.xmp_packet_text(reader)
    assessment.declared_ua_part = pdf_tags.declared_ua_part(packet)
    assessment.xmp_title = pdf_tags.declared_title(packet)


def _read_links(assessment: Assessment, reader) -> None:
    """Link annotations, and how many can reach a tag.

    A link is tagged when its annotation carries a `/StructParent` that
    indexes the element holding its `/OBJR`. Counting annotations that
    merely exist reports every link in a merged issue as tagged while an
    audit reports every one of them untagged, which is the failure
    `pdf_tags` was written to end, so the test here is the key and not the
    annotation.
    """
    for page in reader.pages:
        try:
            annots = page.get("/Annots") or []
        except Exception:
            continue
        for ref in annots:
            try:
                annot = ref.get_object()
            except Exception:
                continue
            if str(annot.get("/Subtype") or "") != "/Link":
                continue
            assessment.link_annotations += 1
            if "/StructParent" not in annot:
                assessment.untagged_links += 1


def _read_structure(assessment: Assessment, outline) -> None:
    """What the tree states: its figures, its headings, and how big it is.

    One walk, through `structure.walk`, rather than a second copy of one
    here. Counting a figure needs the tree and so does saying whether the
    tree is worth reading from, and two walkers answering about the same
    elements is the shape this codebase keeps finding wrong.

    Only elements whose role is `/Figure` are counted as figures: an `/Alt`
    sits on whatever element needs one, equations included, so counting
    them all would answer a different question. A tagged PDF states how
    many figures it holds and how many are described, so an assessment that
    counted every raster as work still owed would quote a journal for
    descriptions it already has.
    """
    assessment.tree_elements = len(outline.elements)
    for element in outline.elements:
        if element.is_figure:
            assessment.tagged_figures += 1
            if element.alt:
                assessment.described_figures += 1
        elif element.is_heading:
            assessment.tree_headings += 1


def _read_images(assessment: Assessment, reader) -> None:
    """Figures, separated from the furniture that repeats down the book."""
    import collections

    pages_per_digest: collections.Counter = collections.Counter()
    for page in reader.pages:
        try:
            images = list(page.images)
        except Exception:
            continue
        seen_here = set()
        for image in images:
            try:
                width, height = image.image.size
            except Exception:
                continue
            if not pdf_ingest.big_enough(width, height):
                continue
            digest = pdf_ingest._digest(image.data)
            if digest not in seen_here:
                seen_here.add(digest)
                pages_per_digest[digest] += 1
    for _digest_value, on_pages in pages_per_digest.items():
        if on_pages >= FURNITURE_MIN_PAGES:
            assessment.furniture_images += 1
        else:
            assessment.figures += 1


def _page_symbol_fonts(page) -> dict:
    """Which fonts set pictures on this page, and how many characters each.

    Two signals, and the second is what makes this readable for a source
    nobody here has seen. A family `pdf_ingest.symbol_family` knows is one
    ingest can already translate, which is work this pipeline has done. A
    character in the private use area is unreadable whatever set it: a
    private use codepoint means nothing to a screen reader, and Typst
    validates PDF/UA rather than declaring it, so one of them aborts the
    compile and costs the chapter its conformance. The font that produced
    it is the thing a mapping has to be written against.

    A Wingdings run that lands on ordinary punctuation rather than in the
    private use area is caught by the first signal and missed by the
    second, which is why both are here: an open circle arriving as `{` is
    readable text as far as any codepoint test can tell.
    """
    import collections

    found: collections.Counter = collections.Counter()
    try:
        chars = page.chars
    except Exception:
        return found
    for char in chars:
        font = char.get("fontname") or ""
        text = char.get("text") or ""
        if not text:
            continue
        family = font.split("+")[-1].strip().lower()
        if pdf_ingest.symbol_family(font) is not None:
            found[family] += 1
        elif any(0xE000 <= ord(c) <= 0xF8FF for c in text):
            found[family] += 1
    return found


def _read_text(assessment: Assessment, pdf, deep: bool) -> None:
    """Text, and what its absence costs.

    A page carrying images and no text layer is a scan. Remediation there
    is OCR and then proofing it, which is a different order of work from
    writing a description, so the two are counted apart rather than summed
    into one number that would mean nothing.
    """
    import collections
    import lint

    body = []
    # Accumulated across the pages and folded into `symbol_fonts` below, so
    # a family is reported once with its totals rather than once a page.
    symbols: collections.Counter = collections.Counter()
    symbol_pages: collections.Counter = collections.Counter()
    for index, page in enumerate(pdf.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
        here = _page_symbol_fonts(page)
        if here:
            assessment.symbol_pages += 1
            for family, count in here.items():
                symbols[family] += count
                symbol_pages[family] += 1
        # Counted in the loop that is already walking the chars, because
        # how much of the text the structure tree reaches is what separates
        # a tree worth reading from one that tags the cover page.
        try:
            for char in page.chars:
                assessment.text_chars += 1
                if char.get("mcid") is not None:
                    assessment.marked_chars += 1
        except Exception:
            pass
        if text.strip():
            body.append(text)
        else:
            assessment.pages_with_no_text += 1
            try:
                if page.images:
                    assessment.pages_needing_ocr += 1
            except Exception:
                pass
        # The real reading, not the prefilter. `_may_clip` is deliberately
        # loose: it matches the least a page must contain for the operator
        # to be there at all, which over this archive is 197 pages against
        # the 15 that actually clip. Reporting its hits as clipped ink
        # would be wrong thirteen times in fourteen. `clipped_glyphs` calls
        # it first anyway, so the cheap test still spares most pages the
        # second parse.
        try:
            clipped = pdf_ingest.clipped_glyphs(page)
        except Exception:
            clipped = frozenset()
        if clipped:
            assessment.clipping_pages += 1
            assessment.clipped_glyphs += len(clipped)
        if deep:
            try:
                assessment.tables = (assessment.tables or 0) + len(
                    pdf_ingest.find_page_tables(page))
            except Exception:
                pass
        if index == 0:
            try:
                lines = pdf_ingest._page_lines(page, 1)
                assessment.cover_pages = pdf_ingest.count_cover_pages(lines)
            except Exception:
                pass

    # The same check the lint pass runs, called rather than copied: a
    # second reader for this has been written wrong here before. The
    # count comes off `units` rather than out of the summary, which this
    # read with a regex over the other module's prose until the check
    # carried the number itself.
    result = lint.check_unreadable_characters({}, {}, "\n".join(body))
    assessment.unreadable_characters = result.units.get(
        "unreadable-characters", 0)

    assessment.symbol_fonts = [
        # Asked of `symbol_family` rather than of the table behind it, which
        # is the public way in and the one place that knows how a font name
        # is matched; it is idempotent on a family already normalised.
        SymbolFont(family=family, characters=count,
                   pages=symbol_pages[family],
                   known=pdf_ingest.symbol_family(family) is not None)
        for family, count in symbols.most_common()
    ]


def _open(assessment: Assessment, path):
    """The reader, or None with the reason recorded on the assessment."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(path))
        assessment.pages = len(reader.pages)
        return reader
    except Exception as exc:
        assessment.readable = False
        assessment.error = f"{type(exc).__name__}: {exc}"
        return None


def read_declaration(path: Path) -> Assessment:
    """What a PDF states about its own conformance, and nothing else.

    `assess_pdf` reads this on its way to counting what remediating an
    archive would cost, which means opening every page. A galley that has
    just been rendered needs only the first part of that, and needs it
    often enough that the rest is worth not doing: this is the catalog and
    the XMP, and no page is parsed.

    Separate entry point, one reader. `_read_catalog` is what decides, and
    what a packet declares is read by `pdf_tags`, beside the code that
    writes one, because a second copy of a conformance reading drifts from
    the first.
    """
    assessment = Assessment(path=Path(path))
    reader = _open(assessment, path)
    if reader is not None:
        _read_catalog(assessment, reader)
    return assessment


def assess_pdf(path: Path, deep: bool = False,
               validate: bool = False) -> Assessment:
    """Read one PDF. Writes nothing, anywhere, ever.

    `validate` runs verapdf over it, which is off by default because it is
    a JVM process at about 13 seconds a file: a folder of 118 chapters is
    half an hour, where the rest of this pass is seconds. Both tools write
    their report to stdout and leave the folder alone, which is what lets
    them be called from here at all; `validate_galleys.py` is what puts a
    report on disk, and it writes into Graphion's own content rather than
    into a folder somebody sent.
    """
    import pdfplumber

    assessment = Assessment(path=Path(path))
    reader = _open(assessment, path)
    if reader is None:
        return assessment

    _read_catalog(assessment, reader)
    _read_links(assessment, reader)
    _read_structure(assessment, structure.read(path, text=False))
    _read_images(assessment, reader)

    try:
        with pdfplumber.open(str(path)) as pdf:
            _read_text(assessment, pdf, deep)
    except Exception as exc:
        assessment.notes.append(
            f"Text could not be read ({type(exc).__name__}); the counts "
            f"above cover structure only.")

    if validate:
        _run_verapdf(assessment, Path(path))

    _add_notes(assessment)
    return assessment


def _add_notes(assessment: Assessment) -> None:
    """What the counts mean, and what no reading can settle."""
    if assessment.conformant:
        said = "Already tagged, titled and declaring PDF/UA-1."
        if assessment.verapdf is None:
            said += " A declaration is not a pass; verapdf is what checks it."
        assessment.notes.append(said)
    else:
        missing = []
        if not assessment.tagged:
            missing.append("no structure tree, so it is untagged")
        if not assessment.declared_ua_part:
            missing.append("no declared PDF/UA conformance")
        if not assessment.xmp_title:
            missing.append(
                "no dc:title in XMP"
                + (", though the Info dictionary carries one"
                   if assessment.info_title else ""))
        if not assessment.lang:
            missing.append("no document language")
        if missing:
            assessment.notes.append("Arrives with " + "; ".join(missing) + ".")

    if assessment.figures_found:
        owed = assessment.undescribed_figures
        if assessment.described_figures:
            assessment.notes.append(
                f"{assessment.described_figures} of "
                f"{assessment.tagged_figures} figure element(s) in the "
                f"structure tree already carry a description, so that much "
                f"is not work still owed.")
        if owed:
            assessment.notes.append(
                f"{owed} figure(s) would each need a description written by "
                f"hand. How many of them carry text as a picture cannot be "
                f"read off the page, and that is a separate obligation "
                f"(WCAG 1.4.5) that describing them does not meet.")
        if assessment.tagged_figures and assessment.figures != (
                assessment.tagged_figures):
            assessment.notes.append(
                f"The structure tree names {assessment.tagged_figures} "
                f"figure(s) and {assessment.figures} embedded raster(s) "
                f"were found. The tree is what the counts above follow; "
                f"the difference is usually vector art, or an image under "
                f"the size floor a figure has to clear.")
    if assessment.furniture_images:
        assessment.notes.append(
            f"{assessment.furniture_images} image(s) repeat on "
            f"{FURNITURE_MIN_PAGES} or more pages and are read as furniture "
            f"rather than figures. Across a whole volume that call is sound; "
            f"inside one file it is worth checking.")
    if assessment.pages_needing_ocr:
        assessment.notes.append(
            f"{assessment.pages_needing_ocr} page(s) carry images and no "
            f"text layer, so they are scans. OCR and the proofing after it "
            f"are a different order of work from the rest of this.")
    if assessment.clipping_pages:
        assessment.notes.append(
            f"{assessment.clipped_glyphs} character(s) across "
            f"{assessment.clipping_pages} page(s) are drawn and then clipped "
            f"away, so the page prints them nowhere. Ingest drops them; a "
            f"reader that does not would publish text the book does not "
            f"show, interleaved into the prose beside it.")
    if assessment.cover_pages:
        assessment.notes.append(
            f"{assessment.cover_pages} cover page(s) ahead of the text, "
            f"which ingest drops so the chapter's own title and byline are "
            f"not read twice.")
    if assessment.untagged_links:
        assessment.notes.append(
            f"{assessment.untagged_links} of {assessment.link_annotations} "
            f"link annotation(s) carry no /StructParent, so they cannot "
            f"reach a tag whatever the structure tree says.")
    if assessment.unreadable_characters:
        assessment.notes.append(
            f"{assessment.unreadable_characters} character(s) in the text "
            f"are private use or control codepoints, which usually means a "
            f"symbol font. They read as nothing to a screen reader.")
    if assessment.symbol_fonts:
        known = [f for f in assessment.symbol_fonts if f.known]
        unknown = [f for f in assessment.symbol_fonts if not f.known]
        assessment.notes.append(
            f"{assessment.symbol_pages} page(s) set type in a symbol font, "
            f"which stores pictures at ordinary character codes: a Wingdings "
            f"open circle extracts as an opening brace and a smiling face as "
            f"a J, and neither reads as what the page shows.")
        if known:
            assessment.notes.append(
                "Already handled: " + ", ".join(
                    f"{f.family} ({f.characters} character(s) on {f.pages} "
                    f"page(s))" for f in known[:6])
                + ". Ingest translates these.")
        if unknown:
            assessment.notes.append(
                "Not yet handled: " + ", ".join(
                    f"{f.family} ({f.characters} character(s) on {f.pages} "
                    f"page(s))" for f in unknown[:6])
                + f". Each font is one reading somebody does off the page "
                f"and writes down once, not a count of characters: only the "
                f"font knows which picture sits at which code, and the font "
                f"name is gone by the time the text reaches the cleanups.")
    if assessment.verapdf is True:
        assessment.notes.append(
            "verapdf confirms PDF/UA-1, so what the file declares holds up.")
    elif assessment.verapdf is False:
        opener = (
            "This file declares PDF/UA-1 and does not pass it. "
            if assessment.contradicted else "")
        assessment.notes.append(
            f"{opener}verapdf finds {assessment.failed_clause_count} rule(s) "
            f"of ISO 14289-1 broken. The instance counts beside them are a "
            f"size and not a quantity of work: one rule here is commonly "
            f"every untagged run of text on every page, and tagging the "
            f"document answers all of them at once.")
        for clause in assessment.failed_clauses[:NAMED_IN_NOTES]:
            assessment.notes.append(
                f"{clause.label}: {clause.description} "
                f"({clause.instances} instance(s)).")
        if assessment.failed_clause_count > NAMED_IN_NOTES:
            assessment.notes.append(
                f"{assessment.failed_clause_count - NAMED_IN_NOTES} further "
                f"rule(s) were found and are not named here.")
    elif assessment.verapdf_note:
        assessment.notes.append(assessment.verapdf_note)
    else:
        assessment.notes.append(
            "Nothing checked the declaration above; verapdf is what would.")

    # What the reconstruction would be built from, which is the same answer
    # either way and has a different consequence. `pdf_ingest` infers for a
    # tagged file and an untagged one alike, so a tree is not something it
    # reads; it is something the result could be checked against. All 118
    # originals in this series carry one, so the second branch is the case
    # this archive never exercises and a typeset back catalogue is full of.
    if assessment.tagged and assessment.tree_usable:
        assessment.notes.append(
            f"The structure tree reaches "
            f"{assessment.tree_coverage:.0f}% of the text and names "
            f"{assessment.tree_headings} heading element(s) across "
            f"{assessment.tree_elements}. Ingest takes the headings from "
            f"it rather than from type size and centring; the paragraphs, "
            f"the quotations and the emphasis are still read off the "
            f"geometry of the page. A file calls what it likes a heading, "
            f"and volume 2 of this series calls its running heads one, so "
            f"the count is of elements and the furniture rule still "
            f"decides what reaches the text.")
    elif assessment.tagged and assessment.tree_coverage is None:
        assessment.notes.append(
            "The file carries a structure tree and no text was read, so "
            "how much of the chapter the tree reaches is unknown rather "
            "than none.")
    elif assessment.tagged:
        assessment.notes.append(
            f"The structure tree reaches only "
            f"{assessment.tree_coverage:.0f}% of the text, which is a cover "
            f"page or a fragment rather than the chapter, so the file being "
            f"tagged says nothing about what could be read from it. The "
            f"reconstruction is inferred from the geometry of the page and "
            f"there is nothing here to check it against.")
    else:
        assessment.notes.append(
            "There is no structure tree, so the reconstruction is inferred "
            "and the file holds nothing to check it against. Every one of "
            "those readings is a judgement that can be wrong, so the pages "
            "are read afterwards by somebody.")

    if assessment.tables is None:
        assessment.notes.append(
            "Tables were not counted; counting them reads every page a "
            "second time.")


@dataclass
class Rollup:
    """Every readable file in one pass, added up.

    `report()` worked these out inline, which was right while a terminal
    was the only reader of them. A page needs the same numbers as data,
    and two places adding up the same files is how one count comes to
    mean two things; `lint.figure_state` and `_carried_description` exist
    for that reason and this codebase has paid for the lesson three
    times.

    An unreadable file is counted and then left out of every total. A
    file pypdf could not open has told you nothing about its figures, and
    folding a zero in beside a real reading is the kind of claim this
    module exists to refuse.
    """

    files: int = 0
    readable: int = 0
    unreadable: int = 0
    pages: int = 0

    # What the files state about themselves.
    declaring: int = 0
    tagged: int = 0
    trees_usable: int = 0

    # What a checker made of that, over the files it reached. Never over
    # the files it did not.
    checked: int = 0
    passing: int = 0
    contradicted: list = field(default_factory=list)

    # Work remediation would have to produce.
    figures_found: int = 0
    figures_owed: int = 0
    pages_needing_ocr: int = 0
    cover_pages: int = 0
    clipping_pages: int = 0
    link_annotations: int = 0
    untagged_links: int = 0
    unreadable_characters: int = 0
    symbol_pages: int = 0
    symbol_fonts: list = field(default_factory=list)

    @property
    def untagged(self) -> int:
        """Files carrying no tree, so with nothing to check a reading
        against. For those the reconstruction is inferred from the
        geometry of the page, which is a judgement that can be wrong."""
        return self.readable - self.tagged

    @property
    def unmapped_fonts(self) -> list:
        """Symbol fonts nobody has read off the page yet, worst first.

        The number a journal is quoted from, because a font is one
        reading somebody does once, however many characters it sets.
        """
        return sorted((f for f in self.symbol_fonts if not f.known),
                      key=lambda f: -f.characters)


def rollup(assessments: list) -> Rollup:
    """Add up a pass. Reads the assessments and asks the files nothing."""
    readable = [a for a in assessments if a.readable]
    checked = [a for a in readable if a.checked]

    # Folded across the pass, because a font is one reading whether it
    # sets one page or forty.
    families: dict = {}
    for assessment in readable:
        for font in assessment.symbol_fonts:
            carried = families.setdefault(
                font.family, SymbolFont(font.family, known=font.known))
            carried.characters += font.characters
            carried.pages += font.pages

    return Rollup(
        files=len(assessments),
        readable=len(readable),
        unreadable=len(assessments) - len(readable),
        pages=sum(a.pages for a in readable),
        declaring=sum(1 for a in readable if a.conformant),
        tagged=sum(1 for a in readable if a.tagged),
        trees_usable=sum(1 for a in readable if a.tree_usable),
        checked=len(checked),
        passing=sum(1 for a in checked if a.verapdf),
        contradicted=[a for a in checked if a.contradicted],
        figures_found=sum(a.figures_found for a in readable),
        figures_owed=sum(a.undescribed_figures for a in readable),
        pages_needing_ocr=sum(a.pages_needing_ocr for a in readable),
        cover_pages=sum(a.cover_pages for a in readable),
        clipping_pages=sum(a.clipping_pages for a in readable),
        link_annotations=sum(a.link_annotations for a in readable),
        untagged_links=sum(a.untagged_links for a in readable),
        unreadable_characters=sum(a.unreadable_characters for a in readable),
        symbol_pages=sum(a.symbol_pages for a in readable),
        symbol_fonts=sorted(families.values(), key=lambda f: f.family),
    )


def assess_folder(folder: Path, deep: bool = False,
                  limit: Optional[int] = None,
                  recursive: bool = False,
                  validate: bool = False) -> list:
    """Every PDF in a folder, in name order. Writes nothing.

    Flat by default, because the folder this is pointed at is usually one
    a journal sent and its shape is one PDF per chapter. `recursive` is
    for a tree that is already laid out, Graphion's own `content/` among
    them.
    """
    pattern = "**/*.pdf" if recursive else "*.pdf"
    pdfs = sorted(Path(folder).glob(pattern))
    if limit:
        pdfs = pdfs[:limit]
    return [assess_pdf(pdf, deep=deep, validate=validate) for pdf in pdfs]


def assess_html_folder(folder: Path, limit: Optional[int] = None,
                       recursive: bool = False,
                       validate: bool = False) -> list:
    """Every HTML page in a folder, in name order. Writes nothing.

    Listed even where nothing is checked, because a journal that sent its
    HTML should not have to wonder whether this pass saw it.
    """
    patterns = ("**/*.html", "**/*.htm") if recursive else ("*.html", "*.htm")
    pages = sorted({page for pattern in patterns
                    for page in Path(folder).glob(pattern)})
    if limit:
        pages = pages[:limit]
    return [assess_html(page, validate=validate) for page in pages]


def report(assessments: list, html: tuple = ()) -> str:
    """The assessment as prose an editor can read and a journal can check."""
    lines = []
    readable = [a for a in assessments if a.readable]
    for assessment in assessments:
        lines.append(assessment.path.name)
        if not assessment.readable:
            lines.append(f"  will not open: {assessment.error}")
            lines.append("")
            continue
        # "declares conformance" rather than "conformant", now that a
        # verdict can stand beside it. The file says one thing and a checker
        # says another, and a single word covering both is how an archive
        # comes to be described as conformant on its own say-so.
        state = ("declares conformance" if assessment.conformant
                 else "needs work")
        counts = [f"{assessment.pages} page(s)", state]
        if assessment.verapdf is True:
            counts.append("verapdf passes")
        elif assessment.verapdf is False:
            counts.append(
                f"verapdf fails {assessment.failed_clause_count} rule(s)")
        if assessment.figures_found:
            counts.append(f"{assessment.figures_found} figure(s)")
        if assessment.tables:
            counts.append(f"{assessment.tables} table(s)")
        lines.append("  " + ", ".join(counts))
        for note in assessment.notes:
            lines.append(f"  - {note}")
        lines.append("")

    for page in html:
        lines.append(page.path.name)
        if not page.readable:
            lines.append(f"  will not open: {page.error}")
            lines.append("")
            continue
        counts = [f"{page.headings} heading(s)"]
        if page.images:
            counts.append(f"{page.images} image(s)")
        if page.images_owed:
            counts.append(f"{page.images_owed} needing a description")
        if page.tables:
            counts.append(f"{page.tables} table(s)")
        if page.links:
            counts.append(f"{page.links} link(s)")
        if page.clean is True:
            counts.append("pa11y finds nothing")
        elif page.clean is False:
            counts.append(f"pa11y finds {page.errors} error(s), "
                          f"{page.warnings} warning(s), "
                          f"{page.notices} notice(s)")
        lines.append("  " + ", ".join(counts))
        for note in page.notes:
            lines.append(f"  - {note}")
        for code, count in page.codes:
            lines.append(f"  - {code} ({count})")
        lines.append("")

    if len(readable) > 1:
        # Added up by `rollup()`, which the assessment page calls too, so
        # the terminal and the browser cannot report different totals over
        # the same files.
        roll = rollup(assessments)
        lines.append(f"{roll.readable} file(s) read, "
                     f"{roll.unreadable} unreadable.")
        lines.append(f"  {roll.declaring} declare conformance.")
        if roll.checked:
            lines.append(
                f"  {roll.passing} of "
                f"{roll.checked} checked file(s) pass verapdf.")
            if roll.contradicted:
                lines.append(
                    f"  {len(roll.contradicted)} declare conformance and do "
                    f"not pass it: "
                    + ", ".join(a.path.name
                                for a in roll.contradicted[:6]) + ".")
        else:
            lines.append(
                "  Nothing was checked; what is above is what each file "
                "declares about itself. Pass --validate to run verapdf.")
        lines.append(
            f"  {roll.figures_owed} figure(s) "
            f"needing a description, of "
            f"{roll.figures_found} found.")
        if roll.pages_needing_ocr:
            lines.append(f"  {roll.pages_needing_ocr} page(s) needing OCR "
                         f"before any of that.")
        if roll.untagged:
            lines.append(
                f"  {roll.untagged} of {roll.readable} carry no structure "
                f"tree, so for those the reconstruction is inferred rather "
                f"than read: paragraphs from the first-line indent, heads "
                f"from type size and centring, emphasis from font names. "
                f"Every one of those is a judgement that can be wrong, so "
                f"the pages are read afterwards by somebody.")
        if roll.symbol_pages:
            unmapped = roll.unmapped_fonts
            lines.append(
                f"  {roll.symbol_pages} page(s) set type in a symbol font, "
                f"across {len(roll.symbol_fonts)} font(s), of which "
                f"{len(unmapped)} are not mapped yet"
                + (": " + ", ".join(f.family for f in unmapped[:6])
                   if unmapped else "")
                + ". A font is one reading somebody does off the page and "
                  "writes down once, however many characters it sets.")
        lines.append(
            "  How many figures carry text as a picture is not in this "
            "total, and cannot be read off the page.")

    if html:
        pages = [p for p in html if p.readable]
        lines.append(f"{len(pages)} HTML page(s) read, "
                     f"{len(html) - len(pages)} unreadable.")
        lines.append(
            f"  {sum(1 for p in pages if p.lang)} carry a language, "
            f"{sum(1 for p in pages if p.title)} a title, "
            f"{sum(1 for p in pages if p.has_main)} a main landmark.")
        lines.append(
            f"  {sum(p.images_owed for p in pages)} image(s) needing a "
            f"description, of {sum(p.images for p in pages)} found.")
        decorative = sum(p.images_decorative for p in pages)
        if decorative:
            lines.append(
                f"  {decorative} further image(s) are marked as carrying "
                f"nothing a reader needs, which only looking confirms.")
        checked_pages = [p for p in pages if p.checked]
        if checked_pages:
            lines.append(
                f"  {sum(1 for p in checked_pages if p.clean)} of "
                f"{len(checked_pages)} checked page(s) carry no pa11y "
                f"finding.")
        else:
            lines.append(
                "  No page was checked; pass --validate to run pa11y over "
                "them.")
        lines.append(
            "  How many of these images set their words as a picture is not "
            "in this total either, and a figure set as a CSS background is "
            "not in the markup to be counted at all.")
    return "\n".join(lines)


def _as_dict(assessment: Assessment) -> dict:
    out = assessment.__dict__.copy()
    out["path"] = str(assessment.path)
    out["conformant"] = assessment.conformant
    out["checked"] = assessment.checked
    out["contradicted"] = assessment.contradicted
    out["failed_clauses"] = [
        {"clause": c.clause, "test_number": c.test_number,
         "description": c.description, "instances": c.instances,
         "tags": list(c.tags)}
        for c in assessment.failed_clauses
    ]
    out["symbol_fonts"] = [
        {"family": f.family, "characters": f.characters, "pages": f.pages,
         "known": f.known}
        for f in assessment.symbol_fonts
    ]
    return out


def _html_as_dict(page: HtmlAssessment) -> dict:
    out = page.__dict__.copy()
    out["path"] = str(page.path)
    out["checked"] = page.checked
    out["images_owed"] = page.images_owed
    out["codes"] = [{"code": code, "count": count} for code, count in page.codes]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Report what remediating a PDF would take. Reads only; "
                    "nothing is ingested and nothing is written.")
    parser.add_argument("path", help="a PDF, or a folder holding PDFs")
    parser.add_argument("--deep", action="store_true",
                        help="count ruled tables, which reads every page "
                             "a second time")
    parser.add_argument("--limit", type=int, help="assess at most N files")
    parser.add_argument("--recursive", action="store_true",
                        help="descend into subfolders, for a tree that is "
                             "already laid out")
    parser.add_argument("--validate", action="store_true",
                        help="run verapdf over the PDFs and pa11y over the "
                             "HTML, so what each file declares is checked "
                             "rather than taken. Slow: a JVM at about 13 "
                             "seconds a PDF and a headless browser at more "
                             "than a minute a page")
    parser.add_argument("--json", action="store_true",
                        help="emit the readings rather than the prose")
    args = parser.parse_args()

    target = Path(args.path)
    if not target.exists():
        print(f"No such path: {target}", file=sys.stderr)
        return 2
    pages: list = []
    if target.is_dir():
        assessments = assess_folder(target, deep=args.deep, limit=args.limit,
                                    recursive=args.recursive,
                                    validate=args.validate)
        pages = assess_html_folder(target, limit=args.limit,
                                   recursive=args.recursive,
                                   validate=args.validate)
    elif target.suffix.lower() in (".html", ".htm"):
        assessments = []
        pages = [assess_html(target, validate=args.validate)]
    else:
        assessments = [assess_pdf(target, deep=args.deep,
                                  validate=args.validate)]
    if not assessments and not pages:
        print(f"No PDFs or HTML in {target}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"pdfs": [_as_dict(a) for a in assessments],
                          "html": [_html_as_dict(p) for p in pages]},
                         indent=2))
    else:
        print(report(assessments, tuple(pages)))
        # Which flag to pass is said here and not in a note, because a note
        # states a finding about the file and a flag is this surface's way
        # of answering it. The same notes are read on the assessment page,
        # where there is a checkbox and no flag to pass, and a page telling
        # an editor to pass --validate is a page written for somebody else.
        # On stderr, so a piped report is unchanged.
        if not args.validate:
            print("\nNo checker was run. Pass --validate for verapdf over "
                  "the PDFs and pa11y over any HTML beside them.",
                  file=sys.stderr)
        if not args.deep and assessments:
            print("Tables were not counted. Pass --deep to count them.",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
