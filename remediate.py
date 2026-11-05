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
