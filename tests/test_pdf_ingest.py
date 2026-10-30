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


# ---------- tables ----------


def test_a_table_caption_is_told_from_a_reference_to_one():
    assert pdf_ingest.is_table_caption(
        "Table 3.1. Abstracts Versus Executive Summaries")
    assert pdf_ingest.is_table_caption("Table 1 A comparison between posters")
    assert not pdf_ingest.is_table_caption(
        "Table 3.1 provides some quick differences to keep in mind")
    assert not pdf_ingest.is_table_caption("Table 4.1 is an example that")


def test_clean_table_drops_empty_columns_and_rejoins_broken_words():
    """A cell is wrapped as it was printed, so it arrives with the line
    breaks and hyphens in it; "introduc- tion" has to come back together or
    the table reads as badly as the prose it replaces."""
    rows = pdf_ingest._clean_table([
        ["", "Angel’s Poster", "Akeelah’s Poster", ""],
        ["Organization", "Emphasizes the introduc-\ntion and conclusion", "", ""],
    ])
    assert rows[0] == ["", "Angel’s Poster", "Akeelah’s Poster"]
    assert rows[1][1] == "Emphasizes the introduction and conclusion"


def test_clean_table_escapes_a_pipe_inside_a_cell():
    """An unescaped pipe would close the column it sits in."""
    rows = pdf_ingest._clean_table([["a | b", "c"], ["d", "e"]])
    assert rows[0][0] == r"a \| b"


def test_table_to_markdown_gives_the_first_row_as_the_header():
    """The header is what lets a screen reader say which column a cell is in,
    and a table read as prose has no columns to name."""
    markdown = pdf_ingest.table_to_markdown(
        [["", "Abstracts", "Executive Summaries"],
         ["Length", "One paragraph.", "One page maximum."]])
    lines = markdown.split("\n")
    assert lines[0] == "|  | Abstracts | Executive Summaries |"
    assert lines[1] == "| --- | --- | --- |"
    assert lines[2] == "| Length | One paragraph. | One page maximum. |"


def test_lines_inside_a_table_are_taken_out_of_the_prose():
    """Reading a two-column table across its columns interleaved the cells
    into prose: "detailing as being the most import- lab procedures ant
    while" is one word cut in half with a cell from the next column inside
    it. Adding the table without removing those lines leaves both."""
    inside = _line("Organization Emphasizes the introduc- Mirrors the IMRAD",
                   page=5, top=200.0)
    outside = _line("Ordinary prose further down the page.", page=5, top=400.0)
    caption = _line("Table 1 A comparison between posters", page=5, top=150.0)
    tables = {5: [((58.0, 160.0, 373.0, 320.0), [["a", "b"], ["c", "d"]])]}
    kept, dropped, anchors = pdf_ingest.drop_lines_inside_tables(
        [caption, inside, outside], tables)
    assert dropped == 1
    assert inside not in kept
    assert caption in kept and outside in kept
    # The caption above the table is the line the table is anchored to.
    assert anchors[(5, 0)] == "Table 1 A comparison between posters"


def test_a_table_is_placed_after_its_caption_in_reading_order():
    """A table's caption is set above it and the two part company across a
    page break, so they are paired in reading order rather than by page:
    both of chapter 11's were on a different page from their table."""
    blocks = [("body", "Prose."),
              ("note", "Table 1 A comparison between posters"),
              ("body", "More prose."),
              ("note", "Table 2 The second one")]
    tables = [{"page": 5, "index": 0, "rows": [["a", "b"], ["c", "d"]]},
              {"page": 9, "index": 0, "rows": [["e", "f"], ["g", "h"]]}]
    out, notes = pdf_ingest.place_tables(blocks, tables)
    kinds = [kind for kind, _ in out]
    assert kinds == ["body", "note", "table", "body", "note", "table"]
    assert "placed 2" in notes[0]


def test_a_table_with_no_caption_to_pair_with_is_reported():
    blocks = [("body", "Prose with no table caption in it.")]
    tables = [{"page": 3, "index": 0, "rows": [["a", "b"], ["c", "d"]]}]
    out, notes = pdf_ingest.place_tables(blocks, tables)
    assert any(kind == "table" for kind, _ in out)
    assert any("matched no caption" in note for note in notes)


# ---------- symbol fonts ----------


def test_wingdings_bullet_is_not_a_brace():
    """Wingdings byte 0x7B is an open circle. Extracted as text it gives "{",
    which reads as punctuation and sorts as code; forty-seven of them stand
    beside the options of a survey in volume 6."""
    chars = _chars([("{", "TKVGHF+Wingdings-Regular", 11, 100),
                    ("A", "AGaramondPro-Regular", 11, 100)])
    text, _, _ = pdf_ingest._line_text("{A", chars)
    assert text == "\u25cbA"


def test_wingdings_smiley_is_not_the_letter_j():
    """The Outlook artifact: a smiling face typed as J. The chapter it sits
    in is discussing emoticons, so the letter reads as a sentence."""
    chars = _chars([("J", "TKVGHF+Wingdings-Regular", 11, 100)])
    text, _, _ = pdf_ingest._line_text("J", chars)
    assert text == "\u263a"


def test_a_private_use_codepoint_from_a_symbol_font_is_translated():
    """U+F0FC is Wingdings 0xFC, a check mark. A private use codepoint says
    nothing to a screen reader, and Typst validates PDF/UA rather than
    declaring it, so one of them costs the chapter its conformance."""
    chars = _chars([("\uf0fc", "TKVGHF+Wingdings-Regular", 11, 100)])
    text, _, _ = pdf_ingest._line_text("\uf0fc", chars)
    assert text == "\u2713"


def test_an_unmapped_private_use_codepoint_is_dropped():
    """Nothing can read it and it aborts the compile, so the choice is
    between losing the glyph and losing the galley."""
    chars = _chars([("A", "AGaramondPro-Regular", 11, 100),
                    ("\uf0dd", "TKVGHF+Wingdings-Regular", 11, 100),
                    ("B", "AGaramondPro-Regular", 11, 100)])
    text, _, _ = pdf_ingest._line_text("A\uf0ddB", chars)
    assert text == "AB"


def test_an_unmapped_ordinary_code_from_a_symbol_font_is_left_alone():
    """Dropping it on the strength of a font-name match could eat real
    text, which is the worse failure."""
    chars = _chars([("Q", "TKVGHF+Wingdings-Regular", 11, 100)])
    text, _, _ = pdf_ingest._line_text("Q", chars)
    assert text == "Q"


def test_opensymbol_and_symbolmt_are_left_alone():
    """Both decode their bullet to U+2022 already; remapping them would
    break text that is not broken. The match is on the whole family after
    the subset prefix, not a substring of it."""
    assert pdf_ingest.symbol_family("ABCDEF+OpenSymbol") is None
    assert pdf_ingest.symbol_family("ABCDEF+SymbolMT") is None
    assert pdf_ingest.symbol_family("POEHNO+Symbol") == "symbol"
    assert pdf_ingest.symbol_family("TKVGHF+Wingdings-Regular") == "wingdings"


def test_a_symbol_font_character_in_a_table_cell_is_translated():
    """extract() strips the font off, so the substitution has to be rebuilt
    from the page; a check mark is the whole content of its cell, and
    leaving it as Wingdings loses the column."""
    trans = {"\uf0fc": "\u2713"}
    rows = pdf_ingest._clean_table(
        [["Move", "Email"], ["Apologizing", "\uf0fc"]], trans)
    assert rows == [["Move", "Email"], ["Apologizing", "\u2713"]]


def test_a_code_used_as_both_symbol_and_text_in_one_table_is_left_alone():
    """Without positions inside the cell the two cannot be told apart, and
    changing both would corrupt the text to fix the glyph."""
    class _Crop:
        chars = [{"text": "{", "fontname": "TKVGHF+Wingdings-Regular"},
                 {"text": "{", "fontname": "AGaramondPro-Regular"},
                 {"text": "\uf0fc", "fontname": "TKVGHF+Wingdings-Regular"}]

    class _Page:
        def crop(self, bbox):
            return _Crop()

    trans = pdf_ingest._symbol_translations(_Page(), (0, 0, 10, 10))
    assert "{" not in trans
    assert trans["\uf0fc"] == "\u2713"


def test_the_three_ways_the_archive_abbreviates_the_label():
    """Volume 2 prints "Fig. 1." over all seventeen of its captions and
    volume 6 prints "Fig 1.0"; matching only "Figure" read volume 2 as a
    book that captions nothing."""
    assert pdf_ingest.is_figure_caption("Fig. 1. Twitter sends brief messages.")
    assert pdf_ingest.is_figure_caption("Fig 1.0. The Structure of RNA and DNA")
    assert pdf_ingest.is_figure_caption("Figure 1. A desk seen from above.")


def test_prose_referring_to_a_figure_by_the_short_label_is_not_a_caption():
    """"Fig. 1, we see that" continues a sentence; a caption does not."""
    assert not pdf_ingest.is_figure_caption(
        "Fig. 1, we see that there is a crowded set of partially inhabited")


def test_alt_text_drops_the_short_label_too():
    assert pdf_ingest.caption_alt_text(
        "Fig. 1. An unformatted resume.") == "An unformatted resume"


def test_an_abbreviated_table_label_is_a_table_caption():
    assert pdf_ingest.is_table_caption("Tab. 2. A comparison of two genres")
    assert pdf_ingest.is_table_caption("Table 2. A comparison of two genres")


def test_a_trailing_credit_sentence_is_not_part_of_the_description():
    """Who made a picture is not what is in it, and a screen reader reading
    alt text cannot skip past the credit to reach the description."""
    assert pdf_ingest.caption_alt_text(
        "Figure 1. A cheeseburger is held in a close-up shot. Photo by Jenae "
        "Cohn") == "A cheeseburger is held in a close-up shot"
    assert pdf_ingest.caption_alt_text(
        "Figure 2. A menu with three columns. Menu image courtesy of Mistie "
        "Cohn") == "A menu with three columns"


def test_a_bare_by_is_part_of_the_description():
    """"chord changes for 'Heart of Gold' by Neil Young" names the song, not
    the photographer, so the credit has to name itself one."""
    kept = pdf_ingest.caption_alt_text(
        "Figure 6. Lyrics and chord changes for \u201cHeart of Gold\u201d by "
        "Neil Young with a fingering chart")
    assert kept.endswith("with a fingering chart")


def test_a_sentence_opening_with_from_is_not_a_credit():
    kept = pdf_ingest.caption_alt_text(
        "Figure 8. A diagram. From the beginning, writers plan before drafting.")
    assert "From the beginning" in kept


def test_a_caption_that_is_only_a_credit_keeps_it():
    """Trimming it to nothing would cost the galley its conformance, and an
    empty alt is not a better answer than a credit."""
    only = pdf_ingest.caption_alt_text(
        "Figure 3. Source: \u201cA Social Model of Writing.\u201d Writing@CSU.")
    assert only.startswith("Source:")


def test_a_caption_set_in_italic_is_still_a_caption():
    """Volume 2 sets one caption in italic, so it arrives wrapped in
    emphasis and a pattern anchored at the start never sees the label. The
    photograph then had nothing to anchor to and printed after the Works
    Cited."""
    assert pdf_ingest.is_figure_caption(
        "*Fig. 1. Nicaraguan woman on a side street in Granada.*")
    assert pdf_ingest.caption_alt_text(
        "*Fig. 1. Nicaraguan woman on a side street in Granada.*"
    ) == "Nicaraguan woman on a side street in Granada"


def test_unemphasize_only_takes_wrapping_that_covers_the_whole_line():
    """Emphasis inside a caption is the caption's own, and stays."""
    assert pdf_ingest.unemphasize("*whole line*") == "whole line"
    assert pdf_ingest.unemphasize("Figure 1. The *Monopoly* article") == \
        "Figure 1. The *Monopoly* article"
    assert pdf_ingest.unemphasize("*") == "*"


def test_an_italic_table_caption_is_still_a_table_caption():
    assert pdf_ingest.is_table_caption("*Table 2. A comparison of genres*")


def test_an_italic_caption_pairs_with_its_figure():
    """The key is matched between the caption as the page prints it and the
    caption as the block holds it, and only the block has been through
    _line_text, so an italic caption arrives with an asterisk on the front.
    Recognising the caption is not enough; the key is what places the
    figure."""
    page = "Fig. 1. Nicaraguan woman on a side street in Granada."
    block = "*Fig. 1. Nicaraguan woman on a side street in Granada.*"
    assert pdf_ingest._caption_key(page) == pdf_ingest._caption_key(block)


def test_an_italic_caption_places_the_figure_before_the_back_matter():
    blocks = [("body", "Prose about the photograph."),
              ("body", "*Fig. 1. Nicaraguan woman on a side street.*"),
              ("head", "Works Cited"),
              ("body", "Savini, Catherine. Nicaraguan Woman. 2007.")]
    figures = [{"page": 10, "index": 0, "name": "figure-p010-1.jpg"}]
    caption_pages = {(10, 0): "Fig. 1. Nicaraguan woman on a side street."}
    out, _ = pdf_ingest.place_figures(blocks, figures, caption_pages)
    kinds = [kind for kind, _ in out]
    assert kinds.index("figure") < kinds.index("head")


def test_a_banner_wide_figure_clears_the_size_floor():
    """Volume 6's Document Localization Process is 315 by 34, a five-stage
    flowchart set to the full text measure. Testing its shorter side
    against the longer side's floor threw it away."""
    assert pdf_ingest.big_enough(315, 34)
    assert pdf_ingest.big_enough(297, 27)


def test_a_rule_does_not():
    """A hairline across the measure is not a figure."""
    assert not pdf_ingest.big_enough(315, 2)
    assert not pdf_ingest.big_enough(400, 12)


def test_a_bullet_or_icon_does_not():
    assert not pdf_ingest.big_enough(30, 30)
    assert not pdf_ingest.big_enough(79, 40)


def test_a_tall_narrow_figure_clears_it_too():
    """The test is on each side separately, so the rule is symmetric."""
    assert pdf_ingest.big_enough(34, 315)


def test_a_cmyk_image_is_converted_before_it_is_written():
    """PNG has no CMYK, so saving one raises inside PIL and the extraction's
    except drops the figure without a word. Volume 6's Document Localization
    Process went that way."""
    from PIL import Image
    cmyk = Image.new("CMYK", (40, 10))
    assert pdf_ingest.for_png(cmyk).mode == "RGB"


def test_transparency_survives_the_conversion():
    from PIL import Image
    assert pdf_ingest.for_png(Image.new("LAB", (8, 8))).mode == "RGB"
    assert pdf_ingest.for_png(Image.new("RGBA", (8, 8))).mode == "RGBA"


def test_a_mode_png_can_hold_is_left_alone():
    from PIL import Image
    rgb = Image.new("RGB", (8, 8))
    assert pdf_ingest.for_png(rgb) is rgb
    grey = Image.new("L", (8, 8))
    assert pdf_ingest.for_png(grey) is grey


def test_lab_is_not_mistaken_for_having_an_alpha_channel():
    """"A" is in "LAB", which is not a reason to give it transparency."""
    from PIL import Image
    assert pdf_ingest.for_png(Image.new("LAB", (8, 8))).mode == "RGB"
    assert pdf_ingest.for_png(Image.new("CMYK", (8, 8))).mode == "RGB"
    assert pdf_ingest.for_png(Image.new("RGBa", (8, 8))).mode == "RGBA"


# ---------- the offprint cover page ----------


COVER_LINES = [
    _line("What Is “Academic” Writing?", page=1),
    _line("by L. Lennie Irvin", page=1),
    _line("This essay is a chapter in Writing Spaces: Readings on Writing,", page=1),
    _line("Volume 1, a peer-reviewed open textbook series for the writing", page=1),
    _line("classroom, and is published through Parlor Press.", page=1),
    _line("The full volume and individual chapter downloads are available for", page=1),
    _line("free from the following sites:", page=1),
    _line("Library of Congress Cataloging-in-Publication Data", page=1),
    _line("Writing spaces : readings on writing. Volume 1 / edited by Charles Lowe", page=1),
    _line("p. cm.", page=1),
    _line("Includes bibliographical references and index.", page=1),
]

CHAPTER_LINES = [
    _line("What Is “Academic” Writing?", page=2),
    _line("L. Lennie Irvin", page=2),
    _line("Introduction: The Academic Writing Task", page=2),
    _line("As a new college student, you may have a lot of anxiety and questions", page=2),
    _line("about the writing you’ll do in college.", page=2),
]


def test_cover_page_is_recognised():
    assert pdf_ingest.is_cover_page(COVER_LINES)


def test_chapter_opening_is_not_a_cover_page():
    assert not pdf_ingest.is_cover_page(CHAPTER_LINES)


def test_one_marker_group_is_not_enough():
    """A chapter may well discuss a Creative Commons licence, and one that
    does must not lose its first page for saying so."""
    discussing = [
        _line("Everything here is licensed under a Creative Commons licence,", page=2),
        _line("which is what lets you quote it in your own essay without asking.", page=2),
    ]
    assert not pdf_ingest.is_cover_page(discussing)


def test_count_cover_pages_finds_the_leading_cover_only():
    assert pdf_ingest.count_cover_pages(COVER_LINES + CHAPTER_LINES) == 1


def test_count_cover_pages_is_zero_where_there_is_none():
    assert pdf_ingest.count_cover_pages(CHAPTER_LINES) == 0


def test_a_late_page_of_boilerplate_is_not_a_cover():
    """A cover page that is not at the front is not a cover page."""
    late = [_line(l.text, page=9) for l in COVER_LINES]
    assert pdf_ingest.count_cover_pages(CHAPTER_LINES + late) == 0


# ---------- a footnote marked with a symbol rather than a number ----------


def test_licence_footnote_does_not_become_a_bullet():
    """The series marks the licence note with an asterisk, so it falls past
    the numbered-note pattern and was written out as it was read. Markdown
    then read the asterisk as a list marker and 69 of the series' chapters
    printed their licence as a bulleted item."""
    text = "* This work is licensed under the Creative Commons Attribution"
    assert pdf_ingest.escape_list_marker(text).startswith("\\*")


def test_escape_list_marker_leaves_ordinary_prose_alone():
    text = "As a new college student, you may have a lot of anxiety."
    assert pdf_ingest.escape_list_marker(text) == text


def test_escape_list_marker_is_idempotent():
    text = "* This work is licensed under the Creative Commons Attribution"
    once = pdf_ingest.escape_list_marker(text)
    assert pdf_ingest.escape_list_marker(once) == once


# ---------- a table's caption stays with its table ----------


def test_table_caption_is_not_collected_with_the_footnotes():
    """`place_tables` had put the tables in the right places and this moved
    every caption off them: volume 6's fifth chapter printed "Table 5.1",
    "Table 5.2" and "Table 5.4" in a row at the end of the chapter, each one
    pages away from the table it names."""
    blocks = [
        ("body", "The spreadsheet below collects what each source contributes."),
        ("note", "Table 5.1. Source Spreadsheet for Literature Reviews"),
        ("table", "| Source | Claim |\n| --- | --- |\n| Smith | Yes |"),
        ("note", "1. A numbered footnote still goes to the end."),
    ]
    out = pdf_ingest.blocks_to_markdown(blocks)
    caption = out.index("Table 5.1. Source Spreadsheet")
    table = out.index("| Source | Claim |")
    footnote = out.index("[^1]:")
    assert caption < table, "the caption is set above its table"
    assert table < footnote, "the numbered footnote still collects at the end"


def test_an_uncaptioned_table_goes_back_where_its_page_printed_it():
    """Volume 1's second chapter introduces its table with a colon on page 6
    and the series gave it no caption, so there was nothing to pair it with
    and it printed after the Works Cited eight pages later."""
    blocks = [
        ("body", "Let's break down the writing situation in college:"),
        ("head", "The Format of the Academic Essay"),
        ("body", "An essay has a beginning, a middle and an end."),
        ("head", "Works Cited"),
        ("body", "Carroll, Lee Ann. *Rehearsing New Roles*. 2002."),
    ]
    tables = [{"page": 6, "index": 0,
               "rows": [["Who's your audience?", "The professor."],
                        ["What's your purpose?", "To show your learning."]]}]
    anchors = {(6, 0): "Let's break down the writing situation in college:"}
    out, notes = pdf_ingest.place_tables(blocks, tables, anchors)
    kinds = [kind for kind, _ in out]
    assert kinds.index("table") == 1, "the table follows the line that introduces it"
    assert any("put back against the line" in note for note in notes)


def test_an_uncaptioned_table_with_no_usable_anchor_still_falls_to_the_end():
    blocks = [("body", "Prose that does not contain the anchor.")]
    tables = [{"page": 3, "index": 0, "rows": [["a", "b"], ["c", "d"]]}]
    out, notes = pdf_ingest.place_tables(blocks, tables, {(3, 0): ""})
    assert any(kind == "table" for kind, _ in out)
    assert any("matched no caption" in note for note in notes)


def test_a_captioned_table_still_goes_to_its_caption():
    """The anchor is a fallback and must not pre-empt a caption."""
    blocks = [("body", "Prose."),
              ("note", "Table 1 A comparison between posters"),
              ("body", "More prose.")]
    tables = [{"page": 5, "index": 0, "rows": [["a", "b"], ["c", "d"]]}]
    anchors = {(5, 0): "More prose."}
    out, _ = pdf_ingest.place_tables(blocks, tables, anchors)
    kinds = [kind for kind, _ in out]
    assert kinds == ["body", "note", "table", "body"]
