"""DOCX-side preprocessors that run before Pandoc ingest.

Each function in this module is OPTIONAL and gracefully degrades when
its underlying dependency is missing. The upload route checks
`*_available()` before offering the toggle in the UI.

Functions:
  - `mammoth_available` / `ingest_with_mammoth`: alternate DOCX → HTML
    reader (and via Pandoc HTML → MD). Often handles text boxes and
    complex tables better than Pandoc's DOCX reader.
  - `libreoffice_available` / `libreoffice_normalize`: open + re-save
    the DOCX via headless LibreOffice. Round-tripping through LO
    normalizes many Word quirks (text boxes flattened, autoformat
    junk cleaned).
  - `scan_docx_for_warnings`: walks a DOCX with python-docx (already a
    hard dependency) and returns a list of human-readable warnings
    about structures that may render imperfectly.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import List, Optional, Tuple


# ---------- Mammoth ----------

def mammoth_available() -> bool:
    try:
        import mammoth  # noqa: F401
        return True
    except Exception:
        return False


def ingest_with_mammoth(
    docx_path: Path, article_path: Path
) -> Tuple[Optional[Path], str]:
    """Convert DOCX to Markdown via Mammoth -> HTML -> Pandoc.

    Returns (raw_md_path, log) on success, (None, error) on failure.
    Writes the intermediate HTML to article-mammoth.html for inspection.
    """
    if not mammoth_available():
        return None, "mammoth not installed (pip install mammoth)"
    import mammoth
    import pypandoc

    assets = article_path / "assets"
    assets.mkdir(exist_ok=True)

    # Convert DOCX -> HTML via Mammoth. Mammoth produces clean semantic
    # HTML even for documents with text boxes, headings, lists, etc.
    image_counter = {"n": 0}

    def image_handler(image):
        # Save embedded images into assets/ and reference them by
        # relative path. Mammoth's default would inline as base64.
        image_counter["n"] += 1
        ext = image.content_type.split("/")[-1] or "png"
        # Map a couple of mime types to canonical extensions.
        ext = {"jpeg": "jpg", "x-emf": "emf"}.get(ext, ext)
        out = assets / f"mammoth-image-{image_counter['n']}.{ext}"
        with image.open() as src, open(out, "wb") as dst:
            dst.write(src.read())
        return {"src": f"assets/{out.name}"}

    with open(docx_path, "rb") as f:
        result = mammoth.convert_to_html(
            f, convert_image=mammoth.images.img_element(image_handler)
        )
    html_text = result.value
    messages = result.messages

    html_path = article_path / "article-mammoth.html"
    html_path.write_text(html_text, encoding="utf-8")

    # Convert that HTML to Markdown via Pandoc.
    raw_md = article_path / "article-raw.md"
    pypandoc.convert_text(
        html_text,
        to="markdown",
        format="html",
        outputfile=str(raw_md),
        extra_args=["--wrap=none", "--markdown-headings=atx"],
    )

    warn_lines = "\n".join(f"  - {m.type}: {m.message}" for m in messages)
    log = (
        f"mammoth ingest OK\n"
        f"  intermediate html: {html_path.name}\n"
        f"  raw markdown: {raw_md.name}\n"
        f"  images extracted: {image_counter['n']}\n"
        f"mammoth messages:\n{warn_lines or '  (none)'}\n"
    )
    return raw_md, log


# ---------- LibreOffice preprocessing ----------

def libreoffice_available() -> bool:
    """Look for LibreOffice's `soffice` binary on PATH (or in common
    install locations on Windows)."""
    if shutil.which("soffice"):
        return True
    # Common Windows install path
    win_paths = [
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    ]
    return any(p.exists() for p in win_paths)


def _libreoffice_binary() -> str:
    bin_path = shutil.which("soffice")
    if bin_path:
        return bin_path
    for p in (
        Path(r"C:\Program Files\LibreOffice\program\soffice.exe"),
        Path(r"C:\Program Files (x86)\LibreOffice\program\soffice.exe"),
    ):
        if p.exists():
            return str(p)
    raise FileNotFoundError("soffice (LibreOffice) not found")


def libreoffice_normalize(docx_path: Path, out_dir: Path) -> Tuple[Optional[Path], str]:
    """Round-trip the DOCX through LibreOffice headless to normalize.

    Returns (normalized_path, log) on success.
    """
    if not libreoffice_available():
        return None, "LibreOffice (soffice) not found on PATH"
    binary = _libreoffice_binary()
    out_dir.mkdir(parents=True, exist_ok=True)
    try:
        result = subprocess.run(
            [
                binary, "--headless", "--convert-to", "docx",
                "--outdir", str(out_dir), str(docx_path),
            ],
            capture_output=True, text=True, timeout=60,
        )
    except subprocess.TimeoutExpired:
        return None, "LibreOffice conversion timed out (60s)"
    if result.returncode != 0:
        return None, f"LibreOffice failed: {result.stderr.strip()}"
    # LibreOffice writes to out_dir with the same stem.
    candidate = out_dir / (docx_path.stem + ".docx")
    if not candidate.exists():
        # LibreOffice may use a different output name. Pick the most
        # recent .docx in out_dir.
        docs = sorted(
            out_dir.glob("*.docx"),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not docs:
            return None, "LibreOffice produced no output file"
        candidate = docs[0]
    log = (
        f"LibreOffice normalize OK\n"
        f"  input: {docx_path.name} ({docx_path.stat().st_size:,} bytes)\n"
        f"  output: {candidate.name} ({candidate.stat().st_size:,} bytes)\n"
    )
    return candidate, log


# ---------- DOCX structural scan (always available) ----------

def scan_docx_for_warnings(docx_path: Path) -> List[str]:
    """Open a DOCX with python-docx and report on structures that may
    render imperfectly through Pandoc. Returns a list of human-readable
    warnings.

    Detects:
      - text boxes (very common cause of rendering glitches)
      - tables with merged cells
      - tables with > 6 columns (often render too narrow)
      - nested tables
      - missing alt text on images
      - tracked changes left in the document
    """
    warnings: List[str] = []
    try:
        from docx import Document
        from docx.oxml.ns import qn
    except Exception:
        return ["python-docx unavailable; skipping structural scan"]
    try:
        d = Document(str(docx_path))
    except Exception as exc:
        return [f"could not open docx: {exc}"]

    # Text boxes: look for <w:txbxContent> anywhere in the document XML.
    body_xml = d.element.body
    txbx = body_xml.findall(".//" + qn("w:txbxContent"))
    if txbx:
        warnings.append(
            f"Contains {len(txbx)} text box(es). Text boxes do not survive "
            "DOCX→Markdown cleanly. Recommended: copy the text out, delete the "
            "text box, paste as a normal paragraph styled 'Quote' or similar."
        )

    # Tables: scan for merged cells, wide tables, nested tables.
    tables = d.tables
    if tables:
        merged_count = 0
        wide_count = 0
        nested_count = 0
        for tbl in tables:
            # python-docx doesn't directly expose merge state; check XML.
            xml = tbl._element
            if xml.findall(".//" + qn("w:vMerge")):
                merged_count += 1
            if xml.findall(".//" + qn("w:gridSpan")):
                merged_count += 1
            try:
                col_count = len(tbl.rows[0].cells) if tbl.rows else 0
            except Exception:
                col_count = 0
            if col_count > 6:
                wide_count += 1
            # Nested tables: a table whose cells contain another table.
            inner = xml.findall(".//" + qn("w:tbl"))
            if len(inner) > 0:
                nested_count += 1
        if merged_count:
            warnings.append(
                f"{merged_count} table(s) have merged cells (vMerge/gridSpan). "
                "Pandoc emits inconsistent column widths for merged tables; "
                "consider restructuring with separate cells."
            )
        if wide_count:
            warnings.append(
                f"{wide_count} table(s) have more than 6 columns and may "
                "render too narrow at 6x9 trim. Consider splitting into "
                "two stacked tables or rotating to portrait if data permits."
            )
        if nested_count:
            warnings.append(
                f"{nested_count} table(s) contain nested tables. Nested "
                "tables almost never survive — pull the inner table out "
                "and reference it as Figure N."
            )

    # Images without alt text.
    images_total = 0
    images_no_alt = 0
    for shape in body_xml.findall(".//" + qn("w:drawing")):
        images_total += 1
        # docPr element holds title/descr.
        docPr = shape.findall(".//" + qn("wp:docPr"))
        has_alt = False
        for el in docPr:
            if el.get("descr") or el.get("title"):
                has_alt = True
                break
        # Also check pic:cNvPr (newer namespace usage).
        if not has_alt:
            cnvpr = shape.findall(
                ".//{http://schemas.openxmlformats.org/drawingml/2006/picture}cNvPr"
            )
            for el in cnvpr:
                if el.get("descr") or el.get("title"):
                    has_alt = True
                    break
        if not has_alt:
            images_no_alt += 1
    if images_total and images_no_alt:
        warnings.append(
            f"{images_no_alt} of {images_total} image(s) have no alt text. "
            "Add alt text in Word (right-click image → Edit Alt Text) before "
            "publishing — required for accessibility."
        )

    # Tracked changes still present.
    ins = body_xml.findall(".//" + qn("w:ins"))
    dele = body_xml.findall(".//" + qn("w:del"))
    if ins or dele:
        warnings.append(
            f"Tracked changes present: {len(ins)} insertion(s), "
            f"{len(dele)} deletion(s). The ingest will accept or reject "
            "them per the upload form; consider resolving in Word first "
            "for clarity."
        )

    return warnings


# ---------- Word image crops ----------

# Word records a crop as a fraction of each edge, in hundred-thousandths.
_SRCRECT_EDGES = ("l", "t", "r", "b")


def _docx_image_crops(docx_path: Path) -> dict:
    """Map each embedded media filename to the crop Word displays it with.

    Cropping an image in Word does not alter the stored file. Word keeps the
    original and records an `a:srcRect` giving the fraction trimmed from each
    edge, then sizes the *cropped* region on the page. Pandoc extracts the
    uncropped file but carries the cropped dimensions across, so anything
    cropped in Word arrives stretched to the wrong aspect ratio.

    Returns ``{media_filename: (left, top, right, bottom)}`` as fractions of
    the full image, including only images with a crop. A filename used more
    than once with differing crops is omitted, since one stored file cannot
    satisfy both; the caller warns instead of guessing.
    """
    import re
    import zipfile
    from collections import defaultdict

    seen = defaultdict(set)
    try:
        with zipfile.ZipFile(docx_path) as z:
            try:
                rels = z.read("word/_rels/document.xml.rels").decode("utf-8", "replace")
                document = z.read("word/document.xml").decode("utf-8", "replace")
            except KeyError:
                return {}
    except Exception:
        return {}

    # relationship id -> media filename
    targets = {
        m.group(1): m.group(2).rsplit("/", 1)[-1]
        for m in re.finditer(r'Id="([^"]+)"[^>]*Target="([^"]*media/[^"]+)"', rels)
    }

    # Each <pic:pic> holds both the relationship reference and its crop.
    for pic in re.findall(r"<pic:pic\b.*?</pic:pic>", document, re.S):
        embed = re.search(r'r:embed="([^"]+)"', pic)
        if not embed:
            continue
        name = targets.get(embed.group(1))
        if not name:
            continue
        rect = re.search(r"<a:srcRect\b([^/>]*)/?>", pic)
        crop = (0.0, 0.0, 0.0, 0.0)
        if rect:
            attrs = rect.group(1)
            values = []
            for edge in _SRCRECT_EDGES:
                m = re.search(rf'\b{edge}="(-?\d+)"', attrs)
                values.append((int(m.group(1)) / 100000.0) if m else 0.0)
            crop = tuple(values)
        seen[name].add(crop)

    out = {}
    for name, crops in seen.items():
        if len(crops) != 1:
            continue
        crop = next(iter(crops))
        if any(v > 0 for v in crop):
            out[name] = crop
    return out


def apply_docx_image_crops(docx_path: Path, assets_dir: Path) -> List[str]:
    """Crop extracted media to the region Word actually displayed.

    Rewrites each cropped file in place so the markdown reference, and the
    width and height Pandoc copied from Word, all stay valid. Returns
    human-readable notes for the conversion log.

    Silently does nothing when Pillow is unavailable; an uncropped image is
    a worse rendering, not a failed one.
    """
    crops = _docx_image_crops(docx_path)
    if not crops:
        return []
    try:
        from PIL import Image
    except ImportError:
        return [
            f"{len(crops)} image(s) are cropped in Word, but Pillow is not "
            "installed, so they will render uncropped and stretched."
        ]

    notes: List[str] = []
    for name, (left, top, right, bottom) in crops.items():
        matches = list(assets_dir.rglob(name))
        if not matches:
            continue
        path = matches[0]
        try:
            with Image.open(path) as im:
                w, h = im.size
                box = (
                    int(round(w * left)),
                    int(round(h * top)),
                    int(round(w * (1.0 - right))),
                    int(round(h * (1.0 - bottom))),
                )
                if box[2] - box[0] < 1 or box[3] - box[1] < 1:
                    continue
                im.crop(box).save(path)
            notes.append(
                f"cropped {name} to the region Word displayed "
                f"({w}x{h} -> {box[2] - box[0]}x{box[3] - box[1]})"
            )
        except Exception as exc:  # noqa: BLE001 - report, never fail ingest
            notes.append(f"could not crop {name}: {type(exc).__name__}: {exc}")
    return notes


__all__ = [
    "apply_docx_image_crops",
    "mammoth_available",
    "ingest_with_mammoth",
    "libreoffice_available",
    "libreoffice_normalize",
    "scan_docx_for_warnings",
]
