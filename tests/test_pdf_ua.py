"""PDF/UA-1 conformance of the Typst compile step.

Two findings drive these tests. Typst writes the conformance identifier,
/Lang, and the ViewerPreferences /DisplayDocTitle entry only when the
standard is asked for, and those last two absences are exactly what an
accessibility audit flags (ISO 14289-1 clause 5, and WCAG 2.4.2 by way of
ISO 7.1-2). Typst also validates the standard instead of merely stamping
it, so content that cannot conform aborts the compile; an editor still has
to get a galley out of that.
"""
import re
import sys
from pathlib import Path

import pypdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import conversion


CLEAN = """#set document(title: [A Rendered Galley], author: ("Jane Doe",))
#set text(lang: "en")
= A Heading

Body text, carrying nothing that needs alt text.
"""

# A figure with no alt text is the one thing most likely to cost a real
# article its conformance, and it needs no image file on disk to reproduce.
NEEDS_ALT = """#set document(title: [A Rendered Galley], author: ("Jane Doe",))
#set text(lang: "en")
#figure(caption: [A caption])[#rect(width: 2cm, height: 1cm)]
"""

BROKEN = """#set document(title: [A Rendered Galley])
#this-function-does-not-exist()
"""

# Nothing wrong with this document but the title it never sets, which is on
# its own enough to cost it the standard.
UNTITLED = """#set text(lang: "en")
= A Heading

Body text, carrying nothing that needs alt text.
"""


def _write(tmp_path: Path, name: str, source: str) -> Path:
    path = tmp_path / name
    path.write_text(source, encoding="utf-8")
    return path


def _markers(pdf_path: Path) -> dict:
    reader = pypdf.PdfReader(str(pdf_path))
    root = reader.trailer["/Root"]
    prefs = root.get("/ViewerPreferences") or {}
    xmp = b""
    if root.get("/Metadata") is not None:
        xmp = root["/Metadata"].get_data()
    part = re.search(rb"pdfuaid:part[^0-9]{0,3}(\d)", xmp)
    return {
        "title": str((reader.metadata or {}).get("/Title") or ""),
        # pypdf hands back its own BooleanObject here, and absent reads the
        # same as false for our purposes: either way no viewer shows a title.
        "display_doctitle": bool(prefs.get("/DisplayDocTitle")),
        "lang": str(root.get("/Lang") or ""),
        "tagged": "/StructTreeRoot" in root,
        "ua_part": part.group(1).decode() if part else None,
    }


def test_clean_document_declares_pdf_ua(tmp_path):
    typ = _write(tmp_path, "clean.typ", CLEAN)
    out = tmp_path / "clean.pdf"

    assert conversion._compile_typst(typ, out, root=tmp_path) is True

    markers = _markers(out)
    assert markers["ua_part"] == "1"
    assert markers["display_doctitle"] is True
    assert markers["title"] == "A Rendered Galley"
    assert markers["lang"] == "en"
    assert markers["tagged"] is True


def test_missing_alt_text_falls_back_to_a_readable_pdf(tmp_path):
    """The editor keeps their galley; it just is not conformant."""
    typ = _write(tmp_path, "noalt.typ", NEEDS_ALT)
    out = tmp_path / "noalt.pdf"

    assert conversion._compile_typst(typ, out, root=tmp_path) is False

    assert out.exists() and out.stat().st_size > 0
    assert _markers(out)["ua_part"] is None


def test_fallback_is_recorded_in_the_conversion_log(tmp_path):
    typ = _write(tmp_path, "noalt.typ", NEEDS_ALT)

    conversion._compile_typst(
        typ, tmp_path / "noalt.pdf", log_to=tmp_path, root=tmp_path
    )

    log = (tmp_path / "conversion.log").read_text(encoding="utf-8")
    assert "PDF/UA" in log
    assert "alt text" in log


def test_a_real_compile_error_still_propagates(tmp_path):
    """Only a PDF/UA complaint earns the fallback; everything else is a bug
    the editor needs to see rather than a silently degraded render."""
    typ = _write(tmp_path, "broken.typ", BROKEN)

    with pytest.raises(Exception) as excinfo:
        conversion._compile_typst(typ, tmp_path / "broken.pdf", root=tmp_path)

    assert "PDF/UA" not in str(excinfo.value)


def test_a_document_with_no_title_is_tagged_and_not_conformant(tmp_path):
    """The failure mode that is easiest to miss, because the galley looks fine.

    Typst tags the content either way, so the PDF has a structure tree and
    reads correctly; it simply carries no conformance identifier and no
    dc:title, and ISO 14289-1 clause 5 reads both. Nothing fails loudly.
    """
    typ = _write(tmp_path, "untitled.typ", UNTITLED)
    out = tmp_path / "untitled.pdf"

    assert conversion._compile_typst(typ, out, root=tmp_path) is False

    markers = _markers(out)
    assert markers["tagged"] is True
    assert markers["ua_part"] is None
    assert markers["title"] == ""


def test_the_issue_front_matter_sets_a_document_title(tmp_path, monkeypatch):
    """The front matter is a part of the bound issue, so its conformance is.

    It set no title for six volumes, which is why every assembled issue held
    three roman-numbered pages that claimed nothing; a merge can carry no
    more conformance than the parts it binds. The journal record here is as
    bare as one can be, because the title has to come from the issue's own
    volume and number rather than from anything an editor filled in.
    """
    monkeypatch.setattr(conversion, "CONTENT_DIR", tmp_path)
    issue = {"volume": 1, "issue_number": 1, "year": 2010,
             "title": "Readings on Writing", "journal_name": "Writing Spaces"}
    journal = {"name": "Writing Spaces", "short_name": "Writing Spaces"}

    out_pdf = conversion.render_front_matter(issue, journal, [], None, tmp_path)

    source = (tmp_path / "_front_matter.typ").read_text(encoding="utf-8")
    assert "#set document(title:" in source
    markers = _markers(out_pdf)
    assert markers["title"] == (
        "Writing Spaces 1.1: Readings on Writing (front matter)")
    assert markers["ua_part"] == "1"
    assert markers["display_doctitle"] is True
    assert markers["tagged"] is True


def test_standard_can_be_switched_off(tmp_path, monkeypatch):
    """GRAPHION_PDF_UA_STANDARD empty means render without the standard,
    which is the escape hatch if Typst's validator ever blocks a galley we
    cannot otherwise fix."""
    monkeypatch.setattr(conversion, "PDF_UA_STANDARD", "")
    typ = _write(tmp_path, "clean.typ", CLEAN)
    out = tmp_path / "clean.pdf"

    assert conversion._compile_typst(typ, out, root=tmp_path) is False
    assert _markers(out)["ua_part"] is None
