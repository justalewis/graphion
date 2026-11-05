"""Mechanical fixes to a page, and the ones this deliberately will not make.

R2. The tests that matter most here are not the fixes; they are the
refusals, because every one of them was a candidate that measurement or
this codebase's own history ruled out, and each would look like an
improvement to anybody who had not measured.

Every fix is also held to `invariance`, which is the point of having
built that first: a pass is allowed to change markup and is not allowed
to change a word, and the proof runs on the same input as the fix.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import invariance
import remediate


def _page(body: str, head: str = "<title>A page</title>",
          html_attrs: str = "") -> bytes:
    return (f"<html{html_attrs}><head>{head}</head><body>{body}</body></html>"
            ).encode("utf-8")


# ---------- language ----------

def test_a_stated_language_is_written_where_there_is_none():
    result = remediate.fix_html(_page("<p>Text.</p>"), language="en")

    assert result.of_kind("lang").count == 1
    assert b'lang="en"' in result.data


def test_a_language_is_never_guessed():
    """None of the 33 cartridges measured declares a locale, so there is
    nothing to read one from. Writing `lang="en"` over a Spanish course
    makes a screen reader pronounce Spanish with English phonetics,
    confidently, which is worse than leaving it off."""
    result = remediate.fix_html(_page("<p>Texto.</p>"))

    assert result.of_kind("lang") is None
    assert b"lang=" not in result.data
    assert result.owes("no-language").count == 1


def test_a_language_the_author_already_set_is_left_alone():
    """The author said something about this page and that outranks what
    the caller said about the course."""
    result = remediate.fix_html(
        _page("<p>Texto.</p>", html_attrs=' lang="es"'), language="en")

    assert result.of_kind("lang") is None
    assert b'lang="es"' in result.data


# ---------- table headers ----------

TWO_WAY = ("<table><tr><th></th><th>Spring</th><th>Autumn</th></tr>"
           "<tr><th>Reading</th><td>3</td><td>4</td></tr></table>")


def test_a_header_in_the_first_row_heads_a_column():
    result = remediate.fix_html(
        _page("<table><tr><th>Week</th><th>Reading</th></tr>"
              "<tr><td>1</td><td>Bunn</td></tr></table>"))

    assert result.of_kind("scope").count == 2
    assert result.data.count(b'scope="col"') == 2


def test_a_table_headed_down_its_left_edge_has_no_column_headers():
    """Every row opens with a header and the first row is not all
    headers, so this table is headed on one edge only. Reading the first
    row as column headings because it is the first row would tell a
    screen reader that "Week" names the column below it, which is the
    data, not a heading."""
    result = remediate.fix_html(
        _page("<table><tr><th>Week</th><td>1</td></tr>"
              "<tr><th>Reading</th><td>Bunn</td></tr></table>"))

    assert result.of_kind("scope").count == 2
    assert result.data.count(b'scope="row"') == 2
    assert b'scope="col"' not in result.data


def test_the_corner_cell_of_a_table_headed_two_ways_is_left_alone():
    """It heads both a row and a column, `scope` has no value meaning
    both, and picking one is a claim about the table."""
    result = remediate.fix_html(_page(TWO_WAY))

    # Spring and Autumn get col, Reading gets row, the corner gets none.
    assert result.of_kind("scope").count == 3
    assert result.data.count(b"<th>") == 1


def test_a_scope_the_author_set_is_not_overwritten():
    result = remediate.fix_html(
        _page('<table><tr><th scope="row">Week</th><th>Reading</th></tr>'
              "<tr><td>1</td><td>Bunn</td></tr></table>"))

    assert result.of_kind("scope").count == 1
    assert b'scope="row"' in result.data


def test_a_table_with_no_header_is_reported_and_not_promoted():
    """Promoting a `<td>` row to `<th>` is a claim about what the table
    means, and getting it wrong changes what a screen reader announces
    for every cell beneath it. 164 tables across the cartridges measured
    are in this state and not one is safe to guess at."""
    page = _page("<table><tr><td>Week</td><td>Reading</td></tr>"
                 "<tr><td>1</td><td>Bunn</td></tr></table>")

    result = remediate.fix_html(page)

    assert result.owes("table-without-header").count == 1
    assert b"<th" not in result.data


def test_a_layout_table_does_not_get_role_presentation():
    """The remedy an audit names, and this codebase has already paid to
    learn it does not work: pa11y fails the page on WCAG F92 because
    `<tbody>`, `<tr>` and `<td>` are semantic children of a presentation
    role. It was written, tested against pa11y and reverted."""
    result = remediate.fix_html(
        _page("<table><tr><td>A long passage of prose set in one cell "
              "because the page is using a table to put two columns "
              "beside each other.</td></tr></table>"))

    assert b"presentation" not in result.data


# ---------- headings ----------

def test_a_skipped_level_is_closed():
    result = remediate.fix_html(
        _page("<h2>One</h2><h4>Under one</h4>"))

    assert result.of_kind("heading-level").count == 1
    assert b"<h3>Under one</h3>" in result.data


def test_where_the_outline_starts_is_left_exactly_alone():
    """The difference from `filters/heading-levels.lua`, and the whole
    "a cartridge is not a course" point. A galley is a whole document so
    its outline must start at one; a Canvas page is wrapped by Canvas,
    which renders the page title as the h1 itself. Over 2,532 real pages
    the first body heading is h2 on 1,574 and h1 on 210, so forcing a
    start at one would put a second h1 on most pages in the archive."""
    result = remediate.fix_html(_page("<h2>One</h2><h3>Two</h3>"))

    assert result.of_kind("heading-level") is None
    assert b"<h2>One</h2>" in result.data
    assert b"<h3>Two</h3>" in result.data


def test_nesting_survives_the_close():
    result = remediate.fix_html(
        _page("<h2>A</h2><h5>A1</h5><h5>A2</h5><h2>B</h2>"))

    assert b"<h2>A</h2>" in result.data
    assert result.data.count(b"<h3>") == 2
    assert b"<h2>B</h2>" in result.data


def test_a_positional_skip_is_caught_where_ranking_would_miss_it():
    """A page can hold every level and still skip one positionally: an
    h2 followed by an h4 with the h3 elsewhere. The same case
    `filters/heading-levels.lua` carries a test for."""
    result = remediate.fix_html(
        _page("<h2>A</h2><h4>skipped to</h4><h3>B</h3>"))

    assert b"<h3>skipped to</h3>" in result.data


def test_a_page_with_no_headings_is_not_touched():
    page = _page("<p>Just prose.</p>")

    assert remediate.fix_html(page).of_kind("heading-level") is None


# ---------- iframes ----------

def test_an_untitled_frame_is_reported_and_not_named():
    """Inventing a title from the embed URL produces "YouTube video
    player" on every frame, which is worse than silence because it looks
    answered."""
    result = remediate.fix_html(
        _page('<iframe src="https://www.youtube.com/embed/x"></iframe>'))

    assert result.owes("iframe-without-title").count == 1
    assert b"title=" not in result.data


# ---------- the contract ----------

CASES = [
    ("a language written", '<html><head></head><body><h2>A</h2>'
     '<p>A sentence the author wrote.</p></body></html>'),
    ("scope added", '<html><body><table><tr><th>Week</th><th>Text</th></tr>'
     '<tr><td>1</td><td>Bunn</td></tr></table></body></html>'),
    ("a heading moved", '<html><body><h2>One</h2><h4>Under one</h4>'
     '<p>Prose beneath.</p></body></html>'),
]


@pytest.mark.parametrize("label, source", CASES)
def test_no_fix_changes_a_word(label, source):
    """The guarantee, on the same input as the fix. A pass is allowed to
    change markup and is not allowed to change a word."""
    data = source.encode("utf-8")
    before = invariance.text_of("p.html", data)

    after = invariance.text_of("p.html",
                               remediate.fix_html(data, language="en").data)

    assert before == after, label


@pytest.mark.parametrize("label, source", CASES)
def test_running_it_twice_changes_nothing_the_second_time(label, source):
    """The rule every cleanup pass in this codebase follows. A pass that
    gains something on each run makes a remediation unrepeatable, and the
    report would count work that is not there."""
    once = remediate.fix_html(source.encode("utf-8"), language="en")
    twice = remediate.fix_html(once.data, language="en")

    assert twice.data == once.data, label
    assert twice.changes == [], label


def test_a_page_this_pass_has_no_work_for_is_not_reformatted():
    """Parsing and reserialising rewrites whitespace and attribute order
    through the whole file. A page with nothing to fix should come back
    as the bytes it arrived as, so a diff of the cartridge shows only
    what was actually remediated."""
    page = _page("<h2>One</h2><h3>Two</h3>", html_attrs=' lang="en"')

    result = remediate.fix_html(page, language="en")

    assert not result.changed
    assert result.data == page


def test_a_page_that_will_not_parse_is_left_exactly_as_it_arrived():
    """A remediation that mangles a file it could not read is the one
    outcome worse than leaving the file alone."""
    rubbish = b"\x00\x01\x02 not markup at all"

    result = remediate.fix_html(rubbish, language="en")

    assert result.data == rubbish
    assert result.error
    assert not result.changed


def test_the_summary_folds_a_run_into_counts():
    results = [
        remediate.fix_html(_page("<h2>A</h2><h4>B</h4>"), language="en"),
        remediate.fix_html(_page("<table><tr><td>x</td></tr></table>"),
                           language="en"),
    ]

    folded = remediate.summarise(results)

    assert folded["changed"]["lang"] == 2
    assert folded["changed"]["heading-level"] == 1
    assert folded["owed"]["table-without-header"] == 1


# ---------- encoding ----------

CURLY = ('<html><head>'
         '<meta http-equiv="Content-Type" content="text/html; charset=utf-8">'
         '<title>A page</title></head><body>'
         '<h2>Reading</h2><p>Read “Writing for understanding” by '
         'Digital.gov — it is short.</p></body></html>').encode("utf-8")


def test_the_character_encoding_survives_the_fix():
    """lxml's HTML serialiser *removes* the `<meta http-equiv>` the page
    arrived with and writes nothing in its place unless asked, so the
    output is UTF-8 bytes with nothing declaring that and the next reader
    falls back to Latin-1. Every curly quotation mark in the course then
    becomes "â€œ".

    That is corruption of the deliverable rather than a reporting
    problem, and it would have shipped: it passed every unit test here
    and failed on 1,960 of the 2,532 real pages the moment the invariance
    harness was pointed at them."""
    result = remediate.fix_html(CURLY, language="en")

    assert b"charset" in result.data
    assert "“".encode("utf-8") in result.data
    assert "â€".encode("utf-8") not in result.data


def test_a_curly_quotation_mark_reads_back_as_itself():
    """The round trip, which is what actually failed. Asserting on the
    bytes alone would pass with a charset that disagreed with them."""
    result = remediate.fix_html(CURLY, language="en")

    before = invariance.text_of("p.html", CURLY)
    after = invariance.text_of("p.html", result.data)

    assert "“Writing for understanding”" in before
    assert before == after


def test_an_em_dash_in_the_authors_prose_is_not_mangled():
    """House style keeps em-dashes out of prose this app writes. An
    author's own are theirs, and carrying them through unharmed is the
    same encoding question."""
    after = invariance.text_of(
        "p.html", remediate.fix_html(CURLY, language="en").data)

    assert "—" in after


# ---------- PDFs ----------

def _pdf(title=None, lang=None, pages=1):
    """A minimal PDF, optionally stating a title or a language."""
    import io
    import pypdf
    writer = pypdf.PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=200, height=200)
    if title is not None:
        writer.add_metadata({"/Title": title})
    if lang is not None:
        writer._root_object[pypdf.generic.NameObject("/Lang")] = \
            pypdf.generic.create_string_object(lang)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _root_of(data):
    import io
    import pypdf
    return pypdf.PdfReader(io.BytesIO(data)).trailer["/Root"]


@pytest.mark.parametrize("junk", [
    "Microsoft Word - research 2.docx",
    "Microsoft Word - Progress Report Structure.docx",
    "Microsoft PowerPoint - week one.pptx",
    "doi:10.1016/j.annemergmed.2007.09.037",
    "Untitled",
    "report.pdf",
    "",
])
def test_a_converters_filename_is_not_a_title(junk):
    """Of the nine distinct Info titles across these cartridges that have
    one and no XMP title, seven are "Microsoft Word - <filename>" and one
    is a DOI. Moving those would make a screen reader announce "Microsoft
    Word - research 2.docx" as the name of the document, which is worse
    than the silence it replaces: it satisfies the checker and tells the
    reader something false."""
    assert not remediate.looks_like_a_title(junk)


@pytest.mark.parametrize("real", [
    "Gill - AAA Contribution",
    "Annoying Ways People Use Sources",
    "A Guide to Reference and Documentation",
])
def test_a_real_title_is_moved(real):
    assert remediate.looks_like_a_title(real)


def test_a_junk_title_is_reported_rather_than_written():
    result = remediate.fix_pdf(_pdf(title="Microsoft Word - notes.docx"),
                               language="en")

    assert result.owes("title-is-not-a-title").count == 1
    assert result.of_kind("xmp-title") is None
    # And it must not turn on DisplayDocTitle either, or the reader shows
    # the filename in its title bar, which is the failure 2.4.2 names.
    assert result.of_kind("display-doc-title") is None


def test_a_stated_language_is_written_into_the_catalog():
    result = remediate.fix_pdf(_pdf(), language="en")

    assert result.of_kind("lang").count == 1
    assert _root_of(result.data)["/Lang"] == "en"


def test_a_language_the_document_already_states_is_left_alone():
    result = remediate.fix_pdf(_pdf(lang="es"), language="en")

    assert result.of_kind("lang") is None
    assert _root_of(result.data)["/Lang"] == "es"


def test_a_real_title_reaches_dc_title_and_reads_back():
    """The whole point of moving it. An earlier version wrote the field
    with an lxml-invented `ns0:` prefix, so it was there, nothing could
    find it, and the stamp reported success."""
    import io
    import pypdf
    import pdf_tags

    result = remediate.fix_pdf(_pdf(title="Gill - AAA Contribution"),
                               language="en")

    assert result.of_kind("xmp-title").count == 1
    reader = pypdf.PdfReader(io.BytesIO(result.data))
    assert pdf_tags.declared_title(pdf_tags.xmp_packet_text(reader)) == \
        "Gill - AAA Contribution"


def test_stamping_never_claims_conformance():
    """A stamp cannot make a file conformant, so it must not say it did.
    `pdfuaid:part` is what an audit reads to decide the document claims
    PDF/UA, and this writes it never."""
    import io
    import pypdf
    import pdf_tags

    result = remediate.fix_pdf(_pdf(title="A Real Title"), language="en")

    reader = pypdf.PdfReader(io.BytesIO(result.data))
    assert pdf_tags.declared_ua_part(pdf_tags.xmp_packet_text(reader)) is None


def test_an_untagged_file_is_reported_as_needing_more_than_a_stamp():
    result = remediate.fix_pdf(_pdf(title="A Real Title"), language="en")

    owed = result.owes("untagged")
    assert owed.count == 1
    assert "reconstructing" in owed.detail


def test_a_file_with_no_title_anywhere_is_reported():
    result = remediate.fix_pdf(_pdf(), language="en")

    assert result.owes("no-title").count == 1
    assert result.of_kind("display-doc-title") is None


def test_a_pdf_that_will_not_open_is_left_exactly_as_it_arrived():
    rubbish = b"not a pdf at all"

    result = remediate.fix_pdf(rubbish, language="en")

    assert result.data == rubbish
    assert result.error
    assert not result.changed


def test_stamping_is_idempotent():
    once = remediate.fix_pdf(_pdf(title="A Real Title"), language="en")
    twice = remediate.fix_pdf(once.data, language="en")

    assert not twice.changed


def test_stamping_moves_no_text():
    """Metadata only; no content stream is touched. The guarantee holds
    for PDFs exactly as it does for pages."""
    data = _pdf(title="A Real Title")

    after = remediate.fix_pdf(data, language="en").data

    assert invariance.text_of("x.pdf", data) == invariance.text_of("x.pdf", after)


# ---------- the doctype ----------

def test_a_doctype_survives_the_fix():
    """lxml drops it unless asked, which puts the page into the browser's
    quirks mode: layout changes and no word does, so the invariance check
    cannot see it. 86 of the 2,532 real pages carry one."""
    page = (b"<!DOCTYPE html>\n<html><head><title>T</title></head>"
            b"<body><h2>A</h2><h4>B</h4></body></html>")

    result = remediate.fix_html(page, language="en")

    assert result.changed
    assert result.data.upper().startswith(b"<!DOCTYPE HTML")


def test_a_page_with_no_doctype_does_not_gain_one():
    """Canvas pages carry none, and adding one would switch them out of
    quirks mode, which is a change to how every one of them lays out."""
    result = remediate.fix_html(_page("<h2>A</h2><h4>B</h4>"), language="en")

    assert b"DOCTYPE" not in result.data.upper()


def test_a_legacy_doctype_is_kept_exactly():
    page = (b'<!DOCTYPE HTML PUBLIC "-//W3C//DTD HTML 4.01//EN" '
            b'"http://www.w3.org/TR/html4/strict.dtd">\n<html><body>'
            b"<h2>A</h2><h4>B</h4></body></html>")

    result = remediate.fix_html(page, language="en")

    assert b"-//W3C//DTD HTML 4.01//EN" in result.data
