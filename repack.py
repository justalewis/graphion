"""Remediate a whole cartridge and hand back what was done.

R7 of `docs/cartridge-audit.md`, and the stage that turns the pieces
before it into something deliverable: screen the cartridge for student
work, fix every page and PDF mechanically, write a new cartridge, and
produce a change log and a worklist of what is still owed.

**Four decisions here are the product, not the plumbing.**

*It screens first and refuses.* A cartridge carrying student work is not
remediated, not kept and not partly processed: `Refusal` carries what was
found, by container and never by content, and nothing is written. The
refusal is also the only place the screen's findings are surfaced to a
person, so it names what to look at.

*It never writes a file it could not prove changed no words.* Each
changed page or PDF is compared before and after, and a fix that moved a
word is dropped for that file, which is delivered exactly as it arrived
and listed in `text_moved`. One bad page does not cost the cartridge its
run, and it does not ship a reworded course either.

*It verifies what it wrote, not what it intended.* After the zip is
closed it is reopened: integrity checked, the member names compared with
the source, every untouched member compared by CRC, and every changed
member's text compared again from the bytes on disk. A check run on the
in-memory result would pass with a zip that fails to write properly.

*Nothing is renamed.* The manifest is copied through untouched and every
member keeps its path, its date and its compression, so every id and
every reference inside the cartridge still points at the thing it
pointed at. A new file is not added either: a member the manifest does
not list is the sort of thing an importer either ignores or chokes on,
and the change log lives beside the cartridge.

**What this is not.** Importing the result into a live course does not
replace anything: Canvas creates new pages with new ids and orphans every
assignment, module item and gradebook column attached to the old ones.
The report says so on its first line. It is right for a fresh shell, a
Commons package or an archival copy, and for a course being taught the
changes are applied item by item by the author.
"""
from __future__ import annotations

import json
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional

import cartridge
import invariance
import remediate

HTML_SUFFIXES = (".html", ".htm")

# A worklist names at most this many files per kind. A cartridge with
# 2,000 untitled frames needs the count and a place to start, not a list
# nobody will read, and the full detail is in the per-file log.
WORKLIST_FILES = 200

# Said first, in every report, because it is the thing most likely to
# cause real damage if it is missed.
IMPORT_WARNING = (
    "Importing this into a course that is already being taught does not "
    "replace anything: Canvas creates new pages with new ids and orphans "
    "every assignment, module item and gradebook column attached to the "
    "old ones. This cartridge is right for a fresh shell, a Commons "
    "package, an archival copy or a course being handed on. For a live "
    "course the changes have to be applied item by item by somebody with "
    "access, and the change log below is the list to work from.")


class Refusal(Exception):
    """The cartridge was not processed, and `message` says why."""


class Stopped(Exception):
    """Cancelled between members. Nothing is left behind."""


@dataclass
class FileRecord:
    path: str
    kind: str
    outcome: str
    changes: list = field(default_factory=list)
    owed: list = field(default_factory=list)
    note: str = ""


@dataclass
class Report:
    source: str
    language: Optional[str]
    members: int = 0
    changed: int = 0
    identical: int = 0
    verified_chars: int = 0
    files: list = field(default_factory=list)
    text_moved: list = field(default_factory=list)
    unread: list = field(default_factory=list)
    totals_changed: dict = field(default_factory=dict)
    totals_owed: dict = field(default_factory=dict)
    worklist: list = field(default_factory=list)
    verified: bool = False
    warning: str = IMPORT_WARNING

    @property
    def holds(self) -> bool:
        """Whether not a word moved, in what was actually written."""
        return self.verified and not self.text_moved_in_output

    text_moved_in_output: list = field(default_factory=list)

    def summary(self) -> str:
        said = (f"{self.changed} file(s) changed and {self.identical} left "
                f"byte for byte as they arrived, of {self.members}. "
                f"{self.verified_chars:,} characters of text compared "
                f"after writing; "
                f"{len(self.text_moved_in_output)} changed.")
        if self.text_moved:
            said += (f" {len(self.text_moved)} fix(es) were dropped because "
                     f"they would have moved a word, and those files are "
                     f"delivered unchanged.")
        if self.unread:
            said += (f" {len(self.unread)} file(s) hold text this cannot "
                     f"read and are not covered by that check.")
        return said


def _record(path: str, kind: str, result) -> FileRecord:
    return FileRecord(
        path=path, kind=kind,
        outcome="changed" if result.changed else "unchanged",
        changes=[asdict(c) for c in result.changes],
        owed=[asdict(o) for o in result.owed])


def _fixer(path: str):
    suffix = Path(path).suffix.lower()
    if suffix in HTML_SUFFIXES:
        return "page", remediate.fix_html
    if suffix == ".pdf":
        return "pdf", remediate.fix_pdf
    return None, None


def remediate_cartridge(
        src, dst, language: Optional[str] = None,
        tick: Optional[Callable] = None,
        stop: Optional[Callable] = None) -> Report:
    """Screen, remediate and write `dst`. Raises `Refusal` or `Stopped`.

    `language` is the course's, stated by the caller and never guessed.
    `tick(done, total, path)` is called as members are handled and `stop()`
    is asked between them, so a job can report progress and be cancelled.
    """
    src, dst = Path(src), Path(dst)
    screening = cartridge.screen_file(src)
    if screening.error:
        raise Refusal(screening.error)
    if not screening.clear:
        found = "; ".join(f"{f.kind} in {f.where}" for f in screening.findings)
        raise Refusal(
            "This cartridge carries what looks like student work, so it "
            "was not processed and nothing was kept: " + found + ". Export "
            "the course again without media and without student content, "
            "or remove those files yourself, and send it again.")

    partial = dst.with_name(dst.name + ".partial")
    report = Report(source=src.name, language=language)
    results = []
    changed_paths: list = []
    originals_text: dict = {}

    try:
        with zipfile.ZipFile(src) as source, \
                zipfile.ZipFile(partial, "w", allowZip64=True) as out:
            infos = source.infolist()
            report.members = len(infos)
            for index, info in enumerate(infos):
                if stop and stop():
                    raise Stopped()
                if tick:
                    tick(index, len(infos), info.filename)

                data = b"" if info.is_dir() else source.read(info.filename)
                kind, fixer = _fixer(info.filename)
                new_data = data

                if fixer is not None and not info.is_dir():
                    result = fixer(data, language)
                    record = _record(info.filename, kind, result)
                    if result.error:
                        record.outcome = "unreadable"
                        record.note = result.error
                    elif result.changed:
                        # The guarantee, per file: a fix that moved a word
                        # is dropped and the file ships as it arrived.
                        was = invariance.text_of(info.filename, data)
                        now = invariance.text_of(info.filename, result.data)
                        if was is None or was != now:
                            report.text_moved.append(info.filename)
                            record.outcome = "dropped"
                            record.changes = []
                            record.note = ("the fix would have changed the "
                                           "text of this file, so it was not "
                                           "applied")
                        else:
                            new_data = result.data
                            changed_paths.append(info.filename)
                            originals_text[info.filename] = was
                    report.files.append(record)
                    results.append(result if record.outcome == "changed"
                                   else remediate.Result(data=data,
                                                         owed=result.owed))

                # Each entry keeps its own name, date and compression, so
                # nothing the manifest points at moves.
                entry = zipfile.ZipInfo(info.filename,
                                        date_time=info.date_time)
                entry.compress_type = info.compress_type
                entry.external_attr = info.external_attr
                entry.comment = info.comment
                out.writestr(entry, new_data)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    _verify(src, partial, changed_paths, originals_text, report)
    if not report.verified:
        partial.unlink(missing_ok=True)
        raise Refusal("The cartridge that was written did not pass its own "
                      "checks, so it was discarded: " + report.summary())
    partial.replace(dst)

    folded = remediate.summarise(results)
    report.totals_changed = folded["changed"]
    report.totals_owed = folded["owed"]
    report.changed = len(changed_paths)
    report.identical = report.members - report.changed
    report.worklist = _worklist(report.files)
    report.unread = _unread(src)
    return report


def _verify(src: Path, written: Path, changed: list, originals: dict,
            report: Report) -> None:
    """Check what is on disk, not what was intended."""
    try:
        with zipfile.ZipFile(src) as a, zipfile.ZipFile(written) as b:
            if b.testzip() is not None:
                return
            if a.namelist() != b.namelist():
                return
            changed_set = set(changed)
            for info in a.infolist():
                if info.is_dir():
                    continue
                new = b.getinfo(info.filename)
                if info.filename in changed_set:
                    now = invariance.text_of(info.filename,
                                             b.read(info.filename))
                    if now != originals.get(info.filename):
                        report.text_moved_in_output.append(info.filename)
                    else:
                        report.verified_chars += len(now or "")
                elif new.CRC != info.CRC:
                    # An untouched member that is not byte-identical is a
                    # defect in this module, whatever it is.
                    return
        report.verified = True
    except Exception:
        report.verified = False


def _unread(src: Path) -> list:
    """Files holding text the proof cannot read, so it says so."""
    try:
        with cartridge.open_cartridge(src) as cart:
            pairs = [(m.path, b"") for m in cart.members()]
        return invariance.unreadable(pairs)
    except Exception:
        return []


def _worklist(files: list) -> list:
    """What is still owed, by kind, with somewhere to start."""
    by_kind: dict = {}
    for record in files:
        for owed in record.owed:
            entry = by_kind.setdefault(
                owed["kind"], {"kind": owed["kind"], "count": 0,
                               "detail": owed["detail"], "files": []})
            entry["count"] += owed["count"]
            if len(entry["files"]) < WORKLIST_FILES:
                entry["files"].append(record.path)
    return sorted(by_kind.values(), key=lambda e: -e["count"])


def render_markdown(report: Report) -> str:
    """The change log and worklist as something a person reads."""
    lines = [f"# Accessibility remediation of {report.source}", "",
             f"> {report.warning}", "", "## What was checked", "",
             report.summary(), ""]
    if report.language:
        lines += [f"The course language was given as `{report.language}`.", ""]
    else:
        lines += ["No course language was given, so none was written. A "
                  "guessed language is read aloud in the wrong accent.", ""]

    lines += ["## What was changed", ""]
    if report.totals_changed:
        for kind, count in sorted(report.totals_changed.items()):
            lines.append(f"- {kind}: {count}")
    else:
        lines.append("Nothing needed changing.")
    lines.append("")

    lines += ["## What is still owed", "",
              "These need a person. Each is something this pass found and "
              "deliberately did not fix.", ""]
    if not report.worklist:
        lines.append("Nothing was found that this pass could not fix.")
    for item in report.worklist:
        lines += [f"### {item['kind']} ({item['count']})", "",
                  item["detail"], ""]
        for path in item["files"][:25]:
            lines.append(f"- `{path}`")
        extra = len(item["files"]) - 25
        if extra > 0:
            lines.append(f"- and {extra} more listed in the JSON report")
        lines.append("")

    if report.text_moved:
        lines += ["## Fixes that were dropped", "",
                  "These files are delivered exactly as they arrived, "
                  "because the fix would have changed a word.", ""]
        lines += [f"- `{p}`" for p in report.text_moved] + [""]

    if report.unread:
        lines += ["## Not covered by the check that no word moved", "",
                  "These hold text this cannot read, so it was neither "
                  "changed nor proved unchanged.", ""]
        lines += [f"- `{p}`" for p in report.unread[:50]] + [""]
    return "\n".join(lines)


def report_json(report: Report) -> str:
    data = asdict(report)
    data["holds"] = report.holds
    return json.dumps(data, indent=2)
