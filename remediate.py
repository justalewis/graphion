"""Mechanical accessibility fixes, and the line they stop at.

R2 of `docs/cartridge-audit.md`. Everything here changes markup and
nothing here changes a word, which `invariance.py` proves on every run
rather than asserting.

**What it fixes.** A missing `lang`, a `<th>` with no `scope`, and a
heading outline that skips a level inside the body. Each is a failure of
markup rather than of authorship, so none of them needs the author.

**What it reports and refuses to fix**, which is the more interesting
half, because each was a candidate that measurement or this codebase's
own history ruled out.

A table with no header cell at all gets reported, not repaired.
Promoting a `<td>` row to `<th>` is a claim about what the table means,
and getting it wrong changes what a screen reader announces for every
cell beneath it. 164 tables across the cartridges measured are in this
state and not one of them is safe to guess at.

A layout table does not get `role="presentation"`. That is the remedy an
audit names and this codebase has already paid to learn it does not
work: pa11y then fails the page on WCAG F92, "role is presentation but
contains child elements with semantic meaning", and goes on failing with
`<colgroup>` suppressed, because `<tbody>`, `<tr>` and `<td>` are the
remaining children. It was written, tested against pa11y and reverted.

An untitled `<iframe>` gets reported. A title is text somebody has to
write, and inventing one from the embed URL produces "YouTube video
player" on every frame, which is worse than silence because it looks
answered.

**The heading rule is not `filters/heading-levels.lua`'s rule**, and the
difference is the whole "a cartridge is not a course" point made
concrete. A galley is a whole document, so its outline must start at
level 1. A Canvas page is a fragment that Canvas wraps: it renders the
page title as the `<h1>` itself. Measured over 2,532 real pages, the
first heading in the body is `<h2>` on 1,574 and `<h1>` on 210, so
forcing a start at level 1 would put a second `<h1>` on most pages in
the archive. The base level is therefore left exactly where the author
put it, and only skips below it are closed.

**`lang` is never guessed.** The language of a course is a fact about
the course, and none of the 33 cartridges measured declares a locale in
`course_settings/course_settings.xml`, so there is nothing to read it
from. It is a parameter, and where the caller does not supply one the
2,446 pages that lack it stay as they are and are reported. Writing
`lang="en"` over a Spanish course is worse than leaving it off: a screen
reader then pronounces Spanish with English phonetics, confidently.

**The file is reformatted.** Parsing and reserialising normalises
whitespace and attribute order throughout, so the diff is large even
where one attribute changed. That is the trade for not editing HTML with
regular expressions, and it is only acceptable because the invariance
harness holds the words still; it is reported so nobody is surprised.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# How deep a heading may go. Beyond six there is no tag, so a document
# nested deeper than this is clamped and said out loud rather than
# silently flattened.
MAX_HEADING = 6

_HEADINGS = "//h1|//h2|//h3|//h4|//h5|//h6"


@dataclass
class Change:
    """Something this pass altered."""

    kind: str
    count: int = 0
    detail: str = ""


@dataclass
class Owed:
    """Something this pass found and deliberately did not alter."""

    kind: str
    count: int = 0
    detail: str = ""


@dataclass
class Result:
    data: bytes
    changes: list = field(default_factory=list)
    owed: list = field(default_factory=list)
    error: str = ""
    # How a change to this file is proved harmless. "text" is the rule for
    # everything here: the visible text is the same before and after. "pixels"
    # is for a recognised text layer, where text appearing is the point and
    # the promise is the other half of the same one, that the page looks
    # identical. `layered` names the pages that carry the layer.
    proof: str = "text"
    layered: list = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.changes)

    def of_kind(self, kind: str) -> Optional[Change]:
        for change in self.changes:
            if change.kind == kind:
                return change
        return None

    def owes(self, kind: str) -> Optional[Owed]:
        for owed in self.owed:
            if owed.kind == kind:
                return owed
        return None


def _set_language(tree, language: Optional[str]) -> Optional[Change]:
    """Put the stated language on the root, where there is one to put.

    Both `lang` and `xml:lang` are left alone when either is already set:
    the author said something about the language of this page and that
    outranks what the caller said about the course.
    """
    if not language:
        return None
    root = tree.getroottree().getroot()
    if root is None or root.tag != "html":
        return None
    if root.get("lang") or root.get("{http://www.w3.org/XML/1998/namespace}lang"):
        return None
    root.set("lang", language)
    return Change(kind="lang", count=1,
                  detail=f"set lang=\"{language}\" on the page")


def _scope_headers(tree) -> Optional[Change]:
    """Give every bare `<th>` the scope it is obviously for.

    A header cell in the first row of its table heads a column; one that
    opens its own row heads that row. Where a cell is both, which is the
    corner cell of a table headed on two sides, nothing is written: it is
    genuinely ambiguous and `scope` has no value meaning both.
    """
    fixed = 0
    for table in tree.xpath("//table"):
        rows = table.xpath(".//tr")
        if not rows:
            continue
        cells_of = [row.xpath("./th|./td") for row in rows]

        # Which edges this table is headed on, worked out once. A first
        # row that is entirely header cells is a row of column headings;
        # a left column of header cells below the first row heads those
        # rows. A table can be headed on one edge, the other, or both,
        # and a cell's scope follows from which.
        heads_columns = bool(cells_of[0]) and all(
            c.tag == "th" for c in cells_of[0])
        heads_rows = any(cells and cells[0].tag == "th"
                         for cells in cells_of[1:])

        for row_index, cells in enumerate(cells_of):
            for cell_index, cell in enumerate(cells):
                if cell.tag != "th" or cell.get("scope"):
                    continue
                is_column_head = row_index == 0 and heads_columns
                is_row_head = cell_index == 0 and heads_rows
                if is_column_head and is_row_head:
                    # The corner cell of a table headed along both edges.
                    # It heads neither and both, and `scope` has no value
                    # that says so, which is why nothing is written.
                    continue
                if is_column_head:
                    cell.set("scope", "col")
                    fixed += 1
                elif is_row_head:
                    cell.set("scope", "row")
                    fixed += 1
    if not fixed:
        return None
    return Change(kind="scope", count=fixed,
                  detail=f"set scope on {fixed} header cell(s)")


def _close_heading_skips(tree) -> Optional[Change]:
    """Close gaps in the outline without moving where it starts.

    The stack is `filters/heading-levels.lua`'s, offset so the first
    heading keeps the level the author gave it. See the module docstring
    for why a Canvas page must not be forced to start at one.
    """
    headings = tree.xpath(_HEADINGS)
    if not headings:
        return None
    base = int(headings[0].tag[1])
    stack: list = []
    moved = 0
    for heading in headings:
        level = int(heading.tag[1])
        while stack and stack[-1] >= level:
            stack.pop()
        stack.append(level)
        want = min(base + len(stack) - 1, MAX_HEADING)
        if want != level:
            heading.tag = f"h{want}"
            moved += 1
    if not moved:
        return None
    return Change(kind="heading-level", count=moved,
                  detail=(f"closed the outline so it skips nothing below "
                          f"h{base}, moving {moved} heading(s)"))


def _report_only(tree) -> list:
    """What was found and deliberately left alone."""
    owed = []

    headerless = [t for t in tree.xpath("//table") if not t.xpath(".//th")]
    if headerless:
        owed.append(Owed(
            kind="table-without-header", count=len(headerless),
            detail=("no header cell, so a screen reader cannot name the "
                    "column a cell is in. Which row is the header is a "
                    "claim about the table and is not guessed at here.")))

    untitled = [f for f in tree.xpath("//iframe") if not f.get("title")]
    if untitled:
        owed.append(Owed(
            kind="iframe-without-title", count=len(untitled),
            detail=("embedded with no title, so it is announced only as "
                    "\"frame\". A title is text somebody has to write.")))

    return owed


def fix_html(data: bytes, language: Optional[str] = None) -> Result:
    """Apply every mechanical fix to one page. Returns the new bytes.

    `language` is the course's, stated by the caller. Omitted, no `lang`
    is written and the gap is reported instead.
    """
    from lxml import html as lxml_html

    try:
        tree = lxml_html.fromstring(data)
    except Exception as exc:
        # A page that will not parse is left exactly as it arrived. A
        # remediation that mangles a file it could not read is the one
        # outcome worse than leaving the file alone.
        return Result(data=data, error=f"could not be parsed: {exc}")

    changes = [c for c in (_set_language(tree, language),
                           _scope_headers(tree),
                           _close_heading_skips(tree)) if c]
    owed = _report_only(tree)
    if not language:
        root = tree.getroottree().getroot()
        if root is not None and root.tag == "html" and not root.get("lang"):
            owed.append(Owed(
                kind="no-language", count=1,
                detail=("the page states no language and none was given "
                        "for the course, so none was written. A guessed "
                        "language is read aloud in the wrong accent.")))

    if not changes:
        # Nothing to do means the bytes are returned untouched, so a page
        # this pass has no work for is not reformatted for nothing.
        return Result(data=data, owed=owed)

    # `include_meta_content_type` is not a nicety. Without it lxml's HTML
    # serialiser *removes* the `<meta http-equiv="Content-Type">` the page
    # arrived with and writes nothing in its place, so the output is UTF-8
    # bytes with nothing declaring that, and the next reader falls back to
    # Latin-1: every curly quotation mark in the course becomes "â€œ".
    #
    # That is not a reporting problem, it is corruption of the deliverable,
    # and it would have shipped. The invariance harness caught it on 1,960
    # of 2,532 real pages, which is what building that first was for.
    out = lxml_html.tostring(tree, encoding="utf-8", method="html",
                             include_meta_content_type=True)
    return Result(data=out, changes=changes, owed=owed)


def summarise(results) -> dict:
    """Fold a run's changes and gaps into counts, for a report."""
    changed: dict = {}
    owed: dict = {}
    for result in results:
        for change in result.changes:
            changed[change.kind] = changed.get(change.kind, 0) + change.count
        for gap in result.owed:
            owed[gap.kind] = owed.get(gap.kind, 0) + gap.count
    return {"changed": changed, "owed": owed}


# ---------- PDFs ----------
#
# R3. Stamping only: `/Lang`, `dc:title`, `/DisplayDocTitle` and
# `/MarkInfo`, with every byte of ink unchanged. Tagging an untagged PDF
# is reconstruction and produces a document that looks different from the
# one the author uploaded; see section 10 of docs/cartridge-audit.md for
# why that is offered separately and never silently.

# Where a title may already be. ISO 14289-1 clause 5 reads `dc:title` in
# the XMP packet; `/Title` in the Info dictionary is a different entry and
# does not satisfy it. 520 of the 1,030 readable PDFs across these
# cartridges carry an Info title and only 340 carry an XMP one, so for 180
# of them the document already states its title and merely states it in
# the wrong place. Moving it is relocation, not authorship.
_DC = "http://purl.org/dc/elements/1.1/"
_RDF = "http://www.w3.org/1999/02/22-rdf-syntax-ns#"
_XML_NS = "http://www.w3.org/XML/1998/namespace"

# What a converter writes into `/Title` when it has nothing to say, which
# is most of what is there. Of the nine distinct Info titles across these
# cartridges that carry one and no XMP title, seven are
# "Microsoft Word - <filename>", one is a DOI, and one is a real title.
# Moving those seven would make a screen reader announce "Microsoft Word
# - research 2.docx" as the name of the document, which is worse than the
# silence it replaces: it satisfies the checker and tells the reader
# something false.
#
# Same shape as `assess.PLACEHOLDER_ALTS`, and found the same way, by
# reading what is actually in the files rather than by imagining what
# might be.
_NOT_A_TITLE = re.compile(
    r"^\s*(microsoft\s+word\s*-|microsoft\s+powerpoint\s*-|doi:|untitled\s*$"
    r"|print\s*$|document\d*\s*$)", re.IGNORECASE)

# A bare filename, whatever produced it.
_FILENAME = re.compile(
    r"\.(docx?|pdf|rtf|pptx?|indd|qxd|pages|odt|txt)\s*$", re.IGNORECASE)


def looks_like_a_title(text: str) -> bool:
    """Whether a document's stated title is one.

    Conservative on purpose. A title that is wrong is published metadata
    read aloud to somebody; a title left absent is a gap this pass
    already reports and somebody can fill.
    """
    text = (text or "").strip()
    if len(text) < 3:
        return False
    if _NOT_A_TITLE.search(text):
        return False
    return not _FILENAME.search(text)


def _xmp_with_title(packet: bytes, title: str) -> Optional[bytes]:
    """Put `dc:title` into an existing XMP packet, keeping the rest.

    `pdf_tags._xmp_packet` builds a whole packet, which is right when it
    is writing a bound issue Graphion rendered itself and wrong here: a
    stranger's PDF carries its own producer, creator, rights and dates in
    that packet, and replacing it wholesale would throw them away to add
    one field. So the packet is edited rather than rebuilt.

    Returns None where the packet cannot be parsed, which leaves the file
    alone rather than guessing at its metadata.
    """
    from lxml import etree

    try:
        root = etree.fromstring(packet)
    except Exception:
        return None
    rdf = root if root.tag == f"{{{_RDF}}}RDF" else root.find(f".//{{{_RDF}}}RDF")
    if rdf is None:
        return None

    existing = rdf.find(f".//{{{_DC}}}title")
    if existing is not None:
        return None  # it already says something; not ours to overwrite

    # The prefixes have to be bound on the element being added, or lxml
    # invents `ns0:` and `pdf_tags.declared_title` reads nothing back: the
    # field is there, nothing can find it, and the stamp reports success.
    description = etree.SubElement(
        rdf, f"{{{_RDF}}}Description", nsmap={"rdf": _RDF, "dc": _DC})
    description.set(f"{{{_RDF}}}about", "")
    holder = etree.SubElement(description, f"{{{_DC}}}title")
    alt = etree.SubElement(holder, f"{{{_RDF}}}Alt")
    item = etree.SubElement(alt, f"{{{_RDF}}}li")
    item.set(f"{{{_XML_NS}}}lang", "x-default")
    item.text = title
    return etree.tostring(root, encoding="utf-8")


def fix_pdf(data: bytes, language: Optional[str] = None) -> Result:
    """Stamp one PDF's declarations. Changes no ink and no text.

    `language` is the course's, stated by the caller, never guessed, for
    the reason `fix_html` does not guess it either.
    """
    import io

    import pypdf

    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        root = reader.trailer["/Root"]
    except Exception as exc:
        return Result(data=data, error=f"could not be opened: {exc}")

    changes: list = []
    owed: list = []

    info_title = ""
    try:
        info_title = str((reader.metadata or {}).get("/Title") or "").strip()
    except Exception:
        info_title = ""

    import pdf_tags
    packet = pdf_tags.xmp_packet_text(reader)
    xmp_title = pdf_tags.declared_title(packet) if packet else ""
    tagged = "/StructTreeRoot" in root

    writer = pypdf.PdfWriter(clone_from=reader)
    new_root = writer._root_object
    touched = False

    if language and not root.get("/Lang"):
        new_root[pypdf.generic.NameObject("/Lang")] = \
            pypdf.generic.create_string_object(language)
        changes.append(Change(kind="lang", count=1,
                              detail=f"set /Lang to \"{language}\""))
        touched = True
    elif not language and not root.get("/Lang"):
        owed.append(Owed(kind="no-language", count=1,
                         detail="states no document language and none was "
                                "given for the course"))

    if info_title and not looks_like_a_title(info_title):
        owed.append(Owed(
            kind="title-is-not-a-title", count=1,
            detail=(f"states its title as {info_title[:60]!r}, which is a "
                    f"converter's filename rather than a title, so it was "
                    f"not moved into dc:title")))
        info_title = ""

    if info_title and not xmp_title:
        if packet:
            # A packet of their own: edit it, because it carries their
            # producer, creator, rights and dates and this is adding one
            # field, not replacing a record.
            rewritten = _xmp_with_title(packet.encode("utf-8"), info_title)
        else:
            # No packet at all, which is the commoner case by a long way:
            # of 301 real PDFs sampled, only 2 had one holding no title.
            # There is nothing to preserve, so `pdf_tags` builds the whole
            # thing, which is what it was written for. `ua_part` is None
            # and always will be from here: stamping cannot make a file
            # conformant and must not say it did.
            import pdf_tags as _tags
            producer = str((reader.metadata or {}).get("/Producer") or "")
            creator = str((reader.metadata or {}).get("/Creator") or "")
            rewritten = _tags._xmp_packet(info_title, language or "",
                                          producer, creator, None)
        if rewritten is not None:
            from pypdf.generic import DecodedStreamObject, NameObject
            stream = DecodedStreamObject()
            stream.set_data(rewritten)
            # Clause 7.1-8 asks for both, and a metadata stream without
            # them is a metadata stream a checker does not count.
            stream[NameObject("/Type")] = NameObject("/Metadata")
            stream[NameObject("/Subtype")] = NameObject("/XML")
            new_root[NameObject("/Metadata")] = writer._add_object(stream)
            changes.append(Change(
                kind="xmp-title", count=1,
                detail="moved the document's own /Title into dc:title, "
                       "which is the field clause 5 reads"))
            touched = True

    title_anywhere = bool(info_title or xmp_title)
    if title_anywhere:
        prefs = new_root.get("/ViewerPreferences")
        shows = bool(prefs and prefs.get("/DisplayDocTitle"))
        if not shows:
            from pypdf.generic import BooleanObject, DictionaryObject, NameObject
            prefs = prefs if prefs is not None else DictionaryObject()
            prefs[NameObject("/DisplayDocTitle")] = BooleanObject(True)
            new_root[NameObject("/ViewerPreferences")] = prefs
            changes.append(Change(
                kind="display-doc-title", count=1,
                detail="a reader now shows the title rather than the "
                       "filename (WCAG 2.4.2)"))
            touched = True
    else:
        owed.append(Owed(
            kind="no-title", count=1,
            detail="carries no title in either the Info dictionary or the "
                   "XMP packet. A title is text somebody has to write, and "
                   "a filename is not one."))

    if not tagged:
        owed.append(Owed(
            kind="untagged", count=1,
            detail="has no structure tree, so stamping cannot make it "
                   "conformant. Tagging means reconstructing the document, "
                   "which produces a file that looks different from the one "
                   "the author uploaded."))

    if not touched:
        return Result(data=data, owed=owed)

    out = io.BytesIO()
    writer.write(out)
    return Result(data=out.getvalue(), changes=changes, owed=owed)


# ---------- Office documents ----------
#
# R5, and it is an audit rather than a fix. Measured over the distinct
# Office files in these cartridges (the 777 first counted was the same
# files recurring across exports; there are 125 .docx, 13 .pptx, 26 .doc
# and 4 .xlsx), not one fix is mechanical.
#
# Every `.docx` already carries a default language, because Word always
# writes one, so the fix first planned is a no-op. What remains is all
# content: a picture with no description is words, a table with no header
# row is a claim about what the table means, a document with no Heading
# styles is a claim about its structure, and a slide with no title is
# words. Each is exactly what this pipeline refuses to guess, so each is
# reported.
#
# Nothing is modified, which is also the safest thing to do to a Word
# file. Round-tripping one through a library can silently drop comments,
# tracked changes and objects it does not model, and a remediation that
# returned a changed document with its review history gone would be worse
# than the gap it closed. The file is copied through byte for byte, and
# the invariance guarantee holds for it trivially.

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_DC_CORE = "http://purl.org/dc/elements/1.1/"

# Past this many paragraphs a document with no Heading style at all is
# reported. A one-page handout does not need an outline; a thirty page
# reading does. Measured: 48 of the 123 documents are long and have none.
LONG_DOCUMENT_PARAGRAPHS = 40

_LEGACY = {".doc": "Word", ".ppt": "PowerPoint", ".xls": "Excel",
           ".rtf": "Rich Text"}


def _zip_part(data: bytes, name: str):
    import io
    import zipfile

    from lxml import etree

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if name not in z.namelist():
            return None
        return etree.fromstring(z.read(name))


def _core_title(data: bytes) -> str:
    import io
    import zipfile

    from lxml import etree

    with zipfile.ZipFile(io.BytesIO(data)) as z:
        if "docProps/core.xml" not in z.namelist():
            return ""
        root = etree.fromstring(z.read("docProps/core.xml"))
    found = root.find(f"{{{_DC_CORE}}}title")
    return (found.text or "").strip() if found is not None else ""


def _title_owed(data: bytes) -> list:
    try:
        title = _core_title(data)
    except Exception:
        title = ""
    if title and looks_like_a_title(title):
        return []
    return [Owed(
        kind="office-no-title", count=1,
        detail=("the document properties carry no title, or only a "
                "filename. A title is text somebody has to write, and "
                "it is what a reader announces when the file opens."))]


# What an authoring tool writes into a picture's description when it has
# nothing to say. Calibrated on the real files, and the result reversed the
# first measurement: of 151 pictures carrying a description across the
# distinct Office files here, 4 were empty, 108 were a filename or a path
# (`vrgraphicnovel.png`, `/tmp/beautiful_ai_exports/<uuid>.jpg`) or a bare
# "Picture 3", and about 40 were Microsoft's machine-written text. Perhaps
# five read as written by a person. Counting presence said 13 of 50 pictures
# were undescribed; counting meaning says nearly all of them are, which is
# the present-and-wrong failure this codebase keeps meeting.
_FILE_DESCR = re.compile(
    r"\.(png|jpe?g|gif|bmp|emf|wmf|svg|tiff?|webp)\s*$", re.IGNORECASE)
_BARE_DESCR = re.compile(
    r"^(image|picture|img|photo|graphic|figure)[ _-]?\d*$", re.IGNORECASE)
_MACHINE_DESCR = re.compile(r"automatically generated", re.IGNORECASE)


def looks_like_a_placeholder_description(text: str) -> bool:
    """Whether a picture's description says nothing about the picture."""
    text = (text or "").strip()
    if not text:
        return True
    return bool(_FILE_DESCR.search(text) or _BARE_DESCR.match(text))


def is_machine_description(text: str) -> bool:
    """Microsoft's "Description automatically generated".

    Reported as owed review and not as missing, because it is present and
    it passes every checker. It is also often nonsense: one real file
    reads "A diagram of a diagram of a diagram". A description nobody
    wrote, vouched for by nobody, is the one kind of answer worse than a
    marked gap.
    """
    return bool(_MACHINE_DESCR.search(text or ""))


def _classify_pictures(elements) -> tuple:
    """(missing, machine_written) over a set of picture elements.

    A picture the author marked decorative has said it carries nothing a
    reader needs, which is a claim they made and not a gap, so it is
    counted as neither.
    """
    missing = machine = 0
    for el in elements:
        if el.xpath(".//*[local-name()='decorative']"):
            continue
        text = el.get("descr") or ""
        if is_machine_description(text):
            machine += 1
        elif looks_like_a_placeholder_description(text):
            missing += 1
    return missing, machine


def _picture_owed(missing: int, machine: int) -> list:
    owed = []
    if missing:
        owed.append(Owed(
            kind="image-without-description", count=missing,
            detail=("no description, or only a filename or placeholder, so "
                    "a screen reader announces a file name or nothing. "
                    "Describing it is words about the authors own "
                    "material.")))
    if machine:
        owed.append(Owed(
            kind="image-description-machine-written", count=machine,
            detail=("carries Microsoft's \"Description automatically "
                    "generated\" text. It is present, so no checker "
                    "flags it, and it is often wrong: it needs the author "
                    "to read it and either keep it or write their own.")))
    return owed


def audit_docx(data: bytes, language: Optional[str] = None) -> Result:
    """Report what a Word document owes. Changes nothing."""
    try:
        document = _zip_part(data, "word/document.xml")
    except Exception as exc:
        return Result(data=data, error=f"could not be opened: {exc}")
    if document is None:
        return Result(data=data, error="has no word/document.xml")

    ns = {"w": _W, "wp": _WP}
    owed: list = []

    owed.extend(_picture_owed(*_classify_pictures(
        document.xpath("//wp:docPr", namespaces=ns))))

    tables = document.xpath("//w:tbl", namespaces=ns)
    bare = [t for t in tables
            if not t.xpath(".//w:trPr/w:tblHeader", namespaces=ns)]
    if bare:
        owed.append(Owed(
            kind="table-without-header-row", count=len(bare),
            detail=("no row is marked as the header, so a screen reader "
                    "cannot name the column a cell is in. Which row is the "
                    "header is a claim about the table and is not guessed "
                    "at here.")))

    paragraphs = len(document.xpath("//w:p", namespaces=ns))
    headings = document.xpath("//w:pStyle[starts-with(@w:val,'Heading')]",
                              namespaces=ns)
    if paragraphs > LONG_DOCUMENT_PARAGRAPHS and not headings:
        owed.append(Owed(
            kind="no-headings", count=1,
            detail=(f"{paragraphs} paragraphs and no Heading style, so a "
                    f"reader cannot navigate it by section. Bold text is "
                    f"not a heading to a screen reader, and deciding which "
                    f"lines are headings is a claim about the structure.")))

    owed.extend(_title_owed(data))
    return Result(data=data, owed=owed)


def audit_pptx(data: bytes, language: Optional[str] = None) -> Result:
    """Report what a presentation owes. Changes nothing."""
    import io
    import re
    import zipfile

    from lxml import etree

    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        names = z.namelist()
    except Exception as exc:
        return Result(data=data, error=f"could not be opened: {exc}")
    if "ppt/presentation.xml" not in names:
        return Result(data=data, error="has no ppt/presentation.xml")

    ns = {"p": _P}
    untitled = missing = machine = 0
    for name in names:
        if not re.fullmatch(r"ppt/slides/slide\d+\.xml", name):
            continue
        slide = etree.fromstring(z.read(name))
        titled = slide.xpath(
            "//p:ph[@type='title' or @type='ctrTitle']", namespaces=ns)
        if not titled:
            untitled += 1
        found = _classify_pictures(
            slide.xpath("//p:pic/p:nvPicPr/p:cNvPr", namespaces=ns))
        missing += found[0]
        machine += found[1]
    z.close()

    owed: list = []
    if untitled:
        owed.append(Owed(
            kind="slide-without-title", count=untitled,
            detail=("no title placeholder, so a screen reader user has no "
                    "slide titles to move between. A title is text "
                    "somebody has to write.")))
    owed.extend(_picture_owed(missing, machine))
    owed.extend(_title_owed(data))
    return Result(data=data, owed=owed)


def audit_legacy(data: bytes, language: Optional[str] = None,
                 name: str = "") -> Result:
    """Report a binary Office format, which cannot be inspected in place.

    Converting it to the current format would make it checkable, and is
    not done here, because the conversion renames the file and every
    reference to it inside the cartridge points at the old name. A
    remediation that broke the links it was trying to make usable would be
    worse than the gap.
    """
    suffix = Path(name).suffix.lower()
    kind = _LEGACY.get(suffix, "Office")
    return Result(data=data, owed=[Owed(
        kind="legacy-format", count=1,
        detail=(f"a legacy {kind} file ({suffix}), which cannot be inspected "
                f"or fixed in place. It needs converting to the current "
                f"format first, which renames it and so has to be done by "
                f"somebody who can update what links to it."))])
