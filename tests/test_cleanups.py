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


# ---------- merge_continued_headings ----------

def test_merge_heading_split_across_two_paragraphs():
    """Pressing Enter mid-heading leaves two Heading paragraphs in Word."""
    src = "# DEATH ROW, ABOLITION, AND WRITING STUDIES:\n\n# A LITERATURE REVIEW\n\nBody.\n"
    out = cleanups.merge_continued_headings(src, _log())
    assert "# DEATH ROW, ABOLITION, AND WRITING STUDIES: | A LITERATURE REVIEW" in out
    assert out.count("#") == 1


def test_merge_leaves_genuine_consecutive_headings_alone():
    """A finished heading followed by another is a section, not a split."""
    src = "# Introduction\n\n# Methods\n\nBody.\n"
    assert cleanups.merge_continued_headings(src, _log()) == src


def test_merge_requires_matching_levels():
    src = "# Section One:\n\n## A Subsection\n\nBody.\n"
    assert cleanups.merge_continued_headings(src, _log()) == src


def test_merge_continued_headings_is_idempotent():
    src = "# Part One:\n\n# Continued\n\nBody.\n"
    once = cleanups.merge_continued_headings(src, _log())
    assert cleanups.merge_continued_headings(once, _log()) == once


def test_spaced_pipe_survives_the_word_artifact_merge():
    """The forced-break convention must not be undone by the artifact repair."""
    src = "## Facing What's Human: | From Dialogic Intertextuality\n\nBody.\n"
    out = cleanups.reassemble_heading_linebreaks(src, _log())
    assert " | " in out


# ---------- normalize_scene_breaks ----------

def test_asterisk_ornament_becomes_a_thematic_break():
    src = "Body one.\n\n**\\***\n\nBody two.\n"
    out = cleanups.normalize_scene_breaks(src, _log())
    assert "\n---\n" in out
    assert "*" not in out.replace("Body one.", "").replace("Body two.", "")


def test_plain_asterisk_ornament_also_normalized():
    src = "Body one.\n\n*\n\nBody two.\n"
    out = cleanups.normalize_scene_breaks(src, _log())
    assert "\n---\n" in out


def test_scene_break_leaves_real_emphasis_alone():
    src = "Body one.\n\n*emphasised words here*\n\nBody two.\n"
    assert cleanups.normalize_scene_breaks(src, _log()) == src


def test_scene_break_never_converts_the_first_paragraph():
    """A leading --- would read as the start of a YAML front matter block."""
    src = "*\n\nBody.\n"
    assert cleanups.normalize_scene_breaks(src, _log()) == src


def test_normalize_scene_breaks_is_idempotent():
    src = "Body one.\n\n**\\***\n\nBody two.\n"
    once = cleanups.normalize_scene_breaks(src, _log())
    assert cleanups.normalize_scene_breaks(once, _log()) == once


# ---------- citation years must survive the div-footnote pass ----------

def test_works_cited_year_is_not_stripped():
    '''A works-cited entry ends in a year and a period, the same shape as an
    orphan list marker. Stripping those unconditionally deleted the
    publication year from every such citation.'''
    for entry in (
        'Baker-Bell, April. *Linguistic Justice*. Routledge, 2020.',
        'Sered, Danielle. *Until We Reckon*. The New Press, 2019.',
        'Goldberg, Jess A. *Abolition Time*. U of Minnesota P, 2024.',
    ):
        out = cleanups.convert_pandoc_div_footnotes_to_native(entry + chr(10), _log())
        assert out.rstrip(chr(10)) == entry, 'year stripped from ' + repr(entry)


def test_sentence_ending_in_a_number_survives():
    src = 'The court denied the motion in 42.' + chr(10)
    assert cleanups.convert_pandoc_div_footnotes_to_native(src, _log()) == src


def test_year_survives_the_full_pipeline():
    src = (
        'A Title' + chr(10)
        + 'Jane Crawford' + chr(0x2014) + 'Penn State' + chr(10)
        + 'Abstract' + chr(10) + 'Short.' + chr(10) + chr(10)
        + '# Works Cited' + chr(10) + chr(10)
        + 'Baker-Bell, April. *Linguistic Justice*. Routledge, 2020.' + chr(10)
    )
    out, _ = cleanups.run_all(src)
    assert 'Routledge, 2020.' in out


# ---------- restore_flattened_endnotes ----------

ARROW = chr(0x21a9)


def test_flattened_endnotes_get_a_heading_and_lose_their_arrows():
    '''An HTML intermediate turns the endnote section into a plain numbered
    list whose items end with a back-reference arrow.'''
    src = (
        '# Works Cited' + chr(10) + chr(10)
        + 'Berger, Dan. *Jacobin*, 2017.' + chr(10) + chr(10)
        + '1. This is an excerpt from a memoir. [' + ARROW + '](#fnref1)' + chr(10)
        + '2. A second note. [' + ARROW + '](#fnref2)' + chr(10)
    )
    out = cleanups.restore_flattened_endnotes(src, _log())
    assert ARROW not in out
    assert '# Notes' in out
    assert out.index('# Notes') > out.index('Berger, Dan')
    assert 'This is an excerpt from a memoir.' in out


def test_flattened_endnotes_not_double_headed():
    src = '# Notes' + chr(10) + chr(10) + '1. Already introduced. [' + ARROW + '](#fnref1)' + chr(10)
    out = cleanups.restore_flattened_endnotes(src, _log())
    assert out.count('# Notes') == 1
    assert ARROW not in out


def test_ordinary_trailing_list_is_left_alone():
    '''The arrow is the discriminator; a plain numbered list is not endnotes.'''
    src = '# Steps' + chr(10) + chr(10) + '1. First thing' + chr(10) + '2. Second thing' + chr(10)
    assert cleanups.restore_flattened_endnotes(src, _log()) == src


def test_restore_flattened_endnotes_is_idempotent():
    src = '1. A note. [' + ARROW + '](#fnref1)' + chr(10)
    once = cleanups.restore_flattened_endnotes(src, _log())
    assert cleanups.restore_flattened_endnotes(once, _log()) == once


# ---------- strip_empty_anchor_spans ----------

def test_mammoth_anchor_span_is_removed_from_heading():
    '''Mammoth turns every bookmark into an empty span holding only an id.'''
    src = '# []{#_heading=h.p3ibalxwq0w}DEATH ROW, ABOLITION' + chr(10)
    out = cleanups.strip_empty_anchor_spans(src, _log())
    assert out == '# DEATH ROW, ABOLITION' + chr(10)


def test_anchor_span_removed_mid_paragraph():
    src = 'Body text []{#_heading=h.abc123} continues here.' + chr(10)
    out = cleanups.strip_empty_anchor_spans(src, _log())
    assert '_heading' not in out
    assert 'Body text' in out and 'continues here.' in out


def test_leading_anchor_does_not_strand_a_bracket():
    '''The drop cap takes the first character of the opening paragraph. A
    stranded bracket became an unclosed #dropcap[ and failed the render.'''
    src = '[]{#_heading=h.x69hh1ymbnnc}When I made it to Parchman' + chr(10)
    out = cleanups.strip_empty_anchor_spans(src, _log())
    assert out.startswith('When I made it')


def test_span_with_real_content_is_kept():
    src = 'A [real span]{#some-id} stays.' + chr(10)
    assert cleanups.strip_empty_anchor_spans(src, _log()) == src


def test_span_with_a_class_is_kept():
    src = 'Highlighted [words]{.mark} stay.' + chr(10)
    assert cleanups.strip_empty_anchor_spans(src, _log()) == src


def test_strip_empty_anchor_spans_is_idempotent():
    src = '# []{#_heading=h.abc}A Heading' + chr(10) + '[]{#_heading=h.def}Body.' + chr(10)
    once = cleanups.strip_empty_anchor_spans(src, _log())
    assert cleanups.strip_empty_anchor_spans(once, _log()) == once


# ---------- split_repeated_author_entries ----------

def _split(src):
    return cleanups.split_repeated_author_entries(src, _log())


def test_repeated_author_entry_gets_its_own_line():
    r"""MLA replaces a repeated author with a dash run; Pandoc escapes the
    leading hyphens, so it arrives as \-\--. rather than ---."""
    src = (
        '# Works Cited' + chr(10) + chr(10)
        + r'Wacquant, Loic. *Class, Race.* 2010. Accessed 16 June 2024. \-\--. *Punishing the Poor*. Duke UP, 2009.' + chr(10)
    )
    out = _split(src)
    lines = [l for l in out.splitlines() if l.strip()]
    assert len(lines) == 3, lines
    assert lines[1].startswith('Wacquant, Loic')
    assert lines[2].lstrip().startswith(r'\-\--.')
    assert 'Punishing the Poor' in lines[2]


def test_plain_dash_marker_also_splits():
    src = '# References' + chr(10) + chr(10) + 'Author, A. *One.* 2019. ---. *Two.* 2020.' + chr(10)
    out = _split(src)
    lines = [l for l in out.splitlines() if l.strip()]
    assert len(lines) == 3
    assert lines[2].startswith('---.')


def test_body_prose_is_not_split():
    '''Only the bibliography is touched; a dash run in prose stays put.'''
    src = '# Introduction' + chr(10) + chr(10) + 'A sentence ---. and it continues here.' + chr(10)
    assert _split(src) == src


def test_entry_without_a_marker_is_untouched():
    src = '# Works Cited' + chr(10) + chr(10) + 'Baker-Bell, April. *Linguistic Justice*. Routledge, 2020.' + chr(10)
    assert _split(src) == src


def test_several_markers_in_one_entry():
    src = ('# Works Cited' + chr(10) + chr(10)
           + 'Author, A. *One.* 2018. ---. *Two.* 2019. ---. *Three.* 2020.' + chr(10))
    lines = [l for l in _split(src).splitlines() if l.strip()]
    assert len(lines) == 4, lines


def test_split_repeated_author_entries_is_idempotent():
    src = ('# Works Cited' + chr(10) + chr(10)
           + 'Author, A. *One.* 2018. ---. *Two.* 2019.' + chr(10))
    once = _split(src)
    assert _split(once) == once
