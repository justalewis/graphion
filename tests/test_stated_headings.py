"""Taking the headings from the file instead of guessing them from the type.

`classify` reads a head off its size and its centring, which finds the ones
a page sets large and misses the ones it does not. Measured against the
structure trees of this archive's own originals, that loses 262 of 784
stated headings, and H5, which is body size in italic, 90 times out of 92.
So where a tree reaches the text the level it states wins.

Three things have to hold for that to be an improvement rather than a
second way to be wrong. The join has to be on the marked content id and
not on how the line looks, or it is the same guess again. A file with no
usable tree has to come out exactly as it did, since that is most of what
this module will ever be pointed at. And the levels are the book's, where
the chapter title is the top and the galley prints that from the front
matter, so what reaches the body has to start where the body starts.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pdf_ingest


def _line(text, page=1, size=10.0, x0=72.0, top=100.0, mcids=(), italic=False):
    return pdf_ingest.Line(
        text=text, size=size, x0=x0, x1=x0 + 200, top=top, page=page,
        italic=italic, mcids=set(mcids))


LAYOUT = pdf_ingest.Layout(
    body_size=10.0, body_left=72.0, body_right=472.0, body_top=100.0,
    body_bottom=700.0, page_centre=306.0, line_pitch=12.0,
)


# ---------- the join ----------

def test_a_line_takes_the_level_of_the_id_it_sits_inside():
    lines = [_line("A Section Head", mcids=[4]), _line("Prose.", mcids=[5])]

    marked = pdf_ingest.apply_stated_headings(lines, {(0, 4): 2})

    assert marked == 1
    assert lines[0].heading_level == 2
    assert lines[1].heading_level is None


def test_the_page_numbers_line_up():
    """`line.page` counts from one, as every page number in this module
    does, and a structure tree indexes its pages from zero."""
    lines = [_line("On page three", page=3, mcids=[9])]

    assert pdf_ingest.apply_stated_headings(lines, {(2, 9): 1}) == 1
    assert lines[0].heading_level == 1


def test_a_line_claiming_two_levels_takes_the_shallower():
    """That is a head something was joined to, and the shallower is the one
    the outline hangs from."""
    lines = [_line("A head and its subhead", mcids=[1, 2])]

    pdf_ingest.apply_stated_headings(lines, {(0, 1): 3, (0, 2): 2})

    assert lines[0].heading_level == 2


def test_nothing_is_marked_where_the_tree_says_nothing():
    lines = [_line("Prose.", mcids=[7])]

    assert pdf_ingest.apply_stated_headings(lines, {}) == 0
    assert lines[0].heading_level is None


# ---------- a sentence is not a heading, whatever the file says ----------

def test_a_stated_head_that_is_a_sentence_is_left_to_the_type():
    """Volume 2's `walk-talk-cook-eat` is written as a dialogue and sets its
    stage directions in `Header_C`, the style the series uses for a third
    level section head, so the file states that "Marvin types it in." is an
    H3 while the chapter's own heads are H1s in the same series. Reading the
    tree faithfully published twelve stage directions as headings, which is
    what somebody navigating by heading would hear.
    """
    line = _line("*Marvin types it in.*")
    line.heading_level = 3
    report = {}

    blocks = pdf_ingest.assemble([line], LAYOUT, set(), set(), report=report)

    # Body, with its emphasis intact: the italic is the direction's own and
    # a reader is meant to hear it.
    assert blocks == [("body", "*Marvin types it in.*")]
    assert report["declined_heads"] == ["Marvin types it in."]


def test_a_stated_head_is_judged_on_the_whole_of_it_not_one_line():
    """Five of the twelve got through when this was asked of a physical
    line: a direction that wraps carries no full stop on its first line.
    `flush` holds the joined text, which is the only place the whole
    heading exists."""
    first = _line("Marvin thinks for a minute, while chewing and", top=100.0)
    second = _line("swallowing a mouthful of apple.", top=112.0)
    first.heading_level = second.heading_level = 3
    report = {}

    blocks = pdf_ingest.assemble([first, second], LAYOUT, set(), set(),
                                 report=report)

    assert [k for k, _ in blocks] == ["body"]
    assert len(report["declined_heads"]) == 1


def test_a_head_that_asks_a_question_is_still_a_head():
    """`writing-eyeball-to-eyeball` closes on one, so rejecting terminal
    punctuation in general would cost a real heading."""
    line = _line("What Difference Does a Mindful Collaboration Make?")
    line.heading_level = 2
    report = {}

    blocks = pdf_ingest.assemble([line], LAYOUT, set(), set(), report=report)

    assert blocks == [
        ("head2", "What Difference Does a Mindful Collaboration Make?")]
    assert report["declined_heads"] == []


def test_a_wrapped_title_keeps_its_level_and_rejoins_its_word():
    """`annoying-ways-people-use-sources` breaks "Useless" across the line,
    and `join_lines` is what puts it back, which is another reason the
    judgement belongs after the join rather than before it."""
    first = _line("Uncle Barry and His Encyclopedia of Use-", top=100.0)
    second = _line("less Information", top=112.0)
    first.heading_level = second.heading_level = 3

    blocks = pdf_ingest.assemble([first, second], LAYOUT, {"useless"}, set())

    assert blocks == [("head3", "Uncle Barry and His Encyclopedia of "
                                "Useless Information")]


def test_a_title_that_ends_in_a_full_stop_is_still_a_title():
    """`on-the-other-hand` heads five sections "Step 1:" to "Step 5:" and
    ends each with a full stop, so the stop alone would have cost six real
    headings to stop twelve false ones. The case is what separates them.
    """
    for text in ("Step 5: Imagine Hostile Audiences.",
                 "Step 4: Examine Alternatives to Your Working Thesis.",
                 "Step 2: Consider the Direct Opposite of Your Working "
                 "Thesis."):
        assert not pdf_ingest.states_a_sentence(text), text


def test_a_head_that_trails_off_is_not_a_sentence():
    """Two heads in this archive end in a spaced ellipsis, which is not a
    full stop however it is set."""
    assert not pdf_ingest.states_a_sentence(
        "But You Still Can’t Convince Everyone . . .")
    assert not pdf_ingest.states_a_sentence(
        "If at First You Fall Asleep . . .")
    assert not pdf_ingest.states_a_sentence("And So On...")


def test_states_a_sentence_reads_the_line_with_its_emphasis_off():
    """A stage direction is set in italic and arrives wrapped, which is the
    same reason the captions call `unemphasize`."""
    assert pdf_ingest.states_a_sentence("Marvin thinks for a moment.")
    assert pdf_ingest.states_a_sentence("*Marvin thinks for a moment.*")
    assert pdf_ingest.states_a_sentence("Marvin types it in.")
    assert pdf_ingest.states_a_sentence(
        "A bit confused, Marvin scratches his head.")
    assert pdf_ingest.states_a_sentence(
        "Marvin clicks back to the Wikipedia site.")
    assert pdf_ingest.states_a_sentence(
        "Marvin logs in, finds the database, and types in “bottled "
        "water AND health.”")
    assert not pdf_ingest.states_a_sentence("The Post-Mortem")
    assert not pdf_ingest.states_a_sentence("*Avoid Leading Questions*")
    assert not pdf_ingest.states_a_sentence("Works Cited")
    assert not pdf_ingest.states_a_sentence(
        "Structuring the Path Ahead: Setting Up Your Project")


def test_a_line_with_no_long_word_to_read_is_not_called_sentence_case():
    """A short head ending in a stop gives the case test nothing to go on,
    and guessing there would turn down a heading on no evidence."""
    assert pdf_ingest.reads_as_title_case("Etc.")
    assert pdf_ingest.reads_as_title_case("No. 5.")


def test_the_measured_gap_in_capitalisation():
    """The threshold is where the archive put it: the stage directions
    capitalise at most a quarter of their long words, the real heads all of
    them."""
    assert pdf_ingest.reads_as_title_case(
        "Step 5: Imagine Hostile Audiences.")
    assert not pdf_ingest.reads_as_title_case(
        "Way ahead of the professor, Marvin’s already started reading "
        "about the health risks and benefits of bottled water.")


# ---------- a stated level wins over the type ----------

def test_a_head_set_at_body_size_is_still_a_head():
    """`Header_B` and `Header_C` are set at body size, which is why the
    inference loses them; it is the whole reason for reading the file."""
    line = _line("Writing Good Questions", size=10.0)
    line.heading_level = 3

    assert pdf_ingest.classify(line, LAYOUT) == "head"


def test_nothing_stated_leaves_the_geometry_in_charge():
    assert pdf_ingest.classify(_line("Prose.", size=10.0), LAYOUT) == "body"
    assert pdf_ingest.classify(
        _line("A Big Centred Head", size=14.0, x0=206.0), LAYOUT) == "head"


# ---------- the levels reach the Markdown ----------

def test_a_stated_level_is_written_as_that_many_hashes():
    blocks = [("head", "Top"), ("head2", "Under it"), ("head3", "Deeper"),
              ("body", "Prose.")]

    md = pdf_ingest.blocks_to_markdown(blocks)

    assert "# Top" in md
    assert "## Under it" in md
    assert "### Deeper" in md


def test_the_body_starts_at_one_however_the_book_numbered_it():
    """Volume 6 calls its section heads H2 under an H1 chapter title, and
    the galley prints that title from the front matter. Left alone, every
    section head would render a level below the title with nothing in
    between."""
    md = pdf_ingest.blocks_to_markdown(
        [("head2", "A Section"), ("head3", "Under it")])

    assert "# A Section" in md
    assert "## Under it" in md


def test_a_file_that_states_nothing_comes_out_as_it_always_did():
    md = pdf_ingest.blocks_to_markdown(
        [("head", "A Head"), ("title", "An Off-Centre Head")])

    assert "# A Head" in md
    assert "# An Off-Centre Head" in md


def test_head_level_reads_the_kinds_and_nothing_else():
    assert pdf_ingest.head_level("head") == 1
    assert pdf_ingest.head_level("title") == 1
    assert pdf_ingest.head_level("head4") == 4
    assert pdf_ingest.head_level("body") is None
    assert pdf_ingest.head_level("header") is None
    assert pdf_ingest.head_level("") is None


# ---------- assembling them ----------

def _assembled(lines):
    return pdf_ingest.assemble(lines, LAYOUT, set(), set())


def test_two_heads_at_different_levels_do_not_merge():
    """Two heads in a row merge into one block, which is older than any of
    this and loses a chapter a heading. Where the file states the levels
    they are separable."""
    first = _line("A Section", top=100.0)
    first.heading_level = 1
    second = _line("Under It", top=112.0)
    second.heading_level = 2

    blocks = _assembled([first, second])

    assert blocks == [("head", "A Section"), ("head2", "Under It")]


def test_two_heads_at_the_same_level_merge_as_they_always_did():
    first = _line("A Section", size=14.0, x0=206.0, top=100.0)
    second = _line("Continued", size=14.0, x0=206.0, top=112.0)

    blocks = _assembled([first, second])

    assert len(blocks) == 1
    assert blocks[0][0] == "head"


def test_emphasis_wrapping_a_stated_head_comes_off():
    """Volume 6 names its fourth level `Header_D_Italics`, so the whole
    line arrives wrapped. Inside a head that is how the page sets the
    level, not something a reader is meant to hear."""
    line = _line("*Avoid Leading Questions*")
    line.heading_level = 3

    blocks = _assembled([line])

    assert blocks == [("head3", "Avoid Leading Questions")]


def test_emphasis_inside_an_inferred_head_is_left_alone():
    """With nothing stated this module behaves exactly as it did, which is
    most of what it will ever be pointed at."""
    line = _line("*A Big Centred Head*", size=14.0, x0=206.0)

    blocks = _assembled([line])

    assert blocks == [("head", "*A Big Centred Head*")]
