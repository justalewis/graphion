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


def test_a_long_caption_is_still_recognised_as_the_alt_text():
    """These captions run to several hundred characters. Testing the whole
    alt text against a short window of the caption meant every long caption
    came back as though someone had written a real description."""
    long_caption = ("Angel’s scientific poster, mock examples created by "
                    "the author. This poster has a lengthy introduction and a "
                    "conclusion, uses the first person throughout, and sets "
                    "its methods out in a single narrow column beside a "
                    "cartoonish graphic of the laboratory bench.")
    body = (f"![{long_caption}](assets/figure-p004-1.jpg)" + HARD_BREAK
            + f"Figure 1: {long_caption}\n")
    assert _alt(body).level == "warn"


def test_alt_text_that_describes_more_than_the_caption_passes():
    body = ("![A truss bridge in elevation, with the load paths through each "
            "diagonal marked](assets/figure-p016-1.jpg)" + HARD_BREAK
            + "Figure 7.4: Schematic bridge diagram\n")
    assert _alt(body).level == "pass"


def test_a_private_use_codepoint_fails_the_lint():
    """U+F0FC is Wingdings 0xFC, which prints a check mark and means nothing
    to anything else. Typst validates PDF/UA rather than declaring it, so one
    of these costs the chapter its conformance identifier."""
    result = lint.check_unreadable_characters(
        {}, {}, "A table cell holding \uf0fc and nothing else.")
    assert result.level == "fail"
    assert "U+F0FC" in result.details[0]


def test_a_control_character_fails_the_lint():
    result = lint.check_unreadable_characters({}, {}, "Before\x86after")
    assert result.level == "fail"
    assert "U+0086" in result.details[0]


def test_ordinary_prose_passes_the_unreadable_check():
    """Em dashes, curly quotes and the characters pdf_ingest translates a
    symbol font into are all ordinary text."""
    body = "A check \u2713, an arrow \u2192, a circle \u25cb, a bullet \u2022."
    result = lint.check_unreadable_characters({}, {}, body)
    assert result.level == "pass"


def test_images_of_text_are_reported_even_once_described():
    """WCAG 1.4.5 is a different failure from a missing description, and
    writing alt text leaves it exactly where it was."""
    fm = {"images-of-text": ["figure-p008-1.png", "figure-p011-1.png"]}
    body = ("![An unformatted resume](assets/figure-p008-1.png)\n\n"
            "![A two-column table](assets/figure-p011-1.png)")
    result = lint.check_images_of_text({}, fm, body)
    assert result.level == "warn"
    assert "2 of 2" in result.summary
    assert "figure-p008-1.png" in result.details[1]


def test_an_article_with_no_images_of_text_passes():
    body = "![A cheeseburger in close-up](assets/figure-p003-1.jpg)"
    assert lint.check_images_of_text({}, {}, body).level == "pass"


def test_a_single_image_of_text_may_be_given_as_a_string():
    result = lint.check_images_of_text(
        {}, {"images-of-text": "figure-p008-1.png"},
        "![A resume](assets/figure-p008-1.png)")
    assert result.level == "warn"
    assert "1 of 1" in result.summary


def test_an_undescribed_equation_is_reported():
    """Before math_alt.py this article linted clean and shipped without
    the PDF/UA-1 conformance identifier: check_alt_text reads Markdown
    image syntax, and an equation is not an image."""
    body = r"The estimator is $$\sum_{i=1}^{n} x_i$$ throughout."
    result = lint.check_math_alt_text({}, {}, body)
    assert result.level == "warn"
    assert "1 of 1" in result.summary
    assert "sum" in result.details[-1]


def test_an_equation_the_reader_can_speak_passes():
    """A warning here would be noise: math_alt declines whole rather than
    guessing, so a generated reading is a correct one."""
    body = "Significant at $p < .05$, with $n$ in each cell."
    assert lint.check_math_alt_text({}, {}, body).level == "pass"


def test_an_author_description_clears_the_warning():
    fm = {"math-alt": {r"\sum_{i=1}^{n} x_i": "the sum of x sub i over i"}}
    body = r"The estimator is $$\sum_{i=1}^{n} x_i$$ throughout."
    assert lint.check_math_alt_text({}, fm, body).level == "pass"


def test_the_generated_readings_are_counted_beside_the_shortfall():
    """So an editor can tell how much of the article is actually owed."""
    body = r"Both $n$ and $p < .05$, and then $$\int_0^1 f(x)\,dx$$."
    result = lint.check_math_alt_text({}, {}, body)
    assert result.level == "warn"
    assert "1 of 3" in result.summary
    assert any("2 other(s)" in d for d in result.details)


def test_an_article_with_no_math_passes():
    assert lint.check_math_alt_text({}, {}, "Ordinary prose.").level == "pass"


def test_the_math_check_runs_in_the_default_pass():
    assert lint.check_math_alt_text in lint.DEFAULT_CHECKS


# ---------- the counts behind the summaries ----------

UNDESCRIBED = "Undescribed figure from page 4 of the source"
BODY_WITH_WORK = "\n\n".join([
    "# A Chapter",
    "Prose that mentions Figure 1.1 and Figure 1.2 in passing.",
    "![A rectangle in burnt orange](assets/one.png)",
    "![" + UNDESCRIBED + "](assets/two.png)",
    "![Figure 1.1. A caption, which is not a description.](assets/three.png)",
    "Figure 1.1. A caption, which is not a description.",
    "An equation, $a^2 + b^2 = c^2$, in a sentence.",
])
BODY_WITH_FAILURES = "\n\n".join([
    "# A Chapter",
    "![](assets/four.png)",
    "A private use codepoint sits here: \uf0fc.",
])
BODIES = [
    ({}, ""),
    ({"images-of-text": ["Figure 1.1"]}, BODY_WITH_WORK),
    ({}, BODY_WITH_FAILURES),
]


def _units_by_check():
    """Every unit name each check reports, over every return path the
    bodies above can reach."""
    seen = {}
    for fm, body in BODIES:
        for check in lint.DEFAULT_CHECKS:
            result = check({}, fm, body)
            seen.setdefault(result.name, set()).update(result.units)
    return seen


def test_no_two_checks_claim_the_same_unit():
    """`register.rollup` sums a unit name across articles, so a name that
    two checks both report would count the same thing twice. The figure
    count is the live case: `check_images_of_text` reads the same images
    `check_alt_text` counts, and deliberately does not count them again.
    """
    owners = {}
    for check_name, units in _units_by_check().items():
        for unit in units:
            assert unit not in owners, (
                unit + " reported by both " + owners[unit] + " and " + check_name)
            owners[unit] = check_name

    assert owners["figures"] == "alt-text"
    assert owners["images-of-text"] == "images-of-text"


def test_a_passing_check_still_reports_its_scale():
    """An archive's figure count has to include the articles with nothing
    wrong with them, or the denominator is only the troubled ones."""
    result = lint.check_alt_text(
        {}, {}, "![A rectangle in burnt orange](assets/one.png)")

    assert result.level == "pass"
    assert result.units == {
        "figures": 1, "figures-no-alt": 0, "figures-undescribed": 0,
        "figures-caption-as-alt": 0, "figures-described": 1,
    }


def test_the_figure_counts_partition_the_figures():
    """Four states, each image in exactly one, so they add back up. A
    double-counted figure would inflate what an archive is told it owes."""
    u = lint.check_alt_text({}, {}, BODY_WITH_WORK).units

    assert u["figures"] == 3
    assert (u["figures-no-alt"] + u["figures-undescribed"]
            + u["figures-caption-as-alt"]
            + u["figures-described"]) == u["figures"]
    assert u["figures-undescribed"] == 1
    assert u["figures-caption-as-alt"] == 1


def test_an_article_with_no_figures_counts_none_rather_than_nothing():
    result = lint.check_alt_text({}, {}, "# A Chapter\n\nProse only.")

    assert result.level == "pass"
    assert result.units == {"figures": 0}


def test_the_unreadable_count_is_a_number_not_a_sentence():
    """`assess.py` read this out of the summary with a regex until the check
    carried it, and the comment there said a second reader for this had
    already been written wrong once."""
    result = lint.check_unreadable_characters(
        {}, {}, "Two of them: \uf0fc\uf0fd.")

    assert result.level == "fail"
    assert result.units == {"unreadable-characters": 2}


def test_an_images_of_text_list_is_counted_without_recounting_the_figures():
    result = lint.check_images_of_text(
        {}, {"images-of-text": ["Figure 1.1", "Figure 1.2"]}, BODY_WITH_WORK)

    assert result.units["images-of-text"] == 2
    assert "figures" not in result.units


def test_both_slots_are_read_the_same_way():
    """A description can sit in the bracket or in `fig-alt`, and one
    function knows which.

    A figure through `pair_figure_captions` keeps the printed caption in the
    bracket and the description in the attribute, so a reader that looks
    only at the bracket sees a caption and reports a description as still
    owed when somebody has already written it. That one-line reader has been
    written wrong three times in this codebase, which is why
    `conversion._carried_description` exists and why this check calls it
    instead of matching the bracket itself.

    The pairing does not currently occur in this archive: of 203 figures,
    one carries a `fig-alt` attribute and its bracket is not a caption. So
    the case below is the one no run would have caught.
    """
    caption = "Figure 1.1. A caption, which is not a description."
    placeholder = "Undescribed figure from page 4 of the source"
    description = "A rectangle in burnt orange"
    shapes = {
        "![" + description + "](a.png)": "figures-described",
        "![" + caption + '](a.png){#fig:x fig-alt="' + description + '"}':
            "figures-described",
        "![" + caption + '](a.png){#fig:x fig-alt="' + placeholder + '"}':
            "figures-undescribed",
        "![" + placeholder + "](a.png)": "figures-undescribed",
        "![](a.png)": "figures-no-alt",
    }
    for body, expected in shapes.items():
        units = lint.check_alt_text({}, {}, body).units
        counted = [k for k in units if k != "figures" and units[k]]
        assert counted == [expected], (body, counted)


def test_a_caption_standing_in_for_a_description_is_still_owed():
    """With no attribute at all the bracket is the only slot, and a caption
    sitting in it is a starting point rather than a description. The printed
    caption below the figure is what gives it away."""
    caption = "Figure 1.1. A rubric for rhetorical reading."
    body = "![" + caption + "](a.png)" + chr(10) + caption

    units = lint.check_alt_text({}, {}, body).units

    assert units["figures-caption-as-alt"] == 1
    assert units["figures-described"] == 0


# ---------- reading order ----------

def _order(recorded):
    return lint.check_reading_order({}, {"reading-order": recorded}, "Prose.\n")


def test_reading_order_is_registered():
    assert lint.check_reading_order in lint.DEFAULT_CHECKS


def test_a_chapter_in_its_source_s_order_passes():
    result = _order({"descents": 0, "worst": 0, "placed": 540, "unplaced": 0})

    assert result.level == "pass"
    assert "540" in result.summary
    assert result.units == {"order-descents": 0, "chapters-order-checked": 1}


def test_a_chapter_that_runs_backwards_is_a_warning():
    """`annoying-ways-people-use-sources` reads 16 descents with a worst of
    637, against a median of 0 across the archive."""
    result = _order({"descents": 16, "worst": 637, "placed": 543,
                     "unplaced": 0})

    assert result.level == "warn"
    assert "16" in result.summary
    assert "637" in result.summary
    assert result.units["order-descents"] == 16
    assert result.units["chapters-order-checked"] == 1


def test_no_record_is_not_a_pass_about_nothing():
    """A chapter nobody has checked and a chapter with nothing wrong look
    identical on a level alone, which is the hole `register.UNRUN` exists
    to keep out of the register. The count of chapters checked is what
    separates them."""
    result = lint.check_reading_order({}, {}, "Prose.\n")

    assert result.level == "pass"
    assert result.units["chapters-order-checked"] == 0
    assert result.details, "the gap has to be said out loud beside the zero"


def test_a_record_that_placed_nothing_counts_as_unchecked():
    """A source whose tree does not reach the text states no order, so
    there was nothing to compare and no reading was made."""
    result = _order({"descents": 0, "worst": 0, "placed": 0, "unplaced": 310})

    assert result.units["chapters-order-checked"] == 0


def test_a_malformed_record_does_not_raise():
    """The field is in the front matter, where an editor can reach it."""
    for bad in ("", [], "two", {"descents": "x"}, {"placed": 5}):
        assert lint.check_reading_order({}, {"reading-order": bad},
                                        "Prose.\n").level == "pass"


def test_descents_are_not_counted_as_editorial_work():
    """`Rollup.work` sums `WORK_ROWS`, and a place to look is not an hour
    of writing. Folding them together would make the one number a journal
    asks for mean two things at once."""
    import register

    work_units = {row.unit for row in register.WORK_ROWS}
    assert "order-descents" not in work_units


def test_the_threshold_sits_where_the_archive_put_it():
    """81 of the archive's 97 checked chapters report no descent, the next
    three report 1, 2 and 4, and the two real defects report 16 and 18. A
    chapter at the top of that noise is not worth an editor's afternoon."""
    assert _order({"descents": 4, "worst": 7, "placed": 500}).level == "pass"
    assert _order({"descents": 5, "worst": 7, "placed": 500}).level == "warn"
