"""Flask app. Phase 1 routes: dashboard, upload, edit, render, download."""
from __future__ import annotations

import re
import shutil
import sqlite3
import tempfile
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request,
    send_file, send_from_directory, url_for,
)
from markupsafe import Markup
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename

import citation_styles
import conversion
import crossref
import db
import describe
import jats
import lint
import ojs_client
import acr
import jobs
import register
import standalone_html
from auth import User, login_manager
from config import (
    ALLOWED_UPLOAD_EXTENSIONS, CONTENT_DIR, LOGIN_MAX_ATTEMPTS,
    LOGIN_WINDOW_SECONDS, MAX_ASSESS_FILES, MAX_ASSESS_VALIDATE_FILES,
    MAX_BATCH_BYTES, MAX_CARTRIDGE_BYTES, MAX_INGEST_FILES,
    MAX_UPLOAD_BYTES, SECURE_COOKIES, SECRET_KEY,
)

# The routes allowed the larger request body, which are the two that take a
# batch of files rather than one manuscript. Named here rather than matched
# on the path, so renaming a route cannot silently widen the limit for
# everything else; a test pins each name to a route that exists.
BATCH_ENDPOINTS = frozenset({"assess_archive", "journal_ingest_batch"})

# The route that takes a whole course cartridge, which carries its media and
# so is routinely several hundred megabytes. Kept apart from the batch
# endpoints rather than folded in, so raising what a cartridge may weigh does
# not raise what a batch of PDFs may.
CARTRIDGE_ENDPOINTS = frozenset({"remediate_upload"})


def _request_limit(endpoint) -> int:
    """How large a body this endpoint may carry, read at call time.

    Looked up per request rather than fixed at start-up so each route is held
    to its own ceiling and not to the largest of them.
    """
    if endpoint in CARTRIDGE_ENDPOINTS:
        return MAX_CARTRIDGE_BYTES
    if endpoint in BATCH_ENDPOINTS:
        return MAX_BATCH_BYTES
    return MAX_UPLOAD_BYTES


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY
    # Flask's limit is per application and two routes take a batch, so the
    # ceiling is the larger of the two limits and the smaller one is
    # enforced below for every other route. Setting this to MAX_BATCH_BYTES
    # alone would hand every upload that writes into content/ twelve times
    # the body it has ever accepted.
    app.config["MAX_CONTENT_LENGTH"] = max(
        MAX_UPLOAD_BYTES, MAX_BATCH_BYTES, MAX_CARTRIDGE_BYTES)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = SECURE_COOKIES

    @app.before_request
    def _hold_single_file_routes_to_the_smaller_limit():
        """Every route but the two batch ones keeps the limit it had.

        `MAX_CONTENT_LENGTH` had to rise for a batch of PDFs to arrive at
        all, and that config is application wide, so without this every
        upload that takes one manuscript would quietly have gained the
        same headroom.
        """
        if (request.content_length or 0) > _request_limit(request.endpoint):
            abort(413)
        return None

    # What a journal row is, available to every template without each
    # route having to pass it, and read through `new_journal.kind_of` so
    # there is one answer: a row written before the column reads NULL, and
    # a template testing the column directly would call it neither kind.
    import new_journal
    app.jinja_env.globals["is_collection"] = new_journal.is_collection
    app.jinja_env.globals["kind_label"] = (
        lambda journal: new_journal.KIND_LABELS[new_journal.kind_of(journal)])

    @app.template_filter("from_json")
    def _from_json(s):
        import json
        if not s:
            return []
        try:
            return json.loads(s)
        except Exception:
            return []

    db.init_db()
    # A row left reading `running` with nothing advancing it is a batch the
    # process died under, and the flattering reading of that is work still
    # in hand. One query, so it belongs at start-up rather than on a page.
    jobs.recover()
    login_manager.init_app(app)

    register_routes(app)
    return app


def slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\-]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "article"


# ---------- login throttling ----------
#
# Every route but /login carries @login_required, so this is the only
# unauthenticated surface. Werkzeug hashes with scrypt, which already makes
# guessing slow, but nothing otherwise caps the number of tries.

_login_failures: dict[str, list[float]] = defaultdict(list)
_login_lock = threading.Lock()


def _client_ip() -> str:
    """Caller address, preferring the header Fly's proxy sets itself.

    Fly-Client-IP is written by the proxy and overwrites anything the client
    sent, so it cannot be spoofed from outside. X-Forwarded-For is only a
    fallback for other proxies.
    """
    fly_ip = request.headers.get("Fly-Client-IP")
    if fly_ip:
        return fly_ip
    forwarded = request.headers.get("X-Forwarded-For", "")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.remote_addr or "unknown"


def _login_retry_after(keys: list[str]) -> int:
    """Seconds until the next attempt is allowed; 0 when not throttled."""
    now = time.time()
    longest = 0
    with _login_lock:
        for key in keys:
            recent = [t for t in _login_failures[key] if now - t < LOGIN_WINDOW_SECONDS]
            if recent:
                _login_failures[key] = recent
            else:
                _login_failures.pop(key, None)
            if len(recent) >= LOGIN_MAX_ATTEMPTS:
                longest = max(longest, int(LOGIN_WINDOW_SECONDS - (now - recent[0])) + 1)
    return longest


def _record_login_failure(keys: list[str]) -> None:
    now = time.time()
    with _login_lock:
        for key in keys:
            _login_failures[key].append(now)


def _clear_login_failures(keys: list[str]) -> None:
    with _login_lock:
        for key in keys:
            _login_failures.pop(key, None)


def register_routes(app: Flask):

    # ---------- auth ----------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            username = request.form.get("username", "")
            # Throttled on both address and account, so that rotating addresses
            # cannot walk one account and one address cannot spray many.
            keys = ["ip:" + _client_ip(), "user:" + username.lower()]

            wait = _login_retry_after(keys)
            if wait:
                minutes = max(1, wait // 60)
                unit = "minute" if minutes == 1 else "minutes"
                flash(
                    "Too many failed sign-ins; try again in "
                    f"{minutes} {unit}.", "error",
                )
                return render_template("login.html"), 429

            user = User.by_username(username)
            if user and user.check_password(request.form.get("password", "")):
                _clear_login_failures(keys)
                login_user(user, remember=True)
                return redirect(url_for("dashboard"))

            _record_login_failure(keys)
            flash("Invalid credentials.", "error")
        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        return redirect(url_for("login"))

    # ---------- dashboard ----------

    @app.route("/")
    @login_required
    def dashboard():
        journals = db.query_all("SELECT * FROM journals ORDER BY name")
        recent = db.query_all(
            "SELECT a.*, j.name AS journal_name "
            "FROM articles a JOIN journals j ON a.journal_id = j.id "
            "ORDER BY a.updated_at DESC LIMIT 20"
        )
        recent_issues = db.query_all(
            "SELECT i.*, j.name AS journal_name FROM issues i "
            "JOIN journals j ON i.journal_id = j.id "
            "ORDER BY i.year DESC, i.volume DESC, i.issue_number DESC LIMIT 10"
        )
        return render_template("dashboard.html", journals=journals, recent=recent, recent_issues=recent_issues)

    # ---------- journal ----------

    @app.route("/journals/new", methods=["GET", "POST"])
    @login_required
    def journal_new():
        """Start a journal, or a collection, from the browser.

        `new_journal.py` was the only way to do this, which is most of why
        this app stayed pointed at the two archives it was written for:
        every other thing a stranger's archive needs had a page, and the
        first step needed a shell on the machine.

        The decisions stay in `new_journal.scaffold`, the way ingest's
        stay in `ingest_volume` and the validators' in
        `validate_galleys`, so a journal started here and one started from
        a terminal are the same journal.
        """
        import new_journal

        starters = db.query_all("SELECT slug, name FROM journals ORDER BY name")
        shape = {"starters": [dict(s) for s in starters],
                 "default_starter": new_journal.STARTER_JOURNAL_SLUG,
                 "kinds": new_journal.KINDS,
                 "kind_labels": new_journal.KIND_LABELS}
        if request.method == "GET":
            return render_template("journal_new.html", shape=shape)

        kind = request.form.get("kind") or new_journal.JOURNAL
        name = (request.form.get("name") or "").strip()
        slug = (request.form.get("slug") or "").strip().lower()
        if not slug and name:
            slug = slugify(name)
        starter = request.form.get("starter") or new_journal.STARTER_JOURNAL_SLUG
        # An ISSN identifies a serial you publish, so it is not offered for
        # a collection and is not read back if one is posted anyway.
        issn = ((request.form.get("issn") or "").strip()
                if kind == new_journal.JOURNAL else None)

        try:
            made = new_journal.scaffold(
                slug, name, issn=issn or None,
                short_name=(request.form.get("short_name") or "").strip() or None,
                starter=starter, kind=kind)
        except new_journal.ScaffoldError as exc:
            flash(str(exc), "error")
            return render_template("journal_new.html", shape=shape,
                                   posted=request.form)

        if made["kind"] == new_journal.COLLECTION:
            flash(f"Created {made['name']}. A collection is not deposited, "
                  f"so the CrossRef and OJS routes do not apply to it; "
                  f"everything else does. Take the archive in from here.",
                  "success")
            return redirect(url_for("journal_ingest_batch", slug=made["slug"]))
        flash(f"Created {made['name']}. The template bundle was copied from "
              f"{starter}; edit it in git, not on the volume.", "success")
        return redirect(url_for("journal_settings", slug=made["slug"]))

    @app.route("/journals/<slug>/settings", methods=["GET", "POST"])
    @login_required
    def journal_settings(slug):
        j = db.query_one("SELECT * FROM journals WHERE slug = ?", (slug,))
        if not j:
            abort(404)
        if request.method == "POST":
            import json
            sections_raw = request.form.get("toc_sections_json", "").strip()
            sections = [line.strip() for line in sections_raw.splitlines() if line.strip()]
            sections_json = json.dumps(sections) if sections else None

            team_roles = request.form.getlist("team_role")
            team_names = request.form.getlist("team_name")
            team_institutions = request.form.getlist("team_institution")
            team = []
            for i, name in enumerate(team_names):
                role = (team_roles[i] if i < len(team_roles) else "").strip()
                nm = (name or "").strip()
                if not nm:
                    continue
                inst = (team_institutions[i] if i < len(team_institutions) else "").strip()
                team.append({"role": role, "name": nm, "institution": inst})
            team_json = json.dumps(team) if team else None

            board_names = request.form.getlist("board_name")
            board_institutions = request.form.getlist("board_institution")
            board = []
            for i, name in enumerate(board_names):
                nm = (name or "").strip()
                if not nm:
                    continue
                inst = (board_institutions[i] if i < len(board_institutions) else "").strip()
                board.append({"name": nm, "institution": inst})
            board_json = json.dumps(board) if board else None

            citation_style = request.form.get("citation_style", "").strip() or None
            if citation_style and citation_style != "custom":
                try:
                    citation_styles.install_style(
                        conversion.template_dir(slug), citation_style
                    )
                except FileNotFoundError as exc:
                    flash(f"Could not install citation style: {exc}", "error")
                    return redirect(request.url)
            elif citation_style == "custom":
                citation_style = None  # store NULL; user manages the .csl file directly

            fields = {
                "short_name": request.form.get("short_name", "").strip() or None,
                "header_label_template": request.form.get("header_label_template", "").strip() or None,
                "depositor_name": request.form.get("depositor_name", "").strip() or None,
                "depositor_email": request.form.get("depositor_email", "").strip() or None,
                "editorial_team_md": request.form.get("editorial_team_md", "").strip() or None,
                "editorial_board_md": request.form.get("editorial_board_md", "").strip() or None,
                "editorial_team_json": team_json,
                "editorial_board_json": board_json,
                "mission_statement_md": request.form.get("mission_statement_md", "").strip() or None,
                "financial_credit_md": request.form.get("financial_credit_md", "").strip() or None,
                "toc_sections_json": sections_json,
                "crossref_prefix": request.form.get("crossref_prefix", "").strip() or None,
                "crossref_member_id": request.form.get("crossref_member_id", "").strip() or None,
                "citation_style": citation_style,
                "ojs_url": request.form.get("ojs_url", "").strip() or None,
                "ojs_api_token": request.form.get("ojs_api_token", "").strip() or None,
                "ojs_context_id": request.form.get("ojs_context_id", "").strip() or None,
            }
            updates = ", ".join(f"{k} = ?" for k in fields)
            db.execute(
                f"UPDATE journals SET {updates} WHERE id = ?",
                (*fields.values(), j["id"]),
            )

            wordmark_file = request.files.get("wordmark")
            if wordmark_file and wordmark_file.filename:
                fname = secure_filename(wordmark_file.filename)
                ext = Path(fname).suffix.lower()
                if ext not in {".png", ".svg", ".jpg", ".jpeg"}:
                    flash("Wordmark must be PNG, SVG, or JPG.", "error")
                    return redirect(request.url)
                target_dir = conversion.template_dir(slug) / "assets"
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / f"wordmark{ext}"
                wordmark_file.save(target)
                rel = target.relative_to(conversion.template_dir(slug).parent.parent.parent)
                db.execute(
                    "UPDATE journals SET wordmark_image_path = ? WHERE id = ?",
                    (str(rel).replace("\\", "/"), j["id"]),
                )

            flash("Journal settings saved.", "success")
            return redirect(url_for("journal_settings", slug=slug))

        wordmark_url = None
        if j["wordmark_image_path"]:
            wm = Path(j["wordmark_image_path"])
            if wm.is_absolute():
                wordmark_url = wm.as_posix()
            else:
                wordmark_url = url_for(
                    "serve_journal_asset", slug=slug, filename=Path(j["wordmark_image_path"]).name
                )
        return render_template(
            "journal_settings.html",
            journal=j,
            wordmark_url=wordmark_url,
            bundled_styles=citation_styles.BUNDLED_STYLES,
        )

    @app.route("/journals/<slug>/assets/<path:filename>")
    @login_required
    def serve_journal_asset(slug, filename):
        target_dir = conversion.template_dir(slug) / "assets"
        return send_from_directory(target_dir, filename)

    @app.route("/journals/<slug>")
    @login_required
    def journal_home(slug):
        j = db.query_one("SELECT * FROM journals WHERE slug = ?", (slug,))
        if not j:
            abort(404)
        articles = db.query_all(
            "SELECT * FROM articles WHERE journal_id = ? ORDER BY updated_at DESC",
            (j["id"],),
        )
        issues = db.query_all(
            "SELECT * FROM issues WHERE journal_id = ? ORDER BY year DESC, volume DESC, issue_number DESC",
            (j["id"],),
        )
        return render_template("journal.html", journal=j, articles=articles, issues=issues)

    # ---------- issues ----------

    @app.route("/issues")
    @login_required
    def issues_list():
        rows = db.query_all(
            "SELECT i.*, j.slug AS journal_slug, j.name AS journal_name, "
            "       (SELECT COUNT(*) FROM articles a WHERE a.issue_id = i.id) AS article_count "
            "FROM issues i JOIN journals j ON i.journal_id = j.id "
            "ORDER BY i.year DESC, i.volume DESC, i.issue_number DESC"
        )
        return render_template("issues.html", issues=rows)

    @app.route("/journals/<slug>/issues/new", methods=["GET", "POST"])
    @login_required
    def issue_new(slug):
        journal = db.query_one("SELECT * FROM journals WHERE slug = ?", (slug,))
        if not journal:
            abort(404)
        if request.method == "POST":
            try:
                volume = int(request.form.get("volume", "").strip())
                issue_number = int(request.form.get("issue_number", "").strip())
                year = int(request.form.get("year", "").strip())
            except ValueError:
                flash("Volume, issue number, and year must be integers.", "error")
                return redirect(request.url)
            title = request.form.get("title", "").strip() or None
            existing = db.query_one(
                "SELECT id FROM issues WHERE journal_id = ? AND volume = ? AND issue_number = ?",
                (journal["id"], volume, issue_number),
            )
            if existing:
                flash(f"Issue {volume}.{issue_number} already exists for {journal['name']}.", "error")
                return redirect(request.url)
            issue_id = db.execute(
                "INSERT INTO issues (journal_id, volume, issue_number, year, title, status) "
                "VALUES (?, ?, ?, ?, ?, 'draft')",
                (journal["id"], volume, issue_number, year, title),
            )
            islug = conversion.issue_slug_for(volume, issue_number, year)
            conversion.issue_dir(slug, islug)
            conversion.write_issue_yaml(slug, islug, {
                "volume": volume,
                "issue": issue_number,
                "year": year,
                "title": title,
                "journal": journal["name"],
                "issn": journal["issn"],
                "status": "draft",
            })
            flash(f"Created issue {volume}.{issue_number} ({year}).", "success")
            return redirect(url_for("issue_home", issue_id=issue_id))
        return render_template("issue_new.html", journal=journal)

    @app.route("/issues/<int:issue_id>")
    @login_required
    def issue_home(issue_id):
        issue = db.query_one(
            "SELECT i.*, j.slug AS journal_slug, j.name AS journal_name "
            "FROM issues i JOIN journals j ON i.journal_id = j.id WHERE i.id = ?",
            (issue_id,),
        )
        if not issue:
            abort(404)
        articles = db.query_all(
            "SELECT * FROM articles WHERE issue_id = ? "
            "ORDER BY COALESCE(order_in_issue, 999999), updated_at",
            (issue_id,),
        )
        unfiled = db.query_all(
            "SELECT * FROM articles WHERE journal_id = ? AND issue_id IS NULL "
            "ORDER BY updated_at DESC",
            (issue["journal_id"],),
        )
        return render_template("issue.html", issue=issue, articles=articles,
                               unfiled=unfiled,
                               journal=_journal_of_issue(issue_id))

    @app.route("/issues/<int:issue_id>/metadata", methods=["GET", "POST"])
    @login_required
    def issue_metadata(issue_id):
        issue = db.query_one(
            "SELECT i.*, j.slug AS journal_slug, j.name AS journal_name "
            "FROM issues i JOIN journals j ON i.journal_id = j.id WHERE i.id = ?",
            (issue_id,),
        )
        if not issue:
            abort(404)
        if request.method == "POST":
            try:
                volume = int(request.form.get("volume", "").strip())
                issue_number = int(request.form.get("issue_number", "").strip())
                year = int(request.form.get("year", "").strip())
            except ValueError:
                flash("Volume, issue, and year must be integers.", "error")
                return redirect(request.url)
            title = request.form.get("title", "").strip() or None
            status = request.form.get("status", "draft")
            season = request.form.get("header_season", "").strip() or None
            db.execute(
                "UPDATE issues SET volume = ?, issue_number = ?, year = ?, title = ?, "
                "status = ?, header_season = ? WHERE id = ?",
                (volume, issue_number, year, title, status, season, issue_id),
            )
            islug = conversion.issue_slug_for(volume, issue_number, year)
            conversion.write_issue_yaml(issue["journal_slug"], islug, {
                "volume": volume,
                "issue": issue_number,
                "year": year,
                "title": title,
                "journal": issue["journal_name"],
                "status": status,
            })
            flash("Issue metadata saved.", "success")
            return redirect(url_for("issue_home", issue_id=issue_id))
        return render_template("issue_metadata.html", issue=issue)

    @app.route("/issues/<int:issue_id>/create-editor-intro", methods=["POST"])
    @login_required
    def issue_create_editor_intro(issue_id):
        issue = db.query_one(
            "SELECT i.*, j.slug AS journal_slug FROM issues i "
            "JOIN journals j ON i.journal_id = j.id WHERE i.id = ?",
            (issue_id,),
        )
        if not issue:
            abort(404)

        existing = db.query_one(
            "SELECT * FROM articles WHERE issue_id = ? AND kind = 'editorial'",
            (issue_id,),
        )
        if existing:
            return redirect(url_for("article_edit", article_id=existing["id"]))

        islug = conversion.issue_slug_for(issue["volume"], issue["issue_number"], issue["year"])
        article_slug = f"editors-introduction-{issue['volume']}-{issue['issue_number']}-{issue['year']}"
        apath = conversion.article_dir(issue["journal_slug"], islug, article_slug)

        title = f"Editors' Introduction to Issue {issue['volume']}.{issue['issue_number']}"
        initial_body = (
            "Write the editors' introduction here in Markdown. "
            "This text becomes pages VI–VII (or however many it needs) "
            "of the front matter when you assemble the issue.\n\n"
            "Close with a signature line like:\n\n"
            "*—Editor One, Editor Two, and Editor Three*\n"
        )
        article_md = (
            "---\n"
            f"title: {title}\n"
            "kind: editorial\n"
            "---\n\n"
            f"{initial_body}"
        )
        (apath / "article.md").write_text(article_md, encoding="utf-8")

        article_id = db.execute(
            "INSERT INTO articles (journal_id, issue_id, slug, title, project_path, "
            "kind, section, status) "
            "VALUES (?, ?, ?, ?, ?, 'editorial', 'FRONT MATTER', 'draft')",
            (issue["journal_id"], issue_id, article_slug, title, str(apath)),
        )
        flash("Editors' introduction created. Edit the Markdown below.", "success")
        return redirect(url_for("article_edit", article_id=article_id))

    @app.route("/issues/<int:issue_id>/add-article", methods=["POST"])
    @login_required
    def issue_add_article(issue_id):
        issue = db.query_one(
            "SELECT i.*, j.slug AS journal_slug FROM issues i "
            "JOIN journals j ON i.journal_id = j.id WHERE i.id = ?",
            (issue_id,),
        )
        if not issue:
            abort(404)
        try:
            article_id = int(request.form.get("article_id", ""))
        except ValueError:
            flash("Invalid article selection.", "error")
            return redirect(url_for("issue_home", issue_id=issue_id))
        article = db.query_one("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not article or article["journal_id"] != issue["journal_id"]:
            flash("Article not found in this journal.", "error")
            return redirect(url_for("issue_home", issue_id=issue_id))

        islug = conversion.issue_slug_for(issue["volume"], issue["issue_number"], issue["year"])
        try:
            new_path = conversion.move_article_to_issue(
                Path(article["project_path"]),
                issue["journal_slug"],
                islug,
                article["slug"],
            )
        except FileExistsError as exc:
            flash(f"Could not move article: {exc}", "error")
            return redirect(url_for("issue_home", issue_id=issue_id))

        max_row = db.query_one(
            "SELECT COALESCE(MAX(order_in_issue), 0) AS m FROM articles WHERE issue_id = ?",
            (issue_id,),
        )
        next_order = (max_row["m"] or 0) + 1
        db.execute(
            "UPDATE articles SET issue_id = ?, order_in_issue = ?, project_path = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (issue_id, next_order, str(new_path), article_id),
        )
        flash(f"Added {article['title']!r} to issue.", "success")
        return redirect(url_for("issue_home", issue_id=issue_id))

    @app.route("/issues/<int:issue_id>/remove-article/<int:article_id>", methods=["POST"])
    @login_required
    def issue_remove_article(issue_id, article_id):
        issue = db.query_one(
            "SELECT i.*, j.slug AS journal_slug FROM issues i "
            "JOIN journals j ON i.journal_id = j.id WHERE i.id = ?",
            (issue_id,),
        )
        if not issue:
            abort(404)
        article = db.query_one("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not article or article["issue_id"] != issue_id:
            flash("Article is not in this issue.", "error")
            return redirect(url_for("issue_home", issue_id=issue_id))

        try:
            new_path = conversion.move_article_to_unfiled(
                Path(article["project_path"]),
                issue["journal_slug"],
                article["slug"],
            )
        except FileExistsError as exc:
            flash(f"Could not move article: {exc}", "error")
            return redirect(url_for("issue_home", issue_id=issue_id))

        db.execute(
            "UPDATE articles SET issue_id = NULL, order_in_issue = NULL, "
            "start_page = NULL, end_page = NULL, project_path = ?, "
            "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (str(new_path), article_id),
        )
        flash(f"Removed {article['title']!r} from issue.", "success")
        return redirect(url_for("issue_home", issue_id=issue_id))

    @app.route("/issues/<int:issue_id>/assemble", methods=["POST"])
    @login_required
    def issue_assemble(issue_id):
        try:
            result = conversion.assemble_issue(issue_id)
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("issue_home", issue_id=issue_id))
        if result.errors:
            flash(
                f"Assembled with issues: {'; '.join(result.errors)}",
                "error",
            )
        else:
            # The merge note says whether the bound issue came out tagged and
            # conformant, which is the one thing about an assembled issue an
            # editor cannot see by opening it.
            detail = f" ({'; '.join(result.notes)})" if result.notes else ""
            flash(
                f"Assembled {result.total_pages} pages across "
                f"{len(result.article_pages)} articles.{detail}",
                "success",
            )
        return redirect(url_for("issue_home", issue_id=issue_id))

    @app.route("/issues/<int:issue_id>/issue.pdf")
    @login_required
    def issue_pdf(issue_id):
        issue = db.query_one(
            "SELECT i.*, j.slug AS journal_slug FROM issues i "
            "JOIN journals j ON i.journal_id = j.id WHERE i.id = ?",
            (issue_id,),
        )
        if not issue:
            abort(404)
        islug = conversion.issue_slug_for(issue["volume"], issue["issue_number"], issue["year"])
        target = conversion.issue_dir(issue["journal_slug"], islug) / "issue.pdf"
        if not target.exists():
            abort(404)
        return send_from_directory(target.parent, "issue.pdf")

    @app.route("/issues/<int:issue_id>/reorder/<int:article_id>/<direction>", methods=["POST"])
    @login_required
    def issue_reorder_article(issue_id, article_id, direction):
        if direction not in {"up", "down"}:
            abort(400)
        rows = db.query_all(
            "SELECT id, order_in_issue FROM articles WHERE issue_id = ? "
            "ORDER BY COALESCE(order_in_issue, 999999), updated_at",
            (issue_id,),
        )
        ids = [r["id"] for r in rows]
        if article_id not in ids:
            flash("Article not in this issue.", "error")
            return redirect(url_for("issue_home", issue_id=issue_id))
        idx = ids.index(article_id)
        if direction == "up" and idx > 0:
            ids[idx - 1], ids[idx] = ids[idx], ids[idx - 1]
        elif direction == "down" and idx < len(ids) - 1:
            ids[idx + 1], ids[idx] = ids[idx], ids[idx + 1]
        else:
            return redirect(url_for("issue_home", issue_id=issue_id))
        for new_order, aid in enumerate(ids, start=1):
            db.execute(
                "UPDATE articles SET order_in_issue = ? WHERE id = ?",
                (new_order, aid),
            )
        return redirect(url_for("issue_home", issue_id=issue_id))

    # ---------- upload ----------

    @app.route("/journals/<slug>/upload", methods=["GET", "POST"])
    @login_required
    def upload_article(slug):
        journal = db.query_one("SELECT * FROM journals WHERE slug = ?", (slug,))
        if not journal:
            abort(404)

        if request.method == "POST":
            # Accept either a .docx (preferred) OR a .md file uploaded
            # directly (for users authoring with Writage, Pandoc CLI, or
            # by hand). The two paths diverge only in Stage 1 — .docx
            # goes through `ingest_docx`; .md skips ingest and the file
            # is copied straight into the article dir as article-raw.md.
            f = (request.files.get("docx") or request.files.get("source")
                 or request.files.get("md"))
            slug_override = request.form.get("slug", "").strip()
            title_hint = request.form.get("title", "").strip()
            short_title = request.form.get("short_title", "").strip()
            short_authors = request.form.get("short_authors", "").strip()
            accept_tc = request.form.get("track_changes", "accept") == "accept"
            ingest_engine = request.form.get("ingest_engine", "pandoc")
            preprocess_lo = request.form.get("preprocess_lo") == "on"

            if not f or not f.filename:
                flash("No file uploaded.", "error")
                return redirect(request.url)
            if not short_title or not short_authors:
                flash("Short title and short authors are required for running headers.", "error")
                return redirect(request.url)

            filename = secure_filename(f.filename)
            ext = Path(filename).suffix.lower()
            if ext not in ALLOWED_UPLOAD_EXTENSIONS:
                flash(
                    f"Unsupported file type {ext!r}. Allowed: "
                    f"{', '.join(sorted(ALLOWED_UPLOAD_EXTENSIONS))}.",
                    "error",
                )
                return redirect(request.url)

            article_slug = slug_override or slugify(Path(filename).stem)
            existing = db.query_one(
                "SELECT id FROM articles WHERE journal_id = ? AND slug = ?",
                (journal["id"], article_slug),
            )
            if existing:
                flash(f"An article with slug {article_slug!r} already exists.", "error")
                return redirect(request.url)

            apath = conversion.article_dir(slug, None, article_slug)
            staged = apath / filename
            f.save(staged)

            try:
                import preprocessors

                if ext == ".docx":
                    # Step 1 (optional): LibreOffice round-trip
                    # normalization. Cleans up text-box-heavy or
                    # weirdly-saved Word documents.
                    docx_for_ingest = staged
                    if preprocess_lo and preprocessors.libreoffice_available():
                        normalized, lo_log = preprocessors.libreoffice_normalize(
                            staged, apath / ".lo-tmp",
                        )
                        if normalized:
                            docx_for_ingest = normalized
                            flash(
                                "LibreOffice normalization succeeded — "
                                "ingest will use the normalized DOCX.",
                                "success",
                            )

                    # Step 2: structural scan + warnings.
                    warnings = preprocessors.scan_docx_for_warnings(docx_for_ingest)
                    for w in warnings:
                        flash(f"DOCX warning: {w}", "warning")

                    # Step 3: actual ingest. Either Mammoth or Pandoc.
                    if ingest_engine == "mammoth":
                        if not preprocessors.mammoth_available():
                            flash(
                                "Mammoth not installed; falling back to "
                                "Pandoc. Run `pip install mammoth` to enable.",
                                "warning",
                            )
                            conversion.ingest_docx(
                                docx_for_ingest, apath,
                                accept_track_changes=accept_tc,
                            )
                        else:
                            raw, log = preprocessors.ingest_with_mammoth(
                                docx_for_ingest, apath,
                            )
                            if raw is None:
                                flash(f"Mammoth ingest failed: {log}", "error")
                                return redirect(request.url)
                            # Append the mammoth log so the user can see
                            # what happened.
                            conversion._append_log(
                                apath, "Stage 1: DOCX ingest (mammoth)", log,
                            )
                    else:
                        conversion.ingest_docx(
                            docx_for_ingest, apath,
                            accept_track_changes=accept_tc,
                        )
                elif ext == ".pdf":
                    # A PDF carries no structure, only placed ink, so ingest
                    # infers the structure back and is a reading rather than a
                    # conversion. Say so: the editor has to check this one
                    # against the page in a way a DOCX ingest does not need.
                    try:
                        conversion.ingest_pdf(staged, apath)
                    except Exception as exc:
                        flash(f"PDF ingest failed: {exc}", "error")
                        return redirect(request.url)
                    flash(
                        "PDF ingest rebuilds structure from the page layout; "
                        "check headings, paragraph breaks, and any hyphenated "
                        "words against the original before publishing.",
                        "warning",
                    )
                else:
                    # Markdown bypass: copy uploaded MD straight to
                    # article-raw.md so cleanups can run on it.
                    raw = apath / "article-raw.md"
                    raw.write_text(
                        staged.read_text(encoding="utf-8"),
                        encoding="utf-8",
                    )
                conversion.run_cleanups(
                    apath,
                    issue_metadata={
                        "short-title": short_title,
                        "short-authors": short_authors,
                    },
                )
                # Pandoc silently drops pictures it cannot place (floating
                # images in text boxes). Save any it lost and say so, since
                # nothing in the Markdown would otherwise show they existed.
                used_pandoc = ingest_engine != "mammoth" or not preprocessors.mammoth_available()
                if ext == ".docx" and used_pandoc:
                    recovered = preprocessors.recover_unplaced_images(apath / "source.docx", apath)
                    if recovered:
                        flash(
                            f"{len(recovered)} image(s) in the DOCX did not come through "
                            "(usually a picture inside a text box): "
                            + ", ".join(recovered)
                            + ". They are saved in the article's assets; place each one "
                            "with Insert image in the Markdown editor.",
                            "warning",
                        )
                        conversion._append_log(
                            apath, "Stage 2b: unplaced images",
                            "".join(f"  - {p}\n" for p in recovered),
                        )
            except Exception as exc:
                flash(f"Conversion failed: {exc}", "error")
                return redirect(request.url)

            title = conversion.plain_text(title_hint or _peek_title(apath / "article.md")) or article_slug
            try:
                article_id = db.execute(
                    "INSERT INTO articles (journal_id, slug, title, project_path, status) "
                    "VALUES (?, ?, ?, ?, 'draft')",
                    (journal["id"], article_slug, title, str(apath)),
                )
            except sqlite3.IntegrityError:
                # UNIQUE(journal_id, slug) collision. The pre-check above
                # missed it (case-insensitive collation, whitespace, or a
                # double-submit). Clean up the directory we just created
                # so the user can retry with a different slug without
                # leftover litter.
                import shutil
                try:
                    if apath.exists() and apath.is_dir():
                        shutil.rmtree(apath)
                except Exception:
                    pass
                flash(
                    f"An article with slug {article_slug!r} already exists in this "
                    "journal. Pick a different slug (use the 'Slug' field on the "
                    "upload form to override the auto-derived value).",
                    "error",
                )
                return redirect(request.url)
            conversion.record_conversion(
                article_id, ext.lstrip("."),
                f"ingest + cleanups OK; project_path={apath}",
            )
            return redirect(url_for("article_home", article_id=article_id))

        import preprocessors
        return render_template(
            "upload.html",
            journal=journal,
            mammoth_available=preprocessors.mammoth_available(),
            libreoffice_available=preprocessors.libreoffice_available(),
        )

    # ---------- article ----------

    @app.route("/articles/<int:article_id>")
    @login_required
    def article_home(article_id):
        article = db.query_one(
            "SELECT a.*, j.slug AS journal_slug, j.name AS journal_name "
            "FROM articles a JOIN journals j ON a.journal_id = j.id WHERE a.id = ?",
            (article_id,),
        )
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        log_path = apath / "conversion.log"
        log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        rendered_html = (apath / "article.html").exists()
        rendered_pdf = (apath / "article.pdf").exists()
        # An article whose teacher material renders as its own galley. The
        # files are what decide this, not the front matter: a chapter marked
        # for the split but not yet re-rendered has nothing to offer yet.
        rendered_teacher_html = (apath / "teacher-resources.html").exists()
        rendered_teacher_pdf = (apath / "teacher-resources.pdf").exists()
        override_css_path = apath / "article-override.css"
        has_override = override_css_path.exists()
        override_size = override_css_path.stat().st_size if has_override else 0
        # Detect grid- or pipe-table syntax so the article page can warn
        # about WYSIWYG editing (ProseMirror's default schema has no
        # table support; opening + saving will mangle them).
        has_tables = False
        md_path = apath / "article.md"
        if md_path.exists():
            sample = md_path.read_text(encoding="utf-8", errors="replace")
            has_tables = ("+---" in sample
                          or "+:---" in sample
                          or "+-+" in sample)
        # Probe optional engine/validator availability so the Advanced
        # section can grey-out buttons that need missing dependencies.
        import validators
        import llm_cleanup
        import ocr as ocr_mod
        # Surface missing image references so the editor can fix them
        # before clicking Render.
        missing_images = conversion.check_missing_image_references(apath)

        # ---- Status-strip data ----
        # Compute everything in one shot so the strip can render without
        # additional queries. All inexpensive (a single file read + a
        # few regex passes).
        import re as _re
        stats = {
            "sections": 0,
            "images": 0,
            "tables": 0,
            "missing": len(missing_images),
            "words": 0,
            "has_bib": (apath / "references.bib").exists(),
            "has_override": has_override,
            "last_rendered": None,
            "last_rendered_iso": None,
            "weasy_pdf_exists": (apath / "article-weasy.pdf").exists(),
            "issue_id": article["issue_id"] if "issue_id" in article.keys() else None,
            "issue_label": None,
        }
        if md_path.exists():
            body_text = md_path.read_text(encoding="utf-8", errors="replace")
            # Strip YAML front matter for a cleaner word count.
            body_only = body_text
            if body_only.startswith("---\n"):
                end = body_only.find("\n---", 4)
                if end != -1:
                    body_only = body_only[end + 4:]
            stats["sections"] = len(_re.findall(r"^#{1,3}\s+\S", body_only, _re.MULTILINE))
            stats["images"] = len(_re.findall(r"!\[[^\]]*\]\([^)\s]+\)", body_only))
            stats["tables"] = (
                body_only.count("\n+---") + body_only.count("\n+:--")
                # Plus pipe tables: lines starting with `| ` followed
                # by a `|---|` separator line.
                + len(_re.findall(r"^\|.+\|\s*$\n^\|[-: |]+\|\s*$", body_only, _re.MULTILINE))
            )
            # Approximate word count: split on whitespace, drop short tokens.
            stats["words"] = sum(1 for w in body_only.split() if len(w) > 1)
        # Last-rendered time: pick the latest mtime of article.html/pdf.
        latest = 0
        for name in ("article.html", "article.pdf"):
            p = apath / name
            if p.exists():
                latest = max(latest, p.stat().st_mtime)
        if latest:
            from datetime import datetime, timezone
            dt = datetime.fromtimestamp(latest, tz=timezone.utc).astimezone()
            stats["last_rendered_iso"] = dt.isoformat(timespec="seconds")
            # Human-readable "Nh ago" string.
            from datetime import datetime as _dt
            ago = _dt.now(timezone.utc).timestamp() - latest
            if ago < 60:
                stats["last_rendered"] = "just now"
            elif ago < 3600:
                stats["last_rendered"] = f"{int(ago // 60)}m ago"
            elif ago < 86400:
                stats["last_rendered"] = f"{int(ago // 3600)}h ago"
            else:
                stats["last_rendered"] = f"{int(ago // 86400)}d ago"

        # Issue label for breadcrumb.
        article_issue_id = article["issue_id"] if "issue_id" in article.keys() else None
        if article_issue_id:
            issue_row = db.query_one(
                "SELECT volume, issue_number, year FROM issues WHERE id = ?",
                (article_issue_id,),
            )
            if issue_row:
                stats["issue_label"] = (
                    f"v{issue_row['volume']}.{issue_row['issue_number']} "
                    f"({issue_row['year']})"
                )

        # Recent activity: last 3 log timestamps from conversion.log.
        recent_activity: list[dict] = []
        if log_text:
            for m in _re.finditer(
                r"=== ([\d\-T:+]+)\s+(.+?) ===", log_text,
            ):
                recent_activity.append({"when": m.group(1), "what": m.group(2)})
            recent_activity = recent_activity[-3:][::-1]

        # Snapshot count for the "Compare" / "Diff" button.
        versions_dir = apath / ".versions"
        snapshot_count = (
            sum(1 for _ in versions_dir.glob("article-*.md"))
            if versions_dir.exists() else 0
        )

        return render_template(
            "article.html",
            article=article,
            # The row itself, so the page can ask what this belongs to
            # rather than reading a kind column off a joined alias: a
            # collection is not deposited and the links have to know.
            journal=_journal_of_article(article_id),
            log_text=log_text,
            rendered_html=rendered_html,
            rendered_pdf=rendered_pdf,
            rendered_teacher_html=rendered_teacher_html,
            rendered_teacher_pdf=rendered_teacher_pdf,
            has_override=has_override,
            override_size=override_size,
            has_tables=has_tables,
            missing_images=missing_images,
            weasyprint_ok=conversion.weasyprint_available(),
            verapdf_ok=validators.verapdf_available(),
            pa11y_ok=validators.pa11y_available(),
            llm_ok=llm_cleanup.available(),
            ocr_ok=ocr_mod.available(),
            stats=stats,
            recent_activity=recent_activity,
            snapshot_count=snapshot_count,
        )

    @app.route("/articles/<int:article_id>/metadata", methods=["GET", "POST"])
    @login_required
    def article_metadata(article_id):
        article = db.query_one(
            "SELECT a.*, j.slug AS journal_slug, j.name AS journal_name "
            "FROM articles a JOIN journals j ON a.journal_id = j.id WHERE a.id = ?",
            (article_id,),
        )
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        fm, body = conversion.read_article_metadata(apath)

        if request.method == "POST":
            updated = dict(fm)
            for key in (
                "title", "subtitle", "short-title", "short-authors", "footer",
                "doi", "abstract", "status", "copyright", "section",
                "journal", "volume", "issue", "year",
            ):
                form_key = key.replace("-", "_")
                val = request.form.get(form_key, "").strip()
                if val:
                    updated[key] = val
                else:
                    updated.pop(key, None)

            # Article kind travels in the YAML front matter (Pandoc reads it
            # into `$kind$` for the Typst template) and is mirrored to the DB
            # so listings can filter without loading each article's file. The
            # default is "article"; the YAML key is dropped in that case to
            # keep existing files unchanged when a user hasn't touched Type.
            selected_kind = (request.form.get("kind") or "article").strip().lower()
            if selected_kind not in {"article", "review", "editorial"}:
                selected_kind = "article"
            if selected_kind == "article":
                updated.pop("kind", None)
            else:
                updated["kind"] = selected_kind

            page = request.form.get("start_page", "").strip()
            if page:
                try:
                    updated["start-page"] = int(page)
                except ValueError:
                    flash("Start page must be a number.", "error")
                    return redirect(request.url)
                # Typing a number here locks it: issue assembly will number
                # around this article rather than renumbering it. Clearing the
                # field hands the article back to automatic pagination.
                updated["start-page-locked"] = True
            else:
                updated.pop("start-page", None)
                updated.pop("start-page-locked", None)

            if request.form.get("hide_page_numbers") == "on":
                updated["hide-page-numbers"] = True
            else:
                updated.pop("hide-page-numbers", None)

            kw_raw = request.form.get("keywords", "").strip()
            if kw_raw:
                updated["keywords"] = [
                    k.strip() for k in kw_raw.replace(";", ",").split(",") if k.strip()
                ]
            else:
                updated.pop("keywords", None)

            author_names = request.form.getlist("author_name")
            author_affils = request.form.getlist("author_affiliation")
            author_orcids = request.form.getlist("author_orcid")
            authors: list[dict] = []
            for i, name in enumerate(author_names):
                name = (name or "").strip()
                if not name:
                    continue
                rec: dict = {"name": name}
                aff = (author_affils[i] if i < len(author_affils) else "").strip()
                if aff:
                    rec["affiliation"] = aff
                orcid = (author_orcids[i] if i < len(author_orcids) else "").strip()
                if orcid:
                    rec["orcid"] = orcid
                authors.append(rec)
            if authors:
                updated["author"] = authors
            else:
                updated.pop("author", None)

            if not updated.get("title"):
                flash("Title is required.", "error")
                return redirect(request.url)
            if not updated.get("short-title") or not updated.get("short-authors"):
                flash("Short title and short authors are required for running headers.", "error")
                return redirect(request.url)

            conversion.write_article_metadata(apath, updated, body)
            new_title = conversion.plain_text(updated.get("title"))
            new_section = updated.get("section")
            db.execute(
                "UPDATE articles SET title = COALESCE(?, title), section = COALESCE(?, section), "
                "kind = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_title, new_section, selected_kind, article_id),
            )

            render_result = conversion.render_all(apath, article["journal_slug"])
            register.record_pdfua(article_id, apath)
            if render_result.errors:
                flash(
                    "Metadata saved, but re-render had issues: " + "; ".join(render_result.errors),
                    "error",
                )
            else:
                flash("Metadata saved and re-rendered.", "success")
            return redirect(url_for("article_home", article_id=article_id))

        kw_string = ""
        if isinstance(fm.get("keywords"), list):
            kw_string = "; ".join(fm["keywords"])
        elif fm.get("keywords"):
            kw_string = str(fm["keywords"])

        authors_list = fm.get("author") or []
        if isinstance(authors_list, dict):
            authors_list = [authors_list]

        journal_row = db.query_one(
            "SELECT toc_sections_json FROM journals WHERE id = ?",
            (article["journal_id"],),
        )
        import json
        toc_sections = []
        if journal_row and journal_row["toc_sections_json"]:
            try:
                toc_sections = json.loads(journal_row["toc_sections_json"]) or []
            except Exception:
                pass
        if not toc_sections:
            toc_sections = ["ARTICLES"]

        return render_template(
            "metadata.html",
            article=article,
            fm=fm,
            authors=authors_list,
            keywords_str=kw_string,
            toc_sections=toc_sections,
        )

    @app.route("/articles/<int:article_id>/edit/wysiwyg", methods=["GET", "POST"])
    @login_required
    def article_edit_wysiwyg(article_id):
        article = db.query_one("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        md_path = apath / "article.md"

        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            body_md = payload.get("body", "")
            fm, _existing_body = conversion.read_article_metadata(apath)
            if fm:
                # Reuse the canonical writer so YAML round-trips correctly.
                conversion.write_article_metadata(apath, fm, body_md)
            else:
                # No YAML; write body as-is.
                conversion.save_markdown(apath, body_md, note="wysiwyg save")
            db.execute(
                "UPDATE articles SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (article_id,),
            )
            return jsonify({"ok": True, "bytes": len(body_md)})

        fm, body = conversion.read_article_metadata(apath)
        return render_template("edit_wysiwyg.html", article=article, body=body, fm=fm)

    @app.route("/articles/<int:article_id>/edit/tinymce", methods=["GET", "POST"])
    @login_required
    def article_edit_tinymce(article_id):
        """Rich-toolbar WYSIWYG editing via TinyMCE.

        TinyMCE is HTML-based but our canonical source is Markdown, so
        we transcode on each side of the editor:
          - GET: Pandoc converts article.md (body only) -> HTML, which
            TinyMCE loads.
          - POST: TinyMCE returns HTML; Pandoc converts HTML -> MD, and
            we write that back to article.md (preserving YAML front
            matter via the canonical writer).

        Round-trip is lossy for some Pandoc-specific extensions (math,
        citations, raw attributes), but lossless enough for the
        formatting TinyMCE actually adds: bold/italic/underline, lists,
        tables, alignment, links, images, blockquotes, code, headings.
        Articles with footnotes survive too — Pandoc emits `[^N]` /
        `[^N]:` in both directions.
        """
        import pypandoc
        article = db.query_one("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        md_path = apath / "article.md"

        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            html_body = payload.get("body", "")
            # Convert HTML -> Markdown.
            #
            # Pandoc-flavored `markdown` (not `markdown_strict`) is the
            # right target: it includes `grid_tables` which can preserve
            # multi-paragraph cells (essential for the tables Word users
            # paste in). We DISABLE `raw_html` so Pandoc is forced to
            # convert HTML tables into native Markdown table syntax
            # rather than dumping the original `<table>` markup inline
            # — raw HTML survives in MD but Pandoc's Typst writer can't
            # render it.
            try:
                md_body = pypandoc.convert_text(
                    html_body,
                    to="markdown+grid_tables+pipe_tables+footnotes+yaml_metadata_block-raw_html-native_divs-native_spans",
                    format="html",
                    extra_args=["--wrap=none"],
                )
            except Exception as exc:
                return jsonify({"ok": False, "error": f"HTML->MD failed: {exc}"}), 500
            fm, _existing_body = conversion.read_article_metadata(apath)
            if fm:
                conversion.write_article_metadata(apath, fm, md_body)
            else:
                conversion.save_markdown(apath, md_body, note="tinymce save")
            db.execute(
                "UPDATE articles SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (article_id,),
            )
            return jsonify({"ok": True, "bytes": len(md_body)})

        # GET: render Markdown -> HTML for TinyMCE to load.
        fm, body = conversion.read_article_metadata(apath)
        try:
            html_body = pypandoc.convert_text(
                body,
                to="html",
                format="markdown+pipe_tables+grid_tables+footnotes+yaml_metadata_block",
                extra_args=["--wrap=none"],
            )
        except Exception as exc:
            flash(f"Could not convert article.md -> HTML for editor: {exc}", "error")
            return redirect(url_for("article_home", article_id=article_id))
        return render_template(
            "edit_tinymce.html",
            article=article,
            html_body=html_body,
        )

    @app.route("/articles/<int:article_id>/edit", methods=["GET", "POST"])
    @login_required
    def article_edit(article_id):
        article = db.query_one("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        md_path = apath / "article.md"

        if request.method == "POST":
            payload = request.get_json(silent=True) or {}
            new_text = payload.get("content", "")
            conversion.save_markdown(apath, new_text, note="editor save")
            db.execute(
                "UPDATE articles SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (article_id,),
            )
            return jsonify({"ok": True, "bytes": len(new_text)})

        md_text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""
        return render_template("edit.html", article=article, md_text=md_text)

    @app.route("/articles/<int:article_id>/render", methods=["POST"])
    @login_required
    def article_render(article_id):
        article = db.query_one(
            "SELECT a.*, j.slug AS journal_slug FROM articles a "
            "JOIN journals j ON a.journal_id = j.id WHERE a.id = ?",
            (article_id,),
        )
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        result = conversion.render_all(apath, article["journal_slug"])
        # Recorded from the galley rather than from the compile. Typst
        # validates PDF/UA instead of declaring it, so one undescribed
        # figure sends `conversion._compile_typst` down its fallback path
        # and the PDF ships readable and unconformant; the fallback writes
        # that to the render log, which nothing counted.
        register.record_pdfua(article_id, apath)
        return jsonify({
            "html": str(result.html_path) if result.html_path else None,
            "pdf": str(result.pdf_path) if result.pdf_path else None,
            "errors": result.errors,
        })

    @app.route("/articles/<int:article_id>/weasy-pdf")
    @login_required
    def serve_weasy_pdf(article_id):
        """Serve the WeasyPrint-rendered alternate PDF."""
        return _serve_artifact(
            article_id, "article-weasy.pdf",
            as_attachment=request.args.get("dl") == "1",
        )

    @app.route("/articles/<int:article_id>/ocr-results")
    @login_required
    def serve_ocr_results(article_id):
        """Serve the OCR results plain text file as a downloadable
        text/plain response so the browser shows it in-line."""
        from flask import Response
        article = db.query_one("SELECT project_path FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        p = Path(article["project_path"]) / "ocr-results.txt"
        if not p.exists():
            abort(404)
        return Response(p.read_text(encoding="utf-8"), mimetype="text/plain")

    @app.route("/articles/<int:article_id>/verapdf-report")
    @login_required
    def serve_verapdf_report(article_id):
        """Render the verapdf JSON report as a readable HTML page."""
        import json
        article = db.query_one("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        p = Path(article["project_path"]) / "verapdf-report.json"
        if not p.exists():
            flash("No verapdf report yet; run Validate PDF/UA first.", "error")
            return redirect(url_for("article_home", article_id=article_id))
        try:
            report = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            report = {"raw": p.read_text(encoding="utf-8")}
        return render_template(
            "validation_report.html",
            article=article, kind="verapdf",
            report=report,
            report_path=p.name,
        )

    @app.route("/articles/<int:article_id>/pa11y-report")
    @login_required
    def serve_pa11y_report(article_id):
        """Render the pa11y JSON report as a readable HTML page."""
        import json
        article = db.query_one("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        p = Path(article["project_path"]) / "pa11y-report.json"
        if not p.exists():
            flash("No pa11y report yet; run Audit HTML accessibility first.", "error")
            return redirect(url_for("article_home", article_id=article_id))
        try:
            issues = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(issues, dict):
                issues = issues.get("issues", [])
        except json.JSONDecodeError:
            issues = []
        return render_template(
            "validation_report.html",
            article=article, kind="pa11y",
            report=issues,
            report_path=p.name,
        )

    @app.route("/articles/<int:article_id>/html")
    @login_required
    def serve_html(article_id):
        return _serve_artifact(
            article_id, "article.html",
            as_attachment=request.args.get("dl") == "1",
        )

    @app.route("/articles/<int:article_id>/html-standalone")
    @login_required
    def serve_html_standalone(article_id):
        """The HTML galley as one self-contained file: stylesheet and
        figures embedded, so it opens styled with nothing beside it."""
        article = db.query_one("SELECT project_path, slug FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        if not (apath / "article.html").exists():
            abort(404)
        from flask import Response
        return Response(
            standalone_html.build(apath),
            mimetype="text/html",
            headers={
                "Content-Disposition": f'attachment; filename="{article["slug"]}.html"',
            },
        )

    @app.route("/articles/<int:article_id>/pdf")
    @login_required
    def serve_pdf(article_id):
        return _serve_artifact(
            article_id, "article.pdf",
            as_attachment=request.args.get("dl") == "1",
        )

    @app.route("/articles/<int:article_id>/teacher-resources.pdf")
    @login_required
    def serve_teacher_pdf(article_id):
        """The teacher galley of a chapter that renders its instructor
        material separately; see `teacher-resources` in the front matter."""
        return _serve_artifact(
            article_id, "teacher-resources.pdf",
            as_attachment=request.args.get("dl") == "1",
        )

    @app.route("/articles/<int:article_id>/teacher-resources.html")
    @login_required
    def serve_teacher_html(article_id):
        return _serve_artifact(
            article_id, "teacher-resources.html",
            as_attachment=request.args.get("dl") == "1",
        )

    @app.route("/articles/<int:article_id>/epub")
    @login_required
    def serve_epub(article_id):
        article = db.query_one(
            "SELECT a.*, j.slug AS journal_slug FROM articles a "
            "JOIN journals j ON a.journal_id = j.id WHERE a.id = ?",
            (article_id,),
        )
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        if conversion.epub_is_stale(apath):
            try:
                conversion.render_epub(apath, article["journal_slug"])
            except Exception as exc:
                flash(f"EPUB render failed: {exc}", "error")
                return redirect(url_for("article_home", article_id=article_id))
        return send_from_directory(
            apath, "article.epub", as_attachment=True,
            download_name=f"{article['slug']}.epub",
        )

    # ---------- figures ----------

    # An image on a line of its own, which is what a DOCX drawing becomes and
    # also what PDF ingest writes.
    #
    # The two differ in one character and it cost this page every figure in
    # the archive. A reconstructed figure is the image, a hard line break, and
    # the caption printed under it, all one paragraph, so the image line ends
    # in a backslash; an end-of-line anchor that does not allow for it matched
    # 34 of the 204 images here and left 38 of the 51 articles holding figures
    # showing an empty page. `_rewrite` has to put the break back, or the
    # caption parts from the figure it belongs to.
    #
    # The caption is lazy rather than a class excluding `]`, for the reason
    # `conversion._BODY_IMAGE_RE` is: a description may carry a bracket of its
    # own, and a class that stops at the first one does not match such a
    # figure at all.
    _FIGURE_RE = re.compile(
        r"^!\[(?P<alt>.*?)\]\((?P<path>[^)]+)\)(?P<attrs>\{[^}]*\})?"
        r"(?P<break>\\)?[ \t]*$",
        re.MULTILINE,
    )

    def _figure_attrs_without_label(attrs: str) -> str:
        return re.sub(r"#fig:[A-Za-z0-9_-]+\s*", "", attrs).strip()

    @app.route("/articles/<int:article_id>/figures", methods=["GET", "POST"])
    @login_required
    def article_figures(article_id):
        """Review every figure in the article in document order.

        The caption-pairing cleanup pass attaches captions Word left adrift,
        but it can only act on paragraphs that look like captions. Anything it
        cannot reach, and anything it guessed wrongly, gets corrected here.

        What this page edits is the bracket and the `#fig:` label, and the
        bracket is not always the same thing. A figure through
        `pair_figure_captions` keeps the printed caption there and its
        description in `fig-alt`, where Pandoc reads it; a figure that has not
        been through it keeps one string doing both jobs. So the description
        is shown here and written in the queue, through
        `conversion.with_description`, which is the function that knows which
        slot a given figure keeps it in. One writer for a description and one
        for a caption, rather than this page overwriting a caption with a
        description and leaving the real one in place to go on winning.
        """
        article = db.query_one(
            "SELECT a.*, j.slug AS journal_slug, j.name AS journal_name "
            "FROM articles a JOIN journals j ON a.journal_id = j.id WHERE a.id = ?",
            (article_id,),
        )
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        fm, body = conversion.read_article_metadata(apath)

        if request.method == "POST":
            captions = request.form.getlist("caption")
            labels = request.form.getlist("label")
            counter = {"i": 0}

            def _rewrite(m):
                i = counter["i"]
                counter["i"] += 1
                caption = (
                    captions[i] if i < len(captions) else m.group("alt")
                ).strip()
                label = (labels[i] if i < len(labels) else "").strip()
                attrs = _figure_attrs_without_label((m.group("attrs") or "")[1:-1])
                if label:
                    if not label.startswith("#fig:"):
                        label = f"#fig:{label}"
                    attrs = f"{label} {attrs}".strip()
                suffix = f"{{{attrs}}}" if attrs else ""
                # The hard break goes back on. It is what joins the figure to
                # the caption printed under it, and dropping it leaves the
                # caption standing as a paragraph of its own.
                return (f"![{caption}]({m.group('path')}){suffix}"
                        f"{m.group('break') or ''}")

            new_body = _FIGURE_RE.sub(_rewrite, body)
            if new_body == body:
                flash("No figure changes to save.", "info")
            else:
                conversion.write_article_metadata(apath, fm, new_body)
                flash(
                    "Figures updated and snapshotted. Render to apply.", "success"
                )
            return redirect(url_for("article_figures", article_id=article_id))

        figures = []
        for n, m in enumerate(_FIGURE_RE.finditer(body), 1):
            path = m.group("path")
            attrs = (m.group("attrs") or "")[1:-1]
            label_match = re.search(r"#fig:([A-Za-z0-9_-]+)", attrs)
            # serve_asset is rooted at the article's assets/ directory.
            relative = path[len("assets/"):] if path.startswith("assets/") else None
            figures.append({
                "n": n,
                "caption": m.group("alt"),
                "path": path,
                "name": path.rsplit("/", 1)[-1],
                "asset_path": relative,
                "label": label_match.group(1) if label_match else "",
                "other_attrs": _figure_attrs_without_label(attrs),
                "exists": (apath / path).exists(),
                # Read from whichever slot holds it, which is the one function
                # that knows; shown rather than edited here.
                "description": conversion._carried_description(m),
                "state": lint.figure_state(m, body),
                # A hard break means the figure and its caption are one
                # paragraph, so Pandoc does not make it a Figure and the
                # figures filter does not number it: the printed numbering in
                # the caption is the numbering, and the prose refers to it.
                "joined": bool(m.group("break")),
            })

        return render_template("figures.html", article=article,
                               figures=figures,
                               state_labels=describe.STATE_LABELS,
                               state_tones=describe.STATE_TONE)

    @app.route("/articles/<int:article_id>/assets/<path:filename>")
    @login_required
    def serve_asset(article_id, filename):
        article = db.query_one("SELECT project_path FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        return send_from_directory(Path(article["project_path"]) / "assets", filename)

    @app.route("/articles/<int:article_id>/css/<path:filename>")
    @login_required
    def serve_article_css(article_id, filename):
        article = db.query_one("SELECT project_path FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        return send_from_directory(Path(article["project_path"]), filename)

    # Inline CSS routes: Pandoc emits `<link href="article.css">` (a
    # relative URL) in the rendered HTML. When the article is served at
    # /articles/<id>/html via Flask, that relative URL resolves to
    # /articles/<id>/article.css, so the file needs a matching route to
    # actually load. Same for the per-article override.
    @app.route("/articles/<int:article_id>/article.css")
    @login_required
    def serve_article_inline_css(article_id):
        return _serve_artifact(article_id, "article.css")

    @app.route("/articles/<int:article_id>/article-override.css")
    @login_required
    def serve_article_inline_override_css(article_id):
        return _serve_artifact(article_id, "article-override.css")

    # ---------- CrossRef ----------

    @app.route("/crossref")
    @login_required
    def crossref_home():
        import new_journal

        # Collections are left out rather than shown as not ready: they are
        # not short of a prefix, they are not deposited at all, and a row
        # saying "missing: crossref_prefix" invites somebody to go and
        # supply one.
        journal_rows = [row for row
                        in db.query_all("SELECT * FROM journals ORDER BY name")
                        if not new_journal.is_collection(row)]
        journals = []
        for jr in journal_rows:
            j = dict(jr)
            ready, missing = crossref.crossref_readiness(j)
            # Sample DOI preview
            try:
                sample_doi = crossref.assign_doi(
                    j,
                    {"volume": 13, "issue_number": 1, "year": 2026},
                    {"slug": "example-2026"},
                    position=1,
                )
            except Exception:
                sample_doi = "(unable to compute)"
            j["_ready"] = ready
            j["_missing"] = missing
            j["_sample_doi"] = sample_doi
            j["_issues"] = db.query_all(
                "SELECT i.*, "
                "  (SELECT COUNT(*) FROM articles a WHERE a.issue_id = i.id AND COALESCE(a.kind,'article') != 'editorial') AS article_count "
                "FROM issues i WHERE i.journal_id = ? "
                "ORDER BY i.year DESC, i.volume DESC, i.issue_number DESC",
                (j["id"],),
            )
            journals.append(j)
        return render_template("crossref.html", journals=journals)

    @app.route("/articles/<int:article_id>/jats.xml")
    @login_required
    def article_jats_xml(article_id):
        try:
            xml = jats.build_article_jats(
                article_id, base_url=request.host_url.rstrip("/")
            )
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("article_home", article_id=article_id))
        from flask import Response
        article = db.query_one("SELECT slug FROM articles WHERE id = ?", (article_id,))
        filename = f"{article['slug']}-jats.xml" if article else f"article-{article_id}-jats.xml"
        return Response(
            xml,
            mimetype="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.route("/articles/<int:article_id>/crossref.xml")
    @login_required
    def article_crossref_xml(article_id):
        _refuse_deposit_for_a_collection(_journal_of_article(article_id))
        try:
            xml = crossref.build_article_deposit_xml(
                article_id, base_url=request.host_url.rstrip("/")
            )
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("article_home", article_id=article_id))
        from flask import Response
        article = db.query_one("SELECT slug FROM articles WHERE id = ?", (article_id,))
        filename = f"{article['slug']}-crossref.xml" if article else f"article-{article_id}-crossref.xml"
        return Response(
            xml,
            mimetype="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.route("/issues/<int:issue_id>/crossref.xml")
    @login_required
    def issue_crossref_xml(issue_id):
        _refuse_deposit_for_a_collection(_journal_of_issue(issue_id))
        try:
            xml = crossref.build_issue_deposit_xml(
                issue_id, base_url=request.host_url.rstrip("/")
            )
        except ValueError as exc:
            flash(str(exc), "error")
            return redirect(url_for("issue_home", issue_id=issue_id))
        from flask import Response
        issue = db.query_one("SELECT volume, issue_number, year FROM issues WHERE id = ?", (issue_id,))
        filename = (
            f"issue-v{issue['volume']}-n{issue['issue_number']}-{issue['year']}-crossref.xml"
            if issue else f"issue-{issue_id}-crossref.xml"
        )
        return Response(
            xml,
            mimetype="application/xml",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.route("/articles/<int:article_id>/override-css", methods=["POST"])
    @login_required
    def article_upload_override_css(article_id):
        article = db.query_one("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        f = request.files.get("override_css")
        if not f or not f.filename:
            flash("No file uploaded.", "error")
            return redirect(url_for("article_home", article_id=article_id))
        if not f.filename.lower().endswith(".css"):
            flash("Override stylesheet must be a .css file.", "error")
            return redirect(url_for("article_home", article_id=article_id))
        target = Path(article["project_path"]) / "article-override.css"
        f.save(target)
        flash(
            f"Per-article CSS saved ({target.stat().st_size:,} bytes). "
            "Re-render to apply.",
            "success",
        )
        return redirect(url_for("article_home", article_id=article_id))

    @app.route("/articles/<int:article_id>/override-css", methods=["DELETE", "POST"], endpoint="article_remove_override_css")
    @login_required
    def article_remove_override_css(article_id):
        # Accept POST with a hidden _method=DELETE for HTML forms.
        if request.method == "POST" and request.form.get("_method") != "DELETE":
            abort(405)
        article = db.query_one("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        target = Path(article["project_path"]) / "article-override.css"
        if target.exists():
            target.unlink()
            flash("Per-article CSS removed. Re-render to revert.", "success")
        else:
            flash("No per-article CSS to remove.", "info")
        return redirect(url_for("article_home", article_id=article_id))

    @app.route("/articles/<int:article_id>/bibliography", methods=["POST"])
    @login_required
    def article_upload_bibliography(article_id):
        article = db.query_one(
            "SELECT * FROM articles WHERE id = ?", (article_id,),
        )
        if not article:
            abort(404)
        f = request.files.get("bibliography")
        if not f or not f.filename:
            flash("No file uploaded.", "error")
            return redirect(url_for("article_home", article_id=article_id))
        if not f.filename.lower().endswith(".bib"):
            flash("Bibliography must be a .bib file.", "error")
            return redirect(url_for("article_home", article_id=article_id))
        target = Path(article["project_path"]) / "references.bib"
        f.save(target)
        flash(f"Bibliography saved ({target.stat().st_size:,} bytes). Re-render to use it.", "success")
        return redirect(url_for("article_home", article_id=article_id))

    @app.route("/articles/<int:article_id>/render-weasy", methods=["POST"])
    @login_required
    def article_render_weasy(article_id):
        """Render an alternate PDF via WeasyPrint from the HTML galley.
        Output: article-weasy.pdf alongside the standard article.pdf."""
        article = db.query_one(
            "SELECT a.*, j.slug AS journal_slug FROM articles a "
            "JOIN journals j ON a.journal_id = j.id WHERE a.id = ?",
            (article_id,),
        )
        if not article:
            abort(404)
        try:
            out = conversion.render_pdf_weasy(
                Path(article["project_path"]), article["journal_slug"],
            )
            view_url = url_for("serve_weasy_pdf", article_id=article_id)
            dl_url = view_url + "?dl=1"
            flash(Markup(
                f"WeasyPrint PDF rendered ({out.stat().st_size:,} bytes). "
                f"<a href='{view_url}' target='_blank'>View →</a> &middot; "
                f"<a href='{dl_url}'>Download →</a>"
            ), "success")
        except Exception as exc:
            flash(f"WeasyPrint render failed: {exc}", "error")
        return redirect(url_for("article_home", article_id=article_id))

    @app.route("/articles/<int:article_id>/validate-pdf", methods=["POST"])
    @login_required
    def article_validate_pdf(article_id):
        """Run verapdf PDF/UA accessibility validation on article.pdf."""
        import validators
        article = db.query_one("SELECT project_path FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        pdf = Path(article["project_path"]) / "article.pdf"
        if not pdf.exists():
            flash("No article.pdf to validate. Render first.", "error")
            return redirect(url_for("article_home", article_id=article_id))
        if not validators.verapdf_available():
            # Nothing recorded. A run is the newest run for its kind, so a
            # row saying the tool could not start would bury whatever a real
            # run had left and `register.latest_run` would hand that back as
            # the current answer. A missing tool is a fact about this
            # machine; the register is about the content.
            flash("verapdf is not on PATH; install it from https://verapdf.org/ "
                  "and try again. Nothing was recorded.", "warning")
            return redirect(url_for("article_home", article_id=article_id))
        # Hashed before the run, so the register dates the verdict to the
        # bytes verapdf read rather than to whatever is there afterwards.
        content_hash = register.hash_for(article["project_path"], "verapdf")
        passed, report = validators.run_verapdf(pdf)
        # Save the full report next to the PDF for later inspection.
        (Path(article["project_path"]) / "verapdf-report.json").write_text(
            __import__("json").dumps(report, indent=2), encoding="utf-8",
        )
        register.record_verapdf(article_id, article["project_path"], passed,
                                report, content_hash=content_hash)
        # What the galley declares, against the same bytes verapdf read. The
        # two answer different questions: this one is what the file says
        # about itself, and verapdf is whether the claim holds up.
        register.record_pdfua(article_id, article["project_path"],
                              content_hash=content_hash)
        view_url = url_for("serve_verapdf_report", article_id=article_id)
        if passed:
            flash(Markup(
                f"PDF/UA-1 validation passed. <a href='{view_url}' target='_blank'>View report →</a>"
            ), "success")
        else:
            err = report.get("error", "see report for details")
            flash(Markup(
                f"PDF/UA-1 validation failed. {err} <a href='{view_url}' target='_blank'>View report →</a>"
            ), "warning")
        return redirect(url_for("article_home", article_id=article_id))

    @app.route("/articles/<int:article_id>/validate-html", methods=["POST"])
    @login_required
    def article_validate_html(article_id):
        """Run pa11y accessibility audit on article.html."""
        import validators
        article = db.query_one("SELECT project_path FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        html = Path(article["project_path"]) / "article.html"
        if not html.exists():
            flash("No article.html to audit. Render first.", "error")
            return redirect(url_for("article_home", article_id=article_id))
        if not validators.pa11y_available():
            flash("pa11y is not installed; run `npm install -g pa11y` and try "
                  "again. Nothing was recorded.", "warning")
            return redirect(url_for("article_home", article_id=article_id))
        content_hash = register.hash_for(article["project_path"], "pa11y")
        passed, issues = validators.run_pa11y(html)
        (Path(article["project_path"]) / "pa11y-report.json").write_text(
            __import__("json").dumps(issues, indent=2), encoding="utf-8",
        )
        register.record_pa11y(article_id, article["project_path"], passed,
                              issues, content_hash=content_hash)
        view_url = url_for("serve_pa11y_report", article_id=article_id)
        if passed:
            flash(Markup(
                f"Accessibility audit clean; 0 issues found. <a href='{view_url}' target='_blank'>View report →</a>"
            ), "success")
        else:
            errors = sum(1 for i in issues if i.get("type") == "error")
            warnings_n = sum(1 for i in issues if i.get("type") == "warning")
            flash(Markup(
                f"Accessibility audit: {errors} error(s), {warnings_n} warning(s). "
                f"<a href='{view_url}' target='_blank'>View report →</a>"
            ), "warning")
        return redirect(url_for("article_home", article_id=article_id))

    @app.route("/articles/<int:article_id>/validate-epub", methods=["POST"])
    @login_required
    def article_validate_epub(article_id):
        """Run epubcheck over article.epub.

        The fifth register kind. `epub_a11y` writes real
        `dcterms:conformsTo` and `a11y:certifiedBy` claims into the package
        document, and nothing read the file back; a false accessibility
        claim is worse than a missing one, because it tells a reader the
        book will work for them.
        """
        import validators
        article = db.query_one("SELECT project_path FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        epub = Path(article["project_path"]) / "article.epub"
        if not epub.exists():
            flash("No article.epub to audit. Render the EPUB first.", "error")
            return redirect(url_for("article_home", article_id=article_id))
        if not validators.epubcheck_available():
            # Asked before the call for the reason `validate_galleys.py`
            # refuses a kind: a run that cannot reach the tool would write
            # "not checked" over whatever a real one had left.
            flash("epubcheck is not installed; see "
                  "https://www.w3.org/publishing/epubcheck/ or set "
                  "EPUBCHECK_PATH. Nothing was recorded.", "warning")
            return redirect(url_for("article_home", article_id=article_id))
        content_hash = register.hash_for(article["project_path"], "epubcheck")
        passed, report = validators.run_epubcheck(epub)
        (Path(article["project_path"]) / "epubcheck-report.json").write_text(
            __import__("json").dumps(report, indent=2), encoding="utf-8",
        )
        register.record_epubcheck(article_id, article["project_path"], passed,
                                  report, content_hash=content_hash)
        counts = report.get("severity_counts") or {}
        if passed:
            warned = counts.get("WARNING", 0)
            flash(f"epubcheck found no errors"
                  f"{f'; {warned} warning(s)' if warned else ''}.", "success")
        else:
            errors = counts.get("ERROR", 0) + counts.get("FATAL", 0)
            flash(f"epubcheck reports {errors} error(s) in the container.",
                  "warning")
        return redirect(url_for("article_home", article_id=article_id))

    @app.route("/articles/<int:article_id>/stylize", methods=["POST"])
    @login_required
    def article_stylize(article_id):
        """Send the article body + journal style guide to Claude and
        write back the restructured result. The journal's style guide
        lives at `content/journals/<slug>/template/style-guide.md`; if
        present it's used verbatim, otherwise Claude falls back to
        general MLA conventions.

        Snapshot before write so the user can roll back via the
        snapshots view if Claude misbehaves. The YAML front matter is
        preserved by the canonical writer; only the body is sent to
        Claude.
        """
        import stylize
        if not stylize.available():
            flash(
                "Claude API unavailable. Set ANTHROPIC_API_KEY and "
                "`pip install anthropic`.",
                "error",
            )
            return redirect(url_for("article_home", article_id=article_id))
        article = db.query_one(
            "SELECT a.*, j.slug AS journal_slug FROM articles a "
            "JOIN journals j ON a.journal_id = j.id WHERE a.id = ?",
            (article_id,),
        )
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        tpl_dir = conversion.template_dir(article["journal_slug"])
        style_guide = stylize.load_style_guide(tpl_dir)

        fm, body = conversion.read_article_metadata(apath)
        if not body.strip():
            flash("Article body is empty.", "error")
            return redirect(url_for("article_home", article_id=article_id))

        try:
            new_body, meta = stylize.stylize(
                body, style_guide,
                article_title=str(fm.get("title", "") if fm else ""),
            )
        except Exception as exc:
            flash(f"Claude API error: {exc}", "error")
            return redirect(url_for("article_home", article_id=article_id))

        if new_body is None:
            flash(meta.get("error", "Stylize failed"), "error")
            return redirect(url_for("article_home", article_id=article_id))

        # Snapshot before writing — gives the user one-click rollback
        # via the Snapshots view if Claude misbehaves.
        conversion._snapshot_version(apath)
        if fm:
            conversion.write_article_metadata(apath, fm, new_body)
        else:
            conversion.save_markdown(apath, new_body, note="stylize via Claude")

        flash(
            f"Stylized via {meta.get('model', 'Claude')}: "
            f"{meta.get('input_tokens', 0):,} input + "
            f"{meta.get('output_tokens', 0):,} output tokens "
            f"(~${meta.get('estimated_cost_usd', 0):.4f}). "
            "Original snapshotted to .versions/. Re-render to apply.",
            "success",
        )
        return redirect(url_for("article_home", article_id=article_id))

    @app.route("/articles/<int:article_id>/llm-tables", methods=["POST"])
    @login_required
    def article_llm_repair_tables(article_id):
        """Find every grid table in article.md and ask Claude to rebuild
        it as a clean Markdown pipe table. The original article.md is
        snapshotted to .versions/ first so you can roll back if Claude's
        reconstruction misbehaves.
        """
        import llm_cleanup
        if not llm_cleanup.available():
            flash(
                "Claude API unavailable. Set ANTHROPIC_API_KEY and "
                "`pip install anthropic`.",
                "error",
            )
            return redirect(url_for("article_home", article_id=article_id))
        article = db.query_one("SELECT project_path FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        md_path = apath / "article.md"
        if not md_path.exists():
            flash("No article.md to scan for tables.", "error")
            return redirect(url_for("article_home", article_id=article_id))

        text = md_path.read_text(encoding="utf-8")
        # Find each grid table: a block starting with a `+---+`-style
        # separator and ending at the next blank line or end of run of
        # `|`/`+` lines.
        lines = text.split("\n")
        out_lines: list[str] = []
        i = 0
        n_repaired = 0
        n_failed = 0
        while i < len(lines):
            line = lines[i]
            if line.lstrip().startswith("+") and "---" in line:
                # Collect until we leave the table block.
                start = i
                while i < len(lines) and (
                    lines[i].lstrip().startswith("+")
                    or lines[i].lstrip().startswith("|")
                    or not lines[i].strip()  # allow blank lines mid-table
                ):
                    # Stop at a true blank-line gap (two blank lines in a row).
                    if not lines[i].strip() and i + 1 < len(lines) and not lines[i + 1].strip():
                        break
                    i += 1
                end = i
                table_block = "\n".join(lines[start:end]).rstrip()
                # Bound the size we send to Claude (keep cost predictable).
                if 50 <= len(table_block) <= 12000:
                    # Provide ~400 chars of context on each side for the prompt.
                    before_ctx = "\n".join(lines[max(0, start - 6):start])[-400:]
                    after_ctx = "\n".join(lines[end:end + 6])[:400]
                    try:
                        repaired = llm_cleanup.repair_mangled_table(
                            table_block, context=before_ctx + "\n\n" + after_ctx,
                        )
                    except Exception as exc:
                        flash(f"Claude API error on table at line {start}: {exc}", "warning")
                        repaired = None
                    if repaired:
                        out_lines.append("")
                        out_lines.append(repaired)
                        out_lines.append("")
                        n_repaired += 1
                        continue
                    else:
                        n_failed += 1
                # Fallback: keep the original table block.
                out_lines.extend(lines[start:end])
                continue
            out_lines.append(line)
            i += 1

        if n_repaired > 0:
            conversion._snapshot_version(apath)
            md_path.write_text("\n".join(out_lines), encoding="utf-8")
            flash(
                f"Repaired {n_repaired} table(s) with Claude. "
                f"{'(' + str(n_failed) + ' failed and kept original.) ' if n_failed else ''}"
                "Original snapshotted to .versions/. Re-render to apply.",
                "success",
            )
        else:
            flash(
                "No tables successfully repaired. "
                "Either there were no grid tables to repair, "
                "or Claude declined to reconstruct them.",
                "warning",
            )
        return redirect(url_for("article_home", article_id=article_id))

    @app.route("/articles/<int:article_id>/llm-alt-text", methods=["POST"])
    @login_required
    def article_llm_alt_text(article_id):
        """Generate alt text for any image without one via Claude vision."""
        import llm_cleanup
        if not llm_cleanup.available():
            flash(
                "Claude API unavailable. Set ANTHROPIC_API_KEY and "
                "`pip install anthropic`.",
                "error",
            )
            return redirect(url_for("article_home", article_id=article_id))
        article = db.query_one("SELECT project_path FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        md_path = apath / "article.md"
        if not md_path.exists():
            flash("No article.md to scan for images.", "error")
            return redirect(url_for("article_home", article_id=article_id))
        # Find each `![](path)` reference in the article and check if
        # the alt text is empty. If so, generate one and rewrite.
        text = md_path.read_text(encoding="utf-8")
        pattern = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")
        n_generated = 0
        new_chunks: list[str] = []
        cursor = 0
        for m in pattern.finditer(text):
            new_chunks.append(text[cursor:m.start()])
            alt, src = m.group(1), m.group(2)
            if not alt.strip() and not src.startswith("http"):
                img_path = apath / src
                if img_path.exists():
                    surrounding = text[max(0, m.start()-400):m.end()+400]
                    try:
                        alt_text = llm_cleanup.generate_alt_text(img_path, surrounding)
                    except Exception as exc:
                        alt_text = None
                        flash(f"Claude API error on {src}: {exc}", "warning")
                    if alt_text:
                        new_chunks.append(f"![{alt_text}]({src})")
                        n_generated += 1
                        cursor = m.end()
                        continue
            new_chunks.append(m.group(0))
            cursor = m.end()
        new_chunks.append(text[cursor:])
        if n_generated:
            md_path.write_text("".join(new_chunks), encoding="utf-8")
            flash(f"Generated {n_generated} alt-text description(s). Re-render to apply.", "success")
        else:
            flash("No images needed alt text (all already have descriptions).", "success")
        return redirect(url_for("article_home", article_id=article_id))

    @app.route("/articles/<int:article_id>/ocr-images", methods=["POST"])
    @login_required
    def article_ocr_images(article_id):
        """Run Tesseract OCR on all images in the article and dump the
        recognized text to ocr-results.txt for the editor to inspect."""
        import ocr as ocr_mod
        if not ocr_mod.available():
            flash(
                "Tesseract OCR unavailable. Install the tesseract CLI "
                "(see https://github.com/UB-Mannheim/tesseract/wiki) and "
                "`pip install pytesseract Pillow`.",
                "error",
            )
            return redirect(url_for("article_home", article_id=article_id))
        article = db.query_one("SELECT project_path FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        assets = apath / "assets"
        if not assets.exists():
            flash("No assets/ directory to scan for images.", "error")
            return redirect(url_for("article_home", article_id=article_id))
        out_lines: list[str] = []
        n_processed = 0
        for img in assets.rglob("*"):
            if img.is_file() and img.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".tiff", ".tif", ".bmp", ".webp"}:
                out_lines.append(f"=== {img.relative_to(apath)} ===\n")
                text = ocr_mod.ocr_image(img)
                if text:
                    out_lines.append(text.strip())
                    out_lines.append("\n\n")
                    n_processed += 1
        if n_processed:
            (apath / "ocr-results.txt").write_text("\n".join(out_lines), encoding="utf-8")
            view_url = url_for("serve_ocr_results", article_id=article_id)
            flash(Markup(
                f"OCR'd {n_processed} image(s). "
                f"<a href='{view_url}' target='_blank'>View results →</a> "
                "(copy any tables into article.md as Markdown)."
            ), "success")
        else:
            flash("No OCR-able images found in assets/.", "warning")
        return redirect(url_for("article_home", article_id=article_id))

    @app.route("/articles/<int:article_id>/snapshots")
    @login_required
    def article_snapshots(article_id):
        """List article.md snapshots with a diff link for each."""
        article = db.query_one("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        versions_dir = apath / ".versions"
        snapshots = []
        if versions_dir.exists():
            for p in sorted(versions_dir.glob("article-*.md"), reverse=True):
                snapshots.append({
                    "name": p.name,
                    "size": p.stat().st_size,
                    "mtime": p.stat().st_mtime,
                })
        return render_template(
            "snapshots.html", article=article, snapshots=snapshots,
        )

    @app.route("/articles/<int:article_id>/diff/<snapshot>")
    @login_required
    def article_diff(article_id, snapshot):
        """Show a unified diff between a snapshot and the current article.md."""
        import difflib
        article = db.query_one("SELECT * FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        snapshot = secure_filename(snapshot)
        snap_path = apath / ".versions" / snapshot
        cur_path = apath / "article.md"
        if not snap_path.exists() or not cur_path.exists():
            abort(404)
        snap_text = snap_path.read_text(encoding="utf-8").splitlines(keepends=True)
        cur_text = cur_path.read_text(encoding="utf-8").splitlines(keepends=True)
        diff_lines = list(difflib.unified_diff(
            snap_text, cur_text,
            fromfile=f"snapshot: {snapshot}",
            tofile="current: article.md",
            n=3,
        ))
        return render_template(
            "diff.html", article=article, snapshot=snapshot, diff_lines=diff_lines,
        )

    @app.route("/articles/<int:article_id>/reclean", methods=["POST"])
    @login_required
    def article_reclean(article_id):
        """Regenerate article.md from article-raw.md by re-running the
        cleanups pipeline. Useful when the WYSIWYG editor (which doesn't
        support grid tables) has mangled an article's table structure
        on save, or when cleanup logic has been updated since the
        article was first ingested. Preserves the existing YAML front
        matter so metadata edits aren't lost."""
        article = db.query_one(
            "SELECT * FROM articles WHERE id = ?", (article_id,),
        )
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        raw_path = apath / "article-raw.md"
        md_path = apath / "article.md"
        if not raw_path.exists():
            flash(
                "No article-raw.md available to re-clean from. This article "
                "may pre-date raw snapshotting; edit article.md by hand.",
                "error",
            )
            return redirect(url_for("article_home", article_id=article_id))

        # Preserve current YAML front matter so user's metadata edits
        # survive the re-clean.
        import yaml as _yaml
        fm, _existing_body = conversion.read_article_metadata(apath)
        # Snapshot current article.md before overwriting.
        try:
            conversion._snapshot_version(apath)
        except Exception:
            pass
        try:
            conversion.run_cleanups(apath, issue_metadata=None)
            # run_cleanups writes article.md from article-raw.md, blowing
            # away the existing YAML. Re-apply the saved metadata.
            if fm:
                conversion.write_article_metadata(apath, fm)
        except Exception as exc:
            flash(f"Re-clean failed: {exc}", "error")
            return redirect(url_for("article_home", article_id=article_id))
        flash(
            "Re-cleaned article.md from article-raw.md. Render to see results.",
            "success",
        )
        return redirect(url_for("article_home", article_id=article_id))

    @app.route("/articles/<int:article_id>/ojs-package")
    @login_required
    def article_ojs_package(article_id):
        """Bundle the rendered HTML galley + its assets into a ZIP for
        OJS upload. OJS's galley submission flow wants the HTML file
        and image files uploaded separately, but the editor can upload
        a single ZIP that OJS will unpack. Includes article.html,
        article.css, and the assets/ directory.
        """
        import zipfile
        import io
        _refuse_deposit_for_a_collection(_journal_of_article(article_id))
        article = db.query_one(
            "SELECT a.*, j.slug AS journal_slug FROM articles a "
            "JOIN journals j ON a.journal_id = j.id WHERE a.id = ?",
            (article_id,),
        )
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        html_path = apath / "article.html"
        if not html_path.exists():
            flash(
                "No rendered HTML to package. Click Render first.",
                "error",
            )
            return redirect(url_for("article_home", article_id=article_id))

        # Resolve the journal's CSS (or per-article override if present).
        css_paths: list[Path] = []
        tpl = conversion.template_dir(article["journal_slug"])
        if (tpl / "article.css").exists():
            css_paths.append(tpl / "article.css")
        if (apath / "article-override.css").exists():
            css_paths.append(apath / "article-override.css")

        slug = article["slug"]
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            # HTML at the root, named after the article slug.
            z.write(html_path, arcname=f"{slug}.html")
            # CSS files alongside.
            for css in css_paths:
                z.write(css, arcname=css.name)
            # All assets recursively.
            assets_dir = apath / "assets"
            if assets_dir.exists():
                for f in assets_dir.rglob("*"):
                    if f.is_file():
                        rel = f.relative_to(apath)
                        z.write(f, arcname=str(rel).replace("\\", "/"))
        buf.seek(0)
        from flask import Response
        return Response(
            buf.getvalue(),
            mimetype="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="{slug}-ojs.zip"',
            },
        )

    @app.route("/articles/<int:article_id>/ojs-upload", methods=["GET", "POST"])
    @login_required
    def article_ojs_upload(article_id):
        """Push a rendered galley file directly into an existing OJS
        submission via the REST API. Reads OJS credentials from the
        journal row (see Journal Settings → OJS). The submission itself
        must already exist in OJS; this endpoint attaches a galley to it.
        """
        article = db.query_one(
            "SELECT a.*, j.slug AS journal_slug "
            "FROM articles a JOIN journals j ON a.journal_id = j.id "
            "WHERE a.id = ?",
            (article_id,),
        )
        if not article:
            abort(404)
        journal = db.query_one("SELECT * FROM journals WHERE id = ?", (article["journal_id"],))
        if not journal:
            abort(404)
        _refuse_deposit_for_a_collection(journal)
        journal = dict(journal)

        apath = Path(article["project_path"])
        # (form-value, file relative to apath, default label)
        galley_choices = [
            ("pdf", "article.pdf", "PDF"),
            ("html", "article.html", "HTML"),
            ("epub", "article.epub", "EPUB"),
            ("ojs_zip", None, "HTML (OJS ZIP)"),
        ]
        available = []
        for key, rel, label in galley_choices:
            if key == "ojs_zip":
                # ZIP is generated on demand; offer it whenever HTML exists.
                if (apath / "article.html").exists():
                    available.append((key, label))
            else:
                if (apath / rel).exists():
                    available.append((key, label))

        if not ojs_client.ojs_configured(journal):
            flash(
                "OJS is not configured for this journal. Add the API URL and token in "
                "Journal Settings before pushing.",
                "error",
            )
            return redirect(url_for("journal_settings", slug=article["journal_slug"]))

        if request.method == "POST":
            submission_id = (request.form.get("submission_id") or "").strip()
            galley_kind = (request.form.get("galley_kind") or "").strip()
            label = (request.form.get("label") or "").strip()
            locale = (request.form.get("locale") or "en").strip() or "en"

            if not submission_id.isdigit():
                flash("Submission ID must be a positive integer (find it in the OJS submission URL).", "error")
                return redirect(request.url)

            match = next(((k, r, l) for k, r, l in galley_choices if k == galley_kind), None)
            if match is None:
                flash("Pick a rendered file to upload.", "error")
                return redirect(request.url)
            _, rel, default_label = match
            label = label or default_label

            # Resolve the file to send.
            import io, zipfile
            from flask import g  # noqa: F401
            upload_path: Optional[Path] = None
            tmp_upload: Optional[Path] = None
            try:
                if galley_kind == "ojs_zip":
                    html_path = apath / "article.html"
                    if not html_path.exists():
                        flash("No rendered HTML to bundle. Render the article first.", "error")
                        return redirect(request.url)
                    tpl = conversion.template_dir(article["journal_slug"])
                    css_paths = []
                    if (tpl / "article.css").exists():
                        css_paths.append(tpl / "article.css")
                    if (apath / "article-override.css").exists():
                        css_paths.append(apath / "article-override.css")
                    slug = article["slug"]
                    tmp_upload = apath / f".{slug}-ojs.zip"
                    with zipfile.ZipFile(tmp_upload, "w", zipfile.ZIP_DEFLATED) as z:
                        z.write(html_path, arcname=f"{slug}.html")
                        for css in css_paths:
                            z.write(css, arcname=css.name)
                        assets_dir = apath / "assets"
                        if assets_dir.exists():
                            for f in assets_dir.rglob("*"):
                                if f.is_file():
                                    z.write(f, arcname=str(f.relative_to(apath)).replace("\\", "/"))
                    upload_path = tmp_upload
                elif galley_kind == "html":
                    # The bare article.html links article.css and assets/ by
                    # relative path, so on its own in OJS it shows unstyled
                    # with broken figures. Send the self-contained version.
                    if not (apath / "article.html").exists():
                        flash("HTML has not been rendered for this article yet.", "error")
                        return redirect(request.url)
                    tmp_dir = apath / ".ojs-upload"
                    tmp_dir.mkdir(exist_ok=True)
                    tmp_upload = tmp_dir / f"{article['slug']}.html"
                    tmp_upload.write_text(standalone_html.build(apath), encoding="utf-8")
                    upload_path = tmp_upload
                else:
                    upload_path = apath / rel
                    if not upload_path.exists():
                        flash(f"{default_label} has not been rendered for this article yet.", "error")
                        return redirect(request.url)

                result = ojs_client.upload_galley(
                    journal=journal,
                    submission_id=int(submission_id),
                    galley_label=label,
                    galley_locale=locale,
                    file_path=upload_path,
                )
                galley_id = result.get("id") if isinstance(result, dict) else None
                if galley_id:
                    flash(
                        f"Uploaded {label} galley to OJS submission {submission_id} "
                        f"(galley id {galley_id}).",
                        "success",
                    )
                else:
                    flash(
                        f"Uploaded {label} galley to OJS submission {submission_id}.",
                        "success",
                    )
                return redirect(url_for("article_home", article_id=article_id))
            except Exception as exc:
                flash(f"OJS upload failed: {exc}", "error")
                return redirect(request.url)
            finally:
                if tmp_upload and tmp_upload.exists():
                    try:
                        tmp_upload.unlink()
                    except OSError:
                        pass

        # GET: render the form. Best-effort submissions dropdown.
        submissions = ojs_client.list_submissions(journal)
        return render_template(
            "article_ojs_upload.html",
            article=article,
            journal=journal,
            available=available,
            submissions=submissions,
        )

    @app.route("/articles/<int:article_id>/delete", methods=["POST"])
    @login_required
    def article_delete(article_id):
        """Delete an article. Removes the DB row AND the on-disk
        directory at project_path. Irreversible — the dashboard's
        delete button uses a JavaScript confirm to gate this.
        """
        import shutil
        article = db.query_one(
            "SELECT id, title, project_path, issue_id FROM articles WHERE id = ?",
            (article_id,),
        )
        if not article:
            abort(404)
        # Filesystem cleanup first (so if it fails, the DB row remains
        # as a pointer for retry). Use missing_ok semantics: if the dir
        # is already gone, that's fine.
        apath = Path(article["project_path"])
        try:
            if apath.exists() and apath.is_dir():
                shutil.rmtree(apath)
        except Exception as exc:
            flash(f"Filesystem cleanup failed: {exc}", "error")
            return redirect(url_for("dashboard"))
        # Cascade-clean DB references. Foreign keys may already CASCADE
        # for conversions etc., but be defensive about anything that
        # references this article id.
        db.execute("DELETE FROM conversions WHERE article_id = ?", (article_id,))
        db.execute("DELETE FROM articles WHERE id = ?", (article_id,))
        flash(f"Deleted {article['title']!r}.", "success")
        # Redirect back to wherever the user was — if the article had an
        # issue, the issue page is the natural landing spot; otherwise
        # the dashboard.
        if article["issue_id"]:
            return redirect(url_for("issue_home", issue_id=article["issue_id"]))
        return redirect(url_for("dashboard"))

    @app.route("/articles/<int:article_id>/upload-missing-assets", methods=["POST"])
    @login_required
    def article_upload_missing_assets(article_id):
        """Upload one or more asset files for an article whose Markdown
        references images that aren't on disk. Each uploaded file is
        placed at the path the Markdown expects — i.e., if the article
        references `assets/media/foo.png`, the upload form names that
        file as the target and we write it there exactly.

        Also auto-detects extension mismatches: if the uploaded file's
        actual format doesn't match the target extension (e.g., a JPEG
        renamed to .png — common when Pandoc extracts media from DOCX
        and uses content hashes for filenames), the file is saved at
        the corrected extension AND article.md is rewritten to point
        at the corrected reference. Without this, Typst would fail
        with 'Invalid PNG signature' on perfectly valid JPEG content.

        This solves the .md-upload case where the editor brought in a
        Markdown file with image references but didn't bring the
        images themselves.
        """
        article = db.query_one("SELECT project_path FROM articles WHERE id = ?", (article_id,))
        if not article:
            abort(404)
        apath = Path(article["project_path"])
        md_path = apath / "article.md"
        md_text = md_path.read_text(encoding="utf-8") if md_path.exists() else ""

        # Magic-byte -> canonical extension map.
        def detect_ext(head: bytes) -> Optional[str]:
            if head.startswith(b"\x89PNG\r\n\x1a\n"):
                return ".png"
            if head[:3] == b"\xff\xd8\xff":
                return ".jpg"
            if head[:6] in (b"GIF87a", b"GIF89a"):
                return ".gif"
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                return ".webp"
            if head[:4] == b"%PDF":
                return ".pdf"
            if head[:2] == b"BM":
                return ".bmp"
            if head[:4] in (b"II*\x00", b"MM\x00*"):
                return ".tif"
            if head[:5] == b"<?xml" or head[:4] == b"<svg":
                return ".svg"
            return None

        n_saved = 0
        n_renamed = 0
        for key, fileobj in request.files.items(multi=True):
            if not fileobj or not fileobj.filename:
                continue
            # `key` carries the target path the markdown expects.
            target_rel = key.strip("/").strip("\\")
            target = (apath / target_rel).resolve()
            try:
                target.relative_to(apath.resolve())
            except ValueError:
                flash(f"Refused upload of {target_rel!r}: path escapes article directory.", "error")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            fileobj.save(target)
            n_saved += 1

            # Sniff the first 16 bytes to confirm the extension matches
            # the file's actual format. If not, rename + rewrite MD.
            head = target.read_bytes()[:16]
            actual_ext = detect_ext(head)
            current_ext = target.suffix.lower()
            if actual_ext and actual_ext != current_ext:
                # Special-case: .jpeg vs .jpg are the same content.
                if not (actual_ext == ".jpg" and current_ext in (".jpg", ".jpeg")):
                    new_target = target.with_suffix(actual_ext)
                    target.rename(new_target)
                    # Rewrite the markdown reference from old ext to new.
                    new_rel = (Path(target_rel).with_suffix(actual_ext)).as_posix()
                    md_text = md_text.replace(target_rel, new_rel)
                    n_renamed += 1
                    flash(
                        f"Detected format mismatch on {target_rel!r}: "
                        f"file is actually {actual_ext[1:].upper()}, not "
                        f"{current_ext[1:].upper() if current_ext else 'unknown'}. "
                        f"Saved as {new_rel} and updated article.md.",
                        "warning",
                    )

        if n_renamed and md_path.exists():
            md_path.write_text(md_text, encoding="utf-8")
        if n_saved:
            flash(f"Saved {n_saved} asset file(s). Re-render to use them.", "success")
        else:
            flash("No files uploaded.", "warning")
        return redirect(url_for("article_home", article_id=article_id))

    @app.route("/articles/<int:article_id>/upload-asset", methods=["POST"])
    @login_required
    def article_upload_asset(article_id):
        """Upload an image (or other asset) to the article's assets/
        directory and return JSON with a relative path the editor can
        insert as Markdown. Used by both the WYSIWYG and Markdown editor
        toolbars."""
        from flask import jsonify
        article = db.query_one(
            "SELECT * FROM articles WHERE id = ?", (article_id,),
        )
        if not article:
            return jsonify({"ok": False, "error": "Article not found."}), 404
        f = request.files.get("asset")
        if not f or not f.filename:
            return jsonify({"ok": False, "error": "No file uploaded."}), 400
        # Accept the common image types Pandoc/Typst can embed.
        allowed = {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".pdf", ".tiff", ".tif"}
        ext = Path(f.filename).suffix.lower()
        if ext not in allowed:
            return jsonify({
                "ok": False,
                "error": f"Unsupported asset type '{ext}'. Allowed: {', '.join(sorted(allowed))}.",
            }), 400
        assets_dir = Path(article["project_path"]) / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        fname = secure_filename(f.filename) or f"asset{ext}"
        # If the name collides, suffix -1, -2, etc., so we never silently
        # overwrite a previous upload.
        target = assets_dir / fname
        if target.exists():
            stem = target.stem
            n = 1
            while True:
                candidate = assets_dir / f"{stem}-{n}{ext}"
                if not candidate.exists():
                    target = candidate
                    break
                n += 1
        f.save(target)
        rel = f"assets/{target.name}"
        # Default alt text is just the stem with hyphens turned to spaces;
        # editor can refine it after insert.
        alt = target.stem.replace("-", " ").replace("_", " ")
        return jsonify({
            "ok": True,
            "filename": target.name,
            "path": rel,
            "markdown": f"![{alt}]({rel})",
            "bytes": target.stat().st_size,
        })

    @app.route("/articles/<int:article_id>/lint")
    @login_required
    def article_lint(article_id):
        article = db.query_one(
            "SELECT a.*, j.slug AS journal_slug, j.name AS journal_name "
            "FROM articles a JOIN journals j ON a.journal_id = j.id WHERE a.id = ?",
            (article_id,),
        )
        if not article:
            abort(404)
        content_hash = register.hash_for(article["project_path"], "lint")
        results = lint.run(dict(article))
        register.record_lint(article_id, article["project_path"], results,
                             content_hash=content_hash)
        counts = {
            "fail": sum(1 for r in results if r.level == "fail"),
            "warn": sum(1 for r in results if r.level == "warn"),
            "pass": sum(1 for r in results if r.level == "pass"),
        }
        return render_template(
            "lint.html",
            article=article,
            results=results,
            counts=counts,
        )

    # ---------- accessibility register ----------

    # Every standing is read by hashing the file on disk, which is what tells
    # a recorded pass from a current one. Measured over the Writing Spaces
    # archive that is 348 files and 61 MB for 118 articles: 0.5s of hashing
    # and 0.8s of lookups, four to an article. The page is a deliberate
    # "where do we stand" view rather than something loaded in a loop, so it
    # is read fresh rather than cached; a cache keyed on mtime would be the
    # weak evidence the register exists to replace. The half worth attacking
    # first is the lookups, which could be one query a journal.

    @app.route("/journals/<slug>/ingest", methods=["GET", "POST"])
    @login_required
    def journal_ingest_batch(slug):
        """Take a folder of chapter PDFs in, as a job rather than a request.

        `ingest_volume.py` has done this from a terminal since the archive
        was first taken in, and that is where it had to stay: a chapter is
        minutes of pdfplumber, so twenty-five of them is most of an
        afternoon and no request survives it. The upload is staged, a job
        is queued, and the page says where to watch it.

        Everything about what each file is, which of them is the collected
        volume, what repeats across the batch and is therefore the series'
        own mark, and how a chapter becomes an article is
        `ingest_volume`'s. This route decides nothing about any of it.
        """
        journal = db.query_one("SELECT * FROM journals WHERE slug = ?",
                               (slug,))
        if not journal:
            abort(404)
        shape = {"max_files": MAX_INGEST_FILES,
                 "max_mb": MAX_BATCH_BYTES // (1024 * 1024)}
        if request.method == "GET":
            return render_template("ingest_batch.html", journal=journal,
                                   shape=shape,
                                   running=jobs.recent(
                                       limit=8, journal_id=journal["id"]))

        uploads = [f for f in request.files.getlist("pdfs")
                   if f and f.filename
                   and Path(f.filename).suffix.lower() == ".pdf"]
        if not uploads:
            flash("No PDFs uploaded; this takes a folder of chapter PDFs.",
                  "error")
            return redirect(request.url)
        if len(uploads) > MAX_INGEST_FILES:
            flash(f"{len(uploads)} files is past the limit of "
                  f"{MAX_INGEST_FILES} for one batch.", "error")
            return redirect(request.url)

        def number(field_name):
            raw = (request.form.get(field_name) or "").strip()
            try:
                return int(raw)
            except ValueError:
                return None

        keep_own_license = request.form.get("keep_license") == "on"
        facts = {
            "volume": number("volume"),
            "year": number("year"),
            "volume_title": (request.form.get("volume_title") or "").strip(),
            "replace": request.form.get("replace") == "on",
            "teacher_mode": ("inline"
                             if request.form.get("teacher_mode") == "inline"
                             else "separate"),
        }
        if not keep_own_license:
            facts["license"] = (request.form.get("license") or "").strip()
            facts["license_url"] = (request.form.get("license_url")
                                    or "").strip()

        label = f"{len(uploads)} chapter(s) into {journal['name']}"
        job_id = jobs.create("ingest_batch", label, facts, journal["id"])
        staged = jobs.staging_dir(job_id)
        try:
            for upload in uploads:
                name = secure_filename(upload.filename) or "chapter.pdf"
                if not name.lower().endswith(".pdf"):
                    name = f"{name}.pdf"
                dest = staged / name
                # `ingest_volume.plan` reads a chapter's number and author
                # off its filename, so two files of one name are two
                # different chapters and the second must not land on the
                # first.
                serial = 1
                while dest.exists():
                    dest = staged / (f"{Path(name).stem}-{serial}"
                                     f"{Path(name).suffix}")
                    serial += 1
                upload.save(dest)
        except Exception as exc:
            jobs.abandon(job_id, f"Staging failed: {type(exc).__name__}: {exc}")
            flash(f"The upload could not be staged: {exc}", "error")
            return redirect(request.url)

        # Released only once every file is on disk. Queuing first is the
        # obvious order and it is a race: the worker claims immediately.
        jobs.release(job_id, total=len(uploads))
        flash(f"Queued {len(uploads)} chapter(s). This runs in the "
              f"background; nothing is lost if you close the page.",
              "success")
        return redirect(url_for("job_detail", job_id=job_id))

    @app.route("/remediate", methods=["GET", "POST"])
    @login_required
    def remediate_upload():
        """Take a course cartridge in and hand a remediated one back.

        Report-only on the course itself: nothing is reworded, and every
        changed page and PDF is proved unchanged in its text before it is
        delivered. The cartridge is screened for student work first and
        refused if it carries any, so what reaches the job is only ever a
        course design. The work is a job because a cartridge with its media
        is hundreds of megabytes and minutes of reading.
        """
        import ocr as ocr_module
        import ocrlayer

        shape = {"max_mb": MAX_CARTRIDGE_BYTES // (1024 * 1024),
                 # Asked at request time, so the form greys the option out
                 # where Tesseract is absent, which is production today.
                 "ocr_ready": ocr_module.available(),
                 "ocr_languages": sorted(
                     code for code, name in ocrlayer.LANGUAGES.items()
                     if name in ocrlayer.installed_languages())}
        if request.method == "GET":
            return render_template("remediate.html", shape=shape)

        upload = request.files.get("cartridge")
        if not upload or not upload.filename:
            flash("No cartridge uploaded.", "error")
            return redirect(url_for("remediate_upload"))
        if Path(upload.filename).suffix.lower() != ".imscc":
            flash("This takes a Common Cartridge, which ends in .imscc.",
                  "error")
            return redirect(url_for("remediate_upload"))

        language = (request.form.get("language") or "").strip()
        if language and not re.fullmatch(r"[A-Za-z]{2,3}(-[A-Za-z0-9]{2,8})*",
                                         language):
            flash("A language is a code such as en, es or fr-CA.", "error")
            return redirect(url_for("remediate_upload"))

        want_ocr = request.form.get("ocr") == "on"
        if want_ocr:
            # Refused at the door rather than queued and left to fail an hour
            # later: each of these is known now, and a long job that cannot
            # do what was asked is the worst place to find out.
            if not shape["ocr_ready"]:
                flash("Tesseract is not installed on this server, so scanned "
                      "pages cannot be read. Untick that option, or run this "
                      "somewhere it is.", "error")
                return redirect(url_for("remediate_upload"))
            if not language:
                flash("Reading scanned pages needs the course language, and "
                      "none is guessed: the wrong language model produces "
                      "confident nonsense.", "error")
                return redirect(url_for("remediate_upload"))
            if not ocrlayer.tesseract_language(language):
                flash(f"The Tesseract model for {language!r} is not "
                      f"installed here. Installed: "
                      f"{', '.join(shape['ocr_languages']) or 'none'}.",
                      "error")
                return redirect(url_for("remediate_upload"))

        name = secure_filename(upload.filename) or "course.imscc"
        job_id = jobs.create("remediate_cartridge", f"Remediate {name}",
                             {"language": language, "filename": name,
                              "ocr": want_ocr}, None)
        try:
            upload.save(jobs.staging_dir(job_id) / name)
        except Exception as exc:
            jobs.abandon(job_id, f"Staging failed: {type(exc).__name__}: {exc}")
            flash(f"The upload could not be staged: {exc}", "error")
            return redirect(url_for("remediate_upload"))
        jobs.release(job_id, total=0)
        flash("Queued. The cartridge is screened for student work first and "
              "turned away if it carries any.", "success")
        return redirect(url_for("job_detail", job_id=job_id))

    # What a remediation job leaves to download, by the name the URL uses.
    # A fixed map and never a path taken from the request, so there is no
    # way to ask for a file that is not one of these.
    RESULT_FILES = {"cartridge": ("remediated.imscc", "application/zip"),
                    "report": ("report.md", "text/markdown"),
                    "report-json": ("report.json", "application/json")}

    @app.route("/jobs/<int:job_id>/download/<which>")
    @login_required
    def job_download(job_id, which):
        entry = RESULT_FILES.get(which)
        if entry is None or jobs.get(job_id) is None:
            abort(404)
        name, mimetype = entry
        path = jobs.results_dir(job_id) / name
        if not path.is_file():
            abort(404)
        return send_file(str(path), mimetype=mimetype, as_attachment=True,
                         download_name=name)

    @app.route("/jobs/<int:job_id>/discard", methods=["POST"])
    @login_required
    def job_discard(job_id):
        if jobs.get(job_id) is None:
            abort(404)
        shutil.rmtree(jobs.results_dir(job_id), ignore_errors=True)
        flash("The remediated copy and its reports were deleted.", "success")
        return redirect(url_for("job_detail", job_id=job_id))

    @app.route("/jobs")
    @login_required
    def jobs_home():
        return render_template("jobs.html", rows=jobs.recent(limit=50),
                               state_tone=jobs.STATE_TONE,
                               terminal=jobs.TERMINAL)

    @app.route("/jobs/<int:job_id>")
    @login_required
    def job_detail(job_id):
        job = jobs.get(job_id)
        if job is None:
            abort(404)
        journal = None
        if job["journal_id"]:
            journal = db.query_one("SELECT slug, name FROM journals "
                                   "WHERE id = ?", (job["journal_id"],))
        return render_template("job.html", job=job, journal=journal,
                               items=jobs.items(job),
                               facts=jobs.payload(job),
                               words=jobs.words(job["kind"]),
                               downloads=[
                                   (key, name) for key, (name, _m)
                                   in RESULT_FILES.items()
                                   if (jobs.results_dir(job_id) / name).is_file()],
                               state_tone=jobs.STATE_TONE,
                               item_tone=jobs.ITEM_TONE,
                               terminal=jobs.TERMINAL)

    @app.route("/jobs/<int:job_id>/state")
    @login_required
    def job_state(job_id):
        """What the job page polls, so it can update without reloading.

        A `<meta http-equiv="refresh">` would have been fewer lines and is
        the wrong thing in this app of all apps: it reloads under the
        reader, moves focus back to the top and cannot be turned off, which
        is WCAG 2.2.1. This hands back the counts and the page writes them
        into the text it already has.
        """
        job = jobs.get(job_id)
        if job is None:
            abort(404)
        return jsonify({
            "state": job["state"],
            "done": job["done"],
            "total": job["total"],
            "finished": job["state"] in jobs.TERMINAL,
            "items": jobs.items(job),
            "error": job["error"],
        })

    @app.route("/jobs/<int:job_id>/cancel", methods=["POST"])
    @login_required
    def job_cancel(job_id):
        job = jobs.get(job_id)
        if job is None:
            abort(404)
        if jobs.cancel(job_id):
            flash("Asked the job to stop. A chapter already being read "
                  "finishes first; nothing after it is started.", "success")
        else:
            flash("That job has already finished.", "error")
        return redirect(url_for("job_detail", job_id=job_id))

    @app.route("/assess", methods=["GET", "POST"])
    @login_required
    def assess_archive():
        """Read a batch of PDFs and report what remediating them would take.

        The front door for an archive Graphion does not hold. Every other
        accessibility page here reads an article the app already owns,
        filed under a journal and an issue, so the question a journal asks
        first, which is what remediating its back catalogue would cost,
        could not be answered without first committing to the archive.
        `assess.py` was written to answer it and had no way in from a
        browser; this is that way in and nothing more.

        Nothing is ingested. No article directory is made, no database row
        is written, and the uploads land in a temporary directory that
        goes away with the request, so a stranger's PDFs do not
        accumulate on the server either. `assess.py` writes nothing by
        contract and this route is the same promise one level up.
        """
        # Imported here rather than at the top, the way `register` imports
        # it and the way every other caller of `validators` in this file
        # does: `assess` pulls pdfplumber in behind it, and one route is
        # not a reason to put that in the server's start-up.
        import assess
        import validators

        validate_ready = validators.verapdf_available()
        shape = {
            "max_files": MAX_ASSESS_FILES,
            "max_validate_files": MAX_ASSESS_VALIDATE_FILES,
            "max_mb": MAX_BATCH_BYTES // (1024 * 1024),
            "validate_ready": validate_ready,
        }
        if request.method == "GET":
            return render_template("assess.html", shape=shape)

        uploads = [f for f in request.files.getlist("pdfs")
                   if f and f.filename]
        if not uploads:
            flash("No files uploaded.", "error")
            return redirect(url_for("assess_archive"))

        deep = request.form.get("deep") == "on"
        validate = request.form.get("validate") == "on" and validate_ready
        # A verdict costs about thirteen seconds a file against about two
        # for a reading, so asking for one lowers how many files a single
        # pass will take.
        cap = MAX_ASSESS_VALIDATE_FILES if validate else MAX_ASSESS_FILES

        def is_pdf(upload) -> bool:
            return Path(upload.filename).suffix.lower() == ".pdf"

        pdfs = [f for f in uploads if is_pdf(f)]
        skipped = [f.filename for f in uploads if not is_pdf(f)]
        over = [f.filename for f in pdfs[cap:]]
        pdfs = pdfs[:cap]

        if not pdfs:
            flash("This page reads PDFs; none of those is one.", "error")
            return redirect(url_for("assess_archive"))
        if skipped:
            flash(f"{len(skipped)} file(s) were not PDFs and were left out: "
                  f"{', '.join(skipped[:6])}.", "error")
        if over:
            flash(f"{len(over)} file(s) past the limit of {cap} for this pass "
                  f"were left out. A whole archive at once is the command "
                  f"line: python assess.py <folder>.", "error")

        with tempfile.TemporaryDirectory(prefix="graphion-assess-") as tmp:
            staged = []
            for upload in pdfs:
                name = secure_filename(upload.filename) or "upload.pdf"
                if not name.lower().endswith(".pdf"):
                    # `secure_filename` can strip a name down to nothing
                    # recognisable; a reported file with no name at all is
                    # worse than a placeholder.
                    name = f"{name or 'upload'}.pdf"
                dest = Path(tmp) / name
                # A batch can carry two files of one name from different
                # folders. Without this the second overwrites the first and
                # the same bytes are reported twice under one heading.
                serial = 1
                while dest.exists():
                    dest = Path(tmp) / (f"{Path(name).stem}-{serial}"
                                        f"{Path(name).suffix}")
                    serial += 1
                upload.save(dest)
                staged.append(dest)
            # Inside the context manager, because reading is the only thing
            # that needs the files; everything below is already data.
            assessments = [assess.assess_pdf(path, deep=deep,
                                             validate=validate)
                           for path in staged]

        return render_template(
            "assess.html",
            shape=shape,
            assessments=assessments,
            rollup=assess.rollup(assessments),
            deep=deep,
            validate=validate,
        )

    @app.route("/accessibility")
    @login_required
    def accessibility_home():
        journals = db.query_all("SELECT * FROM journals ORDER BY name")
        summaries = []
        for j in journals:
            articles = db.query_all(
                "SELECT id, project_path FROM articles WHERE journal_id = ?",
                (j["id"],),
            )
            summaries.append({
                "journal": j,
                "rollup": register.rollup([dict(a) for a in articles]),
            })
        return render_template(
            "accessibility.html",
            summaries=summaries,
            kinds=register.KINDS,
            kind_labels=register.KIND_LABELS,
        )

    @app.route("/accessibility/<slug>")
    @login_required
    def accessibility_journal(slug):
        journal = db.query_one("SELECT * FROM journals WHERE slug = ?", (slug,))
        if not journal:
            abort(404)
        articles = db.query_all(
            "SELECT a.*, i.volume, i.issue_number, i.year, i.title AS issue_title "
            "FROM articles a LEFT JOIN issues i ON a.issue_id = i.id "
            "WHERE a.journal_id = ? "
            "ORDER BY i.year, i.volume, i.issue_number, a.order_in_issue, a.slug",
            (journal["id"],),
        )
        roll = register.rollup([dict(a) for a in articles])
        # Grouped for reading, in the order the query returned, so an issue
        # stays in volume order and the unassigned drafts fall at the end.
        # Each group carries its issue id, which is what gives the heading
        # somewhere to link to.
        groups = []
        for row in roll.rows:
            a = row["article"]
            label = _issue_label(a)
            if not groups or groups[-1]["label"] != label:
                groups.append({"label": label, "rows": [],
                               "issue_id": a.get("issue_id")})
            groups[-1]["rows"].append(row)
        return render_template(
            "accessibility_journal.html",
            journal=journal,
            rollup=roll,
            groups=groups,
            kinds=register.KINDS,
            kind_labels=register.KIND_LABELS,
            # Which external checkers are reachable, so the page can grey
            # out what it cannot run rather than offering it and failing.
            tools=_validator_tools(),
            validating=[job for job in jobs.recent(
                limit=5, journal_id=journal["id"])
                if job["kind"] == "validate"],
        )

    @app.route("/accessibility/<slug>/validate", methods=["POST"])
    @login_required
    def accessibility_validate(slug):
        """Queue verapdf, pa11y and epubcheck over a whole journal.

        Each is a subprocess with a 120 second timeout, so a pass over 118
        articles is an hour at best and a day at worst. That is why
        `validate_galleys.py` is a script and why the corpus route beside
        this one runs only the two in-process checks; now that there is a
        job runner, the pass has somewhere to go.
        """
        journal = db.query_one("SELECT * FROM journals WHERE slug = ?",
                               (slug,))
        if not journal:
            abort(404)

        import validate_galleys
        asked = [k for k in request.form.getlist("kinds")
                 if k in validate_galleys.TOOLS]
        if not asked:
            flash("Pick at least one checker to run.", "error")
            return redirect(url_for("accessibility_journal", slug=slug))

        facts = {"kinds": asked,
                 "skip_current": request.form.get("skip_current") == "on"}
        label = f"{', '.join(asked)} over {journal['name']}"
        # Nothing to stage: a validate pass reads galleys that are already
        # in content/.
        job_id = jobs.create("validate", label, facts, journal["id"],
                             stage=False)
        jobs.release(job_id)
        flash("Queued. Each checker is a subprocess with a two minute "
              "timeout, so a whole journal takes a while; the job page "
              "fills in as it goes.", "success")
        return redirect(url_for("job_detail", job_id=job_id))

    @app.route("/accessibility/<slug>/issues/<int:issue_id>")
    @login_required
    def accessibility_issue(slug, issue_id):
        """One issue, which is the unit an editor actually works in.

        It was a heading on the journal page and nothing else, so there was
        no address to hand anybody: "volume 2 stands here" could only be
        said by sending them the whole journal and telling them where to
        scroll.
        """
        journal = db.query_one("SELECT * FROM journals WHERE slug = ?", (slug,))
        if not journal:
            abort(404)
        issue = db.query_one(
            "SELECT * FROM issues WHERE id = ? AND journal_id = ?",
            (issue_id, journal["id"]),
        )
        if not issue:
            abort(404)
        articles = db.query_all(
            "SELECT a.*, i.volume, i.issue_number, i.year "
            "FROM articles a LEFT JOIN issues i ON a.issue_id = i.id "
            "WHERE a.issue_id = ? ORDER BY a.order_in_issue, a.slug",
            (issue_id,),
        )
        return render_template(
            "accessibility_issue.html",
            journal=journal,
            issue=issue,
            label=_issue_label(dict(issue), from_issue=True),
            rollup=register.rollup([dict(a) for a in articles]),
            kinds=register.KINDS,
            kind_labels=register.KIND_LABELS,
        )

    @app.route("/accessibility/<slug>/acr")
    @login_required
    def accessibility_acr(slug):
        """The conformance report, derived rather than typed.

        An ACR written by hand is a snapshot of somebody's belief on the
        afternoon they wrote it. Generated here it cannot say anything the
        checks did not find, and it goes stale visibly: a run taken against
        content that has since changed stops counting, so the coverage line
        drops rather than the levels quietly staying good.
        """
        journal = db.query_one("SELECT * FROM journals WHERE slug = ?", (slug,))
        if not journal:
            abort(404)
        articles = db.query_all(
            "SELECT id, project_path FROM articles WHERE journal_id = ?",
            (journal["id"],),
        )
        report = acr.report(
            journal["name"], [dict(a) for a in articles],
            template_dir=conversion.template_dir(slug),
        )
        return render_template("acr.html", journal=journal, report=report)

    # ---------- the description queue ----------

    # 201 of the Writing Spaces archive's 203 descriptions were written by
    # hand in a text editor, because the page meant for the job could not see
    # the figures: `article_figures` matches a standalone image paragraph, and
    # a reconstructed figure carries a hard line break into its caption, so 38
    # of the 51 articles that hold figures showed an empty page. These routes
    # are that work with the image on the screen and the count in front of it.

    def _describe_queue(journal):
        """This journal's figures, in the order the register lists them.

        One ORDER BY, shared with `accessibility_journal`, so the queue walks
        the archive in the order its standings are read and "7 of 22" on one
        page means the same figures as on the other.

        Rebuilt on every request rather than carried in the session. The file
        on disk is the only thing that knows what is still owed, and an editor
        may well have `article.md` open in another window; over 118 articles
        and 203 figures the build is half a second, which is the same trade
        the standings already make by hashing rather than caching.
        """
        rows = db.query_all(
            "SELECT a.*, i.volume, i.issue_number, i.year, i.title AS issue_title "
            "FROM articles a LEFT JOIN issues i ON a.issue_id = i.id "
            "WHERE a.journal_id = ? "
            "ORDER BY i.year, i.volume, i.issue_number, a.order_in_issue, a.slug",
            (journal["id"],),
        )
        articles = []
        for row in rows:
            article = dict(row)
            article["issue_label"] = _issue_label(article)
            articles.append(article)
        return describe.build(articles)

    @app.route("/accessibility/<slug>/describe")
    @login_required
    def describe_queue(slug):
        """Where the descriptions stand, volume by volume, and where to start."""
        journal = db.query_one("SELECT * FROM journals WHERE slug = ?", (slug,))
        if not journal:
            abort(404)
        queue = _describe_queue(journal)
        return render_template(
            "describe_queue.html", journal=journal, queue=queue,
            totals=queue.totals(),
        )

    @app.route("/accessibility/<slug>/describe/next")
    @login_required
    def describe_next(slug):
        journal = db.query_one("SELECT * FROM journals WHERE slug = ?", (slug,))
        if not journal:
            abort(404)
        figure = _describe_queue(journal).next_owed()
        if figure is None:
            flash("Every figure in this journal carries a description.", "success")
            return redirect(url_for("describe_queue", slug=slug))
        return redirect(url_for("describe_figure", slug=slug,
                                article_id=figure.article_id, name=figure.name))

    @app.route("/accessibility/<slug>/describe/<int:article_id>/<name>",
               methods=["GET", "POST"])
    @login_required
    def describe_figure(slug, article_id, name):
        """One figure: the image, what the page printed under it, and a field.

        A figure already described opens here too. Described is not the same
        as well described, and the 201 that were written by hand are the ones
        most worth being able to go back to.
        """
        journal = db.query_one("SELECT * FROM journals WHERE slug = ?", (slug,))
        if not journal:
            abort(404)
        queue = _describe_queue(journal)
        figure = queue.find(article_id, name)
        if figure is None:
            abort(404)
        following = queue.next_owed(figure)

        if request.method == "POST":
            description = request.form.get("description", "").strip()
            if not description:
                flash("A description cannot be empty; an image with no alt "
                      "text costs the galley its conformance. The figure "
                      "keeps what it had.", "error")
                return redirect(url_for("describe_figure", slug=slug,
                                        article_id=article_id, name=name))
            changed = describe.write_description(
                Path(figure.project_path), name, description)
            if changed:
                flash(f"Described {name}. The version before it is in "
                      f".versions/; re-render to put it in the galleys.",
                      "success")
            else:
                flash(f"{name} already said that; nothing written.", "info")
            if request.form.get("stay"):
                return redirect(url_for("describe_figure", slug=slug,
                                        article_id=article_id, name=name))
            # `following` was read before the write, which is right: this
            # figure is the only one the write could have changed, and the
            # queue deliberately does not hand it back.
            if following is None:
                flash("That was the last figure owed a description in this "
                      "journal.", "success")
                return redirect(url_for("describe_queue", slug=slug))
            return redirect(url_for("describe_figure", slug=slug,
                                    article_id=following.article_id,
                                    name=following.name))

        group = next((g for g in queue.groups
                      if g.issue_id == figure.issue_id), None)
        return render_template(
            "describe_figure.html", journal=journal, figure=figure,
            group=group, queue=queue, following=following,
            chapter_total=sum(1 for f in queue.items
                              if f.article_id == article_id),
        )

    @app.route("/accessibility/<slug>/images-of-text/<int:article_id>",
               methods=["GET", "POST"])
    @login_required
    def images_of_text(slug, article_id):
        """Which of one chapter's figures carry text as a picture.

        The second lane, and a chapter at a time, because that is how the
        question is answerable: what separates a photograph of a document
        from a photograph of anything else is what the chapter is doing with
        it, and a technical writing volume teaching a genre by showing one is
        a chapter where the answer is most of them. Writing a description
        satisfies WCAG 1.1.1 and leaves 1.4.5 exactly where it was.

        Saving records the answer even when the answer is none. An empty list
        and a missing field are different findings, and only the first of them
        is an answer.
        """
        journal = db.query_one("SELECT * FROM journals WHERE slug = ?", (slug,))
        if not journal:
            abort(404)
        article = db.query_one(
            "SELECT * FROM articles WHERE id = ? AND journal_id = ?",
            (article_id, journal["id"]),
        )
        if not article:
            abort(404)
        row = dict(article)
        pair = describe.read(row)
        if pair is None:
            flash("That article has no article.md to read.", "error")
            return redirect(url_for("describe_queue", slug=slug))
        fm, body = pair
        figures = describe.figures_in(row, fm, body)

        if request.method == "POST":
            kept = describe.record_images_of_text(
                Path(row["project_path"]), request.form.getlist("of-text"))
            if kept:
                flash(f"Recorded {len(kept)} of {len(figures)} figure(s) as "
                      f"carrying text as a picture.", "success")
            else:
                flash("Recorded that none of these figures carries text as a "
                      "picture.", "success")
            following = _describe_queue(journal).next_unjudged(article_id)
            if following is None:
                return redirect(url_for("describe_queue", slug=slug))
            return redirect(url_for("images_of_text", slug=slug,
                                    article_id=following["id"]))

        return render_template(
            "images_of_text.html", journal=journal, article=row,
            figures=figures, judged=describe.judged(fm),
        )

    @app.route("/accessibility/<slug>/run-checks", methods=["POST"])
    @login_required
    def accessibility_run_checks(slug):
        """Run the in-process checks over a whole journal and record each.

        Lint reads `article.md` and the declaration check reads the galley's
        catalog and XMP, so both are cheap enough to run in a request. The
        three external checkers are subprocesses with a 120s timeout each,
        so a corpus pass over those goes through `accessibility_validate`
        and the job runner instead.
        """
        journal = db.query_one("SELECT id, slug FROM journals WHERE slug = ?", (slug,))
        if not journal:
            abort(404)
        articles = db.query_all(
            "SELECT a.*, j.slug AS journal_slug, j.name AS journal_name "
            "FROM articles a JOIN journals j ON a.journal_id = j.id "
            "WHERE a.journal_id = ?",
            (journal["id"],),
        )
        linted = 0
        declared = 0
        no_galley = 0
        skipped = []
        for row in articles:
            article = dict(row)
            content_hash = register.hash_for(article["project_path"], "lint")
            if content_hash is None:
                skipped.append(article["slug"])
            else:
                try:
                    results = lint.run(article)
                    register.record_lint(article["id"], article["project_path"],
                                         results, content_hash=content_hash)
                    linted += 1
                except Exception as exc:
                    skipped.append(f"{article['slug']} ({type(exc).__name__})")
            # An article with no galley owes a render, which is a state the
            # register already has a name for; it is not a skip and not a
            # failure, so it is counted apart from both.
            try:
                if register.record_pdfua(article["id"], article["project_path"]):
                    declared += 1
                else:
                    no_galley += 1
            except Exception as exc:
                skipped.append(f"{article['slug']} galley ({type(exc).__name__})")
        msg = (f"Linted {linted} article(s) and read {declared} galley "
               f"declaration(s).")
        if no_galley:
            msg += f" {no_galley} have no article.pdf rendered yet."
        if skipped:
            msg += (f" {len(skipped)} could not be read: "
                    f"{', '.join(skipped[:10])}")
        flash(msg, "warning" if skipped else "success")
        return redirect(url_for("accessibility_journal", slug=slug))

    # ---------- help / docs ----------

    HELP_TOPICS = [
        # First entry is what /help lands on with no slug, so the quickstart is
        # deliberately ahead of the overview.
        ("00-quickstart", "Quickstart"),
        ("01-overview", "Overview"),
        ("02-workflow", "Workflow"),
        ("03-articles", "Articles"),
        ("04-issues-and-front-matter", "Issues & Front Matter"),
        ("05-citations", "Citations & Bibliography"),
        ("06-figures", "Figures"),
        ("07-output-formats", "Output Formats"),
        ("08-templates", "Templates & Customization"),
        ("09-crossref", "CrossRef Deposit"),
        ("10-troubleshooting", "Troubleshooting & FAQ"),
        ("11-developers", "For Developers"),
        ("12-installation", "Installation"),
        ("13-customization", "Adding a new journal"),
        ("14-advanced-tools", "Advanced Tools"),
    ]

    @app.route("/help")
    @app.route("/help/<slug>")
    @login_required
    def help_page(slug=None):
        from pathlib import Path as _Path
        import mistune

        if slug is None:
            slug = HELP_TOPICS[0][0]
        valid = {s for s, _ in HELP_TOPICS}
        if slug not in valid:
            # The pages cross-link by bare name ("workflow"), while the sidebar
            # uses the numbered slug ("02-workflow"). Accept either and redirect
            # to the canonical one, so a doc can link a sibling without knowing
            # its ordering prefix.
            unprefixed = {s.split("-", 1)[1]: s for s, _ in HELP_TOPICS}
            if slug in unprefixed:
                return redirect(url_for("help_page", slug=unprefixed[slug]))
            abort(404)

        docs_dir = _Path(__file__).parent / "docs" / "help"
        md_path = docs_dir / f"{slug}.md"
        if not md_path.exists():
            abort(404)
        text = md_path.read_text(encoding="utf-8")
        html = mistune.html(text)

        # Title of the current page
        current_title = next((t for s, t in HELP_TOPICS if s == slug), "Help")

        return render_template(
            "help.html",
            topics=HELP_TOPICS,
            current_slug=slug,
            current_title=current_title,
            html=html,
        )

    # ---------- bib builder ----------

    @app.route("/bib-builder", methods=["GET", "POST"])
    @login_required
    def bib_builder_page():
        """Heuristic prose → BibTeX tool. GET renders the form; POST takes
        the pasted prose + style choice and returns the generated BibTeX
        in the same page so the user can review, copy, and download."""
        import bib_builder
        prose = ""
        style = "mla"
        bibtex = ""
        entry_count = 0
        if request.method == "POST":
            prose = request.form.get("prose", "")
            style = request.form.get("style", "mla")
            if prose.strip():
                entries = bib_builder.parse_entries(prose, style=style)
                bibtex = bib_builder.to_bibtex(entries)
                entry_count = len(entries)
        return render_template(
            "bib_builder.html",
            prose=prose,
            style=style,
            bibtex=bibtex,
            entry_count=entry_count,
        )

    @app.route("/bib-builder/download", methods=["POST"])
    @login_required
    def bib_builder_download():
        import bib_builder
        from flask import Response
        prose = request.form.get("prose", "")
        style = request.form.get("style", "mla")
        if not prose.strip():
            flash("Paste a Works Cited list first.", "error")
            return redirect(url_for("bib_builder_page"))
        entries = bib_builder.parse_entries(prose, style=style)
        bibtex = bib_builder.to_bibtex(entries)
        return Response(
            bibtex,
            mimetype="application/x-bibtex",
            headers={"Content-Disposition": 'attachment; filename="references.bib"'},
        )

    @app.route("/healthz")
    def healthz():
        return {"ok": True}


def _journal_of_article(article_id: int):
    return db.query_one(
        "SELECT j.* FROM journals j JOIN articles a ON a.journal_id = j.id "
        "WHERE a.id = ?", (article_id,))


def _journal_of_issue(issue_id: int):
    return db.query_one(
        "SELECT j.* FROM journals j JOIN issues i ON i.journal_id = j.id "
        "WHERE i.id = ?", (issue_id,))


def _refuse_deposit_for_a_collection(journal) -> None:
    """A collection is not deposited, and that is not a cosmetic rule.

    A CrossRef deposit asserts that these DOIs are yours under your
    prefix, and an OJS push puts the content into your own journal's
    workflow. Doing either for an archive somebody sent you to assess is a
    claim about ownership rather than a convenience, and it is the kind of
    claim that is hard to take back once a registry has it.

    The pages do not offer these for a collection either. This is what
    stops a bookmark, a guessed URL or a stale tab, which is where a rule
    only enforced in a template gets through.
    """
    import new_journal

    if journal is not None and new_journal.is_collection(journal):
        abort(404, description=(
            f"{journal['name']} is a collection rather than a journal, so "
            f"it is not deposited. A CrossRef deposit says these DOIs are "
            f"yours under your prefix and an OJS push puts the content "
            f"into your own workflow; neither is offered for an archive "
            f"taken in to be remediated."))


def _validator_tools() -> list:
    """Which external checkers are reachable, asked when it matters.

    The probes live in `validators` and the labels and install lines in
    `validate_galleys`, so this assembles rather than deciding: a page
    keeping its own list would offer a tool the pass then drops, which is
    the one thing a greyed-out control exists to prevent.
    """
    import validate_galleys

    return [{"kind": kind,
             "label": tool["label"],
             "ready": bool(tool["available"]()),
             "install": tool["install"],
             "reads": tool["reads"]}
            for kind, tool in validate_galleys.TOOLS.items()]


def _issue_label(row: dict, from_issue: bool = False) -> str:
    """How an issue is named on the register pages.

    One function, because the journal page groups its headings by this
    string and the issue page titles itself with it. Two copies would
    drift, and the first thing a reader would notice is a heading that
    does not match the page it links to.
    """
    if row.get("volume") is None:
        return (row.get("title") or "Untitled issue") if from_issue             else "Not in an issue"
    label = f"Volume {row['volume']}, number {row['issue_number']}"
    if row.get("year"):
        label += f" ({row['year']})"
    return label


def _peek_title(md_path: Path) -> Optional[str]:
    if not md_path.exists():
        return None
    text = md_path.read_text(encoding="utf-8")
    m = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def _serve_artifact(article_id: int, name: str, as_attachment: bool = False):
    article = db.query_one("SELECT project_path, slug FROM articles WHERE id = ?", (article_id,))
    if not article:
        abort(404)
    apath = Path(article["project_path"])
    target = apath / name
    if not target.exists():
        abort(404)
    download_name = None
    if as_attachment and "." in name:
        ext = name.rsplit(".", 1)[1]
        download_name = f"{article['slug']}.{ext}"
    return send_from_directory(
        apath, name,
        as_attachment=as_attachment,
        download_name=download_name,
    )


if __name__ == "__main__":
    import os

    app = create_app()
    port = int(os.environ.get("PORT", "5050"))
    host = os.environ.get("GRAPHION_HOST", "127.0.0.1")

    # Flask's debugger exposes an interactive Python console on any traceback,
    # so it is only ever safe on loopback. Binding anywhere else turns it off
    # unless it is explicitly forced back on.
    loopback = host in {"127.0.0.1", "localhost", "::1"}
    debug = os.environ.get("GRAPHION_DEBUG", "1" if loopback else "0") == "1"

    app.run(host=host, port=port, debug=debug)
