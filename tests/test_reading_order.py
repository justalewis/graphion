"""Checking a reconstruction's order against the one the file states.

`pdf_ingest` infers reading order from where ink sits, and nothing has ever
checked the result. The defects that follows are the worst kind this
codebase produces, because they are present and wrong rather than missing:
two texts merged character by character inside a clipped figure, a
two-column table shredded into prose as "detailing as being the most
import- lab procedures ant while", seven figures closing a document after
the Works Cited, a marginal pull quote interleaved with a heading. Every
one was found by a person reading a galley. None fails a conformance check,
because the words are all present.

A tagged PDF states the order, which is the only thing a reconstruction can
be checked against: any other reading of what order a page should come out
in is the same inference that produced the reconstruction, so it would
agree with itself and prove nothing.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import structure


def _outline(*elements, chars=(100, 99)):
    """An outline holding the given elements, with enough coverage to be read."""
    out = structure.Outline(path=Path("x.pdf"))
    out.chars, out.marked_chars = chars
    out.styles = {"/P": len(elements)}
    out.elements = list(elements)
    return out


def _element(role, *keys):
    return structure.Element(role=role, style="P", page=0, mcids=list(keys))


def _items(*rows):
    """`(mcids, text)` in the order a reconstruction puts them."""
    return [(list(keys), text) for text, *keys in rows]


# ---------- the order the file states ----------

def test_reading_order_numbers_the_ids_in_document_order():
    outline = _outline(
        _element("/P", (0, 5), (0, 6)),
        _element("/P", (0, 7)),
        _element("/P", (1, 1)),
    )

    assert structure.reading_order(outline) == {
        (0, 5): 0, (0, 6): 1, (0, 7): 2, (1, 1): 3}


def test_a_tree_that_does_not_reach_the_text_states_no_order():
    """The rule `heading_map` follows: a caller gets the file's answer or
    none of it, never a reading of the cover page applied to a chapter."""
    outline = _outline(_element("/P", (0, 1)), chars=(100, 2))

    assert not outline.usable
    assert structure.reading_order(outline) == {}


def test_an_id_claimed_twice_keeps_its_first_place():
    outline = _outline(
        _element("/P", (0, 1)),
        _element("/P", (0, 2)),
        _element("/Span", (0, 1)),
    )

    assert structure.reading_order(outline) == {(0, 1): 0, (0, 2): 1}


def test_a_claim_with_no_page_or_no_id_is_left_out():
    outline = _outline(_element("/P", (0, 1), (None, 2), (0, None)))

    assert structure.reading_order(outline) == {(0, 1): 0}


# ---------- where a reconstruction runs backwards ----------

ORDER = {(0, n): n for n in range(10)}


def test_text_in_the_file_s_order_has_no_descents():
    check = structure.order_descents(ORDER, _items(
        ("First.", (0, 0)), ("Second.", (0, 1)), ("Third.", (0, 2))))

    assert check.descents == []
    assert (check.placed, check.unplaced) == (3, 0)


def test_a_line_out_of_order_is_one_descent_carrying_its_words():
    check = structure.order_descents(ORDER, _items(
        ("First.", (0, 0)), ("Fourth.", (0, 3)), ("Second.", (0, 1))))

    assert len(check.descents) == 1
    d = check.descents[0]
    assert d.gap == 2
    assert d.before == "Fourth."
    assert d.after == "Second."


def test_a_marginal_note_interleaved_with_a_heading_reads_as_descents():
    """`annoying-ways-people-use-sources` sets a pull quote down the side of
    the page, and its lines interleave in reading order with the two lines
    of a wrapping head. That is the shape this exists to find."""
    check = structure.order_descents(ORDER, _items(
        ("Uncle Barry and his", (0, 6)),
        ("Uncle Barry and His Encyclopedia of Use-", (0, 1)),
        ("Encyclopedia of Useless", (0, 7)),
        ("less Information", (0, 2)),
        ("Information: using too", (0, 8)),
    ))

    assert len(check.descents) == 2
    assert [d.gap for d in check.descents] == [5, 5]


def test_a_line_with_no_marked_id_is_unplaced_not_misordered():
    """A line the tree says nothing about cannot be out of order, and
    counting it as in order would be a reading nobody made."""
    check = structure.order_descents(ORDER, _items(
        ("First.", (0, 0)), ("No id.",), ("Second.", (0, 1))))

    assert check.descents == []
    assert (check.placed, check.unplaced) == (2, 1)


def test_the_share_placed_is_the_evidence_behind_the_count():
    check = structure.order_descents(ORDER, _items(
        ("First.", (0, 0)), ("No id.",), ("No id either.",)))

    assert check.placed == 1
    assert check.unplaced == 2
    assert round(check.share_placed) == 33


def test_nothing_read_leaves_the_share_unknown_rather_than_zero():
    check = structure.order_descents(ORDER, [])

    assert check.share_placed is None
    assert check.read == 0


def test_a_line_takes_the_earliest_id_it_sits_in():
    """A line that has been joined to another spans several ids, and where
    it starts is where it belongs."""
    check = structure.order_descents(ORDER, _items(
        ("Joined.", (0, 4), (0, 2)), ("Next.", (0, 5))))

    assert check.descents == []


def test_the_worst_descent_tells_a_swap_from_a_stranded_block():
    check = structure.order_descents({(0, n): n for n in range(400)}, _items(
        ("A.", (0, 1)), ("B.", (0, 0)), ("C.", (0, 300)), ("D.", (0, 10))))

    assert [d.gap for d in check.descents] == [1, 290]
    assert check.worst == 290


# ---------- the join, on the ingest side ----------

import pdf_ingest  # noqa: E402


def _line(text, page=1, mcids=()):
    return pdf_ingest.Line(
        text=text, size=10.0, x0=72.0, x1=272.0, top=100.0, page=page,
        italic=False, mcids=set(mcids))


def _usable(*elements):
    out = structure.Outline(path=Path("x.pdf"))
    out.chars, out.marked_chars = 100, 99
    out.styles = {"/P": len(elements)}
    out.elements = list(elements)
    return out


def test_the_page_numbers_line_up_on_this_side_too():
    """`line.page` counts from one, as every page number in `pdf_ingest`
    does, and a structure tree indexes its pages from zero. Getting this
    wrong places no line at all, which reads exactly like a file with no
    tree."""
    outline = _usable(_element("/P", (2, 9), (2, 10)))
    lines = [_line("On page three", page=3, mcids=[9]),
             _line("Still there", page=3, mcids=[10])]

    check = pdf_ingest.measure_reading_order(outline, lines)

    assert (check.placed, check.unplaced) == (2, 0)
    assert check.descents == []


def test_lines_out_of_the_file_s_order_are_found_through_the_join():
    outline = _usable(_element("/P", (0, 1), (0, 2), (0, 3)))
    lines = [_line("First", mcids=[1]),
             _line("Third", mcids=[3]),
             _line("Second", mcids=[2])]

    check = pdf_ingest.measure_reading_order(outline, lines)

    assert len(check.descents) == 1
    assert check.descents[0].before == "Third"
    assert check.descents[0].after == "Second"


def test_no_outline_reads_nothing_rather_than_reading_zero():
    lines = [_line("Prose", mcids=[1])]

    check = pdf_ingest.measure_reading_order(None, lines)

    assert check.read == 0
    assert check.share_placed is None


def test_a_tree_that_states_no_order_reads_nothing():
    """A cover-page tree gives `reading_order` nothing, and a caller must
    not take that as a chapter in perfect order."""
    thin = structure.Outline(path=Path("x.pdf"))
    thin.chars, thin.marked_chars = 100, 2
    thin.styles = {"/P": 1}
    thin.elements = [_element("/P", (0, 1))]

    check = pdf_ingest.measure_reading_order(thin, [_line("Prose", mcids=[1])])

    assert check.read == 0


# ---------- what the comparison withholds, and why ----------

def test_a_caption_is_not_placed_in_the_body_flow():
    """A tree keeps an anchored object's content in its own branch, so a
    caption's place in the file is nowhere near the prose printed around
    it. Measured over the archive, `introduction-to-primary-research`
    reported three descents and every one was a caption, the worst jumping
    back 734 marked ids after "Fig. 2: A sample timeline for Jared's
    research project." Nothing was wrong with that chapter.
    """
    body = _element("/P", (0, 1), (0, 2))
    caption = structure.Element(role="/P", style="/Caption", page=0,
                                mcids=[(0, 900)], in_flow=False)
    outline = _usable(body, caption)

    order = structure.reading_order(outline)

    assert (0, 900) not in order
    assert order == {(0, 1): 0, (0, 2): 1}


def test_the_exclusion_is_inherited_down_the_subtree():
    """A `/P` inside a `/Note` is still a note, and the text usually sits
    in a `/Span` below that again. Testing the element alone left all ten
    of `7-welhausen`'s footnote descents standing, because the marked ids
    belong to the spans rather than to the `/Note`.
    """
    tree = {"/S": "/Document", "/K": [
        {"/S": "/P", "/K": 1},
        {"/S": "/Note", "/K": [
            {"/S": "/P", "/K": [{"/S": "/Span", "/K": 900}]}]},
        {"/S": "/P", "/K": 2},
    ]}

    elements, _styles = structure.walk(tree, {}, {}, {})
    by_style = {e.style: e for e in elements}

    assert by_style["/Note"].in_flow is False
    # The span three levels down carries the text and must inherit it.
    span = next(e for e in elements if e.style == "/Span")
    assert span.in_flow is False
    assert all(e.in_flow for e in elements if e.style == "/Document")


def test_a_caption_style_under_a_flattened_role_is_caught():
    """`why-blog-searching-for-writing-on-the-web` holds its caption as
    role `/P` with style `/Caption`, which is the same RoleMap flattening
    that hides the heading levels, so the style has to be read too."""
    tree = {"/S": "/Caption", "/K": 900}

    elements, _styles = structure.walk(tree, {}, {"/Caption": "/P"}, {})

    assert elements[0].role == "/P"
    assert elements[0].style == "/Caption"
    assert elements[0].in_flow is False


def test_a_marginal_gloss_in_body_copy_is_still_compared():
    """The pull quote in `annoying-ways-people-use-sources` is italic
    fragments set in `/Body_Copy_Flush_Left`, which the tree calls ordinary
    body. Withholding captions and notes must leave all sixteen of its
    descents standing, or the measure has silenced the one defect it was
    built to find."""
    tree = {"/S": "/Document", "/K": [
        {"/S": "/Body_Copy_Flush_Left", "/K": 500},
        {"/S": "/Body_Copy", "/K": 1},
    ]}

    elements, _styles = structure.walk(tree, {}, {}, {})

    assert all(e.in_flow for e in elements)


def test_carries_body_flow_is_the_one_reader_of_that_flag():
    """`walk` works the answer out as it goes, because it is inherited and
    an element on its own cannot give it."""
    inside = structure.Element(role="/P", style="/P", in_flow=False)
    outside = structure.Element(role="/P", style="/P", in_flow=True)

    assert not structure.carries_body_flow(inside)
    assert structure.carries_body_flow(outside)


# ---------- two columns read across each other ----------

def _char(mcid, text="x"):
    return {"text": text, "mcid": mcid, "size": 11.0, "x0": 0.0, "x1": 1.0,
            "top": 0.0}


def test_a_line_read_across_two_columns_is_split_where_the_file_jumps():
    """Page 12 of volume 5's `8-diab` sets a student's draft beside a
    reviewer's commentary with no rule between them, so pdfplumber reads
    one line across both and publishes "purpose) into three separate
    paragraphs in the US who might un- which helps the reader locate each
    easily". The two halves sit 350 places apart in the file's own order.
    """
    order = {(0, 1): 10, (0, 2): 11, (0, 9): 360}
    chars = [_char(1), _char(2), _char(9)]

    runs = pdf_ingest.column_runs(chars, order, 0)

    assert [[c["mcid"] for c in run] for run in runs] == [[1, 2], [9]]


def test_an_inline_element_is_not_a_column():
    """A link or a run of italic is its own element and lands beside its
    neighbours. Over this chapter the jumps inside a line are 3 to 23 for
    those and 319 to 350 for the columns, so the threshold sits at 100 in
    between."""
    order = {(0, 1): 10, (0, 5): 31, (0, 2): 12}
    chars = [_char(1), _char(5), _char(2)]

    runs = pdf_ingest.column_runs(chars, order, 0)

    assert len(runs) == 1


def test_the_threshold_is_where_this_chapter_measured_it():
    assert pdf_ingest.COLUMN_ORDER_JUMP > 23
    assert pdf_ingest.COLUMN_ORDER_JUMP < 319


def test_no_stated_order_leaves_the_line_whole():
    chars = [_char(1), _char(9)]

    assert pdf_ingest.column_runs(chars, {}, 0) == [chars]


def test_a_character_the_tree_says_nothing_about_stays_where_it_was():
    """An unknown position neither splits nor joins: it carries the last
    stated one forward, so the character stays in the run it was printed
    in rather than starting one of its own."""
    order = {(0, 1): 10, (0, 2): 11}
    chars = [_char(1), _char(None), _char(2)]

    runs = pdf_ingest.column_runs(chars, order, 0)

    assert len(runs) == 1
    assert len(runs[0]) == 3


# ---------- and why the lines are not reordered to match ----------

def test_the_lines_are_left_in_the_order_the_page_printed_them():
    """Sorting a page's lines into the tree's order was built and then
    taken out, because the two orders differ for reasons that are not
    errors. `how-to-read-like-a-writer` prints "I came to realize that all
    writing consists of a series of choices" as a display line, and its
    tree places it elsewhere, so sorting moved the continuation of
    "re-read entire para-" away from the word it finishes and put the
    display line there instead. Twenty-odd chapters changed that way, with
    no word lost and a paragraph relocated in each, which is the failure
    this module calls present and wrong.

    Splitting a merged line is safe because it only decides where a line
    ends. Moving a line decides where the text goes, and the file's order
    is not authority enough for that.
    """
    assert not hasattr(pdf_ingest, "_in_stated_order")


# ---------- where the file says its figures and tables sit ----------

def test_a_figure_is_stated_after_the_body_it_follows():
    """`pdf_ingest` places a figure beside its caption, or at the hole its
    page left, or after the figure before it, and nothing has ever checked
    the result: a figure in the wrong paragraph renders identically."""
    outline = _usable(
        _element("/P", (0, 1), (0, 2)),
        structure.Element(role="/Figure", style="/Figure", page=0,
                          mcids=[(0, 50)], in_flow=False),
        _element("/P", (0, 3)),
        structure.Element(role="/Figure", style="/Figure", page=0,
                          mcids=[(0, 51)], in_flow=False),
    )

    placements = structure.stated_placements(outline)

    assert [(p.role, p.index, p.after) for p in placements] == [
        ("/Figure", 1, 1), ("/Figure", 2, 2)]


def test_a_figure_opening_the_document_follows_nothing():
    outline = _usable(
        structure.Element(role="/Figure", style="/Figure", page=0,
                          mcids=[(0, 50)], in_flow=False),
        _element("/P", (0, 1)),
    )

    assert structure.stated_placements(outline)[0].after is None


def test_a_table_is_counted_apart_from_the_figures():
    outline = _usable(
        _element("/P", (0, 1)),
        structure.Element(role="/Table", style="/Table", page=0,
                          mcids=[(0, 50)], in_flow=False),
        structure.Element(role="/Figure", style="/Figure", page=0,
                          mcids=[(0, 51)], in_flow=False),
    )

    placements = structure.stated_placements(outline)

    assert [(p.role, p.index) for p in placements] == [
        ("/Table", 1), ("/Figure", 1)]


def test_a_caption_is_not_a_placement():
    """It travels with its figure and is placed by the same decision, so
    counting it would report one misplacement twice."""
    outline = _usable(
        _element("/P", (0, 1)),
        structure.Element(role="/P", style="/Caption", page=0,
                          mcids=[(0, 50)], in_flow=False),
    )

    assert structure.stated_placements(outline) == []


def test_a_tree_that_states_no_order_states_no_placement():
    thin = structure.Outline(path=Path("x.pdf"))
    thin.chars, thin.marked_chars = 100, 2
    thin.styles = {"/P": 1}
    thin.elements = [_element("/P", (0, 1))]

    assert structure.stated_placements(thin) == []


# ---------- and when that statement is an export artefact ----------

def test_a_run_of_figures_sharing_one_place_is_not_a_placement():
    """A tagger that serialises anchored objects together gives a run of
    figures one position between them. `the-complexity-of-simplicity`
    states all seven collages after a Works Cited entry at 97% of the
    text, which is the defect `figure_anchors_from_holes` was written to
    repair, and the galley now spreads them through the prose where the
    chapter's own words put them. 7 of this archive's 41 multi-figure
    chapters do this.
    """
    body = _element("/P", *[(0, n) for n in range(1, 21)])
    together = [structure.Element(role="/Figure", style="/Figure", page=0,
                                  mcids=[(0, 50 + i)], in_flow=False)
                for i in range(4)]
    outline = _usable(body, *together)

    assert structure.collects_figures_at_one_place(outline)


def test_being_late_is_not_the_test():
    """`15-bennett` states six of its seven figures at 75% of the text
    while the galley puts them at 6 to 11%, so the artefact is a run with
    one position between them and not a position near the end. The first
    version of this gate tested for lateness and let that chapter through.
    """
    early = [structure.Element(role="/Figure", style="/Figure", page=0,
                               mcids=[(0, 50 + i)], in_flow=False)
             for i in range(4)]
    outline = _usable(*early, _element("/P", *[(0, n) for n in range(1, 21)]))

    assert structure.collects_figures_at_one_place(outline)


def test_figures_each_in_their_own_place_are_a_placement():
    outline = _usable(
        _element("/P", *[(0, n) for n in range(1, 11)]),
        structure.Element(role="/Figure", style="/Figure", page=0,
                          mcids=[(0, 50)], in_flow=False),
        _element("/P", *[(0, n) for n in range(11, 21)]),
        structure.Element(role="/Figure", style="/Figure", page=0,
                          mcids=[(0, 51)], in_flow=False),
    )

    assert not structure.collects_figures_at_one_place(outline)


def test_two_figures_side_by_side_are_left_alone():
    """A page can print a pair together, so two sharing a place is
    ordinary. The threshold sits above that and below the runs of six."""
    outline = _usable(
        _element("/P", *[(0, n) for n in range(1, 11)]),
        structure.Element(role="/Figure", style="/Figure", page=0,
                          mcids=[(0, 50)], in_flow=False),
        structure.Element(role="/Figure", style="/Figure", page=0,
                          mcids=[(0, 51)], in_flow=False),
        _element("/P", *[(0, n) for n in range(11, 21)]),
        structure.Element(role="/Figure", style="/Figure", page=0,
                          mcids=[(0, 52)], in_flow=False),
        _element("/P", *[(0, n) for n in range(21, 31)]),
        structure.Element(role="/Figure", style="/Figure", page=0,
                          mcids=[(0, 53)], in_flow=False),
    )

    assert not structure.collects_figures_at_one_place(outline)


def test_a_single_figure_is_not_called_an_artefact():
    outline = _usable(
        _element("/P", (0, 1), (0, 2)),
        structure.Element(role="/Figure", style="/Figure", page=0,
                          mcids=[(0, 50)], in_flow=False),
    )

    assert not structure.collects_figures_at_one_place(outline)
