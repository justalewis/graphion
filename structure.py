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

    Returns `(elements, mcids, styles)`, where `mcids` is a list parallel
    to `elements` holding each one's `(page, id)` pairs. They are kept
    apart so a caller that only wants the roles need not open the file a
    second time to join the text.
    """
    elements: List[Element] = []
    claims: List[list] = []
    styles: Dict[str, int] = {}
    seen: set = set()

    def collect(node, page: Optional[int], into: list) -> None:
        try:
            obj = node.get_object() if hasattr(node, "get_object") else node
        except Exception:
            return
        if isinstance(obj, int):
            into.append((page, obj))
        elif isinstance(obj, list):
            for kid in obj:
                collect(kid, page, into)
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
                descend(obj, page)

    def descend(node, page: Optional[int], depth: int = 0) -> None:
        if depth > MAX_DEPTH:
            return
        try:
            obj = node.get_object() if hasattr(node, "get_object") else node
        except Exception:
            return
        if isinstance(obj, list):
            for kid in obj:
                descend(kid, page, depth + 1)
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
            element = Element(role=role, style=style, page=here,
                              alt=str(obj.get("/Alt") or "").strip())
            elements.append(element)
            mine: list = []
            claims.append(mine)
        else:
            element = None
            mine = []

        if "/K" in obj:
            collect(obj["/K"], here, mine)

    descend(tree, None)
    return elements, claims, styles


def read(path, text: bool = True) -> Outline:
    """Read one PDF's structure tree. Writes nothing.

    `text` false skips the pdfplumber pass that joins the elements to the
    page, which is most of the cost: a caller counting roles does not need
    it, and `coverage` is then unknown rather than wrong.
    """
    from pypdf import PdfReader

    outline = Outline(path=Path(path))
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
    elements, claims, styles = walk(
        tree, _page_numbers(reader), outline.rolemap, levels)
    outline.elements = elements
    outline.styles = styles

    if not text:
        return outline

    _join_text(outline, claims)
    return outline


def _join_text(outline: Outline, claims: List[list]) -> None:
    """Hand each element the text of the marked content it claims."""
    import collections

    import pdfplumber

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

    for element, mine in zip(outline.elements, claims):
        parts = []
        for key in mine:
            parts.extend(by_id.get(key, ()))
        element.text = " ".join("".join(parts).split())
