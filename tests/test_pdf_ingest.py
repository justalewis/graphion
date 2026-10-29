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
