"""What was checked, when, and against which bytes.

A check result on its own is a claim about an article at a moment, and the
moment is the part that went missing. `lint.run()` renders its results into
a page and discards them; the two validator reports land on disk beside the
galley with no date on them and nothing saying which version of the article
they describe. So "where does this journal stand" could only be answered by
opening every article in turn, and an accessibility conformance report,
which answers that question criterion by criterion with a date against it,
had nothing it could cite.

This module records each result against a hash of the file the check read.
That hash is the whole point of it, because it is what tells a stored pass
from a current one. A recorded pass whose hash no longer matches the file is
not a pass: it is a statement about content that has since changed, and the
rollup counts it as unknown rather than as done. A corpus view that folded
those in would report an archive conformant on the strength of checks that
ran before the content moved, which is the failure with no symptom; the
numbers would look better the longer the register went unrefreshed.

Three states are therefore kept apart from a result, and only one of them
means the question is answered:

    never     no run on record for this article and check
    absent    the file the check reads is not there to be checked
    stale     a run is on record against different bytes
    current   a run is on record against the bytes now on disk

A run is identified by `run_id` rather than reconstructed from the newest row
per check, because those differ as soon as the set of checks changes: a check
retired from `lint.DEFAULT_CHECKS` would otherwise keep reporting its last
finding forever, newest of its name and belonging to a run that is over.

The hash is taken once, before the check runs, which is exact for a single
writer and assumes the one gunicorn worker `deploy/entrypoint.sh` configures,
the same assumption the login limiter in `app.py` already makes.

Three kinds take a verdict from whoever ran the tool. The fourth, `pdfua`,
reads the galley itself and asks what it declares about its own conformance,
which is what `conversion._compile_typst`'s fallback used to say in a render
log and nowhere a count could reach.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence

import db

# The file each kind of check actually reads. A hash of anything else would
# date the result to the wrong thing: linting reads the Markdown source, and
# the two validators read a rendered galley, which can be older or newer than
# the source it came from.
CHECKED_FILE = {
    "lint": "article.md",
    "pdfua": "article.pdf",
    "verapdf": "article.pdf",
    "pa11y": "article.html",
}

KINDS = ("lint", "pdfua", "verapdf", "pa11y")

KIND_LABELS = {
    "lint": "Lint",
    "pdfua": "PDF/UA declared",
    "verapdf": "PDF/UA audited (verapdf)",
    "pa11y": "HTML audit (pa11y)",
}

# What ISO 14289-1 requires a conforming file to say about itself, read off
# the catalog and the XMP. Typst writes all five only when the standard is
# asked for, so a galley that went down `conversion._compile_typst`'s
# fallback path reads here as a missing identifier.
#
# The title is two fields and only one of them counts. Clause 5 reads
# `dc:title` in the XMP packet; the Info dictionary's `/Title` is a
# different entry, and six bound issues in this archive carried that one
# and failed the check for want of the other, which is why the summary
# below says so when it finds exactly that.
_DECLARATION = (
    ("tagged", "tagged",
     "Tagged: the file carries a structure tree.",
     "Untagged: no structure tree, so nothing above the text is marked up."),
    ("pdfua-identifier", "declared_ua_part",
     "Declares PDF/UA-1 (ISO 14289-1 clause 5).",
     "No declared PDF/UA conformance, so an audit has nothing to check "
     "the galley against."),
    ("document-title", "xmp_title",
     "Carries a document title in XMP (dc:title).",
     "No dc:title in XMP, which is the field clause 5 reads."),
    ("display-doc-title", "display_doctitle",
     "Opens showing the title rather than the filename (/DisplayDocTitle).",
     "No /DisplayDocTitle, so a reader is shown the filename (WCAG 2.4.2)."),
    ("document-language", "lang",
     "States a document language (/Lang).",
     "No document language, so a screen reader has to guess the voice "
     "(WCAG 3.1.1)."),
)

NEVER = "never"
ABSENT = "absent"
STALE = "stale"
CURRENT = "current"

# Worst first, which is the order a page should read them in.
_SEVERITY = {"fail": 0, "warn": 1, "pass": 2}


def _worst(levels: Iterable[str]) -> Optional[str]:
    present = [lv for lv in levels if lv in _SEVERITY]
    if not present:
        return None
    return min(present, key=lambda lv: _SEVERITY[lv])


# ---------- hashing ----------

def hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hash_file(path: Path) -> Optional[str]:
    """None where there is no file, which is a different answer from a hash
    of nothing: an article that was never rendered has no galley to audit,
    and reporting that as a failed audit would overstate what is owed."""
    try:
        return hash_bytes(Path(path).read_bytes())
    except (OSError, FileNotFoundError):
        return None


def hash_for(project_path, kind: str) -> Optional[str]:
    return hash_file(Path(project_path) / CHECKED_FILE[kind])


# ---------- writing ----------

@dataclass
class Finding:
    """One line of a recorded run. `lint.LintResult` maps onto this; so does
    a whole-tool verdict from a validator, which has one finding."""
    check_name: str
    level: str
    summary: str = ""
    details: list = field(default_factory=list)


def record(article_id: int, kind: str, findings: Sequence[Finding],
           content_hash: str) -> str:
    """Write one run and return its id.

    `content_hash` is passed in rather than read here, because the caller is
    the only one that knows which bytes the check saw. Hashing at this point
    would date the run to whenever the writing happened to occur.
    """
    if kind not in CHECKED_FILE:
        raise ValueError(f"unknown check kind: {kind}")
    if not content_hash:
        raise ValueError("a run has to name the bytes it ran against")
    run_id = uuid.uuid4().hex
    source_name = CHECKED_FILE[kind]
    with db.cursor() as cur:
        for f in findings:
            cur.execute(
                "INSERT INTO check_runs (article_id, run_id, kind, check_name, "
                "level, summary, details_json, source_name, content_hash) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (article_id, run_id, kind, f.check_name, f.level, f.summary,
                 json.dumps(list(f.details)), source_name, content_hash),
            )
    return run_id


def record_lint(article_id: int, project_path, results: Iterable,
                content_hash: Optional[str] = None) -> Optional[str]:
    """Record a `lint.run()` result set. Returns None where `article.md` is
    gone, since there would be nothing to date the run to.

    A caller that hashed the file before running the checks passes that hash
    in; hashing here instead would date the run to whenever the writing
    happened, which is after the reading.
    """
    content_hash = content_hash or hash_for(project_path, "lint")
    if content_hash is None:
        return None
    findings = [Finding(r.name, r.level, r.summary, list(r.details))
                for r in results]
    return record(article_id, "lint", findings, content_hash)


def record_pdfua(article_id: int, project_path,
                 content_hash: Optional[str] = None) -> Optional[str]:
    """Record what the rendered galley declares about its own conformance.

    This is the question `conversion._compile_typst`'s fallback used to
    leave in a log line and nowhere else. Typst validates PDF/UA rather
    than merely declaring it, so one undescribed figure or one bare
    equation aborts the compile, and the fallback renders the galley
    without the standard so that an editor never loses a galley to this.
    What ships is then readable and unconformant, and the only trace was a
    line in the render log that nothing counted and no page totalled.

    Reading the artifact rather than catching the compile answers more than
    the fallback does. A galley rendered before any of this existed states
    its conformance as plainly as one rendered this morning, so the archive
    can be answered for without re-rendering 115 chapters; and the failure
    is caught however it arrived, which matters, because the six issue
    front matters that silently lost the standard did so for want of a
    title rather than for want of alt text.

    Unlike every other kind here, this one reads the file itself instead of
    taking a verdict from a caller, so it hashes and reads in one place and
    there is no gap for the bytes to move in. The others take the hash from
    whoever ran the check, because only that caller knows which bytes it
    saw.
    """
    content_hash = content_hash or hash_for(project_path, "pdfua")
    if content_hash is None:
        return None
    # Imported here rather than at the top: only this kind needs it, and it
    # pulls pdfplumber in behind it.
    import assess

    read = assess.read_declaration(Path(project_path) / CHECKED_FILE["pdfua"])
    if not read.readable:
        # A file pypdf cannot open has not failed a conformance check; it
        # has not had one. Same rule as a validator missing from PATH.
        return record(article_id, "pdfua",
                      [Finding("pdfua", "warn", f"Not read: {read.error}")],
                      content_hash)

    findings = []
    for name, attr, ok, bad in _DECLARATION:
        if getattr(read, attr):
            findings.append(Finding(name, "pass", ok))
        elif name == "document-title" and read.info_title:
            findings.append(Finding(name, "fail", bad + " The Info dictionary "
                                    "carries a title; that is a different field."))
        else:
            findings.append(Finding(name, "fail", bad))

    # An article with `teacher-resources: separate` renders two galleys, and
    # a second galley that quietly lost the standard is the same hole as the
    # first. It is carried in this run rather than given one of its own,
    # which leaves the run dated to `article.pdf` alone; `render_all` writes
    # the two together, so in practice they move at once, and the soft edge
    # is worth more than leaving the teacher galley unchecked.
    teacher = Path(project_path) / "teacher-resources.pdf"
    if teacher.exists():
        t = assess.read_declaration(teacher)
        if not t.readable:
            findings.append(Finding(
                "teacher-galley", "warn",
                f"teacher-resources.pdf could not be read: {t.error}"))
        else:
            missing = [name for name, attr, _ok, _bad in _DECLARATION
                       if not getattr(t, attr)]
            if missing:
                findings.append(Finding(
                    "teacher-galley", "fail",
                    "teacher-resources.pdf does not declare: "
                    + ", ".join(missing) + "."))
            else:
                findings.append(Finding(
                    "teacher-galley", "pass",
                    "teacher-resources.pdf declares the same."))

    return record(article_id, "pdfua", findings, content_hash)


def record_verapdf(article_id: int, project_path, passed: bool,
                   report: dict,
                   content_hash: Optional[str] = None) -> Optional[str]:
    content_hash = content_hash or hash_for(project_path, "verapdf")
    if content_hash is None:
        return None
    error = (report or {}).get("error")
    if error:
        # The tool could not speak, which is not the galley failing. Recording
        # it as a fail would put a conformance verdict on record that nothing
        # checked.
        finding = Finding("verapdf", "warn", f"Not checked: {error}")
    elif passed:
        finding = Finding("verapdf", "pass", "Declared PDF/UA-1 and verapdf agrees.")
    else:
        finding = Finding("verapdf", "fail", "verapdf reports the galley is not PDF/UA-1.")
    return record(article_id, "verapdf", [finding], content_hash)


def record_pa11y(article_id: int, project_path, passed: bool,
                 issues: Sequence[dict],
                 content_hash: Optional[str] = None) -> Optional[str]:
    content_hash = content_hash or hash_for(project_path, "pa11y")
    if content_hash is None:
        return None
    issues = list(issues or [])
    first_error = issues[0].get("error") if issues and isinstance(issues[0], dict) else None
    if first_error:
        finding = Finding("pa11y", "warn", f"Not checked: {first_error}")
    elif passed:
        finding = Finding("pa11y", "pass", "pa11y found no issues.")
    else:
        errors = sum(1 for i in issues if i.get("type") == "error")
        warns = sum(1 for i in issues if i.get("type") == "warning")
        level = "fail" if errors else "warn"
        finding = Finding(
            "pa11y", level,
            f"pa11y reports {errors} error(s) and {warns} warning(s).",
            [str(i.get("message", ""))[:300] for i in issues[:20]],
        )
    return record(article_id, "pa11y", [finding], content_hash)


# ---------- reading ----------

@dataclass
class Recorded:
    check_name: str
    level: str
    summary: str
    details: list
    ran_at: str
    content_hash: str


def latest_run(article_id: int, kind: str) -> List[Recorded]:
    """Every finding of the newest run, and nothing from any older one.

    Matching the newest row per check name instead would keep a retired
    check's last finding on the page for good: it is the newest of its name,
    and the run it belonged to is over.
    """
    rows = db.query_all(
        "SELECT check_name, level, summary, details_json, ran_at, content_hash "
        "FROM check_runs WHERE article_id = ? AND kind = ? AND run_id = ("
        "  SELECT run_id FROM check_runs WHERE article_id = ? AND kind = ? "
        "  ORDER BY id DESC LIMIT 1)",
        (article_id, kind, article_id, kind),
    )
    out = []
    for r in rows:
        try:
            details = json.loads(r["details_json"] or "[]")
        except json.JSONDecodeError:
            details = []
        out.append(Recorded(r["check_name"], r["level"], r["summary"] or "",
                            details, r["ran_at"], r["content_hash"]))
    out.sort(key=lambda r: (_SEVERITY.get(r.level, 99), r.check_name))
    return out


@dataclass
class Standing:
    """Where one kind of check stands for one article."""
    kind: str
    state: str
    level: Optional[str] = None
    counts: Dict[str, int] = field(default_factory=dict)
    ran_at: Optional[str] = None
    recorded_hash: Optional[str] = None
    current_hash: Optional[str] = None
    findings: List[Recorded] = field(default_factory=list)

    @property
    def settled(self) -> bool:
        """True only where a run is on record against the bytes on disk. Every
        count that claims to say how an archive stands is built on this."""
        return self.state == CURRENT

    @property
    def clean(self) -> bool:
        return self.settled and self.level == "pass"

    @property
    def tone(self) -> str:
        """How a page should colour this. Decided here rather than in the
        template, so there is one answer to what counts as settled: anything
        not current reads as unknown, whatever an older run said about it."""
        if not self.settled:
            return "unknown"
        return {"pass": "good", "warn": "warn", "fail": "bad"}.get(
            self.level or "", "unknown")

    @property
    def label(self) -> str:
        if self.state == NEVER:
            return "not checked"
        if self.state == ABSENT:
            return f"no {CHECKED_FILE[self.kind]}"
        if self.state == STALE:
            # Short, because it is read in a table cell beside three
            # others. What it means is spelled out in `Rollup.note()`,
            # which the page carries under the totals.
            return "older version"
        return {"pass": "clean", "warn": "warnings", "fail": "failing"}.get(
            self.level or "", "checked")


def standing(article_id: int, project_path, kinds: Sequence[str] = KINDS
             ) -> Dict[str, Standing]:
    out = {}
    # What a galley declares and whether the declaration holds up are two
    # kinds reading one PDF, so the file is hashed once per call instead of
    # once per kind. Within a single call there is no question of the bytes
    # differing between the two readings, and over a journal page it is the
    # difference between hashing the archive's galleys once and twice.
    hashes: Dict[str, Optional[str]] = {}
    for kind in kinds:
        source = CHECKED_FILE[kind]
        if source not in hashes:
            hashes[source] = hash_file(Path(project_path) / source)
        current = hashes[source]
        findings = latest_run(article_id, kind)
        if current is None:
            out[kind] = Standing(kind, ABSENT,
                                 recorded_hash=findings[0].content_hash if findings else None)
        elif not findings:
            out[kind] = Standing(kind, NEVER, current_hash=current)
        elif findings[0].content_hash != current:
            out[kind] = Standing(kind, STALE, ran_at=findings[0].ran_at,
                                 recorded_hash=findings[0].content_hash,
                                 current_hash=current)
        else:
            counts = {}
            for f in findings:
                counts[f.level] = counts.get(f.level, 0) + 1
            out[kind] = Standing(
                kind, CURRENT, level=_worst(f.level for f in findings),
                counts=counts, ran_at=findings[0].ran_at,
                recorded_hash=findings[0].content_hash, current_hash=current,
                findings=findings,
            )
    return out


# ---------- the corpus view ----------

@dataclass
class KindRollup:
    kind: str
    clean: int = 0
    warn: int = 0
    fail: int = 0
    stale: int = 0
    never: int = 0
    absent: int = 0

    @property
    def settled(self) -> int:
        return self.clean + self.warn + self.fail

    @property
    def total(self) -> int:
        return self.settled + self.stale + self.never + self.absent

    @property
    def unanswered(self) -> int:
        """Articles this register cannot speak for. Kept separate from the
        failures on purpose: the two are both work, and only one of them is
        work anybody has looked at."""
        return self.stale + self.never + self.absent


@dataclass
class Rollup:
    articles: int = 0
    kinds: Dict[str, KindRollup] = field(default_factory=dict)
    rows: list = field(default_factory=list)

    def note(self) -> str:
        """What the totals above do not cover, said rather than left out."""
        return (
            "A result counts here only where a run is on record against the "
            "bytes now on disk. One taken against an older version is listed "
            "as such and not as a pass, since the content has moved under it. "
            "How many figures carry text as a picture is in neither column; "
            "that is kept by hand in each article's images-of-text field, and "
            "nothing but looking settles it. A bound issue.pdf is not an "
            "article and is not counted here either; what a merge could and "
            "could not carry is reported as the issue is assembled."
        )


def rollup(articles: Iterable[dict], kinds: Sequence[str] = KINDS) -> Rollup:
    """Fold per-article standings into one statement for a journal or issue.

    `articles` are rows carrying at least `id` and `project_path`.
    """
    out = Rollup(kinds={k: KindRollup(k) for k in kinds})
    for article in articles:
        out.articles += 1
        st = standing(article["id"], article["project_path"], kinds)
        for kind in kinds:
            s = st[kind]
            bucket = out.kinds[kind]
            if s.state == CURRENT:
                if s.level == "fail":
                    bucket.fail += 1
                elif s.level == "warn":
                    bucket.warn += 1
                else:
                    bucket.clean += 1
            elif s.state == STALE:
                bucket.stale += 1
            elif s.state == ABSENT:
                bucket.absent += 1
            else:
                bucket.never += 1
        out.rows.append({"article": article, "standing": st})
    return out


__all__ = [
    "CHECKED_FILE", "KINDS", "KIND_LABELS",
    "NEVER", "ABSENT", "STALE", "CURRENT",
    "Finding", "Recorded", "Standing", "KindRollup", "Rollup",
    "hash_bytes", "hash_file", "hash_for",
    "record", "record_lint", "record_pdfua", "record_verapdf", "record_pa11y",
    "latest_run", "standing", "rollup",
]
