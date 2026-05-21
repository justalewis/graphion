# Issues & front matter

An issue is an assembly of articles plus the journal's standing front matter (cover, masthead, mission, editors' introduction, ToC).

## Creating an issue

From a journal page, click **New issue**. Provide:

- Volume (integer)
- Issue number (integer)
- Year
- Optional special-issue title

The tool creates a row in the `issues` table, a directory at `content/journals/<slug>/issues/v<vol>-n<iss>-<year>/`, and an `_issue.yaml` file inside that mirrors the row.

After creating, set the **header season** (e.g., `WINTER 2026`) on the issue's metadata page — it appears in the running header across front-matter pages and the cover.

## Assigning articles

From the issue detail page, an **Add an article** dropdown shows the journal's unfiled articles (those without an issue). Pick one and click "Add to issue." The tool:

1. Updates the article's `issue_id` and `order_in_issue`.
2. **Physically moves** the article directory from `_unfiled/<slug>/` to `issues/v<vol>-n<iss>-<year>/articles/<slug>/`.
3. Updates `project_path` in the DB.

Remove an article and the directory moves back to `_unfiled/`.

Articles in the issue can be reordered with the up/down arrows; their `order_in_issue` updates accordingly. The order drives both the ToC and the page-number sequence during assembly.

## Editors' introduction

Click **Create editors' introduction** to spawn a new article with `kind=editorial`. It's a regular article record (you can edit its body in CodeMirror or WYSIWYG) but the assembler treats it specially: it goes into the front matter (pages VI–VII or however many it needs), and it's *excluded* from the ToC's article list.

The intro's body is whatever Markdown you write. The assembler renders it with the same typography as the mission statement (justified paragraphs, italic signature line works well).

## Assembling

Click **Assemble issue** on the issue detail page. Sequentially, for each article in order:

1. Set `start-page` in that article's YAML.
2. Re-render the article PDF — Typst's `counter(page).update(start-page)` shifts the page counter, so the article's footer numbers begin at the assigned page.
3. Count the rendered pages.
4. Record `start_page` and `end_page` in the DB.

Then render the **front-matter PDF** in one Typst compile: cover, editorial team, editorial board + financial credit, mission statement, editors' introduction, ToC. Roman pagination across. The cover suppresses both header and footer.

Concatenate front matter + article PDFs into `issue.pdf` via pypdf.

Result: a single download (View issue PDF) that is the complete book.

## Front-matter content

Everything in the front matter is configured at one of two levels:

### Per-journal (rarely changes)

Set in **Journal Settings** (linked from the journal page). These render into every issue's front matter:

- **Short name** — used in running headers (e.g., `LiCS`)
- **Wordmark** — image upload (SVG/PNG/JPG); rendered on the cover. Falls back to a Helvetica-Bold text representation of the short name if not uploaded.
- **Header label template** — e.g., `*{short_name}* {volume}.{issue} / {season}`. Placeholders: `{short_name}`, `{name}`, `{volume}`, `{issue}`, `{year}`, `{season}`.
- **Editorial Team** — structured rows (role / name / institution). Renders as a 2-column grid, one cell per editor, with role in small caps, name in regular weight, institution in italic.
- **Editorial Board** — structured rows (name / institution). 2-column grid.
- **Financial credit** (Markdown) — appears below the editorial board.
- **Mission statement** (Markdown) — its own section.
- **ToC section labels** — one per line; articles group by section in the ToC.
- **CrossRef depositor identity** — name + email, plus DOI prefix and member ID.

### Per-issue

Set on the issue metadata page:

- **Volume, issue number, year** — what they sound like.
- **Special-issue title** — optional.
- **Header season** — e.g., `SPRING 2026`.
- **Status** — draft / in-production / published.

## Continuous pagination

The two pagination zones — roman across front matter, arabic restarting at 1 for articles — are produced by Typst's `set page(numbering: "I")` for the front-matter document and arabic numerals in each article. Because each article PDF is rendered separately and then concatenated, the page counters never collide.

The ToC pulls `start_page` from each article's DB row (populated by assembly), so it always shows the right numbers.
