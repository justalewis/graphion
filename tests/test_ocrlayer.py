"""A text layer under a scanned page, and the proof that the page did not move.

R4. Every other pass proves it changed no word by comparing the visible text
before and after. That cannot apply here, because the point is that text
appears where there was none. The proof is the other half of the same
promise, that the page looks identical, checked by rendering each layered
page before and after.

The logic is tested with Tesseract faked so it runs everywhere. The tests
that read real text run only where Tesseract exists and skip where it does
not, which is the convention every optional tool here follows.
"""
import io
import os
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import ocr
import ocrlayer
import remediate
import repack

# The Windows installer from UB-Mannheim does not put the binary on PATH, so
# without this the real-OCR tests skip on the one machine where they could
# run. Set at import because the skip marker is evaluated at collection.
_DEFAULT = (Path(os.environ.get("LOCALAPPDATA", "")) / "Programs"
            / "Tesseract-OCR" / "tesseract.exe")
if not os.environ.get(ocr.TESSERACT_ENV) and _DEFAULT.is_file():
    os.environ[ocr.TESSERACT_ENV] = str(_DEFAULT)

needs_tesseract = pytest.mark.skipif(
    not ocr.available() or "eng" not in ocrlayer.installed_languages(),
    reason="Tesseract with the English model is not installed here")


def _scan(text="Reading rhetorically", size=(1300, 300)) -> bytes:
    """A PDF holding only a picture of some words, which is what a scan is."""
    from PIL import Image, ImageDraw, ImageFont
    image = Image.new("L", size, 255)
    ImageDraw.Draw(image).text((30, 90), text, fill=0,
                               font=ImageFont.load_default(size=80))
    out = io.BytesIO()
    image.convert("RGB").save(out, "PDF", resolution=150)
    return out.getvalue()


def _text_pdf(tmp_path) -> bytes:
    import conversion
    typ = tmp_path / "t.typ"
    typ.write_text('#set text(lang: "en")\n= A page of real text\n\n'
                   "This page already carries a text layer of its own, "
                   "with enough words on it to count as one.", encoding="utf-8")
    out = tmp_path / "t.pdf"
    conversion._compile_typst(typ, out, root=tmp_path)
    return out.read_bytes()


def _combine(*pdfs) -> bytes:
    import pypdf
    writer = pypdf.PdfWriter()
    for data in pdfs:
        for page in pypdf.PdfReader(io.BytesIO(data)).pages:
            writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _fake_layer() -> bytes:
    """A stand-in for Tesseract's text-only page, sized in its own units."""
    import pypdf
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=1000, height=300)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


@pytest.fixture
def faked(monkeypatch):
    """Tesseract present, English installed, and every page read as clean."""
    monkeypatch.setattr(ocr, "tesseract_binary_available", lambda: True)
    monkeypatch.setattr(ocrlayer, "installed_languages", lambda: {"eng"})
    monkeypatch.setattr(ocrlayer, "_read_page",
                        lambda image, model: (_fake_layer(), [95.0, 90.0]))


# ---------- languages ----------

def test_a_document_language_maps_to_the_model_that_is_installed(monkeypatch):
    monkeypatch.setattr(ocrlayer, "installed_languages",
                        lambda: {"eng", "spa"})

    assert ocrlayer.tesseract_language("en") == "eng"
    assert ocrlayer.tesseract_language("en-US") == "eng"
    assert ocrlayer.tesseract_language("es") == "spa"


def test_a_language_whose_model_is_not_installed_maps_to_nothing(monkeypatch):
    monkeypatch.setattr(ocrlayer, "installed_languages", lambda: {"eng"})

    assert ocrlayer.tesseract_language("fr") is None
    assert ocrlayer.tesseract_language("xx") is None
    assert ocrlayer.tesseract_language(None) is None
    assert ocrlayer.tesseract_language("") is None


# ---------- which pages ----------

def test_a_picture_only_page_needs_reading():
    assert ocrlayer.pages_needing_ocr(_scan()) == [0]


def test_a_page_with_real_text_does_not(tmp_path):
    assert ocrlayer.pages_needing_ocr(_text_pdf(tmp_path)) == []


def test_only_the_scanned_pages_of_a_mixed_file_are_named(tmp_path):
    mixed = _combine(_text_pdf(tmp_path), _scan(), _text_pdf(tmp_path))

    assert ocrlayer.pages_needing_ocr(mixed) == [1]


# ---------- what it refuses to do ----------

def test_with_no_tesseract_the_file_is_returned_and_the_gap_is_named(
        monkeypatch):
    monkeypatch.setattr(ocr, "tesseract_binary_available", lambda: False)
    data = _scan()

    result = ocrlayer.add_text_layer(data, "en")

    assert result.data == data
    assert not result.changed
    assert result.owed[0].kind == "ocr-unavailable"


def test_the_language_is_never_guessed(faked):
    """Reading Spanish with the English model produces confident nonsense,
    which is the rule `lang` follows everywhere else here."""
    data = _scan()

    result = ocrlayer.add_text_layer(data, None)

    assert result.data == data
    assert result.owed[0].kind == "ocr-needs-a-language"


def test_a_language_with_no_installed_model_is_refused(faked):
    data = _scan()

    result = ocrlayer.add_text_layer(data, "fr")

    assert result.data == data
    assert result.owed[0].kind == "ocr-language-unavailable"


def test_a_rotated_page_is_skipped_and_reported(faked):
    """Tesseract reads the page as rendered, in its rotated orientation,
    while the layer is placed in unrotated page space, so the words would
    land in the wrong places and nothing downstream would notice."""
    import pypdf
    reader = pypdf.PdfReader(io.BytesIO(_scan()))
    writer = pypdf.PdfWriter(clone_from=reader)
    writer.pages[0].rotate(90)
    out = io.BytesIO()
    writer.write(out)

    result = ocrlayer.add_text_layer(out.getvalue(), "en")

    assert not result.changed
    assert result.pages[0].outcome == "skipped"
    assert "rotated" in result.pages[0].note
    assert any(o.kind == "ocr-page-skipped" for o in result.owed)


def test_a_page_with_no_words_gets_no_layer_and_is_not_owed_proofing(
        faked, monkeypatch):
    monkeypatch.setattr(ocrlayer, "_read_page",
                        lambda image, model: (_fake_layer(), []))
    data = _scan()

    result = ocrlayer.add_text_layer(data, "en")

    assert result.data == data
    assert result.pages[0].outcome == "blank"
    assert not any(o.kind == "ocr-needs-proofing" for o in result.owed)


def test_a_page_whose_appearance_moved_is_dropped(faked, monkeypatch):
    """The proof, exercised. A page that looks different after the layer is
    laid under it is not shipped with one."""
    seen = {"n": 0}

    def drifting(data, pages):
        seen["n"] += 1
        return {i: f"look-{seen['n']}" for i in pages}

    monkeypatch.setattr(ocrlayer, "signatures", drifting)
    data = _scan()

    result = ocrlayer.add_text_layer(data, "en")

    assert result.pages[0].outcome == "dropped"
    assert not result.changed
    assert result.data == data
    assert any(o.kind == "ocr-page-skipped" for o in result.owed)


# ---------- what it records ----------

def test_confidence_is_recorded_per_page_and_the_worst_are_named(faked):
    result = ocrlayer.add_text_layer(_combine(_scan(), _scan()), "en")

    assert [p.outcome for p in result.pages] == ["layered", "layered"]
    assert result.pages[0].words == 2
    assert result.pages[0].mean_confidence == 92.5
    owed = next(o for o in result.owed if o.kind == "ocr-needs-proofing")
    assert "p1 (92.5)" in owed.detail


def test_every_layer_owes_proofing_whatever_its_score(faked, monkeypatch):
    """Measured on real scans: the page that scored 92 percent still read
    "Schoo! of Engineering". An average hides visible errors, so a high
    score is never counted as done."""
    monkeypatch.setattr(ocrlayer, "_read_page",
                        lambda image, model: (_fake_layer(), [99.9] * 40))

    result = ocrlayer.add_text_layer(_scan(), "en")

    assert any(o.kind == "ocr-needs-proofing" for o in result.owed)
    assert "Schoo!" in next(o for o in result.owed
                            if o.kind == "ocr-needs-proofing").detail


# ---------- with the real thing ----------

@needs_tesseract
def test_a_real_scan_becomes_readable_and_looks_identical():
    import pypdf
    data = _scan()
    before_image = pypdf.PdfReader(io.BytesIO(data)).pages[0].images[0].data

    result = ocrlayer.add_text_layer(data, "en")

    assert result.changed
    page = pypdf.PdfReader(io.BytesIO(result.data)).pages[0]
    text = (page.extract_text() or "").lower()
    assert "reading" in text and "rhetorically" in text
    # The scanned picture is the same bytes it arrived as, not re-encoded.
    assert page.images[0].data == before_image
    assert ocrlayer.signatures(data, [0]) == ocrlayer.signatures(result.data, [0])


@needs_tesseract
def test_a_second_pass_has_nothing_left_to_read():
    once = ocrlayer.add_text_layer(_scan(), "en")

    again = ocrlayer.add_text_layer(once.data, "en")

    assert ocrlayer.pages_needing_ocr(once.data) == []
    assert not again.changed


@needs_tesseract
def test_a_page_that_already_had_text_is_untouched(tmp_path):
    mixed = _combine(_text_pdf(tmp_path), _scan())
    before = ocrlayer.fingerprint(mixed, [1])

    result = ocrlayer.add_text_layer(mixed, "en")

    assert result.layered == [1]
    assert ocrlayer.fingerprint(result.data, [1]) == before


# ---------- inside a cartridge ----------

MANIFEST = ('<?xml version="1.0"?><manifest xmlns="http://www.imsglobal.org/'
            'xsd/imsccv1p1/imscp_v1p1"/>')


def _cartridge(tmp_path, pdf):
    path = tmp_path / "c.imscc"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("imsmanifest.xml", MANIFEST)
        z.writestr("web_resources/scan.pdf", pdf)
    return path


def test_without_the_option_scanned_pages_are_still_reported(tmp_path):
    """A report that silently omitted them would read as a clean bill of
    health for a file a screen reader cannot read at all."""
    src = _cartridge(tmp_path, _scan())

    report = repack.remediate_cartridge(src, tmp_path / "o.imscc", "en")

    kinds = {item["kind"] for item in report.worklist}
    assert "scanned-pages" in kinds


def test_the_worklist_uses_one_sentence_per_kind_not_the_first_files(
        tmp_path):
    """The worklist keeps one detail per kind, so a detail naming one file's
    pages would read as the whole archive's."""
    src = _cartridge(tmp_path, _scan())

    report = repack.remediate_cartridge(src, tmp_path / "o.imscc", "en")

    item = next(i for i in report.worklist if i["kind"] == "scanned-pages")
    assert "1 page" not in item["detail"]
    assert "text layer option" in item["detail"]


@needs_tesseract
def test_a_cartridge_scan_is_layered_proved_and_listed(tmp_path):
    src = _cartridge(tmp_path, _scan())
    dst = tmp_path / "o.imscc"

    report = repack.remediate_cartridge(src, dst, "en", ocr=True)

    assert report.holds and report.verified
    assert report.text_moved == []
    with zipfile.ZipFile(dst) as z:
        import pypdf
        page = pypdf.PdfReader(io.BytesIO(z.read("web_resources/scan.pdf"))).pages[0]
        assert "rhetorically" in (page.extract_text() or "").lower()
    kinds = {i["kind"] for i in report.worklist}
    assert "ocr-needs-proofing" in kinds
    assert "scanned-pages" not in kinds
    assert report.totals_changed.get("ocr-text-layer") == 1
    # Said in the summary, because "0 characters compared" alone reads as
    # if nothing was checked when the appearance of the page was.
    assert report.verified_pages == 1
    assert "appearance of 1 scanned page" in report.summary()


def test_a_layer_whose_proof_fails_ships_as_it_arrived(tmp_path, faked,
                                                       monkeypatch):
    """Per file, the same safety net the text check gives every other fix."""
    calls = {"n": 0}

    def drifting(data, pages):
        calls["n"] += 1
        return ({i: f"look-{calls['n']}" for i in pages}, "")

    monkeypatch.setattr(ocrlayer, "fingerprint", drifting)
    src = _cartridge(tmp_path, _scan())
    dst = tmp_path / "o.imscc"

    report = repack.remediate_cartridge(src, dst, "en", ocr=True)

    assert report.text_moved == ["web_resources/scan.pdf"]
    with zipfile.ZipFile(src) as a, zipfile.ZipFile(dst) as b:
        assert a.read("web_resources/scan.pdf") == b.read("web_resources/scan.pdf")


# ---------- the form ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    import db
    import jobs
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    monkeypatch.setattr(jobs, "RESULTS_DIR", tmp_path / "results")
    monkeypatch.setattr(jobs, "WORKER_ENABLED", False)
    db.init_db()
    import app as app_module
    application = app_module.create_app()
    application.config["LOGIN_DISABLED"] = True
    return application.test_client()


def _post(client, **form):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("imsmanifest.xml", MANIFEST)
    return client.post("/remediate", content_type="multipart/form-data",
                       data={"cartridge": (io.BytesIO(buf.getvalue()),
                                           "c.imscc"), **form})


def test_the_form_greys_the_option_out_where_tesseract_is_absent(
        client, monkeypatch):
    monkeypatch.setattr(ocr, "available", lambda: False)

    body = client.get("/remediate").data.decode("utf-8")

    assert "Tesseract is not installed on this server" in body
    assert "Every recognised page still needs proofing" in body


def test_asking_for_ocr_where_it_cannot_run_is_refused_at_the_door(
        client, monkeypatch):
    """Each of these is known now, and a long job that cannot do what was
    asked is the worst place to find out."""
    import jobs
    monkeypatch.setattr(ocr, "available", lambda: False)

    _post(client, language="en", ocr="on")

    assert jobs.recent() == []


def test_asking_for_ocr_with_no_language_is_refused(client, monkeypatch):
    import jobs
    monkeypatch.setattr(ocr, "available", lambda: True)

    _post(client, ocr="on")

    assert jobs.recent() == []


def test_asking_for_a_language_with_no_model_is_refused(client, monkeypatch):
    import jobs
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocrlayer, "installed_languages", lambda: {"eng"})

    _post(client, language="fr", ocr="on")

    assert jobs.recent() == []


def test_a_valid_request_for_ocr_reaches_the_job(client, monkeypatch):
    import jobs
    monkeypatch.setattr(ocr, "available", lambda: True)
    monkeypatch.setattr(ocrlayer, "installed_languages", lambda: {"eng"})

    _post(client, language="en", ocr="on")

    job = jobs.recent()[0]
    assert jobs.payload(job)["ocr"] is True


def test_without_the_option_the_job_is_not_asked_to_read_pages(client):
    import jobs

    _post(client, language="en")

    assert jobs.payload(jobs.recent()[0])["ocr"] is False
