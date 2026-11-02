"""Reading a PDF to say what remediating it would take.

Two things carry the weight here. The reading has to tell work already
done from work still owed, because a report that counted every raster as
a description to write would quote a journal for its own back catalogue.
And the pass has to write nothing: it is pointed at a folder someone sent,
before any agreement exists, and an assessment that left article
directories behind would be the last one anyone asked for.
"""
import shutil
import sys
from pathlib import Path

import pypdf
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assess
import conversion


def _png(path: Path, size=(200, 140)) -> Path:
    from PIL import Image

    Image.new("RGB", size, (200, 120, 60)).save(path)
    return path


def _typst(tmp_path: Path, name: str, source: str) -> Path:
    typ = tmp_path / f"{name}.typ"
    typ.write_text(source, encoding="utf-8")
    out = tmp_path / f"{name}.pdf"
    conversion._compile_typst(typ, out, root=tmp_path)
    return out


DESCRIBED = """#set document(title: [A Described Chapter], author: ("Jane Doe",))
#set text(lang: "en")
= A Heading

Body text above the figure.

#figure(image("fig.png", alt: "A rectangle in burnt orange"),
        caption: [Figure 1. A caption, which is not a description.])
"""

UNDESCRIBED = """#set document(title: [An Undescribed Chapter], author: ("J D",))
#set text(lang: "en")
= A Heading

Body text above the figure.

#figure(image("fig.png"), caption: [Figure 1. A caption.])
"""

PLAIN = """#set document(title: [A Plain Chapter], author: ("Jane Doe",))
#set text(lang: "en")
= A Heading

Body text, carrying no figure at all.
"""


@pytest.fixture
def described(tmp_path):
    _png(tmp_path / "fig.png")
    return _typst(tmp_path, "described", DESCRIBED)


# ---------- conformance as the file states it ----------

def test_a_conformant_galley_reads_as_conformant(described):
    result = assess.assess_pdf(described)

    assert result.readable
    assert result.conformant
    assert result.tagged
    assert result.declared_ua_part == 1
    assert result.xmp_title == "A Described Chapter"
    assert result.lang == "en"


def test_the_light_reading_agrees_with_the_full_one(described):
    """One reader, two entry points.

    `read_declaration` is this module's reading of a file's own conformance
    claim without the page-by-page counting that follows it, because a
    rendered galley has to be asked that question often and the rest of the
    pass costs real time. Keeping them in step is the point: a second copy
    of a conformance reading drifts from the first, which is why
    `_UA_PART_RE` is written here and not in three places.
    """
    light = assess.read_declaration(described)
    full = assess.assess_pdf(described)

    for field in ("readable", "pages", "tagged", "declared_ua_part",
                  "xmp_title", "info_title", "lang", "display_doctitle"):
        assert getattr(light, field) == getattr(full, field), field
    assert light.conformant == full.conformant


def test_the_light_reading_names_a_file_that_will_not_open(tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a PDF")

    result = assess.read_declaration(broken)

    assert result.readable is False
    assert result.error
    assert result.conformant is False


def test_an_untagged_copy_reads_as_needing_work(described, tmp_path):
    """A plain pypdf round trip is the fixture, because that is the defect.

    Adding a page to a writer copies the page and leaves the structure
    tree, the parent tree and /MarkInfo behind, which is how every bound
    issue in this archive came out untagged while its parts passed. The
    same operation makes a legacy-shaped file to read.
    """
    writer = pypdf.PdfWriter()
    writer.append(pypdf.PdfReader(str(described)))
    stripped = tmp_path / "stripped.pdf"
    with open(stripped, "wb") as handle:
        writer.write(handle)

    result = assess.assess_pdf(stripped)

    assert result.readable
    assert not result.conformant
    assert not result.tagged
    assert result.declared_ua_part is None
    assert any("untagged" in note for note in result.notes)


def test_a_file_that_will_not_open_is_reported_by_name(tmp_path):
    """Named rather than raised: one bad file in a folder of 115 must not
    take the assessment down with it."""
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a PDF")

    result = assess.assess_pdf(broken)

    assert result.readable is False
    assert result.error
    assert result.path.name == "broken.pdf"
    assert "will not open" in assess.report([result])


# ---------- work already done against work still owed ----------

def test_a_described_figure_is_not_counted_as_work_owed(described):
    result = assess.assess_pdf(described)

    assert result.figures == 1
    assert result.tagged_figures == 1
    assert result.described_figures == 1
    assert result.undescribed_figures == 0
    assert not any("need a description" in note for note in result.notes)


def test_an_undescribed_figure_is_counted(tmp_path):
    _png(tmp_path / "fig.png")
    pdf = _typst(tmp_path, "undescribed", UNDESCRIBED)

    result = assess.assess_pdf(pdf)

    assert result.figures == 1
    assert result.described_figures == 0
    assert result.undescribed_figures == 1
    assert any("need a description" in note for note in result.notes)


def test_the_caption_is_not_mistaken_for_a_description(tmp_path):
    """Both fixtures caption the figure; only one describes it. A caption
    says what a figure is called and alt text says what is in it."""
    _png(tmp_path / "fig.png")
    undescribed = assess.assess_pdf(_typst(tmp_path, "u", UNDESCRIBED))

    assert undescribed.described_figures == 0


def test_the_structure_tree_decides_where_there_is_one():
    """The reading that was wrong, and the file that showed it.

    Volume 2's `critical-thinking-in-college-writing` tags six figures,
    describes one, and embeds a single raster the scan recognises, the
    other five being vector art or under the size floor. Subtracting the
    described count from the raster count says that chapter owes nothing.
    The tree says it owes five, and the tree is the document speaking
    about itself.
    """
    result = assess.Assessment(path=Path("source.pdf"), figures=1,
                               tagged_figures=6, described_figures=1)

    assert result.undescribed_figures == 5
    assert result.figures_found == 6


def test_an_untagged_file_falls_back_to_the_rasters():
    """Nothing states anything, so every figure found is work."""
    result = assess.Assessment(path=Path("legacy.pdf"), figures=4,
                               tagged_figures=0, described_figures=0)

    assert result.undescribed_figures == 4
    assert result.figures_found == 4


def test_the_count_owed_never_goes_negative():
    """More described than tagged should report nothing owed, not a
    discount against the rest of the volume."""
    result = assess.Assessment(path=Path("x.pdf"), figures=1,
                               tagged_figures=2, described_figures=9)

    assert result.undescribed_figures == 0


def test_a_disagreement_between_the_two_readings_is_reported():
    """Resolved counts hide the disagreement; this one says it out loud,
    because a reader who can see both can check the number."""
    result = assess.Assessment(path=Path("source.pdf"), figures=1,
                               tagged_figures=6, described_figures=1)
    assess._add_notes(result)

    assert any("embedded raster(s) were found" in note
               for note in result.notes)


def test_a_document_with_no_figures_reports_none(tmp_path):
    result = assess.assess_pdf(_typst(tmp_path, "plain", PLAIN))

    assert result.figures == 0
    assert result.undescribed_figures == 0


def test_an_alt_outside_a_figure_is_not_counted_as_a_described_figure(tmp_path):
    """`/Alt` sits on whatever element needs one, equations included since
    `filters/math-alt.lua`, so counting every one would answer a different
    question and inflate what this says is already done."""
    source = """#set document(title: [With Math], author: ("J D",))
#set text(lang: "en")
Inline #[#set math.equation(alt: "x squared"); $x^2$] in a sentence.
"""
    result = assess.assess_pdf(_typst(tmp_path, "math", source))

    assert result.tagged_figures == 0
    assert result.described_figures == 0


# ---------- it writes nothing ----------

def test_assessing_a_folder_leaves_it_exactly_as_it_was(tmp_path):
    """The pass is pointed at a stranger's archive before any agreement
    exists. Ingest is the destructive path; this one must not be."""
    folder = tmp_path / "sent"
    folder.mkdir()
    _png(tmp_path / "fig.png")
    shutil.copy2(_typst(tmp_path, "described", DESCRIBED), folder / "a.pdf")
    shutil.copy2(_typst(tmp_path, "plain", PLAIN), folder / "b.pdf")

    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    results = assess.assess_folder(folder)
    after = {p.name: p.read_bytes() for p in folder.iterdir()}

    assert len(results) == 2
    assert after == before


def test_a_folder_with_no_pdfs_assesses_nothing(tmp_path):
    (tmp_path / "notes.txt").write_text("prose", encoding="utf-8")

    assert assess.assess_folder(tmp_path) == []


def test_the_limit_stops_early(tmp_path):
    _png(tmp_path / "fig.png")
    folder = tmp_path / "many"
    folder.mkdir()
    source = _typst(tmp_path, "plain", PLAIN)
    for name in ("a", "b", "c"):
        shutil.copy2(source, folder / f"{name}.pdf")

    assert len(assess.assess_folder(folder, limit=2)) == 2


# ---------- the report ----------

def test_the_summary_separates_what_is_owed_from_what_was_found(tmp_path):
    _png(tmp_path / "fig.png")
    folder = tmp_path / "vol"
    folder.mkdir()
    shutil.copy2(_typst(tmp_path, "d", DESCRIBED), folder / "a.pdf")
    shutil.copy2(_typst(tmp_path, "u", UNDESCRIBED), folder / "b.pdf")

    text = assess.report(assess.assess_folder(folder))

    assert "1 figure(s) needing a description, of 2 found." in text
    assert "text as a picture" in text


def test_the_report_says_what_it_cannot_know(described):
    """WCAG 1.4.5 is the number that decides whether an archive is done,
    and no reading of the page settles it. A total that left it out would
    read as though the work were smaller than it is."""
    text = assess.report([assess.assess_pdf(described)])

    assert "verapdf" in text


def test_tables_are_not_counted_without_deep(described):
    result = assess.assess_pdf(described)

    assert result.tables is None
    assert any("--deep" in note for note in result.notes)


def test_deep_counts_tables(described):
    result = assess.assess_pdf(described, deep=True)

    assert result.tables is not None
