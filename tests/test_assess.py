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
    of a conformance reading drifts from the first, which is why what a
    packet declares is read by `pdf_tags`, beside the code that writes one.
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


# ---------- what a checker confirms, which is a second fact ----------

def _verapdf_report(rules=(), compliant=None, results=None):
    """A report shaped the way verapdf writes one.

    Built here rather than captured from a run, so the suite says what it
    depends on: `validationResult[0].compliant` and the rule summaries
    under `details`. A canned report is also the only way to test the
    cases a working installation never produces.
    """
    summaries = [
        {"ruleStatus": "FAILED", "specification": "ISO 14289-1:2014",
         "clause": clause, "testNumber": number, "status": "failed",
         "failedChecks": instances, "tags": ["syntax"],
         "description": description}
        for clause, number, instances, description in rules
    ]
    if compliant is None:
        compliant = not summaries
    if results is None:
        results = [{
            "details": {"passedRules": 106 - len(summaries),
                        "failedRules": len(summaries),
                        "passedChecks": 57886,
                        "failedChecks": sum(s["failedChecks"] for s in summaries),
                        "ruleSummaries": summaries},
            "jobEndStatus": "normal",
            "profileName": "PDF/UA-1 validation profile",
            "compliant": compliant}]
    return {"report": {"jobs": [{"itemDetails": {"name": "x.pdf", "size": 1},
                                 "validationResult": results}]}}


def _verapdf_says(monkeypatch, report, passed=True):
    monkeypatch.setattr(assess.validators, "verapdf_available", lambda: True)
    monkeypatch.setattr(assess.validators, "run_verapdf",
                        lambda path: (passed, report))


# The eleven rules a plain typeset chapter of this archive breaks, with the
# instance counts verapdf actually reported for it. The two largest are the
# point: 727 runs of text with no language and 678 pieces of content neither
# tagged nor marked as an artifact, both of which one remediation answers.
UNTAGGED_RULES = (
    ("7.2", 34, 727, "Natural language for text in page content shall be determined"),
    ("7.1", 3, 678, "Content shall be marked as Artifact or tagged as real content"),
    ("7.2", 30, 31, "Natural language for text in ActualText shall be determined"),
    ("7.1", 6, 13, "A circular mapping shall not exist"),
    ("7.18.5", 2, 4, "Links shall contain an alternate description"),
    ("7.18.1", 2, 4, "An annotation shall have either Contents or an Alt entry"),
    ("6.2", 1, 1, "MarkInfo shall contain Marked, whose value shall be true"),
    ("7.1", 10, 1, "ViewerPreferences shall contain DisplayDocTitle, true"),
    ("7.1", 8, 1, "The document catalog shall include a Lang entry"),
    ("7.1", 2, 1, "The document catalog shall include a MarkInfo dictionary"),
    ("7.1", 12, 1, "Metadata shall contain a dc:title"),
)


def test_a_declaration_that_holds_up_is_confirmed(described, monkeypatch):
    _verapdf_says(monkeypatch, _verapdf_report())

    result = assess.assess_pdf(described, validate=True)

    assert result.conformant
    assert result.verapdf is True
    assert result.checked
    assert not result.contradicted


def test_a_declaration_that_does_not_hold_up_is_the_case_to_read_first(
        described, monkeypatch):
    """Six volumes of this archive bound galleys that each declared
    PDF/UA-1 into issues that were not tagged at all. A file that states
    conformance has already been through somebody's pipeline, so what it is
    short of is usually narrow and nobody has been told."""
    _verapdf_says(monkeypatch, _verapdf_report(UNTAGGED_RULES[:2]),
                  passed=False)

    result = assess.assess_pdf(described, validate=True)

    assert result.conformant
    assert result.verapdf is False
    assert result.contradicted
    assert any("declares PDF/UA-1 and does not pass it" in note
               for note in result.notes)


def test_a_checker_that_is_not_installed_reaches_no_verdict(
        described, monkeypatch):
    """The failure this whole register exists to avoid. A missing tool
    reading as a pass would report an archive as checked when nothing ran,
    and reading as a failure would blame the document for the laptop."""
    monkeypatch.setattr(assess.validators, "verapdf_available", lambda: False)

    result = assess.assess_pdf(described, validate=True)

    assert result.verapdf is None
    assert not result.checked
    assert not result.contradicted
    assert any("not on PATH" in note for note in result.notes)


def test_a_tool_that_could_not_process_the_file_is_not_a_failing_file(
        described, monkeypatch):
    """verapdf exits non-zero both for a file that does not comply and for
    one it could not read, so the verdict comes off the report and not off
    the exit code."""
    _verapdf_says(monkeypatch, _verapdf_report(results=[]), passed=False)

    result = assess.assess_pdf(described, validate=True)

    assert result.verapdf is None
    assert any("has not been checked" in note for note in result.notes)


def test_failed_rules_are_ordered_by_size_and_capped(described, monkeypatch):
    _verapdf_says(monkeypatch, _verapdf_report(UNTAGGED_RULES), passed=False)

    result = assess.assess_pdf(described, validate=True)

    assert result.failed_clause_count == len(UNTAGGED_RULES)
    assert len(result.failed_clauses) <= assess.MAX_FAILED_CLAUSES
    assert result.failed_clauses[0].instances == 727
    assert result.failed_clauses[0].label == "7.2-34"


def test_an_instance_count_is_not_a_quantity_of_work(described, monkeypatch):
    """1,462 failed checks across 11 rules is one untagged chapter, and 678
    of those are content neither tagged nor marked as an artifact, which
    tagging the document answers at once. None of it may reach a work
    total, which is the number a journal is quoted from."""
    _verapdf_says(monkeypatch, _verapdf_report(UNTAGGED_RULES), passed=False)

    plain = assess.assess_pdf(described)
    checked = assess.assess_pdf(described, validate=True)

    assert checked.undescribed_figures == plain.undescribed_figures
    assert checked.figures_found == plain.figures_found
    assert any("not a quantity of work" in note for note in checked.notes)


def test_nothing_is_checked_unless_it_is_asked_for(described, monkeypatch):
    def _refuse():
        raise AssertionError("verapdf ran without --validate")

    monkeypatch.setattr(assess.validators, "verapdf_available", _refuse)

    result = assess.assess_pdf(described)

    assert result.verapdf is None
    assert any("pass --validate" in note for note in result.notes)


# ---------- the second checker, over HTML ----------

def _page(tmp_path, name="page.html"):
    target = tmp_path / name
    target.write_text(
        "<!doctype html><html lang='en'><head><title>A page</title></head>"
        "<body><h1>A page</h1></body></html>", encoding="utf-8")
    return target


def test_a_page_nobody_checked_does_not_read_as_a_clean_page(tmp_path):
    result = assess.assess_html(_page(tmp_path), validate=False)

    assert result.clean is None
    assert not result.checked
    assert "--validate" in result.pa11y_note


def test_a_checker_that_is_not_installed_does_not_make_a_page_clean(
        tmp_path, monkeypatch):
    monkeypatch.setattr(assess.validators, "pa11y_available", lambda: False)

    result = assess.assess_html(_page(tmp_path), validate=True)

    assert result.clean is None
    assert not result.checked
    assert "not on PATH" in result.pa11y_note


def test_findings_are_counted_by_kind_and_grouped_by_code(
        tmp_path, monkeypatch):
    issues = [
        {"type": "error", "code": "WCAG2AA.1_1_1.H37",
         "message": "Img element missing an alt attribute"},
        {"type": "error", "code": "WCAG2AA.1_1_1.H37",
         "message": "Img element missing an alt attribute"},
        {"type": "warning", "code": "WCAG2AA.1_3_1.H42", "message": "Heading"},
        {"type": "notice", "code": "WCAG2AA.4_1_2.H91", "message": "Label"},
    ]
    monkeypatch.setattr(assess.validators, "pa11y_available", lambda: True)
    monkeypatch.setattr(assess.validators, "run_pa11y",
                        lambda path: (False, issues))

    result = assess.assess_html(_page(tmp_path), validate=True)

    assert result.clean is False
    assert (result.errors, result.warnings, result.notices) == (2, 1, 1)
    assert result.codes[0] == ("WCAG2AA.1_1_1.H37", 2)


def test_the_page_is_read_whether_or_not_a_checker_runs(tmp_path):
    """Reading costs what reading a file costs, so it is not behind the
    flag that starts a headless browser."""
    target = tmp_path / "page.html"
    target.write_text(
        "<!doctype html><html lang='en'><head><title>A page</title></head>"
        "<body><main><h1>A page</h1>"
        "<p><img src='fig.png' /></p></main></body></html>",
        encoding="utf-8")

    result = assess.assess_html(target)

    assert not result.checked
    assert result.images == 1
    assert result.images_no_alt == 1


def test_the_html_pass_says_what_it_still_cannot_know(tmp_path, monkeypatch):
    """The page is read now, which makes it matter more that two things in
    it are not readable: whether the words in a picture are words, and a
    figure set as a CSS background, which is not in the markup at all."""
    monkeypatch.setattr(assess.validators, "pa11y_available", lambda: True)
    monkeypatch.setattr(assess.validators, "run_pa11y", lambda path: (True, []))

    text = assess.report(
        [], (assess.assess_html(_page(tmp_path), validate=True),))

    assert "words as a picture" in text
    assert "CSS background" in text


def _html(tmp_path, body, head="<title>A page</title>", lang="en",
          name="page.html"):
    target = tmp_path / name
    target.write_text(
        "<!doctype html><html%s><head>%s</head><body>%s</body></html>"
        % ((" lang='%s'" % lang) if lang else "", head, body),
        encoding="utf-8")
    return target


# The six states an image can be in, which are `lint.figure_state`'s four
# plus the two the markup adds: a claim that the image carries nothing, and
# a caption that is word for word the alt text.
IMAGE_CASES = [
    ("<img src='fig.png' />", "images_no_alt"),
    ("<img src='fig.png' alt='' />", "images_decorative"),
    ("<img src='fig.png' role='presentation' alt='Something' />",
     "images_decorative"),
    ("<img src='fig.png' aria-hidden='true' alt='Something' />",
     "images_decorative"),
    ("<img src='figure-p013-1.png' alt='figure-p013-1.png' />",
     "images_placeholder_alt"),
    ("<img src='figure-p013-1.png' alt='Figure p013 1' />",
     "images_placeholder_alt"),
    ("<img src='fig.png' alt='image' />", "images_placeholder_alt"),
    ("<figure><img src='fig.png' alt='Figure 1. A whiteboard.' />"
     "<figcaption>Figure 1. A whiteboard.</figcaption></figure>",
     "images_caption_as_alt"),
    ("<figure><img src='fig.png' alt='A whiteboard of sticky notes.' />"
     "<figcaption>A whiteboard of sticky notes.</figcaption></figure>",
     "images_alt_doubles_as_caption"),
    ("<p><img src='fig.png' alt='A whiteboard covered in sticky notes.' />"
     "<br />Figure 1. The planning wall.</p>", "images_described"),
]


@pytest.mark.parametrize("markup, state", IMAGE_CASES)
def test_an_image_is_read_into_one_state(tmp_path, markup, state):
    page = assess.read_html(_html(tmp_path, markup))

    assert page.images == 1
    assert getattr(page, state) == 1
    counted = sum(getattr(page, name) for name in (
        "images_no_alt", "images_placeholder_alt", "images_caption_as_alt",
        "images_alt_doubles_as_caption", "images_decorative",
        "images_described"))
    assert counted == 1


def test_a_decorative_image_is_not_work_and_is_still_counted(tmp_path):
    """`alt=""` says the image carries nothing a reader needs, which is the
    right answer for a rule and the wrong one for a figure. An archive that
    emptied every alt to quiet a checker looks identical to a described one
    on a count of failures alone."""
    page = assess.read_html(_html(tmp_path, "<img src='rule.png' alt='' />"))

    assert page.images_owed == 0
    assert page.images_decorative == 1


def test_a_caption_a_renderer_printed_is_not_counted_as_work(tmp_path):
    """Pandoc makes a `<figure>` of a lone image and uses its alt as the
    `<figcaption>`, which is how 31 of this archive's own hand-written
    descriptions appear twice on the page. The markup states that case and a
    caption copied into the alt slot identically, so neither total may claim
    it."""
    page = assess.read_html(_html(
        tmp_path,
        "<figure><img src='fig.png' alt='A whiteboard of sticky notes.' />"
        "<figcaption>A whiteboard of sticky notes.</figcaption></figure>"))

    assert page.images_alt_doubles_as_caption == 1
    assert page.images_owed == 0
    assert page.images_described == 0


def test_a_label_is_what_separates_the_two(tmp_path):
    """A caption names a figure and carries its number; a description does
    not. It is the only thing in the markup that tells which way the copy
    went."""
    page = assess.read_html(_html(
        tmp_path,
        "<figure><img src='fig.png' alt='Figure 3. A whiteboard.' />"
        "<figcaption>Figure 3. A whiteboard.</figcaption></figure>"))

    assert page.images_caption_as_alt == 1
    assert page.images_owed == 1


def test_what_the_page_states_about_itself_is_read(tmp_path):
    page = assess.read_html(_html(
        tmp_path, "<main><h1>A page</h1><h2>A section</h2></main>"))

    assert page.lang == "en"
    assert page.title == "A page"
    assert page.has_main
    assert (page.h1s, page.headings, page.skipped_heading_levels) == (1, 2, 0)


def test_a_page_that_states_none_of_it_says_so(tmp_path):
    page = assess.assess_html(_html(tmp_path, "<p>Prose.</p>", head="",
                                    lang=""))

    assert not page.lang and not page.title and not page.has_main
    assert any("no language" in note for note in page.notes)


def test_a_skipped_heading_level_is_counted_and_not_failed(tmp_path):
    """A page may well open at h2 inside a site that sets the h1
    elsewhere."""
    page = assess.read_html(_html(tmp_path, "<h1>A</h1><h3>B</h3>"))

    assert page.skipped_heading_levels == 1


def test_an_unnamed_svg_reaches_a_reader_as_nothing(tmp_path):
    page = assess.read_html(_html(tmp_path, (
        "<svg><circle /></svg>"
        "<svg><title>A pie chart</title><circle /></svg>"
        "<svg aria-hidden='true'><circle /></svg>")))

    assert page.svgs == 3
    assert page.svgs_unnamed == 1


def test_a_table_with_no_header_cell_names_no_column(tmp_path):
    page = assess.read_html(_html(tmp_path, (
        "<table><tr><td>a</td></tr></table>"
        "<table><tr><th>Name</th></tr><tr><td>a</td></tr></table>")))

    assert page.tables == 2
    assert page.tables_without_headers == 1
    assert page.tables_laid_out == 0


def test_a_page_laid_out_in_columns_owes_no_headers(tmp_path):
    """Three chapters here reproduce an annotated draft as ruled boxes of
    live type, which ingest reads as tables so the draft and the margin
    comments do not interleave. Reporting those as headerless data tables
    would quote a journal for naming columns that are not columns."""
    prose = "The Exploitation of Multiple Birth Children. " * 12
    page = assess.read_html(_html(
        tmp_path, "<table><tr><td>%s</td><td>A comment.</td></tr></table>"
        % prose))

    assert page.tables_laid_out == 1
    assert page.tables_without_headers == 0


def test_a_table_that_says_it_is_a_layout_is_taken_at_its_word(tmp_path):
    """A declaration first and an inference second, the way an image's
    `alt=""` is read. Nothing in this archive declares it, because a galley
    that does fails pa11y on WCAG F92; a stranger's page may well, and a
    page that says what it is should not have to be guessed at."""
    page = assess.read_html(_html(
        tmp_path,
        "<table role='presentation'><tr><td>a</td><td>b</td></tr></table>"))

    assert page.tables_laid_out == 1
    assert page.tables_without_headers == 0


def test_a_long_cell_under_a_header_is_still_a_data_table(tmp_path):
    """Measured over this archive, a headed table's longest cell runs to
    1,419 characters, so length alone would take real tables with it. The
    inference is only reached where there is no header at all."""
    prose = "A long explanation of what this row means. " * 12
    page = assess.read_html(_html(
        tmp_path,
        "<table><tr><th>Stage</th><th>What it asks</th></tr>"
        "<tr><td>Invention</td><td>%s</td></tr></table>" % prose))

    assert page.tables == 1
    assert page.tables_laid_out == 0
    assert page.tables_without_headers == 0


def test_media_without_a_captions_track_is_counted(tmp_path):
    page = assess.read_html(_html(tmp_path, (
        "<video src='a.mp4'></video>"
        "<video src='b.mp4'><track kind='captions' src='b.vtt' /></video>")))

    assert page.media == 2
    assert page.media_without_captions == 1


def test_a_link_a_reader_cannot_hear_is_counted(tmp_path):
    page = assess.read_html(_html(tmp_path, (
        "<a href='/a'></a>"
        "<a href='/b'>Read the chapter</a>"
        "<a href='/c'><img src='i.png' alt='A chapter cover' /></a>"
        "<a href='/d' aria-label='The chapter'><img src='i.png' alt='' /></a>")))

    assert page.links == 4
    assert page.links_without_text == 1


def test_a_form_control_is_labelled_any_of_the_ways_html_allows(tmp_path):
    page = assess.read_html(_html(tmp_path, (
        "<input type='text' />"
        "<label for='a'>A</label><input type='text' id='a' />"
        "<label>B <input type='text' /></label>"
        "<input type='text' aria-label='C' />"
        "<input type='hidden' />")))

    assert page.controls_unlabelled == 1


def test_mathml_owes_nothing_and_is_still_counted(tmp_path):
    """A screen reader reads MathML, which is why the Typst filter is gated
    on that writer and the HTML galley needs none of it. An equation set as
    a picture is an image and is counted there."""
    page = assess.assess_html(_html(tmp_path, "<math><mi>x</mi></math>"))

    assert page.equations == 1
    assert page.images_owed == 0
    assert any("owe nothing" in note for note in page.notes)


def test_a_file_that_is_not_html_is_reported_rather_than_counted(tmp_path):
    target = tmp_path / "empty.html"
    target.write_text("   \n", encoding="utf-8")

    page = assess.assess_html(target)

    assert not page.readable
    assert "empty" in page.error
    assert "will not open" in assess.report([], (page,))


def test_html_is_listed_even_where_nothing_checked_it(tmp_path):
    _page(tmp_path, "one.html")
    _page(tmp_path, "two.htm")

    pages = assess.assess_html_folder(tmp_path)

    assert [p.path.name for p in pages] == ["one.html", "two.htm"]
    assert not any(p.checked for p in pages)


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


# ---------- type that is not text ----------

class _Page:
    """The least of a pdfplumber page that `_page_symbol_fonts` reads."""

    def __init__(self, chars):
        self.chars = [{"fontname": font, "text": text} for font, text in chars]


def test_a_symbol_font_is_caught_by_its_name(tmp_path):
    """A Wingdings open circle extracts as an opening brace and a smiling
    face as a J. Both are ordinary punctuation, so no codepoint test sees
    them and only the font name does."""
    found = assess._page_symbol_fonts(
        _Page([("ABCDEF+Wingdings-Regular", "{"),
               ("ABCDEF+Wingdings-Regular", "J"),
               ("GHIJKL+Minion-Regular", "a")]))

    assert found == {"wingdings-regular": 2}


def test_a_private_use_character_is_caught_whatever_set_it(tmp_path):
    """A private use codepoint means nothing to a screen reader, and Typst
    validates PDF/UA rather than declaring it, so one of them aborts the
    compile. The font that produced it is what a mapping is written
    against, known or not."""
    found = assess._page_symbol_fonts(
        _Page([("MNOPQR+SomeDingbats", ""),
               ("GHIJKL+Minion-Regular", "a")]))

    assert found == {"somedingbats": 1}


def test_a_text_font_setting_text_is_not_counted(tmp_path):
    """`SymbolMT` and `OpenSymbol` decode their bullet correctly already,
    and remapping them would break text that is not broken."""
    found = assess._page_symbol_fonts(
        _Page([("ABCDEF+SymbolMT", "•"),
               ("GHIJKL+OpenSymbol", "•"),
               ("MNOPQR+Minion-Regular", "a")]))

    assert found == {}


def test_a_ligature_does_not_break_the_reading(tmp_path):
    """pdfplumber hands back more than one character for a ligature, so a
    codepoint test written for one raises on the first `fi` it meets."""
    found = assess._page_symbol_fonts(
        _Page([("GHIJKL+Minion-Regular", "fi")]))

    assert found == {}


def test_a_font_nobody_has_mapped_is_the_number_that_counts():
    """Only the font knows which picture sits at which code, and the font
    name is gone by the time the text reaches the cleanups, so each font is
    one reading somebody does off the page and writes down once. The
    character count is a size."""
    assessment = assess.Assessment(
        path=Path("x.pdf"), pages=4, symbol_pages=3,
        symbol_fonts=[
            assess.SymbolFont("wingdings", characters=40, pages=2, known=True),
            assess.SymbolFont("acmedingbats", characters=900, pages=1),
        ])
    assess._add_notes(assessment)

    notes = " ".join(assessment.notes)
    assert "Already handled: wingdings" in notes
    assert "Not yet handled: acmedingbats" in notes
    assert "not a count of characters" in notes


def test_the_summary_counts_the_fonts_and_not_the_characters():
    """A font is one reading whether it sets one page or forty, so the
    folder total is folded by family rather than summed per file."""
    files = []
    for name in ("a.pdf", "b.pdf"):
        files.append(assess.Assessment(
            path=Path(name), pages=4, tagged=True, symbol_pages=2,
            symbol_fonts=[assess.SymbolFont("acmedingbats", characters=500,
                                            pages=2)]))

    text = assess.report(files)

    assert "4 page(s) set type in a symbol font" in text
    assert "1 font(s), of which 1 are not mapped yet: acmedingbats" in text


def test_a_tree_is_something_the_result_could_be_checked_against():
    """`pdf_ingest` infers for a tagged file and an untagged one alike, so
    a structure tree is not something it reads. Saying it is would promise
    a reconstruction nobody wrote."""
    assessment = assess.Assessment(path=Path("a.pdf"), pages=4, tagged=True)
    assess._add_notes(assessment)

    notes = " ".join(assessment.notes)
    assert "rather than from the structure tree" in notes
    assert "nothing checks it yet" in notes


def test_a_file_with_no_tree_has_nothing_to_check_against():
    assessment = assess.Assessment(path=Path("a.pdf"), pages=4, tagged=False)
    assess._add_notes(assessment)

    notes = " ".join(assessment.notes)
    assert "holds nothing to check it against" in notes


def test_the_summary_says_what_had_to_be_inferred():
    """A file with no structure tree is one where ingest reconstructs the
    paragraphs, the heads and the emphasis from the geometry of the page,
    and every one of those is a judgement that can be wrong."""
    files = [assess.Assessment(path=Path("a.pdf"), pages=4, tagged=True),
             assess.Assessment(path=Path("b.pdf"), pages=4, tagged=False)]

    text = assess.report(files)

    assert "1 of 2 carry no structure tree" in text
    assert "inferred rather than read" in text


# ---------- it writes nothing ----------

@pytest.mark.parametrize("validate", [False, True])
def test_assessing_a_folder_leaves_it_exactly_as_it_was(tmp_path, validate):
    """The pass is pointed at a stranger's archive before any agreement
    exists. Ingest is the destructive path; this one must not be.

    Run with the validators as well, because they are subprocesses and a
    subprocess is where a file would appear beside the one it read. Both
    write their reports to stdout; `validate_galleys.py` is what puts one
    on disk, and it writes into Graphion's own content rather than into a
    folder somebody sent. Where neither tool is installed this still
    passes, saying less, which is the same shape as the rest of the suite.
    """
    folder = tmp_path / "sent"
    folder.mkdir()
    _png(tmp_path / "fig.png")
    shutil.copy2(_typst(tmp_path, "described", DESCRIBED), folder / "a.pdf")
    shutil.copy2(_typst(tmp_path, "plain", PLAIN), folder / "b.pdf")
    (folder / "page.html").write_text(
        "<!doctype html><html lang='en'><head><title>A page</title></head>"
        "<body><h1>A page</h1></body></html>", encoding="utf-8")

    before = {p.name: p.read_bytes() for p in folder.iterdir()}
    results = assess.assess_folder(folder, validate=validate)
    pages = assess.assess_html_folder(folder, validate=validate)
    after = {p.name: p.read_bytes() for p in folder.iterdir()}

    assert len(results) == 2
    assert len(pages) == 1
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


def test_the_report_does_not_call_a_file_conformant_on_its_own_say_so(
        described):
    """One word covering both the statement and the verdict is how an
    archive comes to be described as conformant because it says it is."""
    text = assess.report([assess.assess_pdf(described)])

    assert "declares conformance" in text
    assert "pass --validate" in text


def test_the_summary_says_when_nothing_checked_the_declarations(tmp_path):
    folder = tmp_path / "sent"
    folder.mkdir()
    _png(tmp_path / "fig.png")
    shutil.copy2(_typst(tmp_path, "described", DESCRIBED), folder / "a.pdf")
    shutil.copy2(_typst(tmp_path, "plain", PLAIN), folder / "b.pdf")

    text = assess.report(assess.assess_folder(folder))

    assert "Nothing was checked" in text


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
