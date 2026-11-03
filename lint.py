"""Article validation pass.

Composable per-article checks. Each check returns one of three levels:
- pass: nothing to do, content is fine.
- warn: worth knowing about; editor can ship anyway.
- fail: blocks confidence in the deposit/publish; editor should fix.

The lint pass is advisory by default; the publish workflow can later opt
to block on `fail` results. Checks are intentionally small and orthogonal
so adding a new one is cheap.

Each check returns a `LintResult`. The full pass returns a list ordered
roughly by severity then by check name.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional

import conversion
import math_alt


@dataclass
class LintResult:
    """One check's answer, with the count behind it kept as a number.

    A level says whether an article has work outstanding; it does not say
    how much, and how much is the question a journal asks first. Every
    counting check here already works the number out and then writes it
    into a sentence, so the only way to total an archive was to read those
    sentences back, which `assess.py` did with a regex over this module's
    own prose for want of anywhere better to look.

    Two rules hold `units` together. A name belongs to exactly one check,
    because `register.rollup` sums a name across articles and two checks
    both reporting `figures` would count every figure twice;
    `test_no_two_checks_claim_the_same_unit` is what holds that. And a
    passing result carries its units too, or an archive's figure count
    would be the figures in the articles that have something wrong with
    them.
    """

    name: str           # short identifier, e.g. "orcid-format"
    level: str          # "pass", "warn", "fail"
    summary: str        # one-line summary shown in the UI
    details: list       # zero-or-more longer notes / offending items
    units: dict = field(default_factory=dict)   # what it counted, by name


def _ok(name: str, summary: str, units: Optional[dict] = None,
        details: Optional[list] = None) -> LintResult:
    # `units` stays third, where every caller already passes it. A pass can
    # carry details too: a zero that means nobody has looked is worth saying
    # beside the zero.
    return LintResult(name=name, level="pass", summary=summary,
                      details=details or [], units=units or {})


def _warn(name: str, summary: str, details: Optional[list] = None,
          units: Optional[dict] = None) -> LintResult:
    return LintResult(name=name, level="warn", summary=summary,
                      details=details or [], units=units or {})


def _fail(name: str, summary: str, details: Optional[list] = None,
          units: Optional[dict] = None) -> LintResult:
    return LintResult(name=name, level="fail", summary=summary,
                      details=details or [], units=units or {})


# ---------- individual checks ----------

ORCID_RE = re.compile(r"^(?:https?://orcid\.org/)?(\d{4}-\d{4}-\d{4}-\d{3}[\dX])$")


def check_required_fields(article: dict, fm: dict, body: str) -> LintResult:
    missing = []
    for k in ("title", "short-title", "short-authors"):
        if not (fm.get(k) or "").strip() if isinstance(fm.get(k), str) else not fm.get(k):
            missing.append(k)
    if not fm.get("author"):
        missing.append("author")
    if missing:
        return _fail(
            "required-fields",
            f"{len(missing)} required field(s) missing.",
            [f"`{m}` is empty or absent." for m in missing],
        )
    return _ok("required-fields", "Required fields are present.")


def check_orcid_format(article: dict, fm: dict, body: str) -> LintResult:
    bad = []
    for a in fm.get("author") or []:
        if not isinstance(a, dict):
            continue
        orcid = (a.get("orcid") or "").strip()
        if not orcid:
            continue
        if not ORCID_RE.match(orcid):
            bad.append(f"{a.get('name', '?')}: `{orcid}` is not a well-formed ORCID.")
    if bad:
        return _warn(
            "orcid-format",
            f"{len(bad)} ORCID value(s) malformed.",
            bad,
        )
    return _ok("orcid-format", "All ORCIDs are well-formed (or absent).")


def check_doi_format(article: dict, fm: dict, body: str) -> LintResult:
    doi = (fm.get("doi") or "").strip()
    if not doi:
        return _ok("doi-format", "No DOI set (will be auto-assigned at deposit time).")
    if not re.match(r"^10\.\d{4,9}/[^\s]+$", doi):
        return _warn(
            "doi-format",
            "DOI does not match CrossRef's expected `10.NNNN/...` shape.",
            [f"Current value: `{doi}`"],
        )
    return _ok("doi-format", f"DOI `{doi}` is well-formed.")


def check_short_title_length(article: dict, fm: dict, body: str) -> LintResult:
    s = (fm.get("short-title") or "").strip()
    if not s:
        return _warn("short-title-length", "Short title is empty.")
    if len(s) > 60:
        return _warn(
            "short-title-length",
            f"Short title is {len(s)} characters; running header may overflow.",
            ["Suggested cap is ~50 characters for typical 6x9 trim."],
        )
    return _ok("short-title-length", f"Short title is {len(s)} chars (well within limits).")


# Words too short or too common to carry a typo worth flagging.
_SHORT_TITLE_STOPWORDS = {
    "a", "an", "and", "as", "at", "but", "by", "for", "from", "in", "into",
    "of", "on", "or", "the", "through", "to", "with",
}


def _word_variants(word: str) -> set:
    """A word plus plausible singular forms of it.

    Every candidate is offered rather than one guessed stem: "narratives"
    yields both "narrative" and "narrativ", and only the correct one will ever
    match anything real. Over-generating here costs nothing but stops a plural
    in the title reading as a typo in the short title.
    """
    variants = {word}
    if len(word) > 3:
        if word.endswith("ies"):
            variants.add(word[:-3] + "y")
        if word.endswith("es"):
            variants.add(word[:-2])
        if word.endswith("s") and not word.endswith("ss"):
            variants.add(word[:-1])
    return variants


def _title_words(text: str) -> set:
    """Comparable words from a title: lowercased, stripped of punctuation,
    each expanded to its singular variants."""
    cleaned = re.sub(r"[^\w\s-]", " ", (text or "").lower())
    words = {w for w in cleaned.split() if w}
    return set().union(*(_word_variants(w) for w in words)) if words else set()


def check_short_title_matches_title(article: dict, fm: dict, body: str) -> LintResult:
    """Flag a short title containing words that appear nowhere in the title.

    The short title only ever shows up in the running header, so a typo in it
    survives every proofread of the article itself. One LiCS galley ran for
    weeks with "Maginifying Dissent" across every recto page while the title
    below read "Magnifying Dissent" correctly.

    Advisory only. A short title is allowed to rephrase rather than truncate,
    and this cannot tell a deliberate rewording from a slip; it just says which
    words are not in the title so the editor can glance at them.
    """
    short = (fm.get("short-title") or "").strip()
    title = (fm.get("title") or "").strip()
    if not short or not title:
        # check_short_title_length already reports an empty short title.
        return _ok("short-title-matches", "No short title or title to compare.")

    title_words = _title_words(title)
    cleaned_short = re.sub(r"[^\w\s-]", " ", short.lower())
    unmatched = [
        word for word in sorted({w for w in cleaned_short.split() if w})
        if len(word) > 2
        and word not in _SHORT_TITLE_STOPWORDS
        and not (_word_variants(word) & title_words)
    ]
    if unmatched:
        return _warn(
            "short-title-matches",
            "Short title has word(s) not in the title: "
            + ", ".join(repr(w) for w in unmatched) + ".",
            [
                "The short title appears only in the running header, so a typo "
                "there is easy to miss.",
                f"Title: {title}",
                f"Short title: {short}",
                "Ignore this if the short title deliberately rephrases the title.",
            ],
        )
    return _ok(
        "short-title-matches",
        "Every word of the short title appears in the title.",
    )


def check_short_authors_length(article: dict, fm: dict, body: str) -> LintResult:
    s = (fm.get("short-authors") or "").strip()
    if not s:
        return _warn("short-authors-length", "Short authors is empty.")
    if len(s) > 60:
        return _warn(
            "short-authors-length",
            f"Short authors is {len(s)} characters; running header may overflow.",
        )
    return _ok("short-authors-length", f"Short authors is {len(s)} chars.")


_URL_RE = re.compile(r"\bhttps?://[^\s)\]>]+", re.IGNORECASE)
_GOOD_URL_RE = re.compile(r"^https?://[\w\-\.]+(:\d+)?(/[^\s]*)?$", re.IGNORECASE)


def check_hyperlinks(article: dict, fm: dict, body: str) -> LintResult:
    urls = _URL_RE.findall(body)
    bad = [u for u in urls if not _GOOD_URL_RE.match(u.rstrip(".,;:"))]
    if bad:
        return _warn(
            "hyperlink-format",
            f"{len(bad)} URL(s) look malformed.",
            list(dict.fromkeys(bad))[:10],
        )
    return _ok("hyperlink-format", f"All {len(urls)} URL(s) look well-formed.")


def check_works_cited_present(article: dict, fm: dict, body: str) -> LintResult:
    heading_re = re.compile(
        r"^#{1,6}\s+(works cited|references|bibliography)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    if heading_re.search(body):
        return _ok("works-cited", "A Works Cited / References section is present.")
    return _warn(
        "works-cited",
        "No Works Cited / References section detected.",
        ["Articles without a references section will deposit with no `<citation>` elements."],
    )


_INTEXT_CITE_RE = re.compile(r"\(([A-Z][\w\-’']+(?:\s+(?:and|&)\s+[A-Z][\w\-’']+)?(?:\s+et\s+al\.?)?)(?:\s+\d{4})?[,;\s][^)]*\)")


def check_citations_match_references(article: dict, fm: dict, body: str) -> LintResult:
    """Best-effort: extract surnames cited in body, surnames in the
    Works Cited entries, and report mismatches.

    Heuristic-only — final coverage waits on the BibTeX citation system.
    """
    heading_re = re.compile(
        r"^#{1,6}\s+(works cited|references|bibliography)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    m = heading_re.search(body)
    if not m:
        return _ok(
            "citation-coverage",
            "Skipped: no Works Cited section to check against.",
        )

    body_text = body[:m.start()]
    refs_text = body[m.end():]

    intext = set()
    for citation in _INTEXT_CITE_RE.findall(body_text):
        surname = citation.split()[0].rstrip(",;.")
        if surname.lower() in {"the", "see", "cf", "i", "we", "my", "our"}:
            continue
        intext.add(surname)

    refs_surnames = set()
    for line in refs_text.split("\n"):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m2 = re.match(r"^([A-Z][\w\-’']+)", line)
        if m2:
            refs_surnames.add(m2.group(1))

    if not intext or not refs_surnames:
        return _ok(
            "citation-coverage",
            "Skipped: not enough citations to compare.",
        )

    cited_not_in_refs = sorted(intext - refs_surnames)
    refs_not_cited = sorted(refs_surnames - intext)
    findings = []
    if cited_not_in_refs:
        findings.append(
            f"In-text without a matching Works Cited entry: "
            + ", ".join(f"`{s}`" for s in cited_not_in_refs[:15])
            + (f" (+{len(cited_not_in_refs) - 15} more)" if len(cited_not_in_refs) > 15 else "")
        )
    if refs_not_cited:
        findings.append(
            f"Works Cited entries never referenced: "
            + ", ".join(f"`{s}`" for s in refs_not_cited[:15])
            + (f" (+{len(refs_not_cited) - 15} more)" if len(refs_not_cited) > 15 else "")
        )

    if findings:
        return _warn(
            "citation-coverage",
            "Possible citation mismatches (heuristic).",
            findings + ["Final accuracy depends on a BibTeX-backed citation system."],
        )
    return _ok("citation-coverage", "In-text citations and Works Cited surnames align.")


def check_unstripped_artifacts(article: dict, fm: dict, body: str) -> LintResult:
    """Warn about leftover Pandoc artifacts that the cleanup should have
    removed but might have missed."""
    issues = []
    if "{.mark}" in body:
        issues.append("`{.mark}` highlighter spans remain (re-run cleanups).")
    if "{.underline}" in body:
        issues.append("`{.underline}` underline spans remain (re-run cleanups).")
    if re.search(r"^\s*\\\|", body, re.MULTILINE):
        issues.append("Hard-line-break heading separators (`\\|`) remain.")
    if "_typst_str" in body or "_typst_inline_md" in body:
        issues.append("Stray Python helper names in body — bug, please report.")
    if issues:
        return _warn(
            "cleanup-artifacts",
            f"{len(issues)} cleanup-pass artifact(s) leaked through.",
            issues,
        )
    return _ok("cleanup-artifacts", "No leftover cleanup-pass artifacts.")


# `src` is captured so one pattern serves the counting here and the queue in
# `describe.py`, which needs the asset path to address a figure by and to
# write a description back to. The alt is lazy for the reason
# `conversion._BODY_IMAGE_RE` spells it that way: a description may carry a
# bracket of its own.
_IMAGE_RE = re.compile(
    r"!\[(?P<alt>.*?)\]\((?P<src>[^)]+)\)(?:\{(?P<attrs>[^}]*)\})?")
_ALT_ATTR_RE = re.compile(r"\balt\s*=")
# The attribute slot `pair_figure_captions` writes a description into,
# as against a plain `alt=`, which Pandoc passes through and which
# `_ALT_ATTR_RE` also matches.
_FIG_ALT_ATTR_RE = re.compile(r"\bfig-alt\s*=")

# What a figure is owed, as `check_alt_text` reads it. The four are
# exhaustive and disjoint: `figure_state` returns exactly one of them.
MISSING = "missing"
UNDESCRIBED = "undescribed"
FROM_CAPTION = "caption"
DESCRIBED = "described"
OWED = (MISSING, UNDESCRIBED, FROM_CAPTION)

# A figure and the caption printed under it are one paragraph joined by a
# hard line break, so the caption is the line after the backslash.
_FOLLOWING_LINE_RE = re.compile(r"\\?\s*(?P<line>[^\n]*)")

# How much of an alt text is tested against the caption beside it. Compared
# on a prefix and not whole: these captions run to several hundred
# characters, so testing whether the alt text sits inside the caption meant
# testing a long string against a window that cut it off, and every long
# caption came back as a real description.
CAPTION_PROBE = 80


def alt_is_caption(alt: str, caption: str) -> bool:
    """Whether this alt text is the caption standing in for a description.

    One predicate, because the same judgement is made about a figure in
    Markdown here and about an `<img>` in a stranger's HTML in `assess.py`,
    and a window that differed between the two would report the same figure
    as a draft in one place and as described in the other.
    """
    probe = (alt or "").strip()[:CAPTION_PROBE].lower()
    return bool(probe and caption and probe in caption.lower())


def printed_caption(match, body: str) -> str:
    """The caption the page printed under this figure, if it printed one.

    Told from prose by the label it opens with, through
    `conversion._CAPTION_START_RE`, which is the pattern that already knows
    the three ways this series abbreviates one. Matching only "Figure 1"
    reads volume 2 as a book that captions nothing, since it prints "Fig. 1."
    over all seventeen of its captions, and volume 6 prints "Fig 1.0". That
    cost 13 of this archive's 167 captions, twice over: the draft count
    below could not see that the alt text was the caption, and the queue in
    `describe.py` had nothing to put beside the field, which is the one thing
    on that screen somebody writing a description would want.

    The label alone decides it here, without `pdf_ingest.is_figure_caption`'s
    further test that a capital follows, because the line this reads is the
    line a hard break joined to the figure and that is the caption by
    construction. Run over the archive, all 167 of the lines it reads
    continue with a capital or a quotation mark and none is prose referring
    to a figure, so the looser test costs nothing; the capital does the work
    where the question is which lines on a page are captions at all.
    """
    following = body[match.end():match.end() + 2000]
    line = _FOLLOWING_LINE_RE.match(following)
    text = line.group("line").strip() if line else ""
    return text if looks_like_a_caption(text) else ""


def looks_like_a_caption(text: str) -> bool:
    """Whether this line opens with a figure label the way a caption does.

    A caption names a figure and so carries its number; a description does
    not. `assess.py` leans on the same test to tell two things apart that
    the markup states identically: a caption a converter copied into the
    alt text, which is work still owed, and a description a renderer also
    printed as the caption, which is work already done.
    """
    return bool(conversion._CAPTION_START_RE.match((text or "").strip()))


def figure_state(match, body: str) -> str:
    """Which of the four states this figure is in.

    One function, because `check_alt_text` counts these and `describe.py`
    queues them. Two readings of one figure is the failure with no symptom:
    the register would report a description as owed while the queue never
    showed the figure, so nobody would write it, and where that surfaces is
    a reader hearing nothing.

    A description can sit in either slot and `conversion._carried_description`
    knows which. A figure through `pair_figure_captions` keeps the printed
    caption in the bracket and the description in `fig-alt`, so a reader that
    looks only at the bracket sees a caption there and reports a description
    as still owed that somebody has already written. Reading the bracket
    alone is the mistake this codebase has made three times;
    `test_both_slots_are_read_the_same_way` pins it.
    """
    alt = match.group("alt").strip()
    elsewhere = conversion._carried_description(match)
    attrs = match.group("attrs") or ""
    if elsewhere and elsewhere != alt:
        return DESCRIBED
    if not elsewhere and _FIG_ALT_ATTR_RE.search(attrs):
        # The description slot is `fig-alt` and it holds no description, so
        # whatever the bracket carries is this figure's caption.
        return UNDESCRIBED
    if not alt and not _ALT_ATTR_RE.search(attrs):
        return MISSING
    if _UNDESCRIBED_ALT_RE.match(alt):
        return UNDESCRIBED
    # PDF ingest puts a figure above the caption printed under it and takes
    # the alt text from that caption. The two are not the same thing: a
    # caption says what a figure is called, alt text says what is in it.
    # Counted so the editing still owed is countable.
    if alt_is_caption(alt, printed_caption(match, body)):
        return FROM_CAPTION
    return DESCRIBED


def check_alt_text(article: dict, fm: dict, body: str) -> LintResult:
    """Flag images with no alt text.

    This is a fail rather than a warn because galleys compile as PDF/UA-1:
    Typst refuses an image that carries no alt text, so a single one costs
    the article its conformance and renders it through the fallback path in
    `conversion._compile_typst` instead. An explicit `{alt="..."}` attribute
    counts, since Pandoc passes that straight through to Typst.
    """
    counts = {MISSING: 0, UNDESCRIBED: 0, FROM_CAPTION: 0, DESCRIBED: 0}
    total = 0
    for match in _IMAGE_RE.finditer(body):
        total += 1
        counts[figure_state(match, body)] += 1
    if not total:
        return _ok("alt-text", "No images in the article.", {"figures": 0})
    missing = counts[MISSING]
    undescribed = counts[UNDESCRIBED]
    from_caption = counts[FROM_CAPTION]
    units = {
        "figures": total,
        "figures-no-alt": missing,
        "figures-undescribed": undescribed,
        "figures-caption-as-alt": from_caption,
        "figures-described": counts[DESCRIBED],
    }
    if missing:
        return _fail(
            "alt-text",
            f"{missing} of {total} image(s) have no alt text.",
            [
                "Screen readers announce nothing for these images.",
                "Typst cannot compile an image without alt text as PDF/UA-1, "
                "so the PDF falls back to a non-conformant render and will be "
                "flagged in an accessibility audit.",
            ],
            units,
        )
    if undescribed or from_caption:
        details = []
        if undescribed:
            details.append(
                f"{undescribed} came off a page that printed no caption, so "
                f"the alt text says only that it is undescribed. A reader "
                f"hearing it learns nothing about the figure."
            )
        if from_caption:
            details.append(
                f"{from_caption} carry their printed caption as alt text. "
                f"That keeps the galley conformant and is a reasonable "
                f"starting point, but a caption names a figure where alt "
                f"text has to describe it."
            )
        return _warn(
            "alt-text",
            f"{undescribed + from_caption} of {total} image(s) need a "
            f"written description.",
            details,
            units,
        )
    return _ok("alt-text", f"All {total} image(s) have alt text.", units)


_UNDESCRIBED_ALT_RE = re.compile(r"^Undescribed figure from page \d+")


def check_figure_coverage(article: dict, fm: dict, body: str) -> LintResult:
    """Flag an article that refers to figures it does not contain.

    check_alt_text cannot see this and reads it as a pass: it tests whether
    an image lacks alt text, so an article whose figures were never extracted
    holds no images to fail and comes back "No images in the article". Both
    volumes of Writing Spaces passed that way while between them referring to
    258 figures that were not there.
    """
    references = set(_FIGURE_NUMBER_RE.findall(body))
    images = len(_IMAGE_RE.findall(body))
    if not references:
        return _ok("figure-coverage", "The text refers to no figures.",
                   {"figures-referred-to": 0, "figures-referred-absent": 0})
    if images:
        return _ok(
            "figure-coverage",
            f"{len(references)} figure(s) referred to, {images} image(s) "
            f"present.",
            {"figures-referred-to": len(references),
             "figures-referred-absent": 0},
        )
    return _warn(
        "figure-coverage",
        f"The text refers to {len(references)} figure(s) and contains none.",
        [
            "A reader is told to look at something that is not in the galley.",
            "Figures referred to: "
            + ", ".join(sorted(references)[:12]),
        ],
        {"figures-referred-to": len(references),
         "figures-referred-absent": len(references)},
    )


# "Figure 7.3" anywhere in the prose, which is how this series refers to one.
_FIGURE_NUMBER_RE = re.compile(r"\bFigure\s+(\d+(?:\.\d+)*)")


_FIG_LABEL_RE = re.compile(r"!\[[^\]]*\]\([^)]+\)\s*\{[^}]*#(fig:[a-zA-Z0-9_-]+)")
_FIG_REF_RE = re.compile(r"\[?@(fig:[a-zA-Z0-9_-]+)\]?")


def check_figure_references(article: dict, fm: dict, body: str) -> LintResult:
    """Verify that every @fig:X reference points at an image with that
    identifier, and that no figure is defined twice."""
    labels = _FIG_LABEL_RE.findall(body)
    refs = _FIG_REF_RE.findall(body)
    if not labels and not refs:
        return _ok("figure-references", "No figures or references.")

    label_set = set(labels)
    dups = sorted({l for l in labels if labels.count(l) > 1})

    refs_set = set(refs)
    refs_missing = sorted(refs_set - label_set)
    unreferenced = sorted(label_set - refs_set)

    findings = []
    if dups:
        findings.append("Duplicate figure labels: " + ", ".join(f"`{d}`" for d in dups))
    if refs_missing:
        findings.append(
            "References to undefined figures: " + ", ".join(f"`@{r}`" for r in refs_missing)
        )
    if unreferenced:
        findings.append(
            "Figures never referenced in text: " + ", ".join(f"`{l}`" for l in unreferenced)
        )

    if not findings:
        return _ok(
            "figure-references",
            f"All {len(refs)} cross-reference(s) resolve; {len(labels)} figure(s) defined.",
        )
    return _warn(
        "figure-references",
        f"{len(findings)} figure-reference issue(s).",
        findings,
    )


# ---------- runner ----------

_UNREADABLE_RE = re.compile(
    r"[-\U000f0000-\U0010fffd]"   # private use, both planes
    r"|[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]"  # C0 and C1 controls
)


def check_unreadable_characters(article: dict, fm: dict, body: str) -> LintResult:
    """Flag characters that no reader can read.

    A private use codepoint has no meaning: it is whatever the font that
    put it there decided, so a screen reader announces nothing or guesses.
    They arrive from symbol fonts, where Wingdings byte 0xFC comes out as
    U+F0FC rather than as the check mark it prints; `pdf_ingest` translates
    the ones this archive uses, and this catches whatever a new source
    brings in that it does not know.

    It is a fail rather than a warn because it costs the galley more than
    its legibility. Typst validates PDF/UA rather than declaring it, so one
    of these aborts the compile, `_compile_typst` falls back to an
    unconstrained render, and the chapter ships without the conformance
    identifier an accessibility audit looks for.
    """
    found = _UNREADABLE_RE.findall(body)
    if not found:
        return _ok("unreadable-characters",
                   "No private use or control characters.",
                   {"unreadable-characters": 0})
    counts: dict = {}
    for ch in found:
        counts[ch] = counts.get(ch, 0) + 1
    details = [
        f"U+{ord(ch):04X} appears {n} time(s); it has no meaning outside "
        f"the font that wrote it."
        for ch, n in sorted(counts.items(), key=lambda kv: -kv[1])
    ]
    return _fail(
        "unreadable-characters",
        f"{len(found)} character(s) no reader can read.",
        details,
        {"unreadable-characters": len(found)},
    )


def check_images_of_text(article: dict, fm: dict, body: str) -> LintResult:
    """Report figures whose content is text set as a picture.

    This is WCAG 1.4.5, and it is a different failure from a missing
    description: writing alt text satisfies 1.1.1 and leaves 1.4.5 exactly
    where it was. The words are still unavailable to anyone who cannot see
    the image, they cannot be searched, selected, translated or reflowed,
    and they do not respond to a reader's own type size.

    A figure is listed here by hand, in the article's `images-of-text` front
    matter, because nothing can tell a photograph of a document from a
    photograph of anything else without looking. 113 of this series' 196
    figures are on that list, which is a property of what the books are:
    a technical writing volume teaches a genre by showing one.

    A warning rather than a failure. The galley is conformant and the
    figure is described; what is wanted is that the shortfall stays
    countable instead of being closed over by the alt text.

    The field being there at all is a second record, and it is read here
    because an empty list and no list are different answers. Absent means
    nobody has looked; empty means somebody looked at the figures and found
    none carrying text, which is why `conversion.write_article_metadata`
    keeps an empty one where it drops every other empty field. Collapsing
    the two leaves a zero nobody can read, and it leaves the lane in
    `describe.py` unfinishable for a chapter whose honest answer is none.
    `register.UNRUN` exists to keep the same hole out of the register: no is
    a finding and nobody asked is not. The level does not turn on it, since
    an unjudged chapter owes somebody's attention rather than a fix, and
    `figures-judged-for-text` is what counts the attention already paid.
    """
    judged = "images-of-text" in fm
    listed = fm.get("images-of-text") or []
    if isinstance(listed, str):
        listed = [listed]
    images = len(_IMAGE_RE.findall(body))
    # The figure count belongs to `check_alt_text`, which reads the same
    # images; reporting it here too would double every figure in the rollup.
    units = {"images-of-text": len(listed),
             "figures-judged-for-text": images if judged else 0}
    if not listed:
        if not images:
            return _ok("images-of-text", "No images in the article.", units)
        if judged:
            return _ok(
                "images-of-text",
                f"None of the {images} figure(s) carries text as a picture.",
                units)
        return _ok("images-of-text", "No figure is recorded as text.", units,
                   [f"Nobody has judged these {images} figure(s) for text as "
                    f"a picture, so the zero is an open question and not a "
                    f"finding."])
    return _warn(
        "images-of-text",
        f"{len(listed)} of {images} figure(s) carry text as a picture.",
        [
            "Described, but the words themselves are still only a picture "
            "(WCAG 1.4.5); transcribing them into the chapter is the fix.",
            "Figures: " + ", ".join(str(x) for x in listed[:12]),
        ],
        units,
    )


def check_math_alt_text(article: dict, fm: dict, body: str) -> LintResult:
    """Report equations with no spoken description.

    PDF/UA-1 wants a formula read aloud the way it wants a figure
    described, and Typst enforces it, so before `math_alt.py` existed one
    equation cost an article its conformance identifier and nothing said
    so: `check_alt_text` reads Markdown image syntax, and an equation is
    not an image.

    A warning rather than a failure, which is the difference between this
    and `check_alt_text`. Every equation now carries alt text by the time
    it reaches Typst, so the galley conforms either way; what is at stake
    is whether a reader hears the formula or hears that there is one.
    `check_images_of_text` draws the line in the same place and for the
    same reason, and the point of both is that the shortfall stays
    countable rather than being closed over.

    An expression this reads aloud is read correctly, since `math_alt`
    declines whole rather than guessing, so a generated description is
    reported and not flagged.
    """
    found = math_alt.expressions(body)
    if not found:
        return _ok("math-alt-text", "No equations in the article.",
                   {"equations": 0})
    descriptions = math_alt.author_descriptions(fm)
    counts = {math_alt.AUTHOR: 0, math_alt.GENERATED: 0,
              math_alt.UNDESCRIBED_SOURCE: 0}
    undescribed = []
    for expr in found:
        _alt, source = math_alt.alt_for(expr.tex, descriptions)
        counts[source] += 1
        if source == math_alt.UNDESCRIBED_SOURCE:
            undescribed.append(expr.tex)
    total = len(found)
    units = {
        "equations": total,
        "equations-undescribed": counts[math_alt.UNDESCRIBED_SOURCE],
        "equations-author-described": counts[math_alt.AUTHOR],
        "equations-generated": counts[math_alt.GENERATED],
    }
    if not counts[math_alt.UNDESCRIBED_SOURCE]:
        return _ok(
            "math-alt-text",
            f"All {total} equation(s) have a spoken description.",
            units,
        )
    details = [
        "A screen reader announces only that an equation is there. Write "
        "the reading into the article's `math-alt` front matter, keyed by "
        "the expression as it appears in the body.",
    ]
    if counts[math_alt.GENERATED]:
        details.append(
            f"{counts[math_alt.GENERATED]} other(s) are read aloud from "
            f"the expression itself, which needs no editing."
        )
    details.append("Undescribed: " + "; ".join(undescribed[:8]))
    return _warn(
        "math-alt-text",
        f"{len(undescribed)} of {total} equation(s) have no spoken "
        f"description.",
        details,
        units,
    )


DEFAULT_CHECKS: list[Callable] = [
    check_required_fields,
    check_orcid_format,
    check_doi_format,
    check_short_title_length,
    check_short_title_matches_title,
    check_short_authors_length,
    check_hyperlinks,
    check_works_cited_present,
    check_citations_match_references,
    check_unstripped_artifacts,
    check_unreadable_characters,
    check_alt_text,
    check_math_alt_text,
    check_images_of_text,
    check_figure_coverage,
    check_figure_references,
]


def run(article: dict, checks: Optional[Iterable[Callable]] = None) -> list[LintResult]:
    apath = Path(article["project_path"])
    fm, body = conversion.read_article_metadata(apath)
    results = []
    for check in (checks or DEFAULT_CHECKS):
        try:
            results.append(check(article, fm, body))
        except Exception as exc:
            results.append(_fail(
                check.__name__,
                f"Check crashed: {type(exc).__name__}: {exc}",
            ))
    # Order: fails first, then warns, then passes; within each by check name
    severity = {"fail": 0, "warn": 1, "pass": 2}
    results.sort(key=lambda r: (severity.get(r.level, 99), r.name))
    return results
