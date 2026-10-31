"""Regression tests for conversion.read/write_article_metadata."""
import shutil
import sys
import tempfile
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import conversion
import pdf_ingest


def _scratch_article(initial_yaml_body: str) -> Path:
    tmp = Path(tempfile.mkdtemp())
    (tmp / ".versions").mkdir(exist_ok=True)
    (tmp / "article.md").write_text(initial_yaml_body, encoding="utf-8")
    return tmp


def test_round_trip_basic():
    article = _scratch_article(
        "---\ntitle: Foo\nshort-title: F\nshort-authors: A\n---\n\nbody.\n"
    )
    try:
        fm, body = conversion.read_article_metadata(article)
        assert fm["title"] == "Foo"
        fm["doi"] = "10.1/x"
        conversion.write_article_metadata(article, fm, body)
        fm2, _ = conversion.read_article_metadata(article)
        assert fm2["title"] == "Foo"
        assert fm2["doi"] == "10.1/x"
    finally:
        shutil.rmtree(article)


def test_sanitize_newlines_in_title():
    """If title has an embedded newline, sanitizer collapses to a space.
    Without the sanitizer the resulting YAML can parse ambiguously."""
    article = _scratch_article("---\ntitle: x\n---\n\nbody.\n")
    try:
        conversion.write_article_metadata(
            article,
            {"title": "Against AI Empire and the \nCritwashing of Generative AI"},
            "body",
        )
        raw = (article / "article.md").read_text(encoding="utf-8")
        end = raw.find("\n---", 4)
        fm = yaml.safe_load(raw[4:end])
        assert fm["title"] == "Against AI Empire and the Critwashing of Generative AI"
    finally:
        shutil.rmtree(article)


def test_sanitize_whitespace_in_authors():
    """Author names with stray whitespace/newlines normalize cleanly."""
    article = _scratch_article("---\ntitle: x\n---\n\nbody.\n")
    try:
        conversion.write_article_metadata(
            article,
            {
                "title": "T",
                "author": [
                    {"name": "Maggie  Fernandes\n", "affiliation": "  UoA  "},
                    {"name": "Jenny\tSano-Franchini", "affiliation": "WVU"},
                ],
            },
            "body",
        )
        raw = (article / "article.md").read_text(encoding="utf-8")
        end = raw.find("\n---", 4)
        fm = yaml.safe_load(raw[4:end])
        assert fm["author"][0]["name"] == "Maggie Fernandes"
        assert fm["author"][0]["affiliation"] == "UoA"
        assert fm["author"][1]["name"] == "Jenny Sano-Franchini"
    finally:
        shutil.rmtree(article)


def test_field_order_canonical():
    """Canonical field order: title first, then author, etc."""
    article = _scratch_article("---\nstatus: draft\n---\n\nbody.\n")
    try:
        conversion.write_article_metadata(
            article,
            {
                "status": "draft",
                "footer": "Journal X 1.1",
                "short-title": "ST",
                "abstract": "An abstract.",
                "title": "T",
                "author": [{"name": "A"}],
                "short-authors": "SA",
            },
            "body",
        )
        raw = (article / "article.md").read_text(encoding="utf-8")
        end = raw.find("\n---", 4)
        yaml_block = raw[4:end]
        # First three lines should be title, author, abstract (in that order)
        first_keys = [line.split(":")[0] for line in yaml_block.splitlines() if line and not line.startswith((" ", "-"))][:5]
        assert first_keys[:3] == ["title", "author", "abstract"]
    finally:
        shutil.rmtree(article)


def test_round_trip_preserves_body():
    article = _scratch_article(
        "---\ntitle: T\n---\n\n# Heading\n\nBody paragraph with `code` and *italics*.\n"
    )
    try:
        fm, body = conversion.read_article_metadata(article)
        assert "Heading" in body
        conversion.write_article_metadata(article, fm, body)
        _, body2 = conversion.read_article_metadata(article)
        assert body == body2
    finally:
        shutil.rmtree(article)


def test_plain_text_strips_markdown_from_titles():
    assert conversion.plain_text(
        "Review of *Abolitionist Intimacies: Queer and Trans Migrants*"
    ) == "Review of Abolitionist Intimacies: Queer and Trans Migrants"
    assert conversion.plain_text("A **bold** and _italic_ title") == "A bold and italic title"
    assert conversion.plain_text(r"Un/learning \*not emphasis\*") == "Un/learning *not emphasis*"
    assert conversion.plain_text("Queer Black Imagination & Abolitionist Futures") == (
        "Queer Black Imagination & Abolitionist Futures"
    )
    assert conversion.plain_text(None) is None


def test_running_head_strings_are_escaped_for_typst():
    """A short title that is itself a quotation used to end the Typst string
    literal early and fail the whole PDF render."""
    typ = (
        "#let short-title-val = GRAPHION_SHORT_TITLE_STRING\n"
        "#let short-authors-val = GRAPHION_SHORT_AUTHORS_STRING\n"
        "#let footer-val = GRAPHION_FOOTER_STRING\n"
    )
    fm = {
        "short-title": "\u201cTeaching Must Be Our Demonstration!\u201d",
        "short-authors": 'Pell & "Duffy"',
    }
    out = conversion._fill_typst_authors(typ, fm)
    assert "GRAPHION_" not in out
    assert '#let short-title-val = "\u201cTeaching Must Be Our Demonstration!\u201d"' in out
    assert '#let short-authors-val = "Pell & \\"Duffy\\""' in out
    assert '#let footer-val = ""' in out


def test_epub_is_stale_after_article_edit():
    """The EPUB is built on first download; a later edit must trigger a rebuild."""
    import os
    article = _scratch_article("---\ntitle: T\n---\n\nbody.\n")
    try:
        assert conversion.epub_is_stale(article)  # never built
        epub = article / "article.epub"
        epub.write_bytes(b"epub")
        md = article / "article.md"
        os.utime(md, (1000, 1000)); os.utime(epub, (2000, 2000))
        assert not conversion.epub_is_stale(article)
        os.utime(md, (3000, 3000))
        assert conversion.epub_is_stale(article)
    finally:
        shutil.rmtree(article)


def test_epub_author_args_split_names_and_affiliations():
    """Map-style authors printed as "true" on the EPUB title page."""
    args = conversion._epub_author_args({"author": [
        {"name": "Erin Green", "affiliation": "University of Maryland"},
        {"name": "Logan Middleton"},
    ]})
    assert args == [
        "-M", "author=Erin Green", "-M", "author=Logan Middleton",
        "-V", "author=Erin Green—University of Maryland",
        "-V", "author=Logan Middleton",
    ]
    assert conversion._epub_author_args({"author": "Solo Author"}) == [
        "-M", "author=Solo Author", "-V", "author=Solo Author",
    ]
    assert conversion._epub_author_args({}) == []


def test_notes_move_ahead_of_works_cited_in_html():
    html = (
        '<section id="intro" class="level1"><p>Body.</p></section>\n'
        '<section id="works-cited" class="level1 references"><h1>Works Cited</h1></section>\n'
        '<section id="footnotes" class="footnotes" role="doc-endnotes">\n<ol><li>A note.</li></ol>\n</section>\n'
        '</article>'
    )
    out = conversion.move_notes_before_references(html)
    assert out.index('id="footnotes"') < out.index('id="works-cited"')
    assert out.count('id="footnotes"') == 1 and out.endswith("</article>")
    # No Works Cited: unchanged.
    no_refs = html.replace('id="works-cited"', 'id="other"')
    assert conversion.move_notes_before_references(no_refs) == no_refs


def test_alt_text_an_editor_wrote_survives_a_second_ingest():
    """The description goes back to its own figure, matched by asset path."""
    previous = (
        "---\ntitle: Foo\n---\n\n"
        "![A quilt block of eight points, each built from rows of small "
        "diamonds.](assets/figure-p012-1.jpg)\n\n"
        "Some prose.\n"
    )
    # The figure has moved in the file and the caption it now pairs with
    # supplies a different description.
    fresh = (
        "Some prose.\n\n"
        "![Anishinaabe Quilts](assets/figure-p012-1.jpg)\\n"
        "Figure 15.3 Anishinaabe Quilts\n"
    )
    out, carried = conversion.carry_alt_text(fresh, previous)
    assert carried == 1
    assert "![A quilt block of eight points, each built from rows of " \
        "small diamonds.](assets/figure-p012-1.jpg)" in out
    # Nothing else about the body is touched, the caption line included.
    assert out.endswith("Figure 15.3 Anishinaabe Quilts\n")
    assert out.count("Some prose.") == 1


def test_a_placeholder_does_not_hold_a_real_description_out():
    """`undescribed_alt` is machine text, so a later caption may replace it."""
    previous = f"![{pdf_ingest.undescribed_alt(7)}](assets/figure-p007-1.jpg)\n"
    fresh = "![Renewable energy definition using partitions](assets/figure-p007-1.jpg)\n"
    out, carried = conversion.carry_alt_text(fresh, previous)
    assert carried == 0
    assert out == fresh
    # And the other way round: a description already written wins over a
    # placeholder the new run produced.
    out, carried = conversion.carry_alt_text(previous, fresh)
    assert carried == 1
    assert "![Renewable energy definition using partitions]" in out


def test_undescribed_alt_still_matches_its_pattern():
    """The carry-forward recognises the string by shape, so it has to hold."""
    assert conversion._UNDESCRIBED_ALT_RE.match(pdf_ingest.undescribed_alt(1))
    assert conversion._UNDESCRIBED_ALT_RE.match(pdf_ingest.undescribed_alt(214))
    assert not conversion._UNDESCRIBED_ALT_RE.match("A real description")


def test_a_figure_the_new_run_did_not_find_carries_nothing():
    """No match by path, so the body comes back exactly as ingest wrote it."""
    previous = "![Hand-written.](assets/figure-p004-1.jpg)\n"
    fresh = "![Undescribed](assets/figure-p009-1.png)\n\nProse.\n"
    out, carried = conversion.carry_alt_text(fresh, previous)
    assert (out, carried) == (fresh, 0)
    # An empty previous body is the first-ingest case and must not raise.
    assert conversion.carry_alt_text(fresh, "") == (fresh, 0)


def test_a_captioned_figure_keeps_its_description_not_its_caption():
    """After pairing, the description is in fig-alt and the caption is not it.

    `pair_figure_captions` puts the printed caption in the bracket and moves
    the description to `fig-alt`, so reading the bracket carries a caption and
    leaves the description behind.
    """
    previous = (
        '![Figure 2. "A College Collage" by Evan Kennedy on YouTube.]'
        '(assets/figure-p007-1.png)'
        '{#fig:1 fig-alt="A woman seen from behind, blurred, walking down an '
        'institutional corridor toward a bright barred window."}\n'
    )
    fresh = f"![{pdf_ingest.undescribed_alt(7)}](assets/figure-p007-1.png)\n"
    out, carried = conversion.carry_alt_text(fresh, previous)
    assert carried == 1
    assert "![A woman seen from behind, blurred, walking down an " \
        "institutional corridor toward a bright barred window.]" in out
    # The caption belongs to the page and is read off it again every run.
    assert "A College Collage" not in out


def test_a_caption_beside_a_placeholder_is_still_only_a_caption():
    """Nothing was ever written here, so there is nothing to carry."""
    previous = (
        "![Fig. 1. The writing situation.](assets/figure-p004-1.png)"
        f'{{#fig:1 fig-alt="{pdf_ingest.undescribed_alt(4)}"}}\n'
    )
    fresh = "![Undescribed](assets/figure-p004-1.png)\n"
    out, carried = conversion.carry_alt_text(fresh, previous)
    assert (out, carried) == (fresh, 0)


def test_a_description_goes_to_fig_alt_when_the_bracket_holds_a_caption():
    """The slot Pandoc reads is the one a description has to land in.

    This is the state `16-vankooten` was published in: the description
    standing where the caption belonged, and the placeholder left in the
    attribute that actually reaches a reader.
    """
    previous = (
        "![A tower of empty amber prescription bottles with white caps, "
        "stacked six rows high.](assets/figure-p006-1.png)"
        f'{{#fig:1 fig-alt="{pdf_ingest.undescribed_alt(6)}"}}\n'
    )
    fresh = (
        "![Figure 1. A still from a student video.]"
        "(assets/figure-p006-1.png)"
        f'{{#fig:1 fig-alt="{pdf_ingest.undescribed_alt(6)}"}}\n'
    )
    out, carried = conversion.carry_alt_text(fresh, previous)
    assert carried == 1
    assert 'fig-alt="A tower of empty amber prescription bottles with ' \
        'white caps, stacked six rows high."' in out
    # The caption the page printed stays where the pairing put it.
    assert "![Figure 1. A still from a student video.]" in out
    assert pdf_ingest.undescribed_alt(6) not in out
    # And carrying again changes nothing.
    again, carried_again = conversion.carry_alt_text(out, previous)
    assert (again, carried_again) == (out, 0)


def _repaired(body: str) -> str:
    """Run the render-time markdown repairs over a scratch article."""
    article = _scratch_article(f"---\ntitle: T\n---\n\n{body}")
    try:
        conversion._repair_markdown_quirks_in_file(article / "article.md")
        return (article / "article.md").read_text(encoding="utf-8")
    finally:
        shutil.rmtree(article, ignore_errors=True)


def test_two_tables_back_to_back_keep_the_blank_line_between_them():
    """A table too long for its page is set again at the top of the next one
    with its header repeated, and ingest puts both parts where the pages put
    them. Welding them made Pandoc read the second header and its delimiter
    as two more rows of the first."""
    out = _repaired(
        "| Aesthetic form | V |\n| --- | --- |\n|  | X |\n\n"
        "| Aesthetic form | V |\n| --- | --- |\n|  | X |\n"
    )
    assert "|  | X |\n\n| Aesthetic form | V |" in out
    assert out.count("| --- | --- |") == 2


def test_a_blank_line_inside_one_table_is_still_dropped():
    """Which is what the repair is for: Pandoc's HTML writer puts a blank
    line between a header and its own delimiter on very wide content."""
    out = _repaired("| A | B |\n\n| --- | --- |\n\n| 1 | 2 |\n")
    assert "| A | B |\n| --- | --- |\n| 1 | 2 |" in out
    # Grid tables go the same way; their separator is `+---+`, not `| --- |`.
    grid = _repaired("+---+---+\n\n| 1 | 2 |\n\n+---+---+\n")
    assert "+---+---+\n| 1 | 2 |\n+---+---+" in grid


def test_an_empty_head_row_does_not_read_as_a_delimiter():
    """PDF ingest gives a single-row box an empty head, so `|  |  |` leads
    most of volume 1 chapter 6's tables. Reading that as a delimiter row
    would stop the table below a blank line being recognised as one
    starting, and the two would be welded after all."""
    out = _repaired(
        "|  |  |\n| --- | --- |\n| Draft | Comment |\n\n"
        "|  |  |\n| --- | --- |\n| More draft | More comment |\n"
    )
    assert "| Draft | Comment |\n\n|  |  |" in out
    assert out.count("| --- | --- |") == 2
