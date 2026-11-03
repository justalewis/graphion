"""The description queue, and the two things it must not get wrong.

A figure keeps its description in one of two slots, and which one depends on
whether the figure has been through `pair_figure_captions`. Every bug this
codebase has had around alt text came from a reader or a writer that knew
about only one of them, so the queue reads through `lint.figure_state` and
writes through `conversion.with_description`, and what these tests hold is
that it goes on doing both.

The second thing is subtler. A description is prose typed into a web form,
and it lands in Markdown image syntax, where a newline ends the image and a
`](` ends the link. Corrupting a body that way fails no check: the words are
there, the galley renders, and what a reader gets is half a description
followed by the rest of it as a paragraph.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import conversion
import db
import describe
import lint


# One figure in each of the four states, written the way ingest writes them.
MISSING_ALT = "![](assets/figure-p001-1.png)"
PLACEHOLDER = ("![Undescribed figure from page 4 of the source]"
               "(assets/figure-p004-1.png)")
PAIRED_OWED = ('![Figure 2. The wiki for Project B.](assets/figure-p006-1.png)'
               '{#fig:2 fig-alt="Undescribed figure from page 6 of the source"}')
PAIRED_DONE = ('![Figure 3. An example Google Doc.](assets/figure-p008-1.png)'
               '{#fig:3 fig-alt="A presentation open in the editor."}')
DESCRIBED = ("![A conference poster headed Revisiting Grammar.]"
             "(assets/figure-p013-1.png)")


def _article(tmp_path, body, fm=None, slug="chapter"):
    """An article on disk and a row describing it, as the queue takes them."""
    apath = tmp_path / slug
    (apath / "assets").mkdir(parents=True)
    conversion.write_article_metadata(apath, dict(fm or {"title": "Chapter"}),
                                      body)
    return {"id": 1, "slug": slug, "title": "Chapter", "issue_id": 7,
            "issue_label": "Volume 1, number 1 (2010)",
            "project_path": str(apath)}


def _read(article):
    return conversion.read_article_metadata(Path(article["project_path"]))


# ---------- one reader ----------

@pytest.mark.parametrize("image, state", [
    (MISSING_ALT, lint.MISSING),
    (PLACEHOLDER, lint.UNDESCRIBED),
    (PAIRED_OWED, lint.UNDESCRIBED),
    (PAIRED_DONE, lint.DESCRIBED),
    (DESCRIBED, lint.DESCRIBED),
])
def test_the_queue_reads_a_figure_the_way_the_check_counts_it(
        tmp_path, image, state):
    """`check_alt_text` and the queue have to agree about every figure.

    Where they do not, the register reports a description as owed and the
    queue never shows the figure, so nobody writes it, and the only place
    that surfaces is a reader hearing nothing.
    """
    article = _article(tmp_path, f"Prose.\n\n{image}\n\nMore prose.\n")
    fm, body = _read(article)

    figures = describe.figures_in(article, fm, body)
    assert [f.state for f in figures] == [state]

    counted = lint.check_alt_text(article, fm, body).units
    owed = counted["figures-no-alt"] + counted["figures-undescribed"] \
        + counted["figures-caption-as-alt"]
    assert owed == sum(1 for f in figures if f.owed)


def test_a_caption_in_the_bracket_is_not_mistaken_for_a_description(tmp_path):
    """The figure that has cost this codebase most: the printed caption sits
    in the bracket and a placeholder sits in `fig-alt`, so a reader looking
    only at the bracket reports it described."""
    article = _article(tmp_path, f"Prose.\n\n{PAIRED_OWED}\n")
    fm, body = _read(article)

    figure = describe.figures_in(article, fm, body)[0]
    assert figure.owed
    assert figure.description == ""


# ---------- the printed caption ----------

@pytest.mark.parametrize("caption", [
    "Figure 1. The wiki for Project A.",
    "Fig. 1. Twitter is a great way to send brief messages.",
    "Fig 1.0 An unformatted resume.",
    "Fig. 2: A sample timeline.",
])
def test_every_label_this_series_prints_is_read_as_a_caption(tmp_path, caption):
    """Volume 2 prints "Fig. 1." over all seventeen of its captions and
    volume 6 prints "Fig 1.0", so a pattern matching only "Figure 1" reads
    those books as captioning nothing. 13 of this archive's 167 captions sat
    outside the long form, which left the queue with nothing to put beside
    the field."""
    article = _article(tmp_path, f"{MISSING_ALT}\\\n{caption}\n\nProse.\n")
    fm, body = _read(article)

    assert describe.figures_in(article, fm, body)[0].caption == caption


def test_prose_about_a_figure_is_not_read_as_its_caption(tmp_path):
    """What tells a caption from a reference to one is the capital that
    follows the label: a caption continues with the figure's name and prose
    continues with a verb."""
    article = _article(
        tmp_path, f"{MISSING_ALT}\\\nAs Figure 1 shows, the wiki was busy.\n")
    fm, body = _read(article)

    assert describe.figures_in(article, fm, body)[0].caption == ""


def test_a_figure_whose_page_printed_nothing_says_so(tmp_path):
    article = _article(tmp_path, f"{MISSING_ALT}\n\nOrdinary prose.\n")
    fm, body = _read(article)

    assert describe.figures_in(article, fm, body)[0].caption == ""


def test_a_paired_figure_shows_the_caption_held_in_its_bracket(tmp_path):
    """There is no caption line to find on such a figure: the pairing moved
    the description to `fig-alt` and left the bracket to Pandoc as the
    caption. Reporting that the page printed none would hide the caption in
    the one slot the editor is not writing in, and the caption is what tells
    them which figure they are looking at."""
    article = _article(tmp_path, f"Prose.\n\n{PAIRED_DONE}\n")
    fm, body = _read(article)

    figure = describe.figures_in(article, fm, body)[0]
    assert figure.caption == "Figure 3. An example Google Doc."
    assert figure.description == "A presentation open in the editor."


def test_a_bracket_holding_the_description_is_not_shown_as_a_caption(tmp_path):
    article = _article(tmp_path, f"Prose.\n\n{DESCRIBED}\n")
    fm, body = _read(article)

    assert describe.figures_in(article, fm, body)[0].caption == ""


# ---------- one writer ----------

def test_a_description_goes_to_the_attribute_where_a_caption_holds_the_bracket(
        tmp_path):
    """Writing to the bracket on such a figure overwrites the printed caption
    and leaves the stale description in place to go on winning.
    `16-vankooten` published a placeholder over a figure an editor had
    described in full, with the description standing where its caption should
    have been."""
    article = _article(tmp_path, f"Prose.\n\n{PAIRED_OWED}\n")
    apath = Path(article["project_path"])

    assert describe.write_description(
        apath, "figure-p006-1.png", "A wiki home page listing student pages.")

    fm, body = _read(article)
    assert "Figure 2. The wiki for Project B." in body
    assert 'fig-alt="A wiki home page listing student pages."' in body
    figure = describe.figures_in(article, fm, body)[0]
    assert figure.state == lint.DESCRIBED
    assert figure.description == "A wiki home page listing student pages."


def test_a_description_goes_to_the_bracket_where_nothing_else_holds_one(
        tmp_path):
    article = _article(tmp_path, f"Prose.\n\n{PLACEHOLDER}\n")
    apath = Path(article["project_path"])

    assert describe.write_description(
        apath, "figure-p004-1.png", "A whiteboard covered in sticky notes.")

    fm, body = _read(article)
    assert "![A whiteboard covered in sticky notes.]" in body
    assert "Undescribed figure" not in body
    assert describe.figures_in(article, fm, body)[0].state == lint.DESCRIBED


def test_a_description_reaches_every_place_the_figure_is_used(tmp_path):
    """`carry_alt_text` matches by asset path and writes to all of them, so
    writing to one would leave the other reported as owed for ever and the
    two would part company at the next re-ingest."""
    article = _article(
        tmp_path, f"{PLACEHOLDER}\n\nAnd again later.\n\n{PLACEHOLDER}\n")
    apath = Path(article["project_path"])

    assert describe.write_description(
        apath, "figure-p004-1.png", "A whiteboard.") == 2

    fm, body = _read(article)
    assert [f.state for f in describe.figures_in(article, fm, body)] == \
        [lint.DESCRIBED, lint.DESCRIBED]


def test_a_description_that_says_what_the_figure_already_said_writes_nothing(
        tmp_path):
    """So a save that changes nothing does not spend one of the five versions
    `.versions/` keeps."""
    article = _article(tmp_path, f"Prose.\n\n{DESCRIBED}\n")
    apath = Path(article["project_path"])
    before = (apath / "article.md").read_text(encoding="utf-8")

    assert describe.write_description(
        apath, "figure-p013-1.png",
        "A conference poster headed Revisiting Grammar.") == 0
    assert (apath / "article.md").read_text(encoding="utf-8") == before


def test_a_description_typed_over_several_lines_stays_inside_the_image(
        tmp_path):
    """A newline in the alt text closes the image and leaves the rest of the
    description standing in the body as prose, which fails no check: the
    words are there and the galley renders."""
    article = _article(tmp_path, f"Prose.\n\n{PLACEHOLDER}\n")
    apath = Path(article["project_path"])

    describe.write_description(
        apath, "figure-p004-1.png",
        "A whiteboard covered in sticky notes.\n\nStudents stand beside it.")

    fm, body = _read(article)
    figures = describe.figures_in(article, fm, body)
    assert len(figures) == 1
    assert figures[0].description == (
        "A whiteboard covered in sticky notes. Students stand beside it.")


def test_a_description_holding_a_bracket_survives_the_round_trip(tmp_path):
    """`the-complexity-of-simplicity` describes a photograph as "labelled
    [desk]", and a pattern stopping at the first `]` does not match such an
    image at all: the carry reads no description off it and writes none onto
    it, saying nothing either way."""
    article = _article(tmp_path, f"Prose.\n\n{PLACEHOLDER}\n")
    apath = Path(article["project_path"])

    describe.write_description(apath, "figure-p004-1.png",
                               "A desk drawer labelled [desk].")

    fm, body = _read(article)
    figure = describe.figures_in(article, fm, body)[0]
    assert figure.description == "A desk drawer labelled [desk]."
    assert figure.state == lint.DESCRIBED


def test_a_description_cannot_close_the_link_early(tmp_path):
    article = _article(tmp_path, f"Prose.\n\n{PLACEHOLDER}\n")
    apath = Path(article["project_path"])

    describe.write_description(apath, "figure-p004-1.png",
                               "A screen reading ](http://example.com).")

    fm, body = _read(article)
    figures = describe.figures_in(article, fm, body)
    assert len(figures) == 1
    assert figures[0].src == "assets/figure-p004-1.png"


def test_a_description_cannot_close_an_attribute_block_early(tmp_path):
    article = _article(tmp_path, f"Prose.\n\n{PAIRED_OWED}\n")
    apath = Path(article["project_path"])

    describe.write_description(apath, "figure-p006-1.png",
                               'A diagram of {a: "set"} notation.')

    fm, body = _read(article)
    figures = describe.figures_in(article, fm, body)
    assert len(figures) == 1
    assert figures[0].state == lint.DESCRIBED
    assert "Figure 2. The wiki for Project B." in body


# ---------- the order the work is done in ----------

def _queue(tmp_path, bodies):
    articles = []
    for i, (slug, body) in enumerate(bodies, 1):
        article = _article(tmp_path, body, slug=slug)
        article["id"] = i
        articles.append(article)
    return describe.build(articles)


def test_the_queue_keeps_the_order_it_was_given(tmp_path):
    """Volume order is the caller's to decide, because only it knows how this
    journal numbers its chapters."""
    queue = _queue(tmp_path, [("later", PLACEHOLDER), ("earlier", MISSING_ALT)])

    assert [f.article_slug for f in queue.items] == ["later", "earlier"]


def test_the_next_figure_owed_reads_forwards_and_does_not_wrap(tmp_path):
    """An editor who saves a description that still reads as the printed
    caption would otherwise be handed the same figure back, and one who
    started in the middle of volume 4 would be walked round to volume 1 with
    nothing saying so."""
    queue = _queue(tmp_path, [("one", PLACEHOLDER), ("two", MISSING_ALT)])
    first, second = queue.items

    assert queue.next_owed() is first
    assert queue.next_owed(first) is second
    assert queue.next_owed(second) is None


def test_a_described_figure_is_still_reachable(tmp_path):
    """Described is not the same as well described, and the 201 written by
    hand are the ones most worth going back to."""
    queue = _queue(tmp_path, [("one", DESCRIBED)])

    assert queue.next_owed() is None
    assert queue.find(1, "figure-p013-1.png") is not None


def test_an_article_with_no_article_md_is_named_rather_than_skipped(tmp_path):
    missing = tmp_path / "gone"
    missing.mkdir()
    queue = describe.build([{"id": 1, "slug": "gone", "title": "Gone",
                             "project_path": str(missing)}])

    assert queue.unreadable == ["gone"]
    assert "gone" in queue.note()


def test_a_figure_whose_raster_is_not_on_disk_says_so(tmp_path):
    """A description written blind would be a guess."""
    article = _article(tmp_path, f"Prose.\n\n{PLACEHOLDER}\n")
    fm, body = _read(article)

    assert describe.figures_in(article, fm, body)[0].exists is False


# ---------- the second lane ----------

def test_a_chapter_with_no_answer_on_record_is_not_counted_as_having_none(
        tmp_path):
    article = _article(tmp_path, f"Prose.\n\n{DESCRIBED}\n")
    fm, _ = _read(article)

    assert describe.judged(fm) is False


def test_an_empty_answer_is_recorded_and_reads_back_as_an_answer(tmp_path):
    """Saving a chapter and ticking nothing is a finding. Leaving the field
    out would put the chapter back among the ones nobody has opened, and the
    lane would offer it again for ever."""
    article = _article(tmp_path, f"Prose.\n\n{DESCRIBED}\n")
    apath = Path(article["project_path"])

    assert describe.record_images_of_text(apath, []) == []

    fm, _ = _read(article)
    assert describe.judged(fm) is True
    assert fm["images-of-text"] == []


def test_an_answer_is_filtered_against_the_figures_the_chapter_holds(tmp_path):
    """The count feeds WCAG 1.4.5 in the conformance report, so a name
    pointing at no figure would inflate it with nothing to look at."""
    article = _article(tmp_path, f"{DESCRIBED}\n\n{MISSING_ALT}\n")
    apath = Path(article["project_path"])

    kept = describe.record_images_of_text(
        apath, ["figure-p013-1.png", "figure-p999-9.png"])

    assert kept == ["figure-p013-1.png"]
    fm, _ = _read(article)
    assert fm["images-of-text"] == ["figure-p013-1.png"]


def test_an_answer_is_written_in_document_order(tmp_path):
    article = _article(tmp_path, f"{DESCRIBED}\n\n{MISSING_ALT}\n")
    apath = Path(article["project_path"])

    kept = describe.record_images_of_text(
        apath, ["figure-p001-1.png", "figure-p013-1.png"])

    assert kept == ["figure-p013-1.png", "figure-p001-1.png"]


def test_the_lane_lists_the_chapters_with_no_answer(tmp_path):
    articles = []
    for i, (slug, fm) in enumerate(
            [("judged", {"title": "A", "images-of-text": []}),
             ("open", {"title": "B"})], 1):
        article = _article(tmp_path, f"Prose.\n\n{DESCRIBED}\n", fm=fm,
                           slug=slug)
        article["id"] = i
        articles.append(article)
    queue = describe.build(articles)

    assert [a["slug"] for a in queue.totals().unjudged] == ["open"]
    assert queue.totals().judged == 1


def test_the_lane_moves_on_from_the_chapter_just_answered(tmp_path):
    """The chapter has left the waiting list by then, so looking for it
    there finds nothing and sends the editor back to the beginning."""
    articles = []
    for i, slug in enumerate(["one", "two", "three"], 1):
        article = _article(tmp_path, f"Prose.\n\n{DESCRIBED}\n", slug=slug)
        article["id"] = i
        articles.append(article)
    describe.record_images_of_text(Path(articles[0]["project_path"]), [])
    queue = describe.build(articles)

    assert queue.next_unjudged(1)["slug"] == "two"
    assert queue.next_unjudged(2)["slug"] == "three"
    assert queue.next_unjudged(3) is None


def test_a_figure_on_the_list_is_marked_on_the_figure(tmp_path):
    article = _article(tmp_path, f"Prose.\n\n{DESCRIBED}\n",
                       fm={"title": "A",
                           "images-of-text": ["figure-p013-1.png"]})
    fm, body = _read(article)

    assert describe.figures_in(article, fm, body)[0].of_text is True


# ---------- the routes ----------

@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    import app as app_module
    application = app_module.create_app()
    application.config["LOGIN_DISABLED"] = True
    application.config["WTF_CSRF_ENABLED"] = False
    return application.test_client()


@pytest.fixture
def journal(client, tmp_path):
    """One journal, one issue, one chapter with a figure owed a description."""
    db.execute("INSERT INTO journals (slug, name, template_path) "
               "VALUES ('a-journal', 'A Journal', ?)", (str(tmp_path),))
    db.execute("INSERT INTO journals (slug, name, template_path) "
               "VALUES ('elsewhere', 'Elsewhere', ?)", (str(tmp_path),))
    issue = db.execute("INSERT INTO issues (journal_id, volume, issue_number, "
                       "year) VALUES (1, 1, 1, 2010)")
    apath = tmp_path / "alpha"
    (apath / "assets").mkdir(parents=True)
    (apath / "assets" / "figure-p004-1.png").write_bytes(b"not really a png")
    conversion.write_article_metadata(
        apath, {"title": "Alpha"},
        f"Prose.\n\n{PLACEHOLDER}\\\nFig. 1. A whiteboard.\n")
    article_id = db.execute(
        "INSERT INTO articles (journal_id, issue_id, slug, title, "
        "project_path) VALUES (1, ?, 'alpha', 'Alpha', ?)",
        (issue, str(apath)))
    return {"article_id": article_id, "path": apath, "issue_id": issue}


def _text(response):
    return response.get_data(as_text=True)


def test_the_queue_page_answers(client, journal):
    body = _text(client.get("/accessibility/a-journal/describe"))

    assert "1 owed a description" in body
    assert "Volume 1, number 1 (2010)" in body


def test_next_goes_to_the_first_figure_owed(client, journal):
    response = client.get("/accessibility/a-journal/describe/next")

    assert response.status_code == 302
    assert response.headers["Location"].endswith(
        "/describe/%d/figure-p004-1.png" % journal["article_id"])


def test_the_figure_page_shows_the_image_and_what_the_page_printed(
        client, journal):
    body = _text(client.get(
        "/accessibility/a-journal/describe/%d/figure-p004-1.png"
        % journal["article_id"]))

    assert "/assets/figure-p004-1.png" in body
    assert "Fig. 1. A whiteboard." in body
    assert describe.STATE_LABELS[lint.UNDESCRIBED] in body


def test_saving_a_description_writes_it_and_moves_on(client, journal):
    response = client.post(
        "/accessibility/a-journal/describe/%d/figure-p004-1.png"
        % journal["article_id"],
        data={"description": "A whiteboard covered in sticky notes."})

    assert response.status_code == 302
    fm, body = conversion.read_article_metadata(journal["path"])
    assert "![A whiteboard covered in sticky notes.]" in body
    # Nothing is owed now, so the queue sends the editor back to the overview
    # rather than round to the beginning.
    assert response.headers["Location"].endswith("/describe")


def test_an_empty_description_is_refused(client, journal):
    """An image with no alt text costs the galley its conformance, so the
    field cannot be used to clear one."""
    before = (journal["path"] / "article.md").read_text(encoding="utf-8")
    client.post(
        "/accessibility/a-journal/describe/%d/figure-p004-1.png"
        % journal["article_id"], data={"description": "   "})

    assert (journal["path"] / "article.md").read_text(encoding="utf-8") == before


def test_a_figure_that_is_not_in_the_journal_is_not_found(client, journal):
    assert client.get(
        "/accessibility/elsewhere/describe/%d/figure-p004-1.png"
        % journal["article_id"]).status_code == 404
    assert client.get(
        "/accessibility/a-journal/describe/%d/figure-p999-9.png"
        % journal["article_id"]).status_code == 404


def test_the_lane_records_an_answer_of_none(client, journal):
    response = client.post("/accessibility/a-journal/images-of-text/%d"
                           % journal["article_id"], data={})

    assert response.status_code == 302
    fm, _ = conversion.read_article_metadata(journal["path"])
    assert fm["images-of-text"] == []


def test_the_lane_records_which_figures_carry_text(client, journal):
    client.post("/accessibility/a-journal/images-of-text/%d"
                % journal["article_id"],
                data={"of-text": "figure-p004-1.png"})

    fm, _ = conversion.read_article_metadata(journal["path"])
    assert fm["images-of-text"] == ["figure-p004-1.png"]


def test_the_lane_page_answers(client, journal):
    body = _text(client.get("/accessibility/a-journal/images-of-text/%d"
                            % journal["article_id"]))

    assert "figure-p004-1.png" in body
    assert "1.4.5" in body


# ---------- the page this queue replaced ----------

def test_the_figures_page_can_see_a_figure_joined_to_its_caption(
        client, journal):
    """It could not, and that is why 201 descriptions were written in a text
    editor. A reconstructed figure ends its line with a hard break, which an
    end-of-line anchor turned down: 34 of the archive's 204 images matched
    and 38 of its 51 articles with figures showed an empty page."""
    body = _text(client.get("/articles/%d/figures" % journal["article_id"]))

    assert "figure-p004-1.png" in body
    assert "No images found in this article" not in body


def test_saving_the_figures_page_keeps_the_break_that_holds_the_caption(
        client, journal):
    """Dropping it parts the figure from the caption printed under it."""
    client.post("/articles/%d/figures" % journal["article_id"],
                data={"caption": "Fig. 1. A whiteboard in use.", "label": ""})

    _, body = conversion.read_article_metadata(journal["path"])
    assert "![Fig. 1. A whiteboard in use.](assets/figure-p004-1.png)\\" in body
    assert "Fig. 1. A whiteboard." in body
