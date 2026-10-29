"""Unit tests for ingest_volume.py.

The database and filesystem work is covered by running the thing; what is
worth pinning here is the planning, because that decides which file becomes
which chapter and in what order, and a volume ingested in the wrong order
is not obviously wrong until someone reads it.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pypdf import PdfWriter

import ingest_volume as iv


def _dir(tmp_path, *names):
    for n in names:
        (tmp_path / n).write_bytes(b"%PDF-1.4\n")
    return tmp_path


def _pdf(path, pages=1):
    """A real PDF of a given length. The planner reads the page count to tell
    a collected volume from a chapter, so some cases need a readable file
    rather than the stub `_dir` writes."""
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=468, height=648)
    with open(path, "wb") as fh:
        writer.write(fh)
    return path


# ---------- filenames ----------


def test_chapter_number_and_surnames_come_off_the_filename():
    number, names, note = iv.parse_filename(Path("1Lester-Lucas-Doyle-Overcash.pdf"))
    assert number == 1
    assert names == ["Lester", "Lucas", "Doyle", "Overcash"]
    assert "filename" in note


def test_single_author_filename():
    number, names, _ = iv.parse_filename(Path("22Wells.pdf"))
    assert (number, names) == (22, ["Wells"])


def test_front_and_back_matter_are_not_chapters():
    """The archive ships these beside the chapters; they are not chapters,
    and numbering them would shift every real chapter by one."""
    for name in ("Acknowledgments.pdf", "Contributors.pdf", "Index.pdf"):
        number, _, note = iv.parse_filename(Path(name))
        assert number is None
        assert "not a chapter" in note


def test_unrecognised_filename_gets_no_number():
    number, names, note = iv.parse_filename(Path("some-scanned-thing.pdf"))
    assert number is None and names == []
    assert "no chapter number" in note


def test_the_older_convention_gives_a_surname_and_a_title():
    """Volumes 1 and 2 name a chapter for its author and an abbreviated
    title, with no number anywhere in it."""
    number, names, note = iv.parse_filename(Path("bunn--how-to-read.pdf"))
    assert number is None
    assert names == ["Bunn"]
    assert "no chapter number" in note


def test_the_older_convention_handles_two_authors():
    _, names, _ = iv.parse_filename(Path("cecil-lemkin--on-revision.pdf"))
    assert names == ["Cecil", "Lemkin"]


def test_volume_three_names_a_chapter_for_its_author_alone():
    number, names, note = iv.parse_filename(Path("gagich.pdf"))
    assert number is None
    assert names == ["Gagich"]
    assert "no chapter number" in note


def test_a_surname_that_carries_its_own_case_is_left_alone():
    """Capitalizing a lowercased surname is safe. Recasing one that already
    has case is not, because nothing recovers the capital inside McLeod."""
    _, names, _ = iv.parse_filename(Path("21Cecil-Lemkin-Gluck.pdf"))
    assert names == ["Cecil", "Lemkin", "Gluck"]


def test_the_older_convention_drops_the_and_between_two_authors():
    """In "barton-and-klint" the middle token is a word in the filename, not
    a third author."""
    _, names, _ = iv.parse_filename(Path("barton-and-klint--a-students-guide.pdf"))
    assert names == ["Barton", "Klint"]


def test_the_whole_volume_in_one_pdf_is_not_a_chapter():
    """Every folder holds the collected book beside its chapters, and the
    archive has named that file three ways as well."""
    for name in ("writing-spaces-readings-on-writing-vol-1.pdf",
                 "writingspaces3.pdf", "WritingSpaces5.pdf"):
        number, _, note = iv.parse_filename(Path(name))
        assert number is None, name
        assert "not a chapter" in note, name


def test_the_later_volumes_name_their_matter_differently():
    """Volumes 3, 4 and 6 ship "front.pdf" and "editors.pdf" where volume 5
    ships "Frontmatter.pdf"; all of it is matter, and read as a surname it
    would publish as a chapter by Mr Front."""
    for name in ("front.pdf", "editors.pdf"):
        number, _, note = iv.parse_filename(Path(name))
        assert number is None, name
        assert "not a chapter" in note, name


# ---------- planning ----------


def test_chapters_sort_by_number_not_by_filename(tmp_path):
    """Sorted as text, chapter 10 comes before chapter 2."""
    _dir(tmp_path, "1Lester.pdf", "2Wells.pdf", "10Sprouse.pdf", "22Thaiss-Wade.pdf")
    numbers = [c.number for c in iv.plan(tmp_path, {})]
    assert numbers == [1, 2, 10, 22]


def test_unnumbered_files_sort_to_the_end_but_are_kept(tmp_path):
    """Dropping them would silently lose a volume's front matter; the editor
    decides, not the runner."""
    _dir(tmp_path, "2Wells.pdf", "Acknowledgments.pdf", "1Lester.pdf")
    chapters = iv.plan(tmp_path, {})
    assert [c.number for c in chapters] == [1, 2, None]
    assert chapters[-1].pdf.name == "Acknowledgments.pdf"


def test_manifest_overrides_the_filename(tmp_path):
    """The manifest is the one source a person checked, so it wins."""
    _dir(tmp_path, "9DeRise.pdf")
    manifest = {"9DeRise.pdf": {"chapter-number": 3, "title": "A Checked Title",
                                "authors": ["Danielle DeRise"]}}
    chapter = iv.plan(tmp_path, manifest)[0]
    assert chapter.number == 3
    assert chapter.title == "A Checked Title"
    assert chapter.authors == ["Danielle DeRise"]
    assert "manifest" in chapter.note


def test_slug_prefers_the_title_then_the_filename(tmp_path):
    _dir(tmp_path, "1Lester-Lucas.pdf", "2Wells.pdf")
    manifest = {"1Lester-Lucas.pdf": {"title": "We Write Because We Care!"}}
    chapters = iv.plan(tmp_path, manifest)
    assert chapters[0].slug == "we-write-because-we-care"
    assert chapters[1].slug == "2-wells"


def test_explicit_slug_wins_over_both(tmp_path):
    _dir(tmp_path, "1Lester.pdf")
    manifest = {"1Lester.pdf": {"title": "Ignored", "slug": "hand-picked"}}
    assert iv.plan(tmp_path, manifest)[0].slug == "hand-picked"


def test_plan_ignores_non_pdfs(tmp_path):
    _dir(tmp_path, "1Lester.pdf")
    (tmp_path / "notes.txt").write_text("not a chapter", encoding="utf-8")
    assert len(iv.plan(tmp_path, {})) == 1


def test_a_collected_volume_is_planned_but_not_ingested(tmp_path):
    """It stays in the plan so the editor can see it was found, and carries
    the flag that keeps a few hundred pages from becoming one article."""
    _dir(tmp_path, "19Irvin.pdf", "writing-spaces-readings-on-writing-vol-1.pdf")
    by_name = {c.pdf.name: c for c in iv.plan(tmp_path, {})}
    assert by_name["19Irvin.pdf"].skip is False
    assert by_name["writing-spaces-readings-on-writing-vol-1.pdf"].skip is True


def test_a_manifest_entry_overrides_the_decision_to_skip(tmp_path):
    """Naming a file in the manifest is the editor saying they want it,
    whatever its own name looks like to the runner."""
    name = "writing-spaces-readings-on-writing-vol-1.pdf"
    _dir(tmp_path, name)
    chapter = iv.plan(tmp_path, {name: {"chapter-number": 1}})[0]
    assert chapter.skip is False
    assert chapter.number == 1


def test_length_catches_a_volume_whose_name_gives_nothing_away(tmp_path):
    """Volume 6 names its collected book for the volume's own theme,
    "technical.pdf", which reads as a surname and which no filename rule
    reaches. Across the six volumes a chapter runs 5 to 29 pages and a
    collected volume 219 to 410, so length settles it where a name cannot."""
    _pdf(tmp_path / "technical.pdf", pages=358)
    _pdf(tmp_path / "17Acharya.pdf", pages=18)
    by_name = {c.pdf.name: c for c in iv.plan(tmp_path, {})}
    assert by_name["technical.pdf"].skip is True
    assert "358 pages" in by_name["technical.pdf"].note
    assert by_name["17Acharya.pdf"].skip is False


def test_a_pdf_that_will_not_open_stays_in_the_plan(tmp_path):
    """The planner does not judge a file it cannot read. Ingest reports that
    failure against the chapter, naming the file, which is of more use to an
    editor than a file quietly missing from the plan."""
    _dir(tmp_path, "4Zhou.pdf")
    assert iv.page_count(tmp_path / "4Zhou.pdf") is None
    assert iv.plan(tmp_path, {})[0].skip is False


def test_slug_comes_from_the_title_half_of_an_older_filename(tmp_path):
    """The archive already put a usable title in those names, and
    "bunn-how-to-read" would be the worse slug of the two."""
    _dir(tmp_path, "bunn--how-to-read.pdf", "gagich.pdf")
    slugs = {c.pdf.name: c.slug for c in iv.plan(tmp_path, {})}
    assert slugs["bunn--how-to-read.pdf"] == "how-to-read"
    assert slugs["gagich.pdf"] == "gagich"


# ---------- manifest loading ----------


def test_manifest_file_round_trips(tmp_path):
    p = tmp_path / "m.json"
    p.write_text(json.dumps({"1A.pdf": {"title": "T"}}), encoding="utf-8")
    assert iv.load_manifest(p) == {"1A.pdf": {"title": "T"}}


def test_no_manifest_is_an_empty_mapping():
    assert iv.load_manifest(None) == {}


def test_a_manifest_that_is_not_an_object_is_rejected(tmp_path):
    p = tmp_path / "m.json"
    p.write_text("[1, 2, 3]", encoding="utf-8")
    try:
        iv.load_manifest(p)
    except ValueError as exc:
        assert "keyed by PDF filename" in str(exc)
    else:
        raise AssertionError("expected a ValueError")


# ---------- running heads ----------


def test_short_title_cuts_at_the_subtitle():
    """A full title overruns the running head's measure and wraps into the
    margin, which is what short-title exists to prevent."""
    assert iv._short_title("We Write Because We Care: Developing Your Writerly "
                           "Identity") == "We Write Because We Care"


def test_short_authors_uses_surnames_with_a_serial_and():
    authors = [{"name": "Glenn Lester"}, {"name": "Taylor Lucas"},
               {"name": "Sydney Doyle"}]
    assert iv._short_authors(authors) == "Lester, Lucas, and Doyle"


def test_short_authors_handles_one_and_two_names():
    assert iv._short_authors([{"name": "Jennifer Wells"}]) == "Wells"
    assert iv._short_authors([{"name": "Chris Thaiss"},
                              {"name": "Stephanie Wade"}]) == "Thaiss and Wade"


def test_short_authors_of_nothing_is_empty():
    assert iv._short_authors([]) == ""


def test_short_title_of_a_long_title_cuts_at_a_word():
    """With no subtitle to cut at, cutting at the 60th character cut through
    a word, and the result ran as a running head on every page."""
    out = iv._short_title("What Color Is My Voice? Academic Writing and the "
                          "Myth of Standard English")
    assert out == "What Color Is My Voice? Academic Writing and the Myth of"
    assert not out.endswith("Sta")


def test_short_title_of_a_long_title_drops_no_partial_word():
    out = iv._short_title("What Can I Add to Discourse Communities? How "
                          "Writers Use Code-Meshing and Translanguaging")
    assert out == "What Can I Add to Discourse Communities? How Writers Use"
    assert len(out) <= 60


def test_short_title_leaves_a_short_title_whole():
    assert iv._short_title("Enabling the Reader") == "Enabling the Reader"


def test_short_title_keeps_a_word_the_cut_landed_after():
    """The cut falling on the space after a whole word is already a clean
    boundary, so nothing needs dropping; only the comma goes."""
    out = iv._short_title("“Is This for a Grade?” Understanding "
                          "Assessment, Evaluation, and Low-Stakes Writing "
                          "Assignments")
    assert out == "“Is This for a Grade?” Understanding Assessment, Evaluation"
