"""Stage 1 ingest for PDF sources.

DOCX ingest hands Pandoc a file that already knows what a paragraph is. A
PDF knows only where ink sits, so this module reconstructs the structure
the typesetter destroyed: it groups characters into lines, lines into
paragraphs, strips the furniture a page carries (running heads, folios,
the rotated volume label in the margin), rejoins words the justification
broke across a line, puts the dropped initial back on the front of its
own sentence, and recovers headings and italics from type size and font
name. What comes out is Markdown with YAML front matter, which then goes
through the same Stage 2 cleanups as any other source.

The geometry is learned per document rather than hardcoded. A series
redesign between volumes, or a chapter set on a different measure, should
degrade the result rather than silently misread every page.

pdfplumber does the character extraction. PyMuPDF is faster and reports
more, but it is AGPL, and this app is deployed; pdfplumber is MIT over
pdfminer.six and reports everything needed here.

Nothing in this module is Writing Spaces specific except the default
`GENRE_HEADS`, which only improves front-matter detection and can be
passed per journal.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional


def available() -> bool:
    """Probe for pdfplumber. Single-dependency shape, as in `ocr.py`."""
    try:
        import pdfplumber  # noqa: F401
    except Exception:
        return False
    return True


# Heads that mark the end of the chapter body in this series. Used only to
# decide where the body stops and the back matter starts; an unrecognized
# head is still emitted as a head.
GENRE_HEADS = (
    "works cited",
    "references",
    "notes",
    "teacher resources",
    "discussion questions",
    "recommended activities",
    "overview and teaching strategies",
)

# A symbol font stores pictures at ordinary character codes, so what a PDF
# reader gets back from a run set in one is not text at all. Wingdings byte
# 0x7B is an open circle, and extracting it gives "{"; byte 0x4A is a smiling
# face, and gives "J". Others land in the private use area as U+F0xx, which
# is worse than wrong: a private use codepoint means nothing to a screen
# reader, and Typst validates PDF/UA rather than declaring it, so one of them
# aborts the compile and costs the chapter its conformance.
#
# Only the font knows which it is, and the font name is gone by the time the
# text reaches Stage 2, so the substitution has to happen here. Every entry
# below was read off the page it came from rather than taken from a chart:
# the archive's own encodings are subsetted and need not agree with one.
SYMBOL_FONT_CHARS = {
    "wingdings": {
        0x4A: "☺",  # smiling face; the "type J in Wingdings" artifact
        0x7B: "○",  # open circle, set as a bullet and as an empty
                         # option beside a survey answer
        0x86: "□",  # open square, set as a bullet
        0xAF: "✳",  # spoked ornament, set three in a row as a break
        0xE0: "→",  # right arrow, between the stages of a process
        0xFC: "✓",  # check mark, in a table cell
    },
    "symbol": {
        0xA5: "•",  # bullet, down the side of a sample resume
    },
}
# Font families whose text comes back correct and must not be remapped:
# OpenSymbol and SymbolMT both decode their bullet to U+2022 already.
_SYMBOL_FAMILIES = {
    "wingdings": "wingdings",
    "wingdings-regular": "wingdings",
    "wingdings2": "wingdings",
    "wingdings3": "wingdings",
    "symbol": "symbol",
}

# A line is a new paragraph when it starts at least this far right of the
# text edge. The series indents 14.4pt; half of that is clear of any
# justification wobble while still catching a real indent.
INDENT_MIN = 6.0
# A run of lines inset by at least this much on the left, with no
# first-line indent pattern, reads as a block quotation.
QUOTE_INSET_MIN = 18.0
# Type this much larger than the body is a head, not body copy.
HEAD_SIZE_DELTA = 0.6
# Type this much larger than the body is a dropped initial, not a head.
DROPCAP_SIZE_FACTOR = 2.5
# A step between lines this much larger than the paragraph's own leading is
# space between blocks. Measured on the series: 13.2pt inside a paragraph,
# 17.5pt and up between them, so the two never come close to overlapping.
PARA_GAP_FACTOR = 1.25


@dataclass
class Line:
    """One typeset line, with its ink position and the fonts it uses."""
    text: str
    size: float
    x0: float
    x1: float
    top: float
    page: int
    italic: bool = False
    fonts: set = field(default_factory=set)
    # Size of the line's first character. A dropped initial is not a line of
    # its own: it sits on the same baseline band as the text beside it, so
    # pdfplumber hands back "Afew semesters back" and only the leading
    # character's size says that the "A" was ever separate.
    lead_size: float = 0.0
    dropcap: bool = False
    # The marked content ids this line's characters sit inside, which is
    # the only thing that joins a line to what a structure tree says about
    # it. Empty for a file with no tree, which is every file this module
    # read before `structure.py` existed.
    mcids: set = field(default_factory=set)
    # The level the file states for this line, where it states one. Set
    # from the tree and never inferred; `classify` lets it win.
    heading_level: Optional[int] = None

    @property
    def centre(self) -> float:
        return (self.x0 + self.x1) / 2

    @property
    def plain(self) -> str:
        return re.sub(r"\*+", "", self.text)


@dataclass
class Layout:
    """Geometry learned from the document itself."""
    body_size: float
    body_left: float
    body_right: float
    body_top: float
    body_bottom: float
    page_centre: float
    # Baseline-to-baseline distance inside a paragraph. Zero means it could
    # not be learned, and the gap rule then stays out of the way.
    line_pitch: float = 0.0


@dataclass
class IngestResult:
    front_matter: dict
    body: str
    notes: list


# ---------- character and line assembly ----------


def _superscript_runs(chars: list, body_size: float) -> set:
    """Indices of characters set as superscripts.

    A footnote reference is printed as a raised, smaller digit, and flattening
    it into the text gives "assignment.1", which reads as a sentence ending in
    the number one. Both tests are needed: small type alone also matches a
    footnote's own body, and a raised baseline alone matches nothing reliably
    once a line mixes sizes.
    """
    if not chars:
        return set()
    baseline = statistics.median([c["bottom"] for c in chars])
    out = set()
    for i, ch in enumerate(chars):
        if not ch["text"].strip():
            continue
        smaller = ch.get("size", body_size) < body_size * 0.8
        raised = ch["bottom"] < baseline - body_size * 0.12
        if smaller and raised:
            out.add(i)
    return out


def symbol_family(fontname: str) -> Optional[str]:
    """The symbol font a PDF font name names, or None for a text font.

    PDF font names carry a subset prefix: `TKVGHF+Wingdings-Regular`. The
    match is on the whole family after that prefix, not a substring, so
    SymbolMT and OpenSymbol are left alone; both decode correctly already,
    and remapping them would break text that is not broken.
    """
    family = (fontname or "").split("+")[-1].strip().lower()
    return _SYMBOL_FAMILIES.get(family)


def translate_symbol_char(fontname: str, ch: str) -> str:
    """What a character set in a symbol font actually says.

    Returns the character unchanged when the font is a text font, or when
    the font is a symbol font whose code is not one this archive uses and
    the code could still be ordinary text.

    An unmapped private use codepoint is dropped instead. It cannot be read
    by anything, and leaving it in place fails the PDF/UA compile, so the
    choice is between losing a glyph and losing the chapter's conformance.
    An unmapped code outside that area is left alone: dropping it on the
    strength of a font-name match could eat real text.
    """
    family = symbol_family(fontname)
    if family is None or not ch:
        return ch
    code = ord(ch)
    if 0xF000 <= code <= 0xF0FF:
        code -= 0xF000
    elif code > 0xFF:
        return ch
    mapped = SYMBOL_FONT_CHARS.get(family, {}).get(code)
    if mapped is not None:
        return mapped
    if 0xE000 <= ord(ch) <= 0xF8FF:
        return ""
    return ch


def _line_text(line_text: str, chars: list, supers: Optional[set] = None) -> tuple:
    """Overlay italics and footnote markers onto an already-spaced line.

    A PDF does not have to store a space: a typesetter can simply move the
    pen, so the gap between two characters is what says whether a space
    belongs there. Deciding that here from a fixed threshold fails on tightly
    set justified lines, which is how a line of a Works Cited entry came out
    as "Agency:TheRoleofSelf-EfficacyBeliefs". pdfplumber already makes that
    call with a tolerance tuned for it, so its text is taken as the authority
    for spacing and only the markup is added here.

    That means walking the two in step: every non-space character in the text
    corresponds to the next character object in order, and the inserted
    spaces correspond to nothing. Italic runs come from the font name, which
    is the only place a PDF records emphasis.
    """
    supers = supers or set()
    out: list = []
    fonts = set()
    italic_any = False
    in_italic = False
    super_run: list = []
    idx = 0

    def flush_super():
        nonlocal super_run
        if super_run:
            out.append("[^" + "".join(super_run) + "]")
            super_run = []

    def close_italic():
        nonlocal in_italic
        if in_italic:
            out.append("*")
            in_italic = False

    for cell in line_text:
        if cell.isspace():
            flush_super()
            # Close the run before the space: a marker with a space inside it
            # is not emphasis to any Markdown reader.
            close_italic()
            out.append(cell)
            continue
        ch = chars[idx] if idx < len(chars) else None
        if ch is None:
            out.append(cell)
            continue
        idx += 1
        font = ch.get("fontname") or ""
        fonts.add(font)
        cell = translate_symbol_char(font, cell)
        if not cell:
            continue
        if (idx - 1) in supers and cell.isdigit():
            close_italic()
            super_run.append(cell)
            continue
        flush_super()
        italic = "italic" in font.lower() or "oblique" in font.lower()
        if italic and not in_italic:
            out.append("*")
            in_italic = True
            italic_any = True
        elif not italic and in_italic:
            close_italic()
        out.append(cell)
    flush_super()
    close_italic()
    text = "".join(out)
    # An italic run covering only punctuation or space is noise, not emphasis.
    text = re.sub(r"\*(\s*[^\w*]*\s*)\*", r"\1", text)
    return text.strip(), italic_any, fonts


# Path-painting operators, each of which ends the current path. A clipping
# path set with `W` takes effect at whichever of these follows it; `n` is the
# one that paints nothing, and is how a path is used for clipping alone.
_PAINT_OPS = ("S", "s", "f", "F", "f_a", "B", "B_a", "b", "b_a", "n")
# A `W` operator ends where the next token begins, so the byte after it is
# whitespace, a delimiter, or the `*` of `W*`; it is never a letter or a
# digit. A page whose stream holds no such pair cannot be clipping anything,
# which is 90% of this series and saves them the second parse. Matching more
# than the operator only costs a parse; matching less would lose a page.
_MAY_CLIP_RE = re.compile(rb"W[^A-Za-z0-9]")
_clip_reader = None


def _may_clip(page) -> bool:
    """Could this page's content stream set a clipping path at all?"""
    from pdfminer.pdftypes import resolve1

    try:
        data = b"".join(resolve1(s).get_data() for s in page.page_obj.contents)
    except Exception:
        return True
    return bool(_MAY_CLIP_RE.search(data))


def _clip_classes():
    """The interpreter and device that read a page's clipping path.

    pdfminer parses `W` and `W*` and then does nothing with them, so every
    glyph the content stream draws is reported whether the page prints it or
    not. Built on first use and cached, because pdfminer is reached through
    pdfplumber and both stay optional.
    """
    global _clip_reader
    if _clip_reader is not None:
        return _clip_reader

    from pdfminer.converter import PDFPageAggregator
    from pdfminer.pdfinterp import PDFPageInterpreter
    from pdfminer.utils import apply_matrix_pt

    def path_bbox(curpath, ctm):
        """The box a path covers, in the space the glyph boxes use.

        `curpath` holds the operands as the stream wrote them, so the
        current transformation matrix has still to be applied. A curve
        contributes its control points, whose box contains the curve, so a
        clip this cannot describe exactly comes out too large and keeps ink
        rather than losing it.
        """
        points = []
        for segment in curpath:
            numbers = [v for v in segment[1:] if isinstance(v, (int, float))]
            for i in range(0, len(numbers) - 1, 2):
                points.append(apply_matrix_pt(ctm, (numbers[i], numbers[i + 1])))
        if not points:
            return None
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        return (min(xs), min(ys), max(xs), max(ys))

    def narrow(clip, box):
        if clip is None:
            return box
        if box is None:
            return clip
        return (max(clip[0], box[0]), max(clip[1], box[1]),
                min(clip[2], box[2]), min(clip[3], box[3]))

    class ClipInterpreter(PDFPageInterpreter):
        """pdfminer's interpreter, with the clipping path kept.

        The clip is part of the graphics state, so `q` and `Q` have to save
        and restore it alongside the matrix pdfminer already stacks.
        """

        def init_state(self, ctm):
            super().init_state(ctm)
            self.clip = None
            self.clipstack: list = []
            self.pending_clip = False

        def do_q(self):
            self.clipstack.append(self.clip)
            super().do_q()

        def do_Q(self):
            if self.clipstack:
                self.clip = self.clipstack.pop()
            super().do_Q()

        def do_W(self):
            self.pending_clip = True

        def do_W_a(self):
            self.pending_clip = True

        def settle_clip(self):
            if self.pending_clip:
                self.clip = narrow(self.clip, path_bbox(self.curpath, self.ctm))
                self.pending_clip = False

    def paints(name):
        painted = getattr(PDFPageInterpreter, "do_" + name, None)
        if painted is None:
            return

        def op(self, *args, **kwargs):
            self.settle_clip()
            return painted(self, *args, **kwargs)

        setattr(ClipInterpreter, "do_" + name, op)

    for name in _PAINT_OPS:
        paints(name)

    class ClipDevice(PDFPageAggregator):
        """Records the box of every glyph drawn wholly outside the clip."""

        def __init__(self, rsrcmgr, **kwargs):
            super().__init__(rsrcmgr, **kwargs)
            self.clipped: set = set()
            self.glyphs = 0
            self.interpreter = None

        def render_char(self, *args, **kwargs):
            advance = super().render_char(*args, **kwargs)
            self.glyphs += 1
            # pdfminer reports no handle on what it just made, so the glyph
            # is read back off the layout, which is how pdfplumber stamps a
            # marked-content id on one.
            if self.cur_item._objs:
                box = self.cur_item._objs[-1].bbox
                if outside_clip(box, self.interpreter.clip):
                    self.clipped.add(tuple(round(v, 2) for v in box))
            return advance

    _clip_reader = (ClipInterpreter, ClipDevice)
    return _clip_reader


def _glyph_box(obj) -> tuple:
    return (round(obj["x0"], 2), round(obj["y0"], 2),
            round(obj["x1"], 2), round(obj["y1"], 2))


def outside_clip(box, clip) -> bool:
    """Does the clip remove this glyph altogether?

    Wholly outside, never merely trimmed. A clip that cuts through a glyph
    leaves part of it on the page, and half a letter read is better than a
    letter dropped; a box reported a fraction of a point past the frame it
    sits in is the commoner case by far.
    """
    if clip is None:
        return False
    return not (box[2] > clip[0] and box[0] < clip[2]
                and box[3] > clip[1] and box[1] < clip[3])


def clipped_glyphs(page) -> frozenset:
    """The glyphs this page draws and then clips away, by their boxes.

    A page may set a clipping path and draw past it, and what falls outside
    is not printed. pdfplumber reports it all the same, which is how volume
    1's chapter 6 came through with the overflow of a reproduced Word page
    interleaved character by character into the prose beside it
    (`IW ue sseindc etrheliys h ocpaeu tai olenssaorny`): two streams at
    overlapping baselines, which `extract_text_lines` reads as one line.

    Nothing here is inferred from the look of the page. The clip is read off
    the content stream, so the question each glyph answers is the one that
    matters, which is whether the page printed it. Guessing at the shape
    instead would not have worked anyway: the two streams overlap in x, so
    no column boundary separates them.

    A second parse of the page buys that, so `_may_clip` is asked first and
    nine pages in ten never reach here.
    """
    if not _may_clip(page):
        return frozenset()
    interpreter_class, device_class = _clip_classes()
    device = device_class(page.pdf.rsrcmgr, laparams=None)
    interpreter = interpreter_class(page.pdf.rsrcmgr, device)
    device.interpreter = interpreter
    interpreter.process_page(page.page_obj)
    if device.glyphs != len(page.chars):
        # The two readings have to be of the same page for the boxes to mean
        # anything. They never disagreed across this series; if they ever do,
        # the page comes through as it always did.
        return frozenset()
    return frozenset(device.clipped)


def drop_clipped_ink(page):
    """The page without the ink it clips away, and how much that was.

    Done before the lines are assembled and before the tables are found,
    because both read it otherwise: the prose takes the overflow into a
    paragraph, and a box that happens to enclose it prints it in a cell.
    Volume 2's chapter 3 carried 71 characters of a comment balloon that
    the page truncates into a pipe table that way.
    """
    try:
        clipped = clipped_glyphs(page)
    except Exception:
        return page, 0
    if not clipped:
        return page, 0
    kept = page.filter(lambda obj: obj.get("object_type") != "char"
                       or _glyph_box(obj) not in clipped)
    return kept, len(clipped)


def _page_lines(page, page_no: int) -> list:
    """Lines on one page, with the rotated margin furniture dropped.

    The volume label runs up the outer margin, so its characters are not
    upright. pdfplumber will happily read them as a line of text, which is
    how "WRITING SPACES 5" arrives as a line reading "SECAPS". Dropping
    non-upright characters before line assembly removes the whole tab
    without having to recognise its wording.
    """
    upright = page.filter(lambda obj: obj.get("upright", True))
    raw_lines = upright.extract_text_lines(return_chars=True, strip=True)
    # The page's own commonest character size stands in for the body size,
    # which the document-wide pass has not worked out yet. It only has to be
    # good enough to spot a superscript against.
    page_body = _modal([c["size"] for ln in raw_lines for c in ln["chars"]]) or 10.0
    lines = []
    for raw in raw_lines:
        chars = sorted(raw["chars"], key=lambda c: c["x0"])
        if not chars:
            continue
        lead_size = round(chars[0]["size"], 1)
        line_src = raw["text"]
        dropcap = lead_size >= page_body * DROPCAP_SIZE_FACTOR and len(chars) > 1
        if dropcap:
            # A dropped initial is set so large that its advance width reaches
            # under the text beside it. pdfplumber measures the gap to the
            # next character from that overhang, decides the first gap is
            # negative and the second is wide, and produces "Af ew semesters".
            # Clipping the initial's width back to where the text actually
            # resumes leaves the spacing to be measured normally. Whether a
            # space belongs after the initial is split_dropcap's decision,
            # not a question of where the ink sits.
            chars = [dict(chars[0], x1=chars[1]["x0"])] + chars[1:]
            line_src = _extract_text(chars)
        text, italic, fonts = _line_text(
            line_src, chars, _superscript_runs(chars, page_body)
        )
        if not text:
            continue
        sizes = [c["size"] for c in chars]
        lines.append(Line(
            text=text,
            mcids={c["mcid"] for c in chars if c.get("mcid") is not None},
            size=round(statistics.median(sizes), 1),
            x0=round(raw["x0"], 1),
            x1=round(raw["x1"], 1),
            top=round(raw["top"], 1),
            page=page_no,
            italic=italic,
            fonts=fonts,
            lead_size=lead_size,
            dropcap=dropcap,
        ))
    return lines


def _extract_text(chars: list) -> str:
    """pdfplumber's own spacing, applied to one line's characters.

    The tolerance is set explicitly: called on a bare list rather than
    through a page, pdfplumber defaults to a wider one and returns the line
    with every space missing.
    """
    from pdfplumber.utils import extract_text

    return extract_text(chars, x_tolerance=1.5)


def _modal(values: Iterable, ndigits: int = 1) -> float:
    vals = [round(v, ndigits) for v in values]
    if not vals:
        return 0.0
    try:
        return statistics.mode(vals)
    except statistics.StatisticsError:
        return statistics.median(vals)


def learn_layout(lines: list, page_width: float) -> Layout:
    """Work out the body size and text block from the lines themselves."""
    body_size = _modal(l.size for l in lines)
    body = [l for l in lines if abs(l.size - body_size) < 0.05]
    if not body:
        body = lines

    # The commonest step between one body line and the next is the leading
    # inside a paragraph. Anything appreciably larger is space the typesetter
    # put between blocks, which is the only mark separating two quoted
    # paragraphs: they share an indent, so position alone runs them together.
    steps: dict = {}
    previous = None
    for line in body:
        if previous is not None and previous.page == line.page:
            step = round(line.top - previous.top, 1)
            if 0 < step < body_size * 3:
                steps[step] = steps.get(step, 0) + 1
        previous = line
    pitch = max(steps, key=steps.get) if steps else 0.0

    return Layout(
        body_size=body_size,
        body_left=_modal(l.x0 for l in body),
        body_right=max((l.x1 for l in body), default=page_width),
        body_top=_modal(min(l.top for l in body if l.page == p)
                        for p in sorted({l.page for l in body})),
        body_bottom=max((l.top for l in body), default=0.0),
        page_centre=page_width / 2,
        line_pitch=pitch,
    )


def strip_furniture(lines: list, layout: Layout) -> tuple:
    """Drop running heads and folios.

    Both sit outside the text block vertically, which is a more durable
    test than matching their wording: a running head carries the author
    names or the short title, and either can be mistaken for body copy by
    any content-based rule.
    """
    kept, dropped = [], []
    for line in lines:
        # Furniture is always set small. Without this guard the chapter
        # number on the opening page, which hangs above the text block and is
        # a bare digit, is indistinguishable from a running head's folio, and
        # gets thrown away with it.
        small = line.size <= layout.body_size + 0.5
        is_folio = bool(re.fullmatch(r"[\divxlcDIVXLC]+", line.plain.strip()))
        above_block = line.top < layout.body_top - 4
        below_block = line.top > layout.body_bottom + 4
        if small and (above_block or (below_block and is_folio)):
            dropped.append(line)
        else:
            kept.append(line)
    return kept, dropped


# ---------- word repair ----------


_WORD_RE = re.compile(r"[A-Za-z][A-Za-z'’]+")


def build_vocabulary(lines: list) -> tuple:
    """Words the document uses, and the hyphenated compounds it uses.

    This is the only evidence available for telling a hyphen the
    typesetter inserted from one the author wrote, short of shipping a
    dictionary. A chapter that writes "school-sponsored" in the middle of
    a line has told us which kind the one at the line break is.
    """
    plain, hyphenated = set(), set()
    for line in lines:
        text = line.plain
        if line.dropcap:
            # The first word of a dropped-initial line is the one word in the
            # document that may be wrong ("Afew"), and it is exactly the word
            # split_dropcap is about to ask this vocabulary about. Leaving it
            # in lets the error vouch for itself.
            text = re.sub(r"^\S+\s*", "", text)
        for match in _WORD_RE.finditer(text):
            plain.add(match.group(0).lower())
        for match in re.finditer(r"([A-Za-z]+)-([A-Za-z]+)", text):
            hyphenated.add(match.group(0).lower())
    return plain, hyphenated


def rejoin_hyphen(head: str, tail: str, vocab: set, compounds: set) -> str:
    """Decide what a hyphen at a line break meant, and join accordingly.

    Defaults to removing it, because in justified book setting most line
    breaks inside a word are the typesetter's doing. The exceptions are
    checked first: a capital after the hyphen is a real compound
    ("anti-Racist"), as is a pairing the document itself writes hyphenated
    somewhere it did not have to.
    """
    head_word = re.search(r"([A-Za-z]+)$", head)
    tail_word = re.match(r"([A-Za-z'’]+)", tail)
    if not head_word or not tail_word:
        return head + tail
    left, right = head_word.group(1), tail_word.group(1)
    if right[:1].isupper():
        return head + "-" + tail
    if f"{left}-{right}".lower() in compounds:
        return head + "-" + tail
    if f"{left}{right}".lower() in vocab:
        return head + tail
    return head + tail


def join_lines(lines: list, vocab: set, compounds: set) -> str:
    """Join typeset lines back into running prose."""
    out = ""
    for line in lines:
        text = line.text
        if not out:
            out = text
            continue
        # The hyphen is not always the last character: an italic run that was
        # broken across the line closes after it, so a Works Cited title ends
        # "Rhet-*" and resumes "*oric". Testing only the final character
        # leaves those words split, with stray emphasis markers mid-word.
        broken = re.match(r"^(.*[^-])-(\*{1,2})?$", out, re.S)
        if broken:
            head, marks = broken.group(1), broken.group(2) or ""
            if marks and text.startswith(marks):
                # Same markers on both sides: one run the typesetter split,
                # so drop both and let the run carry across the join.
                out = rejoin_hyphen(head, text[len(marks):], vocab, compounds)
            else:
                out = rejoin_hyphen(head + marks, text, vocab, compounds)
        else:
            out = out + " " + text
    return re.sub(r"\s+", " ", out).strip()


# ---------- structure ----------


def classify(line: Line, layout: Layout) -> str:
    """What kind of line this is, by size and position.

    A level the file states wins over all of it, because size and position
    are what miss the heads that matter. `Header_B` and `Header_C` are set
    at body size and read as prose; across this series' own trees, 262 of
    784 stated headings are absent from the Markdown, and H5, which is
    body size in italic, is absent 90 times out of 92. Where no tree
    reaches the text nothing is stated and the geometry is all there is,
    which is what every file read here before.
    """
    if line.heading_level:
        return "head"
    if line.size >= layout.body_size * DROPCAP_SIZE_FACTOR:
        return "dropcap"
    if line.size > layout.body_size + HEAD_SIZE_DELTA:
        centred = abs(line.centre - layout.page_centre) < 12
        return "head" if centred else "title"
    if line.size < layout.body_size - 0.5:
        return "note"
    if line.x0 > layout.body_left + QUOTE_INSET_MIN:
        return "quote"
    return "body"


def apply_stated_headings(lines: list, heads: dict) -> int:
    """Mark the lines a file's own structure tree calls headings.

    Joined on the marked content id, which is the only thing that ties a
    structure element to the ink on the page: nothing here is read off how
    the line is set, which is the point, since how it is set is exactly
    what misses it. Returns how many lines were marked, for the note the
    caller leaves.

    `line.page` counts from one, as every page number in this module does,
    and a structure tree indexes its pages from zero.

    A line that claims two levels is a head something was joined to, and
    the shallower is the one the outline hangs from.
    """
    marked = 0
    for line in lines:
        levels = [heads[(line.page - 1, mcid)] for mcid in line.mcids
                  if (line.page - 1, mcid) in heads]
        if not levels:
            continue
        line.heading_level = min(levels)
        marked += 1
    return marked


_LIST_RE = re.compile(r"^(\d{1,2})[.)]\s+")
_NOTE_RE = re.compile(r"^(\d{1,3})[.)]\s+")

# A reference to a note, not a definition of one, which is what the trailing
# colon rules out.
_FOOTNOTE_KEY_RE = re.compile(r"\[\^([^\]\s]+)\](?!:)")
# A footnote marked with a symbol rather than a number, which this series
# uses for the licence it prints on a chapter's opening page.
_MARKER_START_RE = re.compile(r"^([*+\-]|\d{1,3}[.)])\s+")
# The digits of an ordered marker, so the backslash can go after them.
_ORDERED_START_RE = re.compile(r"^(\d{1,3})[.)]\s+")


def escape_list_marker(text: str) -> str:
    """Keep a line that opens with a list marker from becoming a list.

    The licence footnote is marked with an asterisk, not a number, so it
    falls past `_NOTE_RE` and is written out as it was read. Markdown then
    reads the asterisk as a list marker and the galley prints the licence as
    a bulleted item in the middle of the chapter, which is where 69 of the
    series' chapters had it. Escaping the marker leaves the printed text
    exactly as the page set it.

    A number is escaped after its digits and a bullet in front, because a
    backslash escapes punctuation and nothing else: "\\1." is not an escape
    at all, and Pandoc prints the backslash. Only a note that nothing refers
    to reaches this with a number in front of it, which is why the one-rule
    version stood while every numbered note was becoming a definition.
    """
    ordered = _ORDERED_START_RE.match(text)
    if ordered:
        return text[:ordered.end(1)] + "\\" + text[ordered.end(1):]
    if _MARKER_START_RE.match(text):
        return "\\" + text
    return text


def _is_list_start(line: Line, layout: Layout) -> bool:
    return bool(_LIST_RE.match(line.text)) and line.x0 > layout.body_left


def split_dropcap(text: str, vocab: set) -> str:
    """Put a space back after a dropped initial that was a word on its own.

    A dropped initial is usually the first letter of its word, so the line
    reads correctly once the ink is flattened: "M" plus "any" is "Many". It
    is not always, and when the initial is the whole word the flattened line
    reads "Afew semesters back". The document's own vocabulary decides which
    happened, and says nothing when neither form appears, in which case the
    commoner reading is left alone.
    """
    match = re.match(r"^([A-Z])([A-Za-z'’]*)", text)
    if not match or not match.group(2):
        return text
    initial, rest = match.group(1), match.group(2)
    if (initial + rest).lower() in vocab:
        return text
    if rest.lower() in vocab:
        return initial + " " + text[1:]
    return text


def assemble(lines: list, layout: Layout, vocab: set, compounds: set) -> list:
    """Group classified lines into blocks of Markdown.

    Paragraph boundaries come from the first-line indent, which is the
    only mark the series gives them: there is no blank line between
    paragraphs on the printed page, so joining on vertical gaps alone
    runs the whole chapter together.
    """
    blocks = []
    buffer: list = []
    kind = None
    had_dropcap = False
    dropcap_run = False
    # A Works Cited list is set with a hanging indent, which inverts the rule
    # for where an entry begins: the first line is flush and the turn lines
    # are indented, the opposite of a body paragraph. Reading it with the
    # body rule runs the whole list into one paragraph.
    hanging = False
    prev_indented = False
    in_list = False
    prev_line = None

    def flush():
        nonlocal buffer, kind, had_dropcap
        if not buffer:
            return
        text = join_lines(buffer, vocab, compounds)
        if had_dropcap:
            text = split_dropcap(text, vocab)
            had_dropcap = False
        out_kind = kind or "body"
        # A level deeper than one is only ever stated by the file's own
        # tree, so it rides in the kind rather than in a third field on
        # every block: the pair is what this has always returned and what
        # every test builds. `head` stays `head`, so a file with no tree
        # comes out exactly as it did.
        if out_kind == "head" and buffer[0].heading_level:
            # Emphasis wrapping the whole of a head is how the page sets
            # that level, not something a reader is meant to hear: volume
            # 6 names its fourth level `Header_D_Italics`. `unemphasize`
            # is the same function the captions use, and it takes off
            # wrapping that covers the line and only that.
            text = unemphasize(text)
            if buffer[0].heading_level > 1:
                out_kind = "head%d" % min(buffer[0].heading_level, 6)
        blocks.append((out_kind, text))
        buffer = []
        kind = None

    for line in lines:
        this = classify(line, layout)
        if dropcap_run:
            if line.x0 > layout.body_left + INDENT_MIN:
                # Lines set beside a dropped initial are indented to clear
                # it, which is indistinguishable from a block quotation's
                # inset by position alone. They belong to the paragraph the
                # initial opened, so they are neither a quote nor a new
                # paragraph.
                if this == "quote":
                    this = "body"
            else:
                dropcap_run = False

        if this in ("head", "title"):
            hanging = line.plain.strip().lower().startswith(
                ("works cited", "references", "bibliography")
            )
            in_list = False

        # The series sets its Works Cited smaller than its body, at the same
        # sort of size as a footnote, so size alone reads a bibliography as a
        # page of footnotes and the whole list disappears into the note
        # definitions. Inside that section, small type is the list.
        if hanging and this == "note":
            this = "body"

        if in_list:
            if line.x0 > layout.body_left + INDENT_MIN and not _is_list_start(line, layout):
                # A list item's turn lines are indented past its number,
                # which on position alone is a block quotation's inset.
                this = "list"
            elif line.x0 <= layout.body_left + INDENT_MIN:
                in_list = False

        is_note_start = this == "note" and _NOTE_RE.match(line.text)
        # A caption is set at footnote size, so it reads as a note, and a new
        # note only begins at a number. A caption carries none, so it was
        # being appended to whatever footnote happened to precede it: three of
        # the seven in this chapter ended up inside the notes of the page
        # before. A caption always begins its own block, and its own turn
        # lines, carrying no number either, still join it.
        #
        # A table's caption and a bare label are set the same size and go the
        # same way. Testing only for a figure held until the boxes a table
        # caption sits over were read as tables: with their lines no longer
        # left in the prose, the captions of a table carried over several
        # pages became consecutive lines and joined into one block, so volume
        # 6's chapter 4 printed "Table 4.1. A Mechanism Description" and two
        # continuations of it as a single paragraph with no table under any of
        # them.
        is_caption = (is_figure_caption(line.plain)
                      or is_table_caption(line.plain)
                      or is_bare_label(line.plain))
        if this in ("body", "list") and _is_list_start(line, layout):
            flush()
            kind = "list"
            buffer = [line]
            prev_indented = True
            in_list = True
            prev_line = line
            continue
        indented = line.x0 > layout.body_left + INDENT_MIN
        if hanging:
            starts_para = this == "body" and kind in (None, "body") and \
                not indented and prev_indented
        else:
            starts_para = (
                this == "body"
                and kind in (None, "body")
                and not dropcap_run
                and indented
            )
        prev_indented = indented

        # Two quoted paragraphs share an indent and differ only by the space
        # between them, so without this the whole of a printed dialogue
        # arrives as one block quotation.
        gap_break = (
            layout.line_pitch > 0
            and prev_line is not None
            and prev_line.page == line.page
            and this in ("body", "quote")
            and kind in ("body", "quote")
            and (line.top - prev_line.top) > layout.line_pitch * PARA_GAP_FACTOR
        )
        prev_line = line

        # Two heads in a row merge into one block, which is older than any
        # of this and loses a chapter a heading. Where the file states the
        # levels they are separable, and only there: with nothing stated
        # both sides are None and this is the behaviour it always had.
        level_changed = (
            this == "head" and kind == "head" and buffer
            and (buffer[0].heading_level or 0) != (line.heading_level or 0)
        )
        if kind is not None and (this != kind or starts_para or is_note_start
                                 or is_caption or gap_break or level_changed):
            flush()
        if kind is None:
            kind = this
        buffer.append(line)

        if line.dropcap:
            had_dropcap = True
            dropcap_run = True
    flush()
    return blocks


# A block kind that is a head, with the level it carries. `head` and
# `title` are level one, which is what every head was before a structure
# tree could say otherwise.
_HEAD_KIND_RE = re.compile(r"^head(?P<level>\d*)$")


def head_level(kind: str) -> Optional[int]:
    """The heading level this block kind carries, or None for anything else."""
    if kind == "title":
        return 1
    match = _HEAD_KIND_RE.match(kind or "")
    if not match:
        return None
    return int(match.group("level") or 1)


def blocks_to_markdown(blocks: list, abstract: str = "") -> str:
    """Render blocks as Markdown, with footnotes collected at the end.

    A printed footnote sits at the foot of the page it is referenced from,
    which puts it in the middle of the running prose once the pages are
    flattened. Markdown wants the definition anywhere and the reference in
    place, so the definitions are gathered here and the body closes over
    them, leaving the prose unbroken.

    A numbered note that nothing refers to is not a footnote. Some chapters
    print an endnote section headed "Note" at the end, and `_NOTE_RE` reads
    its numbered item exactly as it reads a footnote at the foot of a page,
    so the text was lifted out from under its own heading and written as a
    Markdown definition. Pandoc drops a definition nothing references, with
    a warning and nothing else, so those notes printed in neither galley:
    four of them across volume 2, among them an acknowledgement crediting
    the student by name who photographed the whiteboard work a chapter is
    built on. One that nothing references is left where the page put it,
    with its marker escaped so Markdown does not read "1." as a list.

    `abstract` is scanned for references too, because it is front matter
    rather than a block and a reference in it does resolve; `12-laflen`
    carries one.
    """
    referenced = set(_FOOTNOTE_KEY_RE.findall(abstract or ""))
    for _, text in blocks:
        referenced.update(_FOOTNOTE_KEY_RE.findall(text))

    # A level stated by the file is the book's, where the chapter title is
    # the top and the galley prints it from the front matter instead. So
    # the shallowest level left in the body becomes one, which keeps the
    # depths the file states and starts them where the body starts.
    # Volume 6 calls its section heads H2 under an H1 chapter title, and
    # without this every one of them renders a level below the title with
    # nothing in between. With nothing stated every head is level one, the
    # shift is zero, and this does not move.
    levels = [head_level(kind) for kind, _ in blocks if head_level(kind)]
    shift = min(levels) - 1 if levels else 0

    out, notes = [], []
    for kind, text in blocks:
        if kind in ("figure", "table"):
            # Already Markdown: an image and the caption that names it, or a
            # pipe table.
            out.append(text)
        elif head_level(kind):
            # "title" is a head the series sets off-centre, such as the
            # "Teacher Resources for ..." page. It is still a head, and it
            # is level one like a plain head; anything deeper came off the
            # file's own structure tree.
            out.append("#" * max(1, head_level(kind) - shift) + " " + text)
        elif kind == "quote":
            out.append("> " + text)
        elif kind == "note" and (is_figure_caption(text) or is_table_caption(text)
                                 or is_bare_label(text)):
            # The series sets a figure caption a point smaller than its body,
            # which is the same thing it does to a footnote, so classify reads
            # one as the other. The difference is where it belongs: a footnote
            # is collected at the end, and a caption has to stay under the
            # figure it names. Left as a note, every caption in the chapter
            # was being moved to the back of it.
            #
            # A table's caption is set the same size and goes the same way.
            # Testing only for a figure left volume 6's fifth chapter printing
            # "Table 5.1", "Table 5.2" and "Table 5.4" in a row at the end of
            # the chapter, each one three pages from the table it names;
            # `place_tables` had put the tables in the right places, and then
            # this moved every caption off them.
            #
            # A label with no description after it goes the same way; see
            # `is_bare_label`.
            out.append(text)
        elif kind == "note":
            match = _NOTE_RE.match(text)
            if match and match.group(1) in referenced:
                notes.append(f"[^{match.group(1)}]: {text[match.end():]}")
            elif match:
                out.append(escape_list_marker(text))
            else:
                notes.append(escape_list_marker(text))
        else:
            out.append(text)
    body = "\n\n".join(out).strip()
    if notes:
        body += "\n\n" + "\n\n".join(notes)
    return body.strip() + "\n"


# ---------- front matter ----------


def extract_front_matter(first_page_lines: list, layout: Layout) -> tuple:
    """Pull the title, chapter number, byline and Overview off page one.

    The opening page is the only one whose layout is not the body layout,
    so it is read separately: the largest type is the title, the chapter
    number hangs at its left, the italic line under it is the byline, and
    everything between the Overview head and the first body head is the
    Overview itself.
    """
    fm: dict = {}
    notes: list = []
    if not first_page_lines:
        return fm, [], set(), ["No text found on the first page."]

    biggest = max(l.size for l in first_page_lines)
    title_lines = [l for l in first_page_lines if l.size >= biggest - 2.5
                   and l.size > layout.body_size + HEAD_SIZE_DELTA]
    if title_lines:
        raw = " ".join(l.plain.strip() for l in title_lines)
        number = re.match(r"^\s*(\d{1,2})\s+(.*)$", raw)
        if number:
            fm["chapter-number"] = int(number.group(1))
            raw = number.group(2)
        fm["title"] = re.sub(r"\s+", " ", raw).strip()
    else:
        notes.append("No title found; the opening page has no oversized type.")

    consumed = {id(l) for l in title_lines}
    byline = next(
        (l for l in first_page_lines
         if id(l) not in consumed and l.italic and l.size > layout.body_size),
        None,
    )
    if byline is not None:
        consumed.add(id(byline))
        names = _split_authors(byline.plain)
        if names:
            fm["author"] = [{"name": n} for n in names]
    else:
        notes.append("No byline found; the italic line under the title is missing.")

    overview: list = []
    seen_head = False
    for line in first_page_lines:
        if id(line) in consumed:
            continue
        kind = classify(line, layout)
        if kind == "head":
            if seen_head:
                break
            if is_overview_head(line.plain):
                seen_head = True
                consumed.add(id(line))
                continue
            break
        if seen_head and kind in ("body", "quote"):
            if overview and starts_paragraph(line, layout):
                # "Everything between the Overview head and the first body
                # head" holds only while the body opens with a head. Volume 5
                # chapter 21 opens its body with a plain paragraph, and the
                # overview ran 96 words into it and split a sentence across
                # the two. The overview is one paragraph, so the next
                # first-line indent ends it whether a head follows or not.
                break
            overview.append(line)
            consumed.add(id(line))

    if not overview:
        # The series opens every chapter with an overview, but it does not
        # always put a head on one: chapter 20 of volume 5 runs its straight
        # on from the byline. Prose above the first head of a chapter whose
        # title and byline have already been taken is that overview.
        for line in first_page_lines:
            if id(line) in consumed:
                continue
            kind = classify(line, layout)
            if kind in ("head", "title"):
                break
            if kind in ("body", "quote"):
                if overview and starts_paragraph(line, layout):
                    break
                overview.append(line)
        if overview:
            consumed.update(id(l) for l in overview)
            notes.append("Overview read from the prose under the byline; the "
                         "opening page carries no head over it.")
    return fm, overview, consumed, notes


# "Overview", and the misspellings of it the archive actually prints: volume
# 5 chapter 21 heads its overview "Overvew". One word only, so that the
# "Overview and Teaching Strategies" head in the teacher material, which is
# not an abstract of anything, does not match.
_OVERVIEW_RE = re.compile(r"^overv\w*$", re.IGNORECASE)


def is_overview_head(text: str) -> bool:
    return bool(_OVERVIEW_RE.match(text.strip().strip(":").strip()))


def starts_paragraph(line: Line, layout: Layout) -> bool:
    """Whether this line opens a paragraph, by its first-line indent.

    The same rule `assemble` reads paragraph boundaries with, which is why it
    can bound the overview: both are reading the one piece of geometry the
    series is consistent about.

    A dropped initial opens a paragraph too, and opens it with no indent at
    all: the capital hangs in the margin at the text block's own left edge,
    so the indent is exactly what it does not have. Volume 5 chapter 21 opens
    its body with one, which is how its overview ran on into the chapter even
    once the indent rule was bounding it.
    """
    return line.dropcap or line.x0 > layout.body_left + INDENT_MIN


# A figure is at least this big along its longer side. Anything smaller is
# a bullet, an icon or an inline mark rather than a figure.
MIN_FIGURE_PX = 80
# And at least this big along its shorter side, which is what separates a
# banner from a rule. Testing both sides against 80 lost volume 6's
# Document Localization Process, a five-stage flowchart 315 by 34, along
# with ten more across the series: a figure set to the full text measure is
# often short, and this archive's measure is about 315pt. A repeated mark
# that clears both floors is caught by the furniture rule instead, which is
# the right division of labour: size rejects a rule, provenance rejects a
# publisher's mark.
MIN_FIGURE_THIN_PX = 24


def big_enough(width: float, height: float,
               min_px: float = MIN_FIGURE_PX) -> bool:
    """Whether an embedded image is large enough to be a figure.

    Measured on each side separately rather than on both against one
    number: a figure set to the full text measure is often short, and
    testing the shorter side against the longer side's floor threw away
    eleven real figures, among them a five-stage flowchart 315 by 34.
    """
    return (max(width, height) >= min_px
            and min(width, height) >= MIN_FIGURE_THIN_PX)
# What a browser will actually display. These PDFs carry JPEG 2000 and TIFF as
# well, which Chrome and Firefox render neither of, so a galley that passed
# them through would show a broken image to most readers: 14 of the 95 figures
# in volumes 5 and 6 are one or the other. Those are re-encoded to PNG.
WEB_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".gif", ".webp"}
# A caption names a figure; a sentence refers to one. The archive punctuates
# captions three ways ("Figure 4.1: An exploded view", "Figure 3.3. Example of
# a Scientific Abstract", "Figure 15.1 Pidgin Translation"), so the colon
# cannot be the test. What separates them is the capital: a caption continues
# with the figure's name, prose continues with a verb, as in "Figure 7.6 shows
# that sales" or "Table 4.1 is an example". Only Figure, never Table: a table
# in this series is set as type, so its caption belongs to no image.
# The archive abbreviates the label three ways and is consistent within a
# volume but not across the series: volume 2 prints "Fig. 1." over all
# seventeen of its captions, volume 6 prints "Fig 1.0", and the rest print
# "Figure 1". Matching only the long form read volume 2 as a book that does
# not caption its figures at all, and sent twenty of its twenty-two to the
# undescribed pile with their descriptions sitting in the text above them.
# The capital is what tells a caption from a reference to one, since the
# series writes "Figure 4.1: ", "Figure 3.3. " and "Figure 15.1 " alike and
# punctuation cannot separate them. An opening quotation mark is as good a
# mark of a caption as a capital, and requiring the capital immediately
# turned down the four captions in this archive that name a quoted title:
# `16-vankooten`'s Figures 1 and 2 both begin with "A College Collage",
# and those two were the figures that looked uncaptioned. The capital is
# still required, just not first. The table pattern below has the same shape
# and no instance of this in the archive, so it is left as it is.
_FIGURE_CAPTION_RE = re.compile(
    r"^(?:Figure|Fig\.?)\s+(?P<number>\d+(?:\.\d+)*)\s*[:.]?\s+"
    r"(?=[“‘\"']?[A-Z])")


def unemphasize(text: str) -> str:
    """A line with any emphasis wrapping the whole of it taken off.

    A caption set in italic on the page arrives as "*Fig. 1. Nicaraguan
    woman on a side street in Granada.*", and a pattern anchored at the
    start never sees the label. That left the photograph with no caption to
    anchor to, so it closed the document and printed after the Works Cited.
    """
    stripped = text.strip()
    while len(stripped) > 2 and stripped[0] in "*_" and stripped[-1] == stripped[0]:
        stripped = stripped[1:-1].strip()
    return stripped


def is_figure_caption(text: str) -> bool:
    return bool(_FIGURE_CAPTION_RE.match(unemphasize(text)))


# A label and nothing else. Both abbreviations of both words, since this is
# the same series that writes "Fig. 1.", "Fig 1.0" and "Figure 1".
_BARE_LABEL_RE = re.compile(
    r"^(?P<word>Figure|Fig\.?|Table|Tab\.)\s+\d+(?:\.\d+)*\s*[:.]?$")


def is_bare_label(text: str) -> bool:
    """Whether a line is a figure or table label with no description after it.

    Volume 1's chapter 6 sets the label for each of its draft figures on a
    line of its own above the box, so there is no description following for
    `is_figure_caption` to recognise it by, and the label is set small like
    every caption in the series, so `classify` reads it as a footnote. Once
    the boxes were read as tables and their own lines stopped being swept up
    with them, that left "Fig 2", "Fig 3", "Fig 5" and "Fig 6" printing in a
    row among the references. The label is what the page sets over the
    figure, so it stays where the page put it.
    """
    return bool(_BARE_LABEL_RE.match(unemphasize(text)))


def is_bare_table_label(text: str) -> bool:
    """A bare label naming a table, which is a place a table can be put.

    `place_tables` pairs the nth table with the nth caption, so only a label
    that names a table may count as one. Volume 1's chapter 6 sets a bare
    "Fig 2" over each of its draft boxes, and those boxes are read as tables;
    letting the label take a table caption's place would push every table
    after it one caption along.
    """
    match = _BARE_LABEL_RE.match(unemphasize(text))
    return bool(match) and match.group("word").lower().startswith("tab")


# A credit the archive sets as a trailing sentence of the caption, rather
# than in brackets: "Photo by Jenae Cohn", "Menu image courtesy of Mistie
# Cohn", "Source: Craig A. Meyer". It has to begin a sentence and it has to
# name itself a credit, which is what keeps the pattern off "chord changes
# for 'Heart of Gold' by Neil Young" and "a news show created by Colin
# Charlton": a bare "by" is far more often part of the description. "from"
# is left out altogether, since a sentence may simply open with it.
_CREDIT_TAIL_RE = re.compile(
    r"(?:(?<=\.)|(?<=”)|^)\s*"
    r"(?:\w+\s+)?"
    r"(?:source|credit|photo(?:graph)?|image|illustration|drawing)"
    r"\s*(?::|\bby\b|\bcourtesy\s+of\b)\s*\S.*$",
    re.IGNORECASE)

# A footnote marker the caption printed, which belongs to the caption and not
# to the description: this series footnotes a figure's source on the caption
# itself. Alt text is read aloud with no way to reach a note, and a marker left
# in it is a second reference to one the caption already carries, which Pandoc
# answers by setting the note twice. Only a footnote reference goes; `[desk]`
# is a description's own bracket and stays.
_FOOTNOTE_REF_RE = re.compile(r"\s*\[\^[^\]\s]+\]")


def caption_alt_text(text: str) -> str:
    """Alt text for a figure, from the caption printed under it.

    The label goes, because "Figure 4.1" describes nothing, and so does a
    trailing source credit. What is left is the caption's own description of
    the figure, which is a real description written by the author and a
    better starting point than anything inferred from the image.

    It is a starting point and not an answer. A caption says what a figure is
    called; alt text says what is in it, and for a figure carrying an argument
    the two are not the same. lint.check_alt_text reports every figure still
    holding its caption so the remaining work is countable.
    """
    text = unemphasize(re.sub(r"\s+", " ", text))
    match = _FIGURE_CAPTION_RE.match(text)
    if match:
        text = text[match.end():]
    text = _FOOTNOTE_REF_RE.sub("", text)
    text = re.sub(r"\s*\((?:Source|Credit|Courtesy)[^)]*\)\s*$", "", text,
                  flags=re.IGNORECASE)
    # The archive more often sets the credit as its own trailing sentence
    # than in brackets: "A cheeseburger in close-up. Photo by Jenae Cohn".
    # Who made a picture is not what is in it, and a screen reader reading
    # alt text has no way to skip past it to the description.
    trimmed = _CREDIT_TAIL_RE.sub("", text).strip()
    # Unless the credit was the whole caption, as it is where the archive
    # prints a source line and no description. An empty alt is not a better
    # answer than a credit: it costs the galley its conformance, and
    # `undescribed_alt` is what the caller uses when there is no caption at
    # all, which is a different thing from a caption that only cites.
    if trimmed:
        text = trimmed
    return text.strip().rstrip(".").strip()


def image_digests(pdf_path: Path, min_px: int = MIN_FIGURE_PX):
    """What images this PDF holds, by content, one count per distinct image.

    For `ingest_volume.py`, which is the only thing that sees a whole volume
    and so the only thing that can tell the series' own mark from a figure.
    """
    import collections
    from pypdf import PdfReader

    counts: collections.Counter = collections.Counter()
    try:
        reader = PdfReader(str(pdf_path))
    except Exception:
        return counts
    for page in reader.pages:
        try:
            images = list(page.images)
        except Exception:
            continue
        for image in images:
            try:
                width, height = image.image.size
            except Exception:
                continue
            if not big_enough(width, height, min_px):
                continue
            counts[_digest(image.data)] += 1
    return counts


def _digest(data: bytes) -> str:
    import hashlib
    return hashlib.sha1(data).hexdigest()


# What PNG can hold. Anything else has to be converted on the way out, and
# a figure in press colour is the usual case: PNG has no CMYK, so a CMYK
# TIFF raises inside PIL and the `except` below drops the figure without a
# word. Volume 6's Document Localization Process went that way and was
# found only because its chapter still referred to a figure it did not have.
PNG_MODES = frozenset({"1", "L", "LA", "I", "I;16", "P", "PA", "RGB", "RGBA"})
ALPHA_MODES = frozenset({"LA", "La", "PA", "RGBA", "RGBa"})


def for_png(image):
    """The same image in a mode PNG can hold.

    Converted to RGB, or to RGBA where the original carries transparency,
    which is the pair of modes a press image can always be reduced to. The
    colours shift slightly, as any CMYK to RGB conversion does; the
    alternative on offer is no figure at all.
    """
    if image.mode in PNG_MODES:
        return image
    # Named rather than tested for an "A" in the mode, because LAB has one
    # and no alpha channel.
    has_alpha = image.mode in ALPHA_MODES or "transparency" in getattr(
        image, "info", {})
    return image.convert("RGBA" if has_alpha else "RGB")


def extract_figures(pdf_path: Path, assets_dir: Path,
                    min_px: int = MIN_FIGURE_PX,
                    skip_digests=frozenset()) -> list:
    """Write each embedded raster out, and say which page it came from.

    pypdf is asked for the rasters rather than pdfplumber because it resolves
    the stream filters and names the format; pdfplumber is what reads the
    captions, further down, since the lines are already being read there.

    Returns one dict per figure: page, path, and the order it sits in on its
    page. Page order plus order within the page is what pairs a figure with
    its caption, and it assumes the content stream lists them down the page,
    which is how these are typeset but not a guarantee.
    """
    from pypdf import PdfReader

    assets_dir.mkdir(parents=True, exist_ok=True)
    out: list = []
    reader = PdfReader(str(pdf_path))
    for page_no, page in enumerate(reader.pages, 1):
        try:
            images = list(page.images)
        except Exception:
            continue
        index = 0
        for image in images:
            try:
                width, height = image.image.size
            except Exception:
                continue
            if not big_enough(width, height, min_px):
                continue
            if _digest(image.data) in skip_digests:
                # The series' own mark, which opens every chapter of the
                # volume. Size cannot tell it from a figure: volume 2's is
                # 113 by 165 and volume 3's is 303 by 454, which is wider
                # than a fifth of the real figures in the series.
                continue
            suffix = Path(image.name or "").suffix.lower() or ".png"
            reencode = suffix not in WEB_IMAGE_SUFFIXES
            if reencode:
                suffix = ".png"
            name = f"figure-p{page_no:03d}-{index + 1}{suffix}"
            path = assets_dir / name
            try:
                if reencode:
                    for_png(image.image).save(str(path), format="PNG")
                else:
                    path.write_bytes(image.data)
            except Exception:
                continue
            out.append({"page": page_no, "index": index, "path": path,
                        "name": name, "size": (width, height)})
            index += 1
    return out


# A figure is set into the text block, so the lines part around it and leave a
# hole many times the leading. Where a page printed no caption, that hole is
# the only record of where in the prose the figure stood, and it is in the
# lines already being read: no raster bbox, and so no need for a second
# library to agree with pypdf about which image on the page is which.
FIGURE_HOLE_FACTOR = 4.0


def _text_holes(page_lines: list, layout: Layout, factor: float) -> list:
    """Every gap in one page's text wide enough to have held a figure.

    One entry per hole, in order down the page: the line above it, or None
    where the hole is at the head of the page and the line above it is the
    last line of the page before.
    """
    holes: list = []
    if (page_lines[0].top - layout.body_top) / layout.line_pitch >= factor:
        holes.append(None)
    for above, below in zip(page_lines, page_lines[1:]):
        if (below.top - above.top) / layout.line_pitch >= factor:
            holes.append(above)
    if (layout.body_bottom - page_lines[-1].top) / layout.line_pitch >= factor:
        holes.append(page_lines[-1])
    return holes


def figure_anchors_from_holes(lines: list, layout: Layout, figures: list,
                              caption_pages: dict, table_pages,
                              factor: float = FIGURE_HOLE_FACTOR) -> dict:
    """The line each uncaptioned figure was printed under, read off its page.

    A hole in the text means nothing by itself. A captioned figure leaves the
    same hole, so does a table, and so does a section that ends partway down
    its page: measured over the fourteen chapters of this archive that strand
    a figure, a hole rule alone catches 22 of the 24 stranded-figure pages and
    59 of the 236 pages that carry no stranded figure. Placing a figure on
    that evidence would be the failure this module least wants, the one that
    is present and wrong, and it would be unreviewable: nothing downstream
    can see that a picture sits in the wrong paragraph.

    So the hole counts only on a page where nothing else could have left it.
    The page carries no caption line, no table, and exactly as many holes as
    it has uncaptioned figures; anything else and the figure keeps the old
    behaviour and the notes go on saying so. That leaves 13 of this archive's
    35 stranded figures placed and 22 untouched, which is the right way round:
    the seven collages of `the-complexity-of-simplicity` are a visual essay
    the chapter says is "embedded in the following pages" and were printing
    after the Works Cited, while volume 6's `15-bennett` sets its figures on a
    design spread whose only lines are the series wordmark, forwards and
    reversed, and has nothing an anchor could honestly be read from.
    """
    if not layout.line_pitch:
        return {}

    uncaptioned: dict = {}
    for figure in figures:
        if caption_pages.get((figure["page"], figure["index"]), ""):
            continue
        uncaptioned.setdefault(figure["page"], []).append(figure)
    if not uncaptioned:
        return {}

    by_page: dict = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)

    anchors: dict = {}
    for page_no, page_figures in uncaptioned.items():
        if page_no in table_pages:
            continue
        page_lines = sorted(by_page.get(page_no, []), key=lambda l: l.top)
        # A full-page plate parts no text, so its page says nothing about
        # where in the prose it belongs.
        if not page_lines:
            continue
        if any(is_figure_caption(line.plain) for line in page_lines):
            continue
        holes = _text_holes(page_lines, layout, factor)
        if len(holes) != len(page_figures):
            continue
        for figure, above in zip(sorted(page_figures,
                                        key=lambda f: f["index"]), holes):
            if above is None:
                earlier = [l for l in lines if l.page < page_no]
                if not earlier:
                    continue
                above = max(earlier, key=lambda l: (l.page, l.top))
            anchors[(figure["page"], figure["index"])] = above.plain
    return anchors


def place_figures(blocks: list, figures: list, caption_pages: dict,
                  figure_anchors: Optional[dict] = None) -> tuple:
    """Put each figure into the blocks, beside the caption that names it.

    A captioned figure joins its caption in one block, as an image and a hard
    line break above the caption text. That shape is deliberate: alone in a
    paragraph the image would become a Pandoc Figure, and the journal's
    figures filter numbers every Figure from 1 in document order, which would
    print "Figure 1." over a caption reading "Figure 7.1" and leave every
    "see Figure 7.3" in the prose pointing at the wrong picture. The printed
    numbering is the one a reconstruction has to keep.

    A figure whose page printed no caption has no caption to be placed beside,
    and `figure_anchors_from_holes` reads the line it was printed under off
    the page where the page allows it. The figure then goes after the block
    holding that line, by the same `_anchor_position` the tables use, with the
    same `floor` keeping several of them in reading order. It still has no
    description, so the notes still ask for one.

    Failing both it follows the last captioned figure before it, or closes the
    document if there is none, and it is counted in the notes rather than
    dropped.
    """
    caption_at = {}
    for position, (kind, text) in enumerate(blocks):
        # "note" as well as "body": the series sets captions a point smaller
        # than the body, so classify reads them as footnotes.
        if kind in ("body", "note", "quote") and is_figure_caption(text):
            caption_at.setdefault(_caption_key(text), position)

    inserts: dict = {}
    notes: list = []
    unplaced = 0
    anchored = 0
    floor = 0
    last_captioned = None
    for figure in figures:
        caption = caption_pages.get((figure["page"], figure["index"]), "")
        position = caption_at.get(_caption_key(caption)) if caption else None
        if position is not None:
            inserts.setdefault(position, []).append((figure, caption))
            last_captioned = position
            floor = max(floor, position)
            continue
        anchor = (figure_anchors or {}).get(
            (figure["page"], figure["index"]))
        at = _anchor_position(blocks, anchor, floor)
        if at is not None:
            # The anchor is the line the page printed above the figure, so
            # the figure goes after the block holding it.
            inserts.setdefault(at + 1, []).append((figure, ""))
            anchored += 1
            floor = max(floor, at + 1)
            continue
        unplaced += 1
        target = last_captioned if last_captioned is not None else len(blocks)
        inserts.setdefault(target, []).append((figure, ""))

    out: list = []
    for position, block in enumerate(blocks):
        pending = inserts.pop(position, [])
        replaced = False
        for figure, caption in pending:
            # The alt text comes off the matched block, not off the line the
            # caption was found on. A caption that wraps is several lines on
            # the page and one block here, and the block is the joined,
            # de-hyphenated text: reading the line instead cut 36 of the 95
            # figures' alt text short, 13 of them mid-word on a hyphen.
            alt = caption_alt_text(block[1]) if caption else \
                undescribed_alt(figure["page"])
            image = f"![{alt}](assets/{figure['name']})"
            if caption:
                out.append(("figure", f"{image}\\\n{block[1]}"))
                replaced = True
            else:
                out.append(("figure", image))
        if not replaced:
            out.append(block)
    for position in sorted(inserts):
        for figure, caption in inserts[position]:
            out.append(("figure",
                        f"![{undescribed_alt(figure['page'])}]"
                        f"(assets/{figure['name']})"))

    if figures:
        notes.append(f"Extracted {len(figures)} figure(s); placed "
                     f"{len(figures) - unplaced - anchored} beside the "
                     f"caption naming it.")
    if anchored:
        notes.append(f"{anchored} figure(s) carry no caption and were placed "
                     f"where their page's text parts to let them in. They "
                     f"have no alt text; describe them by hand.")
    if unplaced:
        notes.append(f"{unplaced} figure(s) carry no caption, so they have no "
                     f"alt text and sit after the figure before them; place "
                     f"and describe them by hand.")
    return out, notes


# Tables are found by their rules and never by the alignment of their text.
# This archive rules its tables, and asking pdfplumber to infer them from
# whitespace instead reads a page of ordinary prose as a 48-row table: the
# "text" strategy turned chapter 11's page 3, which holds no table at all,
# into 27 rows of shredded sentences. Missing an unruled table is the better
# failure, because a table that was never found leaves the prose alone.
TABLE_SETTINGS = {"vertical_strategy": "lines", "horizontal_strategy": "lines"}
# Below this it is a rule under a heading or a box around a pull quote, not a
# table. Two columns and two rows is the smallest thing that is one, except
# where a single row's cells wrap: see `_cells_wrap`, which is the shape that
# interleaves and the one case the row floor lets through.
MIN_TABLE_ROWS = 2
MIN_TABLE_COLS = 2
# How far apart two rules may sit and still be read as meeting.
RULE_TOL = 2.0
_TABLE_CAPTION_RE = re.compile(
    r"^(?:Table|Tab\.)\s+(?P<number>\d+(?:\.\d+)*)\s*[:.]?\s+(?=[A-Z])")


def is_table_caption(text: str) -> bool:
    return bool(_TABLE_CAPTION_RE.match(unemphasize(text)))


def _cells_wrap(rows: list) -> bool:
    """Whether any cell holds text that was wrapped across lines.

    This is what separates a one-row box that will interleave from one that
    cannot, and it is the only reason the row floor has an exception. A cell
    of wrapped prose contributes a line to every band of the page it crosses,
    so reading the box across its columns shreds it; a row whose cells are
    each a single line reads across to exactly what the page printed, so
    there is nothing to repair and no reason to call it a table. Volume 6's
    chapter 15 rules a form for ticking seven aesthetic modes, whose only
    legible row is the one naming them: admitting it would have published a
    seven-column table with a head and no body.

    `table.extract()` keeps the wrap as a newline, which is why this is asked
    before `_clean_table` joins the lines back up.
    """
    return any("\n" in (cell or "") for row in rows for cell in row)


def infer_column_rules(page, tol: float = RULE_TOL) -> list:
    """The column rules a box drew only as the breaks in its horizontal ones.

    Word gives every cell its own border, so a table set that way rules its
    top and its bottom once per column, in segments that abut at the column
    boundary, and draws no vertical rule there at all. That leaves
    pdfplumber's "lines" strategy with only the two outer verticals to go on:
    it reads the box as a single column, finds no table worth the name, and
    the cells interleave into the prose. Volume 6's chapter 4 sets both of
    its tables that way and ran 1,400 words of commentary through the sample
    documents it was commenting on, breaking words in half as it went.

    So the column boundary is in the rules after all, and reading it off them
    keeps the discipline that finds tables by their ruling rather than by the
    alignment of their text. It is only believed where three things hold,
    because a break in a horizontal rule is common and on its own means
    nothing: a strikethrough abuts the next strikethrough, and a contents
    page's dot leaders abut all the way across, which is 200 spurious columns
    on one page of volume 5's front matter.

    The segments at that height have to run from one of the box's own
    vertical rules to the other, so that what is being read is a frame and
    not a decoration. The same break has to fall at two of those heights, as
    a column boundary does when the box rules both its top and its bottom.
    And the box must carry no vertical rule inside it: a box that rules its
    own columns has already said where they are, and pdfplumber's reading of
    it is the one to keep. Without that last test the inference reaches
    tables that are already found and splits their columns further, which is
    how five chapters that were right gained a narrow empty column.

    Returned as line objects carrying the frame's own top and bottom, so a
    rule inferred for one box cannot divide another box on the same page.
    """
    verticals = []
    rules: dict = {}
    for edge in page.edges:
        if edge.get("orientation") == "v":
            verticals.append(edge)
        else:
            rules.setdefault(round(edge["top"], 0), []).append(
                (edge["x0"], edge["x1"]))
    if not verticals:
        return []

    # Group the rules that span the same pair of verticals: one frame.
    frames: dict = {}
    for height, segments in rules.items():
        if len(segments) < 2:
            continue
        segments.sort()
        left = segments[0][0]
        right = max(end for _, end in segments)
        if not any(abs(edge["x0"] - left) <= tol for edge in verticals):
            continue
        if not any(abs(edge["x0"] - right) <= tol for edge in verticals):
            continue
        breaks = {round((end + start) / 2, 1)
                  for (_, end), (start, _) in zip(segments, segments[1:])
                  if abs(start - end) <= tol and left + tol < end < right - tol}
        if breaks:
            frames.setdefault((round(left, 1), round(right, 1)), []).append(
                (height, breaks))

    inferred = []
    for (left, right), found in frames.items():
        if len(found) < 2:
            continue
        heights = [height for height, _ in found]
        top, bottom = min(heights), max(heights)
        if any(left + tol < edge["x0"] < right - tol
               and edge["bottom"] > top + tol and edge["top"] < bottom - tol
               for edge in verticals):
            continue
        for x in sorted(set.intersection(*(breaks for _, breaks in found))):
            inferred.append({
                "object_type": "line",
                "x0": x, "x1": x, "top": top, "bottom": bottom,
                "width": 0.0, "height": bottom - top,
                "doctop": top, "orientation": "v",
            })
    return inferred


def find_page_tables(page) -> list:
    """The ruled tables on one page, as (bbox, rows), largest first.

    pdfplumber reports a table and then the cells inside it as further
    tables, so anything sitting inside another's box is dropped: chapter 11's
    page 11 came back as four tables of which three were pieces of the first.

    The column rules a box left implicit are supplied first, since a box
    whose columns are not ruled is not found at all; see
    `infer_column_rules`.
    """
    settings = dict(TABLE_SETTINGS)
    inferred = infer_column_rules(page)
    if inferred:
        settings["explicit_vertical_lines"] = inferred
    try:
        found = page.find_tables(table_settings=settings)
    except Exception:
        return []
    candidates = []
    for table in found:
        try:
            extracted = table.extract()
            rows = _clean_table(extracted,
                                _symbol_translations(page, table.bbox))
        except Exception:
            continue
        if max((len(r) for r in rows), default=0) < MIN_TABLE_COLS:
            continue
        if len(rows) < MIN_TABLE_ROWS and not _cells_wrap(extracted):
            continue
        candidates.append((tuple(table.bbox), rows))

    candidates.sort(key=lambda pair: -_area(pair[0]))
    kept: list = []
    for bbox, rows in candidates:
        if any(_inside(bbox, other) for other, _ in kept):
            continue
        kept.append((bbox, rows))
    # Back into reading order, which is what pairs a table with its caption.
    kept.sort(key=lambda pair: pair[0][1])
    return kept


def _area(bbox) -> float:
    return abs(bbox[2] - bbox[0]) * abs(bbox[3] - bbox[1])


def _inside(inner, outer, tol: float = 2.0) -> bool:
    return (inner[0] >= outer[0] - tol and inner[1] >= outer[1] - tol
            and inner[2] <= outer[2] + tol and inner[3] <= outer[3] + tol)


def _symbol_translations(page, bbox) -> dict:
    """What the symbol-font characters inside one table actually say.

    `table.extract()` hands back strings with the font stripped off, so the
    substitution `_line_text` makes character by character has to be rebuilt
    here from the page. A check mark in a comparison table is the whole
    content of its cell, so leaving it as Wingdings loses the column.

    A code set in a symbol font in part of the table and as ordinary text in
    another part is left alone: the extracted string carries no positions, so
    there is no way to tell those two apart, and changing both would corrupt
    the text to fix the glyph.
    """
    symbol: dict = {}
    literal: set = set()
    try:
        chars = page.crop(bbox).chars
    except Exception:
        return {}
    for ch in chars:
        text = ch.get("text") or ""
        if len(text) != 1:
            continue
        if symbol_family(ch.get("fontname") or "") is None:
            literal.add(text)
        else:
            symbol.setdefault(text, set()).add(
                translate_symbol_char(ch.get("fontname") or "", text))
    return {text: next(iter(seen)) for text, seen in symbol.items()
            if len(seen) == 1 and text not in literal
            and next(iter(seen)) != text}


def _clean_table(rows: list, trans: Optional[dict] = None) -> list:
    """Tidy extracted cells: rejoin broken words, drop empty rows and columns.

    A cell's text is wrapped as it was printed, so it arrives with the line
    breaks and the hyphens in it; "introduc- tion" has to come back together
    or the table reads as badly as the prose it replaces. Columns that are
    entirely empty come from rules pdfplumber counted as boundaries.

    Except in a table of one row, where an empty column is the ordinary
    thing rather than a phantom. A two-column box carried over onto another
    page often has nothing beside the sample there, and dropping the column
    takes the box under the column floor, which puts its text straight back
    into the prose it was about to shred: two of the five pages volume 6's
    chapter 4 runs its process description over carry no commentary, and
    both came through as prose with a caption welded to the front of them.
    """
    table = [[_clean_cell(cell, trans) for cell in row] for row in rows if row]
    table = [row for row in table if any(cell for cell in row)]
    if not table:
        return []
    width = max(len(row) for row in table)
    table = [row + [""] * (width - len(row)) for row in table]
    if len(table) == 1:
        return table
    keep = [i for i in range(width) if any(row[i] for row in table)]
    return [[row[i] for i in keep] for row in table]


def _clean_cell(cell, trans: Optional[dict] = None) -> str:
    text = str(cell or "")
    if trans:
        text = text.translate(str.maketrans(trans))
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = re.sub(r"\s*\n\s*", " ", text)
    # A pipe inside a cell would close the column it sits in.
    return re.sub(r"\s+", " ", text).replace("|", r"\|").strip()


def table_to_markdown(rows: list) -> str:
    """A pipe table, whose first row is the header.

    The header matters more than the shape: it is what lets a screen reader
    say which column a cell is in, and a table read as prose has no columns
    to name. Where the first row is empty in its first cell, as a comparison
    table's corner is, the cell is left empty rather than invented.

    A table of one row has no header to promote, and promoting its only row
    anyway would put the whole of a cell into a column name: the boxes that
    arrive this way set a document beside the commentary on it, so the head
    would have carried 300 words of someone's draft. The row stays the body
    and the head is left empty, which Pandoc reads as the headerless table
    it is.
    """
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    body = [row + [""] * (width - len(row)) for row in rows]
    head = body[0] if len(body) > 1 else [""] * width
    rest = body[1:] if len(body) > 1 else body
    out = ["| " + " | ".join(head) + " |",
           "|" + "|".join([" --- "] * width) + "|"]
    for row in rest:
        out.append("| " + " | ".join(row) + " |")
    return "\n".join(out)


def undescribed_alt(page: int) -> str:
    """Alt text for a figure the page gave no caption to describe it with.

    Not left empty, and not left out. Empty alt text costs the galley its
    PDF/UA conformance, since Typst refuses an undescribed image and the
    compile falls back; leaving the figure out costs the reader the figure.
    This says what is true, reads as what it is to anyone who hears it, and
    is phrased so `lint.check_alt_text` can count how many are still waiting
    on a description.
    """
    return f"Undescribed figure from page {page} of the source"


def drop_lines_inside_tables(lines: list, tables_by_page: dict) -> tuple:
    """Take out the lines a table's cells are made of.

    This is the half that matters. Reading a two-column table across its
    columns interleaves the cells into prose: chapter 11 of volume 5 came
    through with "detailing as being the most import- lab procedures ant
    while", which is one word cut in half with a cell from the next column
    inside it. Adding a table without removing those lines would leave the
    galley holding both.

    A caption is never dropped, even where it falls inside the box, because
    it is what the table is placed against.

    The line left standing immediately above each table is kept as that
    table's anchor, which is the only record of where in the prose the
    table stood. A table the series did not caption has nothing else to be
    placed against, and the end of the document is a poor guess: chapter 2
    of volume 1 introduces its table with "Let's break down the writing
    situation in college:" on page 6 and had it printing after the Works
    Cited on page 14.
    """
    inside = []
    out = []
    anchors: dict = {}
    for line in lines:
        boxes = tables_by_page.get(line.page) or []
        if boxes and not (is_table_caption(line.plain)
                          or is_figure_caption(line.plain)):
            centre = line.top
            hit = next((index for index, (bbox, _) in enumerate(boxes)
                        if bbox[1] - 2 <= centre <= bbox[3] + 2), None)
            if hit is not None:
                anchors.setdefault((line.page, hit),
                                   out[-1].plain if out else "")
                inside.append(line)
                continue
        out.append(line)
    return out, len(inside), anchors


def _normalize_block(text: str) -> str:
    return re.sub(r"\s+", " ", unemphasize(text)).strip().lower()


def _anchor_position(blocks: list, anchor: Optional[str],
                     floor: int = 0) -> Optional[int]:
    """The block holding the line the table's page printed above it.

    The whole anchor is tried first, because the line above a table is often
    a head, and a head is a block whose text is exactly that line. Only then
    its last few words, for a line that has been through `join_lines` by now
    and sits in the middle of a paragraph. A word broken across the line
    break defeats both, and the table then falls back to the end with the
    note saying so.

    The order matters, and matching on the tail alone put volume 1 chapter
    6's zero draft after the Conclusion. The line above that table is the
    "Zero Draft" head, so the tail is the whole of two words, and five
    blocks in the chapter contain them: the head, the paragraphs either side
    of it, and one in the Discussion explaining what a zero draft is for.
    Matched whole, the head is the only block that is those two words.

    Between the two sits a block that merely begins with the anchor, which
    is what a head reads as once something has been joined to it. Volume 5's
    chapter 22 prints "Rhetorical Reading Rubric" over its rubric and
    "Activities to Incorporate 'Writing to Learn'" under it, and with the
    table's own lines gone the two heads are consecutive and `assemble`
    joins them, so no block is the anchor and the merged head is the nearest
    thing to it. Without this tier the table fell back to the tail, which
    matches the paragraph a page earlier that mentions the rubric by name.

    `floor` is the position the table before this one took. Tables arrive in
    page order and their anchors are lines in reading order, so a position
    behind the floor is a mis-match rather than a table that moved
    backwards; among several candidates the first at or after the floor is
    the one in reading order. It is a tie-break and not a rule: where
    nothing matches at or after the floor the last match is still taken,
    since a mis-ordered table is better than one at the end of the chapter,
    and `place_tables` counts those and says so.
    """
    if not anchor:
        return None
    whole = _normalize_block(anchor)
    if not whole:
        return None
    key = " ".join(whole.split()[-6:])

    for matches in (lambda text: text == whole,
                    lambda text: text.startswith(whole),
                    lambda text: key in text):
        found = [position for position, (kind, text) in enumerate(blocks)
                 if kind in ("body", "quote", "note", "head", "title")
                 and matches(_normalize_block(text))]
        if found:
            ahead = [position for position in found if position >= floor]
            return ahead[0] if ahead else found[-1]
    return None


def continues_previous(table: dict, previous: Optional[dict]) -> bool:
    """Whether a table carries on the one before it across a page break.

    A table too long for its page is set again at the top of the next one
    with its header row repeated and no caption of its own, because the
    caption was printed over the first part. It has nothing to be paired
    with, so counting it against the next caption in the chapter shifts
    every table after it one caption along: that is how the second half of
    volume 6 chapter 15's Table 15.2 came to stand under the label of the
    teacher activity's Table 1, with the activity's own tables one label out
    behind it.

    Three things have to hold together, and the third is what does the work.
    Volume 6 chapter 5 sets Tables 5.2 and 5.3 on facing pages under the
    same four column names, so a repeated header on the next page is not
    enough on its own; what separates them is that 5.3's page prints its
    caption above it and a continuation's page prints none. `captioned` is
    set where a table caption or a bare table label stands higher up the
    same page. Across the series seven tables continue this way and that one
    pair is the only thing the test has to turn down.
    """
    if previous is None or table.get("captioned"):
        return False
    if table["page"] != previous["page"] + 1:
        return False
    return (bool(table["rows"]) and bool(previous["rows"])
            and table["rows"][0] == previous["rows"][0])


def place_tables(blocks: list, tables: list, anchors: Optional[dict] = None) -> tuple:
    """Put each table after the caption that names it.

    The series prints the caption above the table, so that is where it goes.
    A pipe table has to begin a line, so it is its own block rather than
    joined to the caption the way a figure is to its own.

    Paired in reading order rather than by page, which is where this differs
    from the figures. A figure and its caption are on one page by definition,
    since the caption is set under the picture. A table's caption is set above
    it and the two part company across a page break: both of chapter 11's did,
    and pairing them by page matched neither. Tables come in page order and
    captions in document order, so the nth of one is the nth of the other,
    once the parts that continue another table are left out of the count.

    A bare "Table 1" counts as a caption here. It is all volume 3's
    `vieregge` prints over its only table, and it is set small like every
    caption in the series, so without this the table fell to its anchor and
    came to rest two paragraphs and a block quote below the label naming it.
    """
    caption_positions = [
        position for position, (kind, text) in enumerate(blocks)
        if kind in ("body", "note", "quote")
        and (is_table_caption(text) or is_bare_table_label(text))
    ]

    anchors = anchors or {}
    inserts: dict = {}
    unplaced = anchored = continued = backwards = 0
    captions_used = 0
    previous = None
    floor = 0
    for table in tables:
        carries_on = continues_previous(table, previous)
        previous = table
        if not carries_on and captions_used < len(caption_positions):
            position = caption_positions[captions_used]
            captions_used += 1
        else:
            # No caption of its own, so fall back to the line the page
            # printed above the table rather than to the end of the chapter.
            # For a continuation that line is the last one of the page it
            # carries on from, which puts it against the part it continues.
            position = _anchor_position(
                blocks, anchors.get((table["page"], table["index"])), floor)
            if position is None:
                unplaced += 1
                position = len(blocks) - 1
            else:
                if position < floor:
                    backwards += 1
                floor = max(floor, position)
                if carries_on:
                    continued += 1
                else:
                    anchored += 1
        inserts.setdefault(position, []).append(table)

    out: list = []
    for position, block in enumerate(blocks):
        out.append(block)
        for table in inserts.pop(position, []):
            out.append(("table", table_to_markdown(table["rows"])))
    for position in sorted(inserts):
        for table in inserts[position]:
            out.append(("table", table_to_markdown(table["rows"])))

    notes = []
    if tables:
        notes.append(f"Read {len(tables)} ruled table(s) as tables; "
                     f"placed {captions_used} against a caption.")
    if continued:
        notes.append(f"{continued} table(s) carry on the table before them "
                     f"across a page break, so they take no caption of "
                     f"their own.")
    if anchored:
        notes.append(f"{anchored} table(s) the series did not caption, put "
                     f"back against the line printed above them.")
    if backwards:
        notes.append(f"{backwards} table(s) anchored behind the table before "
                     f"them, so the line matched is not the one printed "
                     f"above them; check where they belong.")
    if unplaced:
        notes.append(f"{unplaced} table(s) matched no caption and follow the "
                     f"text instead; check where they belong.")
    return out, notes


def _caption_key(text: str) -> str:
    """A caption's first few words, which is enough to find it again.

    The emphasis has to come off here too. The key is matched between the
    caption as the page prints it and the caption as the block holds it,
    and only the block has been through `_line_text`, so an italic caption
    arrives with an asterisk on the front and the two keys differ by that
    one character. Recognising the caption was not enough to place the
    figure; the pairing is what the key does.

    Emphasis inside the caption comes off as well, and this is the only
    place it does. `unemphasize` takes off what wraps the whole line and no
    more, because emphasis within a caption is the caption's own and belongs
    in the text that prints. A key is a different thing: it is matched
    against the caption as `extract_text` reads it off the page, which
    carries no font information and so no markers at all, so one marker
    anywhere inside the first eight words makes the two keys differ and the
    figure has nothing to anchor to. Volume 1's wikipedia-is-good-for-you
    sets in italic the article titles its captions name, and "*Web 2.0*" and
    "*Writing*" fall inside the key for Figures 1 and 2: both pictures were
    left uncaptioned at the end of the chapter while Figures 3 to 6 paired,
    whose italics sit past the eighth word.
    """
    plain = re.sub(r"[*_]", "", unemphasize(text))
    return " ".join(
        re.sub(r"\s+", " ", plain).strip().split()[:8]).lower()


# The standalone chapter download opens on a page the bound volume does not
# have: the series boilerplate, the publisher's copyright page, and the
# licence, printed above the chapter so a reader who found the chapter alone
# can tell what it came from. None of it is the chapter. Volumes 1 to 3 set
# one; 4 to 6 do not. Three groups of marker rather than one phrase, and two
# groups have to be present, because a chapter may well discuss a Creative
# Commons licence and none of them prints a CIP block to discuss.
_COVER_MARKERS = (
    ("boilerplate", ("is a chapter in", "available for free from the following",
                     "print versions of the volume",
                     "to learn about participating in")),
    ("copyright", ("cataloging-in-publication", "includes bibliographical references",
                   "library of congress", "p. cm.")),
    ("licence", ("this work is licensed under",
                 "creative commons license subject to")),
)


def is_cover_page(lines: list) -> bool:
    """Is this the offprint cover rather than a page of the chapter?"""
    text = re.sub(r"\s+", " ", " ".join(l.plain for l in lines)).lower()
    groups = sum(1 for _, markers in _COVER_MARKERS
                 if any(marker in text for marker in markers))
    return groups >= 2


def count_cover_pages(lines: list, limit: int = 2) -> int:
    """How many leading pages are cover rather than chapter.

    Only the first page or two are considered. A chapter that quotes the
    series' own terms of use in its tenth page is discussing them, and a
    cover page that is not at the front is not a cover page.
    """
    by_page: dict = {}
    for line in lines:
        by_page.setdefault(line.page, []).append(line)
    count = 0
    for page_no in sorted(by_page)[:limit]:
        if not is_cover_page(by_page[page_no]):
            break
        count = page_no
    return count


def opening_page_body(body_lines: list, layout: Layout,
                      has_overview: bool) -> list:
    """Which of the opening page's leftover lines belong to the body.

    A chapter's opening page is title furniture above an Overview, so once the
    Overview has been found the leftovers below it are body and all of them
    are kept.

    Without one, the page is cut at its first head: on a chapter whose
    Overview was missed, everything above that head is title furniture that
    was not recognised, and letting it through puts the byline into the body
    as a heading.

    With no head either, the page is kept whole. That is not a chapter
    opening at all; front and back matter prints its title and runs straight
    into prose, and the title has already been consumed, so there is nothing
    left to cut to. Discarding the page then loses a certain page of text to
    be rid of an uncertain line of it. Reading the whole of Writing Spaces 5
    is what turned this up: the acknowledgments came through missing 40% of
    its words and the contributors list missing everyone from Blakesley to
    Duffy, in both cases exactly page one, while every chapter was unharmed
    because every chapter has an Overview.
    """
    if has_overview:
        return body_lines
    first_head = next((i for i, l in enumerate(body_lines)
                       if classify(l, layout) in ("head", "title")), None)
    if first_head is None:
        return body_lines
    return body_lines[first_head:]


def _split_authors(byline: str) -> list:
    """Split a printed byline into names.

    The series prints "A, B, C, and D", so the serial comma and the "and"
    both have to go, and a two-name byline has no comma at all.
    """
    text = re.sub(r"\s+", " ", byline).strip().strip(".")
    text = re.sub(r",?\s+and\s+", ", ", text)
    return [p.strip() for p in text.split(",") if p.strip()]


# ---------- entry point ----------


def _take_stated_headings(pdf_path: Path, lines: list,
                          chars_seen: int, chars_marked: int) -> list:
    """Use the file's own headings where its tree reaches the text.

    Gated on coverage rather than on a tree existing, because every one of
    this series' 118 originals carries a tree and 17 of them tag the
    publisher's cover page and nothing else. Reading those would hand a
    chapter the structure of its boilerplate.

    Each ending says which of the four happened, because "the headings are
    inferred" covers a file with no tree and a file whose tree was read and
    found wanting, and those are different things to be told.
    """
    import structure

    try:
        outline = structure.read(pdf_path, text=False,
                                 chars=(chars_seen, chars_marked))
    except Exception as exc:
        return [f"The structure tree could not be read "
                f"({type(exc).__name__}); the headings are inferred from "
                f"type size and centring."]

    if not outline.tagged:
        return ["No structure tree, so the headings are inferred from type "
                "size and centring."]

    reach = outline.coverage
    if not outline.usable:
        return [f"The structure tree reaches {reach:.0f}% of the text, which "
                f"is a cover page or a fragment rather than the chapter, so "
                f"the headings are inferred from type size and centring."]

    heads = outline.heading_map()
    if not heads:
        return [f"The structure tree reaches {reach:.0f}% of the text and "
                f"names no heading, so the headings are inferred from type "
                f"size and centring."]

    marked = apply_stated_headings(lines, heads)
    return [f"Took {marked} heading(s) from the structure tree, which "
            f"reaches {reach:.0f}% of the text, rather than inferring them "
            f"from type size and centring."]


def extract(pdf_path: Path, genre_heads: Optional[tuple] = None,
            assets_dir: Optional[Path] = None,
            skip_image_digests=frozenset(),
            read_structure: bool = True) -> IngestResult:
    """Read a PDF chapter into front matter plus Markdown body.

    With `assets_dir`, the figures are written there and placed in the body.
    Without it the text comes through alone, which is what it did before
    figures were extracted at all, and what the tests rely on.

    `read_structure` takes the headings from the file's own structure tree
    where the tree reaches the text, instead of inferring them from type
    size and centring. It is on because the inference loses a third of
    them, and it can be turned off to read a file the way this module read
    every file before: that is what the comparison was run with.
    """
    import pdfplumber

    genre_heads = genre_heads or GENRE_HEADS
    notes: list = []
    all_lines: list = []
    page_width = 0.0
    tables_by_page: dict = {}
    table_anchors: dict = {}
    clipped_ink = 0
    chars_seen = chars_marked = 0
    with pdfplumber.open(str(pdf_path)) as pdf:
        if not pdf.pages:
            raise ValueError(f"{pdf_path.name} has no pages.")
        page_width = float(pdf.pages[0].width)
        for page_no, page in enumerate(pdf.pages, 1):
            page, clipped = drop_clipped_ink(page)
            clipped_ink += clipped
            # Counted here because the chars are already in hand, and
            # `structure.read` would otherwise walk the whole file again to
            # work out how far the tree reaches.
            try:
                for char in page.chars:
                    chars_seen += 1
                    if char.get("mcid") is not None:
                        chars_marked += 1
            except Exception:
                pass
            all_lines.extend(_page_lines(page, page_no))
            found = find_page_tables(page)
            if found:
                tables_by_page[page_no] = found

    if not all_lines:
        raise ValueError(
            f"No extractable text in {pdf_path.name}. A scanned PDF needs OCR "
            "before it can be ingested; see ocr.py."
        )

    if clipped_ink:
        notes.append(f"Dropped {clipped_ink} character(s) the page draws and "
                     f"then clips away, so they are never printed.")

    # Before the layout is learned, so the cover's own type cannot vote on
    # what the body size is, and before the vocabulary, so "Cataloging-in-
    # Publication" is never a word this chapter knows.
    cover = count_cover_pages(all_lines)
    if cover:
        all_lines = [l for l in all_lines if l.page > cover]
        tables_by_page = {p: t for p, t in tables_by_page.items() if p > cover}
        notes.append(f"Dropped {cover} offprint cover page(s) printed above "
                     f"the chapter; the chapter opens on page {cover + 1}.")
        if not all_lines:
            raise ValueError(f"{pdf_path.name} is a cover page and nothing else.")

    layout = learn_layout(all_lines, page_width)
    kept, dropped = strip_furniture(all_lines, layout)
    notes.append(f"Dropped {len(dropped)} line(s) of page furniture.")

    # After the furniture is gone, because a file can call its running
    # heads a heading level and mean it: volume 2's chapters map
    # `Running_Headers` to H5, so the author's name and the folio are
    # stated headings. The furniture rule still decides what is furniture.
    if read_structure:
        notes.extend(_take_stated_headings(pdf_path, kept,
                                           chars_seen, chars_marked))

    # Before the vocabulary is built, so that cells shredded across columns
    # do not teach it their fragments as words.
    if tables_by_page:
        kept, in_tables, table_anchors = drop_lines_inside_tables(
            kept, tables_by_page)
        notes.append(f"Took {in_tables} line(s) out of the prose that belong "
                     f"to a table, and read the table instead.")

    vocab, compounds = build_vocabulary(kept)

    opening = cover + 1
    first_page = [l for l in kept if l.page == opening]
    rest = [l for l in kept if l.page > opening]
    fm, overview_lines, consumed, fm_notes = extract_front_matter(first_page, layout)
    notes.extend(fm_notes)

    if overview_lines:
        fm["abstract"] = join_lines(overview_lines, vocab, compounds)
    else:
        notes.append("No Overview found on the opening page.")

    body_lines = opening_page_body(
        [l for l in first_page if id(l) not in consumed],
        layout, bool(overview_lines),
    )
    body_lines.extend(rest)

    blocks = assemble(body_lines, layout, vocab, compounds)

    if tables_by_page:
        tables = []
        for page_no in sorted(tables_by_page):
            # Whether the page names a table higher up than this one is what
            # tells a continuation from a second table under the same column
            # names; `continues_previous` explains why that is the test.
            labelled = [line.top for line in all_lines
                        if line.page == page_no
                        and (is_table_caption(line.plain)
                             or is_bare_table_label(line.plain))]
            for index, (bbox, rows) in enumerate(tables_by_page[page_no]):
                tables.append({"page": page_no, "index": index, "rows": rows,
                               "captioned": any(top < bbox[1]
                                                for top in labelled)})
        blocks, table_notes = place_tables(blocks, tables, table_anchors)
        notes.extend(table_notes)

    if assets_dir is not None:
        figures = extract_figures(Path(pdf_path), Path(assets_dir),
                                  skip_digests=skip_image_digests)
        # A caption is paired with a figure by page and by order down the
        # page, which is all the geometry needed when a page carries two.
        by_page: dict = {}
        for line in all_lines:
            if is_figure_caption(line.plain):
                by_page.setdefault(line.page, []).append(line)
        caption_pages = {}
        for page_no, lines in by_page.items():
            lines.sort(key=lambda l: l.top)
        for figure in figures:
            lines = by_page.get(figure["page"], [])
            if figure["index"] < len(lines):
                caption_pages[(figure["page"], figure["index"])] = \
                    lines[figure["index"]].plain
        figure_anchors = figure_anchors_from_holes(
            kept, layout, figures, caption_pages, set(tables_by_page))
        blocks, figure_notes = place_figures(blocks, figures, caption_pages,
                                             figure_anchors)
        notes.extend(figure_notes)

    body = blocks_to_markdown(blocks, fm.get("abstract", ""))

    hyphens = sum(1 for l in kept if l.text.endswith("-"))
    notes.append(f"Rejoined {hyphens} word(s) broken across a line.")
    notes.append(
        f"Learned layout: {layout.body_size}pt body, text block "
        f"{layout.body_left} to {layout.body_right}pt."
    )
    return IngestResult(front_matter=fm, body=body, notes=notes)
