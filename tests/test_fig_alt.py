"""A figure's description reaching the galley it was written for.

A figure that has been through `pair_figure_captions` keeps the caption
people see in the bracket and the description in a `fig-alt` attribute, and
until `filters/fig-alt.lua` existed nothing downstream read it. Pandoc 3.11
writes the attribute into HTML as `data-fig-alt`, which no assistive
technology looks at, and its Typst writer drops it, so the caption stood as
the alt text in every galley and the description reached nobody. The
archive holds one article in that shape; the description queue writes the
slot for every paired figure, so it was about to be general.

Nothing but running Pandoc shows this, so these tests shell out to it and
skip where it is missing.
"""
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
FILTER = REPO / "filters" / "fig-alt.lua"

pandoc = shutil.which("pandoc")
needs_pandoc = pytest.mark.skipif(pandoc is None, reason="Pandoc is not on PATH")

CAPTION = "Figure 1. An example of an ideal attribution."
DESCRIPTION = "A slide headed Discovering Open or Public Domain Resources."

PAIRED = textwrap.dedent("""\
    ![%s](fig.png){#fig:1 fig-alt="%s"}

    Prose after.
    """) % (CAPTION, DESCRIPTION)

BRACKET_ONLY = "![%s](fig.png)\n\nProse after.\n" % DESCRIPTION

EMPTY_ATTRIBUTE = '![%s](fig.png){fig-alt=""}\n' % CAPTION

INLINE = '![%s](fig.png){fig-alt="%s"}\\\n%s\n' % (CAPTION, DESCRIPTION, CAPTION)


def _render(md: str, to: str) -> str:
    out = subprocess.run(
        [pandoc, "-f", "markdown", "-t", to, f"--lua-filter={FILTER}"],
        input=md, capture_output=True, text=True, encoding="utf-8", check=True,
    )
    return out.stdout


@needs_pandoc
def test_the_html_alt_is_the_description_and_the_caption_is_the_caption():
    html = _render(PAIRED, "html")

    assert 'alt="%s"' % DESCRIPTION in html
    assert "<figcaption" in html and CAPTION in html
    assert 'alt="%s"' % CAPTION not in html


@needs_pandoc
def test_the_caption_stops_being_hidden_once_it_says_something_else():
    """Pandoc marks a figcaption `aria-hidden` while it only repeats the alt
    text. Once the two carry different things a reader should have both, and
    Pandoc works that out for itself; this holds that the filter does not
    leave the caption hidden."""
    html = _render(PAIRED, "html")

    assert "aria-hidden" not in html


@needs_pandoc
def test_nothing_is_left_behind_as_a_data_attribute():
    """`data-fig-alt` is where the description used to go, and nothing
    reads it."""
    assert "data-fig-alt" not in _render(PAIRED, "html")


@needs_pandoc
def test_the_typst_galley_carries_the_description_too():
    """The PDF is where this matters most: Typst validates PDF/UA against
    the alt text it is given, so a galley with the caption there passes
    every check and tells a reader what the figure is called."""
    typ = _render(PAIRED, "typst")

    assert 'alt: "%s"' % DESCRIPTION in typ
    assert 'alt: "%s"' % CAPTION not in typ


@needs_pandoc
def test_an_inline_figure_keeps_its_printed_caption_in_the_text():
    """A reconstructed figure is the image, a hard break and the caption
    under it, all one paragraph. Only the alt text moves."""
    html = _render(INLINE, "html")

    assert 'alt="%s"' % DESCRIPTION in html
    assert CAPTION in html


@needs_pandoc
def test_a_figure_with_no_attribute_is_left_alone():
    """Most of this archive keeps the description in the bracket, which is
    already the alt text, and the filter must not disturb it."""
    html = _render(BRACKET_ONLY, "html")

    assert 'alt="%s"' % DESCRIPTION in html


@needs_pandoc
def test_an_empty_attribute_does_not_empty_the_alt_text():
    """An image with no alt text at all costs the galley its conformance,
    so an attribute that says nothing must not be allowed to write nothing
    over the bracket."""
    html = _render(EMPTY_ATTRIBUTE, "html")

    assert 'alt="%s"' % CAPTION in html
    assert 'alt=""' not in html
