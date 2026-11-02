"""Recording what was checked, when, and against which bytes.

One test here carries most of the weight. A register whose stored passes
went on counting after the content changed would report an archive in
better shape the longer nobody refreshed it, and every number on the page
would be wrong in the flattering direction with nothing to show it. So the
cases below are mostly about what must not be counted: a pass against bytes
that have moved, a check that no longer runs, a galley that was never
rendered, and a tool that could not speak.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
import lint
import register


@pytest.fixture
def store(tmp_path, monkeypatch):
    """A database of its own per test, so nothing reaches the dev copy."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    db.execute(
        "INSERT INTO journals (slug, name, template_path) VALUES (?, ?, ?)",
        ("test-journal", "Test Journal", str(tmp_path / "template")),
    )
    return tmp_path


def _add_article(store, slug, files=("article.md",)):
    """A real article row, because check_runs.article_id is a foreign key.

    It carries ON DELETE CASCADE on purpose: a deleted article has to take
    its recorded runs with it, or the register goes on holding results for
    content that is no longer in the journal.
    """
    apath = store / slug
    apath.mkdir()
    for name in files:
        if name == "article.pdf":
            (apath / name).write_bytes(b"%PDF-1.7 pretend")
        elif name == "article.html":
            (apath / name).write_text("<p>Body.</p>", encoding="utf-8")
        else:
            (apath / name).write_text("Body of " + slug + ".", encoding="utf-8")
    article_id = db.execute(
        "INSERT INTO articles (journal_id, slug, title, project_path) "
        "VALUES (1, ?, ?, ?)",
        (slug, slug.replace("-", " ").title(), str(apath)),
    )
    return {"id": article_id, "project_path": str(apath), "slug": slug,
            "title": slug.replace("-", " ").title()}


@pytest.fixture
def article(store):
    """An article directory with all three checked files present."""
    return _add_article(store, "an-article",
                        files=("article.md", "article.pdf", "article.html"))


def _clean_lint():
    return [lint.LintResult("alt-text", "pass", "Every figure is described.", []),
            lint.LintResult("doi-format", "pass", "DOI is well formed.", [])]


# ---------- a pass against bytes that have moved is not a pass ----------

def test_a_recorded_pass_stops_counting_once_the_file_changes(article):
    """The one that matters.

    An editor lints clean, then edits the article. The stored rows still say
    pass, and the file they describe is gone. Counting them would make the
    journal look finished on the strength of a check that ran against
    different content, and nothing on the page would say so.
    """
    register.record_lint(article["id"], article["project_path"], _clean_lint())
    before = register.standing(article["id"], article["project_path"])["lint"]
    assert before.state == register.CURRENT
    assert before.clean

    Path(article["project_path"], "article.md").write_text(
        "---\ntitle: A\n---\n\nBody, revised.\n", encoding="utf-8")

    after = register.standing(article["id"], article["project_path"])["lint"]
    assert after.state == register.STALE
    assert after.clean is False
    assert after.settled is False
    assert after.tone == "unknown"
    assert after.recorded_hash != after.current_hash


def test_a_stale_pass_is_counted_apart_from_a_clean_one(article):
    register.record_lint(article["id"], article["project_path"], _clean_lint())
    Path(article["project_path"], "article.md").write_text("changed", encoding="utf-8")

    roll = register.rollup([article])

    assert roll.kinds["lint"].clean == 0
    assert roll.kinds["lint"].stale == 1
    assert roll.kinds["lint"].settled == 0
    assert roll.kinds["lint"].unanswered == 1


def test_rewriting_the_same_bytes_leaves_the_run_current(article):
    """Content, not mtime. A re-save that changes nothing has changed
    nothing, and a register keyed on timestamps would say otherwise."""
    text = Path(article["project_path"], "article.md").read_text(encoding="utf-8")
    register.record_lint(article["id"], article["project_path"], _clean_lint())
    Path(article["project_path"], "article.md").write_text(text, encoding="utf-8")

    assert register.standing(
        article["id"], article["project_path"])["lint"].state == register.CURRENT


# ---------- a run is a run, not the newest row of each name ----------

def test_a_check_that_no_longer_runs_stops_being_reported(article):
    """A finding from a retired check is the newest of its name forever.

    Matching the latest row per check name would keep it on the page after
    the check left `lint.DEFAULT_CHECKS`, reporting a problem nothing is
    looking for any more. The run id is what prevents that.
    """
    register.record_lint(article["id"], article["project_path"], [
        lint.LintResult("alt-text", "pass", "Described.", []),
        lint.LintResult("retired-check", "fail", "Something old.", []),
    ])
    register.record_lint(article["id"], article["project_path"], [
        lint.LintResult("alt-text", "pass", "Described.", []),
    ])

    findings = register.latest_run(article["id"], "lint")

    assert [f.check_name for f in findings] == ["alt-text"]
    assert register.standing(
        article["id"], article["project_path"])["lint"].level == "pass"


def test_the_newest_run_replaces_the_one_before_it(article):
    register.record_lint(article["id"], article["project_path"], _clean_lint())
    register.record_lint(article["id"], article["project_path"], [
        lint.LintResult("alt-text", "fail", "Two figures undescribed.", ["p. 3", "p. 7"]),
        lint.LintResult("doi-format", "pass", "DOI is well formed.", []),
    ])

    st = register.standing(article["id"], article["project_path"])["lint"]

    assert st.level == "fail"
    assert st.counts == {"fail": 1, "pass": 1}
    assert st.findings[0].details == ["p. 3", "p. 7"]


def test_the_worst_level_decides_the_article(article):
    register.record_lint(article["id"], article["project_path"], [
        lint.LintResult("a", "pass", "", []),
        lint.LintResult("b", "warn", "", []),
        lint.LintResult("c", "pass", "", []),
    ])

    assert register.standing(
        article["id"], article["project_path"])["lint"].level == "warn"


# ---------- nothing to check is not a failure ----------

def test_a_galley_that_was_never_rendered_reads_as_absent(store):
    """An article with no PDF owes a render, not a conformance failure.
    Rolling the two together would overstate what remediation costs and
    understate what is already conformant."""
    art = _add_article(store, "source-only")

    st = register.standing(art["id"], art["project_path"])

    assert st["verapdf"].state == register.ABSENT
    assert st["pa11y"].state == register.ABSENT
    assert st["lint"].state == register.NEVER

    roll = register.rollup([art])
    assert roll.kinds["verapdf"].absent == 1
    assert roll.kinds["verapdf"].fail == 0
    assert roll.kinds["lint"].never == 1


def test_a_result_about_a_file_since_deleted_is_absent_not_stale(article):
    register.record_verapdf(article["id"], article["project_path"], True, {})
    Path(article["project_path"], "article.pdf").unlink()

    st = register.standing(article["id"], article["project_path"])["verapdf"]

    assert st.state == register.ABSENT
    assert st.settled is False


def test_recording_is_declined_where_there_is_nothing_to_hash(store):
    art = _add_article(store, "no-source")
    Path(art["project_path"], "article.md").unlink()

    assert register.record_lint(
        art["id"], art["project_path"], _clean_lint()) is None
    assert register.latest_run(art["id"], "lint") == []


def test_a_run_has_to_name_the_bytes_it_ran_against(article):
    with pytest.raises(ValueError):
        register.record(article["id"], "lint",
                        [register.Finding("x", "pass")], "")


def test_an_unknown_kind_is_refused(article):
    with pytest.raises(ValueError):
        register.record(article["id"], "spellcheck",
                        [register.Finding("x", "pass")], "abc")


# ---------- a tool that could not speak has not passed or failed ----------

def test_a_missing_validator_records_a_warning_not_a_verdict(article):
    """verapdf absent from PATH is not the galley failing. Recording it as a
    fail would put a conformance verdict on record that nothing checked, and
    recording it as a pass would be worse."""
    register.record_verapdf(article["id"], article["project_path"], False,
                            {"error": "verapdf CLI not on PATH", "passed": False})

    st = register.standing(article["id"], article["project_path"])["verapdf"]

    assert st.level == "warn"
    assert "Not checked" in st.findings[0].summary


def test_a_real_verapdf_failure_is_recorded_as_one(article):
    register.record_verapdf(article["id"], article["project_path"], False,
                            {"passed": False})

    assert register.standing(
        article["id"], article["project_path"])["verapdf"].level == "fail"


def test_pa11y_warnings_alone_do_not_read_as_a_failure(article):
    register.record_pa11y(article["id"], article["project_path"], False, [
        {"type": "warning", "message": "Heading level skipped."},
    ])

    st = register.standing(article["id"], article["project_path"])["pa11y"]

    assert st.level == "warn"


def test_pa11y_errors_read_as_a_failure(article):
    register.record_pa11y(article["id"], article["project_path"], False, [
        {"type": "error", "message": "Image has no alt attribute."},
        {"type": "warning", "message": "Heading level skipped."},
    ])

    st = register.standing(article["id"], article["project_path"])["pa11y"]

    assert st.level == "fail"
    assert "1 error(s)" in st.findings[0].summary


# ---------- each kind is dated to its own file ----------

def test_each_kind_hashes_the_file_its_check_reads(article):
    """A lint result dated to the galley, or a PDF/UA verdict dated to the
    Markdown, would go stale on the wrong edit and stay current on the one
    that mattered."""
    hashes = {k: register.hash_for(article["project_path"], k)
              for k in register.KINDS}
    assert len(set(hashes.values())) == 3

    register.record_lint(article["id"], article["project_path"], _clean_lint())
    register.record_verapdf(article["id"], article["project_path"], True, {})

    Path(article["project_path"], "article.pdf").write_bytes(b"%PDF-1.7 re-rendered")

    st = register.standing(article["id"], article["project_path"])
    assert st["lint"].state == register.CURRENT
    assert st["verapdf"].state == register.STALE


# ---------- the rollup adds up and says what it leaves out ----------

def test_every_article_lands_in_exactly_one_bucket_per_kind(store):
    arts = [_add_article(store, "a%d" % i) for i in range(3)]
    register.record_lint(arts[0]["id"], arts[0]["project_path"], _clean_lint())
    register.record_lint(arts[1]["id"], arts[1]["project_path"], [
        lint.LintResult("alt-text", "fail", "Undescribed.", [])])

    roll = register.rollup(arts)

    assert roll.articles == 3
    k = roll.kinds["lint"]
    assert k.total == 3
    assert k.settled + k.unanswered == 3
    assert (k.clean, k.fail, k.never) == (1, 1, 1)


def test_the_rollup_says_what_is_in_neither_column(store):
    """WCAG 1.4.5 is the number that decides whether an archive is done and
    no check here settles it, so the page says so rather than letting the
    totals read as the whole job."""
    note = register.Rollup().note()

    assert "images-of-text" in note
    assert "older version" in note


def test_an_empty_journal_rolls_up_to_nothing(store):
    roll = register.rollup([])

    assert roll.articles == 0
    assert all(k.total == 0 for k in roll.kinds.values())
