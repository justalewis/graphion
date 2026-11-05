"""Reading a course cartridge, and proving a remediation changed no words.

Two modules, and the order they are built in is the argument. `cartridge`
screens an incoming export for student work before anything audits it,
and `invariance` is the proof that nothing a later pass does moves a word
of the course. Both exist before any fixing pass, so every pass is held
to them from its first commit.

The screen was not designed from the specification. It was written after
reading the 35 cartridges on this machine and finding that four of them
carry a transcript of a student introducing herself by name, inside
`course_settings/media_tracks.xml`, in a set of exports that a check over
filenames alone reads as completely clean.
"""
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cartridge
import invariance


MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="g1" xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1">
  <organizations/><resources/>
</manifest>
"""

EMPTY_TRACKS = """<?xml version="1.0" encoding="UTF-8"?>
<media_tracks xmlns="http://canvas.instructure.com/xsd/cccv1p0">
</media_tracks>
"""

# Shaped like the real thing, with the words replaced. The point of the
# fixture is the container, not the speech.
FULL_TRACKS = """<?xml version="1.0" encoding="UTF-8"?>
<media_tracks xmlns="http://canvas.instructure.com/xsd/cccv1p0">
  <media identifierref="gaaa">
    <track kind="subtitles" locale="en" identifierref="gbbb">1
00:00:00,540 --&gt; 00:00:05,400
Hello, my name is a student and this is my reflection

2
00:00:05,400 --&gt; 00:00:08,880
for the first assignment of the term
</track>
  </media>
</media_tracks>
"""

PAGE = (b"<html><head><title>A page</title></head><body>"
        b"<h1>Reading rhetorically</h1>"
        b"<p>A writer chooses a form before choosing a sentence.</p>"
        b"</body></html>")


def _cartridge(tmp_path, members, name="course.imscc"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("imsmanifest.xml", MANIFEST)
        for inner, body in members.items():
            z.writestr(inner, body)
    return path


# ---------- opening one ----------

def test_a_zip_that_is_not_a_cartridge_is_named_rather_than_raised(tmp_path):
    """A folder of PDFs somebody renamed is not an error worth a
    traceback; it is a thing to say plainly."""
    path = tmp_path / "notacourse.imscc"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("readme.txt", "just some files")

    result = cartridge.screen_file(path)

    assert not result.clear
    assert "not a course export" in result.error


def test_a_damaged_zip_is_reported(tmp_path):
    path = tmp_path / "broken.imscc"
    path.write_bytes(b"this is not a zip at all")

    result = cartridge.screen_file(path)

    assert not result.clear
    assert "zip" in result.error.lower()


def test_an_unreadable_cartridge_is_not_clear(tmp_path):
    """Nothing was screened, and a pass that could not look is not a pass
    that found nothing. Same rule `register.UNRUN` exists for."""
    path = tmp_path / "broken.imscc"
    path.write_bytes(b"nope")

    assert cartridge.screen_file(path).clear is False


def test_the_inventory_counts_by_what_will_read_the_file(tmp_path):
    path = _cartridge(tmp_path, {
        "wiki_content/one.html": PAGE,
        "wiki_content/two.html": PAGE,
        "web_resources/reading.pdf": b"%PDF-1.4 ...",
        "web_resources/slides.pptx": b"PK\x03\x04",
        "course_settings/module_meta.xml": "<modules/>",
    })

    with cartridge.open_cartridge(path) as c:
        counts = c.inventory()

    assert counts["page"] == 2
    assert counts["pdf"] == 1
    assert counts["slides"] == 1
    # The manifest and the Canvas XML are both metadata.
    assert counts["metadata"] == 2


# ---------- the screen ----------

def test_a_course_with_no_student_work_screens_clear(tmp_path):
    path = _cartridge(tmp_path, {
        "wiki_content/syllabus.html": PAGE,
        "course_settings/media_tracks.xml": EMPTY_TRACKS,
        "course_settings/module_meta.xml": "<modules><module/></modules>",
    })

    result = cartridge.screen_file(path)

    assert result.clear
    assert result.findings == []
    assert result.read == 4


def test_a_caption_transcript_is_found_where_a_filename_check_sees_nothing(
        tmp_path):
    """The case this screen exists for. Canvas keeps caption tracks inline
    in `course_settings/media_tracks.xml` rather than as `.vtt` files, so
    a cartridge reads as having no captions at all while carrying a full
    transcript of somebody speaking. Four of the 35 exports on this
    machine are in exactly that state, and every one of them passes a
    check written over paths."""
    path = _cartridge(tmp_path, {
        "course_settings/media_tracks.xml": FULL_TRACKS,
        "wiki_content/page.html": PAGE,
    })

    result = cartridge.screen_file(path)

    assert not result.clear
    found = result.of_kind("caption-transcript")
    assert len(found) == 1
    assert found[0].where.endswith("media_tracks.xml")
    assert found[0].count == 1
    assert "2 cues" in found[0].detail


def test_the_screen_reports_the_container_and_never_the_content(tmp_path):
    """A tool that answers "is there student data here?" by printing the
    student data is not a safeguard."""
    path = _cartridge(tmp_path, {
        "course_settings/media_tracks.xml": FULL_TRACKS,
    })

    result = cartridge.screen_file(path)
    said = " ".join(f.where + " " + f.detail for f in result.findings)

    assert "my name is a student" not in said
    assert "reflection" not in said
    assert "00:00:00" not in said


def test_an_empty_track_list_is_not_a_finding(tmp_path):
    """30 of the 35 cartridges here ship `media_tracks.xml` with nothing
    in it. Reporting those would bury the four that matter."""
    path = _cartridge(tmp_path, {
        "course_settings/media_tracks.xml": EMPTY_TRACKS,
    })

    assert cartridge.screen_file(path).clear


def test_a_path_that_names_student_work_is_found(tmp_path):
    path = _cartridge(tmp_path, {
        "web_resources/What is Writing/student_example_2.docx": b"PK\x03\x04",
    })

    result = cartridge.screen_file(path)

    found = result.of_kind("named-for-student-work")
    assert len(found) == 1
    assert "student_example_2.docx" in found[0].where


def test_fields_canvas_writes_about_people_are_found(tmp_path):
    path = _cartridge(tmp_path, {
        "course_settings/whatever.xml":
            "<r><user_id>99</user_id><submitted_at>2026</submitted_at></r>",
    })

    found = cartridge.screen_file(path).of_kind("person-fields")

    assert len(found) == 1
    assert found[0].count == 2
    assert "user_id" in found[0].detail


def test_screening_extracts_nothing_to_disk(tmp_path):
    """`assess.py` keeps its no-write contract because a pass over a
    stranger's folder has to leave the folder alone. This is the same
    promise one level down: a screen that stops on student data leaves
    nothing behind to clean up."""
    path = _cartridge(tmp_path, {
        "course_settings/media_tracks.xml": FULL_TRACKS,
        "wiki_content/page.html": PAGE,
    })
    before = sorted(p.name for p in tmp_path.iterdir())

    cartridge.screen_file(path)

    assert sorted(p.name for p in tmp_path.iterdir()) == before


# ---------- the proof that no word moved ----------

def test_whitespace_is_not_language():
    assert invariance.normalise("  a   b \n c ") == "a b c"


def test_case_is_language():
    """"US" and "us" are different words, and a pass that changed one to
    the other should fail rather than be smoothed over."""
    assert invariance.digest(invariance.normalise("US")) != \
        invariance.digest(invariance.normalise("us"))


def test_a_format_with_no_text_to_read_answers_none_and_not_empty():
    """None and "" are different answers. An empty string is a file that
    was read and holds no text, which is a fact about the file; None is a
    file nothing here can read, which is a fact about this module."""
    assert invariance.text_of("a.png", b"\x89PNG") is None
    assert invariance.text_of("a.html", b"<html><body></body></html>") == ""


def test_a_file_that_will_not_parse_is_unread_rather_than_unchanged():
    assert invariance.text_of("broken.pdf", b"not a pdf") is None


@pytest.mark.parametrize("label, edit, caught", [
    ("a word reworded", lambda d: d.replace(b"chooses", b"picks"), True),
    ("a sentence deleted", lambda d: d.replace(
        b"<p>A writer chooses a form before choosing a sentence.</p>", b""),
     True),
    ("whitespace moved", lambda d: d.replace(b"<p>", b"\n\n   <p>"), False),
    ("a lang attribute added", lambda d: d.replace(
        b"<html>", b'<html lang="en">'), False),
    ("an alt attribute added", lambda d: d.replace(
        b"<h1>", b'<img src="x.png" alt="a photograph of a desk"><h1>'),
     False),
    ("a heading level normalised", lambda d: d.replace(b"h1>", b"h2>"), False),
])
def test_content_changes_fail_and_remediation_passes(label, edit, caught):
    """The whole contract in one table. Everything remediation is allowed
    to add lives in an attribute, in metadata, or in structure, so none of
    it is visible text; rewording or dropping a sentence is."""
    before = invariance.text_of("p.html", PAGE)
    after = invariance.text_of("p.html", edit(PAGE))

    assert (before != after) is caught, label


def test_a_removed_file_fails_the_check():
    """Dropping a reading from a course is the loudest possible change to
    its content, and a check that only looked at the files still there
    would miss exactly that."""
    before = invariance.fingerprint([("a.html", PAGE), ("b.html", PAGE)])
    after = invariance.fingerprint([("a.html", PAGE)])

    result = invariance.compare(before, after)

    assert not result.holds
    assert result.removed == ["b.html"]


def test_an_added_file_does_not_fail_it():
    """Remediation adds files: a caption track, a transcript, a tagged
    copy. Adding one changes no word of what was there."""
    before = invariance.fingerprint([("a.html", PAGE)])
    after = invariance.fingerprint([("a.html", PAGE), ("a.vtt", PAGE)])

    result = invariance.compare(before, after)

    assert result.holds


def test_the_same_bytes_twice_hold():
    pair = [("a.html", PAGE), ("b.html", PAGE)]

    result = invariance.compare(invariance.fingerprint(pair),
                                invariance.fingerprint(pair))

    assert result.holds
    assert result.compared == 2
    assert result.chars > 0


def test_the_note_carries_the_denominator_and_what_it_could_not_read():
    """A bare "nothing changed" is worth very little without how much was
    looked at, and the files nothing could read have to be in the same
    sentence or the number flatters."""
    pair = [("a.html", PAGE)]
    result = invariance.compare(invariance.fingerprint(pair),
                                invariance.fingerprint(pair),
                                unread=["slides.pptx"])

    said = result.note()

    assert "1 file(s)" in said
    assert "characters of text compared" in said
    assert "0 changed" in said
    assert "1 file(s) hold text this cannot read" in said


def test_formats_holding_text_that_cannot_be_read_are_named():
    """So the proof says what it does not cover instead of implying it
    covered everything."""
    pairs = [("a.html", b""), ("b.pptx", b""), ("c.doc", b""),
             ("d.png", b"")]

    assert sorted(invariance.unreadable(pairs)) == ["b.pptx", "c.doc"]
