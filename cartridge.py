"""Read an IMS Common Cartridge. Writes nothing, anywhere, ever.

A `.imscc` is a zip holding a course: HTML pages under `wiki_content/`,
files under `web_resources/`, Canvas's own design XML under
`course_settings/`, QTI banks, discussion topics and LTI links. Canvas,
D2L and Moodle all export the format with their own additions, so the
manifest is read first and a vendor directory is treated as enrichment
that may not be there.

The point of this module is the pass that has to happen **before** any
audit: whether the cartridge carries student work. Everything else here
exists to make that one answerable.

**It reads members out of the zip rather than extracting.** `assess.py`
keeps its no-write contract because a pass over a stranger's folder has
to leave the folder alone, and this is the same promise one level down:
nothing is unpacked to disk, so a screen that stops on student data
leaves nothing behind to clean up. A caller that genuinely needs files
on disk can extract afterwards, having been told it is safe to.

**The screen reports containers, not content.** It will say that four
caption transcripts are present and roughly how long they are; it will
not quote them. A tool that answers "is there student data here?" by
printing the student data is not a safeguard. It also never tries to
decide whether a name is a student's: that is guesswork with a confident
voice, and the honest output is "this is the kind of thing student work
arrives in, go and look".
"""
from __future__ import annotations

import re
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

# The namespace every Common Cartridge manifest declares, in the versions
# this has been pointed at. Matched loosely, because 1.1, 1.2 and 1.3 each
# bump it and nothing here depends on which.
_MANIFEST = "imsmanifest.xml"
_CC_NS = re.compile(r"imscc_v1p\d|imscp_v1p\d")

# Where each vendor puts things. Read off the manifest where possible; these
# are the fallbacks for an export whose manifest is thin.
HTML_DIRS = ("wiki_content", "web_resources")
SETTINGS_DIR = "course_settings"

# What a file is, for the inventory. Deliberately coarse: the audit cares
# which reader to hand a member to, not what the extension is called.
KINDS = {
    ".html": "page", ".htm": "page", ".xhtml": "page",
    ".pdf": "pdf",
    ".docx": "document", ".doc": "document", ".rtf": "document",
    ".pptx": "slides", ".ppt": "slides",
    ".xlsx": "spreadsheet", ".xls": "spreadsheet", ".csv": "spreadsheet",
    ".mp4": "media", ".mov": "media", ".m4v": "media", ".avi": "media",
    ".mp3": "media", ".m4a": "media", ".wav": "media",
    ".vtt": "captions", ".srt": "captions",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".gif": "image",
    ".svg": "image", ".webp": "image", ".bmp": "image",
    ".xml": "metadata", ".qti": "quiz",
}

# Paths that name student work outright. Checked, but not relied on: the
# four cartridges that turned out to carry a student's recorded reflection
# matched none of these, because the transcript was inside
# `course_settings/media_tracks.xml` under an ordinary name. A screen that
# only reads paths finds only the carelessly named.
_STUDENT_PATHS = re.compile(
    r"submission|gradebook|grade_export|enrollment|roster|users\.xml"
    r"|student_|_grades|attendance", re.IGNORECASE)

# Fields Canvas writes when it is describing a person rather than a course.
_STUDENT_FIELDS = re.compile(
    r"<(user_id|user_name|user_login|sis_user_id|anonymous_id|"
    r"submitted_at|submission_type|workflow_state_user)\b", re.IGNORECASE)

# A cue line, in either WebVTT or SubRip. Counted to size a transcript
# without reading one.
_CUE = re.compile(r"\d\d:\d\d:\d\d[.,]\d{3}\s*--")


@dataclass
class Finding:
    """One reason not to hand this cartridge on, or to look first."""

    kind: str
    where: str
    count: int = 0
    detail: str = ""


@dataclass
class Screening:
    """What the screen found. Empty is the answer you want."""

    findings: list = field(default_factory=list)
    read: int = 0
    error: str = ""

    @property
    def clear(self) -> bool:
        """Whether this cartridge can go on to be audited.

        An unreadable cartridge is not clear: nothing was screened, and a
        pass that could not look is not a pass that found nothing. Same
        rule `register.UNRUN` exists for.
        """
        return not self.findings and not self.error

    def of_kind(self, kind: str) -> list:
        return [f for f in self.findings if f.kind == kind]


@dataclass
class Member:
    """One file inside the cartridge."""

    path: str
    size: int

    @property
    def name(self) -> str:
        return self.path.rsplit("/", 1)[-1]

    @property
    def kind(self) -> str:
        suffix = Path(self.name).suffix.lower()
        return KINDS.get(suffix, "other")


class Cartridge:
    """An open cartridge. Reads members; never writes or extracts."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self.zip = zipfile.ZipFile(self.path)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False

    def close(self) -> None:
        self.zip.close()

    def members(self) -> Iterator[Member]:
        for info in self.zip.infolist():
            if info.is_dir():
                continue
            yield Member(path=info.filename, size=info.file_size)

    def read(self, path: str) -> bytes:
        return self.zip.read(path)

    def text(self, path: str) -> str:
        """A member as text, replacing what will not decode.

        Course material arrives in whatever encoding somebody's editor
        saved, and a screen that raises on one bad byte screens nothing.
        """
        return self.read(path).decode("utf-8", "replace")

    def has(self, path: str) -> bool:
        try:
            self.zip.getinfo(path)
            return True
        except KeyError:
            return False

    @property
    def manifest(self) -> Optional[str]:
        return self.text(_MANIFEST) if self.has(_MANIFEST) else None

    def looks_like_a_cartridge(self) -> bool:
        """Whether this is a Common Cartridge rather than any other zip.

        The manifest is the only thing every vendor's export agrees on, so
        it is what is tested. A zip of PDFs someone renamed is not an
        error worth a traceback; it is a thing to say plainly.
        """
        text = self.manifest
        return bool(text and _CC_NS.search(text))

    def inventory(self) -> dict:
        """How many of each kind, which is the "what is in here" answer."""
        counts: dict = {}
        for member in self.members():
            counts[member.kind] = counts.get(member.kind, 0) + 1
        return counts


def open_cartridge(path) -> Cartridge:
    return Cartridge(Path(path))


# ---------- the screen ----------

def screen(cartridge: Cartridge) -> Screening:
    """Whether this cartridge carries student work.

    Run before anything else. A course export is whatever the instructor
    chose to include, and if that is student names, posts, recordings or
    grades, it is material that should not be sitting on a third party's
    disk at all, let alone being audited and sent back.

    Reports the container and its size, never its contents.
    """
    found: list = []
    read = 0

    for member in cartridge.members():
        read += 1
        if _STUDENT_PATHS.search(member.path):
            found.append(Finding(
                kind="named-for-student-work",
                where=member.path,
                detail="the path names student work, grades or people"))

    # Caption transcripts. These are the ones that matter, and the ones a
    # path check cannot see: Canvas keeps them inline in
    # `course_settings/media_tracks.xml` rather than as `.vtt` files, so a
    # cartridge can read as having no captions at all while carrying a
    # full transcript of somebody speaking. A caption transcribes whoever
    # is talking, so where the media is student work, this is a recording
    # of a student, in text, with their name in it if they introduced
    # themselves.
    for member in cartridge.members():
        if member.name.lower() != "media_tracks.xml":
            continue
        body = cartridge.text(member.path)
        tracks = body.count("<track")
        if not tracks:
            continue
        found.append(Finding(
            kind="caption-transcript",
            where=member.path,
            count=tracks,
            detail=(f"{tracks} transcript(s), about {len(_CUE.findall(body))} "
                    f"cues. Captions transcribe whoever is speaking, so if "
                    f"any of this media is student work this is a recording "
                    f"of a student in text. Look before sending it on.")))

    # Fields Canvas writes when it is describing a person. Counted per
    # file rather than per match, because one submissions export would
    # otherwise read as thousands of findings.
    for member in cartridge.members():
        if member.kind not in ("metadata", "quiz"):
            continue
        hits = _STUDENT_FIELDS.findall(cartridge.text(member.path))
        if hits:
            found.append(Finding(
                kind="person-fields",
                where=member.path,
                count=len(hits),
                detail=("names fields Canvas writes about people rather "
                        "than about course design: "
                        + ", ".join(sorted({h.lower() for h in hits})[:6]))))

    return Screening(findings=found, read=read)


def screen_file(path) -> Screening:
    """Open, screen and close. Returns a Screening even for a bad file."""
    try:
        with open_cartridge(path) as cartridge:
            if not cartridge.looks_like_a_cartridge():
                return Screening(
                    error="No Common Cartridge manifest; this is a zip of "
                          "something, but not a course export.")
            return screen(cartridge)
    except zipfile.BadZipFile:
        return Screening(error="Not a zip file, or the zip is damaged.")
    except OSError as exc:
        return Screening(error=f"Could not be opened: {exc}")
