"""The figures still owed a description, in the order somebody would write them.

201 of this archive's 203 descriptions were written by hand, and until now the
page for writing one could not see most of the figures. `article_figures`
matches a standalone image paragraph, and PDF ingest writes a figure and the
caption printed under it as one paragraph joined by a hard line break, so the
trailing backslash put every reconstructed figure outside the pattern: 34 of
the 204 images matched, and 38 of the 51 articles that hold figures showed an
empty page. The work was done in a text editor, against `article.md`.

What this module decides is which figures are owed something and in what
order, and it decides it by asking `lint.figure_state` rather than reading the
slots itself. Two readings of one figure is the failure with no symptom: the
register would report a description as owed while the queue never showed the
figure, so nobody would write it, and where that surfaces is a reader hearing
nothing. Writing goes the same way, through `conversion.with_description`,
which is the function that already knows a figure with a caption keeps its
description somewhere else.

The two lanes ask different questions of the same figures. A description
satisfies WCAG 1.1.1 and leaves 1.4.5 exactly where it was, and whether a
figure carries text as a picture is answered by looking at a chapter's
figures together rather than one at a time: what separates a photograph of a
document from a photograph of anything else is the kind of thing the chapter
is doing with it. So the first lane is one figure at a time and the second is
one chapter at a time, and the second records its answer even when the answer
is none.
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

import conversion
import lint

# What to call each of lint's four states, and what colour it is. The tone is
# decided here rather than in a template, for the reason
# `register.Standing.tone` is: a template that answered it on its own could
# answer it differently from the count beside it.
STATE_LABELS = {
    lint.MISSING: "No alt text at all",
    lint.UNDESCRIBED: "Says only that it is undescribed",
    lint.FROM_CAPTION: "Carries its printed caption",
    lint.DESCRIBED: "Described",
}
STATE_TONE = {
    lint.MISSING: "bad",
    lint.UNDESCRIBED: "warn",
    lint.FROM_CAPTION: "warn",
    lint.DESCRIBED: "good",
}


@dataclass
class Figure:
    """One figure, as both lanes need it.

    Addressed by `name`, the file the raster sits in, because that is what
    `carry_alt_text` matches on and what `images-of-text` lists; the
    filenames are built from the page the raster came off, so they survive a
    re-ingest where a position in the body does not.
    """
    article_id: int
    article_title: str
    article_slug: str
    project_path: str
    issue_id: Optional[int]
    issue_label: str
    position: int
    src: str
    name: str
    caption: str
    description: str
    state: str
    of_text: bool
    exists: bool

    @property
    def owed(self) -> bool:
        return self.state in lint.OWED

    @property
    def label(self) -> str:
        return STATE_LABELS[self.state]

    @property
    def tone(self) -> str:
        return STATE_TONE[self.state]

    @property
    def served(self) -> str:
        """The path `serve_asset` wants, which is rooted at `assets/`."""
        if self.src.startswith("assets/"):
            return self.src[len("assets/"):]
        return ""


@dataclass
class Group:
    """What one issue's figures stand at, which is the count an editor works to."""
    issue_id: Optional[int] = None
    label: str = ""
    articles: int = 0
    figures: int = 0
    owed: int = 0
    described: int = 0
    of_text: int = 0
    judged: int = 0
    first_owed: Optional[Figure] = None
    unjudged: List[dict] = field(default_factory=list)


@dataclass
class Queue:
    items: List[Figure] = field(default_factory=list)
    groups: List[Group] = field(default_factory=list)
    unreadable: List[str] = field(default_factory=list)

    @property
    def figures(self) -> int:
        return len(self.items)

    @property
    def owed(self) -> List[Figure]:
        return [f for f in self.items if f.owed]

    def find(self, article_id: int, name: str) -> Optional[Figure]:
        for f in self.items:
            if f.article_id == article_id and f.name == name:
                return f
        return None

    def next_owed(self, after: Optional[Figure] = None) -> Optional[Figure]:
        """The next figure owed a description, reading forwards.

        Forwards only, and it does not wrap. An editor who saves a
        description that still reads as the printed caption would otherwise
        be handed the same figure back, and one who started in the middle of
        volume 4 would be walked round to volume 1 with no indication that
        anything had happened. Where there is nothing after, the caller sends
        them to the overview, which is the page that answers what is left.
        """
        start = 0
        if after is not None:
            for i, f in enumerate(self.items):
                if f.article_id == after.article_id and f.name == after.name:
                    start = i + 1
                    break
        for f in self.items[start:]:
            if f.owed:
                return f
        return None

    def next_unjudged(self, after: Optional[int] = None) -> Optional[dict]:
        """The next chapter whose figures nobody has judged for 1.4.5.

        Forwards only, for the reason `next_owed` is, and measured against
        the whole journal's order rather than against the waiting list: the
        chapter just answered has left that list, so looking for it there
        finds nothing and would send the editor back to the beginning.
        """
        waiting = [a for g in self.groups for a in g.unjudged]
        if not waiting:
            return None
        if after is None:
            return waiting[0]
        order = []
        for figure in self.items:
            if figure.article_id not in order:
                order.append(figure.article_id)
        if after not in order:
            return waiting[0]
        cut = order.index(after)
        for article in waiting:
            if article["id"] in order and order.index(article["id"]) > cut:
                return article
        return None

    def totals(self) -> Group:
        """The whole journal, counted the way one issue is."""
        out = Group(label="All volumes")
        for g in self.groups:
            out.articles += g.articles
            out.figures += g.figures
            out.owed += g.owed
            out.described += g.described
            out.of_text += g.of_text
            out.judged += g.judged
            out.unjudged.extend(g.unjudged)
            if out.first_owed is None:
                out.first_owed = g.first_owed
        return out

    def note(self) -> str:
        """What these counts do and do not say."""
        said = (
            "A figure is listed as owed where lint says it is owed, so this "
            "queue and the register are counting the same figures. One whose "
            "page printed no caption carries a placeholder rather than "
            "nothing, which keeps the galley conformant and leaves the "
            "description owed. Whether a figure carries text as a picture is "
            "a different judgement and is asked a chapter at a time; a "
            "chapter with no answer on record is listed as unanswered rather "
            "than counted as having none."
        )
        if self.unreadable:
            said += (f" {len(self.unreadable)} article(s) could not be read "
                     f"and hold no figures here: "
                     f"{', '.join(self.unreadable[:6])}.")
        return said


def image_names(body: str) -> List[str]:
    """Every image file the body places, in document order.

    `lint.image_names` is the reader, because that module owns the pattern
    and two matchers over the same images is how a figure comes to be read
    one way and written another.
    """
    return lint.image_names(body)


def listed_of_text(fm: dict) -> List[str]:
    """The figures this article records as carrying text as a picture.

    Read as names, because that is what the archive's 115 entries are and
    what `check_images_of_text` counts; a path-shaped entry is tolerated
    rather than missed.
    """
    listed = fm.get("images-of-text") or []
    if isinstance(listed, str):
        listed = [listed]
    return [str(x).rsplit("/", 1)[-1] for x in listed]


def judged(fm: dict) -> bool:
    """Whether somebody has answered the images-of-text question here.

    The field's presence is the record. An empty list is an answer and a
    missing field is not, which is why `conversion.write_article_metadata`
    keeps the one empty field it keeps.
    """
    return "images-of-text" in fm


def caption_of(match, body: str) -> str:
    """What this figure is called, from wherever the chapter keeps it.

    Usually the line printed under it, which is what `lint.printed_caption`
    reads. A figure through `pair_figure_captions` is the exception: it moves
    the description to `fig-alt` and leaves the bracket to Pandoc as the
    caption, so there is no caption line to find. Telling an editor the page
    printed none would hide the caption in the one slot they are not writing
    in, and it is the caption that tells them which figure they are looking
    at.

    Where the bracket is itself the description, there is no caption, and
    `_carried_description` is what says which of the two it is.
    """
    printed = lint.printed_caption(match, body)
    if printed:
        return printed
    bracket = match.group("alt").strip()
    attrs = match.group("attrs") or ""
    if bracket and lint._FIG_ALT_ATTR_RE.search(attrs):
        if conversion._carried_description(match) != bracket:
            return bracket
    return ""


def figures_in(article: dict, fm: dict, body: str) -> List[Figure]:
    """Every figure in one article, with what it is owed."""
    listed = set(listed_of_text(fm))
    apath = Path(article["project_path"]) if article.get("project_path") else None
    out = []
    for n, m in enumerate(lint._IMAGE_RE.finditer(body), 1):
        src = m.group("src")
        name = src.rsplit("/", 1)[-1]
        out.append(Figure(
            article_id=article["id"],
            article_title=article.get("title") or article.get("slug") or "",
            article_slug=article.get("slug") or "",
            project_path=str(apath or ""),
            issue_id=article.get("issue_id"),
            issue_label=article.get("issue_label") or "",
            position=n,
            src=src,
            name=name,
            caption=caption_of(m, body),
            description=conversion._carried_description(m),
            state=lint.figure_state(m, body),
            of_text=name in listed,
            exists=bool(apath) and (apath / src).exists(),
        ))
    return out


def read(article: dict):
    """This article's front matter and body, or None where there is none."""
    if not article.get("project_path"):
        return None
    apath = Path(article["project_path"])
    if not (apath / "article.md").exists():
        return None
    try:
        return conversion.read_article_metadata(apath)
    except Exception:
        return None


def build(articles: Iterable[dict]) -> Queue:
    """Fold a journal's articles into one queue.

    `articles` are rows carrying at least `id` and `project_path`, in the
    order they should be worked through; `issue_id` and `issue_label` group
    them. The order is the caller's, because what an editor wants is volume
    order and only the caller knows how this journal numbers its chapters.
    """
    queue = Queue()
    groups: Dict = {}
    order: List = []
    for article in articles:
        key = article.get("issue_id")
        if key not in groups:
            groups[key] = Group(issue_id=key,
                                label=article.get("issue_label") or "")
            order.append(key)
        group = groups[key]
        pair = read(article)
        if pair is None:
            queue.unreadable.append(article.get("slug") or str(article.get("id")))
            continue
        fm, body = pair
        found = figures_in(article, fm, body)
        if not found:
            continue
        group.articles += 1
        group.figures += len(found)
        for figure in found:
            queue.items.append(figure)
            if figure.owed:
                group.owed += 1
                if group.first_owed is None:
                    group.first_owed = figure
            else:
                group.described += 1
            if figure.of_text:
                group.of_text += 1
        if judged(fm):
            group.judged += 1
        else:
            group.unjudged.append({
                "id": article["id"],
                "title": article.get("title") or article.get("slug") or "",
                "slug": article.get("slug") or "",
                "figures": len(found),
            })
    queue.groups = [groups[k] for k in order if groups[k].figures]
    return queue


def write_description(article_path: Path, name: str, description: str) -> int:
    """Write `description` over every image whose file is `name`.

    Every occurrence, because `carry_alt_text` matches by asset path and
    writes to all of them. An article that places one raster twice would
    otherwise take the description on one and go on reporting the other as
    owed, and the two would drift the moment a re-ingest carried the one it
    could find.

    Returns how many images changed, and writes nothing where none did, so
    a save that says what the figure already said does not spend one of the
    five versions `.versions/` keeps.
    """
    fm, body = conversion.read_article_metadata(article_path)
    new_body, changed = _rewritten(body, name, description)
    if not changed:
        return 0
    conversion.write_article_metadata(article_path, fm, new_body)
    return changed


def _rewritten(body: str, name: str, description: str):
    changed = 0

    def swap(match):
        nonlocal changed
        if match.group("src").rsplit("/", 1)[-1] != name:
            return match.group(0)
        attrs = match.group("attrs")
        rebuilt = conversion.with_description(
            match.group("alt"), match.group("src"),
            "{%s}" % attrs if attrs is not None else "", description)
        if rebuilt != match.group(0):
            changed += 1
        return rebuilt

    return lint._IMAGE_RE.sub(swap, body), changed


def record_images_of_text(article_path: Path, names: Iterable[str]) -> List[str]:
    """Record which of this article's figures carry text as a picture.

    The list is filtered against the images the body actually places and
    written in document order, so an entry naming a figure this article no
    longer holds cannot be created here: the count feeds WCAG 1.4.5 in the
    conformance report, and a stale name would inflate it with nothing to
    look at.

    An empty list is written rather than the field being left out. That is
    the difference between a chapter somebody judged and found clear and a
    chapter nobody has opened, and it is the only reason
    `conversion.write_article_metadata` keeps an empty field.
    """
    fm, body = conversion.read_article_metadata(article_path)
    wanted = {str(n).rsplit("/", 1)[-1] for n in names}
    kept = [n for n in image_names(body) if n in wanted]
    if judged(fm) and listed_of_text(fm) == kept:
        return kept
    fm["images-of-text"] = kept
    conversion.write_article_metadata(article_path, fm, body)
    return kept
