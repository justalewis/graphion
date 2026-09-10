"""Unit tests for cleanups.py.

Each pass has at least one input/output pair, plus an idempotence check
across the full pipeline.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import cleanups


def _log():
    return cleanups.CleanupLog()


def test_strip_highlighter_spans():
    src = "Hello [important phrase]{.mark}, world."
    out = cleanups.strip_highlighter_spans(src, _log())
    assert out == "Hello important phrase, world."


def test_strip_highlighter_spans_idempotent():
    src = "Hello [important phrase]{.mark}, world."
    once = cleanups.strip_highlighter_spans(src, _log())
    twice = cleanups.strip_highlighter_spans(once, _log())
    assert once == twice


def test_strip_highlighter_multiline():
    """A real-world highlight spans multiple paragraphs of a works-cited entry."""
    src = (
        "[Alrayes, Yasser. \"Annotate to Educate: The Dual Life of a\n"
        "Syrian Student & Data Annotator.\" *The Data Workers' Inquiry*,\n"
        "2024, https://data-workers.org/yasser.]{.mark}\n"
    )
    out = cleanups.strip_highlighter_spans(src, _log())
    assert "{.mark}" not in out
    assert "Alrayes, Yasser" in out
    assert "https://data-workers.org/yasser" in out


def test_strip_highlighter_with_nested_brackets():
    """A highlight wrapping a markdown link must preserve the link."""
    src = "before [some text with [[url]{.underline}](http://x.test) link]{.mark} after"
    out = cleanups.strip_highlighter_spans(src, _log())
    assert "{.mark}" not in out
    assert "[[url]{.underline}](http://x.test)" in out
    assert "before " in out and " after" in out


def test_strip_underline_spans():
    src = "see [[https://example.org]{.underline}](https://example.org) for details"
    out = cleanups.strip_underline_spans(src, _log())
    assert "{.underline}" not in out
    assert "[https://example.org](https://example.org)" in out


def test_unescape_quoted_brackets():
    src = r"As Crawford notes, \[citation needed\]."
    out = cleanups.unescape_quoted_brackets(src, _log())
    assert out == "As Crawford notes, [citation needed]."


def test_unescape_quoted_brackets_idempotent():
    src = r"\[a\] then \[b\]"
    a = cleanups.unescape_quoted_brackets(src, _log())
    b = cleanups.unescape_quoted_brackets(a, _log())
    assert a == b == "[a] then [b]"


def test_reassemble_heading_linebreaks_pipe():
    src = "# First half \\|Second half\n\nBody text."
    out = cleanups.reassemble_heading_linebreaks(src, _log())
    assert out.startswith("# First half Second half")


def test_reassemble_heading_linebreaks_no_change():
    src = "# Normal heading\n\nBody."
    out = cleanups.reassemble_heading_linebreaks(src, _log())
    assert out == src


def test_strip_orphan_page_numbers_at_end():
    src = "Some content.\n\n\n42\n"
    out = cleanups.strip_orphan_page_numbers(src, _log())
    assert not out.rstrip().endswith("42")


def test_strip_orphan_page_numbers_mid_file_kept():
    src = "Section 1\n\n42\n\nMore content."
    out = cleanups.strip_orphan_page_numbers(src, _log())
    assert "42" in out


def test_normalize_dashes():
    src = "She said yes—then changed her mind."
    out = cleanups.normalize_dashes(src, _log())
    assert out == "She said yes---then changed her mind."


def test_normalize_dashes_idempotent():
    src = "yes—no"
    a = cleanups.normalize_dashes(src, _log())
    b = cleanups.normalize_dashes(a, _log())
    assert a == b


def test_build_yaml_front_matter_basic_lics():
    src = (
        "An Article About Citation\n"
        "Jane Crawford—Penn State\n"
        "John Hao—UC Irvine\n"
        "Keywords\n"
        "citation; ethics; pedagogy\n"
        "Abstract\n"
        "This essay examines citational practices.\n"
        "\n"
        "# Introduction\n"
        "\n"
        "Opening paragraph.\n"
    )
    out = cleanups.build_yaml_front_matter(src, _log())
    assert out.startswith("---\n")
    assert "title: An Article About Citation" in out
    assert "Jane Crawford" in out
    assert "Penn State" in out
    assert "ethics" in out
    assert "# Introduction" in out


def test_build_yaml_front_matter_idempotent():
    src = (
        "An Article\n"
        "Jane—Penn State\n"
        "Abstract\n"
        "Body of abstract.\n"
        "\n"
        "# Intro\n\n"
        "Body.\n"
    )
    once = cleanups.build_yaml_front_matter(src, _log())
    twice = cleanups.build_yaml_front_matter(once, _log())
    assert once == twice


def test_run_all_idempotent():
    src = (
        "An Article About Citation\n"
        "Jane Crawford—Penn State\n"
        "Keywords\n"
        "citation; ethics\n"
        "Abstract\n"
        "Examines [important]{.mark} citational practices.\n"
        "\n"
        "# Introduction\\|Subhead\n"
        "\n"
        "Opening with \\[brackets\\] and a dash—right here.\n"
        "\n"
        "42\n"
    )
    once, _ = cleanups.run_all(src)
    twice, _ = cleanups.run_all(once)
    assert once == twice


def test_run_all_strips_highlight_and_dash_in_body():
    src = (
        "A Title\n"
        "Jane—UC\n"
        "Abstract\n"
        "Short.\n"
        "\n"
        "# Body\n"
        "Yes—indeed [foo]{.mark} bar.\n"
    )
    out, _ = cleanups.run_all(src)
    assert "{.mark}" not in out
    assert "—" not in out
    assert "foo bar" in out
    assert "yes---indeed" in out.lower()


def test_author_affiliation_em_dash():
    src = (
        "A Title\n"
        "Jane Crawford—Penn State University\n"
        "Abstract\n"
        "Short.\n"
        "\n"
        "# Body\n"
        "Body text.\n"
    )
    out, _ = cleanups.run_all(src)
    assert "name: Jane Crawford" in out
    assert "affiliation: Penn State University" in out


def test_author_with_hyphenated_name():
    """Author 'Sano-Franchini' should not be split at the hyphen."""
    src = (
        "A Title\n"
        "Jenny Sano-Franchini—Virginia Tech\n"
        "Abstract\n"
        "Short.\n"
        "\n"
        "# Body\n"
        "Body text.\n"
    )
    out, _ = cleanups.run_all(src)
    assert "name: Jenny Sano-Franchini" in out
    assert "affiliation: Virginia Tech" in out


# ---------- pair_figure_captions ----------

def _pair(src: str) -> str:
    log = cleanups.CleanupLog()
    return cleanups.pair_figure_captions(src, log)


def test_caption_above_image_is_attached():
    """The sample article keeps its caption in a text box, which Pandoc emits
    as a paragraph before the image rather than after it."""
    src = (
        "Body text mentioning Figure 1 in passing.\n"
        "\n"
        "Figure 1. Flowchart showing the capital appeals process.\n"
        "\n"
        "![](assets/media/image1.png){width=\"2.75in\"}\n"
        "\n"
        "Following body text.\n"
    )
    out = _pair(src)
    assert '![Flowchart showing the capital appeals process.]' in out
    assert "#fig:1" in out
    assert 'width="2.75in"' in out
    # The caption paragraph is consumed, not duplicated.
    assert out.count("Flowchart showing") == 1
    assert "Figure 1. Flowchart" not in out
    # Prose that merely mentions a figure is untouched.
    assert "Body text mentioning Figure 1 in passing." in out


def test_caption_below_image_is_attached():
    src = (
        "![](assets/fig.png)\n"
        "\n"
        "Figure 2: A chart of results.\n"
    )
    out = _pair(src)
    assert "![A chart of results.](assets/fig.png){#fig:2}" in out


def test_caption_after_wins_ties_with_caption_before():
    src = (
        "Figure 1. The one before.\n"
        "\n"
        "![](assets/fig.png)\n"
        "\n"
        "Figure 2. The one after.\n"
    )
    out = _pair(src)
    assert "![The one after.](assets/fig.png){#fig:2}" in out
    assert "Figure 1. The one before." in out


def test_already_captioned_image_untouched():
    src = "![An existing caption.](assets/fig.png){#fig:1}\n\n Figure 9. Not mine.\n"
    assert _pair(src) == src


def test_search_stops_at_a_heading():
    """A caption on the far side of a section break belongs to that section."""
    src = (
        "![](assets/fig.png)\n"
        "\n"
        "# Next Section\n"
        "\n"
        "Figure 7. Belongs to a figure further down.\n"
    )
    out = _pair(src)
    assert "![](assets/fig.png)" in out
    assert "Figure 7. Belongs to a figure further down." in out


def test_caption_survives_intervening_list_paragraphs():
    """The sample article separates caption and image by four list items."""
    src = (
        "Figure 1. Flowchart of the appeals process.\n"
        "\n"
        "1) Trial. Four days.\n"
        "\n"
        "2) Direct appeal.\n"
        "\n"
        "3) Post conviction relief.\n"
        "\n"
        "4) Federal habeas corpus.\n"
        "\n"
        "![](assets/media/image1.png)\n"
    )
    out = _pair(src)
    assert "![Flowchart of the appeals process.](assets/media/image1.png){#fig:1}" in out
    assert "1) Trial. Four days." in out


def test_caption_beyond_the_backstop_is_left_alone():
    src = (
        "![](assets/fig.png)\n\n"
        + "".join(f"Filler {n}.\n\n" for n in range(1, 10))
        + "Figure 7. Too far away to belong to it.\n"
    )
    out = _pair(src)
    assert "![](assets/fig.png)" in out
    assert "Figure 7. Too far away" in out


def test_pair_figure_captions_is_idempotent():
    src = (
        "Figure 1. Flowchart showing the capital appeals process.\n"
        "\n"
        "![](assets/media/image1.png){width=\"2.75in\"}\n"
        "\n"
        "Body.\n"
    )
    once = _pair(src)
    assert _pair(once) == once


def test_blank_line_runs_are_preserved():
    """The pass rejoins paragraphs, so it must not reflow spacing elsewhere."""
    src = "Alpha.\n\n\nBeta.\n\n\n\nGamma.\n"
    assert _pair(src) == src


def test_keywords_on_the_label_line():
    """Word manuscripts often write "Keywords: a; b; c" on a single line."""
    src = (
        "A Title\n"
        "Jane Crawford—Penn State University\n"
        "Keywords: Death row; Dissent; Capital appeals process\n"
        "Abstract\n"
        "Short abstract.\n"
        "\n"
        "# Body\n"
        "Body text.\n"
    )
    out, _ = cleanups.run_all(src)
    assert "Death row" in out
    assert "Capital appeals process" in out
    # The abstract must not be swallowed into the keyword list.
    assert "abstract: Short abstract." in out or "abstract: 'Short abstract.'" in out


def test_keywords_on_the_following_line_still_work():
    src = (
        "A Title\n"
        "Jane Crawford—Penn State University\n"
        "Keywords\n"
        "Alpha; Beta\n"
        "Abstract\n"
        "Short abstract.\n"
        "\n"
        "# Body\n"
        "Body text.\n"
    )
    out, _ = cleanups.run_all(src)
    assert "Alpha" in out and "Beta" in out
