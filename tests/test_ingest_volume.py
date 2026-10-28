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

import ingest_volume as iv


def _dir(tmp_path, *names):
    for n in names:
        (tmp_path / n).write_bytes(b"%PDF-1.4\n")
    return tmp_path


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
