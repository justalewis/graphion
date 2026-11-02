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

What it reports divides in two, and the division is the point. The
conformance a PDF arrives with is a fact the file states, so it is read
off the catalog and the XMP and reported as read. What remediation would
have to produce is an estimate, because it is a count of work: a figure
needs a description somebody writes, a page with no text layer needs OCR
and then proofing. Those are reported as counts with the reasoning
attached, so a number can be checked rather than believed.

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
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import pdf_ingest
import pdf_tags

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
    # second reader for this has been written wrong here before.
    result = lint.check_unreadable_characters({}, {}, "\n".join(body))
    if result.level != "pass":
        digits = re.search(r"^(\d+)", result.summary)
        assessment.unreadable_characters = int(digits.group(1)) if digits else 1


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


def assess_pdf(path: Path, deep: bool = False) -> Assessment:
    """Read one PDF. Writes nothing, anywhere, ever."""
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

    _add_notes(assessment)
    return assessment


def _add_notes(assessment: Assessment) -> None:
    """What the counts mean, and what no reading can settle."""
    if assessment.conformant:
        assessment.notes.append(
            "Already tagged, titled and declaring PDF/UA-1. A declaration "
            "is not a pass; verapdf is what checks it.")
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
    if assessment.tables is None:
        assessment.notes.append(
            "Tables were not counted; pass --deep for that, which reads "
            "every page a second time.")


def assess_folder(folder: Path, deep: bool = False,
                  limit: Optional[int] = None,
                  recursive: bool = False) -> list:
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
    return [assess_pdf(pdf, deep=deep) for pdf in pdfs]


def report(assessments: list) -> str:
    """The assessment as prose an editor can read and a journal can check."""
    lines = []
    readable = [a for a in assessments if a.readable]
    for assessment in assessments:
        lines.append(assessment.path.name)
        if not assessment.readable:
            lines.append(f"  will not open: {assessment.error}")
            lines.append("")
            continue
        state = "conformant" if assessment.conformant else "needs work"
        counts = [f"{assessment.pages} page(s)", state]
        if assessment.figures_found:
            counts.append(f"{assessment.figures_found} figure(s)")
        if assessment.tables:
            counts.append(f"{assessment.tables} table(s)")
        lines.append("  " + ", ".join(counts))
        for note in assessment.notes:
            lines.append(f"  - {note}")
        lines.append("")

    if len(readable) > 1:
        lines.append(f"{len(readable)} file(s) read, "
                     f"{len(assessments) - len(readable)} unreadable.")
        lines.append(
            f"  {sum(1 for a in readable if a.conformant)} already conformant.")
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
    return "\n".join(lines)


def _as_dict(assessment: Assessment) -> dict:
    out = assessment.__dict__.copy()
    out["path"] = str(assessment.path)
    out["conformant"] = assessment.conformant
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
    parser.add_argument("--json", action="store_true",
                        help="emit the readings rather than the prose")
    args = parser.parse_args()

    target = Path(args.path)
    if not target.exists():
        print(f"No such path: {target}", file=sys.stderr)
        return 2
    if target.is_dir():
        assessments = assess_folder(target, deep=args.deep, limit=args.limit,
                                    recursive=args.recursive)
    else:
        assessments = [assess_pdf(target, deep=args.deep)]
    if not assessments:
        print(f"No PDFs in {target}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([_as_dict(a) for a in assessments], indent=2))
    else:
        print(report(assessments))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
