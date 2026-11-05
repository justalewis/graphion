"""Work that does not fit in a request.

Everything slow in this app has been a script for that reason. Ingesting a
chapter is minutes of pdfplumber, and each of the three validators is a
subprocess with a 120 second timeout, so `ingest_volume.py` and
`validate_galleys.py` are commands and the corpus route in `app.py` runs
only the two in-process checks. That is the right trade for a single
editor with a terminal and the wrong one for anybody else: the work a
journal most wants done is exactly the work that cannot be asked for from
a browser.

A job is a row, a staging directory and a handler. The row is the record,
so a batch survives the request that asked for it and a restart that
interrupts it; the staging directory is where an upload waits, under
`DATA_DIR` rather than `CONTENT_DIR` because it is input and not content;
and the handler is ordinary code that already existed. `ingest_batch`
drives `ingest_volume.plan`, `volume_furniture` and `ingest_one`, which is
the point: a batch taken in from the browser and one taken in from the
command line are the same ingest, not two that have to be kept in step.

**One worker, which is the assumption this app already makes.**
`deploy/entrypoint.sh` configures a single gunicorn worker and the login
limiter in `app.py` counts in-process on that basis. The worker here is one
daemon thread in that process, waiting on an event rather than polling.
`claim()` is still written as a conditional update, so two of them would
take different jobs rather than the same one, but nothing else in this file
is safe to run twice and the limiter would be wrong first; raising
`GUNICORN_WORKERS` means replacing both.

**A job that was interrupted says so rather than looking finished.** A
process that dies mid-batch leaves a row reading `running` and nothing to
advance it, and the flattering reading of that is a batch still going. So
`recover()` runs at app start and marks any such row `interrupted`, with
the items it had already recorded intact. That is the same rule the
register runs on: a result that is not current does not count, and a state
nobody can vouch for is not a success.

**The parts that fail are named and the rest of the batch continues.** One
unopenable PDF in twenty-five is a finding about that PDF, and stopping the
run on it would cost the other twenty-four an hour. Each item records its
own state, so the job page is a list of what happened rather than one
verdict.
"""
from __future__ import annotations

import json
import shutil
import threading
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import db
import register
from config import JOBS_DIR, RESULTS_DIR

# States. `interrupted` and `cancelled` are deliberately not `failed`: the
# first says the process died under it and the second says somebody stopped
# it, and neither is the job having gone wrong. Folding them into `failed`
# would read as a pipeline that breaks on its own.
STAGING = "staging"
QUEUED = "queued"
RUNNING = "running"
DONE = "done"
FAILED = "failed"
CANCELLED = "cancelled"
INTERRUPTED = "interrupted"

TERMINAL = frozenset({DONE, FAILED, CANCELLED, INTERRUPTED})

STATE_TONE = {
    STAGING: "unknown",
    QUEUED: "unknown",
    RUNNING: "warn",
    DONE: "good",
    FAILED: "bad",
    CANCELLED: "unknown",
    INTERRUPTED: "bad",
}

# Per-item states, which are the handler's to choose. `ingest_one` already
# returns the first three words and a validate job's items are register
# levels, so both vocabularies are their own module's rather than a third
# one written over the top of them. The colours for a level come from
# `register.LEVEL_TONE` for the same reason `Standing.tone` lives there: two
# places deciding what a failure looks like is how one of them goes quietly
# wrong. `unrun` is here and not there because it is not a finding, so it
# reads as unknown rather than as a verdict.
ITEM_TONE = {
    "ingested": "good",
    "replaced": "good",
    "skipped": "unknown",
    "failed": "bad",
    register.UNRUN: "unknown",
    **register.LEVEL_TONE,
}

# What the job page calls a kind's items. Here beside the handlers rather
# than as a switch in the template, because a kind that does not set these
# is a kind somebody forgot, and the fallback should read as plainly
# generic rather than as another kind's words: a validation pass under the
# heading "what happened to each file", telling the reader that nothing is
# published by ingesting it, is worse than saying nothing.
KIND_WORDS = {
    "ingest_batch": {
        "heading": "What happened to each file",
        "item": "File",
        "note": "A chapter that would not open is a finding about that "
                "chapter, so the batch carries on past it and names it "
                "here rather than stopping. What landed is a draft: "
                "nothing is published by ingesting it.",
    },
    "validate": {
        "heading": "What each checker found",
        "item": "Check",
        "note": "Each verdict is recorded against a hash of the file the "
                "checker read, so it stops counting as current if that "
                "file changes. A checker that is not installed is named "
                "above and nothing was recorded for it, because a missing "
                "tool is not a result and would have written over one.",
    },
}

KIND_WORDS["remediate_cartridge"] = {
    "heading": "What was done",
    "item": "Step",
    "note": "Nothing in the course was reworded: every changed page and PDF "
            "had its text compared before and after, and a fix that would "
            "have moved a word was dropped for that file. What is still "
            "owed needs a person, and is listed in the report.",
}

KIND_WORDS["apply_descriptions"] = {
    "heading": "What was written",
    "item": "Step",
    "note": "Only what the author typed was written, and only into the one "
            "attribute that holds a picture's description. Every edited "
            "file's text was compared before and after, and every other "
            "part of an edited Word or PowerPoint file kept its bytes.",
}

DEFAULT_WORDS = {"heading": "What happened", "item": "Item", "note": ""}


def words(kind: str) -> dict:
    return KIND_WORDS.get(kind, DEFAULT_WORDS)


# Set False in tests. A daemon thread that outlives an assertion is the
# usual way a test suite becomes intermittent, and every handler here is
# callable directly through `run_job`, which is what the tests use.
WORKER_ENABLED = True

_HANDLERS: dict = {}
_worker: Optional[threading.Thread] = None
_worker_lock = threading.Lock()
_wake = threading.Event()
_stopping = threading.Event()


def handler(kind: str) -> Callable:
    """Register the callable that runs one kind of job."""
    def register(fn):
        _HANDLERS[kind] = fn
        return fn
    return register


# ---------- the row ----------

def staging_dir(job_id: int) -> Path:
    return Path(JOBS_DIR) / str(job_id)


def create(kind: str, label: str, payload: Optional[dict] = None,
           journal_id: Optional[int] = None, stage: bool = True) -> int:
    """Open a job and make somewhere to stage its input. Returns the id.

    The row comes first because the id is what names the staging
    directory, and it opens in `staging` rather than `queued` so the
    worker cannot take it while the upload is still arriving. Enqueuing
    and then saving the files is the obvious order and it is a race: a
    batch of twenty-five is seconds of saving, and `claim()` is immediate.
    `release()` is what hands it over.
    """
    if kind not in _HANDLERS:
        raise ValueError(f"No handler registered for job kind {kind!r}")
    job_id = db.execute(
        "INSERT INTO jobs (kind, label, state, journal_id, payload_json, "
        "items_json) VALUES (?, ?, ?, ?, ?, '[]')",
        (kind, label, STAGING, journal_id, json.dumps(payload or {})),
    )
    # `stage=False` for a job whose input is already in `content/`, which a
    # validate pass is. A `staged_path` naming a directory that never held
    # anything is a small lie to leave lying around, and the `staging`
    # state still does its work: the row is not claimable until `release`.
    if stage:
        staging_dir(job_id).mkdir(parents=True, exist_ok=True)
        db.execute("UPDATE jobs SET staged_path = ? WHERE id = ?",
                   (str(staging_dir(job_id)), job_id))
    return job_id


def release(job_id: int, total: int = 0) -> None:
    """Hand a staged job to the worker."""
    db.execute("UPDATE jobs SET state = ?, total = ? WHERE id = ? "
               "AND state = ?", (QUEUED, total, job_id, STAGING))
    start_worker()
    _wake.set()


def abandon(job_id: int, reason: str) -> None:
    """Drop a job that never got as far as being queued."""
    _finish(job_id, CANCELLED, reason)


def get(job_id: int) -> Optional[dict]:
    row = db.query_one("SELECT * FROM jobs WHERE id = ?", (job_id,))
    return dict(row) if row else None


def recent(limit: int = 50, journal_id: Optional[int] = None) -> list:
    if journal_id is None:
        rows = db.query_all(
            "SELECT * FROM jobs ORDER BY id DESC LIMIT ?", (limit,))
    else:
        rows = db.query_all(
            "SELECT * FROM jobs WHERE journal_id = ? ORDER BY id DESC "
            "LIMIT ?", (journal_id, limit))
    return [dict(r) for r in rows]


def items(job: dict) -> list:
    """What happened to each part of the batch, oldest first."""
    try:
        return json.loads(job.get("items_json") or "[]")
    except (TypeError, ValueError):
        return []


def payload(job: dict) -> dict:
    try:
        return json.loads(job.get("payload_json") or "{}")
    except (TypeError, ValueError):
        return {}


def cancel(job_id: int) -> bool:
    """Ask a job to stop between items.

    A queued job stops now, because nothing has started. A running one is
    asked rather than killed: a chapter halfway through ingest has files on
    disk and a row that does not match them yet, and the only safe place to
    stop is between two of them.
    """
    job = get(job_id)
    if job is None or job["state"] in TERMINAL:
        return False
    if job["state"] in (QUEUED, STAGING):
        _finish(job_id, CANCELLED)
        return True
    db.execute("UPDATE jobs SET cancel_requested = 1 WHERE id = ?", (job_id,))
    return True


def cancelled(job_id: int) -> bool:
    row = db.query_one("SELECT cancel_requested FROM jobs WHERE id = ?",
                       (job_id,))
    return bool(row and row["cancel_requested"])


# ---------- progress ----------

class Refusal(Exception):
    """A job that declined to run, with a sentence to show.

    Distinct from an exception because a refusal is the job working, not
    breaking: a cartridge carrying student work is turned away on purpose,
    and a traceback under that message would read as a defect.
    """


def results_dir(job_id: int) -> Path:
    return Path(RESULTS_DIR) / str(job_id)


@dataclass
class Progress:
    """What a handler writes to as it goes.

    Every step is a write, which is affordable because a step is a chapter
    and a chapter is minutes. The alternative, holding the list in memory
    and writing once at the end, loses everything the job had learned if
    the process dies, which is exactly the run worth knowing about.
    """

    job_id: int
    _items: list = field(default_factory=list)

    def plan(self, total: int) -> None:
        db.execute("UPDATE jobs SET total = ? WHERE id = ?",
                   (total, self.job_id))

    # Set once a handler has ticked, so `step` stops reporting the length of
    # the item list as progress. A cartridge job ticks through 440 members and
    # then records seven summary items, and without this the page read 7 of
    # 440 after the job had finished all of them.
    ticked: bool = False

    def tick(self, done: int, total: int) -> None:
        """Update the counts without recording an item.

        `step` appends to the item list and rewrites it every time, which is
        right for a chapter and wrong for a cartridge member: a course has
        thousands of them and the list would be rewritten thousands of
        times. A job like that records a handful of summary items at the
        end and ticks the counts as it goes.
        """
        self.ticked = True
        db.execute("UPDATE jobs SET done = ?, total = ? WHERE id = ?",
                   (done, total, self.job_id))

    def step(self, name: str, state: str, detail: str = "") -> None:
        self._items.append({"name": name, "state": state, "detail": detail})
        if self.ticked:
            db.execute("UPDATE jobs SET items_json = ? WHERE id = ?",
                       (json.dumps(self._items), self.job_id))
            return
        db.execute(
            "UPDATE jobs SET items_json = ?, done = ? WHERE id = ?",
            (json.dumps(self._items), len(self._items), self.job_id),
        )

    @property
    def cancelled(self) -> bool:
        """Re-read, because the asking happens in another thread."""
        return cancelled(self.job_id)

    def counts(self) -> dict:
        out: dict = {}
        for item in self._items:
            out[item["state"]] = out.get(item["state"], 0) + 1
        return out


# ---------- running ----------

def _finish(job_id: int, state: str, error: str = "") -> None:
    db.execute(
        "UPDATE jobs SET state = ?, error = ?, "
        "finished_at = CURRENT_TIMESTAMP WHERE id = ?",
        (state, error or None, job_id),
    )
    if state in TERMINAL:
        _clear_staging(job_id)


def _clear_staging(job_id: int) -> None:
    """The uploads go when the job does.

    They are a copy of what somebody already has, and the result of reading
    them is in `content/`, so keeping them would be a second archive nobody
    is maintaining. A failure to remove is not a failure of the job.
    """
    try:
        shutil.rmtree(staging_dir(job_id), ignore_errors=True)
    except OSError:
        pass


def claim() -> Optional[dict]:
    """Take the oldest queued job, or None.

    Written as a conditional update rather than a read followed by a write,
    so that two workers would take two jobs rather than both taking one.
    """
    row = db.query_one(
        "SELECT id FROM jobs WHERE state = ? ORDER BY id LIMIT 1", (QUEUED,))
    if row is None:
        return None
    with db.cursor() as cur:
        cur.execute(
            "UPDATE jobs SET state = ?, started_at = CURRENT_TIMESTAMP "
            "WHERE id = ? AND state = ?",
            (RUNNING, row["id"], QUEUED),
        )
        if cur.rowcount == 0:
            return None
    return get(row["id"])


def run_job(job_id: int) -> str:
    """Run one job to its end and return the state it reached.

    Synchronous and callable on its own, which is what the tests use: a
    handler is ordinary code and should not need a thread to be exercised.
    """
    job = get(job_id)
    if job is None:
        raise ValueError(f"No job {job_id}")
    if job["state"] == QUEUED:
        db.execute("UPDATE jobs SET state = ?, started_at = CURRENT_TIMESTAMP "
                   "WHERE id = ?", (RUNNING, job_id))
        job = get(job_id)

    progress = Progress(job_id=job_id)
    try:
        _HANDLERS[job["kind"]](job, progress)
    except Refusal as exc:
        _finish(job_id, FAILED, str(exc))
        return FAILED
    except Exception as exc:
        # The traceback goes in the row rather than only to a log nobody
        # serves, which is the mistake `conversion.log` already makes: it is
        # written on every ingest and no route shows it.
        _finish(job_id, FAILED,
                f"{type(exc).__name__}: {exc}\n\n{traceback.format_exc()}")
        return FAILED
    state = CANCELLED if cancelled(job_id) else DONE
    _finish(job_id, state)
    return state


def recover() -> int:
    """Mark jobs the process died under, and return how many.

    A row left reading `running` with nothing advancing it is the state
    that reads as work still in hand when it is work that stopped. Called
    at app start, where it is one query.
    """
    rows = db.query_all("SELECT id FROM jobs WHERE state = ?", (RUNNING,))
    for row in rows:
        _finish(row["id"], INTERRUPTED,
                "The process stopped while this was running. What is listed "
                "below is what it had finished; the rest was not attempted.")
    # A `staging` row is an upload that never finished arriving, so there is
    # nothing to resume and nothing to report: it is dropped rather than
    # queued, because running a half-saved batch would ingest some of a
    # volume and call it the whole of one.
    half = db.query_all("SELECT id FROM jobs WHERE state = ?", (STAGING,))
    for row in half:
        _finish(row["id"], CANCELLED,
                "The upload did not finish, so this batch was never queued.")
    if db.query_one("SELECT id FROM jobs WHERE state = ? LIMIT 1", (QUEUED,)):
        start_worker()
        _wake.set()
    return len(rows) + len(half)


def _loop() -> None:
    while not _stopping.is_set():
        try:
            job = claim()
        except Exception:
            # A transient lock is not a reason for the queue to stop being
            # worked. Letting this out ends the thread and strands every
            # job behind it, which looks from the page like work that never
            # started rather than a worker that died.
            job = None
        if job is None:
            # Waiting on the event rather than polling, and with a timeout
            # rather than without: a wake-up that arrived while this thread
            # was between the claim and the wait would otherwise leave a
            # queued job sitting until something else woke it.
            _wake.wait(timeout=30)
            _wake.clear()
            continue
        try:
            run_job(job["id"])
        except Exception:
            # `run_job` records its own failures; this is the one above it,
            # where the recording itself went wrong.
            try:
                _finish(job["id"], FAILED, traceback.format_exc())
            except Exception:
                pass


def start_worker() -> Optional[threading.Thread]:
    """Start the worker if it is not already running. Idempotent."""
    global _worker
    if not WORKER_ENABLED:
        return None
    with _worker_lock:
        _stopping.clear()
        if _worker is not None and _worker.is_alive():
            return _worker
        _worker = threading.Thread(target=_loop, name="graphion-jobs",
                                   daemon=True)
        _worker.start()
        return _worker


def stop_worker(timeout: float = 5.0) -> None:
    """Ask the worker to stop after the job it is on. For tests.

    A daemon thread outliving the test that started it is the usual way a
    suite becomes intermittent, and this one holds a database path that the
    next test has moved.
    """
    global _worker
    _stopping.set()
    _wake.set()
    worker = _worker
    if worker is not None and worker.is_alive():
        worker.join(timeout)
    _worker = None


# ---------- the kinds ----------

@handler("ingest_batch")
def _ingest_batch(job: dict, progress: Progress) -> None:
    """A folder of chapter PDFs, through the ingest the CLI already runs.

    `ingest_volume.plan` reads what each file is from its name, drops the
    collected volume that every one of these folders ships beside its
    chapters, and orders them; `volume_furniture` finds the images that
    repeat across the batch and are therefore the series' own mark rather
    than figures; `ingest_one` does the rest. None of that is reimplemented
    here, because a batch taken in from a browser and one taken in from a
    terminal being the same ingest is the whole reason this is a job and
    not a second pipeline.
    """
    import ingest_volume

    staged = Path(job["staged_path"])
    facts = payload(job)
    journal = db.query_one("SELECT * FROM journals WHERE id = ?",
                           (job["journal_id"],))
    if journal is None:
        raise ValueError("The journal this batch was for no longer exists.")
    journal = dict(journal)

    chapters = ingest_volume.plan(staged, {}, facts.get("volume"))
    progress.plan(len(chapters))
    if not chapters:
        return

    furniture = ingest_volume.volume_furniture(chapters)
    by_source = ingest_volume.existing_sources(journal["id"])

    defaults = {"volume-title": facts.get("volume_title") or None,
                "volume": facts.get("volume"),
                "year": facts.get("year")}
    if facts.get("license"):
        # A volume's terms are a property of the volume, so these overwrite
        # whatever a chapter's own pages carried rather than filling a gap.
        # Left out entirely where the form said to keep each chapter's own,
        # which is the one case volume 1 of this series needs.
        defaults["license"] = facts["license"]
        defaults["license-url"] = facts.get("license_url")

    for chapter in chapters:
        if progress.cancelled:
            return
        if chapter.skip:
            progress.step(chapter.pdf.name, "skipped",
                          chapter.note or "not ingested")
            continue
        try:
            state, detail = ingest_volume.ingest_one(
                chapter, journal, defaults, bool(facts.get("replace")),
                by_source, facts.get("teacher_mode", "separate"), furniture)
        except Exception as exc:
            # One unopenable chapter is a finding about that chapter.
            # Stopping here would cost the rest of the batch its run.
            progress.step(chapter.pdf.name, "failed",
                          f"{type(exc).__name__}: {exc}")
            continue
        progress.step(chapter.pdf.name, state, detail)


@handler("validate")
def _validate(job: dict, progress: Progress) -> None:
    """verapdf, pa11y and epubcheck over a journal, recorded as it goes.

    This is the pass `validate_galleys.py` exists for, and the reason it
    was a script: each tool is a subprocess with a 120 second timeout, so
    118 articles is an hour at best. `app.py`'s corpus route has run only
    lint and the declaration since it was written, with a comment saying
    these belonged in a job runner.

    The script's own decisions are the script's. `TOOLS` says whether a
    tool is there and what to say when it is not, `to_do` says what is in
    the plan, and `run_one` hashes the file before the tool reads it,
    writes the report beside the galley and records the run. Nothing about
    validation is decided here.
    """
    import validate_galleys

    facts = payload(job)
    journal = db.query_one("SELECT * FROM journals WHERE id = ?",
                           (job["journal_id"],))
    if journal is None:
        raise ValueError("The journal this pass was for no longer exists.")

    asked = [k for k in facts.get("kinds") or validate_galleys.KINDS
             if k in validate_galleys.TOOLS]
    ready = [k for k in asked if validate_galleys.TOOLS[k]["available"]()]
    missing = [k for k in asked if k not in ready]

    if not ready:
        # The same answer `validate_galleys.main()` gives, and for the same
        # reason: a recorded run is the newest run for its kind, so a pass
        # with no tool would write "not checked" over verdicts that cost an
        # hour to get. A pass that could check nothing is not a pass.
        raise ValueError(
            "None of the requested tools is installed, so nothing was "
            "checked and nothing was recorded. "
            + "; ".join(f"{validate_galleys.TOOLS[k]['label']}: "
                        f"{validate_galleys.TOOLS[k]['install']}"
                        for k in asked))

    skip_current = bool(facts.get("skip_current", True))
    articles = validate_galleys.articles_for(journal["slug"])
    plan = [(article, kind)
            for article in articles
            for kind in ready
            if validate_galleys.to_do(article, kind, skip_current)]

    # Counted in the total, because a tool that is not installed is
    # something that happened to this pass and the first thing a reader
    # needs off the page. Left out of the total it would be a line nobody
    # looks at under a progress count that says everything is done.
    progress.plan(len(plan) + len(missing))
    for kind in missing:
        tool = validate_galleys.TOOLS[kind]
        progress.step(tool["label"], register.UNRUN,
                      f"not installed, so no {kind} verdict was recorded "
                      f"and none was overwritten: {tool['install']}")

    for article, kind in plan:
        if progress.cancelled:
            return
        try:
            level, note = validate_galleys.run_one(article, kind)
        except Exception as exc:
            progress.step(f"{kind}: {article['slug']}", "failed",
                          f"{type(exc).__name__}: {exc}")
            continue
        if level is None:
            # `run_one` says "no file" where the galley went between the
            # plan and the run. Owing a render is not failing a check.
            progress.step(f"{kind}: {article['slug']}", "skipped", note)
            continue
        progress.step(f"{kind}: {article['slug']}", level, note)


@handler("remediate_cartridge")
def _remediate_cartridge(job: dict, progress: Progress) -> None:
    """Screen, remediate and repack one course cartridge.

    Everything about what is changed, what is refused and what is proved is
    `repack`'s. This stages nothing of its own: it reads the upload, writes
    the result into `results_dir`, which outlives the job, and records a
    handful of summary items, because a cartridge has thousands of members
    and `Progress.step` rewrites its whole list on every call.
    """
    import repack

    facts = payload(job)
    carts = sorted(Path(job["staged_path"]).glob("*.imscc"))
    if not carts:
        raise ValueError("No cartridge was staged for this job.")
    out_dir = results_dir(job["id"])
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        report = repack.remediate_cartridge(
            carts[0], out_dir / "remediated.imscc",
            language=facts.get("language") or None,
            ocr=bool(facts.get("ocr")),
            tick=lambda done, total, _path: progress.tick(done, total),
            stop=lambda: progress.cancelled)
    except repack.Refusal as exc:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise Refusal(str(exc))
    except repack.Stopped:
        shutil.rmtree(out_dir, ignore_errors=True)
        return

    (out_dir / "report.json").write_text(repack.report_json(report),
                                         encoding="utf-8")
    (out_dir / "report.md").write_text(repack.render_markdown(report),
                                       encoding="utf-8")
    progress.tick(report.members, report.members)
    owed_pictures = []
    try:
        import pictures
        owed_pictures = pictures.find_pictures(out_dir / "remediated.imscc")
        pictures.save_pictures(out_dir, owed_pictures)
    except Exception as exc:
        # A queue that cannot be built must not cost the cartridge its
        # result: the remediation itself is done and verified.
        progress.step("Pictures to describe", "warn",
                      f"could not be listed: {type(exc).__name__}: {exc}")
    progress.step("Screened for student work", "pass",
                  "Nothing was found, so the cartridge was processed.")
    progress.step(
        "Text compared after writing",
        "pass" if report.holds else "fail",
        report.summary())
    for kind, count in sorted(report.totals_changed.items()):
        progress.step(f"Fixed: {kind}", "pass", f"{count}")
    if owed_pictures:
        progress.step(
            "Pictures to describe", "warn",
            f"{len(owed_pictures)} picture(s) need a description or a "
            f"decision from the author. They can be done from this page.")
    for item in report.worklist:
        progress.step(f"Still owed: {item['kind']}", "warn",
                      f"{item['count']}. {item['detail']}")


@handler("apply_descriptions")
def _apply_descriptions(job: dict, progress: Progress) -> None:
    """Write an author's descriptions into a copy of a remediated cartridge.

    Reads the queue the remediation left (`pictures.json`) and the author's
    decisions (`descriptions.json`) from that job's results, and writes a new
    cartridge beside them. Nothing is drafted here: only words a person typed
    are written, which is the whole point of the queue.
    """
    import pictures

    facts = payload(job)
    source = results_dir(int(facts["source_job"]))
    cartridge_path = source / "remediated.imscc"
    if not cartridge_path.is_file():
        raise ValueError("The remediated cartridge these descriptions were "
                         "for is no longer on the server.")
    owed = pictures.load_pictures(source) or []
    decisions = pictures.load_decisions(source)
    out_dir = results_dir(job["id"])
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        report = pictures.apply_descriptions(
            cartridge_path, out_dir / "described.imscc", owed, decisions,
            tick=lambda done, total, _path: progress.tick(done, total),
            stop=lambda: progress.cancelled)
    except pictures.Refusal as exc:
        shutil.rmtree(out_dir, ignore_errors=True)
        raise Refusal(str(exc))
    except pictures.Stopped:
        shutil.rmtree(out_dir, ignore_errors=True)
        return

    (out_dir / "described-report.md").write_text(
        pictures.render_markdown(report, owed, decisions), encoding="utf-8")
    progress.tick(report.members, report.members)
    progress.step("Descriptions written",
                  "pass" if not report.failed else "warn", report.summary())
    for failure in report.failed:
        progress.step(f"Could not write: {failure['member']}", "fail",
                      failure["reason"])
