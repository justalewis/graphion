"""Running the two external checkers over a whole journal.

The pass itself is thin: it walks articles, calls `validators`, and records
through `register`. What the tests are about is the two ways it could do
damage rather than nothing.

A tool that is not installed must stop the run before anything is written.
A recorded run is the newest run for its kind, so a pass over an archive
with verapdf missing would write "not checked" over every verdict a real
run had left, and `register.latest_run` would hand that back as the current
answer. The result would read as current, say nothing, and cost whatever
the real pass cost to get.

And the hash has to be taken before the tool runs, or the verdict is dated
to the file as it stands afterwards rather than to the bytes the tool read.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
import register
import validate_galleys
import validators


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.init_db()
    db.execute(
        "INSERT INTO journals (slug, name, template_path) VALUES (?, ?, ?)",
        ("a-journal", "A Journal", str(tmp_path / "template")),
    )
    return tmp_path


def _add_article(store, slug, galleys=("article.pdf", "article.html")):
    apath = store / slug
    apath.mkdir()
    (apath / "article.md").write_text("Body.", encoding="utf-8")
    for name in galleys:
        if name.endswith(".pdf"):
            (apath / name).write_bytes(b"%PDF-1.7 pretend")
        else:
            (apath / name).write_text("<p>Body.</p>", encoding="utf-8")
    article_id = db.execute(
        "INSERT INTO articles (journal_id, slug, title, project_path) "
        "VALUES (1, ?, ?, ?)", (slug, slug.title(), str(apath)))
    return {"id": article_id, "slug": slug, "project_path": str(apath)}


def _tools(monkeypatch, verapdf=True, pa11y=True):
    monkeypatch.setattr(validators, "verapdf_available", lambda: verapdf)
    monkeypatch.setattr(validators, "pa11y_available", lambda: pa11y)


def _run(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["validate_galleys.py", *argv])
    return validate_galleys.main()


# ---------- a tool that is not there writes nothing ----------

def test_a_missing_tool_stops_the_run_before_anything_is_written(
        store, monkeypatch, capsys):
    """The one that matters.

    An earlier pass left a real verdict. A later pass on a machine without
    verapdf must not replace it with a row saying the tool could not start,
    because that row is then the newest run and the only answer anybody
    reads.
    """
    art = _add_article(store, "already-checked")
    register.record_verapdf(art["id"], art["project_path"], True, {})
    assert register.standing(
        art["id"], art["project_path"])["verapdf"].level == "pass"

    _tools(monkeypatch, verapdf=False, pa11y=False)
    code = _run(monkeypatch, "a-journal")

    assert code == 1
    assert "not on PATH" in capsys.readouterr().err
    after = register.standing(art["id"], art["project_path"])["verapdf"]
    assert after.level == "pass"
    assert after.settled is True


def test_one_missing_tool_does_not_stop_the_other(store, monkeypatch):
    """Asked for only the tool that is there, the run proceeds."""
    art = _add_article(store, "html-only")
    _tools(monkeypatch, verapdf=False, pa11y=True)
    monkeypatch.setattr(validators, "run_pa11y", lambda path: (True, []))

    assert _run(monkeypatch, "a-journal", "--only", "pa11y") == 0
    assert register.standing(
        art["id"], art["project_path"])["pa11y"].level == "pass"


def test_a_tool_that_ran_and_could_not_answer_is_recorded(store, monkeypatch):
    """A timeout is a fact about the galley; an uninstalled binary is a fact
    about the machine. Only the first belongs in the register."""
    art = _add_article(store, "times-out")
    _tools(monkeypatch, verapdf=True, pa11y=False)
    monkeypatch.setattr(validators, "run_verapdf", lambda path: (
        False, {"error": "verapdf timed out (120s)", "passed": False}))

    assert _run(monkeypatch, "a-journal", "--only", "verapdf") == 0

    standing = register.standing(art["id"], art["project_path"])["verapdf"]
    assert standing.level == register.UNRUN
    assert standing.settled is False
    assert "timed out" in standing.findings[0].summary


# ---------- what goes into the plan ----------

def test_an_article_with_no_galley_is_left_out(store, monkeypatch):
    """Owing a render is not failing a check, which is a distinction the
    register already draws and this must not undo."""
    art = _add_article(store, "no-galley", galleys=())

    assert validate_galleys.to_do(art, "verapdf", skip_current=False) is None
    assert validate_galleys.to_do(art, "pa11y", skip_current=False) is None


def test_skip_current_leaves_out_what_is_already_answered(store):
    art = _add_article(store, "answered")
    register.record_verapdf(art["id"], art["project_path"], True, {})

    assert validate_galleys.to_do(art, "verapdf", skip_current=True) is None
    assert validate_galleys.to_do(art, "verapdf", skip_current=False) == "queued"


def test_a_run_against_content_that_moved_is_back_in_the_plan(store):
    """Which is what makes a second pass cheap without making it blind."""
    art = _add_article(store, "re-rendered")
    register.record_verapdf(art["id"], art["project_path"], True, {})
    Path(art["project_path"], "article.pdf").write_bytes(b"%PDF-1.7 again")

    assert validate_galleys.to_do(
        art, "verapdf", skip_current=True) == "re-check, content moved"


def test_a_tool_that_could_not_run_is_back_in_the_plan_too(store):
    """An unrun row answers nothing, so skipping past it would leave the
    article unchecked for good."""
    art = _add_article(store, "tool-was-missing")
    register.record_verapdf(art["id"], art["project_path"], False,
                            {"error": "verapdf CLI not on PATH"})

    assert validate_galleys.to_do(art, "verapdf", skip_current=True) == "queued"


def test_the_limit_counts_articles_and_stops(store, monkeypatch, capsys):
    for i in range(4):
        _add_article(store, "a%d" % i)
    _tools(monkeypatch)

    _run(monkeypatch, "a-journal", "--limit", "2", "--dry-run")

    assert "4 check(s) to run" in capsys.readouterr().out


# ---------- the verdict is dated to the bytes the tool read ----------

def test_the_hash_is_taken_before_the_tool_runs(store, monkeypatch):
    """A galley rendered again while the checker was working has moved under
    the verdict, and the register has to say so rather than date the result
    to whatever is on disk once the subprocess returns."""
    art = _add_article(store, "moves-underneath")
    _tools(monkeypatch, verapdf=True, pa11y=False)

    def rewrite_then_pass(path):
        Path(path).write_bytes(b"%PDF-1.7 rendered again mid-check")
        return True, {}

    monkeypatch.setattr(validators, "run_verapdf", rewrite_then_pass)
    _run(monkeypatch, "a-journal", "--only", "verapdf")

    standing = register.standing(art["id"], art["project_path"])["verapdf"]
    assert standing.state == register.STALE
    assert standing.settled is False


def test_a_dry_run_writes_nothing(store, monkeypatch, capsys):
    art = _add_article(store, "untouched")
    _tools(monkeypatch)

    assert _run(monkeypatch, "a-journal", "--dry-run") == 0

    assert "nothing written" in capsys.readouterr().out.lower()
    assert register.latest_run(art["id"], "verapdf") == []
    assert not Path(art["project_path"], "verapdf-report.json").exists()


def test_the_report_lands_beside_the_galley(store, monkeypatch):
    """The same file the per-article button writes, so the article page
    shows what the pass found."""
    art = _add_article(store, "reported")
    _tools(monkeypatch, verapdf=True, pa11y=False)
    monkeypatch.setattr(validators, "run_verapdf",
                        lambda path: (False, {"passed": False}))

    _run(monkeypatch, "a-journal", "--only", "verapdf")

    report = Path(art["project_path"], "verapdf-report.json")
    assert report.exists()
    assert "passed" in report.read_text(encoding="utf-8")


def test_an_unknown_journal_is_refused(store, monkeypatch, capsys):
    assert _run(monkeypatch, "no-such-journal") == 2
    assert "No journal" in capsys.readouterr().err
