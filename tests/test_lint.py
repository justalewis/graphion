"""Unit tests for lint.py checks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import lint


def _check(title: str, short_title: str):
    return lint.check_short_title_matches_title(
        {}, {"title": title, "short-title": short_title}, ""
    )


def test_typo_in_short_title_is_flagged():
    """The short title shows only in the running header, so a typo there
    survives every proofread of the article itself."""
    result = _check(
        "Magnifying Dissent: the Capital Appeals Process", "Maginifying Dissent"
    )
    assert result.level == "warn"
    assert "maginifying" in result.summary


def test_clean_truncation_passes():
    result = _check(
        "Magnifying Dissent: the Capital Appeals Process", "Magnifying Dissent"
    )
    assert result.level == "pass"


def test_acronym_and_punctuation_survive():
    assert _check(
        "Against AI Empire and the Critwashing of Generative AI", "Against AI Empire"
    ).level == "pass"
    assert _check(
        "Facing What's Human: From Dialogic Intertextuality", "Facing What's Human"
    ).level == "pass"


def test_plural_in_title_is_not_a_typo():
    """A singular in the short title against a plural in the title is normal."""
    assert _check("A Study of Literacy in Prisons", "Prison Literacy").level == "pass"
    assert _check("Reading Narratives of Recovery", "Recovery Narrative").level == "pass"
    assert _check("Teaching Bodies and Archives", "Teaching Body").level == "pass"
    assert _check("Studies in Literacy", "Study of Literacy").level == "pass"


def test_deliberate_rephrasing_warns():
    """Advisory only: this cannot tell a rewording from a slip, and says so."""
    result = _check("A Study of Literacy in Prisons", "Carceral Literacy")
    assert result.level == "warn"
    assert any("rephrases" in d for d in result.details)


def test_missing_values_do_not_warn():
    """check_short_title_length already reports an empty short title."""
    assert _check("Some Title", "").level == "pass"
    assert _check("", "Some Short Title").level == "pass"


def test_stopwords_are_ignored():
    """Function words carry no signal and appear in almost any title."""
    assert _check("Reading in the Dark", "Reading Through the Dark").level == "pass"


def test_check_is_registered():
    assert lint.check_short_title_matches_title in lint.DEFAULT_CHECKS


def _alt(body: str):
    return lint.check_alt_text({}, {}, body)


def test_missing_alt_text_blocks():
    """A galley compiles as PDF/UA-1, and Typst refuses an image with no alt
    text, so this costs conformance rather than merely being untidy."""
    result = _alt("Body text.\n\n![](assets/fig1.png)\n")
    assert result.level == "fail"
    assert "1 of 1" in result.summary


def test_alt_attribute_counts_as_alt_text():
    """Pandoc passes an explicit alt attribute through to Typst, so the
    bracket text being empty is not by itself a problem."""
    body = 'Body.\n\n![](assets/fig1.png){alt="A bar chart of response rates"}\n'
    assert _alt(body).level == "pass"


def test_captioned_images_pass():
    result = _alt("![A bar chart of response rates](assets/fig1.png)\n")
    assert result.level == "pass"
    assert "All 1" in result.summary


def test_counts_only_the_images_missing_alt():
    body = (
        "![Good caption](a.png)\n\n"
        "![](b.png)\n\n"
        "![](c.png){alt=\"Also fine\"}\n\n"
        "![](d.png)\n"
    )
    result = _alt(body)
    assert result.level == "fail"
    assert "2 of 4" in result.summary


def test_no_images_passes():
    assert _alt("Just prose, no figures at all.").level == "pass"


def test_alt_text_check_is_registered():
    assert lint.check_alt_text in lint.DEFAULT_CHECKS


# ---------- figures the galley does not have ----------

# A Markdown hard line break: a backslash, then the newline. PDF ingest puts
# a figure and the caption printed under it in one paragraph joined by this,
# so that the image stays an image. Alone in a paragraph it would become a
# Pandoc Figure, and the journal's figures filter numbers every Figure from 1
# in document order, which would print "Figure 1." over a caption reading
# "Figure 7.4". Spelled out here because an escaped one is easy to lose.
HARD_BREAK = "\\" + "\n"


def _coverage(body: str):
    return lint.check_figure_coverage({}, {}, body)


def test_text_referring_to_figures_it_does_not_have_is_flagged():
    """check_alt_text cannot see this and reads it as a pass, because what it
    tests is whether an image lacks alt text. Both volumes of Writing Spaces
    passed that way while referring to 258 figures that were not there."""
    body = ("As Figure 7.1 shows, the sign stands for the thing.\n\n"
            "Compare Figure 7.2 and Figure 7.3.\n")
    result = _coverage(body)
    assert result.level == "warn"
    assert "3 figure(s)" in result.summary
    assert lint.check_alt_text({}, {}, body).level == "pass"


def test_figures_present_alongside_references_pass():
    body = ("![A chair](assets/figure-p004-1.jpg)\\nFigure 7.1: Chair\n\n"
            "As Figure 7.1 shows, the sign stands for the thing.\n")
    assert _coverage(body).level == "pass"


def test_text_referring_to_no_figures_passes():
    assert _coverage("Plain prose with no figures in it.\n").level == "pass"


def test_figure_coverage_is_registered():
    assert lint.check_figure_coverage in lint.DEFAULT_CHECKS


def test_an_undescribed_figure_is_a_warning_not_a_pass():
    """Alt text that says only that the figure is undescribed keeps the
    galley conformant and tells a reader nothing, so it is neither a failure
    nor done."""
    body = ("![Undescribed figure from page 27 of the source]"
            "(assets/figure-p027-1.jpg)\n")
    result = _alt(body)
    assert result.level == "warn"
    assert "1 of 1" in result.summary


def test_alt_text_taken_from_the_caption_is_a_warning():
    """A caption names a figure; alt text has to describe it."""
    body = ("![Schematic bridge diagram](assets/figure-p016-1.jpg)" + HARD_BREAK
            + "Figure 7.4: Schematic bridge diagram\n")
    result = _alt(body)
    assert result.level == "warn"
    assert "need a written description" in result.summary


def test_alt_text_that_describes_more_than_the_caption_passes():
    body = ("![A truss bridge in elevation, with the load paths through each "
            "diagonal marked](assets/figure-p016-1.jpg)" + HARD_BREAK
            + "Figure 7.4: Schematic bridge diagram\n")
    assert _alt(body).level == "pass"
