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
    """What kind of line this is, by size and position."""
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


_LIST_RE = re.compile(r"^(\d{1,2})[.)]\s+")
_NOTE_RE = re.compile(r"^(\d{1,3})[.)]\s+")


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
        blocks.append((kind or "body", text))
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
        is_caption = is_figure_caption(line.plain)
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

        if kind is not None and (this != kind or starts_para or is_note_start
                                 or is_caption or gap_break):
            flush()
        if kind is None:
            kind = this
        buffer.append(line)

        if line.dropcap:
            had_dropcap = True
            dropcap_run = True
    flush()
    return blocks


def blocks_to_markdown(blocks: list) -> str:
    """Render blocks as Markdown, with footnotes collected at the end.

    A printed footnote sits at the foot of the page it is referenced from,
    which puts it in the middle of the running prose once the pages are
    flattened. Markdown wants the definition anywhere and the reference in
    place, so the definitions are gathered here and the body closes over
    them, leaving the prose unbroken.
    """
    out, notes = [], []
    for kind, text in blocks:
        if kind in ("figure", "table"):
            # Already Markdown: an image and the caption that names it, or a
            # pipe table.
            out.append(text)
        elif kind in ("head", "title"):
            # "title" is a head the series sets off-centre, such as the
            # "Teacher Resources for ..." page. It is still a head.
            out.append("# " + text)
        elif kind == "quote":
            out.append("> " + text)
        elif kind == "note" and is_figure_caption(text):
            # The series sets a figure caption a point smaller than its body,
            # which is the same thing it does to a footnote, so classify reads
            # one as the other. The difference is where it belongs: a footnote
            # is collected at the end, and a caption has to stay under the
            # figure it names. Left as a note, every caption in the chapter
            # was being moved to the back of it.
            out.append(text)
        elif kind == "note":
            match = _NOTE_RE.match(text)
            if match:
                notes.append(f"[^{match.group(1)}]: {text[match.end():]}")
            else:
                notes.append(text)
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


# A figure smaller than this in either direction is a rule, a bullet or a
# publisher's mark rather than a figure.
MIN_FIGURE_PX = 80
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
_FIGURE_CAPTION_RE = re.compile(
    r"^Figure\s+(?P<number>\d+(?:\.\d+)*)\s*[:.]?\s+(?=[A-Z])")


def is_figure_caption(text: str) -> bool:
    return bool(_FIGURE_CAPTION_RE.match(text.strip()))


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
    text = re.sub(r"\s+", " ", text).strip()
    match = _FIGURE_CAPTION_RE.match(text)
    if match:
        text = text[match.end():]
    text = re.sub(r"\s*\((?:Source|Credit|Courtesy)[^)]*\)\s*$", "", text,
                  flags=re.IGNORECASE)
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
            if width < min_px or height < min_px:
                continue
            counts[_digest(image.data)] += 1
    return counts


def _digest(data: bytes) -> str:
    import hashlib
    return hashlib.sha1(data).hexdigest()


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
            if width < min_px or height < min_px:
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
                    image.image.save(str(path), format="PNG")
                else:
                    path.write_bytes(image.data)
            except Exception:
                continue
            out.append({"page": page_no, "index": index, "path": path,
                        "name": name, "size": (width, height)})
            index += 1
    return out


def place_figures(blocks: list, figures: list, caption_pages: dict) -> tuple:
    """Put each figure into the blocks, beside the caption that names it.

    A captioned figure joins its caption in one block, as an image and a hard
    line break above the caption text. That shape is deliberate: alone in a
    paragraph the image would become a Pandoc Figure, and the journal's
    figures filter numbers every Figure from 1 in document order, which would
    print "Figure 1." over a caption reading "Figure 7.1" and leave every
    "see Figure 7.3" in the prose pointing at the wrong picture. The printed
    numbering is the one a reconstruction has to keep.

    A figure with no caption has no anchor and no description. It follows the
    last captioned figure before it, or closes the document if there is none,
    and it is counted in the notes rather than dropped.
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
    last_captioned = None
    for figure in figures:
        caption = caption_pages.get((figure["page"], figure["index"]), "")
        if caption:
            position = caption_at.get(_caption_key(caption))
        else:
            position = None
        if position is None:
            unplaced += 1
            target = last_captioned if last_captioned is not None else len(blocks)
            inserts.setdefault(target, []).append((figure, ""))
        else:
            inserts.setdefault(position, []).append((figure, caption))
            last_captioned = position

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

    placed = len(figures) - unplaced
    if figures:
        notes.append(f"Extracted {len(figures)} figure(s); placed {placed} "
                     f"beside the caption naming it.")
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
# table. Two columns and two rows is the smallest thing that is one.
MIN_TABLE_ROWS = 2
MIN_TABLE_COLS = 2
_TABLE_CAPTION_RE = re.compile(
    r"^Table\s+(?P<number>\d+(?:\.\d+)*)\s*[:.]?\s+(?=[A-Z])")


def is_table_caption(text: str) -> bool:
    return bool(_TABLE_CAPTION_RE.match(text.strip()))


def find_page_tables(page) -> list:
    """The ruled tables on one page, as (bbox, rows), largest first.

    pdfplumber reports a table and then the cells inside it as further
    tables, so anything sitting inside another's box is dropped: chapter 11's
    page 11 came back as four tables of which three were pieces of the first.
    """
    try:
        found = page.find_tables(table_settings=TABLE_SETTINGS)
    except Exception:
        return []
    candidates = []
    for table in found:
        try:
            rows = _clean_table(table.extract())
        except Exception:
            continue
        if len(rows) < MIN_TABLE_ROWS:
            continue
        if max((len(r) for r in rows), default=0) < MIN_TABLE_COLS:
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


def _clean_table(rows: list) -> list:
    """Tidy extracted cells: rejoin broken words, drop empty rows and columns.

    A cell's text is wrapped as it was printed, so it arrives with the line
    breaks and the hyphens in it; "introduc- tion" has to come back together
    or the table reads as badly as the prose it replaces. Columns that are
    entirely empty come from rules pdfplumber counted as boundaries.
    """
    table = [[_clean_cell(cell) for cell in row] for row in rows if row]
    table = [row for row in table if any(cell for cell in row)]
    if not table:
        return []
    width = max(len(row) for row in table)
    table = [row + [""] * (width - len(row)) for row in table]
    keep = [i for i in range(width) if any(row[i] for row in table)]
    return [[row[i] for i in keep] for row in table]


def _clean_cell(cell) -> str:
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", str(cell or ""))
    text = re.sub(r"\s*\n\s*", " ", text)
    # A pipe inside a cell would close the column it sits in.
    return re.sub(r"\s+", " ", text).replace("|", r"\|").strip()


def table_to_markdown(rows: list) -> str:
    """A pipe table, whose first row is the header.

    The header matters more than the shape: it is what lets a screen reader
    say which column a cell is in, and a table read as prose has no columns
    to name. Where the first row is empty in its first cell, as a comparison
    table's corner is, the cell is left empty rather than invented.
    """
    if not rows:
        return ""
    width = max(len(row) for row in rows)
    body = [row + [""] * (width - len(row)) for row in rows]
    out = ["| " + " | ".join(body[0]) + " |",
           "|" + "|".join([" --- "] * width) + "|"]
    for row in body[1:]:
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
    """
    inside = []
    out = []
    for line in lines:
        boxes = tables_by_page.get(line.page) or []
        if boxes and not (is_table_caption(line.plain)
                          or is_figure_caption(line.plain)):
            centre = line.top
            if any(bbox[1] - 2 <= centre <= bbox[3] + 2 for bbox, _ in boxes):
                inside.append(line)
                continue
        out.append(line)
    return out, len(inside)


def place_tables(blocks: list, tables: list) -> tuple:
    """Put each table after the caption that names it.

    The series prints the caption above the table, so that is where it goes.
    A pipe table has to begin a line, so it is its own block rather than
    joined to the caption the way a figure is to its own.

    Paired in reading order rather than by page, which is where this differs
    from the figures. A figure and its caption are on one page by definition,
    since the caption is set under the picture. A table's caption is set above
    it and the two part company across a page break: both of chapter 11's did,
    and pairing them by page matched neither. Tables come in page order and
    captions in document order, so the nth of one is the nth of the other.
    """
    caption_positions = [
        position for position, (kind, text) in enumerate(blocks)
        if kind in ("body", "note", "quote") and is_table_caption(text)
    ]

    inserts: dict = {}
    unplaced = 0
    for index, table in enumerate(tables):
        if index < len(caption_positions):
            position = caption_positions[index]
        else:
            unplaced += 1
            position = len(blocks) - 1
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
                     f"placed {len(tables) - unplaced} against a caption.")
    if unplaced:
        notes.append(f"{unplaced} table(s) matched no caption and follow the "
                     f"text instead; check where they belong.")
    return out, notes


def _caption_key(text: str) -> str:
    """A caption's first few words, which is enough to find it again."""
    return " ".join(re.sub(r"\s+", " ", text).strip().split()[:8]).lower()


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


def extract(pdf_path: Path, genre_heads: Optional[tuple] = None,
            assets_dir: Optional[Path] = None,
            skip_image_digests=frozenset()) -> IngestResult:
    """Read a PDF chapter into front matter plus Markdown body.

    With `assets_dir`, the figures are written there and placed in the body.
    Without it the text comes through alone, which is what it did before
    figures were extracted at all, and what the tests rely on.
    """
    import pdfplumber

    genre_heads = genre_heads or GENRE_HEADS
    notes: list = []
    all_lines: list = []
    page_width = 0.0
    tables_by_page: dict = {}
    with pdfplumber.open(str(pdf_path)) as pdf:
        if not pdf.pages:
            raise ValueError(f"{pdf_path.name} has no pages.")
        page_width = float(pdf.pages[0].width)
        for page_no, page in enumerate(pdf.pages, 1):
            all_lines.extend(_page_lines(page, page_no))
            found = find_page_tables(page)
            if found:
                tables_by_page[page_no] = found

    if not all_lines:
        raise ValueError(
            f"No extractable text in {pdf_path.name}. A scanned PDF needs OCR "
            "before it can be ingested; see ocr.py."
        )

    layout = learn_layout(all_lines, page_width)
    kept, dropped = strip_furniture(all_lines, layout)
    notes.append(f"Dropped {len(dropped)} line(s) of page furniture.")

    # Before the vocabulary is built, so that cells shredded across columns
    # do not teach it their fragments as words.
    if tables_by_page:
        kept, in_tables = drop_lines_inside_tables(kept, tables_by_page)
        notes.append(f"Took {in_tables} line(s) out of the prose that belong "
                     f"to a table, and read the table instead.")

    vocab, compounds = build_vocabulary(kept)

    first_page = [l for l in kept if l.page == 1]
    rest = [l for l in kept if l.page != 1]
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
            for index, (_bbox, rows) in enumerate(tables_by_page[page_no]):
                tables.append({"page": page_no, "index": index, "rows": rows})
        blocks, table_notes = place_tables(blocks, tables)
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
        blocks, figure_notes = place_figures(blocks, figures, caption_pages)
        notes.extend(figure_notes)

    body = blocks_to_markdown(blocks)

    hyphens = sum(1 for l in kept if l.text.endswith("-"))
    notes.append(f"Rejoined {hyphens} word(s) broken across a line.")
    notes.append(
        f"Learned layout: {layout.body_size}pt body, text block "
        f"{layout.body_left} to {layout.body_right}pt."
    )
    return IngestResult(front_matter=fm, body=body, notes=notes)
