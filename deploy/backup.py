#!/usr/bin/env python3
"""Back up Graphion's canonical state to off-box storage.

The app is filesystem-first: content/ is the real store and SQLite only indexes
it. Both have to travel together, and both live on a single Fly volume, so an
off-box copy is the only thing standing between a volume failure and the loss of
unpublished manuscripts.

Run manually:

    fly ssh console -C "python /app/deploy/backup.py"

Or let deploy/entrypoint.sh run it on a loop when GRAPHION_BACKUP_REMOTE is set.

Environment:
    GRAPHION_BACKUP_REMOTE   rclone destination, e.g. "b2:graphion-backups".
                             If unset, the archive is written locally only.
    GRAPHION_BACKUP_KEEP     Local archives to retain (default 3).
"""
from __future__ import annotations

import os
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import CONTENT_DIR, DATA_DIR, DB_PATH  # noqa: E402

BACKUP_DIR = Path(os.environ.get("GRAPHION_BACKUP_DIR") or (DATA_DIR.parent / "backups"))
REMOTE = os.environ.get("GRAPHION_BACKUP_REMOTE", "").strip()
KEEP = int(os.environ.get("GRAPHION_BACKUP_KEEP", "3"))


def log(msg: str) -> None:
    print(f"[backup] {msg}", flush=True)


def snapshot_database(dest: Path) -> bool:
    """Copy the live database using SQLite's online backup API.

    A plain file copy of a database being written to can capture a torn page.
    The backup API takes a consistent snapshot without stopping the app.
    """
    if not DB_PATH.exists():
        log(f"no database at {DB_PATH}; skipping")
        return False
    src = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        out = sqlite3.connect(str(dest))
        try:
            src.backup(out)
        finally:
            out.close()
    finally:
        src.close()
    log(f"database snapshot: {dest.stat().st_size:,} bytes")
    return True


def build_archive(stamp: str) -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    archive = BACKUP_DIR / f"graphion-{stamp}.tar.gz"

    with tempfile.TemporaryDirectory() as tmp:
        db_snapshot = Path(tmp) / "graphion.db"
        have_db = snapshot_database(db_snapshot)

        with tarfile.open(archive, "w:gz") as tar:
            if CONTENT_DIR.exists():
                tar.add(CONTENT_DIR, arcname="content")
                log(f"added content tree from {CONTENT_DIR}")
            else:
                log(f"WARNING: content dir missing at {CONTENT_DIR}")
            if have_db:
                tar.add(db_snapshot, arcname="data/graphion.db")

    log(f"archive: {archive} ({archive.stat().st_size:,} bytes)")
    return archive


def upload(archive: Path) -> None:
    if not REMOTE:
        log("GRAPHION_BACKUP_REMOTE unset; archive kept locally only")
        log("a backup on the same volume does not survive losing that volume")
        return
    if shutil.which("rclone") is None:
        raise RuntimeError("rclone not found on PATH")

    log(f"uploading to {REMOTE}")
    subprocess.run(
        ["rclone", "copy", "--no-traverse", str(archive), REMOTE],
        check=True,
    )
    log("upload ok")


def prune() -> None:
    archives = sorted(
        BACKUP_DIR.glob("graphion-*.tar.gz"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    for old in archives[KEEP:]:
        old.unlink()
        log(f"pruned {old.name}")


def main() -> int:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%SZ")
    log(f"starting {stamp}")
    try:
        archive = build_archive(stamp)
        upload(archive)
        prune()
    except Exception as exc:  # noqa: BLE001 - surface the reason in logs
        log(f"FAILED: {exc}")
        return 1
    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
