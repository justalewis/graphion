"""A collection is a journal row saying less, and the one thing it refuses.

Everything a stranger's archive needs had a page: assess it, take it in as
a batch, run the checkers, work the description queue, read the conformance
report. Starting the thing those pages hang off needed a shell on the
machine, because `new_journal.py` was a script with its whole body inside
`main()`. That was most of why this app stayed pointed at the two archives
it was written for.

The distinction is deliberately small, because almost everything is the
same work: a collection holds articles, renders galleys from a template
bundle, and reads identically to the register, the queue and the report.
What it is not is a thing you deposit. A CrossRef deposit asserts these
DOIs are yours under your prefix and an OJS push puts the content into
your own journal's workflow, and doing either for an archive somebody sent
you to assess is a claim about ownership rather than a convenience. So the
tests that matter here are the ones that would catch that claim being made
by accident: a link left on a page, a route reached from a bookmark, and a
row whose kind nobody wrote.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import conversion
import db
import new_journal


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(conversion, "CONTENT_DIR", tmp_path / "content")
    monkeypatch.setattr(new_journal, "CONTENT_DIR", tmp_path / "content")
    db.init_db()
    # A starter bundle to clone, with the files a real one carries.
    starter = tmp_path / "content" / "journals" / "lics" / "template"
    starter.mkdir(parents=True)
    (starter / "article.css").write_text("body { color: #222; }",
                                         encoding="utf-8")
    (starter / "article.typ").write_text("// typst", encoding="utf-8")
    (starter / "assets").mkdir()
    db.execute("INSERT INTO journals (slug, name, template_path) "
               "VALUES (?, ?, ?)", ("lics", "LiCS", str(starter)))
    return tmp_path


@pytest.fixture
def client(workspace, monkeypatch):
    import jobs
    monkeypatch.setattr(jobs, "WORKER_ENABLED", False)
    import app as app_module
    application = app_module.create_app()
    application.config["LOGIN_DISABLED"] = True
    return application.test_client()


def _collection(slug="sent-archive", name="An Archive Somebody Sent"):
    return new_journal.scaffold(slug, name, kind=new_journal.COLLECTION)


def _article_in(journal_id, workspace, slug="chapter-one", rendered=False):
    project = workspace / "content" / slug
    project.mkdir(parents=True, exist_ok=True)
    (project / "article.md").write_text("Body.", encoding="utf-8")
    if rendered:
        # The article page hides the whole Outputs block, the download
        # menu and the deposit links inside it, until something has been
        # rendered. A test asserting on those has to get past that first.
        (project / "article.html").write_text("<p>Body.</p>",
                                              encoding="utf-8")
    return db.execute(
        "INSERT INTO articles (journal_id, slug, title, project_path) "
        "VALUES (?, ?, ?, ?)",
        (journal_id, slug, slug.title(), str(project)))


# ---------- what a row is ----------

def test_a_row_written_before_the_column_reads_as_a_journal(workspace):
    """`kind_of` is the one reader for exactly this. A template or a query
    testing the column directly calls a NULL neither kind, which would
    drop a real journal out of the CrossRef page without saying why."""
    assert new_journal.kind_of({"kind": None}) == new_journal.JOURNAL
    assert new_journal.kind_of({}) == new_journal.JOURNAL
    assert new_journal.kind_of({"kind": "nonsense"}) == new_journal.JOURNAL
    assert new_journal.kind_of({"kind": "collection"}) == new_journal.COLLECTION
    assert not new_journal.is_collection({"kind": None})


def test_the_seeded_journal_is_a_journal(workspace):
    row = db.query_one("SELECT * FROM journals WHERE slug = 'lics'")

    assert new_journal.kind_of(row) == new_journal.JOURNAL
    assert not new_journal.is_collection(row)


def test_scaffolding_makes_the_row_and_the_bundle(workspace):
    made = new_journal.scaffold("mhrj", "Modern Hispanic Review Journal",
                                issn="2326-5620")

    assert made["short_name"] == "MHRJ"
    bundle = Path(made["template_path"])
    assert (bundle / "article.css").exists()
    assert (bundle / "assets").is_dir()
    row = db.query_one("SELECT * FROM journals WHERE slug = 'mhrj'")
    assert row["issn"] == "2326-5620"
    assert new_journal.kind_of(row) == new_journal.JOURNAL


def test_a_collection_is_the_same_row_with_a_different_kind(workspace):
    made = _collection()

    row = db.query_one("SELECT * FROM journals WHERE slug = 'sent-archive'")
    assert new_journal.is_collection(row)
    assert Path(made["template_path"], "article.css").exists()
    # It renders galleys like anything else, so it has a bundle of its own.
    assert row["template_path"] == str(made["template_path"])


@pytest.mark.parametrize("slug", ["", "Has Caps", "-leading", "under_score",
                                  "trailing space "])
def test_a_slug_that_is_not_a_slug_is_refused(workspace, slug):
    with pytest.raises(new_journal.ScaffoldError):
        new_journal.scaffold(slug, "A Name")


def test_a_name_is_required(workspace):
    with pytest.raises(new_journal.ScaffoldError):
        new_journal.scaffold("fine-slug", "   ")


def test_a_slug_already_taken_is_refused(workspace):
    with pytest.raises(new_journal.ScaffoldError) as caught:
        new_journal.scaffold("lics", "Something Else")

    assert "already exists" in str(caught.value)


def test_an_unknown_kind_is_refused(workspace):
    with pytest.raises(new_journal.ScaffoldError):
        new_journal.scaffold("fine-slug", "A Name", kind="archive")


def test_nothing_is_written_when_the_scaffold_refuses(workspace):
    before = sorted(p.name for p in
                    (workspace / "content" / "journals").iterdir())

    with pytest.raises(new_journal.ScaffoldError):
        new_journal.scaffold("Not A Slug", "A Name")

    assert sorted(p.name for p in
                  (workspace / "content" / "journals").iterdir()) == before
    assert len(db.query_all("SELECT id FROM journals")) == 1


def test_an_existing_bundle_is_adopted_rather_than_overwritten(workspace):
    """What a fresh database in a clone needs: the bundles are versioned
    source and come with the checkout, while the database starts empty."""
    theirs = workspace / "content" / "journals" / "theirs" / "template"
    theirs.mkdir(parents=True)
    (theirs / "article.css").write_text("body { color: red; }",
                                        encoding="utf-8")

    made = new_journal.scaffold("theirs", "Theirs", adopt_template=True)

    assert (Path(made["template_path"]) / "article.css").read_text(
        encoding="utf-8") == "body { color: red; }"


def test_adopting_nothing_is_refused(workspace):
    with pytest.raises(new_journal.ScaffoldError) as caught:
        new_journal.scaffold("nowhere", "Nowhere", adopt_template=True)

    assert "No template bundle to adopt" in str(caught.value)


# ---------- the route ----------

def test_the_form_is_served(client):
    body = client.get("/journals/new").data.decode("utf-8")

    assert "Start a journal or a collection" in body
    assert 'value="collection"' in body
    assert "LiCS" in body


def test_creating_a_collection_sends_you_to_take_the_archive_in(client,
                                                                workspace):
    response = client.post("/journals/new",
                           data={"kind": "collection",
                                 "name": "An Archive Somebody Sent",
                                 "slug": "sent-archive"})

    assert response.status_code == 302
    assert "/journals/sent-archive/ingest" in response.headers["Location"]
    assert new_journal.is_collection(
        db.query_one("SELECT * FROM journals WHERE slug = 'sent-archive'"))


def test_creating_a_journal_sends_you_to_its_settings(client, workspace):
    response = client.post("/journals/new",
                           data={"kind": "journal", "name": "A New Journal",
                                 "slug": "a-new-journal"})

    assert "/journals/a-new-journal/settings" in response.headers["Location"]


def test_the_slug_is_made_from_the_name_when_left_empty(client, workspace):
    client.post("/journals/new",
                data={"kind": "journal", "name": "Modern Hispanic Review"})

    assert db.query_one("SELECT id FROM journals WHERE slug = ?",
                        ("modern-hispanic-review",))


def test_an_issn_posted_for_a_collection_is_not_kept(client, workspace):
    """An ISSN identifies a serial you publish. The form does not offer it
    for a collection, and a posted one is dropped rather than stored,
    because a stored one would show up anywhere the row is read."""
    client.post("/journals/new",
                data={"kind": "collection", "name": "An Archive",
                      "slug": "an-archive", "issn": "2326-5620"})

    row = db.query_one("SELECT * FROM journals WHERE slug = 'an-archive'")
    assert row["issn"] is None


def test_a_refused_scaffold_comes_back_with_the_reason(client, workspace):
    response = client.post("/journals/new",
                           data={"kind": "journal", "name": "Clash",
                                 "slug": "lics"},
                           follow_redirects=True)

    assert b"already exists" in response.data
    assert len(db.query_all("SELECT id FROM journals")) == 1


# ---------- a collection is not deposited ----------

def test_the_crossref_page_leaves_collections_out(client, workspace):
    """Not shown as "not ready", because they are not short of a prefix.
    A row reading "missing: crossref_prefix" invites somebody to go and
    supply one for an archive that is not theirs to register."""
    _collection()

    body = client.get("/crossref").data.decode("utf-8")

    assert "LiCS" in body
    assert "An Archive Somebody Sent" not in body


def test_an_articles_crossref_xml_is_refused_for_a_collection(client,
                                                              workspace):
    """The route and not only the link, because a rule enforced in a
    template is a rule a bookmark walks past."""
    made = _collection()
    article_id = _article_in(made["id"], workspace)

    response = client.get(f"/articles/{article_id}/crossref.xml")

    assert response.status_code == 404
    assert b"collection rather than a journal" in response.data


def test_an_ojs_package_is_refused_for_a_collection(client, workspace):
    made = _collection()
    article_id = _article_in(made["id"], workspace)

    assert client.get(
        f"/articles/{article_id}/ojs-package").status_code == 404


def test_an_ojs_push_is_refused_for_a_collection(client, workspace):
    made = _collection()
    article_id = _article_in(made["id"], workspace)

    assert client.get(
        f"/articles/{article_id}/ojs-upload").status_code == 404


def test_an_issues_crossref_xml_is_refused_for_a_collection(client,
                                                            workspace):
    made = _collection()
    issue_id = db.execute(
        "INSERT INTO issues (journal_id, volume, issue_number, year) "
        "VALUES (?, 1, 1, 2026)", (made["id"],))

    assert client.get(f"/issues/{issue_id}/crossref.xml").status_code == 404


def test_a_journal_is_still_offered_all_of_it(client, workspace):
    """The other half, and the one a guard like this usually breaks."""
    journal = db.query_one("SELECT * FROM journals WHERE slug = 'lics'")
    article_id = _article_in(journal["id"], workspace, slug="a-real-article")

    assert client.get(
        f"/articles/{article_id}/crossref.xml").status_code != 404
    assert client.get(
        f"/articles/{article_id}/ojs-upload").status_code != 404


def test_the_article_page_offers_no_deposit_for_a_collection(client,
                                                             workspace):
    made = _collection()
    article_id = _article_in(made["id"], workspace, rendered=True)

    body = client.get(f"/articles/{article_id}").data.decode("utf-8")

    assert "crossref.xml" not in body
    assert "ojs-package" not in body
    # JATS describes the article rather than claiming it, so it stays.
    assert "jats.xml" in body


def test_the_article_page_still_offers_them_for_a_journal(client, workspace):
    journal = db.query_one("SELECT * FROM journals WHERE slug = 'lics'")
    article_id = _article_in(journal["id"], workspace, slug="a-real-article",
                             rendered=True)

    body = client.get(f"/articles/{article_id}").data.decode("utf-8")

    assert "crossref.xml" in body
    assert "ojs-package" in body


def test_the_settings_page_hides_the_deposit_fields_for_a_collection(
        client, workspace):
    _collection()

    body = client.get("/journals/sent-archive/settings").data.decode("utf-8")

    assert 'name="crossref_prefix"' not in body
    assert 'name="ojs_api_token"' not in body
    assert "neither is a claim to make" in body
    # The rest of the page is the same work and is still there: a
    # collection renders galleys from a template bundle like anything
    # else, so its brand and its running heads still matter.
    assert 'name="header_label_template"' in body
    assert 'name="citation_style"' in body


def test_the_settings_page_still_has_them_for_a_journal(client, workspace):
    body = client.get("/journals/lics/settings").data.decode("utf-8")

    assert 'name="crossref_prefix"' in body
    assert 'name="ojs_api_token"' in body


def test_a_collection_is_labelled_where_it_is_listed(client, workspace):
    _collection()

    dashboard = client.get("/").data.decode("utf-8")
    page = client.get("/journals/sent-archive").data.decode("utf-8")

    assert "collection" in dashboard
    assert "collection" in page
    assert "not deposited" in page


# ---------- everything else is the same work ----------

def test_a_collection_gets_every_other_page(client, workspace):
    """The distinction is small on purpose. A collection that could not be
    assessed, ingested into, checked or described would be a second class
    of thing to keep working, and the whole argument for it being one row
    is that it is not."""
    made = _collection()
    _article_in(made["id"], workspace)

    for url in ("/journals/sent-archive",
                "/journals/sent-archive/ingest",
                "/journals/sent-archive/settings",
                "/accessibility/sent-archive",
                "/accessibility/sent-archive/acr",
                "/accessibility/sent-archive/describe"):
        assert client.get(url).status_code == 200, url
