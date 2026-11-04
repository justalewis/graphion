"""Reading what a PDF states about its own structure.

`pdf_ingest` reconstructs a chapter from the geometry of the page, and the
reason is that a PDF knows only where ink sits. That is true of a file with
no structure tree and not true of one with a good tree, and the three ways
of being confidently wrong about the difference are what these hold.

A tree can cover almost nothing, so counting that one exists says nothing
about the chapter. A RoleMap can throw the headings away, so applying it
faithfully reads a chapter as having none. And a tree names roles while
only the page has text, so the two have to be joined on the marked-content
id or the elements come back empty.
"""
import sys
from pathlib import Path

import pypdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import conversion
import structure


CHAPTER = """#set document(title: [A Chapter], author: ("Jane Doe",))
#set text(lang: "en")
= First Impressions

Body text under the first head.

= Implications

Body text under the second head.

== A Subhead

More body text.
"""


def _typst(tmp_path: Path, name: str, source: str) -> Path:
    typ = tmp_path / f"{name}.typ"
    typ.write_text(source, encoding="utf-8")
    out = tmp_path / f"{name}.pdf"
    conversion._compile_typst(typ, out, root=tmp_path)
    return out


@pytest.fixture
def chapter(tmp_path):
    return _typst(tmp_path, "chapter", CHAPTER)


# ---------- the RoleMap throws the headings away ----------

def test_a_flattened_style_keeps_its_level_in_its_numbered_twin():
    """InDesign exports a style that has to map two ways twice, and the
    document uses the one flattened to `/P`. Applying the RoleMap
    faithfully reads a chapter as having no headings at all, which is
    exactly what the richest trees in this archive would come back as."""
    levels = structure.heading_levels({
        "/Chapter_Titles": "/P", "/Chapter_Titles_1": "/H1",
        "/Header_A": "/P", "/Header_A_1": "/H2",
        "/Header_B": "/P", "/Header_B_1": "/H3",
        "/Body_Copy": "/P",
    })

    assert levels["/Chapter_Titles"] == 1
    assert levels["/Header_A"] == 2
    assert levels["/Header_B"] == 3
    assert "/Body_Copy" not in levels


def test_a_style_mapped_straight_to_a_heading_needs_no_twin():
    levels = structure.heading_levels({"/Head": "/H2", "/Body": "/P"})

    assert levels == {"/Head": 2}


def test_a_name_that_merely_ends_in_a_number_is_not_a_twin():
    """`Sidebar_2` is a style of its own wherever `Sidebar` is not one the
    map flattened, and reading it as a twin would promote whatever
    `Sidebar` happens to be."""
    levels = structure.heading_levels({"/Sidebar_2": "/H2"})

    assert levels == {"/Sidebar_2": 2}
    assert "/Sidebar" not in levels


def test_a_stem_that_is_not_flattened_is_left_alone():
    levels = structure.heading_levels({"/Note": "/Span", "/Note_1": "/H3"})

    assert levels == {"/Note_1": 3}


def test_the_level_the_file_states_wins_over_the_map():
    """The style is what the document uses, so a reader has to answer for
    the style and not for what the map turned it into."""
    rolemap = {"/Header_A": "/P", "/Header_A_1": "/H2"}
    levels = structure.heading_levels(rolemap)
    tree = {"/S": "/Document", "/K": [{"/S": "/Header_A", "/K": 0}]}

    elements, _styles = structure.walk(tree, {}, rolemap, levels)

    assert [(e.role, e.style) for e in elements] == [
        ("/Document", "/Document"), ("/H2", "/Header_A")]


# ---------- a tree can cover almost nothing ----------

def test_a_tree_that_covers_the_cover_page_is_not_usable():
    """The Word-exported volumes tag the publisher's boilerplate and leave
    the chapter untouched. A reader that walked the tree and stopped would
    reconstruct a two-paragraph document and report it as the article."""
    outline = structure.Outline(path=Path("x.pdf"), chars=32645,
                                marked_chars=1480, styles={"/Standard": 35})

    assert outline.tagged
    assert outline.coverage < structure.USABLE_COVERAGE
    assert not outline.usable


def test_a_tree_that_covers_the_text_is_usable():
    outline = structure.Outline(path=Path("x.pdf"), chars=54290,
                                marked_chars=53277, styles={"/Body_Copy": 45})

    assert outline.usable


def test_a_file_with_no_tree_is_read_without_an_error(chapter, tmp_path):
    """A plain pypdf round trip leaves the structure tree behind, which is
    the shape a legacy file arrives in and is not a failure to read."""
    writer = pypdf.PdfWriter()
    writer.append(pypdf.PdfReader(str(chapter)))
    stripped = tmp_path / "stripped.pdf"
    with open(stripped, "wb") as handle:
        writer.write(handle)

    outline = structure.read(stripped)

    assert outline.readable
    assert not outline.tagged
    assert not outline.usable
    assert outline.error == ""
    assert outline.headings() == []


def test_a_file_that_will_not_open_says_why(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\nnot really\n")

    outline = structure.read(broken)

    assert not outline.readable
    assert outline.error


# ---------- the tree names roles and only the page has text ----------

def test_the_headings_come_back_in_document_order(chapter):
    outline = structure.read(chapter)

    assert outline.usable
    assert [h.text for h in outline.headings()] == [
        "First Impressions", "Implications", "A Subhead"]


def test_the_levels_come_back_with_them(chapter):
    outline = structure.read(chapter)

    assert [h.role for h in outline.headings()] == ["/H1", "/H1", "/H2"]


def test_reading_without_the_text_leaves_the_coverage_unknown(chapter):
    """The join is most of the cost, and a caller counting roles does not
    need it. What it must not do is report a coverage it never measured,
    which a zero would be."""
    outline = structure.read(chapter, text=False)

    assert outline.tagged
    assert outline.elements
    assert outline.chars == 0
    assert outline.coverage is None
    assert not outline.usable


def test_a_loop_in_the_tree_terminates():
    """A structure tree is shallow and a malformed one is what the depth
    limit is for; a reader pointed at a stranger's archive meets both."""
    inner = {"/S": "/P"}
    outer = {"/S": "/Document", "/K": [inner]}
    inner["/K"] = [outer]

    elements, _styles = structure.walk(outer, {}, {}, {})

    assert [e.style for e in elements] == ["/Document", "/P"]


def test_an_annotation_contributes_no_text():
    """An `/OBJR` names a link annotation, which carries none of its own,
    and following it as though it were content would hand the element the
    text of whatever object it points at."""
    tree = {"/S": "/Link",
            "/K": [{"/Type": "/OBJR", "/Obj": {"/Subtype": "/Link"}}, 7]}

    elements, _styles = structure.walk(tree, {}, {}, {})

    assert [e.style for e in elements] == ["/Link"]
    assert elements[0].mcids == [(None, 7)]
