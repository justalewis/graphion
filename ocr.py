"""Opt-in OCR via Tesseract for tables-as-images.

When authors paste a screenshot of a table from Excel/Sheets/etc., the
content becomes inaccessible — no semantic structure, no screen-reader
support, no indexability. This module runs Tesseract on such images and
returns plain text plus (heuristically) a Markdown table.

Requires:
  - `pytesseract` Python package (in optional requirements.txt block)
  - `tesseract` CLI binary on PATH (separate install):
      Windows:  https://github.com/UB-Mannheim/tesseract/wiki
      macOS:    brew install tesseract
      Linux:    apt install tesseract-ocr
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path
from typing import List, Optional

# Where to find the binary when it is not on PATH, resolved the way
# `PANDOC_PATH` and `EPUBCHECK_PATH` are. The Windows installer from
# UB-Mannheim puts it under %LOCALAPPDATA%\Programs\Tesseract-OCR and does
# not add that to PATH, so without this the probe below reads "absent" for a
# tool that is installed, and everything that depends on it quietly degrades.
TESSERACT_ENV = "TESSERACT_PATH"


def tesseract_binary() -> Optional[str]:
    """The binary to run, from the override first and PATH second.

    Returns the path `shutil.which` found rather than the bare name, because
    on Windows a launcher is not something `CreateProcess` runs from the name.
    """
    named = os.environ.get(TESSERACT_ENV)
    if named and Path(named).is_file():
        return named
    return shutil.which("tesseract")


def tesseract_binary_available() -> bool:
    return tesseract_binary() is not None


def python_binding_available() -> bool:
    try:
        import pytesseract  # noqa: F401
        return True
    except Exception:
        return False


def available() -> bool:
    return tesseract_binary_available() and python_binding_available()


def ocr_image(image_path: Path) -> Optional[str]:
    """Run OCR on an image and return the recognized plain text.
    Returns None if Tesseract isn't available."""
    if not available():
        return None
    if not image_path.exists():
        return None
    import pytesseract
    from PIL import Image
    pytesseract.pytesseract.tesseract_cmd = tesseract_binary()
    img = Image.open(image_path)
    return pytesseract.image_to_string(img)


def ocr_to_markdown_table(image_path: Path) -> Optional[str]:
    """Heuristically convert an OCR'd table image to a Markdown pipe
    table. Best-effort — works well for clean tabular images, poorly
    for skewed scans. Returns None if OCR unavailable.

    Strategy: split OCR output into lines, split each line by 2+
    whitespace characters (heuristic for column boundaries), align
    columns. Emit as a Markdown pipe table with the first row as the
    header.
    """
    if not available():
        return None
    text = ocr_image(image_path)
    if not text:
        return None
    import re
    lines = [l.rstrip() for l in text.split("\n") if l.strip()]
    if not lines:
        return None
    # Split each line on 2+ spaces (column boundary heuristic).
    rows: List[List[str]] = []
    for line in lines:
        cells = [c.strip() for c in re.split(r"\s{2,}", line) if c.strip()]
        if cells:
            rows.append(cells)
    if not rows:
        return None
    # Normalize column count: use the max width.
    col_count = max(len(r) for r in rows)
    rows = [r + [""] * (col_count - len(r)) for r in rows]
    # Render as pipe table.
    out_lines = []
    header = rows[0]
    out_lines.append("| " + " | ".join(header) + " |")
    out_lines.append("|" + "---|" * col_count)
    for body in rows[1:]:
        out_lines.append("| " + " | ".join(body) + " |")
    return "\n".join(out_lines)


__all__ = [
    "TESSERACT_ENV",
    "tesseract_binary",
    "tesseract_binary_available",
    "python_binding_available",
    "available",
    "ocr_image",
    "ocr_to_markdown_table",
]
