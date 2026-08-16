"""JATS (Journal Article Tag Suite) XML emitter.

Produces JATS-archiving-1.3-conformant XML suitable for PubMed Central
ingest and most academic aggregators. Builds on the same structured-
data layer the CrossRef deposit uses (BibTeX for references; YAML
front matter for article-meta), plus the article body re-converted to
JATS via Pandoc.

Coverage focus: the article-meta is the indexer-visible surface, and
that's what we get right. The `<body>` is the Pandoc JATS output (which
handles paragraphs, lists, blockquotes, sections, and inline emphasis
correctly). References are emitted from the article's `references.bib`
when present, falling back to unstructured `<mixed-citation>` entries
parsed from the Markdown's Works Cited section.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

import pypandoc
from lxml import etree

import conversion
import crossref
import db


XLINK_NS = "http://www.w3.org/1999/xlink"
MML_NS = "http://www.w3.org/1998/Math/MathML"

NSMAP = {"xlink": XLINK_NS, "mml": MML_NS}


def _strip_namespace(xml_bytes: bytes) -> bytes:
    """Pandoc's JATS body has its own xmlns declarations; strip them
    when merging into our parent so we don't end up with duplicate
    namespace nodes."""
    text = xml_bytes.decode("utf-8") if isinstance(xml_bytes, bytes) else xml_bytes
    text = re.sub(r"\sxmlns(:[\w-]+)?=\"[^\"]*\"", "", text)
    return text.encode("utf-8")


def _body_from_pandoc(md_path: Path, journal_slug: str) -> etree._Element:
    """Convert article.md to a JATS body fragment via Pandoc, then parse
    out the `<body>` element so we can drop it into our doc."""
    extra = ["--from", "markdown+yaml_metadata_block"]
    extra.extend(conversion._citation_args(md_path.parent, journal_slug))
    jats_text = pypandoc.convert_file(
        str(md_path),
        to="jats_archiving",
        format="markdown+yaml_metadata_block",
        extra_args=extra,
    )
    # Pandoc returns a full <article>...</article>; we want only <body>.
    # Strip namespaces to avoid double-decl on insert.
    cleaned = _strip_namespace(jats_text.encode("utf-8") if isinstance(jats_text, str) else jats_text)
    try:
        root = etree.fromstring(cleaned)
    except etree.XMLSyntaxError:
        # Fall back to wrapping the raw Markdown in a single <p>.
        body = etree.Element("body")
        p = etree.SubElement(body, "p")
        p.text = md_path.read_text(encoding="utf-8")
        return body
    body = root.find(".//body")
    if body is None:
        body = etree.Element("body")
    return body


def _add_contrib(contrib_group: etree._Element, author: dict, seq: int):
    contrib = etree.SubElement(
        contrib_group, "contrib",
        attrib={"contrib-type": "author"},
    )
    name = etree.SubElement(contrib, "name")
    given = (author.get("name") or "").rsplit(" ", 1)
    if len(given) == 2:
        etree.SubElement(name, "surname").text = given[1]
        etree.SubElement(name, "given-names").text = given[0]
    else:
        etree.SubElement(name, "surname").text = author.get("name", "")

    if author.get("orcid"):
        orcid = author["orcid"]
        if not orcid.startswith("http"):
            orcid = f"https://orcid.org/{orcid}"
        contrib_id = etree.SubElement(
            contrib, "contrib-id",
            attrib={"contrib-id-type": "orcid"},
        )
        contrib_id.text = orcid
    if author.get("affiliation"):
        aff = etree.SubElement(contrib, "aff")
        etree.SubElement(aff, "institution").text = author["affiliation"]


def _add_references(back: etree._Element, article: dict):
    """Populate <ref-list> from references.bib (structured) or the
    Markdown Works Cited section (unstructured)."""
    bib_path = Path(article["project_path"]) / "references.bib"
    entries = crossref._read_bibtex(bib_path) if bib_path.exists() else []
    if not entries:
        md_text = (Path(article["project_path"]) / "article.md").read_text(encoding="utf-8")
        unstructured = crossref.extract_works_cited(md_text)
        if not unstructured:
            return
        ref_list = etree.SubElement(back, "ref-list")
        etree.SubElement(ref_list, "title").text = "References"
        for i, raw in enumerate(unstructured, start=1):
            ref = etree.SubElement(ref_list, "ref", attrib={"id": f"ref{i}"})
            mc = etree.SubElement(ref, "mixed-citation", attrib={"publication-type": "other"})
            mc.text = raw
        return

    ref_list = etree.SubElement(back, "ref-list")
    etree.SubElement(ref_list, "title").text = "References"
    for i, entry in enumerate(entries, start=1):
        ref = etree.SubElement(ref_list, "ref", attrib={"id": entry.get("ID") or f"ref{i}"})
        etype = (entry.get("ENTRYTYPE") or "").lower()
        pub_type = {
            "article": "journal",
            "book": "book",
            "incollection": "book-chapter",
            "inbook": "book-chapter",
            "inproceedings": "confproc",
            "phdthesis": "thesis",
            "mastersthesis": "thesis",
        }.get(etype, "other")
        ec = etree.SubElement(ref, "element-citation", attrib={"publication-type": pub_type})

        author_raw = entry.get("author", "")
        if author_raw:
            person_group = etree.SubElement(
                ec, "person-group", attrib={"person-group-type": "author"}
            )
            for a in re.split(r"\s+and\s+", author_raw):
                a = a.strip().strip("{}")
                if not a:
                    continue
                name_el = etree.SubElement(person_group, "name")
                if "," in a:
                    family, _, given = a.partition(",")
                    etree.SubElement(name_el, "surname").text = family.strip()
                    if given.strip():
                        etree.SubElement(name_el, "given-names").text = given.strip()
                else:
                    parts = a.split()
                    etree.SubElement(name_el, "surname").text = parts[-1] if parts else a
                    if len(parts) > 1:
                        etree.SubElement(name_el, "given-names").text = " ".join(parts[:-1])

        title = crossref._clean_bibtex_braces(entry.get("title", ""))
        if title:
            tag = "article-title" if pub_type == "journal" else "source"
            etree.SubElement(ec, tag).text = title
        journal = crossref._clean_bibtex_braces(entry.get("journal") or entry.get("journaltitle") or "")
        if journal and pub_type == "journal":
            etree.SubElement(ec, "source").text = journal
        if entry.get("year"):
            etree.SubElement(ec, "year").text = entry["year"].strip()
        if entry.get("volume"):
            etree.SubElement(ec, "volume").text = entry["volume"].strip()
        if entry.get("number") or entry.get("issue"):
            etree.SubElement(ec, "issue").text = (entry.get("number") or entry.get("issue")).strip()
        if entry.get("pages"):
            pages = entry["pages"].strip()
            parts = re.split(r"[-–—]+", pages)
            if len(parts) >= 1:
                etree.SubElement(ec, "fpage").text = parts[0].strip()
            if len(parts) >= 2:
                etree.SubElement(ec, "lpage").text = parts[1].strip()
        if entry.get("publisher"):
            etree.SubElement(ec, "publisher-name").text = crossref._clean_bibtex_braces(entry["publisher"])
        if entry.get("doi"):
            doi = etree.SubElement(ec, "pub-id", attrib={"pub-id-type": "doi"})
            doi.text = entry["doi"].strip()
        if entry.get("isbn"):
            etree.SubElement(ec, "pub-id", attrib={"pub-id-type": "isbn"}).text = entry["isbn"].strip()


def build_article_jats(article_id: int, base_url: str = "https://example.org") -> bytes:
    """Return JATS XML (bytes) for a single article."""
    art_row = db.query_one(
        "SELECT a.*, j.slug AS journal_slug, j.name AS journal_name, j.issn AS journal_issn, "
        "       j.crossref_prefix, j.crossref_member_id "
        "FROM articles a JOIN journals j ON a.journal_id = j.id WHERE a.id = ?",
        (article_id,),
    )
    if not art_row:
        raise ValueError(f"Article {article_id} not found")
    art = dict(art_row)
    issue = None
    if art.get("issue_id"):
        issue_row = db.query_one("SELECT * FROM issues WHERE id = ?", (art["issue_id"],))
        issue = dict(issue_row) if issue_row else None

    apath = Path(art["project_path"])
    fm, _ = conversion.read_article_metadata(apath)

    # Root element
    root = etree.Element(
        "article",
        attrib={
            "dtd-version": "1.3",
            "article-type": "research-article" if (art.get("kind") or "article") != "editorial" else "editorial",
            "{http://www.w3.org/XML/1998/namespace}lang": "en",
        },
        nsmap=NSMAP,
    )

    # ---- front ----
    front = etree.SubElement(root, "front")

    journal_meta = etree.SubElement(front, "journal-meta")
    journal_title_group = etree.SubElement(journal_meta, "journal-title-group")
    etree.SubElement(journal_title_group, "journal-title").text = art["journal_name"]
    if art.get("journal_issn"):
        etree.SubElement(
            journal_meta, "issn",
            attrib={"publication-format": "electronic"},
        ).text = art["journal_issn"]

    article_meta = etree.SubElement(front, "article-meta")

    if fm.get("doi") or (issue and art.get("crossref_prefix")):
        doi_value = fm.get("doi") or crossref.assign_doi(
            {"crossref_prefix": art.get("crossref_prefix"),
             "crossref_member_id": art.get("crossref_member_id")},
            issue or {"volume": 0, "issue_number": 0, "year": 0},
            art,
            art.get("order_in_issue") or 1,
        )
        etree.SubElement(
            article_meta, "article-id", attrib={"pub-id-type": "doi"}
        ).text = doi_value

    title_group = etree.SubElement(article_meta, "title-group")
    etree.SubElement(title_group, "article-title").text = fm.get("title") or art["title"]
    if fm.get("subtitle"):
        etree.SubElement(title_group, "subtitle").text = fm["subtitle"]

    contrib_group = etree.SubElement(article_meta, "contrib-group")
    for i, a in enumerate(fm.get("author") or []):
        if isinstance(a, dict):
            _add_contrib(contrib_group, a, i)
        else:
            _add_contrib(contrib_group, {"name": str(a)}, i)

    if issue:
        pub_date = etree.SubElement(
            article_meta, "pub-date",
            attrib={"date-type": "pub", "publication-format": "electronic"},
        )
        etree.SubElement(pub_date, "year").text = str(issue["year"])
        etree.SubElement(article_meta, "volume").text = str(issue["volume"])
        etree.SubElement(article_meta, "issue").text = str(issue["issue_number"])

    if art.get("start_page"):
        etree.SubElement(article_meta, "fpage").text = str(art["start_page"])
    if art.get("end_page"):
        etree.SubElement(article_meta, "lpage").text = str(art["end_page"])

    if fm.get("abstract"):
        abstract = etree.SubElement(article_meta, "abstract")
        etree.SubElement(abstract, "p").text = fm["abstract"]

    if fm.get("keywords"):
        kwd_group = etree.SubElement(article_meta, "kwd-group")
        for kw in fm["keywords"]:
            etree.SubElement(kwd_group, "kwd").text = str(kw)

    # ---- body ----
    md = apath / "article.md"
    body = _body_from_pandoc(md, art["journal_slug"])
    if body is None or len(body) == 0:
        # last-resort: empty <body>
        body = etree.SubElement(root, "body")
    else:
        root.append(body)

    # ---- back ----
    back = etree.SubElement(root, "back")
    _add_references(back, art)

    return etree.tostring(root, pretty_print=True, xml_declaration=True, encoding="UTF-8")
