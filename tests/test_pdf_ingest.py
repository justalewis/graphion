"""Unit tests for pdf_ingest.py.

These exercise the reconstruction logic on synthesised lines rather than on
a real PDF, because the judgement calls are what can silently go wrong: a
hyphen read the wrong way, a dropped initial welded to its sentence, a
bibliography mistaken for footnotes. Each of those produced wrong output on
the first run against a real chapter.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pdf_ingest


def _line(text, size=11.0, x0=58.5, x1=376.0, top=100.0, page=2, **kw):
    return pdf_ingest.Line(
        text=text, size=size, x0=x0, x1=x1, top=top, page=page, **kw
    )


LAYOUT = pdf_ingest.Layout(
    body_size=11.0, body_left=58.5, body_right=376.3,
    body_top=56.4, body_bottom=572.0, page_centre=216.0,
)


# ---------- hyphens ----------


def test_line_break_hyphen_is_removed():
    """Justified book setting breaks words at the line end. Keeping those
    hyphens leaves "com-plete" through the whole chapter."""
    vocab = {"complete"}
    assert pdf_ingest.rejoin_hyphen("to com", "plete a class", vocab, set()) == \
        "to complete a class"


def test_real_compound_keeps_its_hyphen():
    """The document writing "school-sponsored" mid-line elsewhere is the only
    evidence available that the break was not the typesetter's."""
    assert pdf_ingest.rejoin_hyphen(
        "and school", "sponsored writing", set(), {"school-sponsored"}
    ) == "and school-sponsored writing"


def test_capital_after_hyphen_keeps_it():
    assert pdf_ingest.rejoin_hyphen("anti", "Racist work", set(), set()) == \
        "anti-Racist work"


def test_unknown_pairing_defaults_to_joining():
    """Most mid-word line breaks are soft, so an unrecognised pair joins."""
    assert pdf_ingest.rejoin_hyphen("resil", "ience matters", set(), set()) == \
        "resilience matters"


def test_join_lines_carries_emphasis_across_a_break():
    """A Works Cited title broken mid-word closes its italic run on one line
    and reopens it on the next, which left markers inside the word."""
    lines = [_line("*Community Literacy and the Rhet-*"), _line("*oric of Public Engagement.*")]
    joined = pdf_ingest.join_lines(lines, {"rhetoric"}, set())
    assert "Rhetoric of Public Engagement" in joined
    assert "Rhet-" not in joined
    assert joined.count("*") == 2


# ---------- dropped initials ----------


def test_dropcap_that_is_a_whole_word_gets_its_space_back():
    """The initial is a word of its own here, so flattening the ink gives
    "Afew semesters back"."""
    assert pdf_ingest.split_dropcap("Afew semesters back", {"few"}).startswith("A few")


def test_dropcap_that_starts_its_word_is_left_alone():
    assert pdf_ingest.split_dropcap("Many college students", {"many"}) == \
        "Many college students"


def test_dropcap_with_no_evidence_is_left_alone():
    """Saying nothing is better than guessing a space into the first word."""
    assert pdf_ingest.split_dropcap("Xyzzy plugh", set()) == "Xyzzy plugh"


def test_vocabulary_ignores_the_dropcap_line_s_first_word():
    """Otherwise the broken word teaches the vocabulary that it is a word,
    and then vouches for itself when split_dropcap asks."""
    lines = [
        _line("Afew semesters back, I was", dropcap=True, lead_size=50.8),
        _line("A few minutes into our conversation"),
    ]
    vocab, _ = pdf_ingest.build_vocabulary(lines)
    assert "afew" not in vocab
    assert "few" in vocab


# ---------- bylines ----------


def test_byline_splits_on_the_serial_and():
    names = pdf_ingest._split_authors(
        "Glenn Lester, Taylor Lucas, Sydney Doyle, and Alison Overcash"
    )
    assert names == ["Glenn Lester", "Taylor Lucas", "Sydney Doyle", "Alison Overcash"]


def test_two_author_byline_has_no_comma():
    assert pdf_ingest._split_authors("Chris Thaiss and Stephanie Wade") == \
        ["Chris Thaiss", "Stephanie Wade"]


# ---------- classification ----------


def test_centred_larger_type_is_a_head():
    head = _line("Works Cited", size=12.0, x0=180.1, x1=251.9)
    assert pdf_ingest.classify(head, LAYOUT) == "head"


def test_inset_body_type_is_a_quote():
    quote = _line("But that is not really writing", x0=86.5)
    assert pdf_ingest.classify(quote, LAYOUT) == "quote"


def test_oversized_leading_type_is_a_dropcap():
    assert pdf_ingest.classify(_line("A", size=50.8), LAYOUT) == "dropcap"


# ---------- assembly ----------


def test_indent_starts_a_new_paragraph():
    """There is no blank line between paragraphs on the printed page; the
    first-line indent is the only mark they get."""
    lines = [
        _line("first paragraph runs on"),
        _line("and wraps to here"),
        _line("second paragraph starts", x0=72.9),
    ]
    blocks = pdf_ingest.assemble(lines, LAYOUT, set(), set())
    assert [k for k, _ in blocks] == ["body", "body"]
    assert blocks[0][1] == "first paragraph runs on and wraps to here"


def test_works_cited_entries_split_on_a_hanging_indent():
    """A bibliography inverts the rule: the first line is flush and the turn
    lines are indented, so the body rule runs the whole list together."""
    lines = [
        _line("Works Cited", size=12.0, x0=180.1, x1=251.9),
        _line("Allen, Sarah. The Inspired Writer.", size=10.0),
        _line("Parlor Press, 2010, pp. 34-44.", size=10.0, x0=72.0),
        _line("Bayles, David. Art and Fear.", size=10.0),
        _line("The Image Continuum, 1993.", size=10.0, x0=72.0),
    ]
    blocks = pdf_ingest.assemble(lines, LAYOUT, set(), set())
    bodies = [t for k, t in blocks if k == "body"]
    assert len(bodies) == 2
    assert bodies[0].startswith("Allen, Sarah.")
    assert bodies[1].startswith("Bayles, David.")


def test_lines_beside_a_dropcap_are_not_a_quote():
    """They are indented to clear the initial, which on position alone is
    exactly a block quotation's inset."""
    lines = [
        _line("A few semesters back, I was", dropcap=True, lead_size=50.8),
        _line("working with a student in", x0=90.2),
        _line("a writing class. The student", x0=90.2),
        _line("was searching for a topic."),
    ]
    blocks = pdf_ingest.assemble(lines, LAYOUT, {"few"}, set())
    assert [k for k, _ in blocks] == ["body"]
    assert "quote" not in [k for k, _ in blocks]


LAYOUT_PITCHED = pdf_ingest.Layout(
    body_size=11.0, body_left=58.5, body_right=376.3,
    body_top=56.4, body_bottom=572.0, page_centre=216.0, line_pitch=13.2,
)


def test_quoted_paragraphs_split_on_the_space_between_them():
    """Printed dialogue is several quoted paragraphs sharing one indent.
    Position cannot tell them apart; only the space between them can."""
    lines = [
        _line("But that is not really writing, Ana told me.", x0=94.5, top=200.0),
        _line("What do you mean? I asked.", x0=94.5, top=220.2),
        _line("That is what I do for me, Ana said.", x0=94.5, top=240.6),
    ]
    blocks = pdf_ingest.assemble(lines, LAYOUT_PITCHED, set(), set())
    assert [k for k, _ in blocks] == ["quote", "quote", "quote"]


def test_ordinary_leading_does_not_split_a_paragraph():
    """The guard that matters: the rule must not fire on normal wrap."""
    lines = [
        _line("a quoted sentence that runs", x0=94.5, top=200.0),
        _line("on to a second line", x0=94.5, top=213.2),
        _line("and a third", x0=94.5, top=226.4),
    ]
    blocks = pdf_ingest.assemble(lines, LAYOUT_PITCHED, set(), set())
    assert len(blocks) == 1


def test_a_page_break_is_not_a_paragraph_break():
    """Tops reset on each page, so the step across a page boundary is
    meaningless and must not be read as space between blocks."""
    lines = [
        _line("a paragraph ending at the foot", top=560.0, page=2),
        _line("of one page and continuing", top=56.4, page=3),
    ]
    blocks = pdf_ingest.assemble(lines, LAYOUT_PITCHED, set(), set())
    assert len(blocks) == 1


def test_list_turn_lines_stay_with_their_item():
    lines = [
        _line("1. Which of the three sections", x0=68.5),
        _line("resonated with you the most?", x0=84.1),
        _line("2. What role has writing played", x0=68.5),
    ]
    blocks = pdf_ingest.assemble(lines, LAYOUT, set(), set())
    assert [k for k, _ in blocks] == ["list", "list"]
    assert blocks[0][1] == "1. Which of the three sections resonated with you the most?"


# ---------- markdown ----------


def test_footnotes_are_collected_as_definitions():
    """A printed footnote sits mid-document once the pages are flattened."""
    blocks = [
        ("body", "Body text.[^1]"),
        ("note", "1. This work is licensed under CC BY-NC-ND."),
        ("body", "More body text."),
    ]
    md = pdf_ingest.blocks_to_markdown(blocks)
    assert "Body text.[^1]\n\nMore body text." in md
    assert md.rstrip().endswith("[^1]: This work is licensed under CC BY-NC-ND.")


def test_off_centre_large_type_still_renders_as_a_head():
    md = pdf_ingest.blocks_to_markdown([("title", "Teacher Resources for X")])
    assert md.startswith("# Teacher Resources for X")


# ---------- line text ----------


def _chars(spec):
    """spec: list of (char, fontname, size, bottom)."""
    out, x = [], 0.0
    for text, font, size, bottom in spec:
        out.append({"text": text, "fontname": font, "size": size,
                    "x0": x, "x1": x + size * 0.5, "bottom": bottom})
        x += size * 0.5
    return out


def test_italic_runs_become_emphasis():
    chars = _chars([("n", "AGaramondPro-Regular", 11, 100),
                    ("o", "AGaramondPro-Italic", 11, 100),
                    ("t", "AGaramondPro-Italic", 11, 100)])
    text, italic, _ = pdf_ingest._line_text("not", chars)
    assert italic is True
    assert text == "n*ot*"


def test_superscript_digit_becomes_a_footnote_reference():
    """Flattened, the raised digit reads as part of the sentence:
    "assignment.1"."""
    chars = _chars([(".", "AGaramondPro-Regular", 11, 100),
                    ("1", "AGaramondPro-Regular", 7, 95)])
    text, _, _ = pdf_ingest._line_text(".1", chars, pdf_ingest._superscript_runs(chars, 11.0))
    assert text == ".[^1]"


def test_spaces_come_from_the_supplied_text_not_the_gaps():
    """pdfplumber's spacing is tuned for tightly set justified lines; a fixed
    gap threshold loses every space in one."""
    chars = _chars([("a", "F", 11, 100), ("b", "F", 11, 100)])
    text, _, _ = pdf_ingest._line_text("a b", chars)
    assert text == "a b"


# ---------- the opening page ----------


def test_opening_page_body_keeps_everything_once_an_overview_is_found():
    """A chapter's title furniture is already consumed by then, so what is
    left below the Overview is body."""
    lines = [_line("A few semesters back, I was working with a student.", page=1),
             _line("Ana was searching for a topic.", page=1)]
    kept = pdf_ingest.opening_page_body(lines, LAYOUT, has_overview=True)
    assert kept == lines


def test_opening_page_body_cuts_to_the_first_head_without_an_overview():
    """On a chapter whose Overview was missed, what sits above the first head
    is title furniture that was not recognised as any, so it is dropped
    rather than run into the body as prose."""
    stray = _line("Many college students write for one reason only.", page=1)
    head = _line("Introduction: What Is Writing, Really?", size=12.0, page=1)
    body = _line("A few semesters back, I was working with a student.", page=1)
    assert pdf_ingest.classify(head, LAYOUT) == "head"
    kept = pdf_ingest.opening_page_body([stray, head, body], LAYOUT,
                                        has_overview=False)
    assert kept == [head, body]


def test_opening_page_body_keeps_a_page_that_has_no_head_at_all():
    """Front and back matter prints its title and runs straight into prose.
    The title is consumed as the title, so no head is left to cut to, and
    cutting the page away lost the volume 5 acknowledgments its first page."""
    dropcap = _line("T", size=30.0, page=1)
    body = _line("hree years ago, in the spring of 2020, we put out a call.",
                 page=1)
    more = _line("That CFP marked a turning point for the project.", page=1)
    kept = pdf_ingest.opening_page_body([dropcap, body, more], LAYOUT,
                                        has_overview=False)
    assert kept == [dropcap, body, more]


def test_opening_page_body_of_an_empty_page_is_empty():
    assert pdf_ingest.opening_page_body([], LAYOUT, has_overview=False) == []


# ---------- the Overview ----------


def test_overview_head_is_recognised_including_the_archive_misspelling():
    """Volume 5 chapter 21 heads its overview "Overvew", so matching the
    word exactly cost that chapter its abstract."""
    assert pdf_ingest.is_overview_head("Overview")
    assert pdf_ingest.is_overview_head("overview")
    assert pdf_ingest.is_overview_head("Overvew")
    assert pdf_ingest.is_overview_head("Overview:")


def test_the_teacher_overview_head_is_not_an_overview():
    """Every chapter's teacher material opens "Overview and Teaching
    Strategies", which abstracts nothing and must not be read as one."""
    assert not pdf_ingest.is_overview_head("Overview and Teaching Strategies")
    assert not pdf_ingest.is_overview_head("Introduction")


def test_overview_is_read_from_prose_under_the_byline_when_unheaded():
    """Chapter 20 of volume 5 runs its overview straight on from the byline
    with no head over it, and the whole paragraph was being dropped."""
    title = _line("20 What's the Diff?", size=18.0, page=1)
    byline = _line("Benjamin Miller", size=12.0, page=1, italic=True)
    over1 = _line("This essay recommends that writers use digital tools.", page=1)
    over2 = _line("These revisitable histories are helpful in several ways.", page=1)
    fm, overview, consumed, _ = pdf_ingest.extract_front_matter(
        [title, byline, over1, over2], LAYOUT)
    assert fm["chapter-number"] == 20
    assert overview == [over1, over2]
    assert id(over1) in consumed and id(over2) in consumed


def test_prose_under_the_byline_stops_at_the_first_head():
    """Only what sits above the first head is the overview; the body that
    follows that head is body."""
    title = _line("20 What's the Diff?", size=18.0, page=1)
    byline = _line("Benjamin Miller", size=12.0, page=1, italic=True)
    over = _line("This essay recommends that writers use digital tools.", page=1)
    head = _line("Introduction", size=12.0, page=1)
    body = _line("Whether you know it or not, you revise as you write.", page=1)
    _, overview, consumed, _ = pdf_ingest.extract_front_matter(
        [title, byline, over, head, body], LAYOUT)
    assert overview == [over]
    assert id(body) not in consumed


def test_overview_ends_at_the_next_paragraph_indent():
    """Volume 5 chapter 21 opens its body with a plain paragraph rather than
    a head, so "up to the first body head" ran the overview 96 words into the
    chapter and split a sentence across the two."""
    head = _line("Overvew", size=12.0, page=1)
    over = _line("From school to the workplace, managing team projects.", page=1)
    over2 = _line("In this chapter, we guide students through the tools.", page=1)
    body = _line("The notorious group project, bane of many students.",
                 x0=58.5 + pdf_ingest.INDENT_MIN + 4, page=1)
    _, overview, consumed, _ = pdf_ingest.extract_front_matter(
        [head, over, over2, body], LAYOUT)
    assert overview == [over, over2]
    assert id(body) not in consumed


def test_starts_paragraph_reads_the_first_line_indent():
    flush = _line("a continuation line of the same paragraph.")
    indented = _line("A new paragraph.", x0=58.5 + pdf_ingest.INDENT_MIN + 4)
    assert not pdf_ingest.starts_paragraph(flush, LAYOUT)
    assert pdf_ingest.starts_paragraph(indented, LAYOUT)


def test_overview_ends_at_a_dropped_initial():
    """Volume 5 chapter 21 opens its body with a dropped initial, which
    begins a paragraph without indenting it, so the indent rule alone let the
    overview run on into the chapter."""
    head = _line("Overvew", size=12.0, page=1)
    over = _line("From school to the workplace, managing team projects.", page=1)
    body = _line("The notorious group project, bane of many students.",
                 page=1, dropcap=True)
    _, overview, consumed, _ = pdf_ingest.extract_front_matter(
        [head, over, body], LAYOUT)
    assert overview == [over]
    assert id(body) not in consumed


def test_starts_paragraph_counts_a_dropped_initial():
    flush = _line("a continuation line of the same paragraph.")
    cap = _line("The notorious group project.", dropcap=True)
    assert not pdf_ingest.starts_paragraph(flush, LAYOUT)
    assert pdf_ingest.starts_paragraph(cap, LAYOUT)


# ---------- figures ----------

# A Markdown hard line break: a backslash, then the newline. The figure and
# the caption printed under it share one paragraph, joined by this, so the
# image stays an image: alone in a paragraph it would become a Pandoc Figure,
# and the journal's figures filter numbers every Figure from 1 in document
# order, which would print "Figure 1." over a caption reading "Figure 7.4"
# and leave every "see Figure 7.3" in the prose pointing at the wrong one.
HARD_BREAK = "\\" + "\n"


def test_the_three_ways_the_archive_punctuates_a_caption():
    for text in ("Figure 4.1: An exploded view drawing",
                 "Figure 3.3. Example of a Scientific Abstract",
                 "Figure 15.1 Pidgin Translation of BBC News"):
        assert pdf_ingest.is_figure_caption(text), text


def test_prose_referring_to_a_figure_is_not_a_caption():
    """The punctuation cannot separate them, because the archive uses all
    three. A caption continues with the figure's name and prose continues
    with a verb, so the capital after the number is the test."""
    for text in ("Figure 7.6 shows that sales tend to be highest",
                 "Table 3.1 provides some quick differences",
                 "Figure 11.1)."):
        assert not pdf_ingest.is_figure_caption(text), text


def test_a_table_caption_names_no_image():
    """A table in this series is set as type, so pairing its caption with a
    figure would put the wrong picture under it."""
    assert not pdf_ingest.is_figure_caption(
        "Table 3.1. Abstracts Versus Executive Summaries")


def test_caption_alt_text_drops_the_label_and_the_credit():
    """"Figure 4.1" describes nothing and neither does a source credit."""
    assert pdf_ingest.caption_alt_text(
        "Figure 4.1: An exploded view drawing (Source: USPTO)"
    ) == "An exploded view drawing"
    assert pdf_ingest.caption_alt_text("Figure 7.1: Chair") == "Chair"


def test_undescribed_alt_names_the_page_it_came_from():
    assert pdf_ingest.undescribed_alt(27) == \
        "Undescribed figure from page 27 of the source"


def test_a_captioned_figure_joins_its_caption_in_one_block():
    blocks = [("body", "Prose before."),
              ("note", "Figure 7.4: Schematic bridge diagram"),
              ("body", "Prose after.")]
    figures = [{"page": 16, "index": 0, "name": "figure-p016-1.jpg"}]
    out, notes = pdf_ingest.place_figures(
        blocks, figures, {(16, 0): "Figure 7.4: Schematic bridge diagram"})
    assert [kind for kind, _ in out] == ["body", "figure", "body"]
    assert out[1][1] == (
        "![Schematic bridge diagram](assets/figure-p016-1.jpg)"
        + HARD_BREAK + "Figure 7.4: Schematic bridge diagram")
    assert "placed 1" in notes[0]


def test_alt_text_comes_from_the_whole_caption_not_its_first_line():
    """A caption that wraps is several lines on the page and one block here.
    Reading the line the caption was found on cut 36 of the 95 figures' alt
    text short, 13 of them mid-word on a hyphen."""
    whole = ("Figure 1: Rowhouse displays outside of North Philadelphia's "
             "Urban Crisis Response Center")
    blocks = [("note", whole)]
    figures = [{"page": 5, "index": 0, "name": "figure-p005-1.jpg"}]
    # What the planner matched on is the first line, hyphenated as printed.
    out, _ = pdf_ingest.place_figures(
        blocks, figures,
        {(5, 0): "Figure 1: Rowhouse displays outside of North Philadelphia's "
                 "Urban Crisis Re-"})
    text = [t for kind, t in out if kind == "figure"][0]
    assert "Urban Crisis Response Center]" in text
    assert "Crisis Re-]" not in text


def test_an_uncaptioned_figure_is_kept_and_said_to_be_undescribed():
    """Dropping it costs the reader the figure and leaving its alt text empty
    costs the galley its conformance, so it is kept and counted."""
    figures = [{"page": 27, "index": 0, "name": "figure-p027-1.jpg"}]
    out, notes = pdf_ingest.place_figures([("body", "Prose.")], figures, {})
    figure_text = [t for kind, t in out if kind == "figure"][0]
    assert "Undescribed figure from page 27" in figure_text
    assert any("no caption" in note for note in notes)


def test_a_caption_after_a_footnote_starts_its_own_block():
    """A caption is set at footnote size, so it reads as a note, and a new
    note only begins at a number. Carrying none, three of the seven captions
    in volume 6 chapter 7 were appended to the footnotes of the page before
    and vanished from the chapter."""
    note = _line("3 The author thanks Matt Crouch for the brochure.", size=9.0)
    caption = _line("Figure 7.1: Chair", size=10.0)
    blocks = pdf_ingest.assemble([note, caption], LAYOUT, set(), set())
    assert "Figure 7.1: Chair" in [text for _, text in blocks]


def test_a_caption_is_not_collected_away_with_the_footnotes():
    """blocks_to_markdown gathers notes at the end of the document, which is
    right for a footnote and wrong for a caption: every caption in both
    volumes was being moved to the back of its chapter."""
    markdown = pdf_ingest.blocks_to_markdown([
        ("note", "Figure 7.1: Chair"),
        ("body", "Prose that follows the figure."),
        ("note", "3 A real footnote."),
    ])
    assert markdown.index("Figure 7.1: Chair") < \
        markdown.index("Prose that follows")
    assert markdown.rstrip().endswith("A real footnote.")
