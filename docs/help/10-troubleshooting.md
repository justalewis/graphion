# Troubleshooting & FAQ

Common issues and how to fix them.

## Setup & first run

**The app won't start: "module not found"**

Run `pip install -r requirements.txt` from the project root. Use Python 3.11 or newer.

**Pandoc not found / "command pandoc not found"**

Install Pandoc from <https://pandoc.org/installing.html>. On Windows it lands in `C:\Users\<user>\AppData\Local\Pandoc\`. The Flask app picks it up automatically.

**Typst rendering fails**

Pandoc and Typst are separate tools. The `typst` PyPI package bundles the Typst engine, so `pip install -r requirements.txt` covers it. If you see "Typst binary not found," your `pip` install probably failed; check the install log.

**Browser shows "address not reachable"**

The app runs on port 5050 (not 5000 — Pinakes typically owns 5000 if you also use that project). Open `http://127.0.0.1:5050/` exactly.

## Article upload

**Upload returns "Conversion failed"**

The docx might have unusual structure that Pandoc couldn't handle. Check `conversion.log` in the article directory for the actual Pandoc error. Most often: the file has a tracked-changes block Pandoc can't reconcile (try uploading with "Reject all" tracked changes).

**Title comes through wrong**

The tool looks for a Title-styled paragraph in the docx. If the author didn't apply that style, the first body line will be used (or nothing). Edit the title in the metadata form after upload — it's just text.

**Highlights show up in the rendered output**

The cleanup pipeline strips `[text]{.mark}` highlighter annotations and `[text]{.underline}` underline annotations. If you see yellow highlights remaining, run the cleanup pipeline manually:

```python
python smoketest.py
```

If it still leaks, the source docx has highlights nested in a way the regex doesn't recognize (rare). Edit `article.md` to remove them manually.

## Rendering

**PDF render: "Access is denied"**

Old issue (resolved). If you see this, you're on a pre-`63a3aba` build; pull the latest.

**HTML render: missing `article.css`**

The journal's template `article.css` is copied into the article directory at render time. If you've moved files around manually, the copy may have failed. Re-run Render.

**EPUB render fails**

Pandoc EPUB3 is generally robust. If it fails, the YAML front matter may have a non-string value where a string is expected (rare). Check article.md for malformed YAML.

**Issue assembly: "Issue has no articles to assemble"**

You haven't added any articles to the issue. From the issue page, use the **Add an article** dropdown.

**Issue assembly: a specific article fails to re-render**

The article's `start-page` gets written to its YAML. If the YAML round-trip fails (very rare with the defensive sanitization now in place), assembly stops at that article. Open the article's metadata page and re-save; that resets the YAML to canonical form.

## Metadata

**Metadata form: my changes don't appear in the rendered output**

Metadata save runs Render automatically. If the rendered output still looks old, hard-refresh your browser (Ctrl+Shift+R) — your browser cached the old version.

**Author reorder didn't stick**

The form submission order is the DOM order. If your save didn't reorder, you may have submitted before the JS reorder propagated. Save again after a half-second pause.

**ToC section field shows only "ARTICLES"**

The journal's `toc_sections_json` is empty. Set the section labels in **Journal Settings** → **Table of contents** (one section per line: ARTICLES, SYMPOSIUM, BOOK REVIEWS).

## Issues & front matter

**Cover wordmark shows "LCS" instead of "LiCS"**

The short name in **Journal Settings** is auto-derived (initials) by default. Set `short_name: LiCS` explicitly.

**Wordmark image isn't appearing**

The tool falls back to text when the image file doesn't exist at the path stored in `wordmark_image_path`. Re-upload via Journal Settings.

**Front matter shows blank pages**

Some Markdown blocks (mission statement, editorial team) might be empty. Set them in Journal Settings.

**Editor's introduction doesn't appear in front matter**

The intro is a `kind=editorial` article. From the issue page, click **Create editors' introduction** (or **Edit editors' introduction** if one exists). Once it has body content, it will be included in the next assembly.

**Page numbers in articles don't continue from front matter**

That's intentional. Front matter uses roman numerals (I–VIII); articles restart at arabic 1. This matches scholarly book convention.

## CrossRef

**"CrossRef will reject deposits with placeholder emails"**

The depositor email in Journal Settings is set to `noreply@example.org` or similar. Change it to a real email registered with your CrossRef account.

**Sample DOI looks wrong**

The DOI pattern is `{prefix}/{member}.{vol}.{iss}.{position}` by default. For a custom pattern, set the journal's `config_json.doi_pattern` — currently via a direct DB edit or `seed.py` modification (no UI yet).

**Per-article XML returns 500**

Most likely the article isn't assigned to an issue. CrossRef needs vol/iss/year to deposit a journal article. Assign the article to an issue first.

## Lint

**Lint warning: "citation-coverage"**

Heuristic check. If your article uses BibTeX-style citations, this check is mostly unreliable; ignore it. Otherwise, look at which surnames are flagged and decide whether they're real omissions or false positives.

**Lint warning: "cleanup-artifacts"**

Cleanup pipeline left a `{.mark}` or `{.underline}` span. Edit `article.md` to remove it.

## Bibliography

**BibTeX upload says "saved" but Works Cited section doesn't appear**

You also need to:
1. Remove any manual "# Works Cited" section from `article.md` (the BibTeX path generates one).
2. Use Pandoc citation syntax in the body: `[@key]` or `@key`.
3. Re-render.

**Citations render as "[?]" in the output**

The `@key` in the body doesn't match an entry in `references.bib`. Check the key spelling. Citation keys are case-sensitive.

## Editing

**WYSIWYG editor doesn't load (blank page or "loading")**

The editor imports ProseMirror modules from <https://esm.sh/>. Check your network connection. If you need offline operation, bundle ProseMirror locally (roadmap item).

**Save loses formatting**

The WYSIWYG editor serializes back to Markdown. Markdown's expressiveness is a subset of what a rich editor can produce. If you used a feature that has no Markdown equivalent (custom colors, fonts, tables with complex styling), it won't survive a save round-trip. Use the Markdown editor for those cases, or simplify your formatting.

## Filesystem

**Article appears in the dashboard but its files are missing**

The DB has the row but the directory's gone. Check `project_path` on the article row and restore the directory from git or a backup. If unrecoverable, delete the row and re-upload.

**Two articles with the same slug**

The DB has a unique constraint per (journal_id, slug), so this shouldn't happen. If you see it via direct DB edit, fix it via direct DB edit.

## Where to ask for help

- This documentation lives at `/help` in the app and as Markdown files in `docs/help/` in the repo.
- Specific feature roadmap: `docs/audit-and-roadmap.md`.
- File issues against the project's git remote if you have one.
