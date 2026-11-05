"""Work that does not fit in a request, and the states it must not lie about.

Everything slow in this app has been a script, because a chapter is minutes
of pdfplumber and each validator is a 120 second subprocess. That is fine
for one editor with a terminal and it is the whole barrier for anybody
else, so the work a journal most wants done was the work that could not be
asked for from a browser.

What a job runner mostly has to get right is not throughput, it is telling
the truth about what happened. A row reading `running` that nothing is
advancing reads as work still in hand. A half-saved upload that gets queued
ingests some of a volume and calls it the whole of one. A batch that stops
on its first unopenable file costs the other twenty-four their run. Each of
those is a failure with no symptom, which is the kind this codebase keeps
paying for, so each of them is a test here.
"""
import io
import json
import shutil
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import conversion
import db
import jobs


@pytest.fixture(autouse=True)
def quiet_worker(monkeypatch):
    """No thread unless a test asks for one.

    Every handler is ordinary code reachable through `run_job`, so almost
    nothing here needs the worker, and a daemon thread outliving the test
    that started it holds a database path the next test has moved.
    """
    monkeypatch.setattr(jobs, "WORKER_ENABLED", False)
    yield
    jobs.stop_worker()


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A database, a content root and a staging root, none of them real."""
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(conversion, "CONTENT_DIR", tmp_path / "content")
    monkeypatch.setattr(jobs, "JOBS_DIR", tmp_path / "jobs")
    db.init_db()
    return tmp_path


@pytest.fixture
def journal(workspace):
    journal_id = db.execute(
        "INSERT INTO journals (slug, name, template_path) VALUES (?, ?, ?)",
        ("demo", "Demo Collection", str(workspace / "template")))
    return dict(db.query_one("SELECT * FROM journals WHERE id = ?",
                             (journal_id,)))


CHAPTER = """#set document(title: [Chapter {n}], author: ("A Writer",))
#set text(lang: "en")
= A Heading

Body text for chapter {n}, with enough words in it to look like a paragraph
on the page rather than a stray line of type.
"""


@pytest.fixture(scope="module")
def chapter_pdfs(tmp_path_factory):
    """Two one-page chapters, named the way volumes 4 to 6 name theirs.

    Module scoped because compiling them is the slow part and nothing in
    any test writes to them.
    """
    out = tmp_path_factory.mktemp("chapters")
    made = []
    for number in (1, 2):
        typ = out / f"c{number}.typ"
        typ.write_text(CHAPTER.replace("{n}", str(number)), encoding="utf-8")
        pdf = out / f"{number}Writer.pdf"
        conversion._compile_typst(typ, pdf, root=out)
        made.append(pdf)
    return made


def _stage(job_id, *sources):
    staged = jobs.staging_dir(job_id)
    for source in sources:
        shutil.copy(source, staged / Path(source).name)
    return staged


def _batch(journal, chapter_pdfs, facts=None, count=2):
    job_id = jobs.create("ingest_batch", "a batch",
                         facts if facts is not None else
                         {"replace": False, "teacher_mode": "separate"},
                         journal["id"])
    _stage(job_id, *chapter_pdfs[:count])
    jobs.release(job_id, total=count)
    return job_id


# ---------- the states ----------

def test_a_staged_job_is_not_claimed(workspace, journal):
    """Queuing and then saving the files is the obvious order and it is a
    race: a batch of twenty-five is seconds of saving and `claim()` is
    immediate, so the worker would read a directory still filling up and
    ingest part of a volume as the whole of one."""
    job_id = jobs.create("ingest_batch", "a batch", {}, journal["id"])

    assert jobs.get(job_id)["state"] == jobs.STAGING
    assert jobs.claim() is None


def test_releasing_hands_it_over(workspace, journal):
    job_id = jobs.create("ingest_batch", "a batch", {}, journal["id"])
    jobs.release(job_id, total=3)

    assert jobs.get(job_id)["state"] == jobs.QUEUED
    claimed = jobs.claim()
    assert claimed["id"] == job_id
    assert jobs.get(job_id)["state"] == jobs.RUNNING
    assert jobs.get(job_id)["total"] == 3


def test_claiming_twice_takes_two_jobs_and_not_one(workspace, journal):
    """Written as a conditional update rather than a read then a write, so
    two workers would take two jobs. One worker is the assumption this app
    makes everywhere, but the cost of being right here is one `WHERE`."""
    first = jobs.create("ingest_batch", "first", {}, journal["id"])
    second = jobs.create("ingest_batch", "second", {}, journal["id"])
    jobs.release(first)
    jobs.release(second)

    assert [jobs.claim()["id"], jobs.claim()["id"]] == [first, second]
    assert jobs.claim() is None


def test_a_job_the_process_died_under_reads_interrupted(workspace, journal):
    """Not `failed`, because the job did not go wrong, and not `running`,
    because nothing is advancing it. Left as `running` it reads as work
    still in hand, which is the flattering version of a process that
    stopped."""
    job_id = jobs.create("ingest_batch", "a batch", {}, journal["id"])
    jobs.release(job_id)
    jobs.claim()

    assert jobs.recover() == 1

    job = jobs.get(job_id)
    assert job["state"] == jobs.INTERRUPTED
    assert "stopped while this was running" in job["error"]


def test_an_upload_that_never_finished_is_dropped_not_queued(workspace,
                                                             journal):
    """A `staging` row is an upload that never finished arriving. Queuing
    it would run a half-saved batch, which is worse than losing it: the
    files that did arrive would come in as if they were all of it."""
    job_id = jobs.create("ingest_batch", "a batch", {}, journal["id"])

    jobs.recover()

    job = jobs.get(job_id)
    assert job["state"] == jobs.CANCELLED
    assert "did not finish" in job["error"]


def test_recover_leaves_a_finished_job_alone(workspace, journal):
    job_id = jobs.create("ingest_batch", "a batch", {}, journal["id"])
    jobs.release(job_id)
    jobs.claim()
    jobs._finish(job_id, jobs.DONE)

    assert jobs.recover() == 0
    assert jobs.get(job_id)["state"] == jobs.DONE


def test_the_staging_directory_goes_when_the_job_does(workspace, journal,
                                                      chapter_pdfs):
    """The uploads are a copy of what somebody already has, and what came
    of reading them is in `content/`. Keeping them would be a second
    archive nobody maintains."""
    job_id = _batch(journal, chapter_pdfs)
    staged = jobs.staging_dir(job_id)
    assert list(staged.iterdir())

    jobs.run_job(job_id)

    assert not staged.exists()


def test_an_unknown_kind_is_refused_before_a_row_exists(workspace):
    with pytest.raises(ValueError):
        jobs.create("no-such-kind", "a batch", {}, None)

    assert jobs.recent() == []


# ---------- progress and failure ----------

def test_progress_is_written_as_it_goes_and_not_at_the_end(workspace,
                                                           monkeypatch):
    """Holding the list in memory and writing once at the end is cheaper
    and loses everything the job had learned if the process dies, which is
    exactly the run worth knowing about."""
    seen = []

    def probe(job, progress):
        progress.plan(2)
        progress.step("first.pdf", "ingested", "article 1")
        seen.append(dict(jobs.get(job["id"])))
        progress.step("second.pdf", "ingested", "article 2")

    monkeypatch.setitem(jobs._HANDLERS, "probe", probe)
    job_id = jobs.create("probe", "a probe", {}, None)
    jobs.release(job_id)

    jobs.run_job(job_id)

    midway = seen[0]
    assert midway["done"] == 1
    assert midway["total"] == 2
    assert json.loads(midway["items_json"])[0]["name"] == "first.pdf"
    assert jobs.get(job_id)["done"] == 2


def test_a_handler_that_raises_records_the_traceback(workspace, monkeypatch):
    """Into the row rather than only into a log nobody serves, which is the
    mistake `conversion.log` already makes: it is written on every ingest
    and no route shows it."""
    def probe(job, progress):
        raise RuntimeError("the thing went wrong")

    monkeypatch.setitem(jobs._HANDLERS, "probe", probe)
    job_id = jobs.create("probe", "a probe", {}, None)
    jobs.release(job_id)

    assert jobs.run_job(job_id) == jobs.FAILED

    job = jobs.get(job_id)
    assert job["state"] == jobs.FAILED
    assert "the thing went wrong" in job["error"]
    assert "RuntimeError" in job["error"]


def test_cancelling_a_queued_job_stops_it_before_it_starts(workspace,
                                                           journal):
    job_id = jobs.create("ingest_batch", "a batch", {}, journal["id"])
    jobs.release(job_id)

    assert jobs.cancel(job_id) is True
    assert jobs.get(job_id)["state"] == jobs.CANCELLED
    assert jobs.claim() is None


def test_a_running_job_is_asked_rather_than_killed(workspace, monkeypatch):
    """A chapter halfway through ingest has files on disk and a row that
    does not match them yet, so the only safe place to stop is between two
    of them."""
    def probe(job, progress):
        progress.plan(3)
        progress.step("first.pdf", "ingested")
        jobs.cancel(job["id"])
        if progress.cancelled:
            return
        progress.step("second.pdf", "ingested")

    monkeypatch.setitem(jobs._HANDLERS, "probe", probe)
    job_id = jobs.create("probe", "a probe", {}, None)
    jobs.release(job_id)

    assert jobs.run_job(job_id) == jobs.CANCELLED
    assert jobs.get(job_id)["done"] == 1


def test_cancelling_a_finished_job_says_so(workspace, journal):
    job_id = jobs.create("ingest_batch", "a batch", {}, journal["id"])
    jobs._finish(job_id, jobs.DONE)

    assert jobs.cancel(job_id) is False


# ---------- the worker thread ----------

def _wait_for(job_id, timeout=20):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = jobs.get(job_id)
        if job["state"] in jobs.TERMINAL:
            return job
        time.sleep(0.02)
    raise AssertionError(f"job {job_id} never finished: {jobs.get(job_id)}")


def test_the_worker_runs_a_released_job(workspace, monkeypatch):
    done = []

    def probe(job, progress):
        progress.plan(1)
        progress.step("one.pdf", "ingested")
        done.append(job["id"])

    monkeypatch.setitem(jobs._HANDLERS, "probe", probe)
    monkeypatch.setattr(jobs, "WORKER_ENABLED", True)
    job_id = jobs.create("probe", "a probe", {}, None)
    jobs.release(job_id)

    assert _wait_for(job_id)["state"] == jobs.DONE
    assert done == [job_id]


def test_the_worker_carries_on_past_a_handler_that_raises(workspace,
                                                          monkeypatch):
    """One job blowing up must not strand every job behind it, which is
    what letting the exception out of the loop would do."""
    def probe(job, progress):
        if jobs.payload(job).get("explode"):
            raise RuntimeError("no")
        progress.step("one.pdf", "ingested")

    monkeypatch.setitem(jobs._HANDLERS, "probe", probe)
    monkeypatch.setattr(jobs, "WORKER_ENABLED", True)
    first = jobs.create("probe", "bad", {"explode": True}, None)
    second = jobs.create("probe", "good", {}, None)
    jobs.release(first)
    jobs.release(second)

    assert _wait_for(first)["state"] == jobs.FAILED
    assert _wait_for(second)["state"] == jobs.DONE


# ---------- ingest_batch ----------

def test_a_batch_is_ingested_through_ingest_volume(workspace, journal,
                                                   chapter_pdfs):
    """The handler drives `plan`, `volume_furniture` and `ingest_one`
    rather than reimplementing any of them, which is the point of this
    being a job: a batch from the browser and one from the command line
    are the same ingest and not two that have to be kept in step."""
    job_id = _batch(journal, chapter_pdfs,
                    {"volume": 1, "year": 2026, "replace": False,
                     "teacher_mode": "separate"})

    assert jobs.run_job(job_id) == jobs.DONE

    job = jobs.get(job_id)
    assert job["done"] == 2
    assert [i["state"] for i in jobs.items(job)] == ["ingested", "ingested"]

    rows = db.query_all("SELECT slug, project_path FROM articles "
                        "ORDER BY slug")
    assert len(rows) == 2
    for row in rows:
        assert (Path(row["project_path"]) / "article.md").exists()


def test_one_unreadable_chapter_does_not_stop_the_batch(workspace, journal,
                                                        chapter_pdfs):
    """A file that will not open is a finding about that file. Stopping
    here would cost the other twenty-four chapters of a volume their run,
    which is an afternoon."""
    job_id = jobs.create("ingest_batch", "a batch",
                         {"replace": False, "teacher_mode": "separate"},
                         journal["id"])
    staged = _stage(job_id, *chapter_pdfs)
    (staged / "3Broken.pdf").write_bytes(b"this is not a PDF")
    jobs.release(job_id, total=3)

    assert jobs.run_job(job_id) == jobs.DONE

    states = {i["name"]: i["state"] for i in jobs.items(jobs.get(job_id))}
    assert states["3Broken.pdf"] == "failed"
    assert states["1Writer.pdf"] == "ingested"
    assert states["2Writer.pdf"] == "ingested"


def test_a_chapter_already_here_is_skipped_unless_replace_is_set(
        workspace, journal, chapter_pdfs):
    first = _batch(journal, chapter_pdfs, count=1)
    jobs.run_job(first)

    again = _batch(journal, chapter_pdfs,
                   {"replace": False, "teacher_mode": "separate"}, count=1)
    jobs.run_job(again)

    assert jobs.items(jobs.get(again))[0]["state"] == "skipped"
    assert len(db.query_all("SELECT id FROM articles")) == 1

    replaced = _batch(journal, chapter_pdfs,
                      {"replace": True, "teacher_mode": "separate"}, count=1)
    jobs.run_job(replaced)

    assert jobs.items(jobs.get(replaced))[0]["state"] == "replaced"
    assert len(db.query_all("SELECT id FROM articles")) == 1


def test_the_licence_is_left_alone_when_the_form_says_to(workspace, journal,
                                                         chapter_pdfs):
    """The default, and for an archive you did not publish the only safe
    one. Volume 1 of Writing Spaces mixes two licences across seventeen
    chapters, so one value stamped across a run published the stricter
    terms over twelve that permit derivatives. The licence is the field in
    this archive that least tolerates being rounded off, so a batch that
    was told to keep each chapter's own must write neither key."""
    job_id = _batch(journal, chapter_pdfs,
                    {"replace": False, "teacher_mode": "separate"}, count=1)

    jobs.run_job(job_id)

    row = db.query_one("SELECT project_path FROM articles")
    front, _body = conversion.read_article_metadata(Path(row["project_path"]))
    assert "license" not in front or not front.get("license")


def test_a_licence_given_is_stamped_over_every_chapter(workspace, journal,
                                                       chapter_pdfs):
    """The other half: where a batch really does share one licence, it
    overwrites whatever a chapter's own pages carried rather than filling a
    gap, because that is what makes it one licence across the run."""
    job_id = _batch(journal, chapter_pdfs,
                    {"replace": False, "teacher_mode": "separate",
                     "license": "CC BY-NC-ND 4.0",
                     "license_url": "https://creativecommons.org/x/"},
                    count=2)

    jobs.run_job(job_id)

    rows = db.query_all("SELECT project_path FROM articles")
    assert len(rows) == 2
    for row in rows:
        front, _ = conversion.read_article_metadata(Path(row["project_path"]))
        assert front["license"] == "CC BY-NC-ND 4.0"
        assert front["license-url"] == "https://creativecommons.org/x/"


def test_a_deleted_journal_takes_its_job_history_with_it(workspace, journal,
                                                         chapter_pdfs):
    """`ON DELETE CASCADE` on `journal_id`, by the rule `check_runs`
    already follows: a record of what was run against something that no
    longer exists answers for nothing."""
    job_id = _batch(journal, chapter_pdfs, count=1)
    db.execute("DELETE FROM articles WHERE journal_id = ?", (journal["id"],))
    db.execute("DELETE FROM journals WHERE id = ?", (journal["id"],))

    assert jobs.get(job_id) is None


def test_a_batch_with_no_journal_fails_rather_than_guessing(workspace,
                                                            chapter_pdfs):
    """`journal_id` is nullable, so the handler can be reached without one.
    Picking some journal to put the chapters in would file somebody's
    archive under a title they never chose."""
    job_id = jobs.create("ingest_batch", "a batch",
                         {"replace": False, "teacher_mode": "separate"},
                         None)
    _stage(job_id, chapter_pdfs[0])
    jobs.release(job_id, total=1)

    assert jobs.run_job(job_id) == jobs.FAILED
    assert "no longer exists" in jobs.get(job_id)["error"]
    assert db.query_all("SELECT id FROM articles") == []


# ---------- validate ----------

@pytest.fixture
def galleys(workspace, journal):
    """Two articles with all three galleys beside them.

    The files only have to exist and hash: `run_one` is stubbed in these
    tests, because what is being checked is the pass's own decisions and
    not verapdf's.
    """
    made = []
    for slug in ("alpha", "beta"):
        project = workspace / "content" / slug
        project.mkdir(parents=True)
        for name in ("article.pdf", "article.html", "article.epub"):
            (project / name).write_bytes(b"not really a galley, but bytes")
        article_id = db.execute(
            "INSERT INTO articles (journal_id, slug, title, project_path) "
            "VALUES (?, ?, ?, ?)",
            (journal["id"], slug, slug.title(), str(project)))
        made.append(article_id)
    return made


@pytest.fixture
def every_tool_installed(monkeypatch):
    import validators
    for probe in ("verapdf_available", "pa11y_available",
                  "epubcheck_available"):
        monkeypatch.setattr(validators, probe, lambda: True)


def _verdicts(monkeypatch, level="pass"):
    """Stand in for the three subprocesses, recording what was asked."""
    import validate_galleys
    asked = []

    def run_one(article, kind):
        asked.append((kind, article["slug"]))
        return level, "0.1s"

    monkeypatch.setattr(validate_galleys, "run_one", run_one)
    return asked


def test_a_validate_pass_runs_each_checker_over_each_galley(
        workspace, journal, galleys, every_tool_installed, monkeypatch):
    asked = _verdicts(monkeypatch)
    job_id = jobs.create("validate", "all three", {"skip_current": False},
                         journal["id"], stage=False)
    jobs.release(job_id)

    assert jobs.run_job(job_id) == jobs.DONE

    job = jobs.get(job_id)
    assert job["total"] == 6
    assert job["done"] == 6
    assert sorted(asked) == sorted(
        [(kind, slug) for slug in ("alpha", "beta")
         for kind in ("verapdf", "pa11y", "epubcheck")])
    assert {i["state"] for i in jobs.items(job)} == {"pass"}


def test_a_tool_that_is_not_installed_is_left_out_and_named(
        workspace, journal, galleys, monkeypatch):
    """`validate_galleys.py` drops a missing kind rather than refusing the
    pass, because the reason for refusing is about that one kind's rows.
    The job does the same and says which, counted in the total so the line
    is not one nobody looks at under a progress bar reading done."""
    import validators
    monkeypatch.setattr(validators, "verapdf_available", lambda: True)
    monkeypatch.setattr(validators, "pa11y_available", lambda: True)
    monkeypatch.setattr(validators, "epubcheck_available", lambda: False)
    asked = _verdicts(monkeypatch)
    job_id = jobs.create("validate", "two of three", {"skip_current": False},
                         journal["id"], stage=False)
    jobs.release(job_id)

    jobs.run_job(job_id)

    items = jobs.items(jobs.get(job_id))
    unrun = [i for i in items if i["state"] == jobs.register.UNRUN]
    assert len(unrun) == 1
    assert "not installed" in unrun[0]["detail"]
    assert "none was overwritten" in unrun[0]["detail"]
    assert {kind for kind, _slug in asked} == {"verapdf", "pa11y"}
    assert jobs.get(job_id)["total"] == 5


def test_a_pass_with_no_tool_at_all_fails_rather_than_recording_nothing(
        workspace, journal, galleys, monkeypatch):
    """A recorded run is the newest run for its kind, so a pass with no
    tool would write "not checked" over verdicts that cost an hour to get.
    Finishing `done` having checked nothing would be the same claim one
    level up."""
    import validators
    for probe in ("verapdf_available", "pa11y_available",
                  "epubcheck_available"):
        monkeypatch.setattr(validators, probe, lambda: False)
    job_id = jobs.create("validate", "none", {}, journal["id"], stage=False)
    jobs.release(job_id)

    assert jobs.run_job(job_id) == jobs.FAILED

    error = jobs.get(job_id)["error"]
    assert "None of the requested tools is installed" in error
    assert "verapdf.org" in error


def test_the_level_a_checker_reached_is_the_item_state(
        workspace, journal, galleys, every_tool_installed, monkeypatch):
    _verdicts(monkeypatch, level="fail")
    job_id = jobs.create("validate", "failing", {"skip_current": False},
                         journal["id"], stage=False)
    jobs.release(job_id)

    jobs.run_job(job_id)

    assert {i["state"] for i in jobs.items(jobs.get(job_id))} == {"fail"}


def test_a_galley_that_went_missing_is_skipped_and_not_failed(
        workspace, journal, galleys, every_tool_installed, monkeypatch):
    """Owing a render is not failing a check, which is the distinction the
    register draws between `absent` and `fail` and the reason three of
    Writing Spaces' articles are not counted as shortfalls."""
    import validate_galleys
    monkeypatch.setattr(validate_galleys, "run_one",
                        lambda article, kind: (None, "no file"))
    job_id = jobs.create("validate", "gone", {"skip_current": False},
                         journal["id"], stage=False)
    jobs.release(job_id)

    jobs.run_job(job_id)

    assert {i["state"] for i in jobs.items(jobs.get(job_id))} == {"skipped"}


def test_one_checker_raising_does_not_stop_the_pass(
        workspace, journal, galleys, every_tool_installed, monkeypatch):
    import validate_galleys
    seen = []

    def run_one(article, kind):
        seen.append(kind)
        if kind == "pa11y":
            raise RuntimeError("the node process went away")
        return "pass", "0.1s"

    monkeypatch.setattr(validate_galleys, "run_one", run_one)
    job_id = jobs.create("validate", "one bad", {"skip_current": False},
                         journal["id"], stage=False)
    jobs.release(job_id)

    assert jobs.run_job(job_id) == jobs.DONE

    states = [i["state"] for i in jobs.items(jobs.get(job_id))]
    assert states.count("failed") == 2
    assert states.count("pass") == 4


def test_a_validation_pass_can_be_stopped_partway(
        workspace, journal, galleys, every_tool_installed, monkeypatch):
    """The one that matters most here: a pass over 118 articles is an hour
    at best, so being unable to stop it is the difference between usable
    and not."""
    import validate_galleys
    done = []

    def run_one(article, kind):
        done.append(kind)
        if len(done) == 2:
            jobs.cancel(article["job_id"])
        return "pass", "0.1s"

    job_id = jobs.create("validate", "stoppable", {"skip_current": False},
                         journal["id"], stage=False)
    monkeypatch.setattr(
        validate_galleys, "run_one",
        lambda article, kind: run_one(dict(article, job_id=job_id), kind))
    jobs.release(job_id)

    assert jobs.run_job(job_id) == jobs.CANCELLED
    assert len(done) == 2
    assert jobs.get(job_id)["done"] == 2


def test_a_validate_job_stages_nothing(workspace, journal):
    """Its input is already in `content/`. A `staged_path` naming a
    directory that never held anything is a small lie to leave lying
    around."""
    job_id = jobs.create("validate", "no staging", {}, journal["id"],
                         stage=False)

    assert jobs.get(job_id)["staged_path"] is None
    assert not jobs.staging_dir(job_id).exists()
    # The `staging` state still does its work regardless of the directory.
    assert jobs.claim() is None


def test_each_kind_has_its_own_words_for_what_its_items_are(workspace,
                                                            journal):
    """A validation pass under "what happened to each file", telling the
    reader that nothing is published by ingesting it, is worse than saying
    nothing, so the fallback is plainly generic and every registered kind
    sets its own."""
    assert set(jobs.KIND_WORDS) == set(jobs._HANDLERS)
    for kind, said in jobs.KIND_WORDS.items():
        assert said["heading"] and said["item"] and said["note"]
    assert jobs.words("no-such-kind") == jobs.DEFAULT_WORDS
    assert jobs.DEFAULT_WORDS["note"] == ""


def test_the_job_page_uses_the_words_for_its_own_kind(client, journal,
                                                      every_tool_installed,
                                                      galleys, monkeypatch):
    _verdicts(monkeypatch)
    job_id = jobs.create("validate", "a pass", {"skip_current": False},
                         journal["id"], stage=False)
    jobs.release(job_id)
    jobs.run_job(job_id)

    body = client.get(f"/jobs/{job_id}").data.decode("utf-8")

    assert "What each checker found" in body
    assert "nothing is published by ingesting it" not in body


def test_the_colour_of_a_level_is_registers_answer_and_not_a_second_one():
    """Two places deciding what a failure looks like is how one of them
    goes quietly wrong, which is why `Standing.tone` lives in `register`
    at all. A validate job's items are register levels, so they read their
    colours from the same map."""
    import register

    for level, tone in register.LEVEL_TONE.items():
        assert jobs.ITEM_TONE[level] == tone
    # `unrun` is not a finding, so it is not given a verdict's colour.
    assert register.UNRUN not in register.LEVEL_TONE
    assert jobs.ITEM_TONE[register.UNRUN] == "unknown"


# ---------- the routes ----------

@pytest.fixture
def client(workspace, monkeypatch):
    import app as app_module
    application = app_module.create_app()
    application.config["LOGIN_DISABLED"] = True
    return application.test_client()


def _upload(*names_and_bytes):
    return {"pdfs": [(io.BytesIO(data), name)
                     for name, data in names_and_bytes]}


def test_the_batch_form_is_served(client, journal):
    response = client.get("/journals/demo/ingest")

    assert response.status_code == 200
    assert b"Ingest a batch into Demo Collection" in response.data
    assert b'name="pdfs"' in response.data
    assert b"multiple" in response.data


def test_queueing_a_batch_stages_every_file_and_releases_it(client, journal,
                                                            chapter_pdfs):
    data = _upload(*[(p.name, p.read_bytes()) for p in chapter_pdfs])
    data["keep_license"] = "on"

    response = client.post("/journals/demo/ingest", data=data,
                           content_type="multipart/form-data")

    assert response.status_code == 302
    job = jobs.recent()[0]
    assert job["state"] == jobs.QUEUED
    assert job["total"] == 2
    staged = sorted(p.name for p in jobs.staging_dir(job["id"]).iterdir())
    assert staged == ["1Writer.pdf", "2Writer.pdf"]
    # Keeping each chapter's own licence means writing neither key, not
    # writing an empty one that would overwrite what the pages carried.
    assert "license" not in jobs.payload(job)


def test_two_files_of_one_name_are_both_staged(client, journal,
                                               chapter_pdfs):
    """`plan` reads a chapter's number and author off its filename, so two
    files of one name are two chapters and the second must not land on the
    first."""
    data = chapter_pdfs[0].read_bytes()

    client.post("/journals/demo/ingest",
                data=_upload(("1Writer.pdf", data), ("1Writer.pdf", data)),
                content_type="multipart/form-data")

    staged = sorted(p.name for p in
                    jobs.staging_dir(jobs.recent()[0]["id"]).iterdir())
    assert staged == ["1Writer-1.pdf", "1Writer.pdf"]


def test_uploading_no_pdfs_says_so(client, journal):
    response = client.post("/journals/demo/ingest",
                           data=_upload(("notes.docx", b"x")),
                           content_type="multipart/form-data",
                           follow_redirects=True)

    assert b"No PDFs uploaded" in response.data
    assert jobs.recent() == []


def test_the_job_page_shows_what_happened(client, journal, chapter_pdfs):
    job_id = _batch(journal, chapter_pdfs, count=1)
    jobs.run_job(job_id)

    body = client.get(f"/jobs/{job_id}").data.decode("utf-8")

    assert "1Writer.pdf" in body
    assert "ingested" in body
    assert "done" in body


def test_the_state_endpoint_reports_progress(client, journal, chapter_pdfs):
    job_id = _batch(journal, chapter_pdfs, count=1)
    jobs.run_job(job_id)

    payload = client.get(f"/jobs/{job_id}/state").get_json()

    assert payload["state"] == jobs.DONE
    assert payload["finished"] is True
    assert payload["done"] == 1
    assert payload["items"][0]["name"] == "1Writer.pdf"


def test_a_running_job_is_not_reported_as_finished(client, journal):
    job_id = jobs.create("ingest_batch", "a batch", {}, journal["id"])
    jobs.release(job_id)
    jobs.claim()

    payload = client.get(f"/jobs/{job_id}/state").get_json()

    assert payload["state"] == jobs.RUNNING
    assert payload["finished"] is False


def test_cancelling_from_the_page(client, journal):
    job_id = jobs.create("ingest_batch", "a batch", {}, journal["id"])
    jobs.release(job_id)

    client.post(f"/jobs/{job_id}/cancel")

    assert jobs.get(job_id)["state"] == jobs.CANCELLED


def test_the_jobs_list_is_served(client, journal):
    job_id = jobs.create("ingest_batch", "a readable label", {},
                         journal["id"])
    jobs.release(job_id)

    body = client.get("/jobs").data.decode("utf-8")

    assert "a readable label" in body
    assert "queued" in body


def test_a_missing_job_is_a_404(client):
    assert client.get("/jobs/9999").status_code == 404
    assert client.get("/jobs/9999/state").status_code == 404


# ---------- the larger request body stays on the batch routes ----------

def test_every_batch_endpoint_names_a_route_that_exists(client):
    """The exemption is by endpoint name rather than by path, so a rename
    detaches it. A detached name means that route starts refusing a batch
    while every other route silently keeps the larger limit, and neither
    half of that is visible."""
    import app as app_module

    for endpoint in app_module.BATCH_ENDPOINTS:
        assert endpoint in client.application.view_functions, endpoint


def test_the_ingest_route_is_allowed_the_larger_body(client, journal,
                                                     chapter_pdfs,
                                                     monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 8)

    response = client.post(
        "/journals/demo/ingest",
        data=_upload(("1Writer.pdf", chapter_pdfs[0].read_bytes())),
        content_type="multipart/form-data")

    assert response.status_code == 302


def test_queueing_a_validation_pass(client, journal, every_tool_installed):
    response = client.post("/accessibility/demo/validate",
                           data={"kinds": ["verapdf", "pa11y"],
                                 "skip_current": "on"})

    assert response.status_code == 302
    job = jobs.recent()[0]
    assert job["kind"] == "validate"
    assert job["state"] == jobs.QUEUED
    assert jobs.payload(job)["kinds"] == ["verapdf", "pa11y"]
    assert jobs.payload(job)["skip_current"] is True


def test_picking_no_checker_says_so(client, journal):
    response = client.post("/accessibility/demo/validate", data={},
                           follow_redirects=True)

    assert b"Pick at least one checker" in response.data
    assert jobs.recent() == []


def test_a_checker_name_the_pass_does_not_know_is_dropped(client, journal,
                                                          every_tool_installed):
    """The form posts names, so the names are checked against the ones
    `validate_galleys` actually has rather than passed through."""
    response = client.post("/accessibility/demo/validate",
                           data={"kinds": ["verapdf", "made-up"]})

    assert response.status_code == 302
    assert jobs.payload(jobs.recent()[0])["kinds"] == ["verapdf"]


def test_the_page_greys_out_a_checker_that_is_not_installed(client, journal,
                                                            monkeypatch):
    """The convention the rest of the app follows, and here it has teeth:
    the pass drops a missing tool, so offering it would be the page and
    the job disagreeing about what is about to happen."""
    import validators
    monkeypatch.setattr(validators, "verapdf_available", lambda: True)
    monkeypatch.setattr(validators, "pa11y_available", lambda: False)
    monkeypatch.setattr(validators, "epubcheck_available", lambda: False)

    body = client.get("/accessibility/demo").data.decode("utf-8")

    assert "npm install -g pa11y" in body
    assert "disabled" in body


def test_the_single_file_routes_still_keep_the_smaller_limit(client,
                                                             monkeypatch):
    import app as app_module
    monkeypatch.setattr(app_module, "MAX_UPLOAD_BYTES", 8)

    refused = client.post("/journals/demo/upload",
                          data={"body": "x" * 200},
                          content_type="multipart/form-data")

    assert refused.status_code == 413
