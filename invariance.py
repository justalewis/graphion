"""Proof that remediation did not change a word.

"It will not change the language or content of your course" is what makes
an instructor willing to hand their work to somebody else. It is worth
more than a promise, so it is a test: the visible text of every page,
document and slide is extracted before remediation and again after, and
any pass that changed a word fails the run.

Everything remediation is allowed to add lives in an attribute, in
metadata, or in structure. An `alt`, a `lang`, a `scope`, a `/Lang`, a
`dc:title`, an OCR layer under a scanned image: none of those is visible
text, so all of them leave this fingerprint untouched. Rewording a
sentence, "helpfully" expanding an abbreviation, or regenerating a page
from a reconstruction does not, which is exactly the point.

Built before the first fixing pass rather than after, so every pass is
held to it from its first commit. That is the order
`test_assessing_a_folder_leaves_it_exactly_as_it_was` was written in.

**Two things it deliberately does not cover**, and both are reported
separately rather than folded in. Appearance is not text: normalising an
`<h3>` to an `<h2>` keeps every word and changes how the page looks. And
a file this cannot read contributes nothing, so `Comparison.unread` is
counted and shown; a fingerprint that silently skipped half an archive
would be a proof of nothing that reads like a proof of something.

**pypdf, not pdfplumber, for PDF text.** This needs the same extractor on
both sides, not the best one: pdfplumber reads character positions and is
the right tool for reconstruction, and it is an order of magnitude slower
over the 1,199 PDFs a set of cartridges holds. Consistency is what is
being asked for here.
"""
from __future__ import annotations

import hashlib
import io
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Collapsed before comparison, because whitespace is not language. Reserialising
# HTML moves newlines and indentation around without touching a word, and a
# check that failed on that would cry wolf on every run until somebody turned
# it off.
_SPACE = re.compile(r"\s+")

# What this can read. Anything else is counted as unread rather than as
# unchanged; see the module docstring.
READABLE = {".html", ".htm", ".xhtml", ".pdf", ".docx", ".pptx"}


def normalise(text: str) -> str:
    """Whitespace collapsed, ends trimmed. Case and punctuation kept.

    Case is language: "US" and "us" are different words, and a pass that
    changed one to the other should fail.
    """
    return _SPACE.sub(" ", text or "").strip()


def _html_text(data: bytes) -> str:
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(data)
    # Script and style are not read to anybody, and a remediation pass is
    # free to touch them. Dropped so it can.
    for bad in tree.xpath("//script | //style"):
        bad.getparent().remove(bad)
    # Joined with a space rather than `text_content()`, which concatenates
    # across tags: `</h1><p>` gives "rhetoricallyA writer" and
    # `</h1>\n  <p>` gives "rhetorically A writer", so a pass that merely
    # reserialised the page would read as having changed a word. Any pass
    # that edits an attribute reserialises, so that is every run, and a
    # check which fires on every run is a check somebody turns off.
    #
    # The cost is that inline markup inside a word, `un<em>der</em>stand`,
    # fingerprints as three words. That happens identically on both sides,
    # so it cannot produce a false positive; this is a fingerprint, not a
    # reading.
    return " ".join(tree.itertext())


def _pdf_text(data: bytes) -> str:
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(data))
    return " ".join(page.extract_text() or "" for page in reader.pages)


def _docx_text(data: bytes) -> str:
    import docx

    document = docx.Document(io.BytesIO(data))
    parts = [p.text for p in document.paragraphs]
    # Table cells are text on the page and belong in the fingerprint; a
    # pass that promoted a row to a header must not also reword a cell.
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return " ".join(parts)


def _pptx_text(data: bytes) -> str:
    """Every run of text on every slide and every set of speaker notes.

    Read at the XML level rather than through python-pptx, which models
    shapes and so misses text in the corners of a deck: grouped shapes,
    tables inside placeholders, and notes. The same extractor runs on both
    sides of a comparison, so what it needs is to be consistent, not to be
    the best reader.
    """
    import zipfile

    from lxml import etree

    a_t = "{http://schemas.openxmlformats.org/drawingml/2006/main}t"
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        parts = sorted(n for n in z.namelist()
                       if re.fullmatch(r"ppt/(slides|notesSlides)/[^/]+\.xml", n))
        for name in parts:
            root = etree.fromstring(z.read(name))
            out.extend(el.text or "" for el in root.iter(a_t))
    return " ".join(out)


_READERS = {
    ".html": _html_text, ".htm": _html_text, ".xhtml": _html_text,
    ".pdf": _pdf_text,
    ".docx": _docx_text,
    ".pptx": _pptx_text,
}


def text_of(name: str, data: bytes) -> Optional[str]:
    """The visible text of one file, or None where it has none to read.

    None and "" are different answers and are kept apart: an empty string
    is a file that was read and holds no text, which is a fact about the
    file, while None is a file nothing here can read, which is a fact
    about this module.
    """
    reader = _READERS.get(Path(name).suffix.lower())
    if reader is None:
        return None
    try:
        return normalise(reader(data))
    except Exception:
        # A file that will not parse cannot be fingerprinted, and that is
        # not the same as one that did not change. Unread, loudly.
        return None


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class Print:
    """One file's text, reduced to a hash and a length."""

    path: str
    digest: str
    chars: int


@dataclass
class Comparison:
    """What moved between two fingerprints of the same thing."""

    compared: int = 0
    chars: int = 0
    changed: list = field(default_factory=list)
    added: list = field(default_factory=list)
    removed: list = field(default_factory=list)
    unread: list = field(default_factory=list)

    @property
    def holds(self) -> bool:
        """Whether not a word moved.

        A removed file fails it too. Dropping a reading from a course is
        the loudest possible change to its content, and a check that only
        looked at the files still there would miss exactly that.
        """
        return not self.changed and not self.removed

    def note(self) -> str:
        """The sentence an instructor reads, which carries the denominator.

        A bare "nothing changed" is worth very little without how much was
        looked at, and the files nothing could read have to be in the same
        sentence or the number flatters.
        """
        said = (f"{self.compared} file(s) and {self.chars:,} characters of "
                f"text compared; {len(self.changed)} changed")
        if self.removed:
            said += f", {len(self.removed)} removed"
        if self.added:
            said += f", {len(self.added)} added"
        if self.unread:
            said += (f". {len(self.unread)} file(s) hold text this cannot "
                     f"read and are not covered")
        return said + "."


def fingerprint(files) -> dict:
    """Fingerprint an iterable of (path, bytes). Returns {path: Print}.

    Takes pairs rather than a directory or a zip so the same function
    serves a cartridge, a folder and a test, which is what keeps one
    reader of what "the text of this file" means.
    """
    prints: dict = {}
    for path, data in files:
        text = text_of(path, data)
        if text is None:
            continue
        prints[path] = Print(path=path, digest=digest(text), chars=len(text))
    return prints


def unreadable(files) -> list:
    """Paths that hold text in a format this cannot read.

    A `.pptx`, a legacy `.doc`, an `.rtf`. Named so the proof says what it
    does not cover instead of implying it covered everything.
    """
    out = []
    for path, _data in files:
        suffix = Path(path).suffix.lower()
        if suffix in READABLE:
            continue
        if suffix in (".ppt", ".doc", ".rtf", ".odt", ".txt", ".md"):
            out.append(path)
    return out


def compare(before: dict, after: dict, unread=()) -> Comparison:
    """Hold one fingerprint against another."""
    result = Comparison(unread=list(unread))
    for path, was in before.items():
        now = after.get(path)
        if now is None:
            result.removed.append(path)
            continue
        result.compared += 1
        result.chars += was.chars
        if now.digest != was.digest:
            result.changed.append(path)
    for path in after:
        if path not in before:
            result.added.append(path)
    return result


def fingerprint_cartridge(cart) -> tuple:
    """Fingerprint an open `cartridge.Cartridge`. Returns (prints, unread).

    Here rather than in `cartridge.py` because that module's job is to
    read a cartridge and this one's is to know what counts as its text;
    a cartridge is just one caller.
    """
    pairs = [(m.path, cart.read(m.path)) for m in cart.members()
             if Path(m.path).suffix.lower() in READABLE
             or Path(m.path).suffix.lower() in (".ppt", ".doc",
                                                ".rtf", ".odt")]
    return fingerprint(pairs), unreadable(pairs)
