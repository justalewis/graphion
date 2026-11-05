"""Put a text layer under a scanned page without changing how it looks.

R4 of `docs/cartridge-audit.md`. A scanned PDF page is a picture, so a
screen reader finds nothing at all. This reads the picture with Tesseract
and lays the recognised words under it, invisibly, at the places they were
printed. The page looks exactly as it did and can now be read aloud,
searched and selected.

**The proof is pixels, not text.** Every other pass here proves it changed
no word by comparing the visible text before and after. That cannot apply
here, because the whole point is that text appears where there was none.
The right invariant is the other half of the same promise: the page looks
identical. Each page that gets a layer is rendered before and after and the
two images compared, and a page whose appearance moved is dropped. Pages
that already had a text layer are never touched, and their text is compared
as it always was.

**It overlays; it does not rebuild.** `tesseract ... pdf` on its own makes a
new page from a re-encoded image, which would replace the scan and break
"every byte of ink is unchanged". Tesseract 5's text-only mode produces just
the invisible text, which is laid over the original page, so the scanned
image stream is the same bytes it arrived as. Measured on a real page of the
CPTSC corpus: 2,837 characters added, pixels identical, and the file grew by
34 KB.

**Three things it refuses to do.**

It does not guess the language. Recognition needs a language model, and
reading Spanish with the English one produces confident nonsense. With none
given, nothing is recognised and the pages are reported as owing OCR, which
is the rule `lang` already follows everywhere else here.

It does not call a page done because Tesseract was sure of it. Measured on
real scans, the page that scored 92 percent mean confidence still read
"Schoo! of Engineering", "Alr Force [Institute" and "(Dick, | don't". An
average hides visible errors, so every layer owes proofing and the report
says so. Per-page confidence is recorded only so the worst pages can be read
first.

It does not touch a rotated page. Tesseract reads the page as rendered, in
its rotated orientation, while the layer is placed in unrotated page space,
so the words would land in the wrong places and nothing downstream would
notice. Reported, not guessed at.
"""
from __future__ import annotations

import hashlib
import io
import os
import statistics
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import ocr

# A page with fewer characters than this has no usable text layer. A scan
# with a few stray characters of page furniture still needs reading, and a
# page of real prose has far more.
MIN_TEXT_CHARS = 20

# Resolution the page is read at. 150 dpi read as well as 300 on every page
# measured, at roughly the same cost, so this is the lower figure.
OCR_DPI = 200

# Words below this confidence are counted so the worst pages can be read
# first. Not a threshold for "done": see the module docstring.
LOW_CONFIDENCE = 60.0

# The resolution pages are compared at. Low on purpose: the question is
# whether anything visible moved, and a coarse render answers it quickly.
SIGNATURE_DPI = 100

# ISO 639-1 to Tesseract's three-letter codes, for the languages most often
# met. A region subtag is dropped, since the model is per language.
LANGUAGES = {
    "en": "eng", "es": "spa", "fr": "fra", "de": "deu", "it": "ita",
    "pt": "por", "nl": "nld", "ru": "rus", "pl": "pol", "sv": "swe",
    "ar": "ara", "ja": "jpn", "ko": "kor", "tr": "tur", "el": "ell",
}


class Stopped(Exception):
    """Cancelled between pages. The caller decides what that means."""


@dataclass
class PageOcr:
    page: int                      # 1-based
    outcome: str                   # layered | blank | skipped | dropped
    words: int = 0
    mean_confidence: float = 0.0
    low_words: int = 0
    note: str = ""


@dataclass
class OcrResult:
    data: bytes
    pages: list = field(default_factory=list)
    changes: list = field(default_factory=list)
    owed: list = field(default_factory=list)
    layered: list = field(default_factory=list)   # zero-based page indexes
    error: str = ""

    @property
    def changed(self) -> bool:
        return bool(self.layered)


def tesseract_language(code: Optional[str]) -> Optional[str]:
    """A document language as the Tesseract model name, if it is installed."""
    if not code:
        return None
    base = code.split("-")[0].split("_")[0].lower()
    name = LANGUAGES.get(base)
    if name is None:
        return None
    return name if name in installed_languages() else None


def installed_languages() -> set:
    binary = ocr.tesseract_binary()
    if not binary:
        return set()
    try:
        done = subprocess.run([binary, "--list-langs"], capture_output=True,
                              text=True, timeout=30)
    except Exception:
        return set()
    lines = [l.strip() for l in done.stdout.splitlines()]
    return {l for l in lines[1:] if l and l != "osd"}


def pages_needing_ocr(data: bytes) -> list:
    """Zero-based indexes of pages with no usable text layer."""
    import pypdf

    reader = pypdf.PdfReader(io.BytesIO(data))
    needing = []
    for index, page in enumerate(reader.pages):
        try:
            text = (page.extract_text() or "").strip()
        except Exception:
            text = ""
        if len(text) < MIN_TEXT_CHARS:
            needing.append(index)
    return needing


def _render(data: bytes, index: int, dpi: int):
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument(data)
    try:
        return pdf[index].render(scale=dpi / 72).to_pil().convert("L")
    finally:
        pdf.close()


def signatures(data: bytes, pages: list) -> dict:
    """A hash of how each named page looks, at a coarse resolution."""
    return {index: hashlib.sha256(
        _render(data, index, SIGNATURE_DPI).tobytes()).hexdigest()
        for index in pages}


def text_outside(data: bytes, pages: list) -> str:
    """The text of every page not named, which a layer must not disturb."""
    import pypdf

    skip = set(pages)
    reader = pypdf.PdfReader(io.BytesIO(data))
    return " ".join((page.extract_text() or "").strip()
                    for index, page in enumerate(reader.pages)
                    if index not in skip)


def fingerprint(data: bytes, layered: list) -> tuple:
    """What must not change when a layer is laid under `layered` pages.

    How those pages look, and the text of every other page. Compared before
    and after, here and again on the bytes written to disk.
    """
    return signatures(data, layered), text_outside(data, layered)


def _read_page(image, language: str):
    """One pass of Tesseract: the invisible text and the word confidences."""
    binary = ocr.tesseract_binary()
    with tempfile.TemporaryDirectory(prefix="graphion-ocr-") as tmp:
        source = Path(tmp) / "page.png"
        image.save(source)
        base = Path(tmp) / "out"
        done = subprocess.run(
            [binary, str(source), str(base), "-l", language,
             "-c", "textonly_pdf=1", "pdf", "tsv"],
            capture_output=True, text=True, timeout=300)
        layer = base.with_suffix(".pdf")
        table = base.with_suffix(".tsv")
        if done.returncode != 0 or not layer.exists():
            raise RuntimeError(done.stderr.strip()[:200] or "tesseract failed")
        confidences = []
        for row in table.read_text(encoding="utf-8").splitlines()[1:]:
            cells = row.split("\t")
            if len(cells) >= 12 and cells[0] == "5" and cells[11].strip():
                try:
                    value = float(cells[10])
                except ValueError:
                    continue
                if value >= 0:
                    confidences.append(value)
        return layer.read_bytes(), confidences


def _overlay(data: bytes, layers: dict) -> bytes:
    """Lay each page's invisible text over that page and write the file."""
    import pypdf
    from pypdf import Transformation

    reader = pypdf.PdfReader(io.BytesIO(data))
    writer = pypdf.PdfWriter(clone_from=reader)
    for index, layer in layers.items():
        target = writer.pages[index]
        layer_page = pypdf.PdfReader(io.BytesIO(layer)).pages[0]
        width = float(target.mediabox.width)
        height = float(target.mediabox.height)
        # The layer is sized in the units Tesseract picked, not the page's,
        # so it is scaled to fit rather than assumed to match.
        scale_x = width / float(layer_page.mediabox.width)
        scale_y = height / float(layer_page.mediabox.height)
        target.merge_transformed_page(
            layer_page, Transformation().scale(scale_x, scale_y))
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def add_text_layer(
        data: bytes, language: Optional[str],
        tick: Optional[Callable] = None,
        stop: Optional[Callable] = None) -> OcrResult:
    """Read the scanned pages of one PDF and lay a text layer under them.

    Returns the file unchanged, with the reason, whenever it cannot do that
    honestly: no Tesseract, no language, a language model that is not
    installed, or a page that would not come out looking the same.
    """
    from remediate import Change, Owed

    result = OcrResult(data=data)
    try:
        needing = pages_needing_ocr(data)
    except Exception as exc:
        result.error = f"could not be read: {exc}"
        return result
    if not needing:
        return result

    def owe(kind, detail):
        result.owed.append(Owed(kind=kind, count=len(needing), detail=detail))
        return result

    if not ocr.tesseract_binary_available():
        return owe("ocr-unavailable",
                   f"{len(needing)} page(s) have no text layer, and "
                   f"Tesseract is not installed on this machine, so they "
                   f"cannot be read by a screen reader.")
    if not language:
        return owe("ocr-needs-a-language",
                   f"{len(needing)} page(s) have no text layer. Reading "
                   f"them needs the language of the document, and reading "
                   f"Spanish with the English model produces confident "
                   f"nonsense, so none was guessed.")
    model = tesseract_language(language)
    if model is None:
        return owe("ocr-language-unavailable",
                   f"{len(needing)} page(s) have no text layer, and the "
                   f"Tesseract language model for {language!r} is not "
                   f"installed.")

    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(data))
    layers: dict = {}
    pages: list = []
    for done, index in enumerate(needing):
        if stop and stop():
            raise Stopped()
        if tick:
            tick(done, len(needing), index)
        if reader.pages[index].rotation:
            pages.append(PageOcr(index + 1, "skipped",
                                 note="the page is rotated, so the words "
                                      "would land in the wrong places"))
            continue
        try:
            layer, confidences = _read_page(_render(data, index, OCR_DPI),
                                            model)
        except Exception as exc:
            pages.append(PageOcr(index + 1, "skipped",
                                 note=f"Tesseract failed: {exc}"))
            continue
        if not confidences:
            pages.append(PageOcr(index + 1, "blank",
                                 note="no text was found on this page"))
            continue
        layers[index] = layer
        pages.append(PageOcr(
            index + 1, "layered", words=len(confidences),
            mean_confidence=round(statistics.mean(confidences), 1),
            low_words=sum(1 for c in confidences if c < LOW_CONFIDENCE)))

    if layers:
        before = signatures(data, list(layers))
        merged = _overlay(data, layers)
        after = signatures(merged, list(layers))
        moved = [i for i in layers if before[i] != after[i]]
        if moved:
            # A page whose appearance changed is not shipped with a layer.
            for index in moved:
                layers.pop(index)
                for page in pages:
                    if page.page == index + 1:
                        page.outcome = "dropped"
                        page.note = ("laying the text under it changed how "
                                     "the page looks, so it was left as it "
                                     "arrived")
            merged = _overlay(data, layers) if layers else data
        result.data = merged
        result.layered = sorted(layers)
    result.pages = pages

    layered = [p for p in pages if p.outcome == "layered"]
    if layered:
        worst = sorted(layered, key=lambda p: p.mean_confidence)[:5]
        result.changes.append(Change(
            kind="ocr-text-layer", count=len(layered),
            detail=(f"laid a recognised text layer under {len(layered)} "
                    f"scanned page(s), so a screen reader can read them. "
                    f"The pages look exactly as they did.")))
        result.owed.append(Owed(
            kind="ocr-needs-proofing", count=len(layered),
            detail=("OCR is confidently wrong: a page scoring 92 percent "
                    "still read \"Schoo! of Engineering\". Every recognised "
                    "layer needs a person to read it against the page. "
                    "Lowest confidence first: "
                    + ", ".join(f"p{p.page} ({p.mean_confidence})"
                                for p in worst) + ".")))
    skipped = [p for p in pages if p.outcome in ("skipped", "dropped")]
    if skipped:
        result.owed.append(Owed(
            kind="ocr-page-skipped", count=len(skipped),
            detail="; ".join(f"p{p.page}: {p.note}" for p in skipped[:5])))
    return result
