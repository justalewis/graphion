"""Flask app. Phase 1 routes: dashboard, upload, edit, render, download."""
from __future__ import annotations

import re
import sqlite3
import threading
import time
from collections import defaultdict
from pathlib import Path
from typing import Optional

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request,
    send_from_directory, url_for,
)
from markupsafe import Markup
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename

import citation_styles
import conversion
import crossref
import db
import jats
import lint
from auth import User, login_manager
from config import (
    ALLOWED_UPLOAD_EXTENSIONS, CONTENT_DIR, LOGIN_MAX_ATTEMPTS,
    LOGIN_WINDOW_SECONDS, MAX_UPLOAD_BYTES, SECURE_COOKIES, SECRET_KEY,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
    app.config["SESSION_COOKIE_SECURE"] = SECURE_COOKIES

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
        return render_template("issue.html", issue=issue, articles=articles, unfiled=unfiled)

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
            flash(
                f"Assembled {result.total_pages} pages across {len(result.article_pages)} articles.",
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
            except Exception as exc:
                flash(f"Conversion failed: {exc}", "error")
                return redirect(request.url)

            title = title_hint or _peek_title(apath / "article.md") or article_slug
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
            log_text=log_text,
            rendered_html=rendered_html,
            rendered_pdf=rendered_pdf,
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

            page = request.form.get("start_page", "").strip()
            if page:
                try:
                    updated["start-page"] = int(page)
                except ValueError:
                    flash("Start page must be a number.", "error")
                    return redirect(request.url)
            else:
                updated.pop("start-page", None)

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
            new_title = updated.get("title")
            new_section = updated.get("section")
            db.execute(
                "UPDATE articles SET title = COALESCE(?, title), section = COALESCE(?, section), "
                "updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (new_title, new_section, article_id),
            )

            render_result = conversion.render_all(apath, article["journal_slug"])
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
            flash("No verapdf report yet — run Validate PDF/UA first.", "error")
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
            flash("No pa11y report yet — run Audit HTML accessibility first.", "error")
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

    @app.route("/articles/<int:article_id>/pdf")
    @login_required
    def serve_pdf(article_id):
        return _serve_artifact(
            article_id, "article.pdf",
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
        target = apath / "article.epub"
        if not target.exists():
            try:
                conversion.render_epub(apath, article["journal_slug"])
            except Exception as exc:
                flash(f"EPUB render failed: {exc}", "error")
                return redirect(url_for("article_home", article_id=article_id))
        return send_from_directory(apath, "article.epub", as_attachment=True)

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
        journal_rows = db.query_all("SELECT * FROM journals ORDER BY name")
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
        passed, report = validators.run_verapdf(pdf)
        # Save the full report next to the PDF for later inspection.
        (Path(article["project_path"]) / "verapdf-report.json").write_text(
            __import__("json").dumps(report, indent=2), encoding="utf-8",
        )
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
        passed, issues = validators.run_pa11y(html)
        (Path(article["project_path"]) / "pa11y-report.json").write_text(
            __import__("json").dumps(issues, indent=2), encoding="utf-8",
        )
        view_url = url_for("serve_pa11y_report", article_id=article_id)
        if passed:
            flash(Markup(
                f"Accessibility audit clean — 0 issues found. <a href='{view_url}' target='_blank'>View report →</a>"
            ), "success")
        else:
            errors = sum(1 for i in issues if i.get("type") == "error")
            warnings_n = sum(1 for i in issues if i.get("type") == "warning")
            flash(Markup(
                f"Accessibility audit: {errors} error(s), {warnings_n} warning(s). "
                f"<a href='{view_url}' target='_blank'>View report →</a>"
            ), "warning")
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
        results = lint.run(dict(article))
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

    # ---------- help / docs ----------

    HELP_TOPICS = [
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
