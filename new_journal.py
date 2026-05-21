"""Scaffold a new journal.

Usage:
    python new_journal.py <slug> "<Full Journal Name>" [--issn <issn>]

Creates a journal row in the DB and copies the LiCS template bundle to
`content/journals/<slug>/template/`. After this runs you'll customize the
journal at `/journals/<slug>/settings` (brand, front-matter content,
CrossRef config) and edit the template bundle's CSS/Typst files to taste.

The slug must be unique, kebab-case-friendly (letters, digits, dashes).
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

import db
from config import CONTENT_DIR


STARTER_JOURNAL_SLUG = "lics"


def main():
    parser = argparse.ArgumentParser(description="Scaffold a new journal in Graphion.")
    parser.add_argument("slug", help="URL-safe identifier (e.g., 'mhrj')")
    parser.add_argument("name", help='Full journal name (e.g., "Modern Hispanic Review Journal")')
    parser.add_argument("--issn", help="ISSN (e.g., '2326-5620')", default=None)
    parser.add_argument("--short-name", help="Short name for running headers (e.g., 'MHRJ'). Defaults to initials of `name`.", default=None)
    parser.add_argument("--from", dest="starter", default=STARTER_JOURNAL_SLUG, help="Slug of an existing journal to copy the template bundle from. Default: lics.")
    args = parser.parse_args()

    if not re.match(r"^[a-z0-9][a-z0-9-]*$", args.slug):
        print(f"Refusing to create journal with slug {args.slug!r}: must be lowercase letters/digits/dashes, starting with a letter or digit.", file=sys.stderr)
        sys.exit(1)

    db.init_db()

    existing = db.query_one("SELECT id FROM journals WHERE slug = ?", (args.slug,))
    if existing:
        print(f"Journal {args.slug!r} already exists (id={existing['id']}). Edit it at /journals/{args.slug}/settings.", file=sys.stderr)
        sys.exit(1)

    src_tpl = CONTENT_DIR / "journals" / args.starter / "template"
    if not src_tpl.exists():
        print(f"Starter template not found: {src_tpl}. Pass --from <slug> to point at a different existing journal.", file=sys.stderr)
        sys.exit(1)

    dest_tpl = CONTENT_DIR / "journals" / args.slug / "template"
    if dest_tpl.exists():
        print(f"Template directory already exists: {dest_tpl}. Remove it first or pick a different slug.", file=sys.stderr)
        sys.exit(1)

    print(f"Copying template bundle from {src_tpl} to {dest_tpl}...")
    shutil.copytree(src_tpl, dest_tpl)
    print("  copied article.css, article.html.j2, article.typ, journal-filter.lua, figures-filter.lua, mla.csl, and assets/")

    short_name = args.short_name or _initials(args.name)

    journal_id = db.execute(
        "INSERT INTO journals (slug, name, issn, template_path, short_name, "
        "header_label_template) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            args.slug,
            args.name,
            args.issn,
            str(dest_tpl),
            short_name,
            "*{short_name}* {volume}.{issue} / {season}",
        ),
    )
    print(f"  registered journal: id={journal_id}, slug={args.slug!r}, short_name={short_name!r}")

    print(f"""
Done. Next steps:

1. Run the app:        python app.py
2. Visit settings:     http://127.0.0.1:5050/journals/{args.slug}/settings
3. Configure:          wordmark image, editorial team, board, mission,
                       financial credit, ToC section labels, CrossRef
                       prefix + member ID + depositor identity
4. Customize:          edit {dest_tpl}/article.css and article.typ to
                       match your journal's visual identity
5. Upload an article:  click "Upload DOCX" on the journal's home page
""")


def _initials(name: str) -> str:
    skip = {"in", "of", "the", "and", "for", "on", "to", "a", "an"}
    parts = [w for w in re.split(r"\s+", name) if w]
    initials = "".join(w[0] for w in parts if w.lower() not in skip)
    return initials.upper() or name[:5].upper()


if __name__ == "__main__":
    main()
