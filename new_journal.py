"""Scaffold a journal, or a collection, which is the same row saying less.

Usage:
    python new_journal.py <slug> "<Full Name>" [--issn <issn>]
    python new_journal.py <slug> "<Full Name>" --collection

Creates the row and copies the LiCS template bundle to
`content/journals/<slug>/template/`. After this runs you customize it at
`/journals/<slug>/settings` and edit the bundle's CSS and Typst files.

Template bundles are versioned source, so a clone carries them while the
gitignored database starts empty. `--adopt-template` registers against the
bundle already on disk rather than refusing to overwrite it, which is what
a fresh database needs for a journal that already has one.

**A collection is somebody else's archive, taken in to be read and
remediated rather than published.** It is the same row because almost
everything about it is the same: it holds articles, it renders galleys
from a template bundle, and the accessibility register, the description
queue and the conformance report all work on it unchanged. That is the
point of the distinction being this small. Remediation in this app is
re-publication rather than repair, so a collection genuinely needs a
template the way a journal does, and a separate table would have been a
copy of `journals` with two columns missing.

What it is not is a thing you deposit. A CrossRef deposit asserts that
these DOIs are yours under your prefix, and an OJS push puts the content
into your own journal's workflow; doing either for an archive somebody
sent you to assess is a claim about ownership, not a convenience. So
those routes refuse for a collection and the pages do not offer them.
Everything else is offered, because everything else is the same work.

The slug must be unique and kebab-case-friendly (letters, digits, dashes).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

import db
from config import CONTENT_DIR

STARTER_JOURNAL_SLUG = "lics"

# What a row is for. `articles.kind` already uses this word for the same
# sort of question, so it is the word here too.
JOURNAL = "journal"
COLLECTION = "collection"
KINDS = (JOURNAL, COLLECTION)

KIND_LABELS = {
    JOURNAL: "Journal",
    COLLECTION: "Collection",
}

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")


class ScaffoldError(Exception):
    """Something that should stop the scaffold, with a sentence to show."""


def kind_of(journal) -> str:
    """What a row is, defaulting for anything written before the column.

    Read through this rather than off the row, so a NULL left by an older
    insert cannot read as neither kind and drop a real journal out of the
    CrossRef page.
    """
    try:
        value = journal["kind"]
    except (KeyError, IndexError, TypeError):
        value = None
    return value if value in KINDS else JOURNAL


def is_collection(journal) -> bool:
    return kind_of(journal) == COLLECTION


def scaffold(slug: str, name: str, issn: Optional[str] = None,
             short_name: Optional[str] = None,
             starter: str = STARTER_JOURNAL_SLUG,
             adopt_template: bool = False,
             kind: str = JOURNAL) -> dict:
    """Make the row and the template bundle. Returns what it did.

    A function rather than the body of `main()` because the browser needs
    it too: `new_journal.py` being the only way to start a journal is what
    kept this app pointed at the two archives it was written for. The
    rules stay here, the way `ingest_volume`'s and `validate_galleys`' do,
    so a journal started from a form and one started from a terminal are
    the same journal.

    Raises `ScaffoldError` for anything a caller should show and stop on;
    it writes nothing before every one of those has been checked.
    """
    if kind not in KINDS:
        raise ScaffoldError(f"Unknown kind {kind!r}; expected one of "
                            f"{', '.join(KINDS)}.")
    if not SLUG_RE.match(slug or ""):
        raise ScaffoldError(
            f"Refusing the slug {slug!r}: lowercase letters, digits and "
            f"dashes only, starting with a letter or digit.")
    if not (name or "").strip():
        raise ScaffoldError("A name is required.")
    if db.query_one("SELECT id FROM journals WHERE slug = ?", (slug,)):
        raise ScaffoldError(
            f"{slug!r} already exists. Pick another slug, or open it at "
            f"/journals/{slug}/settings.")

    dest_tpl = CONTENT_DIR / "journals" / slug / "template"
    notes = []
    if adopt_template:
        if not dest_tpl.exists():
            raise ScaffoldError(
                f"No template bundle to adopt at {dest_tpl}. Leave adopt "
                f"off to copy one from {starter!r}.")
        notes.append(f"adopted the bundle already at {dest_tpl}")
    else:
        src_tpl = CONTENT_DIR / "journals" / starter / "template"
        if not src_tpl.exists():
            raise ScaffoldError(
                f"No starter bundle at {src_tpl}. Name an existing journal "
                f"to copy the template from.")
        if dest_tpl.exists():
            raise ScaffoldError(
                f"A template bundle already exists at {dest_tpl}. Adopt it "
                f"instead, or pick a different slug.")
        shutil.copytree(src_tpl, dest_tpl)
        notes.append(f"copied the template bundle from {starter}")

    short = short_name or _initials(name)
    journal_id = db.execute(
        "INSERT INTO journals (slug, name, issn, template_path, short_name, "
        "header_label_template, kind) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (slug, name, issn or None, str(dest_tpl), short,
         "*{short_name}* {volume}.{issue} / {season}", kind),
    )
    return {"id": journal_id, "slug": slug, "name": name, "kind": kind,
            "short_name": short, "template_path": dest_tpl, "notes": notes}


def _initials(name: str) -> str:
    skip = {"in", "of", "the", "and", "for", "on", "to", "a", "an"}
    parts = [w for w in re.split(r"\s+", name) if w]
    initials = "".join(w[0] for w in parts if w.lower() not in skip)
    return initials.upper() or name[:5].upper()


def main():
    parser = argparse.ArgumentParser(
        description="Scaffold a journal or a collection in Graphion.")
    parser.add_argument("slug", help="URL-safe identifier (e.g., 'mhrj')")
    parser.add_argument("name", help='Full name (e.g., "Modern Hispanic Review Journal")')
    parser.add_argument("--issn", help="ISSN (e.g., '2326-5620')", default=None)
    parser.add_argument("--short-name", help="Short name for running headers (e.g., 'MHRJ'). Defaults to initials of `name`.", default=None)
    parser.add_argument("--collection", action="store_true",
                        help="An archive taken in to be read and remediated "
                             "rather than published: the same row, minus the "
                             "CrossRef and OJS routes, which assert that the "
                             "content is yours to deposit.")
    parser.add_argument("--from", dest="starter", default=STARTER_JOURNAL_SLUG, help="Slug of an existing journal to copy the template bundle from. Default: lics.")
    parser.add_argument("--adopt-template", action="store_true", help="Register against the template bundle already at content/journals/<slug>/template/ instead of copying a new one. For a fresh database in a clone that already carries the bundle in git.")
    args = parser.parse_args()

    db.init_db()
    kind = COLLECTION if args.collection else JOURNAL
    try:
        made = scaffold(args.slug, args.name, issn=args.issn,
                        short_name=args.short_name, starter=args.starter,
                        adopt_template=args.adopt_template, kind=kind)
    except ScaffoldError as exc:
        print(exc, file=sys.stderr)
        sys.exit(1)

    for note in made["notes"]:
        print(f"  {note}")
    print(f"  registered {made['kind']}: id={made['id']}, "
          f"slug={made['slug']!r}, short_name={made['short_name']!r}")

    if made["kind"] == COLLECTION:
        print(f"""
Done. Next steps:

1. Run the app:        python app.py
2. Take the archive in: http://127.0.0.1:5050/journals/{args.slug}/ingest
3. See where it stands: http://127.0.0.1:5050/accessibility/{args.slug}

A collection is not deposited, so the CrossRef and OJS routes refuse for
it. Everything else, the register, the description queue and the
conformance report, works on it exactly as on a journal.
""")
        return

    print(f"""
Done. Next steps:

1. Run the app:        python app.py
2. Visit settings:     http://127.0.0.1:5050/journals/{args.slug}/settings
3. Configure:          wordmark image, editorial team, board, mission,
                       financial credit, ToC section labels, CrossRef
                       prefix + member ID + depositor identity
4. Customize:          edit {made['template_path']}/article.css and
                       article.typ to match your journal's visual identity
5. Upload an article:  click "Upload DOCX" on the journal's home page
""")


if __name__ == "__main__":
    main()
