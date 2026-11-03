"""What remediating a PDF would take, read without ingesting it.

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


@dataclass
class HtmlAssessment:
    """One HTML file, as a checker reads it.

    Thinner than `Assessment` on purpose, and the thinness is the honest
    part. This is pa11y's verdict and nothing else: what the page holds,
    how many figures it carries, how many of those are described and how
    many set their words as a picture, is not read here. A journal's HTML
    still has to be assessed the way its PDFs are, and saying so beats a
    clean pa11y run reading as a clean archive.
    """

    path: Path
    clean: Optional[bool] = None
    note: str = ""
    errors: int = 0
    warnings: int = 0
    notices: int = 0
    codes: list = field(default_factory=list)

    @property
    def checked(self) -> bool:
        return self.clean is not None


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


def assess_html(path: Path, validate: bool = True) -> HtmlAssessment:
    """Run pa11y over one HTML file. Writes nothing.

    `validate` false records that the file is there and was not checked,
    which is worth saying: a journal that sent its HTML should not have to
    wonder whether this pass noticed it.
    """
    import collections

    out = HtmlAssessment(path=Path(path))
    if not validate:
        out.note = "Not checked; pass --validate to run pa11y over it."
        return out
    if not validators.pa11y_available():
        out.note = "pa11y is not on PATH, so this page was not checked."
        return out
    clean, issues = validators.run_pa11y(Path(path))
    if issues and isinstance(issues[0], dict) and issues[0].get("error"):
        out.note = str(issues[0]["error"])
        return out
    out.clean = bool(clean)
    counts: collections.Counter = collections.Counter()
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        kind = str(issue.get("type") or "")
        if kind == "error":
            out.errors += 1
        elif kind == "warning":
            out.warnings += 1
        elif kind == "notice":
            out.notices += 1
        counts[str(issue.get("code") or "")] += 1
    out.codes = counts.most_common(MAX_NAMED_CODES)
    return out


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


def _read_structure_figures(assessment: Assessment, reader) -> None:
    """Figure elements in the structure tree, and which carry a description.

    A tagged PDF states this, so an assessment that counted every raster as
    work still owed would quote a journal for writing descriptions it
    already has. Only elements whose `/S` is `/Figure` are counted: an
    `/Alt` sits on whatever element needs one, equations included, so
    counting them all would answer a different question.
    """
    root = reader.trailer["/Root"]
    if "/StructTreeRoot" not in root:
        return
    seen: set = set()

    def walk(node, depth: int = 0) -> None:
        if depth > 80:
            return
        try:
            resolved = node.get_object() if hasattr(node, "get_object") else node
        except Exception:
            return
        if isinstance(resolved, list):
            for kid in resolved:
                walk(kid, depth + 1)
            return
        if not isinstance(resolved, dict):
            return
        marker = id(resolved)
        if marker in seen:
            return
        seen.add(marker)
        if str(resolved.get("/S") or "") == "/Figure":
            assessment.tagged_figures += 1
            if str(resolved.get("/Alt") or "").strip():
                assessment.described_figures += 1
        if "/K" in resolved:
            walk(resolved["/K"], depth + 1)

    try:
        walk(root["/StructTreeRoot"])
    except Exception:
        pass


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


def _read_text(assessment: Assessment, pdf, deep: bool) -> None:
    """Text, and what its absence costs.

    A page carrying images and no text layer is a scan. Remediation there
    is OCR and then proofing it, which is a different order of work from
    writing a description, so the two are counted apart rather than summed
    into one number that would mean nothing.
    """
    import lint

    body = []
    for index, page in enumerate(pdf.pages):
        try:
            text = page.extract_text() or ""
        except Exception:
            text = ""
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
    _read_structure_figures(assessment, reader)
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
                f"rule(s) are in the readings; pass --json for all of them.")
    elif assessment.verapdf_note:
        assessment.notes.append(assessment.verapdf_note)
    else:
        assessment.notes.append(
            "Nothing checked the declaration above; pass --validate to run "
            "verapdf over it.")

    if assessment.tables is None:
        assessment.notes.append(
            "Tables were not counted; pass --deep for that, which reads "
            "every page a second time.")


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
        if not page.checked:
            lines.append(f"  not checked: {page.note}")
            lines.append("")
            continue
        verdict = ("pa11y finds nothing" if page.clean
                   else f"pa11y finds {page.errors} error(s), "
                        f"{page.warnings} warning(s), "
                        f"{page.notices} notice(s)")
        lines.append("  " + verdict)
        for code, count in page.codes:
            lines.append(f"  - {code} ({count})")
        lines.append(
            "  - What the page holds is not read here; only a checker ran "
            "over it.")
        lines.append("")

    if len(readable) > 1:
        lines.append(f"{len(readable)} file(s) read, "
                     f"{len(assessments) - len(readable)} unreadable.")
        lines.append(
            f"  {sum(1 for a in readable if a.conformant)} declare "
            f"conformance.")
        checked = [a for a in readable if a.checked]
        if checked:
            lines.append(
                f"  {sum(1 for a in checked if a.verapdf)} of "
                f"{len(checked)} checked file(s) pass verapdf.")
            contradicted = [a for a in checked if a.contradicted]
            if contradicted:
                lines.append(
                    f"  {len(contradicted)} declare conformance and do not "
                    f"pass it: "
                    + ", ".join(a.path.name for a in contradicted[:6]) + ".")
        else:
            lines.append(
                "  Nothing was checked; what is above is what each file "
                "declares about itself. Pass --validate to run verapdf.")
        lines.append(
            f"  {sum(a.undescribed_figures for a in readable)} figure(s) "
            f"needing a description, of "
            f"{sum(a.figures_found for a in readable)} found.")
        ocr = sum(a.pages_needing_ocr for a in readable)
        if ocr:
            lines.append(f"  {ocr} page(s) needing OCR before any of that.")
        lines.append(
            "  How many figures carry text as a picture is not in this "
            "total, and cannot be read off the page.")

    if html:
        checked_pages = [p for p in html if p.checked]
        lines.append(f"  {len(html)} HTML page(s) in the folder, "
                     f"{len(checked_pages)} checked.")
        if checked_pages:
            lines.append(
                f"  {sum(1 for p in checked_pages if p.clean)} of "
                f"{len(checked_pages)} carry no pa11y finding.")
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
    return out


def _html_as_dict(page: HtmlAssessment) -> dict:
    out = page.__dict__.copy()
    out["path"] = str(page.path)
    out["checked"] = page.checked
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
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
