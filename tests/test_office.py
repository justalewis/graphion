"""Auditing Word and PowerPoint files, and the one thing it must not do.

R5. There is nothing here that fixes a file, and that is the finding. The
777 Office documents first counted across the cartridges were the same
files recurring across exports: 125 distinct .docx, 13 .pptx, 26 .doc and
4 .xlsx. Every .docx already carries a default language, because Word
always writes one, so the fix first planned was a no-op, and what is left
is all content. A picture with no description is words, a table with no
header row is a claim about what the table means, a document with no
Heading styles is a claim about its structure, and a slide with no title
is words. Each is reported and none is guessed.

So the contract here is the inverse of the other passes: every one of
these must return the bytes it was given. Round-tripping a Word file
through a library can silently drop comments, tracked changes and objects
it does not model, and a remediation that returned a changed document with
its review history gone would be worse than the gap it closed.
"""
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import remediate


def _png() -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 100, 50)).save(out, "PNG")
    return out.getvalue()


def _docx(build) -> bytes:
    import docx
    document = docx.Document()
    build(document)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _kinds(result):
    return {o.kind: o for o in result.owed}


# ---------- Word ----------

def test_a_picture_with_no_description_is_owed():
    data = _docx(lambda d: d.add_picture(io.BytesIO(_png())))

    result = remediate.audit_docx(data)

    assert _kinds(result)["image-without-description"].count == 1


def test_a_described_picture_is_not_owed():
    def build(d):
        d.add_picture(io.BytesIO(_png()))
        d.inline_shapes[0]._inline.docPr.set("descr", "An orange square")

    result = remediate.audit_docx(_docx(build))

    assert "image-without-description" not in _kinds(result)


def test_a_picture_marked_decorative_is_not_owed():
    """The author has said it carries nothing a reader needs, which is a
    decision they took and not a gap. Counting it would quote them for it."""
    from lxml import etree

    def build(d):
        d.add_picture(io.BytesIO(_png()))
        doc_pr = d.inline_shapes[0]._inline.docPr
        ext = etree.SubElement(doc_pr, "{http://schemas.openxmlformats.org/"
                               "drawingml/2006/main}extLst")
        item = etree.SubElement(ext, "{http://schemas.openxmlformats.org/"
                                "drawingml/2006/main}ext")
        etree.SubElement(item, "{http://schemas.microsoft.com/office/"
                         "drawing/2017/decorative}decorative").set("val", "1")

    result = remediate.audit_docx(_docx(build))

    assert "image-without-description" not in _kinds(result)


def test_a_table_with_no_header_row_is_reported_and_not_promoted():
    """Which row is the header is a claim about what the table means."""
    data = _docx(lambda d: d.add_table(rows=2, cols=2))

    result = remediate.audit_docx(data)

    assert _kinds(result)["table-without-header-row"].count == 1
    assert result.data == data


def test_a_table_whose_header_row_is_marked_is_not_owed():
    from docx.oxml import OxmlElement

    def build(d):
        table = d.add_table(rows=2, cols=2)
        properties = table.rows[0]._tr.get_or_add_trPr()
        properties.append(OxmlElement("w:tblHeader"))

    assert "table-without-header-row" not in _kinds(
        remediate.audit_docx(_docx(build)))


def test_a_long_document_with_no_headings_is_owed_an_outline():
    def build(d):
        for n in range(60):
            d.add_paragraph(f"Paragraph {n}.")

    result = remediate.audit_docx(_docx(build))

    assert _kinds(result)["no-headings"].count == 1


def test_a_short_handout_does_not_need_an_outline():
    result = remediate.audit_docx(_docx(lambda d: d.add_paragraph("Hi.")))

    assert "no-headings" not in _kinds(result)


def test_a_long_document_with_headings_is_not_owed_one():
    def build(d):
        d.add_heading("One", 1)
        for n in range(60):
            d.add_paragraph(f"Paragraph {n}.")

    assert "no-headings" not in _kinds(remediate.audit_docx(_docx(build)))


def test_a_missing_title_is_owed_and_a_real_one_is_not():
    without = remediate.audit_docx(_docx(lambda d: None))

    def titled(d):
        d.core_properties.title = "Reading Rhetorically"

    assert "office-no-title" in _kinds(without)
    assert "office-no-title" not in _kinds(remediate.audit_docx(_docx(titled)))


def test_a_converters_filename_is_not_a_title_in_a_document_either():
    """The same Microsoft Word - <filename> that 204 of the PDFs carried."""
    def titled(d):
        d.core_properties.title = "Microsoft Word - research 2.docx"

    assert "office-no-title" in _kinds(remediate.audit_docx(_docx(titled)))


def test_a_word_file_is_returned_byte_for_byte():
    """Round-tripping can drop comments and tracked changes. The file is
    copied through untouched, so its review history cannot go missing."""
    data = _docx(lambda d: d.add_picture(io.BytesIO(_png())))

    assert remediate.audit_docx(data).data == data


def test_a_docx_that_will_not_open_is_reported_and_left_alone():
    result = remediate.audit_docx(b"not a zip")

    assert result.error
    assert result.data == b"not a zip"


# ---------- what a description is ----------

@pytest.mark.parametrize("text", [
    "", "vrgraphicnovel.png", "rhetorical-situation-4.jpg",
    "/tmp/beautiful_ai_exports/85c18576-4c8b-4b61-88d6-53461ecbbd77.jpg",
    "Picture 3", "image1", "Graphic",
])
def test_a_filename_or_placeholder_is_not_a_description(text):
    """Calibrated on the real files, and it reversed the first measurement.
    Of 151 pictures carrying a description across the distinct Office files
    here, 4 were empty and 108 were a filename, a path or a bare "Picture
    3". Counting presence said 13 of 50 were undescribed; counting meaning
    says nearly all are."""
    assert remediate.looks_like_a_placeholder_description(text)


@pytest.mark.parametrize("text", [
    "collage of magazine clippings",
    "An orange square",
    "Here is an example of a worksheet you can use to take double-entry notes",
])
def test_a_sentence_about_the_picture_is_taken_as_a_description(text):
    assert not remediate.looks_like_a_placeholder_description(text)


def test_microsofts_generated_text_is_recognised():
    assert remediate.is_machine_description(
        "A diagram of a diagram of a diagram&#xA;&#xA;Description "
        "automatically generated")
    assert not remediate.is_machine_description("A diagram of a process")


def _with_descr(text):
    def build(d):
        d.add_picture(io.BytesIO(_png()))
        d.inline_shapes[0]._inline.docPr.set("descr", text)
    return _docx(build)


def test_a_filename_description_is_owed_as_missing():
    result = remediate.audit_docx(_with_descr("IMG_2223 (1).png"))

    assert _kinds(result)["image-without-description"].count == 1


def test_a_machine_written_description_is_owed_review_and_not_called_missing():
    """Present, so no checker flags it, and often wrong: one real file
    reads "A diagram of a diagram of a diagram". A description nobody
    wrote and nobody vouched for is worse than a marked gap, so it is
    reported on its own and never counted as a gap closed."""
    result = remediate.audit_docx(
        _with_descr("A diagram of a diagram&#xA;Description automatically "
                    "generated"))

    kinds = _kinds(result)
    assert kinds["image-description-machine-written"].count == 1
    assert "image-without-description" not in kinds


def test_a_real_description_is_owed_nothing():
    kinds = _kinds(remediate.audit_docx(_with_descr("An orange square")))

    assert "image-without-description" not in kinds
    assert "image-description-machine-written" not in kinds


# ---------- PowerPoint ----------

def _pptx(build) -> bytes:
    import pptx
    deck = pptx.Presentation()
    build(deck)
    out = io.BytesIO()
    deck.save(out)
    return out.getvalue()


def test_a_slide_with_no_title_is_owed_one():
    def build(deck):
        deck.slides.add_slide(deck.slide_layouts[6])  # blank

    result = remediate.audit_pptx(_pptx(build))

    assert _kinds(result)["slide-without-title"].count == 1


def test_a_slide_with_a_title_placeholder_is_not():
    def build(deck):
        slide = deck.slides.add_slide(deck.slide_layouts[5])  # title only
        slide.shapes.title.text = "Week one"

    assert "slide-without-title" not in _kinds(
        remediate.audit_pptx(_pptx(build)))


def test_a_slide_picture_with_no_description_is_owed():
    def build(deck):
        slide = deck.slides.add_slide(deck.slide_layouts[6])
        slide.shapes.add_picture(io.BytesIO(_png()), 0, 0)

    assert _kinds(remediate.audit_pptx(_pptx(build)))[
        "image-without-description"].count == 1


def test_a_presentation_is_returned_byte_for_byte():
    data = _pptx(lambda deck: deck.slides.add_slide(deck.slide_layouts[6]))

    assert remediate.audit_pptx(data).data == data


# ---------- legacy formats ----------

@pytest.mark.parametrize("name, label", [
    ("reading.doc", "Word"), ("deck.ppt", "PowerPoint"),
    ("grades.xls", "Excel"), ("note.rtf", "Rich Text"),
])
def test_a_binary_format_is_reported_and_never_converted(name, label):
    """Converting it would make it checkable, and the conversion renames
    the file, so every reference to it inside the cartridge would point at
    a name that no longer exists. A remediation that broke the links it
    was trying to make usable would be worse than the gap."""
    result = remediate.audit_legacy(b"\xd0\xcf\x11\xe0", name=name)

    owed = _kinds(result)["legacy-format"]
    assert label in owed.detail
    assert "renames it" in owed.detail
    assert result.data == b"\xd0\xcf\x11\xe0"


# ---------- inside a cartridge ----------

def test_a_cartridge_with_office_files_ships_them_untouched_and_lists_the_gaps(
        tmp_path):
    import repack
    manifest = ('<?xml version="1.0"?><manifest xmlns="http://www.imsglobal'
                '.org/xsd/imsccv1p1/imscp_v1p1"/>')
    word = _docx(lambda d: d.add_table(rows=2, cols=2))
    deck = _pptx(lambda d: d.slides.add_slide(d.slide_layouts[6]))
    path = tmp_path / "c.imscc"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("imsmanifest.xml", manifest)
        z.writestr("web_resources/reading.docx", word)
        z.writestr("web_resources/deck.pptx", deck)
        z.writestr("web_resources/old.doc", b"\xd0\xcf\x11\xe0")
    dst = tmp_path / "out.imscc"

    report = repack.remediate_cartridge(path, dst, language="en")

    with zipfile.ZipFile(dst) as z:
        assert z.read("web_resources/reading.docx") == word
        assert z.read("web_resources/deck.pptx") == deck
        assert z.read("web_resources/old.doc") == b"\xd0\xcf\x11\xe0"
    kinds = {item["kind"] for item in report.worklist}
    assert {"table-without-header-row", "slide-without-title",
            "legacy-format"} <= kinds
    assert report.changed == 0
    assert report.holds
