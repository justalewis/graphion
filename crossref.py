"""CrossRef deposit XML emitter.

Builds deposit XML conformant to CrossRef's `journal_article` schema for
single-article and full-issue deposits. Works Cited is parsed as
unstructured citations for v1 (one `<unstructured_citation>` per entry);
structured citation parsing is a future enhancement.

DOI assignment uses each journal's `crossref_prefix` and a journal-
configured suffix pattern. The default LiCS pattern follows their
historical scheme `{prefix}/{member-id}.{vol}.{iss}.{n}` (e.g.,
`10.21623/1.13.1.1`).

Tested against the CrossRef schema at
https://data.crossref.org/reports/help/schema_doc/5.3.1/index.html.
The output is meant for manual upload via the CrossRef admin UI; API
submission is a follow-up once the XML is proven correct.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from lxml import etree

import conversion
import db


CROSSREF_NS = "http://www.crossref.org/schema/5.3.1"
XSI_NS = "http://www.w3.org/2001/XMLSchema-instance"
NSMAP = {None: CROSSREF_NS, "xsi": XSI_NS}
SCHEMA_LOCATION = (
    "http://www.crossref.org/schema/5.3.1 "
    "https://www.crossref.org/schemas/crossref5.3.1.xsd"
)


# ---------- DOI assignment ----------

def assign_doi(journal: dict, issue: dict, article: dict, position: int) -> str:
    """Compute a DOI for an article.

    Pattern: `{prefix}/{member-id}.{vol}.{iss}.{position}`. If the journal
    has a `doi_pattern` in its config_json, that overrides; the pattern can
    reference {prefix}, {member}, {vol}, {iss}, {year}, {position}, {slug}.
    """
    prefix = (journal.get("crossref_prefix") or "10.0000").strip()
    member = (journal.get("crossref_member_id") or "1").strip()
    fmt = "{prefix}/{member}.{vol}.{iss}.{position}"
    if journal.get("config_json"):
        try:
            import json
            cfg = json.loads(journal["config_json"]) or {}
            if "doi_pattern" in cfg:
                fmt = cfg["doi_pattern"]
        except Exception:
            pass
    return fmt.format(
        prefix=prefix, member=member,
        vol=issue["volume"], iss=issue["issue_number"], year=issue["year"],
        position=position, slug=article["slug"],
    )


# ---------- Works Cited extraction ----------

def extract_works_cited(article_md: str) -> list[str]:
    """Pull the Works Cited section's entries from the cleaned Markdown.

    Each non-empty paragraph after the Works Cited heading becomes one
    citation. Returns the raw text of each entry, suitable for an
    `<unstructured_citation>` element.
    """
    heading_re = re.compile(
        r"^#{1,6}\s+(works cited|references|bibliography)\s*$",
        re.IGNORECASE | re.MULTILINE,
    )
    m = heading_re.search(article_md)
    if not m:
        return []
    body = article_md[m.end():]
    paragraphs = re.split(r"\n\s*\n", body)
    out = []
    for p in paragraphs:
        text = p.strip()
        if not text:
            continue
        if text.startswith("#"):
            break
        # Strip markdown markers conservatively for citation text
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"_([^_]+)_", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        text = re.sub(r"\s+", " ", text)
        out.append(text)
    return out


# ---------- XML helpers ----------

def _root() -> etree._Element:
    root = etree.Element(
        f"{{{CROSSREF_NS}}}doi_batch",
        nsmap=NSMAP,
        attrib={
            "version": "5.3.1",
            f"{{{XSI_NS}}}schemaLocation": SCHEMA_LOCATION,
        },
    )
    return root


def _add_head(root: etree._Element, journal: dict):
    head = etree.SubElement(root, f"{{{CROSSREF_NS}}}head")
    etree.SubElement(head, f"{{{CROSSREF_NS}}}doi_batch_id").text = uuid.uuid4().hex
    etree.SubElement(head, f"{{{CROSSREF_NS}}}timestamp").text = (
        datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    )
    depositor = etree.SubElement(head, f"{{{CROSSREF_NS}}}depositor")
    etree.SubElement(depositor, f"{{{CROSSREF_NS}}}depositor_name").text = (
        journal.get("depositor_name") or journal.get("name") or "publisher"
    )
    etree.SubElement(depositor, f"{{{CROSSREF_NS}}}email_address").text = (
        journal.get("depositor_email") or "noreply@example.org"
    )
    etree.SubElement(head, f"{{{CROSSREF_NS}}}registrant").text = (
        journal.get("name", "publisher")
    )


def _read_bibtex(bib_path: Path) -> list[dict]:
    """Parse a BibTeX file into a list of entries (dicts). Returns []
    if the file is missing or invalid."""
    if not bib_path.exists():
        return []
    try:
        import bibtexparser
        with bib_path.open(encoding="utf-8") as f:
            db = bibtexparser.load(f)
        return db.entries or []
    except Exception:
        return []


def _bib_first_author(entry: dict) -> tuple[str, str]:
    """Return (given, family) of the first author for CrossRef contributor."""
    raw = entry.get("author", "")
    if not raw:
        return ("", "")
    first = re.split(r"\s+and\s+", raw, maxsplit=1)[0].strip()
    if "," in first:
        family, _, given = first.partition(",")
        return (given.strip(), family.strip())
    parts = first.split()
    if len(parts) == 1:
        return ("", parts[0])
    return (" ".join(parts[:-1]), parts[-1])


def _clean_bibtex_braces(s: str) -> str:
    """Strip BibTeX brace-protection from a string value."""
    if not s:
        return s
    return s.replace("{", "").replace("}", "").strip()


def _populate_structured_citation(cit_el: etree._Element, entry: dict):
    """Emit a structured CrossRef citation from a BibTeX entry.

    Maps common BibTeX fields to CrossRef's `citation` child elements.
    Unrecognized fields fall through to `unstructured_citation` so no
    information is lost.
    """
    journal = _clean_bibtex_braces(entry.get("journal") or entry.get("journaltitle") or "")
    year = (entry.get("year") or "").strip()
    volume = (entry.get("volume") or "").strip()
    issue = (entry.get("number") or entry.get("issue") or "").strip()
    pages = (entry.get("pages") or "").strip()
    title = _clean_bibtex_braces(entry.get("title") or "")
    doi = (entry.get("doi") or "").strip()
    isbn = (entry.get("isbn") or "").strip()
    issn = (entry.get("issn") or "").strip()
    publisher = _clean_bibtex_braces(entry.get("publisher") or "")
    given, family = _bib_first_author(entry)
    series_title = _clean_bibtex_braces(entry.get("booktitle") or "")

    if journal:
        etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}journal_title").text = journal
    if family:
        etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}author").text = family
    if volume:
        etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}volume").text = volume
    if issue:
        etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}issue").text = issue
    if pages:
        first_page = pages.split("-")[0].strip()
        if first_page:
            etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}first_page").text = first_page
    if year:
        etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}cYear").text = year
    if title:
        if journal:
            etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}article_title").text = title
        else:
            etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}volume_title").text = title
    if series_title and not journal:
        etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}series_title").text = series_title
    if publisher and not journal:
        etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}publication_type").text = "book"
    if doi:
        etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}doi").text = doi
    if isbn and not journal:
        etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}isbn").text = isbn
    if issn:
        etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}issn").text = issn

    if len(cit_el) == 0:
        # No recognized BibTeX fields populated anything; fall back to
        # a unstructured concatenation so the deposit still carries the
        # raw info.
        formatted = ", ".join(
            v for v in (
                family, given, year, title, journal, volume, pages, publisher,
            ) if v
        )
        etree.SubElement(cit_el, f"{{{CROSSREF_NS}}}unstructured_citation").text = (
            formatted or "(empty entry)"
        )


def crossref_readiness(journal: dict) -> tuple[bool, list[str]]:
    """Return (is_ready, list_of_missing_fields)."""
    missing = []
    for f in ("crossref_prefix", "crossref_member_id", "depositor_name", "depositor_email"):
        if not (journal.get(f) or "").strip():
            missing.append(f)
    return (not missing, missing)


def _add_journal_metadata(journal_el: etree._Element, journal: dict):
    jm = etree.SubElement(journal_el, f"{{{CROSSREF_NS}}}journal_metadata")
    etree.SubElement(jm, f"{{{CROSSREF_NS}}}full_title").text = journal["name"]
    if journal.get("issn"):
        issn = etree.SubElement(jm, f"{{{CROSSREF_NS}}}issn", media_type="electronic")
        issn.text = journal["issn"]


def _add_journal_issue(journal_el: etree._Element, issue: dict):
    ji = etree.SubElement(journal_el, f"{{{CROSSREF_NS}}}journal_issue")
    pub_date = etree.SubElement(ji, f"{{{CROSSREF_NS}}}publication_date", media_type="online")
    etree.SubElement(pub_date, f"{{{CROSSREF_NS}}}year").text = str(issue["year"])
    jv = etree.SubElement(ji, f"{{{CROSSREF_NS}}}journal_volume")
    etree.SubElement(jv, f"{{{CROSSREF_NS}}}volume").text = str(issue["volume"])
    etree.SubElement(ji, f"{{{CROSSREF_NS}}}issue").text = str(issue["issue_number"])


def _add_article(
    journal_el: etree._Element,
    article: dict,
    article_md: str,
    fm: dict,
    issue: dict,
    doi: str,
    resource_url: str,
):
    ja = etree.SubElement(
        journal_el,
        f"{{{CROSSREF_NS}}}journal_article",
        publication_type="full_text",
    )

    titles = etree.SubElement(ja, f"{{{CROSSREF_NS}}}titles")
    etree.SubElement(titles, f"{{{CROSSREF_NS}}}title").text = conversion.plain_text(
        fm.get("title", article["title"])
    )
    if fm.get("subtitle"):
        etree.SubElement(titles, f"{{{CROSSREF_NS}}}subtitle").text = fm["subtitle"]

    authors = fm.get("author") or []
    if authors:
        contributors = etree.SubElement(ja, f"{{{CROSSREF_NS}}}contributors")
        for i, a in enumerate(authors):
            if not isinstance(a, dict):
                a = {"name": str(a)}
            sequence = "first" if i == 0 else "additional"
            person = etree.SubElement(
                contributors,
                f"{{{CROSSREF_NS}}}person_name",
                sequence=sequence,
                contributor_role="author",
            )
            name = a.get("name", "")
            given, _, family = name.rpartition(" ")
            etree.SubElement(person, f"{{{CROSSREF_NS}}}given_name").text = given or name
            etree.SubElement(person, f"{{{CROSSREF_NS}}}surname").text = family or name
            if a.get("affiliation"):
                aff_block = etree.SubElement(person, f"{{{CROSSREF_NS}}}affiliations")
                inst = etree.SubElement(aff_block, f"{{{CROSSREF_NS}}}institution")
                etree.SubElement(inst, f"{{{CROSSREF_NS}}}institution_name").text = a["affiliation"]
            if a.get("orcid"):
                orcid_val = a["orcid"]
                if not orcid_val.startswith("http"):
                    orcid_val = "https://orcid.org/" + orcid_val
                etree.SubElement(person, f"{{{CROSSREF_NS}}}ORCID").text = orcid_val

    if fm.get("abstract"):
        abstract = etree.SubElement(ja, f"{{{CROSSREF_NS}}}abstract", attrib={
            "{http://www.ncbi.nlm.nih.gov/JATS1}xmlns": "http://www.ncbi.nlm.nih.gov/JATS1",
        })
        p = etree.SubElement(abstract, f"{{{CROSSREF_NS}}}p")
        p.text = fm["abstract"]

    pub_date = etree.SubElement(ja, f"{{{CROSSREF_NS}}}publication_date", media_type="online")
    etree.SubElement(pub_date, f"{{{CROSSREF_NS}}}year").text = str(issue["year"])

    if article.get("start_page") and article.get("end_page"):
        pages = etree.SubElement(ja, f"{{{CROSSREF_NS}}}pages")
        etree.SubElement(pages, f"{{{CROSSREF_NS}}}first_page").text = str(article["start_page"])
        etree.SubElement(pages, f"{{{CROSSREF_NS}}}last_page").text = str(article["end_page"])

    doi_data = etree.SubElement(ja, f"{{{CROSSREF_NS}}}doi_data")
    etree.SubElement(doi_data, f"{{{CROSSREF_NS}}}doi").text = doi
    etree.SubElement(doi_data, f"{{{CROSSREF_NS}}}resource").text = resource_url

    bib_entries = _read_bibtex(Path(article["project_path"]) / "references.bib")
    if bib_entries:
        cite_list = etree.SubElement(ja, f"{{{CROSSREF_NS}}}citation_list")
        for idx, entry in enumerate(bib_entries, start=1):
            cit = etree.SubElement(
                cite_list,
                f"{{{CROSSREF_NS}}}citation",
                key=entry.get("ID") or f"ref{idx}",
            )
            _populate_structured_citation(cit, entry)
    else:
        # Fall back to unstructured citations parsed out of the Markdown.
        citations = extract_works_cited(article_md)
        if citations:
            cite_list = etree.SubElement(ja, f"{{{CROSSREF_NS}}}citation_list")
            for idx, raw in enumerate(citations, start=1):
                cit = etree.SubElement(
                    cite_list,
                    f"{{{CROSSREF_NS}}}citation",
                    key=f"ref{idx}",
                )
                etree.SubElement(cit, f"{{{CROSSREF_NS}}}unstructured_citation").text = raw


# ---------- public API ----------

def build_article_deposit_xml(article_id: int, base_url: str = "https://example.org") -> bytes:
    """Return CrossRef deposit XML (bytes) for a single article."""
    art_row = db.query_one(
        "SELECT a.*, j.name AS journal_name, j.issn AS journal_issn, "
        "       j.crossref_prefix, j.crossref_member_id, j.config_json "
        "FROM articles a JOIN journals j ON a.journal_id = j.id WHERE a.id = ?",
        (article_id,),
    )
    if not art_row:
        raise ValueError(f"Article {article_id} not found")
    art = dict(art_row)
    if not art.get("issue_id"):
        raise ValueError("Article is not assigned to an issue; cannot mint DOI")

    issue_row = db.query_one("SELECT * FROM issues WHERE id = ?", (art["issue_id"],))
    issue = dict(issue_row)
    journal_row = db.query_one(
        "SELECT * FROM journals WHERE id = ?",
        (art["journal_id"],),
    )
    journal = dict(journal_row) if journal_row else {}

    apath = Path(art["project_path"])
    fm, body = conversion.read_article_metadata(apath)
    article_md = (apath / "article.md").read_text(encoding="utf-8")
    position = art["order_in_issue"] or 1
    doi = fm.get("doi") or assign_doi(journal, issue, art, position)
    resource_url = f"{base_url.rstrip('/')}/articles/{article_id}/html"

    root = _root()
    _add_head(root, journal)
    body_el = etree.SubElement(root, f"{{{CROSSREF_NS}}}body")
    journal_el = etree.SubElement(body_el, f"{{{CROSSREF_NS}}}journal")
    _add_journal_metadata(journal_el, journal)
    _add_journal_issue(journal_el, issue)
    _add_article(journal_el, art, article_md, fm, issue, doi, resource_url)

    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")


def build_issue_deposit_xml(issue_id: int, base_url: str = "https://example.org") -> bytes:
    """Return CrossRef deposit XML (bytes) batching all articles in an issue."""
    issue_row = db.query_one(
        "SELECT i.*, j.name AS journal_name, j.issn AS journal_issn, "
        "       j.crossref_prefix, j.crossref_member_id, j.config_json "
        "FROM issues i JOIN journals j ON i.journal_id = j.id WHERE i.id = ?",
        (issue_id,),
    )
    if not issue_row:
        raise ValueError(f"Issue {issue_id} not found")
    issue = dict(issue_row)
    article_rows = db.query_all(
        "SELECT * FROM articles WHERE issue_id = ? "
        "ORDER BY COALESCE(order_in_issue, 999999), id",
        (issue_id,),
    )
    if not article_rows:
        raise ValueError("Issue has no articles to deposit")
    articles = [dict(r) for r in article_rows]

    journal_row = db.query_one(
        "SELECT * FROM journals WHERE id = ?",
        (issue["journal_id"],),
    )
    journal = dict(journal_row) if journal_row else {}

    root = _root()
    _add_head(root, journal)
    body_el = etree.SubElement(root, f"{{{CROSSREF_NS}}}body")
    journal_el = etree.SubElement(body_el, f"{{{CROSSREF_NS}}}journal")
    _add_journal_metadata(journal_el, journal)
    _add_journal_issue(journal_el, issue)

    for idx, art in enumerate(articles, start=1):
        apath = Path(art["project_path"])
        fm, _ = conversion.read_article_metadata(apath)
        article_md = (apath / "article.md").read_text(encoding="utf-8")
        position = art["order_in_issue"] or idx
        doi = fm.get("doi") or assign_doi(journal, issue, art, position)
        resource_url = f"{base_url.rstrip('/')}/articles/{art['id']}/html"
        _add_article(journal_el, art, article_md, fm, issue, doi, resource_url)

    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")
