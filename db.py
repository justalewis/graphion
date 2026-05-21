"""SQLite layer. Raw sqlite3, no ORM. Match the Pinakes pattern."""
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    email TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS journals (
    id INTEGER PRIMARY KEY,
    slug TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    issn TEXT,
    template_path TEXT NOT NULL,
    crossref_member_id TEXT,
    crossref_prefix TEXT,
    config_json TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS issues (
    id INTEGER PRIMARY KEY,
    journal_id INTEGER NOT NULL REFERENCES journals(id),
    volume INTEGER NOT NULL,
    issue_number INTEGER NOT NULL,
    year INTEGER NOT NULL,
    title TEXT,
    editorial_introduction_path TEXT,
    status TEXT DEFAULT 'draft',
    published_at TIMESTAMP,
    config_json TEXT,
    UNIQUE(journal_id, volume, issue_number)
);

CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY,
    issue_id INTEGER REFERENCES issues(id),
    journal_id INTEGER NOT NULL REFERENCES journals(id),
    slug TEXT NOT NULL,
    title TEXT NOT NULL,
    short_title TEXT,
    doi TEXT,
    project_path TEXT NOT NULL,
    order_in_issue INTEGER,
    start_page INTEGER,
    end_page INTEGER,
    status TEXT DEFAULT 'draft',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(journal_id, slug)
);

CREATE TABLE IF NOT EXISTS authors (
    id INTEGER PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    affiliation TEXT,
    orcid TEXT,
    email TEXT,
    is_corresponding INTEGER DEFAULT 0,
    sequence INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS conversions (
    id INTEGER PRIMARY KEY,
    article_id INTEGER NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    source_format TEXT,
    pandoc_version TEXT,
    notes TEXT,
    success INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_articles_journal ON articles(journal_id);
CREATE INDEX IF NOT EXISTS idx_articles_issue ON articles(issue_id);
CREATE INDEX IF NOT EXISTS idx_authors_article ON authors(article_id);
CREATE INDEX IF NOT EXISTS idx_conversions_article ON conversions(article_id);
"""


def get_connection():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def cursor():
    conn = get_connection()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with cursor() as cur:
        cur.executescript(SCHEMA)
    _apply_migrations()


def _apply_migrations():
    """Additive column migrations. Idempotent: skips any column that already
    exists. Append new columns at the bottom; never reorder or drop."""
    additions = {
        "journals": [
            ("short_name", "TEXT"),
            ("wordmark_image_path", "TEXT"),
            ("header_label_template", "TEXT"),
            ("depositor_name", "TEXT"),
            ("depositor_email", "TEXT"),
            ("editorial_team_md", "TEXT"),
            ("editorial_board_md", "TEXT"),
            ("mission_statement_md", "TEXT"),
            ("financial_credit_md", "TEXT"),
            ("toc_sections_json", "TEXT"),
        ],
        "articles": [
            ("kind", "TEXT DEFAULT 'article'"),
            ("section", "TEXT DEFAULT 'ARTICLES'"),
        ],
        "issues": [
            ("header_season", "TEXT"),
        ],
    }
    with cursor() as cur:
        for table, cols in additions.items():
            cur.execute(f"PRAGMA table_info({table})")
            existing = {row[1] for row in cur.fetchall()}
            for name, decl in cols:
                if name not in existing:
                    cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def query_one(sql, params=()):
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()


def query_all(sql, params=()):
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def execute(sql, params=()):
    with cursor() as cur:
        cur.execute(sql, params)
        return cur.lastrowid
