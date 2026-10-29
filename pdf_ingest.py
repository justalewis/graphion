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
                                 or gap_break):
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
        if kind in ("head", "title"):
            # "title" is a head the series sets off-centre, such as the
            # "Teacher Resources for ..." page. It is still a head.
            out.append("# " + text)
        elif kind == "quote":
            out.append("> " + text)
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


def extract(pdf_path: Path, genre_heads: Optional[tuple] = None) -> IngestResult:
    """Read a PDF chapter into front matter plus Markdown body."""
    import pdfplumber

    genre_heads = genre_heads or GENRE_HEADS
    notes: list = []
    all_lines: list = []
    page_width = 0.0
    with pdfplumber.open(str(pdf_path)) as pdf:
        if not pdf.pages:
            raise ValueError(f"{pdf_path.name} has no pages.")
        page_width = float(pdf.pages[0].width)
        for page_no, page in enumerate(pdf.pages, 1):
            all_lines.extend(_page_lines(page, page_no))

    if not all_lines:
        raise ValueError(
            f"No extractable text in {pdf_path.name}. A scanned PDF needs OCR "
            "before it can be ingested; see ocr.py."
        )

    layout = learn_layout(all_lines, page_width)
    kept, dropped = strip_furniture(all_lines, layout)
    notes.append(f"Dropped {len(dropped)} line(s) of page furniture.")

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
    body = blocks_to_markdown(blocks)

    hyphens = sum(1 for l in kept if l.text.endswith("-"))
    notes.append(f"Rejoined {hyphens} word(s) broken across a line.")
    notes.append(
        f"Learned layout: {layout.body_size}pt body, text block "
        f"{layout.body_left} to {layout.body_right}pt."
    )
    return IngestResult(front_matter=fm, body=body, notes=notes)
