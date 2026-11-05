"""The queue of pictures a course owes, and writing the author's words.

R6. Everything before this reports a picture with no description and goes no
further, because a description is words about the author's own material.
This is where the author supplies them, and the tests that matter are the
ones about what it will not do: write anything a person did not type, touch
more than the one attribute, ship a file whose text moved, or edit a picture
it cannot be sure it has found again.

The counts it is held to were measured independently before it existed: 62
pictures in web pages, 13 in Word files and 110 in PowerPoint files owed a
real description across the real cartridges, and 35 more carried Microsoft's
machine-written text. The finder agreed with all four.
"""
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
import invariance
import jobs
import pictures
import remediate

MANIFEST = ('<?xml version="1.0"?><manifest xmlns="http://www.imsglobal.org/'
            'xsd/imsccv1p1/imscp_v1p1"/>')


def _png() -> bytes:
    from PIL import Image
    out = io.BytesIO()
    Image.new("RGB", (40, 30), (200, 100, 50)).save(out, "PNG")
    return out.getvalue()


def _page(*imgs, head="<h2>Reading</h2>", doctype="") -> bytes:
    return (f"{doctype}<html><head><title>P</title></head><body>{head}"
            f"<p>Some words around the pictures.</p>{''.join(imgs)}"
            f"</body></html>").encode("utf-8")


def _docx(*descrs) -> bytes:
    import docx
    document = docx.Document()
    document.add_paragraph("A paragraph of the author's own prose.")
    for text in descrs:
        document.add_picture(io.BytesIO(_png()))
        if text is not None:
            document.inline_shapes[-1]._inline.docPr.set("descr", text)
    out = io.BytesIO()
    document.save(out)
    return out.getvalue()


def _pptx(count=2) -> bytes:
    import pptx
    deck = pptx.Presentation()
    slide = deck.slides.add_slide(deck.slide_layouts[5])
    slide.shapes.title.text = "Week one"
    for _ in range(count):
        slide.shapes.add_picture(io.BytesIO(_png()), 0, 0)
    out = io.BytesIO()
    deck.save(out)
    return out.getvalue()


def _cartridge(tmp_path, members, name="c.imscc"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("imsmanifest.xml", MANIFEST)
        for inner, body in members.items():
            z.writestr(inner, body)
    return path


def _read(path, inner):
    with zipfile.ZipFile(path) as z:
        return z.read(inner)


# ---------- finding them ----------

def test_a_picture_with_no_alt_or_a_filename_for_one_is_queued(tmp_path):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page(
        '<img src="a.png">', '<img src="b.png" alt="b.png">')})

    found = pictures.find_pictures(src)

    assert [p.state for p in found] == ["missing", "missing"]
    assert [p.n for p in found] == [0, 1]


@pytest.mark.parametrize("img", [
    '<img src="a.png" alt="">',
    '<img src="a.png" alt="" role="presentation">',
    '<img src="a.png" aria-hidden="true">',
    '<img src="a.png" alt="A rhetorical triangle with three labelled corners">',
])
def test_a_decorative_or_described_picture_is_not_queued(tmp_path, img):
    """`alt=""` is the author saying the picture carries nothing a reader
    needs, which is a claim they made and not a gap. Counting it would quote
    them for a decision already taken."""
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page(img)})

    assert pictures.find_pictures(src) == []


def test_microsofts_machine_text_is_queued_and_kept_apart_from_missing(
        tmp_path):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page(
        '<img src="a.png" alt="A diagram&#10;&#10;Description automatically '
        'generated">')})

    found = pictures.find_pictures(src)

    assert found[0].state == "machine-written"


def test_the_position_counts_every_picture_so_it_can_be_found_again(tmp_path):
    """A page with a described picture before a missing one: the missing one
    is the second `img`, and the edit has to land on it and not the first."""
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page(
        '<img src="a.png" alt="A real description of the first picture">',
        '<img src="b.png">')})

    found = pictures.find_pictures(src)

    assert [(p.n, p.state) for p in found] == [(1, "missing")]


def test_pictures_get_ids_in_the_order_the_cartridge_holds_them(tmp_path):
    src = _cartridge(tmp_path, {
        "wiki_content/a.html": _page('<img src="1.png">'),
        "wiki_content/b.html": _page('<img src="2.png">')})

    assert [p.pid for p in pictures.find_pictures(src)] == [0, 1]


def test_a_canvas_file_reference_is_found_inside_the_package(tmp_path):
    src = _cartridge(tmp_path, {
        "wiki_content/p.html": _page(
            '<img src="$IMS-CC-FILEBASE$/Uploaded%20Media/pic.png">'),
        "web_resources/Uploaded Media/pic.png": _png()})

    found = pictures.find_pictures(src)

    assert found[0].asset == "web_resources/Uploaded Media/pic.png"


def test_a_picture_hosted_elsewhere_has_no_asset_and_no_preview(tmp_path):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page(
        '<img src="https://example.org/x.png">')})

    found = pictures.find_pictures(src)

    assert found[0].asset == ""
    assert pictures.read_preview(src, found[0]) is None


def test_where_a_picture_sits_is_recorded_to_help_the_author(tmp_path):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page(
        '<img src="a.png">', head="<h2>The rhetorical situation</h2>")})

    found = pictures.find_pictures(src)

    assert found[0].heading == "The rhetorical situation"
    assert "Some words around" in found[0].nearby


def test_word_pictures_are_classified_by_meaning_and_not_presence(tmp_path):
    src = _cartridge(tmp_path, {"web_resources/r.docx": _docx(
        "photo.png", "A real description", "Text&#xA;Description automatically "
        "generated")})

    found = pictures.find_pictures(src)

    assert [(p.kind, p.state) for p in found] == [
        ("docx", "missing"), ("docx", "machine-written")]
    assert [p.n for p in found] == [0, 2]


def test_a_word_picture_can_be_shown(tmp_path):
    src = _cartridge(tmp_path, {"web_resources/r.docx": _docx(None)})

    found = pictures.find_pictures(src)
    shown = pictures.read_preview(src, found[0])

    assert shown is not None and shown[1] == "image/png"


def test_slide_pictures_are_found_with_the_slide_title(tmp_path):
    src = _cartridge(tmp_path, {"web_resources/d.pptx": _pptx(2)})

    found = pictures.find_pictures(src)

    assert [p.kind for p in found] == ["pptx", "pptx"]
    assert found[0].heading == "Week one"
    assert found[0].asset_part.startswith("ppt/media/")


def test_a_svg_is_never_offered_as_a_preview(tmp_path):
    """It can carry script, and this is served from this origin."""
    src = _cartridge(tmp_path, {
        "wiki_content/p.html": _page('<img src="v.svg">'),
        "wiki_content/v.svg": "<svg onload='alert(1)'/>"})

    found = pictures.find_pictures(src)

    assert found[0].asset == "wiki_content/v.svg"
    assert pictures.read_preview(src, found[0]) is None


# ---------- what an author may say ----------

def test_a_description_is_one_line_of_plain_words():
    assert pictures.clean_description("  A   desk\n with  a lamp ") == \
        "A desk with a lamp"


@pytest.mark.parametrize("bad", ["", "   ", "photo.png", "Picture 3",
                                 "/tmp/x/abc.jpg", "x" * 1001])
def test_a_filename_or_nothing_or_an_essay_is_not_a_description(bad):
    """A filename is exactly the thing being replaced; accepting one would
    clear a gap in the report while leaving the gap."""
    with pytest.raises(ValueError):
        pictures.clean_description(bad)


def test_only_a_machine_written_description_can_be_kept_as_it_is():
    mine = pictures.Picture(pid=0, state="missing")
    theirs = pictures.Picture(pid=1, state="machine-written")

    with pytest.raises(ValueError):
        pictures.validate_decision(mine, "keep", "")
    assert pictures.validate_decision(theirs, "keep", "").action == "keep"


def test_an_action_that_is_not_one_is_refused():
    with pytest.raises(ValueError):
        pictures.validate_decision(pictures.Picture(), "rewrite", "x")


# ---------- writing it into a page ----------

def _apply(src, tmp_path, decisions, **kw):
    found = pictures.find_pictures(src)
    dst = tmp_path / "out.imscc"
    report = pictures.apply_descriptions(src, dst, found, decisions, **kw)
    return found, dst, report


def test_a_page_gets_the_authors_words_and_nothing_else(tmp_path):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page(
        '<img src="a.png" alt="a.png">', '<img src="b.png" alt="b.png">')})
    found = pictures.find_pictures(src)

    _f, dst, report = _apply(src, tmp_path, {
        found[0].pid: pictures.Decision("describe", "A lamp on a desk")})

    page = _read(dst, "wiki_content/p.html").decode("utf-8")
    assert 'alt="A lamp on a desk"' in page
    assert 'alt="b.png"' in page      # the one not decided is untouched
    assert report.applied == [found[0].pid]
    assert report.still_owed == [found[1].pid]


def test_decorative_writes_an_empty_alt(tmp_path):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page(
        '<img src="rule.png">')})
    found = pictures.find_pictures(src)

    _f, dst, _r = _apply(src, tmp_path, {
        found[0].pid: pictures.Decision("decorative")})

    assert 'alt=""' in _read(dst, "wiki_content/p.html").decode("utf-8")


def test_a_doctype_is_kept_when_a_page_is_edited(tmp_path):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page(
        '<img src="a.png">', doctype="<!DOCTYPE html>\n")})
    found = pictures.find_pictures(src)

    _f, dst, _r = _apply(src, tmp_path, {
        found[0].pid: pictures.Decision("describe", "A lamp")})

    assert _read(dst, "wiki_content/p.html").upper().startswith(b"<!DOCTYPE")


def test_the_text_of_an_edited_page_is_unchanged(tmp_path):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page('<img src="a.png">')})
    found = pictures.find_pictures(src)

    _f, dst, _r = _apply(src, tmp_path, {
        found[0].pid: pictures.Decision("describe", "A lamp")})

    assert invariance.text_of("p.html", _read(src, "wiki_content/p.html")) == \
        invariance.text_of("p.html", _read(dst, "wiki_content/p.html"))


def test_a_description_with_quotes_and_markup_is_escaped_not_injected(
        tmp_path):
    """It is typed into a web form and lands in an attribute."""
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page('<img src="a.png">')})
    found = pictures.find_pictures(src)
    nasty = 'A "quoted" <b>tag</b> & an ampersand'

    _f, dst, _r = _apply(src, tmp_path, {
        found[0].pid: pictures.Decision("describe", nasty)})

    from lxml import html as lxml_html
    tree = lxml_html.fromstring(_read(dst, "wiki_content/p.html"))
    assert tree.xpath("//img")[0].get("alt") == nasty
    assert not tree.xpath("//b")


# ---------- writing it into Word and PowerPoint ----------

def _inner(path, member):
    return zipfile.ZipFile(io.BytesIO(_read(path, member)))


def test_a_word_file_changes_in_exactly_one_part(tmp_path):
    """Round-tripping a Word file through a library can silently drop
    comments, tracked changes and objects it does not model. The one XML part
    that holds the picture is edited as text, in place."""
    src = _cartridge(tmp_path, {"web_resources/r.docx": _docx(None, None)})
    found = pictures.find_pictures(src)

    _f, dst, report = _apply(src, tmp_path, {
        found[0].pid: pictures.Decision("describe", "A lamp on a desk")})

    before, after = _inner(src, "web_resources/r.docx"), _inner(dst, "web_resources/r.docx")
    changed = [i.filename for i in before.infolist()
               if before.getinfo(i.filename).CRC != after.getinfo(i.filename).CRC]
    assert changed == ["word/document.xml"]
    assert report.failed == []


def test_the_word_file_still_opens_and_reads_back_the_authors_words(tmp_path):
    import docx
    src = _cartridge(tmp_path, {"web_resources/r.docx": _docx(None, None)})
    found = pictures.find_pictures(src)

    _f, dst, _r = _apply(src, tmp_path, {
        found[1].pid: pictures.Decision("describe", "A lamp on a desk")})

    document = docx.Document(io.BytesIO(_read(dst, "web_resources/r.docx")))
    assert document.inline_shapes[1]._inline.docPr.get("descr") == \
        "A lamp on a desk"
    assert not document.inline_shapes[0]._inline.docPr.get("descr")


def test_two_pictures_in_one_part_are_each_edited_where_they_are(tmp_path):
    """Replacements are applied from the end so the first does not shift the
    second, which is how a position-based edit goes wrong silently."""
    import docx
    src = _cartridge(tmp_path, {"web_resources/r.docx": _docx(None, None)})
    found = pictures.find_pictures(src)

    _f, dst, _r = _apply(src, tmp_path, {
        found[0].pid: pictures.Decision("describe", "The first picture"),
        found[1].pid: pictures.Decision("describe", "The second one, longer")})

    shapes = docx.Document(io.BytesIO(
        _read(dst, "web_resources/r.docx"))).inline_shapes
    assert shapes[0]._inline.docPr.get("descr") == "The first picture"
    assert shapes[1]._inline.docPr.get("descr") == "The second one, longer"


def test_a_decorative_word_picture_is_marked_the_way_word_marks_it(tmp_path):
    src = _cartridge(tmp_path, {"web_resources/r.docx": _docx(None)})
    found = pictures.find_pictures(src)

    _f, dst, _r = _apply(src, tmp_path, {
        found[0].pid: pictures.Decision("decorative")})

    result = remediate.audit_docx(_read(dst, "web_resources/r.docx"))
    assert not any(o.kind.startswith("image-") for o in result.owed)
    xml = _inner(dst, "web_resources/r.docx").read("word/document.xml")
    assert b"decorative" in xml
    from lxml import etree
    etree.fromstring(xml)          # still well-formed


def test_a_description_in_word_survives_the_audit(tmp_path):
    src = _cartridge(tmp_path, {"web_resources/r.docx": _docx(None)})
    found = pictures.find_pictures(src)
    before = remediate.audit_docx(_read(src, "web_resources/r.docx"))
    assert any(o.kind == "image-without-description" for o in before.owed)

    _f, dst, _r = _apply(src, tmp_path, {
        found[0].pid: pictures.Decision("describe", "A lamp on a desk")})

    after = remediate.audit_docx(_read(dst, "web_resources/r.docx"))
    assert not any(o.kind.startswith("image-") for o in after.owed)


def test_slide_pictures_are_edited_and_the_deck_still_opens(tmp_path):
    import pptx
    src = _cartridge(tmp_path, {"web_resources/d.pptx": _pptx(2)})
    found = pictures.find_pictures(src)

    _f, dst, report = _apply(src, tmp_path, {
        found[1].pid: pictures.Decision("describe", "A collage of clippings")})

    deck = pptx.Presentation(io.BytesIO(_read(dst, "web_resources/d.pptx")))
    pics = [s for s in deck.slides[0].shapes if s.shape_type == 13]
    assert pics[1]._element.xpath("./p:nvPicPr/p:cNvPr")[0].get("descr") == \
        "A collage of clippings"
    assert report.failed == []


def test_an_edited_part_stays_well_formed_with_awkward_text(tmp_path):
    from lxml import etree
    src = _cartridge(tmp_path, {"web_resources/d.pptx": _pptx(1)})
    found = pictures.find_pictures(src)

    _f, dst, _r = _apply(src, tmp_path, {
        found[0].pid: pictures.Decision("describe", 'A "quote" & <angle> é')})

    inner = _inner(dst, "web_resources/d.pptx")
    root = etree.fromstring(inner.read("ppt/slides/slide1.xml"))
    cnv = root.xpath("//p:pic/p:nvPicPr/p:cNvPr",
                     namespaces={"p": pictures._P})[0]
    assert cnv.get("descr") == 'A "quote" & <angle> é'


# ---------- what it refuses ----------

def test_a_picture_it_cannot_be_sure_of_is_left_alone_and_reported(tmp_path):
    """The picture is found again by its own id, so a file that does not look
    the way the finder saw it is not guessed at."""
    src = _cartridge(tmp_path, {"web_resources/r.docx": _docx(None)})
    found = pictures.find_pictures(src)
    found[0].ident = "9999"

    dst = tmp_path / "out.imscc"
    report = pictures.apply_descriptions(src, dst, found, {
        found[0].pid: pictures.Decision("describe", "A lamp")})

    assert report.failed and "not the one" in report.failed[0]["reason"]
    assert _read(dst, "web_resources/r.docx") == _read(src, "web_resources/r.docx")


def test_a_file_with_fewer_pictures_than_before_is_left_alone(tmp_path):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page('<img src="a.png">')})
    found = pictures.find_pictures(src)
    found[0].n = 5

    dst = tmp_path / "out.imscc"
    report = pictures.apply_descriptions(src, dst, found, {
        found[0].pid: pictures.Decision("describe", "A lamp")})

    assert report.failed
    assert _read(dst, "wiki_content/p.html") == _read(src, "wiki_content/p.html")


def test_an_edit_that_would_move_a_word_is_dropped(tmp_path, monkeypatch):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page('<img src="a.png">')})
    found = pictures.find_pictures(src)
    monkeypatch.setattr(pictures, "_edit_html",
                        lambda data, items: data.replace(b"words", b"WORDS"))

    dst = tmp_path / "out.imscc"
    report = pictures.apply_descriptions(src, dst, found, {
        found[0].pid: pictures.Decision("describe", "A lamp")})

    assert report.failed and "changed the text" in report.failed[0]["reason"]
    assert _read(dst, "wiki_content/p.html") == _read(src, "wiki_content/p.html")


def test_undecided_skipped_and_kept_pictures_are_not_touched(tmp_path):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page(
        '<img src="a.png">', '<img src="b.png">',
        '<img src="c.png" alt="x&#10;Description automatically generated">')})
    found = pictures.find_pictures(src)

    _f, dst, report = _apply(src, tmp_path, {
        found[0].pid: pictures.Decision("skip"),
        found[2].pid: pictures.Decision("keep")})

    assert _read(dst, "wiki_content/p.html") == _read(src, "wiki_content/p.html")
    assert report.kept == [found[2].pid]
    assert set(report.still_owed) == {found[0].pid, found[1].pid}
    assert report.files_changed == 0


def test_everything_else_in_the_cartridge_keeps_its_bytes(tmp_path):
    src = _cartridge(tmp_path, {
        "wiki_content/p.html": _page('<img src="a.png">'),
        "web_resources/clip.mp4": b"not really video" * 50,
        "web_resources/other.html": _page("<p>Nothing to do</p>")})
    found = pictures.find_pictures(src)

    _f, dst, report = _apply(src, tmp_path, {
        found[0].pid: pictures.Decision("describe", "A lamp")})

    for name in ("imsmanifest.xml", "web_resources/clip.mp4",
                 "web_resources/other.html"):
        assert _read(dst, name) == _read(src, name)
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst) as b:
        assert a.namelist() == b.namelist()
    assert report.verified


def test_stopping_part_way_leaves_nothing_behind(tmp_path):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page('<img src="a.png">')})
    found = pictures.find_pictures(src)
    dst = tmp_path / "out.imscc"

    with pytest.raises(pictures.Stopped):
        pictures.apply_descriptions(
            src, dst, found,
            {found[0].pid: pictures.Decision("describe", "A lamp")},
            stop=lambda: True)

    assert not dst.exists()
    assert not Path(str(dst) + ".partial").exists()


def test_what_was_written_no_longer_owes_anything_on_the_next_pass(tmp_path):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page(
        '<img src="a.png">', '<img src="b.png">')})
    found = pictures.find_pictures(src)

    _f, dst, _r = _apply(src, tmp_path, {
        found[0].pid: pictures.Decision("describe", "A lamp on a desk"),
        found[1].pid: pictures.Decision("decorative")})

    assert pictures.find_pictures(dst) == []


# ---------- the queue's own files ----------

def test_the_queue_files_round_trip(tmp_path):
    owed = [pictures.Picture(pid=0, member="a.html", kind="page"),
            pictures.Picture(pid=1, member="b.html", kind="page")]
    pictures.save_pictures(tmp_path, owed)
    pictures.save_decisions(tmp_path, {1: pictures.Decision("describe", "x y")})

    assert [p.pid for p in pictures.load_pictures(tmp_path)] == [0, 1]
    assert pictures.load_decisions(tmp_path)[1].text == "x y"


def test_missing_queue_files_read_as_nothing_not_as_an_error(tmp_path):
    assert pictures.load_pictures(tmp_path) is None
    assert pictures.load_decisions(tmp_path) == {}


def test_a_skipped_picture_is_still_waiting():
    owed = [pictures.Picture(pid=i) for i in range(3)]
    decisions = {0: pictures.Decision("describe", "x y"),
                 1: pictures.Decision("skip")}

    assert [p.pid for p in pictures.pending(owed, decisions)] == [1, 2]


def test_the_record_carries_the_authors_own_words(tmp_path):
    src = _cartridge(tmp_path, {"wiki_content/p.html": _page('<img src="a.png">')})
    found = pictures.find_pictures(src)
    decisions = {found[0].pid: pictures.Decision("describe", "A lamp on a desk")}
    dst = tmp_path / "o.imscc"
    report = pictures.apply_descriptions(src, dst, found, decisions)

    text = pictures.render_markdown(report, found, decisions)

    assert "A lamp on a desk" in text
    assert "—" not in text


# ---------- as a job ----------

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(jobs, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(jobs, "WORKER_ENABLED", False)
    db.init_db()
    return tmp_path


def _course(tmp_path):
    return _cartridge(tmp_path, {
        "wiki_content/p.html": _page(
            '<img src="$IMS-CC-FILEBASE$/Uploaded Media/pic.png" '
            'alt="pic.png">'),
        "web_resources/Uploaded Media/pic.png": _png(),
        "course_settings/media_tracks.xml":
            '<media_tracks xmlns="http://canvas.instructure.com/xsd/cccv1p0">\n'
            '</media_tracks>'}, name="course.imscc")


def _remediated(workspace):
    job_id = jobs.create("remediate_cartridge", "a course",
                         {"language": "en"}, None)
    (jobs.staging_dir(job_id) / "course.imscc").write_bytes(
        _course(workspace).read_bytes())
    jobs.release(job_id)
    assert jobs.run_job(job_id) == jobs.DONE
    return job_id


def test_a_remediation_leaves_the_queue_beside_its_results(workspace):
    job_id = _remediated(workspace)

    owed = pictures.load_pictures(jobs.results_dir(job_id))

    assert len(owed) == 1
    assert owed[0].asset == "web_resources/Uploaded Media/pic.png"


def test_the_remediation_says_how_many_pictures_wait(workspace):
    job_id = _remediated(workspace)

    steps = {i["name"]: i for i in jobs.items(jobs.get(job_id))}

    assert "1 picture(s)" in steps["Pictures to describe"]["detail"]


def test_a_course_with_nothing_owed_has_no_queue(workspace):
    job_id = jobs.create("remediate_cartridge", "a course", {}, None)
    clean = _cartridge(workspace, {"wiki_content/p.html": _page(
        '<img src="a.png" alt="A rhetorical triangle with three corners">')},
        name="clean.imscc")
    (jobs.staging_dir(job_id) / "c.imscc").write_bytes(clean.read_bytes())
    jobs.release(job_id)

    jobs.run_job(job_id)

    assert pictures.load_pictures(jobs.results_dir(job_id)) == []


def test_the_apply_job_writes_a_new_cartridge_and_leaves_the_old_one(workspace):
    source = _remediated(workspace)
    folder = jobs.results_dir(source)
    pictures.save_decisions(folder, {
        0: pictures.Decision("describe", "A lamp on a desk")})
    before = (folder / "remediated.imscc").read_bytes()

    apply_id = jobs.create("apply_descriptions", "write", {"source_job": source},
                           None, stage=False)
    jobs.release(apply_id)
    state = jobs.run_job(apply_id)

    assert state == jobs.DONE
    out = jobs.results_dir(apply_id)
    assert (out / "described.imscc").is_file()
    assert (out / "described-report.md").is_file()
    assert (folder / "remediated.imscc").read_bytes() == before
    assert b'alt="A lamp on a desk"' in _read(out / "described.imscc",
                                              "wiki_content/p.html")


def test_the_apply_job_fails_plainly_when_the_source_is_gone(workspace):
    source = _remediated(workspace)
    import shutil
    shutil.rmtree(jobs.results_dir(source))

    apply_id = jobs.create("apply_descriptions", "write", {"source_job": source},
                           None, stage=False)
    jobs.release(apply_id)

    assert jobs.run_job(apply_id) == jobs.FAILED
    assert "no longer on the server" in jobs.get(apply_id)["error"]


# ---------- the pages ----------

@pytest.fixture
def client(workspace):
    import app as app_module
    application = app_module.create_app()
    application.config["LOGIN_DISABLED"] = True
    return application.test_client()


def test_the_job_page_offers_the_queue(client, workspace):
    job_id = _remediated(workspace)

    body = " ".join(client.get(f"/jobs/{job_id}").data.decode("utf-8").split())

    assert "Pictures to describe" in body
    assert "Describe the pictures" in body
    assert "Nothing is written for you" in body


def test_the_queue_lists_every_picture_and_says_what_it_will_do(client,
                                                                workspace):
    job_id = _remediated(workspace)

    body = " ".join(client.get(f"/jobs/{job_id}/describe").data.decode(
        "utf-8").split())

    assert "none is written for you" in body
    assert "Describe the next one" in body
    assert "waiting" in body


def test_the_picture_page_shows_the_picture_and_where_it_sits(client, workspace):
    job_id = _remediated(workspace)

    body = client.get(f"/jobs/{job_id}/describe/0").data.decode("utf-8")

    assert f"/jobs/{job_id}/describe/0/image" in body
    assert "Where it sits" in body
    assert "What does it show?" in body
    assert 'value="keep"' not in body     # only for machine-written text


def test_saving_a_description_records_it_and_moves_on(client, workspace):
    job_id = _remediated(workspace)

    response = client.post(f"/jobs/{job_id}/describe/0",
                           data={"action": "describe",
                                 "text": "A lamp on a desk"})

    assert response.status_code == 302
    saved = pictures.load_decisions(jobs.results_dir(job_id))
    assert saved[0].text == "A lamp on a desk"


@pytest.mark.parametrize("text", ["", "pic.png", "x" * 1001])
def test_a_bad_description_is_not_saved_and_says_why(client, workspace, text):
    job_id = _remediated(workspace)

    response = client.post(f"/jobs/{job_id}/describe/0",
                           data={"action": "describe", "text": text},
                           follow_redirects=True)

    assert response.status_code == 200
    assert pictures.load_decisions(jobs.results_dir(job_id)) == {}


def test_the_form_keeps_what_was_typed_when_it_is_refused(client, workspace):
    job_id = _remediated(workspace)

    body = client.post(f"/jobs/{job_id}/describe/0",
                       data={"action": "describe", "text": "pic.png"}
                       ).data.decode("utf-8")

    assert "pic.png" in body
    assert "filename or a placeholder" in body


def test_the_preview_is_served_with_the_headers_that_make_it_inert(client,
                                                                   workspace):
    job_id = _remediated(workspace)

    response = client.get(f"/jobs/{job_id}/describe/0/image")

    assert response.status_code == 200
    assert response.mimetype == "image/png"
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert "sandbox" in response.headers["Content-Security-Policy"]


def test_a_picture_with_no_preview_is_a_404_not_a_crash(client, workspace):
    job_id = _remediated(workspace)
    folder = jobs.results_dir(job_id)
    owed = pictures.load_pictures(folder)
    owed[0].asset = ""
    pictures.save_pictures(folder, owed)

    assert client.get(f"/jobs/{job_id}/describe/0/image").status_code == 404


def test_a_job_that_is_not_a_remediation_has_no_queue(client, workspace):
    other = jobs.create("ingest_batch", "x", {}, None)

    assert client.get(f"/jobs/{other}/describe").status_code == 404
    assert client.get(f"/jobs/9999/describe").status_code == 404


def test_a_picture_that_is_not_in_the_queue_is_a_404(client, workspace):
    job_id = _remediated(workspace)

    assert client.get(f"/jobs/{job_id}/describe/7").status_code == 404
    assert client.get(f"/jobs/{job_id}/describe/7/image").status_code == 404


def test_writing_with_nothing_decided_is_refused(client, workspace):
    job_id = _remediated(workspace)

    client.post(f"/jobs/{job_id}/describe/apply")

    assert [j for j in jobs.recent() if j["kind"] == "apply_descriptions"] == []


def test_writing_queues_a_job_for_what_was_decided(client, workspace):
    job_id = _remediated(workspace)
    client.post(f"/jobs/{job_id}/describe/0",
                data={"action": "describe", "text": "A lamp on a desk"})

    response = client.post(f"/jobs/{job_id}/describe/apply")

    assert response.status_code == 302
    job = [j for j in jobs.recent() if j["kind"] == "apply_descriptions"][0]
    assert jobs.payload(job)["source_job"] == job_id


def test_the_result_can_be_downloaded(client, workspace):
    source = _remediated(workspace)
    pictures.save_decisions(jobs.results_dir(source), {
        0: pictures.Decision("decorative")})
    apply_id = jobs.create("apply_descriptions", "w", {"source_job": source},
                           None, stage=False)
    jobs.release(apply_id)
    jobs.run_job(apply_id)

    assert client.get(f"/jobs/{apply_id}/download/described").status_code == 200
    assert client.get(
        f"/jobs/{apply_id}/download/described-report").status_code == 200
