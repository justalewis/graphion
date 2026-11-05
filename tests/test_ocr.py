"""Finding Tesseract, and reading with it when it is there.

The Windows installer from UB-Mannheim puts the binary under
`%LOCALAPPDATA%\\Programs\\Tesseract-OCR` and does not add that to PATH, so
a probe that only asks PATH reads "absent" for a tool that is installed and
everything that depends on it quietly degrades. `TESSERACT_PATH` is the
same override `PANDOC_PATH` and `EPUBCHECK_PATH` already give.

The probe is the part tested everywhere. Reading real text is tested only
where Tesseract exists, and skipped where it does not, which is the
convention every optional tool in this codebase follows.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ocr


@pytest.fixture
def no_path(monkeypatch):
    """A machine with no tesseract on PATH and no override."""
    monkeypatch.delenv(ocr.TESSERACT_ENV, raising=False)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: None)


def test_it_is_absent_when_neither_the_override_nor_path_has_it(no_path):
    assert ocr.tesseract_binary() is None
    assert not ocr.tesseract_binary_available()
    assert not ocr.available()


def test_the_override_is_found_without_being_on_path(no_path, tmp_path,
                                                      monkeypatch):
    fake = tmp_path / "tesseract.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv(ocr.TESSERACT_ENV, str(fake))

    assert ocr.tesseract_binary() == str(fake)
    assert ocr.tesseract_binary_available()


def test_an_override_that_names_nothing_is_ignored_and_not_trusted(
        no_path, tmp_path, monkeypatch):
    """A stale variable pointing at a folder that has since been removed
    must read as absent rather than as available, or the probe says yes and
    the first call crashes."""
    monkeypatch.setenv(ocr.TESSERACT_ENV, str(tmp_path / "gone" / "t.exe"))

    assert ocr.tesseract_binary() is None
    assert not ocr.tesseract_binary_available()


def test_path_is_used_when_there_is_no_override(monkeypatch):
    monkeypatch.delenv(ocr.TESSERACT_ENV, raising=False)
    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/usr/bin/tesseract")

    assert ocr.tesseract_binary() == "/usr/bin/tesseract"


def test_the_override_outranks_path(tmp_path, monkeypatch):
    fake = tmp_path / "tesseract.exe"
    fake.write_bytes(b"")
    monkeypatch.setenv(ocr.TESSERACT_ENV, str(fake))
    monkeypatch.setattr(ocr.shutil, "which", lambda name: "/usr/bin/tesseract")

    assert ocr.tesseract_binary() == str(fake)


def test_reading_an_image_declines_where_there_is_no_binary(no_path, tmp_path):
    image = tmp_path / "x.png"
    image.write_bytes(b"")

    assert ocr.ocr_image(image) is None


# ---------- with the real thing ----------

needs_tesseract = pytest.mark.skipif(
    not ocr.available(), reason="Tesseract is not installed here")


@needs_tesseract
def test_it_reads_real_text_from_a_rendered_image(tmp_path):
    from PIL import Image, ImageDraw, ImageFont

    image = Image.new("L", (900, 160), 255)
    draw = ImageDraw.Draw(image)
    draw.text((20, 40), "Reading rhetorically", fill=0,
              font=ImageFont.load_default(size=64))
    path = tmp_path / "words.png"
    image.save(path)

    text = (ocr.ocr_image(path) or "").lower()

    assert "reading" in text
    assert "rhetorically" in text
