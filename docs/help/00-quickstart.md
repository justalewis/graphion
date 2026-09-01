# Quickstart

Your first article, start to finish, in about fifteen minutes.

This page assumes you have never opened Graphion before and that someone else
set it up. If you want the reasoning behind any step, every section below points
at a fuller page.

## What you are working with

Graphion turns an accepted Word manuscript into finished galleys: a web-ready
HTML page, a print-quality tagged PDF, an EPUB, and the XML that indexers and
CrossRef need. You hand it a `.docx`; it hands you back everything the issue
needs.

It is **not** a peer review system. By the time a manuscript reaches Graphion it
has already been accepted. See [Overview](overview) for what it deliberately
leaves to OJS.

## 1. Sign in

Open the address your editor sent you and sign in with the username and password
they gave you. Everything, including this help section, sits behind that login.

If you are running Graphion on your own machine instead, it lives at
`http://127.0.0.1:5050/`; see [Installation](installation).

The top bar is the same everywhere: **Dashboard**, **Issues**, **Bib Builder**,
**CrossRef**, **Help**, **Sign out**.

## 2. Upload the manuscript

From the **Dashboard**, click **Upload DOCX** next to the journal. Two fields on
that form are required and easy to skim past:

- **Short title** and **short authors**. These become the running headers along
  the top of every PDF page, so they need to be short enough to fit. "Composing
  Access" beats "Composing Access: Disability, Rhetoric, and the Work of the
  Multimodal Classroom".

Everything else has a sensible default. Leave the slug blank and it comes from
the filename. Tracked changes are accepted unless you say otherwise.

On submit, Graphion converts the document, pulls out title, authors, abstract,
and keywords, and runs a cleanup pass over the Word debris.

**Read the warnings it flashes back.** It scans the `.docx` for things that do
not survive conversion cleanly: text boxes, merged table cells, nested tables,
images with no alt text. None of these stop you, but each one is a place to look
before you publish.

More detail: [Articles](articles).

## 3. Look over the article page

You land on the article's home page. Four things to orient by:

- **Status strip** — when it last rendered, plus counts of sections, images,
  tables, and words.
- **Action grid** — the four clusters you will actually use: **Edit**,
  **Render**, **Outputs**, **Tools**.
- **Tabs** — Overview, Preview, Logs, Settings. Keys `1` through `4`.
- **Breadcrumb** — Dashboard, journal, issue, article.

## 4. Fix the metadata

**Edit**, then **Metadata**. This is a form; you never touch YAML.

Work down it: title and subtitle, DOI, the table-of-contents section the piece
belongs in, then authors as repeating rows of name, affiliation, and ORCID. Use
the arrow buttons to reorder authors; dragging is not supported yet. Then
abstract and keywords, then the running-header fields from step 2.

Saving does two things: it writes the metadata back into the article, and it
**re-renders automatically**. You do not need to press Render after a metadata
save.

## 5. Fix the body, if it needs it

**Edit** again, and pick the editor that matches the job:

| Editor | Use it for |
|---|---|
| **Rich (TinyMCE)** | Anything with tables. Full Word-style toolbar, real cell editing. |
| **Lite (ProseMirror)** | Plain prose. Fast and simple. |
| **Markdown** | Raw control, with a live preview beside the source. |

One trap worth naming: **Lite cannot handle tables**. Opening and saving a
table-heavy article in it will mangle them. The Edit menu shows a warning chip
when the article contains tables; believe it and use Rich instead.

Every save keeps a snapshot of the previous version, and the last five are
recoverable, so you can experiment.

## 6. Run lint

**Tools**, then **Run lint**. Eleven checks run: required fields, ORCID and DOI
formatting, running-header lengths, link well-formedness, whether a Works Cited
section exists, whether in-text citations match it, leftover cleanup artifacts,
missing image alt text, and unresolved figure cross-references.

Results are pass, warn, or fail. **Warnings do not block anything.** They are
advice, and some of them will not apply to your piece.

## 7. Render

Press **Render**, or just hit `R`. HTML and PDF are produced together; EPUB and
JATS build on demand the first time you ask for them.

Check the result in the **Preview** tab before moving on. If something looks
wrong, the **Logs** tab holds the full conversion trace.

The PDF is a 6x9 book page with running headers, a drop cap on the opening
paragraph, hanging-indent Works Cited, and automatic landscape pages for wide
tables.

## 8. Download what you need

The **Outputs** cluster appears once the article has rendered. The **Download**
menu is grouped by who the file is for:

- **For readers** — HTML and PDF galleys, EPUB.
- **For indexers** — JATS XML, CrossRef deposit XML.
- **For OJS submission** — a single ZIP bundling the HTML, its stylesheet, and
  its images, ready to upload as a galley.

See [Output formats](output-formats) for what each one is actually good for.

## What comes after

Individual articles are only half of it. Once an issue's lineup is settled,
assembling it renumbers every article's pages, builds the cover, masthead,
mission statement, editors' introduction, and table of contents, and
concatenates the whole thing into one issue PDF. That is
[Issues & front matter](issues-and-front-matter).

## Things that catch people out

- **Short title and short authors are not optional.** They drive the running
  headers, and the render will look wrong without them.
- **Metadata saves re-render; body saves do not.** After editing the body, press
  Render yourself.
- **Lite mangles tables.** Use Rich for anything tabular.
- **Warnings are advisory.** Neither the upload scan nor lint blocks you.
- **Your work is saved on the server, not in the browser.** Closing the tab
  loses nothing that you saved.

## Where to go next

- [Workflow](workflow) — the whole pipeline, including what happens during
  conversion.
- [Articles](articles) — every option on the article page in detail.
- [Citations & bibliography](citations) — BibTeX, MLA, and the Bib Builder.
- [Figures](figures) — numbering, cross-references, and alt text.
- [Troubleshooting & FAQ](troubleshooting) — when a render goes wrong.
