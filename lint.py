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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Optional

import conversion


@dataclass
class LintResult:
    name: str           # short identifier, e.g. "orcid-format"
    level: str          # "pass", "warn", "fail"
    summary: str        # one-line summary shown in the UI
    details: list       # zero-or-more longer notes / offending items


def _ok(name: str, summary: str) -> LintResult:
    return LintResult(name=name, level="pass", summary=summary, details=[])


def _warn(name: str, summary: str, details: Optional[list] = None) -> LintResult:
    return LintResult(name=name, level="warn", summary=summary, details=details or [])


def _fail(name: str, summary: str, details: Optional[list] = None) -> LintResult:
    return LintResult(name=name, level="fail", summary=summary, details=details or [])


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


def check_alt_text(article: dict, fm: dict, body: str) -> LintResult:
    images = re.findall(r"!\[(.*?)\]\([^)]+\)", body)
    missing = sum(1 for alt in images if not alt.strip())
    if not images:
        return _ok("alt-text", "No images in the article.")
    if missing:
        return _warn(
            "alt-text",
            f"{missing} of {len(images)} image(s) have empty alt text.",
            ["Alt text is required for screen readers and tagged PDF compliance."],
        )
    return _ok("alt-text", f"All {len(images)} image(s) have alt text.")


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

DEFAULT_CHECKS: list[Callable] = [
    check_required_fields,
    check_orcid_format,
    check_doi_format,
    check_short_title_length,
    check_short_authors_length,
    check_hyperlinks,
    check_works_cited_present,
    check_citations_match_references,
    check_unstripped_artifacts,
    check_alt_text,
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
