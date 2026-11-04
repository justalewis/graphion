"""What a PDF states about its own structure, where it states anything.

`pdf_ingest` reconstructs a chapter from the geometry of the page, and the
reason is in CLAUDE.md: a PDF knows only where ink sits. That is true of a
PDF with no structure tree and it is not true of one with a good tree, and
this archive holds both under the same roof. Every one of its 118 originals
carries a tree, which is why reading one looked like an easy win; what they
carry differs so completely by how the volume was typeset that the count
alone says nothing.

Three things make reading a tree harder than it looks, and each is a way to
be confidently wrong.

**A tree can cover almost nothing.** The Word-exported volumes tag the
publisher's cover page and leave the chapter untouched, so a reader that
walked the tree and stopped would reconstruct a two-paragraph document and
report it as the article. `coverage` is the share of the text that sits
inside marked content at all, and `usable` is the gate: below it, the tree
is evidence about the cover page and nothing else.

**The RoleMap throws the headings away.** InDesign exports each paragraph
style twice, once mapped to its standard type and once flattened to `/P`,
and the document uses the flattened one. So `Header_A` maps to `/P` while
`Header_A_1` maps to `/H2`, and a reader that faithfully applies the
RoleMap gets a chapter with no headings in it at all. The level is still in
the file: `heading_levels()` reads it back off the RoleMap by pairing a
flattened style with its numbered twin, which is the file answering for
itself rather than this module knowing what a publisher calls a head.

**The tree names roles; only the page has text.** The marked-content id is
the one thing that joins them, so the text is collected per `(page, mcid)`
from pdfplumber and handed back to the elements that claim those ids. A
file whose chars carry no mcid cannot be joined however rich its tree
looks, which is the same failure as coverage and is reported the same way.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

# Below this share of the text inside marked content, a tree is about the
# cover page rather than about the chapter. The archive splits far wider
# than any threshold needs: see `docs/accessibility-service.md` for the
# measurement, which is why this sits where it does rather than being tuned.
USABLE_COVERAGE = 50.0

# The standard roles that name a heading, and the level each one means.
HEADING_ROLES = {
    "/H": 1, "/H1": 1, "/H2": 2, "/H3": 3,
    "/H4": 4, "/H5": 5, "/H6": 6, "/Title": 1,
}

# InDesign deduplicates a style that has to map two ways by appending a
# number, so `Header_A` and `Header_A_1` are the same style and only the
# second keeps its heading level.
_TWIN_SUFFIX_RE = re.compile(r"^(?P<stem>.+?)_(?P<n>\d+)$")

# How deep the walk goes before it gives up. A structure tree is shallow;
# a loop in one is what this is really for.
MAX_DEPTH = 100


@dataclass
class Element:
    """One element of the tree, with the text the page gives it."""

    role: str
    style: str
    page: Optional[int] = None
    text: str = ""
    alt: str = ""
    # The marked content this element claims, as `(page index, id)` pairs.
    # It is what joins the tree to the page, and it is kept rather than
    # consumed because a caller matching the tree against lines of its own
    # needs the same join and must not have to repeat it on the text.
    mcids: List[tuple] = field(default_factory=list)
    # Whether this element's text is part of the running body, inherited
    # from its ancestors by `walk`. False inside a caption, a note, a
    # figure or a table. See `carries_body_flow`.
    in_flow: bool = True

    @property
    def is_heading(self) -> bool:
        return self.role in HEADING_ROLES

    @property
    def is_figure(self) -> bool:
        return self.role == "/Figure"


@dataclass
class Outline:
    """What one file states about its own structure."""

    path: Path
    readable: bool = True
    error: str = ""
    elements: List[Element] = field(default_factory=list)
    chars: int = 0
    marked_chars: int = 0
    styles: Dict[str, int] = field(default_factory=dict)
    rolemap: Dict[str, str] = field(default_factory=dict)

    @property
    def tagged(self) -> bool:
        return bool(self.styles)

    @property
    def coverage(self) -> Optional[float]:
        """The share of the text that sits inside marked content.

        None where no text was read, which is not the same as none. A
        caller that asked for the roles alone, or a file whose pages would
        not open, has measured nothing, and a zero there would be a number
        reported for a reading that never happened.
        """
        if not self.chars:
            return None
        return self.marked_chars / self.chars * 100.0

    @property
    def usable(self) -> bool:
        """Whether the tree covers enough of the text to be read from.

        A tree that covers the cover page and nothing else is a true fact
        about the file and a useless one about the chapter, and the two
        look identical to anything that only asks whether a tree exists.
        """
        coverage = self.coverage
        return (self.tagged and coverage is not None
                and coverage >= USABLE_COVERAGE)

    def headings(self) -> List[Element]:
        return [e for e in self.elements if e.is_heading and e.text.strip()]

    def heading_map(self) -> Dict[tuple, int]:
        """Every marked id the file calls a heading, with its level.

        `(page index, marked id) -> level`, which is what a reconstruction
        joins its own lines on. Empty where the tree does not reach the
        text, so a caller gets the file's answer or nothing and never a
        reading of the cover page applied to a chapter.
        """
        if not self.usable:
            return {}
        out: Dict[tuple, int] = {}
        for element in self.elements:
            if not element.is_heading:
                continue
            level = HEADING_ROLES[element.role]
            for page, mcid in element.mcids:
                # A claim with no page or no id cannot be joined to a line
                # on one, so it is left out rather than carried as a key
                # nothing will ever match.
                if page is not None and mcid is not None:
                    out[(page, mcid)] = level
        return out


@dataclass
class Descent:
    """One place a reconstruction runs backwards through the file's order.

    `gap` is how far back it jumps, counted in marked ids, so a step back of
    one is two lines swapped and a step back of two hundred is a block that
    came to rest somewhere else entirely. The texts either side are carried
    because the number says there is a problem and only the words say what
    it is.
    """

    index: int
    gap: int
    before: str
    after: str


@dataclass
class OrderCheck:
    """How far a reconstruction's order agrees with the file's own.

    `placed` and `unplaced` are the evidence behind the descents: a chapter
    whose lines mostly carry no marked id has not been checked, however few
    descents it reports, which is the same distinction `coverage` draws and
    the same one `register.UNRUN` exists for.
    """

    descents: List["Descent"] = field(default_factory=list)
    placed: int = 0
    # Lines the file states no body-flow position for: a caption, a note, a
    # table cell, or a line carrying no marked id at all. Counted rather
    # than dropped quietly, because a reading made over half the lines is a
    # different reading and `share_placed` is what says so.
    unplaced: int = 0

    @property
    def read(self) -> int:
        return self.placed + self.unplaced

    @property
    def share_placed(self) -> Optional[float]:
        """What share of the text could be placed in the file's order.

        None where nothing was read, never zero, because a zero there is a
        number reported for a reading that did not happen.
        """
        if not self.read:
            return None
        return self.placed / self.read * 100.0

    @property
    def worst(self) -> int:
        return max((d.gap for d in self.descents), default=0)


# What a tree calls text the body flow does not carry, or that the pipeline
# repositions on purpose, so its place in the file says nothing about the
# reconstruction's order. Read off the file rather than guessed from the
# line, for the reason the heading levels are.
#
# Each entry is here because a chapter reported a descent for it. A caption
# is kept in its own branch, so `introduction-to-primary-research` jumped
# back 734 marked ids after "Fig. 2: A sample timeline" with nothing wrong.
# A footnote is kept where the page printed it while the tree collects the
# note elements elsewhere, which is all ten of `7-welhausen`'s descents. And
# a table's cells come out of the prose into a pipe table, so their place in
# the running text is not a reading of anything.
#
# Both the role and the style are tested, because the RoleMap flattens:
# `why-blog-searching-for-writing-on-the-web` holds its caption as role
# `/P` with style `/Caption`, which is the same export trick that hides the
# heading levels.
NOT_BODY_FLOW = frozenset({
    "/Caption", "/Note", "/Footnotes", "/Footnote",
    "/Figure", "/Formula",
    "/Table", "/TR", "/TD", "/TH", "/THead", "/TBody",
    "/TOC", "/TOCI", "/Artifact", "/Index",
})


def carries_body_flow(element: "Element") -> bool:
    """Whether this element's text is part of the running body.

    False for a caption, a note, a figure or a table cell: text the
    reconstruction places by a rule of its own, or that the tree keeps in
    its own branch, so comparing where it came out against where the file
    holds it measures a decision rather than a reading.

    `walk` works this out as it goes, because the answer is inherited and
    an element on its own cannot give it: a `/P` inside a `/Note` is still
    a note, and the text usually sits in a `/Span` below that again. One
    reader, so a caller cannot ask the question a second way and get a
    second answer.
    """
    return element.in_flow


def reading_order(outline: "Outline", gated: bool = True) -> Dict[tuple, int]:
    """Each marked id's place in the order the file states.

    `gated` false skips the document-level coverage check, and only one
    caller wants that. A repair applied to a single page needs to know
    whether the tree reaches *that page's* text, which `Outline.usable`
    cannot answer because it is computed over the whole document and only
    after every page has been read. `pdf_ingest` reads the tree before the
    page loop, for the order, and gates each page on its own marked share
    as it goes. One function either way, so the two cannot drift.

    Numbered over the body-flow elements in document order, so a marked id's
    position is where the tree puts the text it holds. This is the one thing
    a reconstruction's order can be checked against: every other reading of
    what order a page should come out in is the same inference that produced
    the reconstruction, so it would agree with itself and prove nothing.

    A caption, a note and a table cell are left out, by `carries_body_flow`,
    so a line holding one of them is reported unplaced rather than as text
    in the wrong place. The alternative was a pattern in `pdf_ingest`
    guessing which lines those were from how they read, which missed
    "Figs. 2-6." for want of a plural and every footnote this series prints
    without a stop after its number.

    Empty where the tree does not reach the text, by the rule `heading_map`
    follows, so a caller gets the file's answer or none of it.
    """
    if gated and not outline.usable:
        return {}
    if not outline.tagged:
        return {}
    out: Dict[tuple, int] = {}
    position = 0
    for element in outline.elements:
        if not carries_body_flow(element):
            continue
        for key in element.mcids:
            page, mcid = key
            if page is None or mcid is None:
                continue
            # A tree can claim one id from two elements; the first is where
            # the text is read.
            if key in out:
                continue
            out[key] = position
            position += 1
    return out


def order_descents(order: Dict[tuple, int], items) -> OrderCheck:
    """Where a reconstruction runs backwards through the file's own order.

    `items` is `(mcids, text)` in the order the reconstruction puts them.
    A line's position is the earliest of the ids it sits in, since that is
    where it starts.

    Counted as descents between consecutive lines rather than as an
    agreement over the whole chapter, because the defect is local and a
    whole-chapter figure hides it. The pull quote interleaved with a heading
    in `annoying-ways-people-use-sources` is six lines out of some three
    hundred: as a share of all the pairs that could be out of order it is
    0.02%, which no threshold could separate from a clean chapter, and as a
    count of places where the text jumps backwards it is a handful against
    zero. One is reportable and the other is not.
    """
    check = OrderCheck()
    positions: List[int] = []
    texts: List[str] = []
    for mcids, text in items:
        here = [order[key] for key in _keys_of(mcids) if key in order]
        if not here:
            check.unplaced += 1
            continue
        check.placed += 1
        positions.append(min(here))
        texts.append(text or "")

    for i in range(len(positions) - 1):
        if positions[i + 1] < positions[i]:
            check.descents.append(Descent(
                index=i,
                gap=positions[i] - positions[i + 1],
                before=texts[i][:120],
                after=texts[i + 1][:120],
            ))
    return check


def _keys_of(mcids) -> List[tuple]:
    """A line's `(page, id)` keys, however the caller holds them.

    `pdf_ingest.Line` carries a set of bare ids and the page separately,
    so the caller pairs them up before calling; anything already paired is
    passed through. Written once because getting it wrong gives a reading
    with every line unplaced, which looks like a file with no tree.
    """
    out = []
    for item in mcids or ():
        if isinstance(item, tuple) and len(item) == 2:
            out.append(item)
    return out


def heading_levels(rolemap: Dict[str, str]) -> Dict[str, int]:
    """The heading level each style means, read off the file's own RoleMap.

    A style the RoleMap flattens to `/P` keeps its level in a numbered twin
    that maps to a real heading, because that is how InDesign exports a
    style it has to map two ways. Pairing them recovers every heading in
    the richer half of this archive without this module knowing what any
    publisher calls a head, which is the same discipline `learn_layout`
    follows for the geometry: learned per document, never hardcoded.
    """
    direct = {style: HEADING_ROLES[role]
              for style, role in rolemap.items() if role in HEADING_ROLES}
    out = dict(direct)
    for style, level in direct.items():
        twin = _TWIN_SUFFIX_RE.match(style)
        if not twin:
            continue
        stem = twin.group("stem")
        # Only where the stem is a style of its own that was flattened; a
        # name that merely ends in a number is not a twin of anything.
        if rolemap.get(stem) == "/P" and stem not in out:
            out[stem] = level
    return out


def _page_numbers(reader) -> Dict[tuple, int]:
    out = {}
    for index, page in enumerate(reader.pages):
        ref = getattr(page, "indirect_reference", None)
        if ref is not None:
            out[(ref.idnum, ref.generation)] = index
    return out


def _page_of(obj, pages: Dict[tuple, int]) -> Optional[int]:
    ref = getattr(obj, "indirect_reference", None)
    if ref is None:
        ref = obj if hasattr(obj, "idnum") else None
    if ref is None:
        return None
    return pages.get((ref.idnum, ref.generation))


def _read_rolemap(tree) -> Dict[str, str]:
    try:
        raw = tree.get("/RoleMap") or {}
        return {str(k): str(v) for k, v in raw.items()}
    except Exception:
        return {}


def walk(tree, pages: Dict[tuple, int], rolemap: Dict[str, str],
         levels: Dict[str, int]) -> tuple:
    """Every element of the tree in document order, with its marked ids.

    Returns `(elements, styles)`. Each element carries the `(page, id)`
    pairs it claims, which is the only thing that joins a role to the text
    on the page.
    """
    elements: List[Element] = []
    styles: Dict[str, int] = {}
    seen: set = set()

    def collect(node, page: Optional[int], into: list,
                in_flow: bool = True) -> None:
        try:
            obj = node.get_object() if hasattr(node, "get_object") else node
        except Exception:
            return
        if isinstance(obj, int):
            into.append((page, obj))
        elif isinstance(obj, list):
            for kid in obj:
                collect(kid, page, into, in_flow)
        elif isinstance(obj, dict):
            kind = str(obj.get("/Type") or "")
            if kind == "/MCR":
                where = _page_of(obj.get("/Pg"), pages) if obj.get("/Pg") else page
                mcid = obj.get("/MCID")
                if isinstance(mcid, int):
                    into.append((where, mcid))
            elif kind == "/OBJR":
                # An annotation, which carries no text of its own.
                return
            else:
                descend(obj, page, in_flow=in_flow)

    def descend(node, page: Optional[int], depth: int = 0,
                in_flow: bool = True) -> None:
        if depth > MAX_DEPTH:
            return
        try:
            obj = node.get_object() if hasattr(node, "get_object") else node
        except Exception:
            return
        if isinstance(obj, list):
            for kid in obj:
                descend(kid, page, depth + 1, in_flow)
            return
        if not isinstance(obj, dict):
            return
        marker = id(obj)
        if marker in seen:
            return
        seen.add(marker)

        style = str(obj.get("/S") or "")
        here = page
        if obj.get("/Pg") is not None:
            found = _page_of(obj["/Pg"], pages)
            if found is not None:
                here = found

        if style:
            styles[style] = styles.get(style, 0) + 1
            # The level the file states for this style wins over whatever
            # the RoleMap flattened it to; everything else is the mapped
            # role, or the style itself where the map says nothing.
            if style in levels:
                role = "/H%d" % levels[style]
            else:
                role = rolemap.get(style, style)
            # Whether this element's text is part of the running body, and
            # it is inherited: a `/P` inside a `/Note` is still a note, and
            # the text usually sits in a `/Span` below that again. Testing
            # the element alone left all ten of `7-welhausen`'s footnote
            # descents standing, because the ids belong to the spans.
            in_flow = in_flow and not (role in NOT_BODY_FLOW
                                       or style in NOT_BODY_FLOW)
            element = Element(role=role, style=style, page=here,
                              alt=str(obj.get("/Alt") or "").strip(),
                              in_flow=in_flow)
            elements.append(element)
            mine = element.mcids
        else:
            mine = []

        if "/K" in obj:
            collect(obj["/K"], here, mine, in_flow)

    descend(tree, None)
    return elements, styles


def read(path, text: bool = True, chars: Optional[tuple] = None) -> Outline:
    """Read one PDF's structure tree. Writes nothing.

    `text` false skips the pdfplumber pass that joins the elements to the
    page, which is most of the cost: a caller counting roles does not need
    it, and `coverage` is then unknown rather than wrong.

    `chars` is `(total, marked)` from a caller that has already walked the
    pages, which `pdf_ingest` has by the time it asks. It buys the coverage
    gate without a second pass over the file, and it is passed in rather
    than assigned afterwards so that a count nobody made stays None.
    """
    from pypdf import PdfReader

    outline = Outline(path=Path(path))
    if chars:
        outline.chars, outline.marked_chars = chars
    try:
        reader = PdfReader(str(path))
        root = reader.trailer["/Root"]
    except Exception as exc:
        outline.readable = False
        outline.error = f"{type(exc).__name__}: {exc}"
        return outline

    if "/StructTreeRoot" not in root:
        return outline

    try:
        tree = root["/StructTreeRoot"].get_object()
    except Exception as exc:
        outline.readable = False
        outline.error = f"{type(exc).__name__}: {exc}"
        return outline

    outline.rolemap = _read_rolemap(tree)
    levels = heading_levels(outline.rolemap)
    outline.elements, outline.styles = walk(
        tree, _page_numbers(reader), outline.rolemap, levels)

    if not text:
        return outline

    _join_text(outline)
    return outline


def _join_text(outline: Outline) -> None:
    """Hand each element the text of the marked content it claims."""
    import collections

    import pdfplumber

    # Reset rather than add to, so a caller that passed its own counts and
    # then asked for the text does not get them twice.
    outline.chars = outline.marked_chars = 0
    by_id: dict = collections.defaultdict(list)
    try:
        with pdfplumber.open(str(outline.path)) as pdf:
            for index, page in enumerate(pdf.pages):
                try:
                    chars = page.chars
                except Exception:
                    continue
                for char in chars:
                    outline.chars += 1
                    mcid = char.get("mcid")
                    if mcid is None:
                        continue
                    outline.marked_chars += 1
                    by_id[(index, mcid)].append(char.get("text") or "")
    except Exception as exc:
        outline.error = f"{type(exc).__name__}: {exc}"
        return

    for element in outline.elements:
        parts = []
        for key in element.mcids:
            parts.extend(by_id.get(key, ()))
        element.text = " ".join("".join(parts).split())
