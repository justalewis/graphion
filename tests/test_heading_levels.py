"""A galley's heading outline starting at one and skipping nothing.

PDF/UA asks both of a rendered document and a book promises neither, which
only became live when ingest started reading structure trees.
`on-the-other-hand` sets its sections in `Header_A` and its five steps in
`Header_C` with no `Header_B` between, so the chapter really goes from a
first level to a third; and a split article renders two documents from one
body, the teacher half's intermediate dropping the `Teacher Resources`
heading that its template prints as a title, so that galley opens on the
level 2 beneath it. Typst validates the standard rather than declaring it,
so either one aborts the compile and the galley ships unconstrained. Four
did.

Nothing but running Pandoc shows this, so these tests shell out to it and
skip where it is missing.
"""
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[1]
FILTER = REPO / "filters" / "heading-levels.lua"

pandoc = shutil.which("pandoc")
needs_pandoc = pytest.mark.skipif(pandoc is None,
                                  reason="Pandoc is not on PATH")


_HEADER_RE = re.compile(r"\bHeader\s+(\d+)\b")


def levels(markdown, use_filter=True):
    """The heading levels Pandoc writes, in document order.

    Read off the native output, which prints each as `Header 2 (...)`, so
    the assertion is about what Pandoc holds rather than about how a given
    writer spells a heading.
    """
    argv = [pandoc, "-f", "markdown", "-t", "native"]
    if use_filter:
        argv += [f"--lua-filter={FILTER}"]
    out = subprocess.run(argv, input=markdown, capture_output=True,
                         text=True, encoding="utf-8", check=True).stdout
    return [int(m.group(1)) for m in _HEADER_RE.finditer(out)]


@needs_pandoc
def test_a_skipped_level_closes_up():
    """`on-the-other-hand` goes from its section head straight to a step,
    which is the shape that aborted the compile."""
    md = textwrap.dedent("""\
        # A Section

        ### Step 1: Have a Working Thesis

        ### Step 2: Consider the Direct Opposite
        """)

    assert levels(md, use_filter=False) == [1, 3, 3]
    assert levels(md) == [1, 2, 2]


@needs_pandoc
def test_an_outline_that_starts_deep_starts_at_one():
    """The teacher galley's intermediate drops the heading its template
    prints as the title, so the document opens on what sat under it."""
    md = textwrap.dedent("""\
        ## Overview and Teaching Strategies

        Prose.

        ## Discussion Questions
        """)

    assert levels(md, use_filter=False) == [2, 2]
    assert levels(md) == [1, 1]


@needs_pandoc
def test_nesting_is_preserved_not_flattened():
    """Closing the gaps must not lose the hierarchy; a step under a section
    stays under it."""
    md = textwrap.dedent("""\
        # One

        ### Under One

        ## Two

        ### Under Two

        # Three
        """)

    assert levels(md) == [1, 2, 2, 3, 1]


@needs_pandoc
def test_a_positional_skip_is_caught_where_ranking_would_miss_it():
    """A chapter can hold every level and still skip one, so ranking the
    distinct levels is not enough: here all of 1, 2 and 3 are present and
    the first jump is still a skip."""
    md = textwrap.dedent("""\
        # One

        ### Deep

        ## Two

        ### Under Two
        """)

    assert sorted(set(levels(md, use_filter=False))) == [1, 2, 3]
    assert levels(md) == [1, 2, 2, 3]


@needs_pandoc
def test_an_outline_that_is_already_right_is_left_alone():
    md = textwrap.dedent("""\
        # One

        ## Under One

        ### Deeper

        ## Another

        # Two
        """)

    assert levels(md) == [1, 2, 3, 2, 1]


@needs_pandoc
def test_a_document_with_no_headings_survives():
    assert levels("Just prose.\n") == []


@needs_pandoc
def test_the_filter_leaves_the_heading_text_alone():
    """Only the level changes; a filter that rewrote the words would be
    changing the chapter."""
    md = "# A Section\n\n### Step 1: Imagine Hostile Audiences.\n"
    out = subprocess.run(
        [pandoc, "-f", "markdown", "-t", "markdown",
         f"--lua-filter={FILTER}"],
        input=md, capture_output=True, text=True, encoding="utf-8",
        check=True).stdout

    assert "A Section" in out
    assert "Step 1: Imagine Hostile Audiences." in out
    assert "## Step 1" in out


def test_the_filter_is_where_conversion_looks_for_it():
    """Wired into every path that renders Markdown through Pandoc, or a
    galley goes out without it."""
    import conversion

    assert conversion.HEADING_LEVELS_FILTER == FILTER
    assert FILTER.exists()
    assert conversion._heading_levels_filter_args() == [
        f"--lua-filter={FILTER}"]
