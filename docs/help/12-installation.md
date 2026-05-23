# Installation & setup

A start-from-scratch guide for getting Graphion running on your machine. Two paths: a **basic install** that gets you a working app in 10 minutes, and an **optional advanced install** that enables AI assistance, accessibility validators, and alternate engines.

## Minimum requirements (basic install)

- **Operating system:** macOS, Linux, or Windows. The tool is developed on Windows 11.
- **Python:** 3.11 or newer (3.12 recommended). Older Pythons (3.10 and below) are missing dataclass features the codebase relies on.
- **Pandoc:** 3.0 or newer. Required for ingest (DOCX → Markdown) and all output formats (HTML / EPUB / JATS / Typst input).
- **Disk:** A few hundred MB for dependencies. Each article averages 100 KB–2 MB depending on figures.
- **Browser:** Any modern browser. The Rich (TinyMCE) editor and the WYSIWYG editor load JS modules from CDN, so the first load needs internet; subsequent loads are cached.

## Basic install (10 minutes)

### Before you start

Install two things in advance: [Python 3.11+](https://www.python.org/downloads/) and [git](https://git-scm.com/downloads). On Windows, when the Python installer asks, tick **"Add Python to PATH"** before clicking Install — without that, the `python` command won't be found in your terminal.

Every command in this guide runs in a terminal: **cmd** or **PowerShell** on Windows, **Terminal** on macOS, your shell of choice on Linux. To confirm both tools are ready, open a terminal and run:

```bash
python --version
git --version
```

If both print a version number, you're set. If either reports "command not found" or "is not recognized," reinstall it and reopen the terminal before continuing.

If you would rather have the install script check these for you and walk through the rest interactively, clone the repo (Step 2 below) and then run `python graphion-install.py` instead of working through Steps 1–4 by hand.

### Step 1: Install Pandoc

**macOS** (Homebrew):
```bash
brew install pandoc
```

**Linux** (Debian/Ubuntu):
```bash
sudo apt install pandoc
```

Or download a `.deb` from the [Pandoc releases page](https://github.com/jgm/pandoc/releases) if your distro's package is older than 3.0.

**Windows:** Download the installer from <https://github.com/jgm/pandoc/releases>. The installer adds Pandoc to PATH automatically.

Verify:
```bash
pandoc --version
```
You should see `pandoc 3.x.x` or higher.

### Step 2: Clone the repo and install Python dependencies

```bash
git clone https://github.com/justalewis/graphion.git
cd graphion
python -m pip install -r requirements.txt
```

This installs Flask, Flask-Login, pypandoc, python-docx, PyYAML, mistune, lxml, requests, typst (which bundles the Typst rendering engine), pypdf, pypdfium2, bibtexparser, and the optional integration packages (mammoth, weasyprint, anthropic, pytesseract, Pillow — see [Advanced Tools](advanced-tools) for what each enables).

If you prefer a virtual environment (recommended for keeping dependencies isolated):

```bash
python -m venv .venv
source .venv/bin/activate         # macOS/Linux
.venv\Scripts\activate            # Windows PowerShell
pip install -r requirements.txt
```

### Step 3: First-run seed

```bash
python seed.py
```

The script will:

1. Create the SQLite database at `data/graphion.db`.
2. Apply the schema and any pending column migrations.
3. Register the LiCS example journal (you can rename/remove later via the Journal Settings page).
4. Prompt you for an admin username and password.

For non-interactive setup (CI, scripts):
```bash
python seed.py --user admin --pass changeme123 --email you@example.org
```

Then **change the password immediately** via the admin user record before deploying anywhere.

### Step 4: Run the app

```bash
python app.py
```

The app boots a Flask development server on port 5050. Open:

<http://127.0.0.1:5050/>

Sign in with the admin credentials you just created.

### Step 5: Smoke-test (optional)

The repo ships with a smoke-test:
```bash
python smoketest.py
```

This drives the full pipeline against a placeholder DOCX. If it passes, the install is healthy.

## Optional advanced install

These integrations are **all optional**. The basic install above is fully functional. Each advanced feature gracefully degrades when its dependency isn't present — the corresponding button in the UI just stays disabled with an "install X to enable" tooltip.

### Windows quick-installer (recommended for Windows users)

A PowerShell script at the repo root installs every advanced dependency in one shot via Chocolatey:

```cmd
cd C:\path\to\graphion
powershell -ExecutionPolicy Bypass -File .\install-graphion-deps.ps1
```

Run it in an **Administrator** PowerShell window. It auto-installs Chocolatey if absent, then installs LibreOffice, Tesseract OCR, Node.js, Java 21 (for verapdf), GTK3 Runtime (for WeasyPrint), verapdf, and pa11y. **Close PowerShell and open a new one after it finishes** — PATH updates only apply to new shells.

### Manual per-tool install (macOS / Linux / piecemeal Windows)

Each tool is independent. Install whichever you want; skip the others.

#### Mammoth — alternate DOCX reader (Python only)

Already in requirements.txt. Better than Pandoc for text-box-heavy Word documents.

```bash
pip install mammoth
```

After install, the **upload form** shows a *Pandoc / Mammoth* radio button.

#### LibreOffice — DOCX normalize preprocessor

Install LibreOffice from <https://www.libreoffice.org/download/>. Graphion looks for `soffice` on PATH or in the standard install location (`C:\Program Files\LibreOffice\program\` on Windows).

After install, the **upload form** shows a *Round-trip the DOCX through LibreOffice before ingest* checkbox. Helps with documents that have text boxes, complex tables, or autoformat junk.

#### Tesseract OCR — image OCR

OCR pasted screenshots of tables back into recoverable text.

```bash
# Python wrapper (already in requirements.txt)
pip install pytesseract Pillow

# Tesseract CLI binary (separate install):
#   macOS:    brew install tesseract
#   Linux:    apt install tesseract-ocr
#   Windows:  https://github.com/UB-Mannheim/tesseract/wiki  (check "Add to PATH" during install)
```

After install: **Article page → Tools → Advanced → OCR images (Tesseract)**.

#### WeasyPrint — alternate PDF render

```bash
# Python (already in requirements.txt)
pip install weasyprint
```

WeasyPrint also needs **native GTK runtime libraries**. On macOS: `brew install cairo pango gdk-pixbuf`. On Linux: `apt install python3-cffi libpango-1.0-0 libpangoft2-1.0-0`. On Windows: install the [GTK3 runtime](https://github.com/tschoonj/GTK-for-Windows-Runtime-Environment-Installer/releases) (the installer ticks "Add to PATH" by default).

After install: **Article page → Tools → Advanced → Render PDF (WeasyPrint)**.

#### verapdf — PDF/UA accessibility validator

verapdf is a Java tool. Install [Java 21 (Temurin)](https://adoptium.net/temurin/releases/?version=21) first, then download verapdf from <https://verapdf.org/software/> and add it to PATH.

After install: **Article page → Tools → Advanced → Validate PDF/UA**.

#### pa11y — HTML accessibility audit

```bash
# Requires Node.js (https://nodejs.org/)
npm install -g pa11y
```

After install: **Article page → Tools → Advanced → Audit HTML accessibility**.

#### Anthropic Claude API — AI editorial assistance

The most useful advanced feature. Powers the **Stylize article ★** button (applies the journal's style guide to the whole article in one pass: splits Works Cited, fixes tables, strips Word junk, normalizes typography). Also powers alt-text generation and table repair.

**Step A: Get an API key.** Sign up at <https://console.anthropic.com/>. Generate a key from Settings → API Keys.

**Step B: Install the Python SDK.** Already in requirements.txt:

```bash
pip install anthropic
```

**Step C: Set the env var.** In the shell where you'll run `python app.py`:

```bash
# macOS / Linux:
export ANTHROPIC_API_KEY=sk-ant-your-key-here

# Windows cmd:
set ANTHROPIC_API_KEY=sk-ant-your-key-here

# Windows PowerShell:
$env:ANTHROPIC_API_KEY = "sk-ant-your-key-here"
```

**To make it permanent on Windows** (so you don't have to set it every shell):
```cmd
setx ANTHROPIC_API_KEY "sk-ant-your-key-here"
```
Then close and reopen the terminal — `setx` only applies to new shells.

**To make it permanent on macOS / Linux**, add the `export` line to `~/.zshrc` (zsh) or `~/.bashrc` (bash) or `~/.config/fish/config.fish` (fish).

Verify the key is visible to Python:
```bash
python -c "import os; print('Set:' if os.environ.get('ANTHROPIC_API_KEY') else 'Not set:', bool(os.environ.get('ANTHROPIC_API_KEY')))"
```

After setup: **Article page → Tools → Advanced → Stylize article ★**. Costs typically $0.02–$0.05 per article at Haiku 4.5 pricing.

**Customize the per-journal style guide** at `content/journals/<slug>/template/style-guide.md`. The default LiCS style guide ships with the repo — edit it once to match your journal's conventions, and the Stylize button uses it every time. See [Advanced Tools → Stylize](advanced-tools) for details.

## Deriving typography from an existing InDesign layout

If your journal has been laid out in InDesign for years, the IDML export of any past issue is a goldmine — it contains the exact paragraph styles (font, point size, leading, indentation, spacing) that define your house typography. Graphion can use those numbers directly in its Typst template so the rendered PDF closely matches your hand-laid issues.

This is **optional** but highly recommended if you're adapting Graphion for a journal that already has an established print design.

### Step 1: Export IDML from InDesign

In InDesign, open a recent issue or article that represents your house style.

1. **File → Save As...**
2. Format dropdown → **InDesign Markup (IDML)**
3. Save somewhere accessible (e.g., `~/Desktop/MyJournal.idml`)

IDML is a zip-based format that preserves every style definition.

### Step 2: Extract `Styles.xml`

IDML is internally a zip archive. The styles live in `Resources/Styles.xml`. On Windows, the simplest way to extract just that file (avoiding rename hassles with hidden file extensions):

```cmd
cd "C:\path\to\folder\with\your\idml"
python -c "import zipfile; zipfile.ZipFile('MyJournal.idml').extract('Resources/Styles.xml', '.')"
```

On macOS/Linux:

```bash
unzip -p MyJournal.idml Resources/Styles.xml > Styles.xml
```

Or just extract the whole IDML if you want to poke around:

```bash
python -c "import zipfile; zipfile.ZipFile('MyJournal.idml').extractall('idml-extracted')"
```

You only need `Styles.xml` for typography work. The other files (Stories, MasterSpreads, Graphic) contain article content, page-level masters, and color swatches respectively — useful as additional reference but not strictly needed.

### Step 3: Survey the paragraph styles

A short Python script enumerates every paragraph style with its key typographic values:

```bash
python -c "
import xml.etree.ElementTree as ET
root = ET.parse('Styles.xml').getroot()
for ps in root.findall('.//ParagraphStyle'):
    name = ps.get('Name', '')
    pt = ps.get('PointSize', '')
    weight = ps.get('FontStyle', '')
    first_ind = ps.get('FirstLineIndent', '0')
    left_ind = ps.get('LeftIndent', '0')
    space_b = ps.get('SpaceBefore', '0')
    space_a = ps.get('SpaceAfter', '0')
    align = ps.get('Justification', '')
    props = ps.find('Properties')
    leading = font = ''
    if props is not None:
        le = props.find('Leading');     leading = le.text if le is not None else ''
        fo = props.find('AppliedFont'); font = fo.text if fo is not None else ''
    print(f'{name}: font={font} size={pt}pt leading={leading} weight={weight} align={align} indent=first:{first_ind} left:{left_ind} space=before:{space_b} after:{space_a}')
"
```

The output lists every paragraph style in the document — typically 50-100 entries. Look for the ones that correspond to your editorial structure:

| Common InDesign style name | Maps to |
|---|---|
| BodyText / Body / Body Text / Body First | Article body |
| ChapterTitle / Article Title / Title | Article title |
| SubHead / Section Head / Heading 1 / H1 | Section heading |
| SubSection Heading / Heading 2 / H2 | Subsection |
| BlockQuote / Block Quote / Quote | Block quote |
| Pull Quotes / Pull-Quote / Sidebar | Pull quote |
| WorksCited / Bibliography / References | Works Cited entries |
| Notes / Footnote / Endnote | Endnote text |
| caption / Figure Caption | Figure caption |
| PageNumbers / Page Number | Page numbers |
| RunningHeader / Running Head | Running header |

Ignore the dozens of `Paragraph Style N` and Word-imported clutter styles — most are unused. Focus on the named editorial styles that match the table above.

### Step 4: Map values to the Typst template

Open `content/journals/<your-journal-slug>/template/article.typ`. Update these values to match your IDML export:

- **`body-font`** and **`display-font`** font stacks (top of file) — list your house fonts first, with free fallbacks after (EB Garamond is bundled with Typst, GFS Didot is free for high-contrast display, etc.)
- **`#set text(font: body-font, size: <Npt>, ...)`** — body size from the BodyText paragraph style
- **`#set par(leading: <Mem>, first-line-indent: <Npt>, ...)`** — leading from Leading property (compute as `(leading - body_size) / body_size` for em-based leading; or just use absolute points), and first-line indent from FirstLineIndent
- **`#show heading.where(level: 1)`** — section heading: font, size, alignment, spacing before/after from SubHead / Article Sections
- **`#show heading.where(level: 2)`** — subsection: font, size, alignment from SubSection Heading
- **Title block** (`#align(center, { ... [$title$] ... })`) — title size from ChapterTitle, subtitle treatment, author byline
- **Block quote** (`#show quote.where(block: true)`) — left/right pad from BlockQuote's LeftIndent
- **Page header/footer** (`#set page(header: ..., footer: ...)`) — size, font, alignment from RunningHeader / PageNumbers

Once you've updated `article.typ`, re-render any article in the app — the PDF should now closely match your hand-laid InDesign reference.

### Step 5: Document the typography in the editorial style guide

The per-journal style guide at `content/journals/<your-journal-slug>/template/style-guide.md` (read by Graphion's Claude-powered **Stylize** button) should have a "House typography" section documenting the canonical values. This serves three purposes:

1. **Editor reference** — anyone working on the journal can see what the rendered output should look like
2. **Claude context** — when Stylize sees the typography table as the canonical source of truth, it disambiguates editorial structure (e.g., "this looks like a section head — it should be `##` because that maps to Didot 13pt centered in the table")
3. **Future-proofing** — when the journal redesigns, you update the table here first, then propagate to `article.typ`, `article.css`, etc.

See `content/journals/lics/template/style-guide.md` for the canonical example — the "House typography" section near the top of the file shows the format. You can copy that structure into your own journal's guide and fill in your IDML-derived values.

### Step 6 (optional): Custom font installation

If your house font is commercial (Minion Pro, Didot, Adobe Garamond, etc.), it's typically already installed on machines that have InDesign. Typst will pick it up automatically via the system font resolver. If you need to install fonts on a machine that doesn't have InDesign:

- **Open-source equivalents**: EB Garamond (Minion-ish), GFS Didot (Didot), Crimson Text (Garamond-ish), Inter (sans). All free from Google Fonts / SIL repositories.
- **Commercial fonts**: install per-license through the relevant foundry; Typst reads system-installed fonts on all platforms.

Test font availability with a one-liner:

```bash
python -c "import typst; print(typst.query('test.typ', '--font'))" 2>&1 | head -20
```

(Or simpler: render an article and check the resulting PDF — if Typst can't find your declared font, it falls through the fallback chain in the template and the rendered output uses the next-available face.)

### Recap

A 30-minute workflow that pays for itself on every future article:

1. Export IDML from a representative recent issue
2. Extract `Styles.xml`
3. Run the survey script, note your editorial style values
4. Update `article.typ` in your journal's template directory
5. Document the values in the style guide for editor reference + Claude context
6. Render an article and compare to your hand-laid reference PDFs

## Configuration knobs

Most config lives in the database (set via the Journal Settings UI). A few environment variables override defaults:

| Variable | Default | What it does |
|---|---|---|
| `PORT` | `5050` | Port to bind |
| `FLASK_SECRET_KEY` | per-process random | Session signing key (set in production) |
| `PANDOC_PATH` | `pandoc` | Path to the Pandoc binary if not on PATH |
| `TYPST_PATH` | bundled | Path to a Typst binary (default: the `typst` Python package's bundled engine) |
| `ANTHROPIC_API_KEY` | unset | Enables Claude features (Stylize, alt-text, table repair) |
| `GRAPHION_CLAUDE_MODEL` | `claude-haiku-4-5` | Override Claude model (e.g., `claude-sonnet-4-5` for harder articles) |
| `OJS_URL` | unset | Future: direct OJS REST submission base URL |
| `OJS_API_TOKEN` | unset | Future: OJS API token |

## Updating

```bash
git pull
pip install -r requirements.txt    # in case requirements changed
python seed.py                     # runs migrations; safe to re-run
```

Schema migrations are additive (`ALTER TABLE ... ADD COLUMN`) and idempotent; existing data is never modified.

## Deployment beyond local dev

Graphion is designed as a single-editor local tool. For multi-machine access:

1. Use a production WSGI server (`gunicorn`, `waitress`) instead of `app.run`.
2. Reverse-proxy behind nginx or Caddy with HTTPS.
3. Set `FLASK_SECRET_KEY` from environment.
4. Persist `data/graphion.db` and `content/` on a backed-up volume.
5. Optionally containerize: a `Dockerfile` that starts from `python:3.12-slim`, installs Pandoc, and adds the repo is straightforward. For the advanced integrations, layer in LibreOffice, Node, Java, and the GTK runtime as needed.

There is no built-in multi-user authentication or role-based access control. If multiple people need to collaborate, run multiple instances or stick to OJS for the submission/review workflow and use Graphion only for layout.

## Troubleshooting the install

| Symptom | Likely cause | Fix |
|---|---|---|
| `pandoc not found` at render | Pandoc not on PATH | Re-install Pandoc, verify with `pandoc --version` |
| `TypstError: file not found` | Image referenced but not in `assets/` | Use the Missing Images upload form on the article page |
| `weasyprint` import fails with `libgobject-2.0-0` error | GTK3 native libs missing | Install GTK3 runtime (see WeasyPrint section above) |
| `Stylize ★` button greyed out | `ANTHROPIC_API_KEY` not set or `anthropic` not installed | Set the env var in the SAME shell where `python app.py` runs |
| `Tools → OCR images` greyed out | Tesseract CLI not on PATH | Install Tesseract binary AND `pip install pytesseract` |
| `verapdf` command not found | Java not installed or verapdf not on PATH | Install Java 21 Temurin + add `verapdf` to PATH |
| `pa11y` not installed | Node.js missing | Install Node.js, then `npm install -g pa11y` |

See [Troubleshooting](troubleshooting) for runtime errors beyond setup.
