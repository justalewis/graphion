"""The register's pages, and the one thing they have to agree about.

An issue was a heading on the journal page and nothing else, so there was
no address to hand anybody: "volume 2 stands here" could only be said by
sending someone the whole journal and telling them where to scroll. It has
a route now, which means the heading and the page it links to both have to
name the issue, and they have to name it the same way. Two copies of that
string would drift, and the first thing a reader would notice is a heading
that does not match the page it opened.
"""
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db
import lint
import register


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
def archive(client, tmp_path):
    """Two journals, two issues in the first, and an unfiled draft."""
    db.execute("INSERT INTO journals (slug, name, template_path) "
               "VALUES (?, ?, ?)", ("a-journal", "A Journal", str(tmp_path)))
    db.execute("INSERT INTO journals (slug, name, template_path) "
               "VALUES (?, ?, ?)", ("elsewhere", "Elsewhere", str(tmp_path)))
    one = db.execute("INSERT INTO issues (journal_id, volume, issue_number, "
                     "year) VALUES (1, 1, 1, 2010)")
    two = db.execute("INSERT INTO issues (journal_id, volume, issue_number, "
                     "year) VALUES (1, 2, 1, 2011)")
    other = db.execute("INSERT INTO issues (journal_id, volume, issue_number, "
                       "year) VALUES (2, 1, 1, 2012)")
    made = {}
    for label, issue_id, slugs in (("one", one, ("alpha", "beta")),
                                   ("two", two, ("gamma",)),
                                   ("other", other, ("delta",))):
        for slug in slugs:
            apath = tmp_path / slug
            apath.mkdir()
            (apath / "article.md").write_text("Body.", encoding="utf-8")
            journal_id = 2 if label == "other" else 1
            article_id = db.execute(
                "INSERT INTO articles (journal_id, issue_id, slug, title, "
                "project_path) VALUES (?, ?, ?, ?, ?)",
                (journal_id, issue_id, slug, slug.title(), str(apath)))
            register.record_lint(article_id, str(apath), [
                lint.LintResult("alt-text", "pass", "", [], {"figures": 0})])
        made[label] = issue_id
    unfiled = tmp_path / "unfiled"
    unfiled.mkdir()
    (unfiled / "article.md").write_text("Body.", encoding="utf-8")
    db.execute("INSERT INTO articles (journal_id, slug, title, project_path) "
               "VALUES (1, 'unfiled', 'Unfiled', ?)", (str(unfiled),))
    return made


def _text(response) -> str:
    return response.get_data(as_text=True)


def test_an_issue_has_an_address(client, archive):
    response = client.get("/accessibility/a-journal/issues/%d" % archive["one"])

    assert response.status_code == 200
    assert "Volume 1, number 1 (2010)" in _text(response)


def test_the_heading_and_the_page_it_links_to_say_the_same_thing(client, archive):
    """One function names an issue, because the journal page groups by that
    string and the issue page titles itself with it."""
    journal = _text(client.get("/accessibility/a-journal"))
    link = re.search(
        r'href="[^"]*/issues/%d"[^>]*>\s*([^<]+?)\s*<' % archive["one"], journal)
    assert link, "the heading does not link to the issue"

    issue = _text(client.get("/accessibility/a-journal/issues/%d" % archive["one"]))
    assert link.group(1) in issue


def test_an_issue_shows_its_own_articles_and_no_others(client, archive):
    body = _text(client.get("/accessibility/a-journal/issues/%d" % archive["one"]))

    assert "Alpha" in body and "Beta" in body
    assert "Gamma" not in body
    assert "Unfiled" not in body


def test_an_issue_belonging_to_another_journal_is_not_found(client, archive):
    """The id is in the URL, so the journal in the URL has to own it or the
    page would serve one journal's standing under another's name."""
    assert client.get(
        "/accessibility/a-journal/issues/%d" % archive["other"]).status_code == 404


def test_an_issue_that_does_not_exist_is_not_found(client, archive):
    assert client.get("/accessibility/a-journal/issues/999999").status_code == 404


def test_articles_in_no_issue_are_grouped_without_a_link(client, archive):
    """There is nothing to link to, and a heading that looks like a link and
    is not is worse than one that does not."""
    body = _text(client.get("/accessibility/a-journal"))

    heading = re.search(r'<h2 class="group-head">\s*Not in an issue\s*</h2>', body)
    assert heading, "the unfiled group is missing or is linked"


def test_the_issue_page_counts_only_its_own_articles(client, archive):
    body = _text(client.get("/accessibility/a-journal/issues/%d" % archive["two"]))

    assert re.search(r"1 of 1", body), "the answered count covers the journal"


def test_every_register_page_answers(client, archive):
    for url in ("/accessibility",
                "/accessibility/a-journal",
                "/accessibility/a-journal/acr",
                "/accessibility/a-journal/issues/%d" % archive["one"]):
        assert client.get(url).status_code == 200, url
