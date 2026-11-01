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

# An equation is the other thing Typst refuses, and it was the quieter of
# the two: a figure with no alt text fails `lint.check_alt_text` first,
# while nothing looked at math at all.
BARE_MATH = """#set document(title: [A Rendered Galley], author: ("Jane Doe",))
#set text(lang: "en")
Inline $a^2 + b^2 = c^2$ in a sentence.
"""

# What `filters/math-alt.lua` writes around the same equation. The `alt`
# goes on through a set rule in a content block rather than on the call,
# because Pandoc writes the math and the filter only wraps it.
DESCRIBED_MATH = """#set document(title: [A Rendered Galley], author: ("Jane Doe",))
#set text(lang: "en")
Inline #[#set math.equation(alt: "a squared plus b squared equals c \
squared"); $a^2 + b^2 = c^2$] in a sentence.
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


def _alt_texts(pdf_path: Path) -> list:
    """Every /Alt in the structure tree.

    Walked rather than grepped out of the file, because a checker reads the
    tree and a string that happens to sit in the bytes proves nothing about
    what reaches a screen reader.
    """
    reader = pypdf.PdfReader(str(pdf_path))
    root = reader.trailer["/Root"]
    found: list = []
    seen: set = set()

    def walk(node):
        node = node.get_object() if hasattr(node, "get_object") else node
        if isinstance(node, list):
            for kid in node:
                walk(kid)
            return
        if not isinstance(node, dict):
            return
        if id(node) in seen:
            return
        seen.add(id(node))
        if "/Alt" in node:
            found.append(str(node["/Alt"]))
        if "/K" in node:
            walk(node["/K"])

    if "/StructTreeRoot" in root:
        walk(root["/StructTreeRoot"])
    return found


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


def test_an_equation_with_no_alt_text_costs_the_galley_its_conformance(tmp_path):
    """One equation anywhere in an article was enough, and silently.

    Pandoc's Typst writer emits a bare `$...$`, which is this document, so
    before `filters/math-alt.lua` an article with a single formula in it
    rendered through the fallback below and shipped with no conformance
    identifier. Nothing reported it either: `lint.check_alt_text` reads
    Markdown image syntax, and an equation is not an image.
    """
    typ = _write(tmp_path, "baremath.typ", BARE_MATH)
    out = tmp_path / "baremath.pdf"

    assert conversion._compile_typst(typ, out, root=tmp_path) is False

    assert out.exists() and out.stat().st_size > 0
    assert _markers(out)["ua_part"] is None


def test_an_equation_carrying_alt_text_conforms(tmp_path):
    """And the alt reaches the structure tree, which is where a checker
    looks for it; a galley that merely compiled would prove nothing."""
    typ = _write(tmp_path, "describedmath.typ", DESCRIBED_MATH)
    out = tmp_path / "describedmath.pdf"

    assert conversion._compile_typst(typ, out, root=tmp_path) is True

    markers = _markers(out)
    assert markers["ua_part"] == "1"
    assert markers["tagged"] is True
    assert "a squared plus b squared equals c squared" in _alt_texts(out)


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
