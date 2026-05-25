-- LiCS Pandoc Lua filter.
--
-- Works in tandem with `--section-divs`. Pandoc auto-wraps each H1
-- section in `<section class="level1">`; this filter adds extra classes
-- and identifiers so the article.css selectors match the design:
--
--   * First H1 section gets class "opening" (enables the drop cap in HTML
--     via section.opening > h1 + p::first-letter)
--   * Works Cited / References / Bibliography H1 gets:
--       - identifier "works-cited"
--       - class "references"
--
-- For Typst output, the filter additionally wraps the first character of
-- the first paragraph of the opening section in a #dropcap[X] raw inline.
-- This is needed because Pandoc's Typst writer does not propagate header
-- classes, so we cannot key a Typst `show` rule on the `opening` class.
-- HTML output uses CSS `::first-letter`; the drop cap there does not need
-- the wrapping.
--
-- Additional journal idioms (pull quotes, epigraphs, etc.) can be added
-- here as patterns surface.

local first_h1_seen = false

-- Convert ` | ` (space-pipe-space) tokens in an Inlines list into
-- LineBreak elements. This is the editorial convention for forcing a
-- line break in a title or heading — long titles like
-- "Facing What's Human: | From Dialogic Intertextuality | to Translingual Praxis"
-- get the breaks the editor specified rather than whatever Typst's
-- line-breaker decides on its own. Pandoc renders LineBreak natively
-- per format (Typst `\`, HTML `<br>`, JATS just collapses to space).
--
-- Pandoc tokenizes `## Foo | Bar` as [Str("Foo"), Space, Str("|"),
-- Space, Str("Bar")], so a pipe usually appears as its own Str node
-- bracketed by Space inlines. We drop the surrounding Spaces — one
-- by rewinding the output, one by skipping a Space whose immediate
-- predecessor in the output is a LineBreak — so the line doesn't
-- start or end with a stray space. We only inspect top-level Str
-- nodes; pipes nested inside Emph/Strong/Link are left alone.
local function split_pipes_to_linebreaks(inlines)
  local out = pandoc.Inlines({})
  for _, inl in ipairs(inlines) do
    if inl.t == "Space" and #out > 0 and out[#out].t == "LineBreak" then
      -- Drop the leading space that followed a forced break.
    elseif inl.t == "Str" and inl.text:find("|", 1, true) then
      local parts = {}
      local i = 1
      while true do
        local s, e = inl.text:find("|", i, true)
        if not s then
          table.insert(parts, inl.text:sub(i))
          break
        end
        table.insert(parts, inl.text:sub(i, s - 1))
        table.insert(parts, "|")
        i = e + 1
      end
      for _, p in ipairs(parts) do
        if p == "|" then
          while #out > 0 and out[#out].t == "Space" do
            out:remove(#out)
          end
          out:insert(pandoc.LineBreak())
        elseif p ~= "" then
          out:insert(pandoc.Str(p))
        end
      end
    else
      out:insert(inl)
    end
  end
  return out
end

local function is_references_heading(header)
  local txt = pandoc.utils.stringify(header):lower()
  return txt:match("^works cited") ~= nil
      or txt:match("^references") ~= nil
      or txt:match("^bibliography") ~= nil
end

local function _is_notes_text(header)
  local txt = pandoc.utils.stringify(header):lower()
  return txt:match("^notes%s*$") ~= nil or txt:match("^endnotes%s*$") ~= nil
end

-- Pipe-to-linebreak: split the inline content of every heading on
-- ` | ` tokens so editors can control where long headings wrap. The
-- transformation happens before the references/notes tagging below so
-- a `## Works Cited: | Primary Sources` would still get the
-- references treatment (we stringify before checking, which collapses
-- the LineBreak back to a space for the match).
function Header(el)
  el.content = split_pipes_to_linebreaks(el.content)
  -- Tag the references/works-cited heading regardless of source level.
  -- Some articles use `### Works Cited` (H3) — typed that way by an
  -- editor or by Claude per the style guide — others use `# Works Cited`
  -- (H1) depending on how the source DOCX styled it. We PROMOTE all of
  -- them to level 1 so they pick up the canonical section-heading
  -- treatment (Didot 13pt centered per the LiCS typography table),
  -- matching other section headings in the article body. Same for
  -- explicit Notes / Endnotes headings.
  if is_references_heading(el) then
    el.level = 1
    el.identifier = "works-cited"
    table.insert(el.classes, "references")
    return el
  end
  if _is_notes_text(el) then
    -- HTML and EPUB: Pandoc auto-emits a `<section id="footnotes">`
    -- with the actual numbered notes inside. The explicit `### Notes`
    -- heading from the markdown source would render as an empty
    -- orphan section right above it — visible to readers as a bare
    -- "Notes" line followed by a blank gap, then Pandoc's own `<hr>`
    -- and numbered list. Delete the orphan. The auto-generated
    -- section already gets a "Notes" label via the CSS rule
    -- `section.footnotes::before { content: "Notes"; ... }`.
    if FORMAT:match("^html") or FORMAT:match("^epub") then
      return {}
    end
    -- Typst (and any other format without Pandoc's auto-footnotes
    -- behavior): keep the heading. Our Pandoc() pass injects the
    -- collected note content under it.
    el.level = 1
    el.identifier = "notes-section"
    table.insert(el.classes, "notes")
    return el
  end
  if el.level == 1 then
    if not first_h1_seen then
      first_h1_seen = true
      table.insert(el.classes, "opening")
    end
    return el
  end
  return nil
end

-- Typst-only: inject a #dropcap[X] raw inline at the start of the
-- opening paragraph.
--
-- Two-pass strategy: first look for the canonical "opening" section
-- (the first H1 that isn't Works Cited). If found, drop the cap there.
-- If the article has no H1s at all (common for book reviews and short
-- articles), fall back to the FIRST body-level Para that comes after
-- the document title. Either way, the visual result is "drop cap on
-- the first letter of the running text."
local function inject_typst_dropcap(blocks)
  local in_opening = false
  local injected = false

  local function wrap_first_letter(block)
    local first_str_idx = nil
    for i, inline in ipairs(block.content) do
      if inline.t == "Str" and #inline.text > 0 then
        first_str_idx = i
        break
      end
    end
    if first_str_idx then
      local s = block.content[first_str_idx].text
      local letter = s:sub(1, 1)
      local rest = s:sub(2)
      local dropcap_raw = pandoc.RawInline("typst", "#dropcap[" .. letter .. "]")
      block.content[first_str_idx] = pandoc.Str(rest)
      table.insert(block.content, first_str_idx, dropcap_raw)
      return true
    end
    return false
  end

  -- Pass 1: opening-section heuristic.
  for _, block in ipairs(blocks) do
    if block.t == "Header" and block.level == 1 then
      in_opening = false
      for _, cls in ipairs(block.classes or {}) do
        if cls == "opening" then in_opening = true end
      end
    elseif in_opening and not injected and block.t == "Para" then
      if wrap_first_letter(block) then injected = true end
    end
  end

  -- Pass 2: fallback if Pass 1 didn't fire (article has no opening
  -- H1 — e.g., book reviews, short articles whose body starts with
  -- prose). Wrap the very first Para in the document.
  if not injected then
    for _, block in ipairs(blocks) do
      if block.t == "Para" then
        if wrap_first_letter(block) then injected = true end
        break
      end
    end
  end

  return blocks
end

-- Typst-only: after the Works Cited heading, inject a #set par(...) raw
-- block that turns OFF the global first-line indent and turns ON a
-- hanging indent. This is the standard hanging-indent treatment for
-- bibliography entries (first line at the margin; subsequent lines
-- indented). HTML output handles the same effect via CSS on
-- section.references; Typst needs an explicit setting because the
-- references heading doesn't carry classes through to the body.
local function is_notes_heading(header)
  local txt = pandoc.utils.stringify(header):lower()
  return txt:match("^notes%s*$") ~= nil or txt:match("^endnotes%s*$") ~= nil
end

local function inject_typst_hanging_indent(blocks)
  -- (a) Apply hanging-indent treatment after any references-style
  -- heading, whatever its level. Some articles label Works Cited as
  -- H1, others as H3 (depends on DOCX styling), and we want the
  -- bibliography to render correctly in both cases.
  -- (b) Start Works Cited and explicit Notes/Endnotes sections on
  -- their own pages — matches the LiCS print convention.
  local out = {}
  for _, block in ipairs(blocks) do
    if block.t == "Header" and is_references_heading(block) then
      table.insert(out, pandoc.RawBlock("typst", "#pagebreak()"))
      table.insert(out, block)
      table.insert(out, pandoc.RawBlock(
        "typst",
        "#set par(first-line-indent: 0pt, hanging-indent: 1.5em)"
      ))
    elseif block.t == "Header" and is_notes_heading(block) then
      table.insert(out, pandoc.RawBlock("typst", "#pagebreak()"))
      table.insert(out, block)
      table.insert(out, pandoc.RawBlock(
        "typst",
        "#set par(first-line-indent: 0pt, hanging-indent: 1.2em, leading: 0.55em)\n#set text(size: 9.5pt)"
      ))
    else
      table.insert(out, block)
    end
  end
  return out
end

-- Typst-only: convert footnotes to endnotes.
--
-- Pandoc's Typst writer emits each `[^N]` reference as a `#footnote[...]`
-- call, which Typst places at the bottom of the page where the reference
-- appears. That's standard book typography but most journal articles
-- (including LiCS) prefer an end-of-article "Notes" section. We replace
-- each Pandoc `Note` AST node with a numbered superscript marker, hold
-- the note content aside, then append a "Notes" H1 plus a numbered list
-- of contents at the document end.
local collected_notes = {}

local function has_explicit_notes_heading(blocks)
  -- Detect whether the document already has a "Notes" / "Endnotes"
  -- heading at any level. If so, our auto-injected one would be a
  -- duplicate. (Common when an editor — or Claude via Stylize — has
  -- added an explicit ### Notes section to the markdown.)
  for _, block in ipairs(blocks) do
    if block.t == "Header" then
      local txt = pandoc.utils.stringify(block):lower()
      if txt:match("^notes%s*$") or txt:match("^endnotes%s*$") then
        return true
      end
    end
  end
  return false
end

local function collect_typst_endnotes(doc)
  -- First pass: walk and rewrite Note inlines.
  local idx = 0
  doc = doc:walk({
    Note = function(el)
      idx = idx + 1
      table.insert(collected_notes, el.content)
      -- Emit a Typst-native superscript so the marker matches the
      -- numbered list at the end. RawInline keeps the rendered form
      -- under our control rather than relying on Pandoc's default
      -- Superscript styling.
      return pandoc.RawInline("typst", "#super[" .. tostring(idx) .. "]")
    end,
  })

  -- Helper: build the list of blocks that emit the endnote content
  -- (numbered superscript marker + content for each note). We do NOT
  -- emit a #set par here when injecting after an explicit Notes
  -- heading — inject_typst_hanging_indent runs later in the same
  -- Pandoc(doc) pass and emits the right par/text settings right
  -- after the explicit Notes heading, so this helper would just
  -- duplicate them.
  local function emit_notes_blocks()
    local blocks = {}
    for i, content in ipairs(collected_notes) do
      local first = content[1]
      if first and first.t == "Para" then
        local inlines = pandoc.Inlines({})
        inlines:insert(pandoc.Superscript(pandoc.Str(tostring(i))))
        inlines:insert(pandoc.Space())
        for _, inl in ipairs(first.content) do inlines:insert(inl) end
        table.insert(blocks, pandoc.Para(inlines))
        for j = 2, #content do
          table.insert(blocks, content[j])
        end
      else
        for _, b in ipairs(content) do
          table.insert(blocks, b)
        end
      end
    end
    return blocks
  end

  if #collected_notes > 0 and has_explicit_notes_heading(doc.blocks) then
    -- Article has an explicit `### Notes` heading (Claude typically
    -- adds this during stylize). The heading is already in the right
    -- place; we just need to inject the stashed note content right
    -- after it. Pandoc consumed the original `[^N]:` definitions when
    -- parsing the markdown, so the heading was left orphan — that's
    -- why earlier renders showed "Notes" with nothing under it.
    local new_blocks = {}
    for _, block in ipairs(doc.blocks) do
      table.insert(new_blocks, block)
      if block.t == "Header" then
        local txt = pandoc.utils.stringify(block):lower()
        if txt:match("^notes%s*$") or txt:match("^endnotes%s*$") then
          for _, b in ipairs(emit_notes_blocks()) do
            table.insert(new_blocks, b)
          end
        end
      end
    end
    doc.blocks = pandoc.Blocks(new_blocks)
    return doc
  end

  if #collected_notes > 0 then
    -- No explicit Notes heading — append one (LiCS print convention)
    -- on its own page.
    doc.blocks:insert(pandoc.RawBlock("typst", "#pagebreak()"))
    local notes_header = pandoc.Header(
      1,
      pandoc.Inlines({ pandoc.Str("Notes") }),
      pandoc.Attr("notes-section", { "notes-endnotes" })
    )
    doc.blocks:insert(notes_header)
    -- Reset the global hanging-indent setting (which was set after the
    -- Works Cited heading) and turn on a tighter, smaller-text style
    -- for the notes list itself.
    doc.blocks:insert(pandoc.RawBlock(
      "typst",
      "#set par(first-line-indent: 0pt, hanging-indent: 1.2em, leading: 0.55em)\n#set text(size: 9.5pt)"
    ))
    for i, content in ipairs(collected_notes) do
      -- Content from `Note` is a list of Blocks; flatten the first
      -- block's inlines into a single paragraph prefixed with the
      -- numbered marker. Multi-paragraph notes are rare; if present,
      -- the trailing paragraphs come after.
      local first = content[1]
      local first_inlines = pandoc.Inlines({})
      if first and first.t == "Para" then
        first_inlines:insert(pandoc.Superscript(pandoc.Str(tostring(i))))
        first_inlines:insert(pandoc.Space())
        for _, inl in ipairs(first.content) do
          first_inlines:insert(inl)
        end
        doc.blocks:insert(pandoc.Para(first_inlines))
        -- Any additional paragraphs in the note.
        for j = 2, #content do
          doc.blocks:insert(content[j])
        end
      else
        -- Fallback: treat the whole content as separate blocks.
        for _, b in ipairs(content) do
          doc.blocks:insert(b)
        end
      end
    end
  end
  return doc
end

-- Typst-only: adapt tables to the 6x9 book trim based on column count.
--
-- 6x9 with 0.75-inch side margins leaves only ~4.5 inches for content,
-- which is plenty for 2-3 column tables but cramped for 4+ column data
-- charts (each column gets ~1 inch — too narrow for prose cells). We
-- handle the two regimes differently:
--
--   * 4+ columns: wrap the table's #figure in `#page(flipped: true)`
--     so it gets its own landscape (9x6) page. That gives ~7.5 inches
--     of horizontal space — readable.
--   * 2-3 columns: leave on the portrait page but reduce the font size
--     to 8pt so column content fits without aggressive wrapping.
--   * 1 column: untouched (these are callout-boxes already styled as
--     blockquotes via the earlier cleanup pass).
local function adapt_typst_tables(blocks)
  local out = {}
  for _, block in ipairs(blocks) do
    if block.t == "Table" then
      local ncols = #block.colspecs
      if ncols >= 4 then
        table.insert(out, pandoc.RawBlock(
          "typst",
          "#page(flipped: true)[\n#set text(size: 9pt)"
        ))
        table.insert(out, block)
        table.insert(out, pandoc.RawBlock("typst", "]"))
      elseif ncols >= 2 then
        table.insert(out, pandoc.RawBlock(
          "typst",
          "#block[\n#set text(size: 8pt)"
        ))
        table.insert(out, block)
        table.insert(out, pandoc.RawBlock("typst", "]"))
      else
        table.insert(out, block)
      end
    elseif block.t == "Div" then
      -- Recurse into Divs so tables nested inside them also get
      -- adapted. Pandoc-emitted figures wrap the table in a Div.
      block.content = adapt_typst_tables(block.content)
      table.insert(out, block)
    else
      table.insert(out, block)
    end
  end
  return out
end

-- Apply the pipe-to-linebreak convention to title and subtitle in the
-- document metadata, so editors can write
--   title: "Facing What's Human: | From Dialogic Intertextuality | to Translingual Praxis"
-- in YAML and get a three-line title on the title page. Pandoc parses
-- title/subtitle as MetaInlines, which can hold LineBreak nodes; the
-- Typst writer renders them as `\`, the HTML writer as `<br>`.
local function split_pipes_in_meta(meta)
  for _, key in ipairs({ "title", "subtitle" }) do
    if meta[key] and meta[key].t == "MetaInlines" then
      meta[key] = pandoc.MetaInlines(split_pipes_to_linebreaks(meta[key]))
    end
  end
  return meta
end

function Pandoc(doc)
  doc.meta = split_pipes_in_meta(doc.meta)
  if FORMAT == "typst" then
    doc = collect_typst_endnotes(doc)
    doc.blocks = inject_typst_dropcap(doc.blocks)
    doc.blocks = inject_typst_hanging_indent(doc.blocks)
    doc.blocks = adapt_typst_tables(doc.blocks)
  end
  return doc
end
