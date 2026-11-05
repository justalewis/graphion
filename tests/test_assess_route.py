"""The assessment front door, and the two promises it has to keep.

`assess.py` answers the question a journal asks before any agreement
exists, which is what remediating its back catalogue would cost, and it
answers it by reading: no article directory, no database row, no file
beside the one it read. For as long as the only caller was a terminal
that contract was tested where it lives. A route is a second caller, and
it has to keep the same promise one level up: the uploads go to a
temporary directory that goes away with the request, so a stranger's PDFs
do not accumulate on a server either.

The other promise is arithmetic. `report()` added the pass up inline,
which was right while prose was the only output; a page needs the same
numbers as data, and two places adding up the same files is how one count
comes to mean two things. `rollup()` is the one adder now, so the tests
that matter most here are the ones that would catch the browser and the
terminal disagreeing.
"""
import io
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import assess
import conversion
import db


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    import app as app_module
    application = app_module.create_app()
    application.config["LOGIN_DISABLED"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application.test_client()


def _upload(*names_and_bytes):
    """A multipart payload holding one entry per file."""
    return {"pdfs": [(io.BytesIO(data), name)
                     for name, data in names_and_bytes]}


CHAPTER = """#set document(title: [A Chapter], author: ("Jane Doe",))
#set text(lang: "en")
= A Heading

Body text, carrying no figure at all.
"""


@pytest.fixture
def real_pdf(tmp_path):
    """A conformant galley, built the way `test_assess.py` builds them."""
    typ = tmp_path / "chapter.typ"
    typ.write_text(CHAPTER, encoding="utf-8")
    out = tmp_path / "chapter.pdf"
    conversion._compile_typst(typ, out, root=tmp_path)
    return out


# ---------- the rollup is the one adder ----------

def _assessment(name, **kwargs):
    return assess.Assessment(path=Path(name), **kwargs)


def test_an_unreadable_file_is_counted_and_left_out_of_every_total():
    """A file pypdf could not open has told you nothing about its figures.

    Folding a zero in beside a real reading is the kind of claim this
    module exists to refuse, and it would read as an archive with less
    work in it than it has.
    """
    roll = assess.rollup([
        _assessment("good.pdf", pages=10, tagged=True, figures=4),
        _assessment("broken.pdf", readable=False, error="not a PDF"),
    ])

    assert roll.files == 2
    assert roll.readable == 1
    assert roll.unreadable == 1
    assert roll.pages == 10
    assert roll.figures_owed == 4
    # The unreadable file is not counted as one carrying no tree either,
    # which a naive `readable - tagged` over everything would have done.
    assert roll.untagged == 0


def test_the_rollup_and_the_report_add_the_same_files_up_the_same_way():
    """The reason `rollup()` exists at all.

    `report()` worked these out inline. A page cannot read prose, so the
    numbers had to come out as data, and the failure to avoid is the
    browser and the terminal quoting a journal two different figures for
    one archive.
    """
    files = [
        _assessment("a.pdf", pages=12, tagged=True, tagged_figures=6,
                    described_figures=1),
        _assessment("b.pdf", pages=8, tagged=False, figures=3),
        _assessment("c.pdf", readable=False, error="encrypted"),
    ]

    roll = assess.rollup(files)
    text = assess.report(files)

    assert f"{roll.readable} file(s) read, {roll.unreadable} unreadable." in text
    assert (f"{roll.figures_owed} figure(s) needing a description, of "
            f"{roll.figures_found} found.") in text
    assert f"{roll.untagged} of {roll.readable} carry no structure tree" in text
    # And the numbers are the ones the archive's own reading produces: five
    # owed on the tagged file, because the tree decides there, plus three
    # on the untagged one, where the raster count is all there is.
    assert roll.figures_owed == 8
    assert roll.figures_found == 9


def test_a_verdict_is_only_counted_over_the_files_a_checker_reached():
    """`checked` is never inferred from a file's own declaration.

    A tool that did not run has told you nothing, and counting its
    silence as a pass is the failure `register.UNRUN` exists for.
    """
    roll = assess.rollup([
        _assessment("passed.pdf", tagged=True, verapdf=True),
        _assessment("failed.pdf", tagged=True, verapdf=False),
        _assessment("unasked.pdf", tagged=True),
    ])

    assert roll.checked == 2
    assert roll.passing == 1
    assert roll.readable == 3


def test_a_file_that_declares_conformance_and_fails_is_called_out():
    """The case to read first in a prospect's archive: it has already been
    through somebody's pipeline, so what it is short of is usually narrow
    and nobody has been told."""
    roll = assess.rollup([
        _assessment("states-it.pdf", tagged=True, declared_ua_part=1,
                    xmp_title="A Chapter", verapdf=False),
        _assessment("honest.pdf", tagged=False, verapdf=False),
    ])

    assert [a.path.name for a in roll.contradicted] == ["states-it.pdf"]
    assert roll.declaring == 1


def test_a_symbol_font_is_folded_across_the_pass_rather_than_counted_twice():
    """A font is one reading somebody does off the page and writes down
    once, however many characters it sets or files it appears in. The
    number a journal is quoted from is how many fonts nobody has mapped
    yet, so two files setting the same font are one piece of work."""
    font = lambda: assess.SymbolFont("acmedingbats", characters=50, pages=1)
    roll = assess.rollup([
        _assessment("a.pdf", tagged=True, symbol_pages=1,
                    symbol_fonts=[font()]),
        _assessment("b.pdf", tagged=True, symbol_pages=1,
                    symbol_fonts=[font()]),
    ])

    assert roll.symbol_pages == 2
    assert len(roll.symbol_fonts) == 1
    assert roll.symbol_fonts[0].characters == 100
    assert [f.family for f in roll.unmapped_fonts] == ["acmedingbats"]


def test_a_mapped_font_is_not_work():
    """`SYMBOL_FONT_CHARS` already knows it, so nobody has to read it off
    the page; reporting it as outstanding would inflate the quote."""
    roll = assess.rollup([
        _assessment("a.pdf", tagged=True, symbol_pages=1,
                    symbol_fonts=[assess.SymbolFont("wingdings", characters=9,
                                                    pages=1, known=True)]),
    ])

    assert roll.symbol_fonts
    assert roll.unmapped_fonts == []


def test_an_empty_pass_adds_up_to_nothing_rather_than_raising():
    roll = assess.rollup([])

    assert roll.files == 0
    assert roll.readable == 0
    assert roll.untagged == 0
    assert roll.unmapped_fonts == []


# ---------- a note is a finding, not an instruction ----------

def test_no_note_tells_the_reader_to_pass_a_flag(real_pdf):
    """`_add_notes` is read on a web page now as well as in a terminal.

    Three of its notes named a command line flag, which is correct in a
    shell and nonsense in a browser: an editor who has just ticked a
    checkbox is told to pass `--validate`. A note states what was found
    about the file; which flag or which checkbox answers it belongs to
    whichever surface is asking, so `main()` prints the flags and the
    page prints its own copy beside the controls.
    """
    assessment = assess.assess_pdf(real_pdf)
    page_note = assess.HtmlAssessment(path=Path("x.html")).pa11y_note

    assert assessment.notes
    for note in assessment.notes:
        assert "--" not in note, note
    assert "--" not in page_note


# ---------- the route writes nothing ----------

def test_the_form_is_served(client):
    response = client.get("/assess")

    assert response.status_code == 200
    assert b"Assess an archive" in response.data
    assert b'name="pdfs"' in response.data
    assert b"multiple" in response.data


def test_nothing_is_written_where_the_request_could_reach(client, monkeypatch,
                                                          tmp_path, real_pdf):
    """The contract `assess.py` keeps, kept one level up.

    `test_assessing_a_folder_leaves_it_exactly_as_it_was` holds the module
    to this. The route is a second caller and could break it on its own,
    by leaving the upload behind: a server collecting a stranger's PDFs is
    the last thing anybody assessing an archive asked for.
    """
    scratch = tmp_path / "temp-root"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))

    response = client.post("/assess",
                           data=_upload(("chapter.pdf", real_pdf.read_bytes())),
                           content_type="multipart/form-data")

    assert response.status_code == 200
    assert b"chapter.pdf" in response.data
    # The temporary directory the upload was saved into is gone, and
    # nothing took its place.
    assert list(scratch.iterdir()) == []


def test_a_real_pdf_is_read_through_the_route(client, real_pdf):
    """End to end, so the route is exercised against a file rather than
    against a dataclass: a conformant galley reads as one."""
    response = client.post("/assess",
                           data=_upload(("chapter.pdf", real_pdf.read_bytes())),
                           content_type="multipart/form-data")

    body = response.data.decode("utf-8")
    assert "declares PDF/UA-1" in body
    assert "language en" in body


def test_a_file_that_will_not_open_is_reported_rather_than_dropped(client):
    """An unreadable file is a finding about the archive. Leaving it off
    the page would read as a smaller archive that is in better shape."""
    response = client.post("/assess",
                           data=_upload(("junk.pdf", b"not a PDF at all")),
                           content_type="multipart/form-data")

    body = response.data.decode("utf-8")
    assert response.status_code == 200
    assert "junk.pdf" in body
    assert "will not open" in body


def test_something_that_is_not_a_pdf_is_left_out_and_said_so(client,
                                                             real_pdf):
    response = client.post(
        "/assess",
        data=_upload(("chapter.pdf", real_pdf.read_bytes()),
                     ("notes.docx", b"PK\x03\x04 not a pdf")),
        content_type="multipart/form-data")

    body = response.data.decode("utf-8")
    assert "1 file(s) were not PDFs and were left out" in body
    assert "notes.docx" in body
    assert "chapter.pdf" in body


def test_uploading_nothing_at_all_says_so(client):
    response = client.post("/assess", data={},
                           content_type="multipart/form-data",
                           follow_redirects=True)

    assert b"No files uploaded." in response.data


def test_uploading_only_non_pdfs_says_so(client):
    response = client.post("/assess", data=_upload(("a.docx", b"x")),
                           content_type="multipart/form-data",
                           follow_redirects=True)

    assert b"This page reads PDFs; none of those is one." in response.data


def test_the_batch_is_capped_and_the_overflow_is_named(client, monkeypatch,
                                                        real_pdf):
    """A browser request is not where a 118 chapter archive belongs, and
    the page says where that is rather than reading two of them and
    silently dropping the rest."""
    import app as app_module
    monkeypatch.setattr(app_module, "MAX_ASSESS_FILES", 1)
    data = real_pdf.read_bytes()

    response = client.post(
        "/assess",
        data=_upload(("one.pdf", data), ("two.pdf", data)),
        content_type="multipart/form-data")

    body = response.data.decode("utf-8")
    assert "1 file(s) past the limit of 1" in body
    assert "python assess.py" in body
    assert "two.pdf" not in body.split("File by file")[-1]
    assert body.count('class="assess-file"') == 1


def test_two_files_of_one_name_are_both_read(client, real_pdf):
    """A batch can carry the same name from two folders. Saved over each
    other, the second overwrites the first and one file's bytes are
    reported twice under one heading, which reads as an archive with two
    identical chapters in it."""
    data = real_pdf.read_bytes()

    response = client.post(
        "/assess",
        data=_upload(("chapter.pdf", data), ("chapter.pdf", data)),
        content_type="multipart/form-data")

    body = response.data.decode("utf-8")
    assert "chapter.pdf" in body
    assert "chapter-1.pdf" in body
    assert body.count('class="assess-file"') == 2


# ---------- the larger request body stays on this one route ----------

def test_the_endpoint_named_as_exempt_is_one_that_exists(client):
    """The exemption is by endpoint name rather than by path, so a rename
    would detach it. If that name stops resolving, every other route
    silently keeps the larger limit and this route starts refusing a
    batch, so the pairing is pinned."""
    import app as app_module
    application = client.application

    assert app_module.ASSESS_ENDPOINT in application.view_functions


def test_the_publishing_routes_keep_the_smaller_limit(client, monkeypatch):
    """`MAX_CONTENT_LENGTH` is per application and had to rise for a batch
    of PDFs to arrive at all. Without the hook, every upload that writes
    into `content/` would quietly have gained the same headroom."""
    import app as app_module
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 8)

    refused = client.post("/journals/whatever/upload",
                          data={"body": "x" * 200},
                          content_type="multipart/form-data")

    assert refused.status_code == 413


def test_the_assessment_route_is_allowed_the_larger_body(client, monkeypatch,
                                                          real_pdf):
    """The other half of the same hook: the one route that needs the room
    is not caught by the limit meant for the rest."""
    import app as app_module
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 8)

    response = client.post("/assess",
                           data=_upload(("chapter.pdf", real_pdf.read_bytes())),
                           content_type="multipart/form-data")

    assert response.status_code == 200


def test_the_verapdf_box_is_disabled_where_the_tool_is_missing(client,
                                                               monkeypatch):
    """The convention the rest of the app follows: optional tooling greys
    out the control rather than failing when it is pressed."""
    import validators
    monkeypatch.setattr(validators, "verapdf_available", lambda: False)

    body = client.get("/assess").data.decode("utf-8")

    assert "verapdf is not on PATH" in body
    assert "disabled" in body


def test_a_verdict_is_not_asked_for_where_the_tool_is_missing(client,
                                                             monkeypatch,
                                                             real_pdf):
    """Ticking the box in a stale page must not reach a tool that is not
    there. A missing tool is not a result, which is the rule
    `validate_galleys.py` refuses to start on."""
    import validators
    monkeypatch.setattr(validators, "verapdf_available", lambda: False)
    called = []
    monkeypatch.setattr(assess, "_run_verapdf",
                        lambda *a, **k: called.append(a))

    client.post("/assess",
                data={"pdfs": [(io.BytesIO(real_pdf.read_bytes()),
                                "chapter.pdf")],
                      "validate": "on"},
                content_type="multipart/form-data")

    assert called == []
