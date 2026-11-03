#!/usr/bin/env python
"""Run the two external checkers over a journal's galleys and record them.

`register.py` has four kinds and two of them have never run. Every article
in the Writing Spaces archive declares PDF/UA-1, which is what the galley
says about itself; whether the claim holds up is verapdf's answer, and
nothing here had asked it. A declaration is the beginning of a check and
not the end of one, which this codebase knows better than most: six volumes
bound galleys that each declared conformance into issues that were not
tagged at all.

This is a script rather than a route because of what the two tools cost.
Each is a subprocess with a 120 second timeout, so a pass over 118 articles
is a wall-clock hour at best and most of a day at worst, which is not a
request. The corpus route in `app.py` runs only the two in-process checks
for the same reason.

What it does not do is manufacture a result it does not have. A tool that
is not installed stops the run before anything is written, and the reason
is worth keeping: a recorded run is the newest run for its kind, so a pass
over an archive with verapdf missing would write "not checked" over every
verdict a real run had left, and `register.latest_run` would hand that back
as the current answer. Refusing costs nothing; the alternative loses
results that were expensive to get.

A tool that is installed and then cannot answer is a different fact and is
recorded. A galley verapdf times out on has told you something about the
galley; a laptop without verapdf has told you something about the laptop.

Usage:

    python validate_galleys.py writing-spaces --dry-run
    python validate_galleys.py writing-spaces --skip-current
    python validate_galleys.py writing-spaces --only verapdf --limit 5
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Optional

import db
import register
import validators

KINDS = ("verapdf", "pa11y")

# The tool behind each kind, how to ask whether it is there, and what to say
# when it is not. The install lines are the ones in `validators.py`; they are
# repeated to the person running this because that is the moment they need
# them. The probes are called through rather than stored, so that whether a
# tool is installed is asked of `validators` at the moment it matters.
TOOLS = {
    "verapdf": {
        "label": "verapdf",
        "available": lambda: validators.verapdf_available(),
        "install": "download from https://verapdf.org/ and put `verapdf` on PATH",
        "reads": "article.pdf",
        "report": "verapdf-report.json",
    },
    "pa11y": {
        "label": "pa11y",
        "available": lambda: validators.pa11y_available(),
        "install": "npm install -g pa11y",
        "reads": "article.html",
        "report": "pa11y-report.json",
    },
}


def articles_for(journal_slug: str) -> list:
    rows = db.query_all(
        "SELECT a.id, a.slug, a.title, a.project_path, "
        "       i.volume, i.issue_number "
        "FROM articles a "
        "LEFT JOIN journals j ON a.journal_id = j.id "
        "LEFT JOIN issues i ON a.issue_id = i.id "
        "WHERE j.slug = ? "
        "ORDER BY i.year, i.volume, i.issue_number, a.order_in_issue, a.slug",
        (journal_slug,),
    )
    return [dict(r) for r in rows]


def to_do(article: dict, kind: str, skip_current: bool) -> Optional[str]:
    """Why this article and kind is in the run, or None to leave it out.

    An article with no galley is left out rather than recorded as a failure,
    which is the distinction `register` already draws between owing a render
    and failing a check.
    """
    path = Path(article["project_path"]) / register.CHECKED_FILE[kind]
    if not path.exists():
        return None
    if not skip_current:
        return "queued"
    standing = register.standing(
        article["id"], article["project_path"], kinds=(kind,))[kind]
    if standing.settled:
        return None
    return {register.STALE: "re-check, content moved",
            register.NEVER: "never checked"}.get(standing.state, "queued")


def run_one(article: dict, kind: str) -> tuple:
    """Run one checker against one galley and record it.

    The hash is taken before the tool runs, so the register dates the
    verdict to the bytes the tool read rather than to whatever is on disk
    once it finishes.
    """
    project = Path(article["project_path"])
    target = project / register.CHECKED_FILE[kind]
    content_hash = register.hash_for(project, kind)
    if content_hash is None:
        return None, "no file"

    started = time.time()
    if kind == "verapdf":
        passed, payload = validators.run_verapdf(target)
    else:
        passed, payload = validators.run_pa11y(target)
    elapsed = time.time() - started

    (project / TOOLS[kind]["report"]).write_text(
        json.dumps(payload, indent=2), encoding="utf-8")

    if kind == "verapdf":
        register.record_verapdf(article["id"], project, passed, payload,
                                content_hash=content_hash)
    else:
        register.record_pa11y(article["id"], project, passed, payload,
                              content_hash=content_hash)

    standing = register.standing(article["id"], project, kinds=(kind,))[kind]
    return standing.level, f"{elapsed:.1f}s"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run verapdf and pa11y over a journal's galleys and "
                    "record each run in the accessibility register.")
    parser.add_argument("journal", help="journal slug, e.g. writing-spaces")
    parser.add_argument("--only", choices=KINDS,
                        help="run one of the two rather than both")
    parser.add_argument("--skip-current", action="store_true",
                        help="leave out an article whose run is already on "
                             "record against the file now on disk, which is "
                             "what makes a second pass cheap and an "
                             "interrupted one resumable")
    parser.add_argument("--limit", type=int,
                        help="stop after this many articles")
    parser.add_argument("--dry-run", action="store_true",
                        help="print the plan and write nothing")
    parser.add_argument("--stop-on-error", action="store_true")
    args = parser.parse_args()

    db.init_db()
    kinds = (args.only,) if args.only else KINDS

    journal = db.query_one("SELECT slug, name FROM journals WHERE slug = ?",
                           (args.journal,))
    if not journal:
        print(f"No journal with slug {args.journal!r}.", file=sys.stderr)
        return 2

    # Checked before the plan is built, so a missing tool costs nobody a
    # pass over the archive before it says so.
    missing = [k for k in kinds if not TOOLS[k]["available"]()]
    if missing and not args.dry_run:
        for kind in missing:
            tool = TOOLS[kind]
            print(f"{tool['label']} is not on PATH: {tool['install']}",
                  file=sys.stderr)
        print("Nothing written. A run that cannot call the tool would record "
              "\"not checked\" over whatever a real run had left, and that "
              "row would then be the current answer.", file=sys.stderr)
        return 1

    articles = articles_for(args.journal)
    plan = []
    left_out = 0
    for article in articles:
        for kind in kinds:
            reason = to_do(article, kind, args.skip_current)
            if reason:
                plan.append((article, kind, reason))
            else:
                left_out += 1
        if args.limit and len({a["id"] for a, _k, _r in plan}) >= args.limit:
            break

    print(f"{journal['name']}: {len(articles)} article(s), "
          f"{len(plan)} check(s) to run "
          f"({', '.join(kinds)})")
    for kind in kinds:
        n = sum(1 for _a, k, _r in plan if k == kind)
        state = "ready" if TOOLS[kind]["available"]() else "NOT INSTALLED"
        print(f"  {TOOLS[kind]['label']:8s} {n:4d} queued  [{state}]")
    # Counted while planning rather than subtracted from the whole journal,
    # which reported every article past a `--limit` as left out.
    if left_out:
        print(f"  {left_out} left out: no galley rendered, or already current")
    if args.limit and len(articles) > args.limit:
        print(f"  stopped at --limit {args.limit}")

    if args.dry_run:
        for article, kind, reason in plan[:40]:
            print(f"    {kind:8s} {article['slug'][:48]:48s} {reason}")
        if len(plan) > 40:
            print(f"    ... and {len(plan) - 40} more")
        print("Dry run; nothing written.")
        return 0

    counts: dict = {}
    failures = 0
    started = time.time()
    for index, (article, kind, _reason) in enumerate(plan, 1):
        try:
            level, note = run_one(article, kind)
        except Exception as exc:
            failures += 1
            print(f"  [{index}/{len(plan)}] {kind:8s} {article['slug'][:48]:48s} "
                  f"ERROR {type(exc).__name__}: {exc}")
            if args.stop_on_error:
                return 1
            continue
        counts[(kind, level)] = counts.get((kind, level), 0) + 1
        print(f"  [{index}/{len(plan)}] {kind:8s} {article['slug'][:48]:48s} "
              f"{level or 'skipped':8s} {note}")

    print(f"\nDone in {time.time() - started:.0f}s.")
    for (kind, level), n in sorted(counts.items(), key=lambda kv: str(kv[0])):
        print(f"  {kind:8s} {str(level):8s} {n}")
    if failures:
        print(f"  {failures} raised and were left unrecorded")
    print("The accessibility page reads these as soon as they are written; "
          "a result stops counting once the file it read changes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
