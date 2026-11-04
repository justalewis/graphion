"""The accessibility conformance report, generated from what was checked.

An ACR is the document an institution asks for before it adopts a journal:
every WCAG success criterion with a support level against it, and a date.
Typed by hand it is a snapshot of somebody's belief on the afternoon they
wrote it, and it starts drifting from the content immediately. Generated
from `register`, it cannot say anything the checks did not find, and it
goes stale visibly rather than quietly, because a run that no longer
matches the file it read stops counting.

Three rules decide every row, and each exists because the opposite is the
easy mistake.

A criterion with nothing behind it reads **Not Evaluated**, never Supports.
Most of WCAG cannot be checked by a machine at all, and an ACR that quietly
filled those in would be the whole exercise defeated. Half this table is
Not Evaluated, which is the honest shape of a generated report and the
reason the generated one is worth having: the rows that do carry a level
carry a named check and a date with it.

**Not Applicable** is a claim too, and it is made only from evidence. A
criterion about captions does not apply to a publication with no media,
but "there is no media" is a fact about the content, so it is read off the
content rather than assumed. Where it cannot be read, the row is Not
Evaluated.

And a level is derived from the articles the register can currently speak
for. An article whose run was taken against content that has since changed
is not evidence of anything, so it is left out of the count and named in
the coverage line instead of quietly improving it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

import register

SUPPORTS = "Supports"
PARTIAL = "Partially Supports"
DOES_NOT = "Does Not Support"
NOT_EVALUATED = "Not Evaluated"
NOT_APPLICABLE = "Not Applicable"

# Worst first, for a page that leads with what is not met.
_ORDER = {DOES_NOT: 0, PARTIAL: 1, SUPPORTS: 2, NOT_APPLICABLE: 3,
          NOT_EVALUATED: 4}

# What makes a criterion applicable at all. Each is a fact read off the
# content rather than an assumption about what a journal publishes.
MEDIA = "media"
FORMS = "forms"
SCRIPTS = "scripts"

# A galley is static prose and pictures, so these say what would have to be
# in it for the criteria that turn on them to engage.
_MEDIA_RE = re.compile(
    r"<(?:video|audio|iframe|embed|object)\b|\.(?:mp4|m4v|mov|webm|mp3|wav|ogg)\b",
    re.I)
_FORMS_RE = re.compile(r"<(?:form|input|select|textarea|button)\b", re.I)
_SCRIPTS_RE = re.compile(r"<script\b|\bon(?:click|focus|input|change)\s*=", re.I)


@dataclass
class Criterion:
    number: str
    name: str
    level: str                      # "A" or "AA"
    basis: Tuple = ()               # (kind, check_name) pairs in the register
    bundle: str = ""                # a template-bundle fact, where that is the evidence
    needs: str = ""                 # MEDIA / FORMS / SCRIPTS, or "" for always
    note: str = ""                  # what the evidence does and does not settle


# WCAG 2.1 Level A and AA, in order. `basis` names the checks that bear on
# the criterion; an empty one is a row no machine here can fill, and it
# says so rather than guessing.
CRITERIA: Tuple[Criterion, ...] = (
    # ---------- 1. Perceivable ----------
    Criterion("1.1.1", "Non-text Content", "A",
              basis=(("lint", "alt-text"), ("verapdf", "verapdf"),
                     ("pa11y", "pa11y")),
              note="Every figure in the Markdown source carries alt text or "
                   "is counted as owing one; verapdf enforces /Alt on each "
                   "/Figure in the tagged PDF, and pa11y reads the HTML."),
    Criterion("1.2.1", "Audio-only and Video-only (Prerecorded)", "A",
              needs=MEDIA),
    Criterion("1.2.2", "Captions (Prerecorded)", "A", needs=MEDIA),
    Criterion("1.2.3", "Audio Description or Media Alternative (Prerecorded)",
              "A", needs=MEDIA),
    Criterion("1.3.1", "Info and Relationships", "A",
              basis=(("pdfua", "tagged"), ("verapdf", "verapdf"),
                     ("pa11y", "pa11y")),
              note="Headings, lists and tables are structural in the source "
                   "and tagged in the PDF; a pipe table carries a header row "
                   "so a cell can be named by its column."),
    Criterion("1.3.2", "Meaningful Sequence", "A",
              basis=(("verapdf", "verapdf"),),
              note="Reading order is part of what PDF/UA-1 validates. The "
                   "HTML galley has a single linear flow."),
    Criterion("1.3.3", "Sensory Characteristics", "A",
              note="Whether the prose directs a reader by shape, colour or "
                   "position is a reading, not a check."),
    Criterion("1.4.1", "Use of Color", "A",
              note="Whether colour alone carries meaning in a figure cannot "
                   "be read off the file."),
    Criterion("1.4.2", "Audio Control", "A", needs=MEDIA),
    # ---------- 2. Operable ----------
    # A galley with no scripts still has links, and a link is
    # functionality. Not Applicable would be wrong here; the honest answer
    # is that nobody has tabbed through one.
    Criterion("2.1.1", "Keyboard", "A",
              note="The only focusable elements in a galley are native "
                   "links, which are keyboard operable without anything "
                   "being done to them. Tabbing through one is a thing to "
                   "do, not a thing checked here."),
    Criterion("2.1.2", "No Keyboard Trap", "A",
              note="Nothing in a galley takes or holds focus; as above, "
                   "this is answered by trying it."),
    Criterion("2.1.4", "Character Key Shortcuts", "A", needs=SCRIPTS),
    Criterion("2.2.1", "Timing Adjustable", "A", needs=SCRIPTS),
    Criterion("2.2.2", "Pause, Stop, Hide", "A", needs=MEDIA),
    Criterion("2.3.1", "Three Flashes or Below Threshold", "A", needs=MEDIA),
    Criterion("2.4.1", "Bypass Blocks", "A", bundle="skip-link",
              note="The HTML galley opens with a skip link past the running "
                   "head anchors, styled off screen until it is focused."),
    Criterion("2.4.2", "Page Titled", "A",
              basis=(("pdfua", "document-title"),
                     ("pdfua", "display-doc-title"), ("pa11y", "pa11y")),
              note="The PDF carries dc:title in XMP and opens showing it "
                   "rather than the filename; the HTML carries a <title>."),
    Criterion("2.4.3", "Focus Order", "A",
              note="Focus follows the single linear flow of the document, "
                   "which is a property of there being nothing else in it "
                   "rather than a check that ran."),
    Criterion("2.4.4", "Link Purpose (In Context)", "A",
              basis=(("pa11y", "pa11y"),),
              note="pa11y reports a link with no discernible text. Whether a "
                   "link's text describes where it goes is a reading."),
    Criterion("2.5.1", "Pointer Gestures", "A", needs=SCRIPTS),
    Criterion("2.5.2", "Pointer Cancellation", "A", needs=SCRIPTS),
    Criterion("2.5.3", "Label in Name", "A", needs=FORMS),
    Criterion("2.5.4", "Motion Actuation", "A", needs=SCRIPTS),
    # ---------- 3. Understandable ----------
    Criterion("3.1.1", "Language of Page", "A",
              basis=(("pdfua", "document-language"), ("pa11y", "pa11y")),
              note="The PDF catalog carries /Lang and the HTML carries a "
                   "lang attribute, so a screen reader knows which voice to "
                   "read in."),
    Criterion("3.2.1", "On Focus", "A", needs=SCRIPTS),
    Criterion("3.2.2", "On Input", "A", needs=FORMS),
    Criterion("3.3.1", "Error Identification", "A", needs=FORMS),
    Criterion("3.3.2", "Labels or Instructions", "A", needs=FORMS),
    # ---------- 4. Robust ----------
    Criterion("4.1.1", "Parsing", "A",
              basis=(("pa11y", "pa11y"),),
              note="Pandoc emits well-formed HTML5 and pa11y parses it."),
    Criterion("4.1.2", "Name, Role, Value", "A",
              basis=(("pa11y", "pa11y"),),
              note="The galley uses native elements rather than ARIA "
                   "widgets, which is what makes this answerable at all."),
    # ---------- AA ----------
    Criterion("1.2.4", "Captions (Live)", "AA", needs=MEDIA),
    Criterion("1.2.5", "Audio Description (Prerecorded)", "AA", needs=MEDIA),
    Criterion("1.3.4", "Orientation", "AA",
              note="The galley is reflowable and sets no orientation lock, "
                   "which nothing here verifies."),
    Criterion("1.3.5", "Identify Input Purpose", "AA", needs=FORMS),
    Criterion("1.4.3", "Contrast (Minimum)", "AA",
              basis=(("pa11y", "pa11y"),),
              note="pa11y computes contrast where it can resolve both "
                   "colours. Text inside a figure is a picture to it, and a "
                   "dark-mode palette is never rendered, so "
                   "tests/test_template_bundles.py reads every palette each "
                   "bundle declares and checks it against 4.5:1 as well."),
    Criterion("1.4.4", "Resize Text", "AA",
              note="Type is set in relative units; that it survives 200% in "
                   "a real reader is a thing to try, not to check."),
    Criterion("1.4.5", "Images of Text", "AA",
              basis=(("lint", "images-of-text"),),
              note="Kept by hand in each article's images-of-text field, "
                   "because nothing can tell a photograph of a document from "
                   "a photograph of anything else. A figure on that list "
                   "fails this criterion however well it is described."),
    Criterion("1.4.10", "Reflow", "AA",
              note="A reflowable galley, not verified at 320 CSS pixels."),
    Criterion("1.4.11", "Non-text Contrast", "AA",
              note="Contrast inside a figure is a property of the picture."),
    Criterion("1.4.12", "Text Spacing", "AA",
              note="Nothing here applies a spacing override and measures "
                   "what happens."),
    Criterion("1.4.13", "Content on Hover or Focus", "AA", needs=SCRIPTS),
    Criterion("2.4.5", "Multiple Ways", "AA",
              note="A property of the journal's site, not of a galley."),
    Criterion("2.4.6", "Headings and Labels", "AA",
              basis=(("pa11y", "pa11y"),),
              note="pa11y reports an empty or skipped heading. Whether a "
                   "heading describes its section is a reading."),
    Criterion("2.4.7", "Focus Visible", "AA", bundle="focus-visible",
              note="The journal stylesheet sets a focus outline and never "
                   "removes one."),
    Criterion("3.1.2", "Language of Parts", "AA",
              note="A passage quoted in another language should carry its "
                   "own lang attribute; nothing here detects one."),
    Criterion("3.2.3", "Consistent Navigation", "AA",
              note="Every galley is rendered from one template per journal, "
                   "which is the mechanism; the claim is about the site."),
    Criterion("3.2.4", "Consistent Identification", "AA",
              note="As above: one template per journal, asserted rather than "
                   "measured."),
    Criterion("3.3.3", "Error Suggestion", "AA", needs=FORMS),
    Criterion("3.3.4", "Error Prevention (Legal, Financial, Data)", "AA",
              needs=FORMS),
    Criterion("4.1.3", "Status Messages", "AA", needs=SCRIPTS),
)


# ---------- the template bundle, where that is the evidence ----------

def skip_link_target(template: str) -> Optional[str]:
    """The id a bundle's skip link points at, or None where it points at
    nothing. A link to an id nothing defines sends a keyboard reader to the
    top of the page, which is where they already were."""
    link = re.search(r'class="skip-link"[^>]*href="#([^"]+)"', template)
    if not link:
        return None
    target = link.group(1)
    return target if re.search(r'id="%s"' % re.escape(target), template) else None


def focus_is_visible(css: str) -> bool:
    """Whether the stylesheet shows where focus is. A rule that sets
    `outline: none` is the commonest way this criterion is failed on
    purpose."""
    rule = re.search(r":focus-visible\s*\{[^}]*\}", css, re.S)
    return bool(rule and "outline" in rule.group(0)
                and "outline: none" not in rule.group(0))


def skip_link_is_hidden_until_focused(css: str) -> bool:
    """Both halves. Markup without the rule puts a visible link above every
    title; a rule that hides it with no `:focus` counterpart hides it from
    the reader it is for."""
    rule = re.search(r"\.skip-link\s*\{[^}]*\}", css, re.S)
    if not (rule and re.search(r"(left|top)\s*:\s*-", rule.group(0))):
        return False
    return bool(re.search(r"\.skip-link:focus\s*\{", css))


# WCAG 2.1 asks 4.5:1 of normal body text (1.4.3). The galleys set no large
# text below that, so the one threshold covers what the bundles declare.
TEXT_CONTRAST_MIN = 4.5

# The palette entries that carry text, against the one that is the page. A
# rule or a frame edge is not here on purpose: 1.4.11 asks 3:1 of a
# meaningful graphic and a decorative rule is neither, so asserting on it
# would quote a journal for a hairline nobody has to see.
_TEXT_TOKENS = ("--ink", "--ink-soft", "--link", "--link-visited")
_PAGE_TOKEN = "--paper"


def _blocks(css: str, selector: str) -> list:
    """Each `{...}` body whose selector line contains `selector`.

    Brace-matched rather than matched by pattern, because a palette block
    holds no nested braces but an `@media` wrapper does, and a regex that
    stops at the first `}` reads the wrapper as the block.
    """
    out = []
    for hit in re.finditer(re.escape(selector), css):
        open_at = css.find("{", hit.end())
        if open_at < 0:
            continue
        depth = 0
        for i in range(open_at, len(css)):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    out.append(css[open_at + 1:i])
                    break
    return out


_VAR_RE = re.compile(r"(--[a-z0-9-]+)\s*:\s*([^;]+);")
# Named for the stylesheet it reads, because `_MEDIA_RE` above is the
# pattern that decides whether a journal publishes video or audio at all,
# and a second definition of that name silently replaced it: every
# applicability claim about media then turned on whether the stylesheet
# held an `@media` block.
_CSS_MEDIA_RE = re.compile(r"@media([^{]*)\{")


def palettes(css: str) -> Dict[str, Dict[str, str]]:
    """Every palette the stylesheet declares, resolved.

    The bundles define their colours once as custom properties and then
    override them under `prefers-color-scheme: dark` and under
    `forced-colors`, so the variables are the palette and reading them needs
    no cascade engine. Each override is returned merged over the base, which
    is what a reader in that mode actually gets.

    This is the half pa11y cannot reach: it renders a page with default
    preferences, so whatever a bundle declares for dark mode is checked by
    nothing. Writing Spaces carries two overrides and LiCS none.
    """
    base: Dict[str, str] = {}
    for body in _blocks(css, ":root"):
        for name, value in _VAR_RE.findall(body):
            base.setdefault(name, value.strip())

    out = {"base": dict(base)}
    for hit in _CSS_MEDIA_RE.finditer(css):
        condition = " ".join(hit.group(1).split())
        open_at = css.find("{", hit.start())
        depth = 0
        end = len(css)
        for i in range(open_at, len(css)):
            if css[i] == "{":
                depth += 1
            elif css[i] == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        inner = css[open_at:end]
        overrides = {n: v.strip() for n, v in _VAR_RE.findall(inner)}
        if overrides:
            merged = dict(base)
            merged.update(overrides)
            out[condition] = merged
    return out


def relative_luminance(colour: str) -> Optional[float]:
    """A colour's relative luminance, by the WCAG formula.

    None for anything that is not a plain hex triple, because a palette
    entry naming another variable or a keyword has not been resolved and a
    number invented for it would be a contrast ratio nobody measured.
    """
    text = (colour or "").strip().lstrip("#")
    if len(text) == 3:
        text = "".join(c * 2 for c in text)
    if len(text) != 6:
        return None
    try:
        parts = [int(text[i:i + 2], 16) / 255.0 for i in (0, 2, 4)]
    except ValueError:
        return None
    linear = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
              for c in parts]
    return (0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2])


def contrast_ratio(a: str, b: str) -> Optional[float]:
    """The contrast between two colours, or None where either is unresolved."""
    la, lb = relative_luminance(a), relative_luminance(b)
    if la is None or lb is None:
        return None
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def text_contrast_failures(css: str) -> list:
    """Every text colour in every palette that does not clear 1.4.3.

    Returned as `(palette, token, ratio)` so a failure says which mode and
    which entry rather than only that something is wrong. A pair this
    cannot resolve is left out rather than counted either way, by the rule
    `register.UNRUN` follows: an unresolved variable is not a finding.
    """
    out = []
    for name, palette in palettes(css).items():
        page = palette.get(_PAGE_TOKEN)
        if not page:
            continue
        for token in _TEXT_TOKENS:
            colour = palette.get(token)
            if not colour:
                continue
            ratio = contrast_ratio(colour, page)
            if ratio is not None and ratio < TEXT_CONTRAST_MIN:
                out.append((name, token, round(ratio, 2)))
    return out


def bundle_facts(template_dir: Path) -> Dict[str, bool]:
    template_dir = Path(template_dir)
    template = _read(template_dir / "article.html.j2")
    css = _read(template_dir / "article.css")
    return {
        "skip-link": bool(skip_link_target(template))
        and skip_link_is_hidden_until_focused(css),
        "focus-visible": focus_is_visible(css),
        "text-contrast": not text_contrast_failures(css),
    }


def _read(path: Path) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except OSError:
        return ""


# ---------- what the content contains ----------

@dataclass
class Content:
    """What is in the journal, as far as that decides applicability."""

    articles: int = 0
    read: int = 0
    media: int = 0
    forms: int = 0
    scripts: int = 0

    def has(self, what: str) -> Optional[bool]:
        """True, False, or None where nothing could be read."""
        if not self.read:
            return None
        return bool(getattr(self, what, 0))


def survey(articles: Sequence[dict]) -> Content:
    """Read each article's source for the things that decide whether a
    criterion engages at all.

    Not Applicable is a claim like any other, so it is made from the
    content rather than from an assumption about what a journal publishes.
    An article that cannot be read is counted out, and a journal none of
    whose articles could be read makes no applicability claims at all.
    """
    content = Content(articles=len(articles))
    for article in articles:
        try:
            body = (Path(article["project_path"]) / "article.md").read_text(
                encoding="utf-8")
        except OSError:
            continue
        content.read += 1
        if _MEDIA_RE.search(body):
            content.media += 1
        if _FORMS_RE.search(body):
            content.forms += 1
        if _SCRIPTS_RE.search(body):
            content.scripts += 1
    return content


# ---------- the report ----------

@dataclass
class Row:
    criterion: Criterion
    level: str
    remark: str
    evidence: List[str] = field(default_factory=list)
    counted: int = 0

    @property
    def tone(self) -> str:
        return {SUPPORTS: "good", PARTIAL: "warn", DOES_NOT: "bad"}.get(
            self.level, "unknown")


@dataclass
class Report:
    journal: str = ""
    generated_at: str = ""
    content: Content = field(default_factory=Content)
    rows: List[Row] = field(default_factory=list)
    covered: int = 0
    uncovered: int = 0

    def counts(self) -> Dict[str, int]:
        out: Dict[str, int] = {}
        for row in self.rows:
            out[row.level] = out.get(row.level, 0) + 1
        return out

    def note(self) -> str:
        return (
            f"Generated from the register on {self.generated_at}. Every level "
            f"above is derived from runs on record against the files as they "
            f"now stand; {self.covered} of {self.content.articles} article(s) "
            f"could be spoken for and {self.uncovered} could not, because no "
            f"run is on record against the file now on disk. A criterion with "
            f"no check behind it reads Not Evaluated rather than Supports, "
            f"which is most of WCAG and the reason the rows that do carry a "
            f"level carry a named check with them. Nothing here is a "
            f"substitute for a person reading the galley."
        )


def _levels_for(criterion: Criterion, standings: List[dict]) -> Tuple[str, int, int]:
    """(level, passing, counted) over the articles the register can speak
    for. A criterion is Supports only where every one of them passed."""
    passing = counted = 0
    for standing in standings:
        verdicts = []
        for kind, check_name in criterion.basis:
            found = standing.get(kind)
            if found is None or not found.settled:
                continue
            for finding in found.findings:
                if finding.check_name == check_name:
                    verdicts.append(finding.level)
        if not verdicts:
            continue
        counted += 1
        if all(v == "pass" for v in verdicts):
            passing += 1
    if not counted:
        return NOT_EVALUATED, 0, 0
    if passing == counted:
        return SUPPORTS, passing, counted
    if passing == 0:
        return DOES_NOT, passing, counted
    return PARTIAL, passing, counted


def report(journal_name: str, articles: Sequence[dict],
           template_dir: Optional[Path] = None,
           criteria: Sequence[Criterion] = CRITERIA) -> Report:
    """Build the report for one journal.

    `articles` are rows carrying `id` and `project_path`, the same shape
    `register.rollup` takes.
    """
    articles = [dict(a) for a in articles]
    out = Report(journal=journal_name,
                 generated_at=datetime.now(timezone.utc).strftime(
                     "%Y-%m-%d %H:%M UTC"),
                 content=survey(articles))

    standings = []
    for article in articles:
        standing = register.standing(article["id"], article["project_path"])
        standings.append(standing)
        if any(s.settled for s in standing.values()):
            out.covered += 1
        else:
            out.uncovered += 1

    bundle = bundle_facts(template_dir) if template_dir else {}

    for criterion in criteria:
        out.rows.append(_row(criterion, standings, bundle, out.content))
    out.rows.sort(key=lambda r: (_ORDER.get(r.level, 9), r.criterion.number))
    return out


def _row(criterion: Criterion, standings, bundle, content: Content) -> Row:
    if criterion.needs:
        present = content.has(criterion.needs)
        if present is None:
            return Row(criterion, NOT_EVALUATED,
                       "No article could be read, so whether this criterion "
                       "engages is unknown.")
        if not present:
            return Row(
                criterion, NOT_APPLICABLE,
                f"No {criterion.needs} in any of the {content.read} article(s) "
                f"read, so the criterion does not engage.",
                evidence=[f"source scan of {content.read} article(s)"],
                counted=content.read)
        # It does engage, and nothing here checks it.
        return Row(criterion, NOT_EVALUATED,
                   f"{getattr(content, criterion.needs)} article(s) carry "
                   f"{criterion.needs}, which nothing here checks.")

    if criterion.bundle:
        if criterion.bundle not in bundle:
            return Row(criterion, NOT_EVALUATED,
                       "The journal's template bundle was not read.")
        ok = bundle[criterion.bundle]
        return Row(criterion, SUPPORTS if ok else DOES_NOT,
                   criterion.note or "",
                   evidence=[f"journal template bundle ({criterion.bundle})"])

    if not criterion.basis:
        return Row(criterion, NOT_EVALUATED,
                   criterion.note or "No check here bears on this criterion.")

    level, passing, counted = _levels_for(criterion, standings)
    names = [f"{kind}:{check}" for kind, check in criterion.basis]
    if level == NOT_EVALUATED:
        return Row(criterion, level,
                   "No run is on record for the checks that bear on this "
                   "criterion.", evidence=names)
    remark = f"{passing} of {counted} article(s) pass."
    missing = len(standings) - counted
    if missing:
        # Said on the row rather than only in the coverage line, because a
        # reader comparing "115 of 115" against a journal of 118 should not
        # have to work out where the other three went.
        remark += (f" {missing} article(s) are not counted here: no run is "
                   f"on record for them, usually because the galley has not "
                   f"been rendered.")
    if criterion.note:
        remark += " " + criterion.note
    return Row(criterion, level, remark, evidence=names, counted=counted)


__all__ = [
    "SUPPORTS", "PARTIAL", "DOES_NOT", "NOT_EVALUATED", "NOT_APPLICABLE",
    "MEDIA", "FORMS", "SCRIPTS",
    "Criterion", "CRITERIA", "Content", "Row", "Report",
    "skip_link_target", "focus_is_visible", "skip_link_is_hidden_until_focused",
    "bundle_facts", "survey", "report",
    "palettes", "relative_luminance", "contrast_ratio",
    "text_contrast_failures", "TEXT_CONTRAST_MIN",
]
