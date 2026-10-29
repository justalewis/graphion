"""Splitting a chapter's teacher material into its own galley.

A teaching series puts a block addressed to instructors behind its own
title page at the back of each chapter. Rendering it as a second galley
means deciding where the chapter stops, what metadata the second document
carries, and making sure the two renders cannot overwrite each other.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import conversion


CHAPTER = """Opening body text.

# Conclusion

The chapter ends here.

# Works Cited

Doe, Jane. *A Book*. Example Press, 2020.
"""

TEACHER = """# Teacher Resources for "A Chapter"

# Overview and Teaching Strategies

Use this chapter early in the term.

# Discussion Questions

1. A question.
"""


def _write(tmp_path: Path, body: str, **meta):
    fm = {"title": "A Chapter", "short-title": "A Chapter",
          "short-authors": "Doe", "author": [{"name": "Jane Doe"}]}
    fm.update(meta)
    import yaml
    front = yaml.safe_dump(fm, sort_keys=False, allow_unicode=True, width=10_000)
    (tmp_path / "article.md").write_text(f"---\n{front}---\n\n{body}", encoding="utf-8")
    return tmp_path


# ---------- splitting ----------


def test_split_separates_at_the_heading():
    chapter, teacher = conversion.split_teacher_resources(CHAPTER + "\n" + TEACHER)
    assert "Works Cited" in chapter
    assert "Teacher Resources" not in chapter
    assert teacher.startswith("# Teacher Resources")
    assert "Discussion Questions" in teacher


def test_an_article_without_the_section_comes_back_whole():
    """Callers use this unconditionally, so the no-op case has to be safe."""
    chapter, teacher = conversion.split_teacher_resources(CHAPTER)
    assert chapter.strip() == CHAPTER.strip()
    assert teacher == ""


def test_the_heading_is_matched_at_any_level_and_any_case():
    for heading in ("# Teacher Resources", "### teacher resources",
                    "## TEACHER RESOURCES for X"):
        _, teacher = conversion.split_teacher_resources(f"Body.\n\n{heading}\n\nAfter.")
        assert teacher.startswith(heading), heading


def test_a_mention_in_prose_does_not_split():
    """Only a heading splits. The phrase turns up in body prose often."""
    body = "We provide teacher resources at the end of this chapter.\n"
    chapter, teacher = conversion.split_teacher_resources(body)
    assert teacher == ""
    assert chapter.strip() == body.strip()


# ---------- footnotes ----------


def test_a_note_follows_its_reference_into_the_chapter():
    """Markdown lets a definition sit anywhere, so they collect at the end of
    the document, which is behind the teacher material. Splitting there
    handed every chapter note to the teacher galley, where Pandoc reported
    it defined and unused while the chapter lost the note."""
    body = (
        "Body text with a note.[^1]\n\n"
        "# Teacher Resources\n\n"
        "Instructor material.\n\n"
        "[^1]: The licence note.\n"
    )
    chapter, teacher = conversion.split_teacher_resources(body)
    assert "[^1]: The licence note." in chapter
    assert "[^1]:" not in teacher
    assert "Instructor material." in teacher


def test_a_note_referenced_only_by_the_teacher_half_stays_there():
    body = (
        "Body text, no notes.\n\n"
        "# Teacher Resources\n\n"
        "Instructor material.[^a]\n\n"
        "[^a]: A note for instructors.\n"
    )
    chapter, teacher = conversion.split_teacher_resources(body)
    assert "[^a]:" in teacher
    assert "[^a]:" not in chapter


def test_notes_are_sorted_to_whichever_half_refers_to_each():
    body = (
        "Chapter text.[^1]\n\n"
        "# Teacher Resources\n\n"
        "Teaching text.[^2]\n\n"
        "[^1]: First.\n\n"
        "[^2]: Second.\n"
    )
    chapter, teacher = conversion.split_teacher_resources(body)
    assert "[^1]: First." in chapter and "[^2]:" not in chapter
    assert "[^2]: Second." in teacher and "[^1]:" not in teacher


def test_an_unreferenced_note_is_kept_rather_than_dropped():
    """Losing an editor's content is worse than an unused note."""
    body = "Body.\n\n# Teacher Resources\n\nTeaching.\n\n[^9]: Orphan.\n"
    chapter, teacher = conversion.split_teacher_resources(body)
    assert "[^9]: Orphan." in chapter


# ---------- licence ----------


def test_a_body_that_states_its_licence_is_recognised():
    """A published chapter prints its terms itself, and ingest recovers that
    note, so printing the metadata licence as well says it twice."""
    for text in (
        "visit http://creativecommons.org/licenses/by-nc-nd/4.0/",
        "This work is licensed under the Creative Commons Attribution",
        "CC BY-NC-ND 4.0",
        "All rights reserved.",
    ):
        assert conversion.body_states_license(text) is True, text


def test_ordinary_prose_is_not_a_licence_notice():
    for text in ("", "The chapter explores what it means to be a writer.",
                 "Students licensed to drive may park here."):
        assert conversion.body_states_license(text) is False, text


def test_the_licence_prints_only_when_the_body_is_silent():
    fm = {"license": "CC BY-NC-ND 4.0."}
    assert conversion.should_print_license(fm, "Plain body text.") is True
    assert conversion.should_print_license(
        fm, "Body.\n\n[^1]: This work is licensed under CC BY-NC-ND 4.0.") is False


def test_nothing_prints_when_no_licence_is_recorded():
    assert conversion.should_print_license({}, "Plain body text.") is False
    assert conversion.should_print_license({"license": "  "}, "Body.") is False


def test_each_half_is_judged_on_its_own_text():
    """A notice living only in the teacher material must not vouch for a
    chapter that says nothing, or the chapter publishes with no terms."""
    fm = {"license": "CC BY-NC-ND 4.0."}
    body = (
        "Chapter text with no licence notice at all.\n\n"
        "# Teacher Resources\n\n"
        "Instructor material, licensed under CC BY-NC-ND 4.0.\n"
    )
    chapter, teacher = conversion.split_teacher_resources(body)
    assert conversion.should_print_license(fm, chapter) is True
    assert conversion.should_print_license(fm, teacher) is False


# ---------- opt-in ----------


def test_the_split_is_opt_in():
    assert conversion.teacher_resources_separate({}) is False
    assert conversion.teacher_resources_separate({"teacher-resources": "inline"}) is False
    assert conversion.teacher_resources_separate({"teacher-resources": "separate"}) is True
    assert conversion.teacher_resources_separate({"teacher-resources": " Separate "}) is True


def test_sources_are_unsplit_without_the_opt_in(tmp_path):
    _write(tmp_path, CHAPTER + "\n" + TEACHER)
    sources = conversion.part_sources(tmp_path)
    assert set(sources) == {"chapter"}
    assert sources["chapter"].name == "article.md"


def test_sources_split_when_asked(tmp_path):
    _write(tmp_path, CHAPTER + "\n" + TEACHER, **{"teacher-resources": "separate"})
    sources = conversion.part_sources(tmp_path)
    assert set(sources) == {"chapter", "teacher"}
    assert "Teacher Resources" not in sources["chapter"].read_text(encoding="utf-8")
    assert "Discussion Questions" in sources["teacher"].read_text(encoding="utf-8")


def test_asking_for_a_split_with_nothing_to_split_is_not_an_error(tmp_path):
    """An article can be marked before its teacher block is written."""
    _write(tmp_path, CHAPTER, **{"teacher-resources": "separate"})
    assert set(conversion.part_sources(tmp_path)) == {"chapter"}


def test_canonical_article_md_is_never_rewritten(tmp_path):
    """The split writes derived files. article.md is what the editor edits
    and must come through untouched."""
    _write(tmp_path, CHAPTER + "\n" + TEACHER, **{"teacher-resources": "separate"})
    before = (tmp_path / "article.md").read_text(encoding="utf-8")
    conversion.part_sources(tmp_path)
    assert (tmp_path / "article.md").read_text(encoding="utf-8") == before


def test_the_teacher_body_loses_the_heading_that_became_its_title(tmp_path):
    """Leaving it in printed the title twice: once in the title block and
    again as the first heading under it."""
    _write(tmp_path, CHAPTER + "\n" + TEACHER, **{"teacher-resources": "separate"})
    teacher = conversion.part_sources(tmp_path)["teacher"].read_text(encoding="utf-8")
    body = teacher.split("---", 2)[2]
    assert "# Teacher Resources" not in body
    assert body.lstrip().startswith("# Overview and Teaching Strategies")


def test_strip_leading_heading_leaves_a_body_without_one_alone():
    assert conversion._strip_leading_heading("Just prose.\n") == "Just prose.\n"
    assert conversion._strip_leading_heading("# A head\n\nProse.\n") == "Prose.\n"


# ---------- derived metadata ----------


def test_teacher_front_matter_titles_itself():
    out = conversion._teacher_front_matter({"title": "A Chapter"})
    assert out["title"] == "Teacher Resources for “A Chapter”"
    assert out["short-title"] == "Teacher Resources"


def test_teacher_front_matter_drops_what_belongs_to_the_chapter():
    fm = {"title": "A Chapter", "abstract": "An overview.", "chapter-number": 3,
          "start-page": 41, "doi": "10.1234/x", "author": [{"name": "Jane Doe"}],
          "volume-title": "Writing Spaces 5", "teacher-resources": "separate"}
    out = conversion._teacher_front_matter(fm)
    for gone in ("abstract", "chapter-number", "start-page", "doi",
                 "teacher-resources"):
        assert gone not in out, gone
    # What describes the volume and the people stays.
    assert out["author"] == [{"name": "Jane Doe"}]
    assert out["volume-title"] == "Writing Spaces 5"


def test_deriving_does_not_mutate_the_chapter_s_metadata():
    fm = {"title": "A Chapter", "abstract": "An overview."}
    conversion._teacher_front_matter(fm)
    assert fm["abstract"] == "An overview."


# ---------- stale galleys ----------


def test_an_article_that_stops_being_split_loses_its_teacher_galley(tmp_path):
    """The article page offers the teacher galley when the file is there, so
    a stale one sits beside the chapter looking current while the chapter
    now contains that material itself."""
    _write(tmp_path, CHAPTER + "\n" + TEACHER)
    for name in ("teacher-resources.pdf", "teacher-resources.html",
                 ".teacher.md", ".teacher.typ", ".chapter.md"):
        (tmp_path / name).write_bytes(b"stale")

    removed = conversion.clear_stale_parts(tmp_path, conversion.part_sources(tmp_path))

    assert set(removed) == {"teacher-resources.pdf", "teacher-resources.html",
                            ".teacher.md", ".teacher.typ", ".chapter.md"}
    assert not (tmp_path / "teacher-resources.pdf").exists()
    assert (tmp_path / "article.md").exists()


def test_a_split_article_keeps_its_teacher_galley(tmp_path):
    _write(tmp_path, CHAPTER + "\n" + TEACHER, **{"teacher-resources": "separate"})
    (tmp_path / "teacher-resources.pdf").write_bytes(b"current")

    removed = conversion.clear_stale_parts(tmp_path, conversion.part_sources(tmp_path))

    assert removed == []
    assert (tmp_path / "teacher-resources.pdf").exists()


def test_clearing_is_quiet_when_there_is_nothing_to_clear(tmp_path):
    _write(tmp_path, CHAPTER)
    assert conversion.clear_stale_parts(tmp_path, {"chapter"}) == []


# ---------- output paths ----------


def test_each_part_renders_to_its_own_file(tmp_path):
    """Both parts went through one intermediate at first, so whichever
    render ran second overwrote the first one's Typst source."""
    _write(tmp_path, CHAPTER + "\n" + TEACHER, **{"teacher-resources": "separate"})
    _, chapter_out = conversion._part_paths(tmp_path, "chapter", ".pdf")
    _, teacher_out = conversion._part_paths(tmp_path, "teacher", ".pdf")
    assert chapter_out.name == "article.pdf"
    assert teacher_out.name == "teacher-resources.pdf"


def test_asking_for_a_part_that_does_not_exist_says_why(tmp_path):
    _write(tmp_path, CHAPTER)
    try:
        conversion._part_paths(tmp_path, "teacher", ".pdf")
    except ValueError as exc:
        assert "teacher-resources: separate" in str(exc)
    else:
        raise AssertionError("expected a ValueError")
