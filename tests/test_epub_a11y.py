"""What the EPUB declares about what a reader can do with it.

Pandoc writes an accessibility block of its own and writes the same one for
every file it converts: `alternativeText` whether or not a figure carries a
description, and `accessModeSufficient: textual`, which says a reader who
cannot see the pictures is missing nothing. For a chapter with an
undescribed figure both are false.

That is the failure these tests are mostly about. A missing accessibility
claim leaves a reader to find out for themselves; a false one tells them
the book will work for them, and they find out afterwards. So the cases
below are about what must not be claimed: alternative text for a figure
nobody described, sufficiency for a page of words set as a picture, and
conformance for either.
"""
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import conversion
import epub_a11y

pandoc = pytest.mark.skipif(
    shutil.which("pandoc") is None, reason="Pandoc is not on PATH")

DESCRIBED = "![A rectangle in burnt orange](assets/one.png)"
PLACEHOLDER = "![Undescribed figure from page 4 of the source](assets/two.png)"
EQUATION = "An equation, $a^2 + b^2 = c^2$, in a sentence."

# The least a package document has to be for the stamp to work on it, laid
# out the way Pandoc lays one out.
OPF = """<?xml version="1.0" encoding="UTF-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="epub-id-1">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>A Chapter</dc:title>
    <dc:language>en</dc:language>
    <meta property="dcterms:modified">2026-01-01T00:00:00Z</meta>
    <meta property="schema:accessMode">textual</meta>
    <meta property="schema:accessModeSufficient">textual</meta>
    <meta property="schema:accessibilityFeature">alternativeText</meta>
    <meta property="schema:accessibilityHazard">none</meta>
  </metadata>
  <manifest/>
  <spine/>
</package>
"""

CONTAINER = """<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="EPUB/content.opf"
    media-type="application/oebps-package+xml"/></rootfiles>
</container>
"""


@pytest.fixture
def epub(tmp_path):
    """A minimal EPUB carrying Pandoc's own accessibility block."""
    path = tmp_path / "article.epub"
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip",
                   compress_type=zipfile.ZIP_STORED)
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("EPUB/content.opf", OPF)
        z.writestr("EPUB/text/ch001.xhtml", "<html><body><p>Body.</p></body></html>")
    return path


# ---------- what must not be claimed ----------

def test_an_undescribed_figure_withholds_the_alternative_text_claim():
    """Pandoc asserts `alternativeText` for every file it converts. A
    chapter with a figure nobody has described has not got it."""
    claim = epub_a11y.describe({}, DESCRIBED + "\n\n" + PLACEHOLDER)

    assert "alternativeText" not in claim.features
    assert "structuralNavigation" in claim.features
    assert claim.conforms_to is None


def test_words_set_as_a_picture_make_text_alone_insufficient():
    """A description of a page of text is not the text. `accessModeSufficient:
    textual` would tell a reader who cannot see it that they are missing
    nothing, and they would be missing the words."""
    claim = epub_a11y.describe({"images-of-text": ["Figure 1"]}, DESCRIBED)

    assert claim.sufficient == ["textual,visual"]
    assert "alternativeText" in claim.features
    assert claim.conforms_to is None


def test_a_described_figure_without_text_in_it_leaves_text_sufficient():
    claim = epub_a11y.describe({}, DESCRIBED)

    assert claim.sufficient == ["textual"]
    assert claim.access_modes == ["textual", "visual"]
    assert "alternativeText" in claim.features


def test_mathml_names_the_markup_and_the_reading_is_a_separate_question():
    """`MathML` says the formulas are marked up so a screen reader can walk
    them, which Pandoc's EPUB writer does either way. Whether one also
    carries a reading somebody wrote is what the conformance claim turns
    on. `math_alt` declines a tilde, since it reads "is similar to" in
    geometry and "is distributed as" in statistics.
    """
    assert "MathML" in epub_a11y.describe({}, EQUATION).features
    assert epub_a11y.describe({}, EQUATION).conforms_to == epub_a11y.CONFORMS_TO

    undescribed = epub_a11y.describe({}, r"A relation, $x \sim y$, holds.")

    assert "MathML" in undescribed.features
    assert undescribed.conforms_to is None
    assert "no spoken description" in undescribed.summary


def test_an_unreadable_character_withholds_the_conformance_claim():
    body = DESCRIBED + "\n\nA private use codepoint: ."

    claim = epub_a11y.describe({}, body)

    assert claim.conforms_to is None
    assert "no meaning outside the font" in claim.summary


# ---------- what may be claimed ----------

def test_a_clean_article_claims_conformance_and_names_who_says_so(tmp_path):
    claim = epub_a11y.describe({}, DESCRIBED, certifier="Writing Spaces")

    assert claim.conforms_to == epub_a11y.CONFORMS_TO
    assert claim.certified_by == "Writing Spaces"


def test_a_claim_with_nobody_behind_it_names_nobody():
    """`a11y:certifiedBy` is who stands behind the claim, so it is written
    only where there is somebody to name."""
    claim = epub_a11y.describe({}, DESCRIBED)

    assert claim.conforms_to == epub_a11y.CONFORMS_TO
    assert claim.certified_by is None
    assert "a11y:certifiedBy" not in claim.as_meta()


def test_an_article_with_no_figures_says_so_rather_than_claiming_visually():
    claim = epub_a11y.describe({}, "# A Chapter\n\nProse only.")

    assert claim.access_modes == ["textual"]
    assert "alternativeText" not in claim.features
    assert "no figures" in claim.summary


# ---------- the summary is read by people ----------

def test_the_summary_says_what_is_not_true():
    claim = epub_a11y.describe({"images-of-text": ["Figure 1", "Figure 2"]},
                               DESCRIBED + "\n\n" + PLACEHOLDER)

    assert "1 of 2 figure(s) carry a written description" in claim.summary
    assert "will miss what they show" in claim.summary
    assert "2 figure(s) set text as a picture" in claim.summary


# ---------- writing it into the package ----------

def test_pandoc_defaults_are_replaced_rather_than_joined(epub):
    """Two `accessModeSufficient` values, one saying textual is enough and
    one saying it is not, is worse than either alone."""
    claim = epub_a11y.describe({"images-of-text": ["Figure 1"]}, DESCRIBED)

    assert epub_a11y.stamp(epub, claim) is True

    found = epub_a11y.read_claim(epub)
    assert found["schema:accessModeSufficient"] == ["textual,visual"]
    assert found["schema:accessibilityFeature"].count("alternativeText") == 1
    assert found["dcterms:modified"]  # Pandoc's own metadata is left alone


def test_stamping_twice_leaves_one_copy(epub):
    claim = epub_a11y.describe({}, DESCRIBED, certifier="A Journal")
    epub_a11y.stamp(epub, claim)
    first = epub_a11y.read_claim(epub)
    epub_a11y.stamp(epub, claim)

    assert epub_a11y.read_claim(epub) == first


def test_the_mimetype_stays_first_and_uncompressed(epub):
    """What a reading system looks at before it trusts anything else in the
    container. A rewrite that deflates it produces a file that opens
    nowhere, and no other test would notice."""
    epub_a11y.stamp(epub, epub_a11y.describe({}, DESCRIBED))

    with zipfile.ZipFile(epub) as z:
        first = z.infolist()[0]
        assert first.filename == "mimetype"
        assert first.compress_type == zipfile.ZIP_STORED
        assert z.read("mimetype") == b"application/epub+zip"
        assert z.read("EPUB/text/ch001.xhtml").startswith(b"<html>")


def test_a_file_with_no_package_document_is_declined(tmp_path):
    broken = tmp_path / "broken.epub"
    with zipfile.ZipFile(broken, "w") as z:
        z.writestr("mimetype", "application/epub+zip")

    assert epub_a11y.stamp(broken, epub_a11y.Claim()) is False


# ---------- the galley has to carry what it declares ----------

@pandoc
def test_the_epub_carries_the_figures_it_claims_to_have(tmp_path):
    """An EPUB packages what it references, and Pandoc resolves a relative
    resource path against the working directory rather than against the
    file it is reading. Without `--resource-path` every figure was dropped
    with a warning on stderr, so the galley declared `accessMode: visual`
    over a file holding no pictures at all and the prose went on saying
    "see Figure 1".
    """
    import conversion

    article = tmp_path / "an-article"
    (article / "assets").mkdir(parents=True)
    from PIL import Image
    Image.new("RGB", (240, 160), (200, 120, 60)).save(article / "assets" / "one.png")
    (article / "article.md").write_text(
        "---\ntitle: A Chapter\n---\n\n# A Heading\n\n"
        "Prose above the figure.\n\n"
        "![A rectangle in burnt orange](assets/one.png)\n",
        encoding="utf-8")

    out = conversion.render_epub(article, "writing-spaces")

    with zipfile.ZipFile(out) as z:
        images = [n for n in z.namelist() if n.lower().endswith(".png")]
    assert images, "the figure was not packaged"

    found = epub_a11y.read_claim(out)
    assert "visual" in found["schema:accessMode"]
    assert "alternativeText" in found["schema:accessibilityFeature"]


# ---------- a container may not reach outside itself ----------

def test_a_remote_import_is_taken_out_for_the_epub():
    """Both bundles import EB Garamond from Google Fonts, which is right
    for the HTML galley and invalid in a container: epubcheck reports
    RSC-006, "Remote resource reference is not allowed in this context".
    Found by the fifth register kind on its first run, because the HTML
    galley fetches the font and the PDF never sees this stylesheet.
    """
    css = ("@import url('https://fonts.googleapis.com/css2?family=X');\n"
           "body { color: #141414; }\n")

    out, removed = conversion.stylesheet_for_epub(css)

    assert removed == 1
    assert "fonts.googleapis" not in out
    assert "body { color: #141414; }" in out


def test_a_relative_import_is_left_alone():
    """It names a file Pandoc carries into the container, so removing it
    would take a stylesheet the EPUB actually has."""
    css = "@import url('fonts.css');\nbody { color: #000; }\n"

    out, removed = conversion.stylesheet_for_epub(css)

    assert removed == 0
    assert "fonts.css" in out


def test_a_remote_font_face_is_not_touched():
    """A different rule, which these bundles do not use. Reaching for one
    nobody has written is how a cleanup pass starts removing what nobody
    asked it to."""
    css = ("@font-face { font-family: X; src: url(https://e.com/x.woff2); }\n"
           "body { color: #000; }\n")

    out, removed = conversion.stylesheet_for_epub(css)

    assert removed == 0
    assert "e.com/x.woff2" in out


def test_nothing_else_in_the_stylesheet_moves():
    """The count of rules is the cheap check that a pattern meant for one
    line has not eaten a block."""
    for bundle in sorted(Path("content/journals").glob("*/template")):
        css_path = bundle / "article.css"
        if not css_path.exists():
            continue
        css = css_path.read_text(encoding="utf-8")
        out, _removed = conversion.stylesheet_for_epub(css)
        assert out.count("{") == css.count("{"), bundle.parent.name


def test_both_bundles_currently_carry_one():
    """A measured fact rather than an assumption: every EPUB either
    journal produced was invalid for this until it was stripped."""
    found = {}
    for bundle in sorted(Path("content/journals").glob("*/template")):
        css_path = bundle / "article.css"
        if css_path.exists():
            _out, removed = conversion.stylesheet_for_epub(
                css_path.read_text(encoding="utf-8"))
            found[bundle.parent.name] = removed
    assert found, "no bundles found"
    assert all(n >= 1 for n in found.values()), found
