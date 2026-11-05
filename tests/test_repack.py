"""Remediating a whole cartridge, and what it has to refuse and prove.

R7. The fixes themselves are tested in `test_remediate.py`; what is held
here is everything around them, because that is where a remediation
service gets it wrong in ways nobody sees. A cartridge carrying student
work must be turned away and leave nothing behind. A fix that moved a word
must never ship. What is written must be checked, not what was meant to
be. And nothing the manifest points at may move.
"""
import io
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cartridge
import db
import invariance
import jobs
import remediate
import repack

MANIFEST = """<?xml version="1.0" encoding="UTF-8"?>
<manifest identifier="g1" xmlns="http://www.imsglobal.org/xsd/imsccv1p1/imscp_v1p1">
  <organizations/><resources/>
</manifest>
"""

EMPTY_TRACKS = ('<?xml version="1.0"?><media_tracks '
                'xmlns="http://canvas.instructure.com/xsd/cccv1p0">\n'
                '</media_tracks>\n')

STUDENT_TRACKS = (
    '<?xml version="1.0"?><media_tracks '
    'xmlns="http://canvas.instructure.com/xsd/cccv1p0"><media>'
    '<track kind="subtitles" locale="en">1\n00:00:00,540 --&gt; '
    '00:00:05,400\nHello, this is my reflection\n</track></media>'
    '</media_tracks>')

PAGE = (b"<html><head><title>A page</title></head><body>"
        b"<h2>Reading</h2><h4>Skipped to</h4>"
        b"<table><tr><th>Week</th><th>Text</th></tr>"
        b"<tr><td>1</td><td>Bunn</td></tr></table>"
        b"<p>A writer chooses a form before a sentence.</p></body></html>")


def _pdf(title="A Real Title"):
    import pypdf
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=200, height=200)
    if title:
        writer.add_metadata({"/Title": title})
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _make(tmp_path, extra=None, name="course.imscc", tracks=EMPTY_TRACKS):
    path = tmp_path / name
    members = {
        "imsmanifest.xml": MANIFEST,
        "wiki_content/one.html": PAGE,
        "web_resources/reading.pdf": _pdf(),
        "web_resources/clip.mp4": b"not really video" * 50,
        "course_settings/media_tracks.xml": tracks,
    }
    members.update(extra or {})
    with zipfile.ZipFile(path, "w") as z:
        for inner, body in members.items():
            z.writestr(inner, body)
    return path


def _bytes(path, inner):
    with zipfile.ZipFile(path) as z:
        return z.read(inner)


# ---------- the happy path ----------

def test_pages_and_pdfs_are_fixed_and_everything_else_is_byte_identical(
        tmp_path):
    src = _make(tmp_path)
    dst = tmp_path / "out.imscc"

    report = repack.remediate_cartridge(src, dst, language="en")

    assert b'lang="en"' in _bytes(dst, "wiki_content/one.html")
    assert _bytes(dst, "web_resources/clip.mp4") == \
        _bytes(src, "web_resources/clip.mp4")
    assert report.changed == 2
    assert report.identical == report.members - 2


def test_the_manifest_is_copied_through_untouched(tmp_path):
    """Nothing the manifest points at may move: every id and reference
    inside the cartridge still has to mean what it meant."""
    src = _make(tmp_path)
    dst = tmp_path / "out.imscc"

    repack.remediate_cartridge(src, dst, language="en")

    assert _bytes(dst, "imsmanifest.xml") == _bytes(src, "imsmanifest.xml")


def test_every_member_keeps_its_name_and_order_and_none_is_added(tmp_path):
    """A member the manifest does not list is the sort of thing an
    importer either ignores or chokes on, so the change log lives beside
    the cartridge and never inside it."""
    src = _make(tmp_path)
    dst = tmp_path / "out.imscc"

    repack.remediate_cartridge(src, dst, language="en")

    with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst) as b:
        assert a.namelist() == b.namelist()


def test_no_word_moved_in_what_was_written(tmp_path):
    src = _make(tmp_path)
    dst = tmp_path / "out.imscc"

    report = repack.remediate_cartridge(src, dst, language="en")

    assert report.holds
    assert report.verified
    assert report.text_moved_in_output == []
    assert report.verified_chars > 0
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst) as b:
        for inner in ("wiki_content/one.html", "web_resources/reading.pdf"):
            assert invariance.text_of(inner, a.read(inner)) == \
                invariance.text_of(inner, b.read(inner))


def test_a_second_pass_over_the_result_changes_nothing(tmp_path):
    """The rule every pass in this codebase follows, held for the whole
    cartridge: a remediation that gains something on each run reports work
    that is not there."""
    src = _make(tmp_path)
    once = tmp_path / "once.imscc"
    twice = tmp_path / "twice.imscc"
    repack.remediate_cartridge(src, once, language="en")

    again = repack.remediate_cartridge(once, twice, language="en")

    assert again.changed == 0
    assert _bytes(twice, "wiki_content/one.html") == \
        _bytes(once, "wiki_content/one.html")


def test_no_language_given_means_none_is_written_and_the_gap_is_reported(
        tmp_path):
    src = _make(tmp_path)
    dst = tmp_path / "out.imscc"

    report = repack.remediate_cartridge(src, dst)

    assert b"lang=" not in _bytes(dst, "wiki_content/one.html")
    assert any(item["kind"] == "no-language" for item in report.worklist)


# ---------- the screen refuses ----------

def test_a_cartridge_carrying_student_work_is_refused_and_leaves_nothing(
        tmp_path):
    """The reason the screen runs first. Nothing is processed, nothing is
    kept and nothing partial is left lying around."""
    src = _make(tmp_path, tracks=STUDENT_TRACKS)
    dst = tmp_path / "out.imscc"

    with pytest.raises(repack.Refusal) as caught:
        repack.remediate_cartridge(src, dst, language="en")

    assert not dst.exists()
    assert not Path(str(dst) + ".partial").exists()
    assert "student work" in str(caught.value)


def test_the_refusal_names_where_and_never_what(tmp_path):
    """A tool that answers "is there student data here?" by printing the
    student data is not a safeguard."""
    src = _make(tmp_path, tracks=STUDENT_TRACKS)

    with pytest.raises(repack.Refusal) as caught:
        repack.remediate_cartridge(src, tmp_path / "out.imscc")

    said = str(caught.value)
    assert "media_tracks.xml" in said
    assert "my reflection" not in said


def test_a_zip_that_is_not_a_cartridge_is_refused(tmp_path):
    path = tmp_path / "x.imscc"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("readme.txt", "just files")

    with pytest.raises(repack.Refusal):
        repack.remediate_cartridge(path, tmp_path / "out.imscc")


# ---------- a fix that moves a word never ships ----------

def test_a_fix_that_would_move_a_word_is_dropped_for_that_file(
        tmp_path, monkeypatch):
    """One bad page does not cost the cartridge its run, and it does not
    ship a reworded course either: the file is delivered exactly as it
    arrived and listed."""
    def rewording(data, language=None):
        return remediate.Result(
            data=data.replace(b"chooses", b"picks"),
            changes=[remediate.Change(kind="lang", count=1)])

    monkeypatch.setattr(remediate, "fix_html", rewording)
    src = _make(tmp_path)
    dst = tmp_path / "out.imscc"

    report = repack.remediate_cartridge(src, dst, language="en")

    assert report.text_moved == ["wiki_content/one.html"]
    assert _bytes(dst, "wiki_content/one.html") == \
        _bytes(src, "wiki_content/one.html")
    assert report.holds


def test_a_page_that_will_not_parse_is_shipped_as_it_arrived(tmp_path):
    src = _make(tmp_path, extra={"wiki_content/bad.html": b"\x00\x01 junk"})
    dst = tmp_path / "out.imscc"

    report = repack.remediate_cartridge(src, dst, language="en")

    assert _bytes(dst, "wiki_content/bad.html") == b"\x00\x01 junk"
    assert report.holds


# ---------- cancelling ----------

def test_stopping_part_way_leaves_nothing_behind(tmp_path):
    src = _make(tmp_path)
    dst = tmp_path / "out.imscc"
    calls = {"n": 0}

    def stop():
        calls["n"] += 1
        return calls["n"] > 2

    with pytest.raises(repack.Stopped):
        repack.remediate_cartridge(src, dst, language="en", stop=stop)

    assert not dst.exists()
    assert not Path(str(dst) + ".partial").exists()


# ---------- the report ----------

def test_the_summary_carries_the_denominator_and_what_it_could_not_read(
        tmp_path):
    src = _make(tmp_path, extra={"web_resources/slides.pptx": b"PK\x03\x04"})

    report = repack.remediate_cartridge(src, tmp_path / "o.imscc", "en")
    said = report.summary()

    assert "characters of text compared" in said
    assert "0 changed" in said
    assert "hold text this cannot read" in said


def test_the_markdown_leads_with_the_warning_about_re_importing(tmp_path):
    """The thing most likely to cause real damage if it is missed."""
    src = _make(tmp_path)
    report = repack.remediate_cartridge(src, tmp_path / "o.imscc", "en")

    text = repack.render_markdown(report)

    assert "orphans" in text.split("## What was checked")[0]
    assert "What is still owed" in text
    assert "—" not in text


def test_the_worklist_says_what_is_owed_and_where(tmp_path):
    src = _make(tmp_path, extra={
        "wiki_content/frame.html":
            b'<html><body><iframe src="https://x/y"></iframe></body></html>'})

    report = repack.remediate_cartridge(src, tmp_path / "o.imscc", "en")

    kinds = {item["kind"]: item for item in report.worklist}
    assert "iframe-without-title" in kinds
    assert "wiki_content/frame.html" in kinds["iframe-without-title"]["files"]


# ---------- as a job ----------

@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(jobs, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(jobs, "WORKER_ENABLED", False)
    db.init_db()
    return tmp_path


def _queue(workspace, cart_path, language="en"):
    job_id = jobs.create("remediate_cartridge", "a course",
                         {"language": language}, None)
    target = jobs.staging_dir(job_id) / "course.imscc"
    target.write_bytes(Path(cart_path).read_bytes())
    jobs.release(job_id)
    return job_id


def test_the_job_writes_the_cartridge_and_both_reports(workspace, tmp_path):
    job_id = _queue(workspace, _make(tmp_path))

    assert jobs.run_job(job_id) == jobs.DONE

    out = jobs.results_dir(job_id)
    assert (out / "remediated.imscc").is_file()
    assert (out / "report.json").is_file()
    assert (out / "report.md").is_file()


def test_the_upload_is_deleted_when_the_job_ends_and_the_result_is_not(
        workspace, tmp_path):
    job_id = _queue(workspace, _make(tmp_path))

    jobs.run_job(job_id)

    assert not jobs.staging_dir(job_id).exists()
    assert jobs.results_dir(job_id).exists()


def test_a_refusal_is_a_message_and_not_a_traceback(workspace, tmp_path):
    """A refusal is the job working, not breaking. A traceback under it
    would read as a defect."""
    job_id = _queue(workspace, _make(tmp_path, tracks=STUDENT_TRACKS))

    assert jobs.run_job(job_id) == jobs.FAILED

    error = jobs.get(job_id)["error"]
    assert "student work" in error
    assert "Traceback" not in error


def test_a_refused_course_leaves_no_result_and_no_upload(workspace, tmp_path):
    job_id = _queue(workspace, _make(tmp_path, tracks=STUDENT_TRACKS))

    jobs.run_job(job_id)

    assert not jobs.results_dir(job_id).exists()
    assert not jobs.staging_dir(job_id).exists()


def test_a_cartridge_with_thousands_of_members_does_not_rewrite_a_list_each_time(
        workspace):
    """`step` appends and rewrites the whole item list, which is right for
    a chapter and wrong for a course member."""
    job_id = jobs.create("remediate_cartridge", "x", {}, None)
    progress = jobs.Progress(job_id=job_id)

    for n in range(50):
        progress.tick(n, 50)

    job = jobs.get(job_id)
    assert job["done"] == 49
    assert job["total"] == 50
    assert jobs.items(job) == []


def test_summary_items_do_not_overwrite_a_ticked_count(workspace):
    """Found by running the real 373 MB cartridge: 440 members were
    handled and the job page read 7 of 440, because `step` set the count
    to the length of the item list and the summary recorded seven."""
    job_id = jobs.create("remediate_cartridge", "x", {}, None)
    progress = jobs.Progress(job_id=job_id)

    progress.tick(440, 440)
    for n in range(7):
        progress.step(f"summary {n}", "pass")

    job = jobs.get(job_id)
    assert (job["done"], job["total"]) == (440, 440)
    assert len(jobs.items(job)) == 7


def test_a_job_that_never_ticks_still_counts_its_items(workspace):
    job_id = jobs.create("remediate_cartridge", "x", {}, None)
    progress = jobs.Progress(job_id=job_id)

    progress.step("one", "pass")
    progress.step("two", "pass")

    assert jobs.get(job_id)["done"] == 2


def test_a_finished_cartridge_job_reports_every_member(workspace, tmp_path):
    job_id = _queue(workspace, _make(tmp_path))

    jobs.run_job(job_id)

    job = jobs.get(job_id)
    assert job["done"] == job["total"] > 0


# ---------- the routes ----------

@pytest.fixture
def client(workspace):
    import app as app_module
    application = app_module.create_app()
    application.config["LOGIN_DISABLED"] = True
    return application.test_client()


def _post(client, name, data, **form):
    return client.post("/remediate", content_type="multipart/form-data",
                       data={"cartridge": (io.BytesIO(data), name), **form})


def test_the_form_is_served(client):
    body = client.get("/remediate").data.decode("utf-8")

    assert "Remediate a course cartridge" in body
    assert "does not change a word" in body
    assert "turned away" in body
    assert "orphans" in body


def test_an_upload_is_staged_and_queued(client, tmp_path):
    data = _make(tmp_path).read_bytes()

    response = _post(client, "course.imscc", data, language="en")

    assert response.status_code == 302
    job = jobs.recent()[0]
    assert job["kind"] == "remediate_cartridge"
    assert job["state"] == jobs.QUEUED
    assert jobs.payload(job)["language"] == "en"
    assert (jobs.staging_dir(job["id"]) / "course.imscc").is_file()


def test_something_that_is_not_a_cartridge_is_turned_down_at_the_door(client):
    response = _post(client, "notes.docx", b"x", language="en")

    assert response.status_code == 302
    assert jobs.recent() == []


@pytest.mark.parametrize("bad", ["english", "e", "en_US", "<script>"])
def test_a_language_that_is_not_a_code_is_refused(client, tmp_path, bad):
    """It is written into every page of somebody's course, so it is not
    free text."""
    data = _make(tmp_path).read_bytes()

    _post(client, "course.imscc", data, language=bad)

    assert jobs.recent() == []


@pytest.mark.parametrize("good", ["en", "es", "fr-CA", "zh-Hant"])
def test_ordinary_language_codes_are_accepted(client, tmp_path, good):
    data = _make(tmp_path).read_bytes()

    _post(client, "course.imscc", data, language=good)

    assert len(jobs.recent()) == 1


def test_only_the_three_named_results_can_be_downloaded(client, tmp_path):
    """A fixed map and never a path taken from the request."""
    job_id = _queue(tmp_path, _make(tmp_path))
    jobs.run_job(job_id)

    assert client.get(f"/jobs/{job_id}/download/cartridge").status_code == 200
    assert client.get(f"/jobs/{job_id}/download/report").status_code == 200
    assert client.get(f"/jobs/{job_id}/download/report-json").status_code == 200
    for bad in ("..", "course.imscc", "%2e%2e%2fdb", "staging"):
        assert client.get(f"/jobs/{job_id}/download/{bad}").status_code == 404


def test_a_download_for_a_job_that_does_not_exist_is_a_404(client):
    assert client.get("/jobs/9999/download/cartridge").status_code == 404


def test_the_job_page_offers_the_downloads_and_a_way_to_delete_them(
        client, tmp_path):
    job_id = _queue(tmp_path, _make(tmp_path))
    jobs.run_job(job_id)

    body = client.get(f"/jobs/{job_id}").data.decode("utf-8")

    assert "remediated.imscc" in body
    assert "report.md" in body
    assert "Delete these from the server" in body
    assert "never backed up" in body


def test_discarding_removes_the_result(client, tmp_path):
    job_id = _queue(tmp_path, _make(tmp_path))
    jobs.run_job(job_id)

    client.post(f"/jobs/{job_id}/discard")

    assert not jobs.results_dir(job_id).exists()
    assert client.get(f"/jobs/{job_id}/download/cartridge").status_code == 404


# ---------- request limits ----------

def test_each_route_is_held_to_its_own_ceiling(monkeypatch):
    """Raising what a cartridge may weigh must not raise what a batch of
    PDFs may, or what a single manuscript may."""
    import app as app_module
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 1)
    monkeypatch.setattr(app_module, "MAX_BATCH_BYTES", 10)
    monkeypatch.setattr(app_module, "MAX_CARTRIDGE_BYTES", 100)

    assert app_module._request_limit("remediate_upload") == 100
    assert app_module._request_limit("assess_archive") == 10
    assert app_module._request_limit("upload_article") == 1


def test_the_cartridge_endpoint_named_as_exempt_exists(client):
    """By endpoint name rather than by path, so a rename detaches it
    loudly: the route would start refusing a cartridge while every other
    route silently kept its limit."""
    import app as app_module

    for endpoint in app_module.CARTRIDGE_ENDPOINTS:
        assert endpoint in client.application.view_functions
