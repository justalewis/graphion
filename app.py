"""Flask app. Phase 1 routes: dashboard, upload, edit, render, download."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

from flask import (
    Flask, abort, flash, jsonify, redirect, render_template, request,
    send_from_directory, url_for,
)
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename

import conversion
import crossref
import db
from auth import User, login_manager
from config import (
    ALLOWED_UPLOAD_EXTENSIONS, CONTENT_DIR, MAX_UPLOAD_BYTES, SECRET_KEY,
)


def create_app() -> Flask:
    app = Flask(__name__)
    app.config["SECRET_KEY"] = SECRET_KEY
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_BYTES

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


def register_routes(app: Flask):

    # ---------- auth ----------

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("dashboard"))
        if request.method == "POST":
            user = User.by_username(request.form.get("username", ""))
            if user and user.check_password(request.form.get("password", "")):
                login_user(user, remember=True)
                return redirect(url_for("dashboard"))
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
            fields = {
                "short_name": request.form.get("short_name", "").strip() or None,
                "header_label_template": request.form.get("header_label_template", "").strip() or None,
                "depositor_name": request.form.get("depositor_name", "").strip() or None,
                "depositor_email": request.form.get("depositor_email", "").strip() or None,
                "editorial_team_md": request.form.get("editorial_team_md", "").strip() or None,
                "editorial_board_md": request.form.get("editorial_board_md", "").strip() or None,
                "mission_statement_md": request.form.get("mission_statement_md", "").strip() or None,
                "financial_credit_md": request.form.get("financial_credit_md", "").strip() or None,
                "toc_sections_json": sections_json,
                "crossref_prefix": request.form.get("crossref_prefix", "").strip() or None,
                "crossref_member_id": request.form.get("crossref_member_id", "").strip() or None,
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
        return render_template("journal_settings.html", journal=j, wordmark_url=wordmark_url)

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
            f = request.files.get("docx")
            slug_override = request.form.get("slug", "").strip()
            title_hint = request.form.get("title", "").strip()
            short_title = request.form.get("short_title", "").strip()
            short_authors = request.form.get("short_authors", "").strip()
            accept_tc = request.form.get("track_changes", "accept") == "accept"

            if not f or not f.filename:
                flash("No file uploaded.", "error")
                return redirect(request.url)
            if not short_title or not short_authors:
                flash("Short title and short authors are required for running headers.", "error")
                return redirect(request.url)

            filename = secure_filename(f.filename)
            if Path(filename).suffix.lower() not in ALLOWED_UPLOAD_EXTENSIONS:
                flash("Only .docx files are accepted.", "error")
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
                conversion.ingest_docx(staged, apath, accept_track_changes=accept_tc)
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
            article_id = db.execute(
                "INSERT INTO articles (journal_id, slug, title, project_path, status) "
                "VALUES (?, ?, ?, ?, 'draft')",
                (journal["id"], article_slug, title, str(apath)),
            )
            conversion.record_conversion(
                article_id, "docx",
                f"ingest + cleanups OK; project_path={apath}",
            )
            return redirect(url_for("article_home", article_id=article_id))

        return render_template("upload.html", journal=journal)

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
        log_path = Path(article["project_path"]) / "conversion.log"
        log_text = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
        rendered_html = (Path(article["project_path"]) / "article.html").exists()
        rendered_pdf = (Path(article["project_path"]) / "article.pdf").exists()
        return render_template(
            "article.html",
            article=article,
            log_text=log_text,
            rendered_html=rendered_html,
            rendered_pdf=rendered_pdf,
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
                "doi", "abstract", "status", "copyright",
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
            if updated.get("title") != article["title"]:
                db.execute(
                    "UPDATE articles SET title = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (updated["title"], article_id),
                )
            else:
                db.execute(
                    "UPDATE articles SET updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                    (article_id,),
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

        return render_template(
            "metadata.html",
            article=article,
            fm=fm,
            authors=authors_list,
            keywords_str=kw_string,
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

    @app.route("/articles/<int:article_id>/html")
    @login_required
    def serve_html(article_id):
        return _serve_artifact(article_id, "article.html")

    @app.route("/articles/<int:article_id>/pdf")
    @login_required
    def serve_pdf(article_id):
        return _serve_artifact(article_id, "article.pdf")

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

    # ---------- CrossRef ----------

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

    @app.route("/healthz")
    def healthz():
        return {"ok": True}


def _peek_title(md_path: Path) -> Optional[str]:
    if not md_path.exists():
        return None
    text = md_path.read_text(encoding="utf-8")
    m = re.search(r"^title:\s*[\"']?(.+?)[\"']?\s*$", text, re.MULTILINE)
    return m.group(1).strip() if m else None


def _serve_artifact(article_id: int, name: str):
    article = db.query_one("SELECT project_path FROM articles WHERE id = ?", (article_id,))
    if not article:
        abort(404)
    apath = Path(article["project_path"])
    target = apath / name
    if not target.exists():
        abort(404)
    return send_from_directory(apath, name)


if __name__ == "__main__":
    import os
    app = create_app()
    port = int(os.environ.get("PORT", "5050"))
    app.run(host="127.0.0.1", port=port, debug=True)
