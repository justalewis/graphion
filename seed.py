"""Initial seed: schema + LiCS journal record + first admin user.

Usage:
    python seed.py                       # interactive (prompts for admin pw)
    python seed.py --user x --pass y     # non-interactive (CI / scripts)
"""
from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

import auth
import db
from config import CONTENT_DIR


def ensure_lics_journal():
    existing = db.query_one("SELECT id FROM journals WHERE slug = ?", ("lics",))
    if existing:
        print(f"  lics journal already registered (id={existing['id']})")
        return existing["id"]

    tpl = CONTENT_DIR / "journals" / "lics" / "template"
    if not tpl.exists():
        print(f"  ! template directory missing: {tpl}", file=sys.stderr)
        sys.exit(1)

    journal_id = db.execute(
        "INSERT INTO journals (slug, name, issn, template_path, crossref_prefix, crossref_member_id) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        ("lics", "Literacy in Composition Studies", "2326-5620", str(tpl), "10.21623", "1"),
    )
    print(f"  registered LiCS (id={journal_id})")
    return journal_id


def ensure_admin_user(username: str, password: str, email: str | None):
    if auth.User.by_username(username):
        print(f"  user {username!r} already exists; skipping")
        return
    uid = auth.create_user(username, password, email=email)
    print(f"  created admin user {username!r} (id={uid})")


def main():
    parser = argparse.ArgumentParser(description="Initialize the Graphion database.")
    parser.add_argument("--user", default=None, help="Admin username (interactive if omitted)")
    parser.add_argument("--pass", dest="password", default=None, help="Admin password (interactive if omitted)")
    parser.add_argument("--email", default=None)
    args = parser.parse_args()

    print("Initializing database...")
    db.init_db()
    print("  schema ok")

    print("Registering journals...")
    ensure_lics_journal()

    print("Creating admin user...")
    username = args.user or input("  Admin username [admin]: ").strip() or "admin"
    if args.password:
        password = args.password
    else:
        password = getpass.getpass("  Admin password: ")
        confirm = getpass.getpass("  Confirm password: ")
        if password != confirm:
            print("  ! passwords do not match", file=sys.stderr)
            sys.exit(1)
    if len(password) < 6:
        print("  ! password must be at least 6 characters", file=sys.stderr)
        sys.exit(1)
    ensure_admin_user(username, password, args.email)

    print("\nDone. Start the app with: python app.py")


if __name__ == "__main__":
    main()
