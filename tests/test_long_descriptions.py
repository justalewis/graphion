"""A figure's long description reaching the galley it was written for.

Alt text says what a figure is. A flowchart, a whiteboard collage or a data
plot needs somebody to say what it shows and in what order a listener needs
it, which is prose rather than a field: it will not fit an `alt` attribute
and it should not, because an alt read aloud has no structure and no way
back. Section 3.8 of `docs/accessibility-service.md` named the gap and
there was nowhere to put one.

Nothing but running Pandoc shows the rendering half, so those tests shell
out to it and skip where it is missing.
"""
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import conversion
import lint

REPO = Path(__file__).resolve().parents[1]
FILTER = REPO / "filters" / "long-description.lua"

pandoc = shutil.which("pandoc")
needs_pandoc = pytest.mark.skipif(pandoc is None,
                                  reason="Pandoc is not on PATH")

DOC = textwrap.dedent("""\
    ---
    long-descriptions:
      figure-p007-1.jpg: >
        A five stage flowchart. Stage one names the problem.
    ---

    ![A flowchart.](assets/figure-p007-1.jpg)

    Prose after.
    """)


def render(markdown, to):
    return subprocess.run(
        [pandoc, "-f", "markdown+yaml_metadata_block", "-t", to,
         f"--lua-filter={FILTER}"],
        input=markdown, capture_output=True, text=True,
        encoding="utf-8", check=True).stdout


# ---------- the field, and who reads it ----------

def test_the_description_is_read_by_asset_name():
    """An editor types what is in front of them, so a key written as a path
    is matched rather than missed, the way `images-of-text` is read."""
    assert lint.long_descriptions(
        {"long-descriptions": {"assets/figure-p007-1.jpg": "What it shows."}}
    ) == {"figure-p007-1.jpg": "What it shows."}


def test_whitespace_in_the_prose_is_collapsed():
    """It arrives from a folded YAML scalar or a web form, so it comes with
    the line breaks of whatever wrote it."""
    assert lint.long_descriptions(
        {"long-descriptions": {"f.jpg": "One line\n  then another."}}
    ) == {"f.jpg": "One line then another."}


def test_an_empty_or_malformed_field_reads_as_nothing():
    for bad in (None, "", [], "a string", {"f.jpg": ""},
                {"f.jpg": None}, {"": "text"}):
        assert lint.long_descriptions({"long-descriptions": bad}) == {}


def test_it_is_carried_through_a_re_ingest():
    """Nothing can derive it and the page does not state it, which is the
    test the other three carried fields meet."""
    assert "long-descriptions" in conversion.CARRIED_FIELDS


# ---------- what the check reports ----------

def _check(fm, body):
    return lint.check_long_descriptions({}, fm, body)


BODY = "![A flowchart.](assets/figure-p007-1.jpg)\n\nProse.\n"


def test_a_figure_with_a_description_is_counted():
    result = _check({"long-descriptions": {"figure-p007-1.jpg": "Shows."}},
                    BODY)

    assert result.level == "pass"
    assert result.units["figures-long-described"] == 1
    assert result.units["long-descriptions-orphaned"] == 0


def test_no_description_is_a_pass_and_not_a_shortfall():
    """Nothing can tell a complex figure from a simple one, so there is no
    denominator to be short of; inventing a count of figures owed one would
    be the inflation a failed-check count already threatened."""
    result = _check({}, BODY)

    assert result.level == "pass"
    assert result.units["figures-long-described"] == 0
    assert result.details, "the absence of a denominator has to be said"


def test_a_description_naming_a_figure_that_is_not_there_is_a_warning():
    """The only silent failure here. The galley renders, the alt text
    stays, every checker passes, and the prose an editor wrote sits in the
    front matter being read by nothing. A renamed asset does it, and so
    does a typed key."""
    result = _check({"long-descriptions": {"figure-p009-2.jpg": "Shows."}},
                    BODY)

    assert result.level == "warn"
    assert "figure-p009-2.jpg" in " ".join(result.details)
    assert result.units["long-descriptions-orphaned"] == 1


def test_the_check_is_registered():
    assert lint.check_long_descriptions in lint.DEFAULT_CHECKS


def test_no_two_checks_claim_its_units():
    """`register.rollup` sums a unit name across articles, so a name two
    checks both report would count the same thing twice."""
    mine = set(_check({"long-descriptions": {"figure-p007-1.jpg": "x"}},
                      BODY).units)
    for check in lint.DEFAULT_CHECKS:
        if check is lint.check_long_descriptions:
            continue
        other = set(check({}, {}, BODY).units)
        assert not (mine & other), f"{check.__name__} shares {mine & other}"


def test_the_image_names_are_read_in_one_place():
    """`describe.image_names` used to match the images itself; two matchers
    over the same figures is how one comes to be read one way and written
    another."""
    import describe

    assert describe.image_names(BODY) == lint.image_names(BODY)


# ---------- and reaching both galleys ----------

@needs_pandoc
def test_the_html_ties_the_description_to_the_image():
    out = render(DOC, "html")

    assert 'aria-describedby="longdesc-1"' in out
    assert 'id="longdesc-1"' in out
    assert "<details" in out and "</details>" in out
    assert "A five stage flowchart" in out


@needs_pandoc
def test_the_pdf_gets_a_labelled_paragraph_instead():
    """Typst has no disclosure widget and a PDF reader has no way to open
    one, so the description is a plain labelled paragraph there."""
    out = render(DOC, "typst")

    assert "<details" not in out
    assert "Description of the figure above" in out
    assert "A five stage flowchart" in out


@needs_pandoc
def test_it_is_visible_rather_than_hidden():
    """A description hidden from sighted readers is one nobody proofreads,
    and it rots. Neither writer may put it behind `aria-hidden` or off
    screen."""
    out = render(DOC, "html")

    body = re.search(r"<details.*?</details>", out, re.S)
    assert body, "no description block emitted"
    assert "aria-hidden" not in body.group(0)
    assert "display:none" not in body.group(0).replace(" ", "")


@needs_pandoc
def test_a_figure_with_no_description_is_untouched():
    doc = "![A flowchart.](assets/other.jpg)\n\nProse.\n"

    out = render(doc, "html")

    assert "aria-describedby" not in out
    assert "<details" not in out


@needs_pandoc
def test_the_map_does_not_travel_into_the_galley_metadata():
    """It is instruction to this filter and not content; left in the
    metadata it lands in the EPUB package document and the JATS header for
    nothing."""
    out = render(DOC, "html")

    assert "long-descriptions" not in out


@needs_pandoc
def test_two_described_figures_get_their_own_ids():
    doc = textwrap.dedent("""\
        ---
        long-descriptions:
          a.jpg: First description.
          b.jpg: Second description.
        ---

        ![One.](assets/a.jpg)

        ![Two.](assets/b.jpg)
        """)

    out = render(doc, "html")

    assert out.count("<details") == 2
    assert 'id="longdesc-1"' in out and 'id="longdesc-2"' in out


def test_the_filter_is_where_conversion_looks_for_it():
    assert conversion.LONG_DESCRIPTION_FILTER == FILTER
    assert FILTER.exists()
    assert conversion._long_description_filter_args() == [
        f"--lua-filter={FILTER}"]
