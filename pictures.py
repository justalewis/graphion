"""Find the pictures a course owes a description, and write the author's words.

R6 of `docs/cartridge-audit.md`. Everything before this reports a picture
with no description and goes no further, because a description is words
about the author's own material and nobody else knows what the picture is
for. This is where the author supplies them: the pictures a remediation
found are queued, the author writes a description or marks the picture
decorative, and this writes exactly that, and nothing else, into the one
attribute that holds it.

**It writes only what a person typed.** There is no drafting step. A
description produced by a machine is present, so no checker flags it, and it
is often wrong: one real file reads "A diagram of a diagram of a diagram".
That is why Microsoft's generated text is counted as owed review and not as
described, and a tool that wrote its own would be producing more of exactly
that. An optional drafting service would send the author's images to an
outside company, which is a decision for them and not a default.

**It edits one attribute and leaves every other byte alone.** A web page is
parsed and written back by the same serialiser the other fixes use. A Word or
PowerPoint file is a zip inside the cartridge, and round-tripping it through
a library can silently drop comments, tracked changes and objects the library
does not model, so the one XML part that holds the picture is edited as text,
in place, and every other part of the file keeps its bytes. The edit is
located by the picture's own `id` and `name`, so a file that does not look
the way the finder saw it is left alone and reported, not guessed at.

**Nothing ships that moved a word.** Each edited file's text is compared
before and after, and the written cartridge is reopened and checked again:
every untouched member by CRC, every edited one by text, and every untouched
part inside an edited Office file by CRC.
"""
from __future__ import annotations

import io
import json
import posixpath
import re
import zipfile
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, Optional
from urllib.parse import unquote
from xml.sax.saxutils import escape as _escape

import invariance
import remediate

_A = "http://schemas.openxmlformats.org/drawingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_WP = "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing"
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_P = "http://schemas.openxmlformats.org/presentationml/2006/main"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS = {"a": _A, "r": _R, "wp": _WP, "w": _W, "p": _P}

# What an author may choose for a picture.
DESCRIBE, DECORATIVE, KEEP, SKIP = "describe", "decorative", "keep", "skip"
ACTIONS = (DESCRIBE, DECORATIVE, KEEP, SKIP)

# A picture's state, from what it carries now. Only the first two are queued.
MISSING, MACHINE, OK, MARKED_DECORATIVE = (
    "missing", "machine-written", "described", "decorative")
QUEUED_STATES = (MISSING, MACHINE)

# Long enough for a real description of a complex figure and short enough
# that a pasted paragraph is noticed. A description is read aloud with no way
# back, so length is a cost to a listener.
MAX_DESCRIPTION = 1000

# Previews are served from the cartridge, so only formats a browser draws
# without executing anything. An SVG can carry script and is served as
# neither a preview nor a download.
RASTER_TYPES = {".png": "image/png", ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg", ".gif": "image/gif",
                ".webp": "image/webp", ".bmp": "image/bmp"}
MAX_PREVIEW_BYTES = 15 * 1024 * 1024

# Microsoft's own marker for "this picture carries nothing a reader needs".
_DECORATIVE_URI = "{C183D7F6-B498-43B3-948B-1728B52AA6E4}"
_DECORATIVE_NS = "http://schemas.microsoft.com/office/drawing/2017/decorative"
_EXT = (f'<a:ext uri="{_DECORATIVE_URI}"><adec:decorative '
        f'xmlns:adec="{_DECORATIVE_NS}" val="1"/></a:ext>')
_EXTLST = f'<a:extLst xmlns:a="{_A}">{_EXT}</a:extLst>'


class Refusal(Exception):
    """Nothing was written, and the message says why."""


class Stopped(Exception):
    """Cancelled between files. Nothing is left behind."""


@dataclass
class Picture:
    """One picture a course owes a description."""

    pid: int = -1
    member: str = ""          # the file in the cartridge
    part: str = ""            # the XML part inside an Office file, if any
    kind: str = ""            # page | docx | pptx
    n: int = 0                # position among the pictures of that part
    state: str = MISSING
    current: str = ""         # what it carries now
    label: str = ""           # docPr / cNvPr name, to find it again
    ident: str = ""           # docPr / cNvPr id, to find it again
    asset: str = ""           # where the picture itself is, if inside
    asset_part: str = ""      # the part inside the Office file
    src: str = ""             # a web page's own reference to it
    heading: str = ""
    nearby: str = ""


@dataclass
class Decision:
    action: str
    text: str = ""


# ---------- reading what a picture carries ----------

def _state(descr: Optional[str], decorative: bool, explicit_empty: bool) -> str:
    if decorative:
        return MARKED_DECORATIVE
    if remediate.is_machine_description(descr or ""):
        return MACHINE
    if explicit_empty:
        # `alt=""` is the author saying the picture carries nothing a reader
        # needs. That is a claim they made, not a gap.
        return MARKED_DECORATIVE
    if remediate.looks_like_a_placeholder_description(descr or ""):
        return MISSING
    return OK


def _short(text: str, limit: int = 240) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "..."


def _resolve_asset(member: str, src: str, names: set) -> str:
    """Where a web page's picture is inside the cartridge, or empty.

    Canvas writes `$IMS-CC-FILEBASE$/Uploaded Media/x.png` for a file in the
    course; D2L and Moodle write ordinary relative paths. A picture hosted
    elsewhere is not in the package and cannot be shown from it.
    """
    if not src or src.startswith(("http://", "https://", "data:", "//")):
        return ""
    path = unquote(src.split("#")[0].split("?")[0])
    path = path.replace("$IMS-CC-FILEBASE$", "web_resources")
    for candidate in (path.lstrip("/"),
                      posixpath.normpath(posixpath.join(
                          posixpath.dirname(member), path))):
        if candidate in names:
            return candidate
    return ""


def _rels(z: zipfile.ZipFile, part: str) -> dict:
    """Relationship id to the part it names, for one part of an Office file."""
    from lxml import etree

    folder, name = posixpath.split(part)
    rel_path = posixpath.join(folder, "_rels", name + ".rels")
    if rel_path not in z.namelist():
        return {}
    out = {}
    for rel in etree.fromstring(z.read(rel_path)):
        target = rel.get("Target") or ""
        if rel.get("TargetMode") == "External":
            continue
        out[rel.get("Id")] = (target.lstrip("/") if target.startswith("/")
                              else posixpath.normpath(posixpath.join(folder, target)))
    return out


def _html_pictures(member: str, data: bytes, names: set) -> list:
    from lxml import html as lxml_html

    try:
        tree = lxml_html.fromstring(data)
    except Exception:
        return []
    found = []
    for n, img in enumerate(tree.xpath("//img")):
        alt = img.get("alt")
        marked = (img.get("role") == "presentation"
                  or img.get("aria-hidden") == "true")
        state = _state(alt, marked, alt is not None and alt.strip() == "")
        if state not in QUEUED_STATES:
            continue
        heading = img.xpath("preceding::*[self::h1 or self::h2 or self::h3 "
                            "or self::h4][1]")
        block = img.xpath("ancestor::*[self::p or self::li or self::td or "
                          "self::figure or self::div][1]")
        nearby = _short(" ".join(block[0].itertext())) if block else ""
        if not nearby:
            # A picture alone in its paragraph, which is how Canvas writes
            # most of them, has no text of its own around it, and an author
            # shown nothing is being asked to describe it blind. The nearest
            # paragraph above that says something is the best context there is.
            above = img.xpath("preceding::p[normalize-space(.)][1]")
            nearby = _short(" ".join(above[0].itertext())) if above else ""
        src = img.get("src") or ""
        found.append(Picture(
            member=member, kind="page", n=n, state=state, current=alt or "",
            src=src, asset=_resolve_asset(member, src, names),
            heading=_short(" ".join(heading[0].itertext())) if heading else "",
            nearby=nearby))
    return found


def _docx_pictures(member: str, data: bytes) -> list:
    from lxml import etree

    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        if "word/document.xml" not in z.namelist():
            return []
        doc = etree.fromstring(z.read("word/document.xml"))
        rels = _rels(z, "word/document.xml")
    except Exception:
        return []
    found = []
    for n, el in enumerate(doc.xpath("//wp:docPr", namespaces=NS)):
        decorative = bool(el.xpath(".//*[local-name()='decorative']"))
        descr = el.get("descr")
        state = _state(descr, decorative, False)
        if state not in QUEUED_STATES:
            continue
        embeds = el.getparent().xpath(".//a:blip/@r:embed", namespaces=NS)
        para = el.xpath("ancestor::w:p[1]", namespaces=NS)
        found.append(Picture(
            member=member, part="word/document.xml", kind="docx", n=n,
            state=state, current=descr or "", label=el.get("name") or "",
            ident=el.get("id") or "",
            asset_part=rels.get(embeds[0], "") if embeds else "",
            nearby=_short("".join(para[0].xpath(".//w:t/text()",
                                                namespaces=NS))) if para else ""))
    return found


def _pptx_pictures(member: str, data: bytes) -> list:
    from lxml import etree

    found = []
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
        slides = sorted(
            (n for n in z.namelist()
             if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
            key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1)))
    except Exception:
        return []
    for part in slides:
        try:
            slide = etree.fromstring(z.read(part))
            rels = _rels(z, part)
        except Exception:
            continue
        title = slide.xpath(
            "//p:sp[p:nvSpPr/p:nvPr/p:ph[@type='title' or @type='ctrTitle']]"
            "//a:t/text()", namespaces=NS)
        for n, pic in enumerate(slide.xpath("//p:pic", namespaces=NS)):
            props = pic.xpath("./p:nvPicPr/p:cNvPr", namespaces=NS)
            if not props:
                continue
            el = props[0]
            decorative = bool(el.xpath(".//*[local-name()='decorative']"))
            descr = el.get("descr")
            state = _state(descr, decorative, False)
            if state not in QUEUED_STATES:
                continue
            embeds = pic.xpath("./p:blipFill/a:blip/@r:embed", namespaces=NS)
            found.append(Picture(
                member=member, part=part, kind="pptx", n=n, state=state,
                current=descr or "", label=el.get("name") or "",
                ident=el.get("id") or "",
                asset_part=rels.get(embeds[0], "") if embeds else "",
                heading=_short(" ".join(title))))
    return found


def find_pictures(cartridge_path) -> list:
    """Every picture in a cartridge that still owes a description.

    Web pages, Word files and PowerPoint files, in the order the cartridge
    holds them. Pictures already described, or marked decorative by their
    author, are not queued: counting them would quote the author for work or
    a decision already taken.
    """
    found: list = []
    with zipfile.ZipFile(cartridge_path) as z:
        names = set(z.namelist())
        for info in z.infolist():
            if info.is_dir():
                continue
            suffix = Path(info.filename).suffix.lower()
            if suffix in (".html", ".htm"):
                found.extend(_html_pictures(info.filename, z.read(info.filename),
                                            names))
            elif suffix == ".docx":
                found.extend(_docx_pictures(info.filename, z.read(info.filename)))
            elif suffix == ".pptx":
                found.extend(_pptx_pictures(info.filename, z.read(info.filename)))
    for index, picture in enumerate(found):
        picture.pid = index
    return found


def read_preview(cartridge_path, picture: Picture) -> Optional[tuple]:
    """(bytes, content_type) for the picture itself, or None.

    Raster formats only, and capped, because this is served to a browser from
    a file somebody else sent. Anything else is not shown.
    """
    try:
        with zipfile.ZipFile(cartridge_path) as z:
            if picture.kind == "page":
                path, data_source = picture.asset, z
            else:
                path = picture.asset_part
                inner = zipfile.ZipFile(io.BytesIO(z.read(picture.member)))
                data_source = inner
            suffix = Path(path).suffix.lower()
            if not path or suffix not in RASTER_TYPES:
                return None
            if data_source.getinfo(path).file_size > MAX_PREVIEW_BYTES:
                return None
            return data_source.read(path), RASTER_TYPES[suffix]
    except Exception:
        return None


# ---------- what an author may say ----------

def clean_description(text: str) -> str:
    """One line of plain words, or a sentence saying why not.

    A description is read aloud with no structure and no way back, so it is
    one line. A filename or a bare "Picture 3" is exactly the thing being
    replaced, and accepting one would clear a gap in the report while
    leaving the gap.
    """
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        raise ValueError("Write what the picture shows, or mark it "
                         "decorative if it carries nothing a reader needs.")
    if len(text) > MAX_DESCRIPTION:
        raise ValueError(f"That is {len(text)} characters. A description is "
                         f"read aloud with no way back, so keep it under "
                         f"{MAX_DESCRIPTION}.")
    if remediate.looks_like_a_placeholder_description(text):
        raise ValueError("That reads as a filename or a placeholder, not as "
                         "a description of what the picture shows.")
    return text


def validate_decision(picture: Picture, action: str, text: str) -> Decision:
    if action not in ACTIONS:
        raise ValueError("Choose what to do with this picture.")
    if action == DESCRIBE:
        return Decision(DESCRIBE, clean_description(text))
    if action == KEEP and picture.state != MACHINE:
        raise ValueError("Only a machine-written description can be kept "
                         "as it is.")
    return Decision(action, "")


# ---------- writing it ----------

def _set_attr(tag: str, name: str, value: str) -> str:
    """Set one attribute inside an opening tag, touching nothing else."""
    escaped = _escape(value, {'"': "&quot;"})
    if re.search(rf"\s{name}\s*=\s*'", tag):
        raise ValueError(f"unusual quoting on {name}")
    pattern = re.compile(rf'(\s{name}\s*=\s*)"[^"]*"')
    if pattern.search(tag):
        return pattern.sub(lambda m: f'{m.group(1)}"{escaped}"', tag, count=1)
    return re.sub(r"(\s*/?>)$",
                  lambda m: f' {name}="{escaped}"{m.group(1)}', tag, count=1)


def _element(text: str, start: int, name: str) -> tuple:
    """(start, end) of the element opening at `start`."""
    opening = re.compile(
        r"<" + re.escape(name) + r"\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>"
    ).match(text, start)
    if opening is None:
        raise ValueError("could not read the element")
    if opening.group(0).endswith("/>"):
        return start, opening.end()
    close = text.find(f"</{name}>", opening.end())
    if close < 0:
        raise ValueError("unclosed element")
    return start, close + len(name) + 3


def _rewrite(element: str, name: str, decision: Decision) -> str:
    opening = re.compile(
        r"<" + re.escape(name) + r"\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>"
    ).match(element)
    tag, rest = opening.group(0), element[opening.end():]
    tag = _set_attr(tag, "descr", decision.text)
    if decision.action != DECORATIVE:
        return tag + rest
    if tag.endswith("/>"):
        return tag[:-2].rstrip() + ">" + _EXTLST + f"</{name}>"
    inner = rest.rfind("</a:extLst>")
    if inner >= 0:
        return tag + rest[:inner] + _EXT + rest[inner:]
    close = rest.rfind(f"</{name}>")
    return tag + rest[:close] + _EXTLST + rest[close:]


def _edit_office_part(text: str, kind: str, edits: dict) -> str:
    """Apply `{n: (picture, decision)}` to the XML text of one part."""
    name = "wp:docPr" if kind == "docx" else "p:cNvPr"
    opener = re.compile(
        r"<" + re.escape(name) + r"\b(?:[^>\"']|\"[^\"]*\"|'[^']*')*>")
    if kind == "docx":
        spots = [m.start() for m in opener.finditer(text)]
    else:
        spots = []
        for pic in re.finditer(r"<p:pic\b[^>]*>.*?</p:pic>", text, re.DOTALL):
            inner = opener.search(pic.group(0))
            if inner:
                spots.append(pic.start() + inner.start())
    replacements = []
    for n, (picture, decision) in edits.items():
        if n >= len(spots):
            raise ValueError("the file has fewer pictures than it did")
        start, end = _element(text, spots[n], name)
        element = text[start:end]
        # The picture is found again by its own id and name, so a part that
        # does not look the way the finder saw it is left alone.
        if picture.ident and f'id="{picture.ident}"' not in element[:400]:
            raise ValueError("the picture at that position is not the one "
                             "that was queued")
        replacements.append((start, end, _rewrite(element, name, decision)))
    for start, end, new in sorted(replacements, reverse=True):
        text = text[:start] + new + text[end:]
    return text


def _edit_office(data: bytes, items: list) -> bytes:
    """Rewrite one Office file, changing only the parts that hold pictures."""
    by_part: dict = {}
    for picture, decision in items:
        by_part.setdefault((picture.part, picture.kind), {})[picture.n] = (
            picture, decision)
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(data)) as source, \
            zipfile.ZipFile(out, "w", allowZip64=True) as dest:
        for info in source.infolist():
            body = source.read(info.filename)
            for (part, kind), edits in by_part.items():
                if info.filename == part:
                    body = _edit_office_part(
                        body.decode("utf-8"), kind, edits).encode("utf-8")
            entry = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            entry.compress_type = info.compress_type
            entry.external_attr = info.external_attr
            dest.writestr(entry, body)
    return out.getvalue()


def _edit_html(data: bytes, items: list) -> bytes:
    from lxml import html as lxml_html

    tree = lxml_html.fromstring(data)
    images = tree.xpath("//img")
    for picture, decision in items:
        if picture.n >= len(images):
            raise ValueError("the page has fewer pictures than it did")
        images[picture.n].set("alt", decision.text)
    return remediate.serialise_html(tree, data)


def _edit_member(member: str, data: bytes, items: list) -> bytes:
    suffix = Path(member).suffix.lower()
    if suffix in (".html", ".htm"):
        return _edit_html(data, items)
    return _edit_office(data, items)


def _inner_crc_ok(before: bytes, after: bytes, edited_parts: set) -> bool:
    """Every part of an Office file that was not edited kept its bytes."""
    try:
        with zipfile.ZipFile(io.BytesIO(before)) as a, \
                zipfile.ZipFile(io.BytesIO(after)) as b:
            if a.namelist() != b.namelist():
                return False
            return all(b.getinfo(i.filename).CRC == i.CRC
                       for i in a.infolist()
                       if i.filename not in edited_parts and not i.is_dir())
    except Exception:
        return False


@dataclass
class ApplyReport:
    source: str
    applied: list = field(default_factory=list)
    decorative: list = field(default_factory=list)
    kept: list = field(default_factory=list)
    still_owed: list = field(default_factory=list)
    failed: list = field(default_factory=list)
    files_changed: int = 0
    members: int = 0
    verified: bool = False

    def summary(self) -> str:
        said = (f"{len(self.applied)} description(s) written and "
                f"{len(self.decorative)} picture(s) marked decorative, in "
                f"{self.files_changed} file(s) of {self.members}. ")
        if self.kept:
            said += (f"{len(self.kept)} machine-written description(s) were "
                     f"read and kept by their author. ")
        if self.still_owed:
            said += f"{len(self.still_owed)} picture(s) are still owed. "
        if self.failed:
            said += (f"{len(self.failed)} could not be written and are "
                     f"listed below. ")
        said += ("Every edited file's text was compared before and after "
                 "and none had changed." if self.verified and not self.failed
                 else "")
        return said.strip()


def apply_descriptions(
        src, dst, pictures: list, decisions: dict,
        tick: Optional[Callable] = None,
        stop: Optional[Callable] = None) -> ApplyReport:
    """Write the author's decisions into a copy of the cartridge.

    `decisions` maps a picture's `pid` to a `Decision`. Only what was decided
    is written: a skipped picture stays owed and an undecided one is untouched.
    """
    src, dst = Path(src), Path(dst)
    report = ApplyReport(source=src.name)
    by_member: dict = {}
    for picture in pictures:
        decision = decisions.get(picture.pid)
        if decision is None or decision.action == SKIP:
            report.still_owed.append(picture.pid)
        elif decision.action == KEEP:
            report.kept.append(picture.pid)
        else:
            by_member.setdefault(picture.member, []).append((picture, decision))

    partial = dst.with_name(dst.name + ".partial")
    edited: dict = {}      # member -> set of inner parts edited
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
                items = by_member.get(info.filename)
                if items:
                    try:
                        new = _edit_member(info.filename, data, items)
                        before = invariance.text_of(info.filename, data)
                        after = invariance.text_of(info.filename, new)
                        if before is None or before != after:
                            raise ValueError("it would have changed the text "
                                             "of the file")
                        parts = {p.part for p, _d in items if p.part}
                        if parts and not _inner_crc_ok(data, new, parts):
                            raise ValueError("it would have changed a part "
                                             "of the file it was not meant "
                                             "to touch")
                    except Exception as exc:
                        for picture, _d in items:
                            report.failed.append(
                                {"pid": picture.pid, "member": info.filename,
                                 "reason": str(exc)})
                    else:
                        data = new
                        # Only real inner parts: a web page has none, and an
                        # empty-string part is truthy, which made verification
                        # try to open an HTML file as a zip and refuse to ship.
                        edited[info.filename] = {p.part for p, _d in items
                                                 if p.part}
                        for picture, decision in items:
                            (report.applied if decision.action == DESCRIBE
                             else report.decorative).append(picture.pid)
                entry = zipfile.ZipInfo(info.filename,
                                        date_time=info.date_time)
                entry.compress_type = info.compress_type
                entry.external_attr = info.external_attr
                entry.comment = info.comment
                out.writestr(entry, data)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise

    report.files_changed = len(edited)
    report.verified = _verify(src, partial, edited)
    if not report.verified:
        partial.unlink(missing_ok=True)
        raise Refusal("The cartridge that was written did not pass its own "
                      "checks, so it was discarded and nothing was kept.")
    partial.replace(dst)
    return report


def _verify(src: Path, written: Path, edited: dict) -> bool:
    """Reopen what was written and check it, rather than what was meant."""
    try:
        with zipfile.ZipFile(src) as a, zipfile.ZipFile(written) as b:
            if b.testzip() is not None or a.namelist() != b.namelist():
                return False
            for info in a.infolist():
                if info.is_dir():
                    continue
                if info.filename in edited:
                    before = a.read(info.filename)
                    after = b.read(info.filename)
                    if invariance.text_of(info.filename, before) != \
                            invariance.text_of(info.filename, after):
                        return False
                    parts = edited[info.filename]
                    if parts and not _inner_crc_ok(before, after, parts):
                        return False
                elif b.getinfo(info.filename).CRC != info.CRC:
                    return False
        return True
    except Exception:
        return False


# ---------- the queue's own files ----------

def _write_json(path: Path, value) -> None:
    """Atomically, so a reader never meets half a file."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(value, indent=2), encoding="utf-8")
    tmp.replace(path)


def save_pictures(folder: Path, pictures: list) -> None:
    _write_json(folder / "pictures.json", [asdict(p) for p in pictures])


def load_pictures(folder: Path) -> Optional[list]:
    path = folder / "pictures.json"
    if not path.is_file():
        return None
    return [Picture(**row) for row in json.loads(path.read_text("utf-8"))]


def save_decisions(folder: Path, decisions: dict) -> None:
    _write_json(folder / "descriptions.json",
                {str(pid): asdict(d) for pid, d in decisions.items()})


def load_decisions(folder: Path) -> dict:
    path = folder / "descriptions.json"
    if not path.is_file():
        return {}
    return {int(pid): Decision(**row)
            for pid, row in json.loads(path.read_text("utf-8")).items()}


def pending(pictures: list, decisions: dict) -> list:
    """Pictures with no decision yet, or one the author skipped."""
    return [p for p in pictures
            if decisions.get(p.pid) is None
            or decisions[p.pid].action == SKIP]


def render_markdown(report: ApplyReport, pictures: list,
                    decisions: dict) -> str:
    """A record of what was written, in the author's own words."""
    by_pid = {p.pid: p for p in pictures}
    lines = [f"# Descriptions written into {report.source}", "",
             report.summary(), ""]
    written = [(pid, "described") for pid in report.applied] + \
              [(pid, "marked decorative") for pid in report.decorative]
    if written:
        lines += ["## What was written", ""]
        for pid, what in sorted(written):
            picture = by_pid[pid]
            lines.append(f"- `{picture.member}` ({what})")
            if what == "described":
                lines.append(f"  > {decisions[pid].text}")
        lines.append("")
    if report.failed:
        lines += ["## Could not be written", ""]
        for failure in report.failed:
            lines.append(f"- `{failure['member']}`: {failure['reason']}")
        lines.append("")
    if report.still_owed:
        lines += ["## Still owed", ""]
        for pid in report.still_owed:
            picture = by_pid[pid]
            lines.append(f"- `{picture.member}`"
                         + (f" ({picture.label})" if picture.label else ""))
        lines.append("")
    return "\n".join(lines)
