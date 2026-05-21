# Graphion — Competitive Audit & Roadmap

Written 2026-05-21, after 12 commits. Compares the current tool against
peer publishing platforms and identifies concrete improvements organized
by the three angles in your ask: UI-friendliness, affordances, export
formats. Closes with a prioritized roadmap and a list of features we
should explicitly **not** build.

---

## 1. Where Graphion already does well versus peers

Compared to OJS, Janeway, Quarto, Editoria, Texture, Manuscripts.io, and
Pressbooks, Graphion already has a few distinct strengths:

| Feature | Graphion | Quarto | OJS | Janeway | Editoria | Texture |
|---|---|---|---|---|---|---|
| Single Markdown source → HTML + tagged PDF | ✓ | ✓ | ✗ | ✗ | ✓ | ✓ |
| Per-journal template bundle (CSS + Typst + Lua) | ✓ | partial | ✗ | ✗ | ✓ | partial |
| Form-based article metadata editor | ✓ | ✗ | ✓ | ✓ | partial | ✓ |
| Editor's introduction as first-class content | ✓ | ✗ | ✗ | partial | ✗ | ✗ |
| Issue assembly (front matter + articles, mixed pagination) | ✓ | ✗ | ✗ | ✗ | ✓ | ✗ |
| Built-in CrossRef deposit XML generator | ✓ | ✗ | plugin | plugin | ✗ | ✗ |
| DOI auto-assignment from journal pattern | ✓ | ✗ | ✗ | ✗ | ✗ | ✗ |
| Filesystem-self-documenting article layout | ✓ | partial | ✗ | ✗ | ✗ | ✗ |
| Drop cap, running headers, roman/arabic page split | ✓ | partial | ✗ | ✗ | ✓ | ✗ |
| Hyphenation off + book-quality typography (Typst) | ✓ | partial | ✗ | ✗ | partial | ✗ |

The combination of *Markdown source*, *Typst-rendered tagged PDF*, and
*per-journal structured editorial metadata* is uncommon. None of the
peer tools combines them in the same single-editor workstation form.

---

## 2. UI-friendliness gaps

### 2.1 The Markdown editor will frighten non-technical editors

The CodeMirror editor is fine for power users, but the user already
flagged this. Authors and copyeditors often want a richer authoring
experience. Peer tools split this two ways:

- **WYSIWYG editor with structured output** (Manuscripts.io, Texture,
  Editoria). Uses ProseMirror or similar. The author sees a rendered
  document; the system writes back to a structured backing format
  (JATS, Markdown, etc.).
- **Tracked-changes / suggestion mode** (Google Docs, OJS galley
  reviewer). Multiple editors comment and suggest; one editor accepts.

**Recommendation:** add a **ProseMirror-based WYSIWYG layer** that
serializes back to the same Markdown source. Reuses the rendering
pipeline; gives a Word-like editing experience to non-technical editors.
The Markdown view stays available for power users. Plan it as a single
new route `/articles/<id>/edit/wysiwyg` next to the existing
`/articles/<id>/edit` CodeMirror view.

### 2.2 No diff / revision view

Spec section 9 called this out (`Diff viewer`) and it isn't built. The
`.versions/` snapshots exist; we just don't render them. Compared to
Google Docs's revision history this is a major gap for editorial review.

**Recommendation:** `/articles/<id>/revisions` page that lists snapshots
with paragraph-level diff (use `difflib.unified_diff` or render side-by-
side rendered HTML for visual diff). Two days of work; high editorial
value.

### 2.3 Article home page buries the most important actions

The action row has Edit metadata / Edit Markdown / Render / View HTML /
View PDF / Download CrossRef XML in one flat strip. Compared to OJS's
clear status-driven workflow (Submission → Review → Copyedit → Layout →
Publish), Graphion doesn't show "what stage is this article in" at a
glance.

**Recommendation:** add a **status timeline** at the top of each article
page (draft → revising → final → published). Show which step is current,
with the relevant actions for that step prominent and the rest tucked
into a "more" menu. Same `status` field we already have; just better
visualization.

### 2.4 No reader-facing site

OJS, Janeway, and Pressbooks all produce a public journal site as part
of the same tool. Graphion produces files; you upload them elsewhere. For
LiCS this is fine (OJS hosts the public site). For a journal that wants
to self-host, this is missing.

**Recommendation:** out of scope for v1 since LiCS uses OJS. Note for
future: a `/public/<journal>/<issue>` reader view that renders the
rendered HTML with a journal-styled navigation chrome would be 1–2
weeks of work.

### 2.5 No assistive validation

When an editor saves metadata or renders, we don't validate anything
beyond "title and short-title are required." OJS, Texture, and Quarto
all run checks: missing alt text on figures, broken cross-references,
unbalanced quotation marks, ORCID format, DOI format, etc.

**Recommendation:** add a `/articles/<id>/lint` route (spec called this
out as the "citation linter" but it can be broader). Run a battery of
checks; show pass/warn/fail per check; let the editor proceed anyway.
Concrete checks worth shipping:

- Author ORCIDs are valid format (regex)
- DOI string conforms to journal's pattern
- Works Cited entries each have a structured author match in body text
- Cross-references resolve
- All hyperlinks are well-formed URLs
- All figure references resolve
- Footer text length isn't excessive
- Short title and short authors aren't longer than reasonable

### 2.6 The CrossRef tab is configuration-heavy; the workflow isn't obvious

Right now the CrossRef tab shows config + downloads. Compared to OJS's
CrossRef plugin which has explicit "queue this for deposit" / "marked
as deposited" / "DOI confirmed" states, Graphion has no awareness of
which deposits have actually been registered.

**Recommendation:** add a `deposits` table tracking when each article's
DOI was last submitted (manually marked or auto-marked when the user
clicks "Download XML"), and surface this status on the CrossRef tab.
Future API submission slots in naturally.

---

## 3. Affordance gaps

### 3.1 Citation handling is shallow

Right now the Works Cited section is rendered as plain prose with
hanging indent (good) and emitted as `<unstructured_citation>` to
CrossRef (acceptable but weak). Peer tools handle citations natively:

- **Quarto / Pandoc + CSL** — author maintains a `.bib` file or Zotero
  library; cites with `[@key]`; Pandoc resolves to a styled reference
  via CSL stylesheet.
- **Texture, Manuscripts** — citations are structured nodes in the
  document, with full CSL bibliographic data behind each citation.

**Recommendation (medium effort):** add a Zotero / BibTeX import for
the journal. Each article's Works Cited becomes a structured list. The
body's parenthetical citations become Pandoc citation markers. The
CrossRef XML emits proper structured citations. This is the highest
ROI affordance improvement in this list — it powers reference linking,
citation analytics, indexing eligibility, and proper CrossRef metadata
all at once.

### 3.2 Figure handling is barebones

We support inline images via Markdown. We don't:
- Number figures automatically (Fig. 1, Fig. 2, etc.)
- Generate a List of Figures
- Cross-reference figures (`See Fig. 2`)
- Validate alt text
- Manage figure files separately from prose

**Recommendation:** install `pandoc-crossref` (already noted in the spec
as planned) and define a figure metadata convention. Add a Figures tab
on the article page that lists all `assets/` images with their captions,
references in body, and alt text. Lint missing alt text.

### 3.3 No table of figures / tables / equations

Related to 3.2. Books and journal articles often have LoF / LoT. Pandoc
+ pandoc-crossref can generate these. Quarto exposes this. We don't.

**Recommendation:** when figures are first-class, also auto-generate
LoF + LoT pages between ToC and article 1 in the front matter (or as a
back-matter section, depending on journal convention).

### 3.4 No author profiles or ORCID lookup

We store author name, affiliation, ORCID. We don't:
- Validate ORCIDs against the ORCID API (verify the ORCID exists and
  matches the name)
- Pre-fill an author's affiliation from their ORCID
- Display an authors index across all journals' articles

**Recommendation:** "validate ORCID" button next to each author input
that hits `https://pub.orcid.org/v3.0/<id>/person` and confirms the name
matches. Cheap UX win, prevents typos.

### 3.5 No DOI suffix preview before assignment

When you create an issue and assign articles, the DOI is computed at
deposit time. The CrossRef tab shows a sample DOI for the journal but
not the actual DOI for each article. If the journal's numbering pattern
ever needs to change, you'd discover the mistake only after deposit.

**Recommendation:** show each article's resolved DOI on the article
home page once the issue is assembled. Lint flags conflicts (two
articles with the same DOI).

### 3.6 No persistent ID beyond DOI

CrossRef ROR (organization), CrossRef Funder Registry (grants), ORCIDs
on contributors. We support ORCID. Funder and affiliation ROR are
absent. Major indexers expect these.

**Recommendation:** add ROR (`https://ror.org/...`) field on authors
and on the journal record (institutional affiliation). Add a per-article
funding statement field. Emit both in CrossRef XML (their schema
supports both).

### 3.7 No accessibility validation

Tagged PDF is half the battle — we do produce it via Typst. But:
- Alt text on figures isn't checked
- Heading hierarchy isn't validated (no h3 before h2, etc.)
- Color contrast in the HTML isn't audited
- PDF tagging quality isn't verified

**Recommendation:** integrate `axe-core` or similar accessibility
linter into the lint route. Run on rendered HTML; report violations.
For PDF: `verapdf` (open source PDF/A and PDF/UA validator) checks
tagging quality. Both can run as part of the lint pass.

### 3.8 No "publish" workflow distinct from "render"

Right now `status: published` is just a metadata flag. There's no
notion of:
- Locking metadata once published (preventing accidental edits)
- Recording the publication date stamp
- Issuing a notification (slack/email)
- Triggering CrossRef deposit
- Moving the source files to a read-only archive

**Recommendation:** add a `/articles/<id>/publish` action that:
1. Validates metadata (run lint, block if errors)
2. Sets `status: published` and stamps `published_at`
3. Snapshots the current rendered HTML/PDF as `article.published.html`
   and `article.published.pdf`
4. Optionally triggers CrossRef deposit
5. Optionally sends a Slack/email notification

### 3.9 No collaboration model

Single-user only. A real journal has multiple editors, copyeditors,
designers. OJS and Janeway model these as user roles with permissions.

**Recommendation:** not worth building unless LiCS wants to move off
OJS entirely. Graphion's current model (single layout editor working from
manuscripts handed to them) matches the actual LiCS workflow. Adding
multi-user is significant work for a small payoff in this context.

---

## 4. Export format gaps

Currently we export: **HTML** (semantic, OJS-galley-style) and **PDF**
(Typst, tagged, 6×9). Peer tools support more:

| Format | Graphion | Quarto | OJS | Editoria | Pressbooks | Reason it matters |
|---|---|---|---|---|---|---|
| HTML | ✓ | ✓ | upload | ✓ | ✓ | Web reading |
| Tagged PDF | ✓ | ✓ | upload | ✓ | ✓ | Print + accessibility |
| EPUB | ✗ | ✓ | plugin | ✓ | ✓ | E-readers, libraries |
| DOCX | ✗ | ✓ | upload | ✓ | ✓ | Sharing with non-tech reviewers |
| LaTeX | ✗ | ✓ | ✗ | ✗ | ✗ | Power users, journals that require it |
| **JATS XML** | ✗ | ✓ | ✓ | ✓ | ✗ | **PubMed Central, indexers** |
| **CrossRef XML** | ✓ | ✗ | plugin | ✗ | ✗ | DOI deposit |
| Plain Markdown | ✓ | ✓ | ✗ | ✓ | ✓ | Source archival |
| OPDS / catalog | ✗ | ✗ | ✓ | ✗ | ✓ | Aggregator discovery |

### 4.1 EPUB output — high value, low effort

Pandoc supports EPUB out of the box. We already have the cleaned
Markdown. One Pandoc invocation per article (similar to our HTML one)
produces a valid EPUB3. Add a per-article EPUB download and a per-issue
combined EPUB. Estimated: half a day.

### 4.2 DOCX output — useful for editorial review

Pandoc can emit DOCX from our Markdown. Use case: an editor wants to
send the cleaned article to an author for one last review, or to a
copyeditor who only uses Word. Half a day.

### 4.3 **JATS XML output — important for indexing**

JATS (Journal Article Tag Suite) is the lingua franca of scholarly
indexing. PubMed Central, Crossref's structured metadata, JISC's
Sherpa, and most aggregators consume JATS. Without it, indexers fall
back to deposit metadata only (which is shallower).

Pandoc's `jats` output is partial; we'd want to hand-craft the JATS
emitter to match the structural quality of our HTML template. Several
days of work.

This is the second-highest-ROI export to add (after EPUB) because it
makes the journal *indexable* in ways the CrossRef deposit alone
doesn't.

### 4.4 LaTeX output — low priority unless requested

Some journals require LaTeX submission. Pandoc can emit it. Add only if
asked.

### 4.5 No "format menu" UI

Even with new formats wired, the article page has individual buttons
per format. Compare to Quarto's `format: [html, pdf, epub, docx]` block
in `_quarto.yml` and a `quarto render` that produces all at once.

**Recommendation:** add a "Render formats" preference to the journal
that's a checkbox list (HTML, PDF, EPUB, DOCX, JATS). The article page
shows download links only for the enabled formats. A single Render
button produces all of them.

---

## 5. Prioritized roadmap

Given the work already done, here's what I'd recommend in order, with
rough effort estimates:

### Must — within the next month if LiCS is going to publish from this tool

1. **Structured citations via CSL + BibTeX** (3.1) — 3–5 days. Unlocks
   reference linking, CrossRef structured citations, and indexing
   eligibility.
2. **JATS XML export** (4.3) — 3–4 days. Required for PubMed Central
   and most academic indexers.
3. **EPUB export** (4.1) — half a day. Easy win.
4. **Lint / validation pass** (2.5) — 2 days. Catches mistakes before
   deposit.
5. **Revision diff viewer** (2.2) — 2 days. Already have the snapshots;
   just need to render diffs.

### Should — within the quarter

6. **Figure management with pandoc-crossref** (3.2, 3.3) — 2 days.
7. **WYSIWYG editor (ProseMirror) alongside CodeMirror** (2.1) — 1
   week. Big editorial UX win.
8. **Publish workflow with locked metadata** (3.8) — 2 days.
9. **Deposit tracking on CrossRef tab** (2.6) — 1 day.
10. **ORCID validation + auto-fill** (3.4) — half a day.
11. **DOCX export** (4.2) — half a day.

### Nice — when there's time

12. **ROR + Funder Registry** (3.6) — 1 day.
13. **Accessibility lint (axe-core + verapdf)** (3.7) — 2 days.
14. **Public reader site** (2.4) — 1–2 weeks. Only if you want to leave
    OJS.
15. **LaTeX export** (4.4) — half a day, only if a journal requires it.

### Skip — explicitly not worth building here

- **Multi-user collaboration / role-based access.** Not worth the
  complexity for a single-editor workflow. If LiCS needs this, stay on
  OJS for the review pipeline and use Graphion only for layout.
- **Author submission / peer review workflow.** Same reason; OJS does
  this and Graphion shouldn't try.
- **Print-on-demand integration.** Niche; only relevant if LiCS ever
  prints physical copies.
- **Analytics / read tracking.** OJS handles this if the public site is
  there.

---

## 6. The shortlist if you only do five things

If I had to pick five items that, together, would make the biggest
visible improvement to the tool's editorial quality and reach:

1. **Structured citations (CSL + BibTeX)** — fixes the biggest
   indexer-facing weakness
2. **JATS XML export** — unlocks PubMed Central and most aggregators
3. **EPUB export** — broadens reader reach
4. **WYSIWYG editor (ProseMirror)** — the biggest UI-friendliness win
5. **Lint / validation pass** — most affordance per line of code

Roughly two weeks of focused work for the first four; the fifth is
incremental as new checks land.

---

## Appendix: features peer tools have that we explicitly chose not to copy

For completeness, here's what I'd keep *out* of Graphion on principle:

- **Database-stored article content** (OJS does this). We deliberately
  keep article body on disk; the SQLite is just an index. Easier to
  migrate, version-control, and inspect.
- **Plugin ecosystem** (OJS). For a tool serving 1–2 journals it's not
  worth the surface area.
- **WordPress underneath** (Pressbooks). Adds an entire CMS layer for
  what is essentially a static-site-generator-with-metadata problem.
- **HTML/CSS-only PDF rendering** (Pressbooks, Vivliostyle). We chose
  Typst for typographic quality; Print CSS is a step backward.
- **JATS-native authoring** (Texture). JATS is for exchange/archival,
  not for authoring. Markdown is friendlier; we emit JATS from
  Markdown when needed.
