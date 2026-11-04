"""Every journal's HTML galley, not just the one that was remediated.

The two bundles had drifted. Writing Spaces carried a skip link, a `<main>`
landmark, `aria-labelledby` pointing at real headings and a licence
statement; LiCS carried none of them and named its sections with
`aria-label` instead. `new_journal.py` clones LiCS, so every journal added
from here would have started from the less accessible of the two and the
remediation would have stayed in the bundle nothing copies.

So the contract belongs to the bundles rather than to one of them, and
these tests read whatever bundles are on disk. A journal added tomorrow is
covered by them without anybody remembering to add it.

The last pair are the ones easiest to get half right. Markup without the
stylesheet puts a visible "Skip to the article" link at the top of every
galley, and a stylesheet that hides it without a `:focus` rule hides it
from the keyboard reader it exists for.
"""
import re
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import acr

BUNDLES = sorted(
    p for p in Path("content/journals").glob("*/template")
    if (p / "article.html.j2").exists()
)

# Named so a failure says which journal, rather than which index.
IDS = [p.parent.name for p in BUNDLES]


@pytest.fixture(params=BUNDLES, ids=IDS)
def bundle(request):
    return request.param


def _template(bundle) -> str:
    return (bundle / "article.html.j2").read_text(encoding="utf-8")


def _css(bundle) -> str:
    css = bundle / "article.css"
    return css.read_text(encoding="utf-8") if css.exists() else ""


def test_there_is_a_bundle_to_check():
    assert BUNDLES, "no journal template bundles found under content/journals"


def test_the_document_states_its_language(bundle):
    """WCAG 3.1.1. Without it a screen reader reads English prose in
    whatever voice it defaulted to."""
    assert re.search(r"<html[^>]*\blang=", _template(bundle))


def test_there_is_a_main_landmark(bundle):
    """A reader navigating by landmark has somewhere to go. The running
    head anchors sit outside it, which is the point."""
    assert "<main" in _template(bundle)


def test_the_skip_link_lands_somewhere_in_the_same_document(bundle):
    """WCAG 2.4.1. A skip link pointing at an id nothing defines sends a
    keyboard reader to the top of the page, which is where they already
    were.

    Read through `acr`, which cites the same fact in the conformance
    report. One reader, so the report cannot claim a criterion this test
    would fail on.
    """
    assert acr.skip_link_target(_template(bundle)) is not None


def test_every_aria_labelledby_points_at_a_heading_that_exists(bundle):
    """An `aria-labelledby` naming an id that is not in the document leaves
    the section unnamed, and nothing renders differently."""
    html = _template(bundle)
    for target in re.findall(r'aria-labelledby="([^"]+)"', html):
        assert re.search(r'id="%s"' % re.escape(target), html), (
            "aria-labelledby=%r has no element with that id" % target)


def test_a_section_with_a_heading_is_named_by_it(bundle):
    """`aria-label` on a section that has a visible heading replaces the
    heading text with a second copy of it, which can drift from the first
    and usually does. `aria-labelledby` pointing at the heading cannot.

    A footer with no heading inside it is the case `aria-label` is for, so
    it is allowed one.
    """
    html = _template(bundle)
    for element in re.findall(r"<(?:section|aside)\b[^>]*>", html):
        assert "aria-label=" not in element, (
            "%s should name itself by its own heading" % element.strip())


def test_the_licence_is_stated_where_a_machine_reads_it(bundle):
    """An open-access journal publishes terms, and a galley that carries
    them only in prose cannot be indexed on them."""
    html = _template(bundle)
    assert 'rel="license"' in html
    assert "dcterms.rights" in html


def test_the_licence_is_stated_where_a_reader_sees_it(bundle):
    html = _template(bundle)
    assert re.search(r"<footer[^>]*class=\"licence\"", html), (
        "the terms are in the metadata and nowhere on the page")


# ---------- the markup and the stylesheet are one thing ----------

def test_the_skip_link_is_out_of_the_way_until_it_is_needed(bundle):
    """Without the rule the galley opens with a visible "Skip to" link
    above the title, on every article, for every reader."""
    css = _css(bundle)
    assert ".skip-link" in css, "the markup has a skip link and the CSS does not"
    assert acr.skip_link_is_hidden_until_focused(css), (
        "the skip link is not taken off screen, or never comes back")


def test_the_skip_link_comes_back_on_focus(bundle):
    """Hidden and never shown is worse than not having one: the keyboard
    reader it exists for is the one who cannot see it."""
    assert re.search(r"\.skip-link:focus\s*\{", _css(bundle))


def test_focus_is_visible(bundle):
    """WCAG 2.4.7. Tabbing through a document with no focus ring is
    navigating it blind."""
    assert acr.focus_is_visible(_css(bundle))


# ---------- and what the bundle actually renders ----------

pandoc = pytest.mark.skipif(
    shutil.which("pandoc") is None, reason="Pandoc is not on PATH")

ARTICLE = """---
title: A Study of Literacy in Prisons
short-title: Prison Literacy
short-authors: Lewis
abstract: What the article argues, in a paragraph.
keywords: [literacy, carceral studies]
license: CC BY-NC-ND 4.0
license-url: https://creativecommons.org/licenses/by-nc-nd/4.0/
author:
  - name: Justin Lewis
    affiliation: Olympic College
---

# A Heading

Body text of the article.
"""


@pandoc
def test_the_licence_url_survives_the_filters(bundle, tmp_path):
    """A journal filter that walks the whole document reaches metadata too.

    The URL filter inserts soft break points so a long citation cannot run
    off the measure, and walked over the metadata it put `<wbr>` through
    the licence href, which then pointed nowhere. Nothing showed it until
    the template started carrying the licence, which is how one bundle
    kept the bug for as long as the other one had the fix.
    """
    import conversion

    article = tmp_path / "an-article"
    article.mkdir()
    (article / "article.md").write_text(ARTICLE, encoding="utf-8")

    out = conversion.render_html(article, bundle.parent.name)
    html = Path(out).read_text(encoding="utf-8")

    for href in re.findall(r'href="([^"]*)"', html):
        assert "<wbr>" not in href, "soft break points inside an href"
    assert ('href="https://creativecommons.org/licenses/by-nc-nd/4.0/"'
            in html)


@pandoc
def test_the_rendered_galley_has_somewhere_to_skip_to(bundle, tmp_path):
    """The template can be right and the render still wrong, if whatever
    the skip link points at is injected by a filter that did not run."""
    import conversion

    article = tmp_path / "an-article"
    article.mkdir()
    (article / "article.md").write_text(ARTICLE, encoding="utf-8")

    html = Path(conversion.render_html(
        article, bundle.parent.name)).read_text(encoding="utf-8")

    link = re.search(r'class="skip-link"[^>]*href="#([^"]+)"', html)
    assert link
    assert re.search(r'id="%s"' % re.escape(link.group(1)), html)
    assert "<main" in html


# ---------- contrast, including the palette pa11y never renders ----------

def test_the_contrast_formula_is_the_one_wcag_states():
    """Black on white is 21:1 and a colour on itself is 1:1. Worth pinning,
    because the formula has a linearisation step that is easy to leave out
    and leaving it out still produces plausible-looking numbers."""
    assert round(acr.contrast_ratio("#000000", "#ffffff"), 1) == 21.0
    assert round(acr.contrast_ratio("#ffffff", "#ffffff"), 1) == 1.0
    assert round(acr.contrast_ratio("#777777", "#ffffff"), 1) == 4.5


def test_a_colour_that_is_not_a_hex_triple_is_not_guessed_at():
    """A palette entry naming another variable has not been resolved, and a
    ratio invented for it would be a measurement nobody made."""
    assert acr.relative_luminance("var(--ink)") is None
    assert acr.relative_luminance("") is None
    assert acr.contrast_ratio("var(--ink)", "#ffffff") is None


def test_shorthand_hex_is_read():
    assert round(acr.contrast_ratio("#000", "#fff"), 1) == 21.0


def test_every_palette_the_bundle_declares_is_read(bundle):
    """The colours are declared once as custom properties and overridden
    per media query, so the variables are the palette."""
    found = acr.palettes(_css(bundle))

    assert "base" in found
    assert found["base"].get("--paper"), "no page colour in the base palette"
    assert found["base"].get("--ink"), "no text colour in the base palette"


def test_text_clears_the_contrast_minimum_in_every_palette(bundle):
    """1.4.3 asks 4.5:1 of body text. pa11y checks this on a rendered page
    and so only ever checks the light palette; a bundle's dark mode is
    whatever it declares and nothing exercises it. Measured today: LiCS
    reads 9.3 to 16.8 and Writing Spaces 7.0 to 18.4 light, 8.5 to 14.7
    dark.
    """
    failures = acr.text_contrast_failures(_css(bundle))

    assert not failures, "\n".join(
        f"{palette}: {token} is {ratio}:1, below "
        f"{acr.TEXT_CONTRAST_MIN}:1" for palette, token, ratio in failures)


def test_the_bundle_reports_its_contrast_as_a_fact(bundle):
    """So the report cannot claim a criterion this test would fail on,
    which is the arrangement 2.4.1 and 2.4.7 already use."""
    facts = acr.bundle_facts(bundle)

    assert "text-contrast" in facts
    assert facts["text-contrast"] is True
