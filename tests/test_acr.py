"""The conformance report, and the four ways it could flatter the archive.

An ACR is the document an institution reads before adopting a journal, so
every way it can be wrong is a way somebody is misled about whether they
can read the thing. Generating it from the register removes one failure
mode, a report drifting from the content it describes, and introduces
four others worth testing for.

It could fill in a criterion nothing checks. It could call a criterion Not
Applicable without establishing that it does not apply. It could count an
article whose run was taken against content that has since changed. And it
could report a level over the articles it managed to check while saying
nothing about the ones it could not.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import acr
import db
import lint
import register


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    db.execute(
        "INSERT INTO journals (slug, name, template_path) VALUES (?, ?, ?)",
        ("a-journal", "A Journal", str(tmp_path / "template")),
    )
    return tmp_path


def _add_article(store, slug, body="Body of the article.\n"):
    apath = store / slug
    apath.mkdir()
    (apath / "article.md").write_text(body, encoding="utf-8")
    (apath / "article.pdf").write_bytes(b"%PDF-1.7 pretend")
    (apath / "article.html").write_text("<p>Body.</p>", encoding="utf-8")
    article_id = db.execute(
        "INSERT INTO articles (journal_id, slug, title, project_path) "
        "VALUES (1, ?, ?, ?)", (slug, slug.title(), str(apath)))
    return {"id": article_id, "project_path": str(apath), "slug": slug}


def _lint(article, images_of_text=0, alt="pass"):
    register.record_lint(article["id"], article["project_path"], [
        lint.LintResult("alt-text", alt, "", [], {"figures": 1}),
        lint.LintResult("images-of-text",
                        "warn" if images_of_text else "pass", "", [],
                        {"images-of-text": images_of_text}),
    ])


def _one(report, number):
    return next(r for r in report.rows if r.criterion.number == number)


# ---------- a row nothing backs says so ----------

def test_a_criterion_with_no_check_behind_it_is_never_supported(store):
    """Most of WCAG cannot be checked by a machine. A generated report that
    quietly filled those in would defeat the whole exercise, and would be
    harder to catch than a hand-typed one because it looks systematic."""
    article = _add_article(store, "an-article")
    _lint(article)

    report = acr.report("A Journal", [article])

    for number in ("1.3.3", "1.4.1", "1.4.4", "3.1.2"):
        row = _one(report, number)
        assert row.level == acr.NOT_EVALUATED
        assert row.remark


def test_the_rows_that_do_carry_a_level_name_the_check(store):
    article = _add_article(store, "an-article")
    _lint(article)

    row = _one(acr.report("A Journal", [article]), "1.4.5")

    assert row.level == acr.SUPPORTS
    assert "lint:images-of-text" in row.evidence


# ---------- the level follows the findings ----------

def test_every_article_passing_supports_the_criterion(store):
    arts = [_add_article(store, "a%d" % i) for i in range(3)]
    for a in arts:
        _lint(a)

    assert _one(acr.report("A Journal", arts), "1.4.5").level == acr.SUPPORTS


def test_one_article_failing_makes_it_partial(store):
    arts = [_add_article(store, "a%d" % i) for i in range(3)]
    _lint(arts[0], images_of_text=2)
    _lint(arts[1])
    _lint(arts[2])

    row = _one(acr.report("A Journal", arts), "1.4.5")

    assert row.level == acr.PARTIAL
    assert "2 of 3 article(s) pass" in row.remark


def test_every_article_failing_does_not_support_it(store):
    arts = [_add_article(store, "a%d" % i) for i in range(2)]
    for a in arts:
        _lint(a, images_of_text=1)

    assert _one(acr.report("A Journal", arts), "1.4.5").level == acr.DOES_NOT


def test_a_run_against_content_that_moved_is_not_evidence(store):
    """The register's own rule, carried into the report. A level derived
    from runs taken before the content changed would read better the longer
    nobody re-checked, which is the failure the hash exists to prevent."""
    article = _add_article(store, "an-article")
    _lint(article)
    assert _one(acr.report("A Journal", [article]), "1.4.5").level == acr.SUPPORTS

    Path(article["project_path"], "article.md").write_text(
        "Body, revised.", encoding="utf-8")

    report = acr.report("A Journal", [article])
    assert _one(report, "1.4.5").level == acr.NOT_EVALUATED
    assert report.uncovered == 1


def test_a_row_says_how_many_articles_it_could_not_reach(store):
    """"115 of 115 pass" under a journal of 118 should not leave a reader
    working out where the other three went."""
    checked = _add_article(store, "checked")
    _lint(checked)
    silent = _add_article(store, "never-checked")

    row = _one(acr.report("A Journal", [checked, silent]), "1.4.5")

    assert "1 of 1 article(s) pass" in row.remark
    assert "1 article(s) are not counted here" in row.remark


# ---------- not applicable is a claim too ----------

def test_not_applicable_is_read_off_the_content(store):
    article = _add_article(store, "prose-only")
    _lint(article)

    row = _one(acr.report("A Journal", [article]), "1.2.2")

    assert row.level == acr.NOT_APPLICABLE
    assert "1 article(s) read" in row.remark
    assert row.evidence


def test_content_that_does_engage_a_criterion_is_not_waved_through(store):
    """A journal that does publish video gets Not Evaluated for captions,
    not Not Applicable and not Supports."""
    article = _add_article(
        store, "with-video",
        body="Body.\n\n<video src=\"talk.mp4\" controls></video>\n")
    _lint(article)

    row = _one(acr.report("A Journal", [article]), "1.2.2")

    assert row.level == acr.NOT_EVALUATED
    assert "carry media" in row.remark


def test_a_journal_nothing_could_be_read_from_claims_nothing(store):
    """No applicability claim without the content to back it."""
    article = _add_article(store, "gone")
    Path(article["project_path"], "article.md").unlink()

    row = _one(acr.report("A Journal", [article]), "1.2.2")

    assert row.level == acr.NOT_EVALUATED


# ---------- the bundle, where that is the evidence ----------

def test_a_bundle_with_both_halves_supports_bypass_blocks(tmp_path):
    bundle = tmp_path / "template"
    bundle.mkdir()
    (bundle / "article.html.j2").write_text(
        '<a class="skip-link" href="#body">Skip</a><div id="body"></div>',
        encoding="utf-8")
    (bundle / "article.css").write_text(
        ".skip-link { left: -9999px; }\n.skip-link:focus { left: 1rem; }\n"
        ":focus-visible { outline: 3px solid blue; }\n", encoding="utf-8")

    facts = acr.bundle_facts(bundle)

    assert facts["skip-link"] is True
    assert facts["focus-visible"] is True


def test_a_skip_link_with_no_stylesheet_rule_is_not_support(tmp_path):
    """Half of this fix is worse than none: the markup without the rule
    puts a visible "Skip" link above every title."""
    bundle = tmp_path / "template"
    bundle.mkdir()
    (bundle / "article.html.j2").write_text(
        '<a class="skip-link" href="#body">Skip</a><div id="body"></div>',
        encoding="utf-8")
    (bundle / "article.css").write_text("p { margin: 0; }", encoding="utf-8")

    assert acr.bundle_facts(bundle)["skip-link"] is False


def test_a_skip_link_pointing_at_nothing_is_not_support(tmp_path):
    bundle = tmp_path / "template"
    bundle.mkdir()
    (bundle / "article.html.j2").write_text(
        '<a class="skip-link" href="#nowhere">Skip</a>', encoding="utf-8")
    (bundle / "article.css").write_text(
        ".skip-link { left: -9999px; }\n.skip-link:focus { left: 1rem; }\n",
        encoding="utf-8")

    assert acr.skip_link_target(
        '<a class="skip-link" href="#nowhere">Skip</a>') is None
    assert acr.bundle_facts(bundle)["skip-link"] is False


def test_an_outline_that_is_removed_is_not_focus_visible():
    assert acr.focus_is_visible(":focus-visible { outline: 3px solid blue; }")
    assert not acr.focus_is_visible(":focus-visible { outline: none; }")
    assert not acr.focus_is_visible("a:focus { color: red; }")


def test_a_bundle_that_was_not_read_is_not_evaluated(store):
    article = _add_article(store, "an-article")
    _lint(article)

    row = _one(acr.report("A Journal", [article]), "2.4.1")

    assert row.level == acr.NOT_EVALUATED


# ---------- the table itself ----------

def test_every_criterion_appears_once_and_is_a_or_aa():
    numbers = [c.number for c in acr.CRITERIA]

    assert len(numbers) == len(set(numbers)), "a criterion is listed twice"
    assert all(c.level in ("A", "AA") for c in acr.CRITERIA)
    assert len(acr.CRITERIA) == 50, "WCAG 2.1 has 30 Level A and 20 Level AA"


def test_every_basis_names_a_check_the_register_can_hold():
    for criterion in acr.CRITERIA:
        for kind, _check in criterion.basis:
            assert kind in register.KINDS, (criterion.number, kind)


def test_the_report_says_what_it_is_not(store):
    article = _add_article(store, "an-article")
    _lint(article)

    note = acr.report("A Journal", [article]).note()

    assert "Not Evaluated rather than Supports" in note
    assert "substitute for a person reading" in note
