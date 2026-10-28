"""Ingest a whole volume of published chapter PDFs in one pass.

Usage:
    python ingest_volume.py <journal-slug> <directory-of-pdfs> [options]

    --manifest FILE     JSON of per-chapter metadata keyed by PDF filename
    --volume-title STR  e.g. "Writing Spaces 5"; sets the margin tab
    --volume N          volume number
    --year YYYY
    --dry-run           report what would happen; touch nothing
    --limit N           stop after N chapters (for a trial run)
    --skip-existing     leave an already-ingested chapter alone (default)
    --replace           re-ingest a chapter that already exists
    --stop-on-error     halt on the first failure instead of carrying on

The directory holds one PDF per chapter, as the WAC Clearinghouse serves
them. Download it yourself and point this at the folder: the runner never
fetches anything, so a volume cannot be pulled down by accident, and an
editor can see what they are about to ingest before it is ingested.

Chapter order and authorship come from the manifest where one is given.
Without it they are read from the filename, which that archive encodes as
chapter number followed by surnames ("1Lester-Lucas-Doyle-Overcash.pdf").
That is a convention, not a guarantee, so the runner reports what it
inferred for each file and `--dry-run` shows the whole plan first.

This is a reading of typeset pages, not a conversion of structured source.
Everything `pdf_ingest` infers can be wrong, and nothing here is published
automatically: chapters land as drafts for an editor to check against the
original.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import conversion
import db


# "1Lester-Lucas-Doyle-Overcash.pdf" -> chapter 1, surnames Lester, Lucas, ...
FILENAME_RE = re.compile(r"^(?P<number>\d{1,3})(?P<names>[A-Za-z][A-Za-z\-']*)?$")
# Files the archive ships alongside the chapters that are not chapters.
NON_CHAPTER = {"acknowledgments", "contributors", "frontmatter", "front-matter",
               "introduction", "index", "cover", "toc", "copyright"}


@dataclass
class Chapter:
    pdf: Path
    number: Optional[int] = None
    title: Optional[str] = None
    authors: list = field(default_factory=list)
    slug: str = ""
    note: str = ""
    is_chapter: bool = True


def slugify(text: str) -> str:
    """Same rule app.py uses, so a batch-made slug matches a hand-made one."""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "chapter"


def parse_filename(pdf: Path) -> tuple:
    """Chapter number and surnames inferred from an archive filename.

    Returns (number, surnames, note). The note records what was inferred so
    the run log can say, rather than leaving the editor to guess why a
    chapter sorted where it did.
    """
    stem = pdf.stem.strip()
    if stem.lower() in NON_CHAPTER:
        return None, [], "not a chapter (front or back matter)"
    match = FILENAME_RE.match(stem)
    if not match:
        return None, [], "filename carries no chapter number"
    number = int(match.group("number"))
    raw = match.group("names") or ""
    surnames = [n for n in raw.split("-") if n]
    return number, surnames, f"chapter {number} from the filename"


def load_manifest(path: Optional[Path]) -> dict:
    """Per-chapter metadata keyed by PDF filename.

    Shape, with every field optional:

        {"1Lester-Lucas-Doyle-Overcash.pdf": {
            "chapter-number": 1,
            "title": "We Write Because We Care",
            "authors": ["Glenn Lester", "Taylor Lucas"],
            "slug": "we-write-because-we-care"}}

    A manifest always wins over the filename and over what the PDF's own
    pages say, because it is the one source a person checked.
    """
    if not path:
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Manifest must be a JSON object keyed by PDF filename.")
    return data


def plan(pdf_dir: Path, manifest: dict) -> list:
    """Work out what each PDF is, and in what order to take them."""
    chapters = []
    for pdf in sorted(pdf_dir.glob("*.pdf")):
        entry = manifest.get(pdf.name, {})
        number, surnames, note = parse_filename(pdf)
        is_chapter = "not a chapter" not in note
        if entry.get("chapter-number") is not None:
            number = int(entry["chapter-number"])
            note = "chapter number from the manifest"
        title = entry.get("title")
        authors = entry.get("authors") or []
        slug = entry.get("slug") or ""
        if not slug:
            if title:
                slug = slugify(title)
            elif number is not None and surnames:
                slug = slugify(f"{number}-{'-'.join(surnames)}")
            else:
                slug = slugify(pdf.stem)
        chapters.append(Chapter(pdf=pdf, number=number, title=title,
                                authors=authors, slug=slug, note=note,
                                is_chapter=is_chapter or number is not None))
    # Numbered chapters in order, then anything unnumbered, by filename. A
    # volume's front and back matter sorts to the end rather than being
    # dropped: the editor decides whether to keep it.
    chapters.sort(key=lambda c: (c.number is None, c.number or 0, c.pdf.name))
    return chapters


def existing_sources(journal_id: int) -> dict:
    """Map each already-ingested source filename to its article row.

    Matching on the slug alone is not enough. A slug is built from the title
    where one is known, so the same PDF ingested with and without a manifest
    lands under two different slugs and is taken in twice. `source-file` is
    what the chapter actually came from, and it does not move.
    """
    index: dict = {}
    for row in db.query_all(
        "SELECT id, slug, project_path FROM articles WHERE journal_id = ?",
        (journal_id,),
    ):
        md = Path(row["project_path"]) / "article.md"
        if not md.exists():
            continue
        try:
            fm, _ = conversion.read_article_metadata(Path(row["project_path"]))
        except Exception:
            continue
        name = fm.get("source-file")
        if name:
            index[str(name)] = dict(row)
    return index


def ingest_one(chapter: Chapter, journal: dict, defaults: dict,
               replace: bool, by_source: dict,
               teacher_mode: str = "separate") -> tuple:
    """Ingest one chapter. Returns (status, detail)."""
    existing = by_source.get(chapter.pdf.name)
    if existing is None:
        row = db.query_one(
            "SELECT id, slug, project_path FROM articles "
            "WHERE journal_id = ? AND slug = ?",
            (journal["id"], chapter.slug),
        )
        existing = dict(row) if row else None
    if existing and not replace:
        return "skipped", (f"already ingested as article {existing['id']} "
                           f"({existing['slug']})")

    apath = conversion.article_dir(journal["slug"], None, chapter.slug)
    conversion.ingest_pdf(chapter.pdf, apath)
    conversion.run_cleanups(apath)

    fm, body = conversion.read_article_metadata(apath)
    # The manifest and the command line describe the volume; the PDF's own
    # pages describe the chapter. Volume facts are applied over whatever the
    # pages happened to carry, chapter facts only where the pages gave none.
    for key, value in defaults.items():
        if value is not None:
            fm[key] = value
    if chapter.number is not None:
        fm["chapter-number"] = chapter.number
    elif not chapter.is_chapter:
        # Front and back matter is not chapter N of anything. The extractor
        # reads a number off the opening page whenever one is printed there,
        # and acknowledgments pages have been known to carry one.
        fm.pop("chapter-number", None)
    if chapter.title:
        fm["title"] = chapter.title
    if chapter.authors:
        fm["author"] = [{"name": n} for n in chapter.authors]
    if teacher_mode == "separate" and conversion.split_teacher_resources(body)[1].strip():
        # The series puts a block addressed to instructors behind its own
        # title page at the back of every chapter. Marking it here is what
        # makes it render as a galley of its own.
        fm.setdefault("teacher-resources", "separate")
    fm.setdefault("short-title", _short_title(fm.get("title") or chapter.slug))
    fm.setdefault("short-authors", _short_authors(fm.get("author") or []))
    conversion.write_article_metadata(apath, fm, body)

    title = conversion.plain_text(fm.get("title")) or chapter.slug
    if existing:
        db.execute(
            "UPDATE articles SET title = ?, project_path = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (title, str(apath), existing["id"]),
        )
        return "replaced", f"article {existing['id']}"
    try:
        article_id = db.execute(
            "INSERT INTO articles (journal_id, slug, title, project_path, status) "
            "VALUES (?, ?, ?, ?, 'draft')",
            (journal["id"], chapter.slug, title, str(apath)),
        )
    except sqlite3.IntegrityError as exc:
        return "failed", f"slug collision: {exc}"
    return "ingested", f"article {article_id}"


def _short_title(title: str) -> str:
    """A running head has about four inches to work with, so a long title is
    cut at its subtitle rather than wrapped into the margin."""
    text = re.sub(r"\s+", " ", str(title)).strip()
    return text.split(":")[0].strip()[:60] or text[:60]


def _short_authors(authors: list) -> str:
    names = []
    for a in authors:
        name = a.get("name") if isinstance(a, dict) else str(a)
        surname = str(name or "").strip().split()[-1:] or [""]
        if surname[0]:
            names.append(surname[0])
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) == 2:
        return f"{names[0]} and {names[1]}"
    return ", ".join(names[:-1]) + f", and {names[-1]}"


def main():
    parser = argparse.ArgumentParser(
        description="Ingest a volume of chapter PDFs into a Graphion journal.")
    parser.add_argument("journal", help="journal slug, e.g. writing-spaces")
    parser.add_argument("pdf_dir", help="directory holding one PDF per chapter")
    parser.add_argument("--manifest", help="JSON of per-chapter metadata")
    parser.add_argument("--volume-title", dest="volume_title")
    parser.add_argument("--volume", type=int)
    parser.add_argument("--year", type=int)
    parser.add_argument("--limit", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace", action="store_true",
                        help="re-ingest chapters that already exist")
    parser.add_argument("--stop-on-error", action="store_true")
    parser.add_argument("--teacher-resources", dest="teacher_mode",
                        choices=("separate", "inline"), default="separate",
                        help="render a chapter's Teacher Resources as its own "
                             "galley (default) or leave it inside the chapter")
    args = parser.parse_args()

    pdf_dir = Path(args.pdf_dir)
    if not pdf_dir.is_dir():
        print(f"Not a directory: {pdf_dir}", file=sys.stderr)
        sys.exit(1)

    db.init_db()
    journal_row = db.query_one("SELECT * FROM journals WHERE slug = ?", (args.journal,))
    if not journal_row:
        print(f"No journal with slug {args.journal!r}. Create it with "
              f"new_journal.py first.", file=sys.stderr)
        sys.exit(1)
    journal = dict(journal_row)

    chapters = plan(pdf_dir, load_manifest(args.manifest))
    if not chapters:
        print(f"No PDFs found in {pdf_dir}.", file=sys.stderr)
        sys.exit(1)
    if args.limit:
        chapters = chapters[:args.limit]

    defaults = {"volume-title": args.volume_title, "volume": args.volume,
                "year": args.year}

    print(f"{len(chapters)} chapter(s) from {pdf_dir}:")
    for c in chapters:
        num = f"{c.number:>3}" if c.number is not None else "  ?"
        print(f"  {num}  {c.pdf.name:<44} -> {c.slug}")
        if c.note:
            print(f"       ({c.note})")
    if args.dry_run:
        print("\nDry run; nothing was written.")
        return

    print()
    by_source = existing_sources(journal["id"])
    counts: dict = {}
    for c in chapters:
        label = f"{c.number if c.number is not None else '?'} {c.pdf.name}"
        try:
            status, detail = ingest_one(c, journal, defaults, args.replace,
                                        by_source, args.teacher_mode)
        except Exception as exc:
            status, detail = "failed", f"{type(exc).__name__}: {exc}"
            if args.stop_on_error:
                print(f"  FAILED {label}: {detail}")
                traceback.print_exc()
                sys.exit(1)
        counts[status] = counts.get(status, 0) + 1
        print(f"  {status:<9} {label}  ({detail})")

    print("\n" + ", ".join(f"{n} {s}" for s, n in sorted(counts.items())))
    print(
        "Chapters are drafts. PDF ingest reconstructs structure from page\n"
        "layout, so check headings, paragraph breaks and hyphenation against\n"
        "the original before publishing any of them."
    )


if __name__ == "__main__":
    main()
