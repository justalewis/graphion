-- LiCS Pandoc Lua filter.
--
-- Works in tandem with `--section-divs`. Pandoc auto-wraps each H1
-- section in `<section class="level1">`; this filter adds extra classes
-- and identifiers so the article.css selectors match the design:
--
--   * First H1 section gets class "opening" (retained for any per-journal
--     stylesheet that keys off it; the drop cap no longer needs it).
--   * Works Cited / References / Bibliography H1 gets:
--       - identifier "works-cited"
--       - class "references"
--
-- Drop cap: the first Para of the body proper carries the initial, whether
-- the body opens with prose or with a heading. Two output paths need it:
--   * Typst: the filter wraps the first character in a #dropcap[X] raw
--     inline. Pandoc's Typst writer does not propagate block classes, so
--     a `show` rule keyed on a class is not an option.
--   * HTML / EPUB: the filter wraps the first Para in a Div with class
--     "opening-para" so article.css can target `.opening-para > p::first-letter`
--     regardless of whether that paragraph sits before or inside a section.
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

-- Typst-only: wrap the first body Para in document order in #dropcap[...].
--
-- The rule is deliberately "first Para, wherever it sits" rather than
-- "first Para of the opening section." A body that opens with prose
-- above the first H1 — e.g., an introductory line the editor moved out
-- of the abstract — still gets its cap on that line, not on the first
-- paragraph that happens to follow a heading. Book reviews and short
-- articles with no H1s at all fall into the same rule for free.
--
-- The template's #dropcap takes the whole paragraph (it hands it to the
-- droplet package) so the text flows beside a two-line initial. Wrapping
-- only the first letter made the enlarged glyph inflate the first line's
-- height, leaving a visible gap between lines one and two.
local function inject_typst_dropcap(blocks)
  local function wrap_para(block)
    local first = nil
    for _, inline in ipairs(block.content) do
      if inline.t == "Str" and #inline.text > 0 then
        first = inline.text:sub(1, 1)
        break
      elseif inline.t ~= "Space" then
        return false
      end
    end
    -- Only ever cap a letter or digit; a paragraph opening with a quotation
    -- mark, bracket, or formatting is left as ordinary text.
    if not first or not first:match("[%w]") then return false end
    block.content:insert(1, pandoc.RawInline("typst", "#dropcap["))
    block.content:insert(pandoc.RawInline("typst", "]"))
    return true
  end

  for i, block in ipairs(blocks) do
    if block.t == "Para" then
      -- Typst indents a paragraph only when it follows another paragraph,
      -- and the drop-cap block is not one, so the paragraph after it would
      -- start flush left. Give it the body indent explicitly.
      if wrap_para(block) and blocks[i + 1] and blocks[i + 1].t == "Para" then
        blocks[i + 1].content:insert(1, pandoc.RawInline("typst", "#h(18pt)"))
      end
      break
    end
  end

  return blocks
end

-- HTML / EPUB: wrap the first body Para in a Div with class
-- "opening-para" so article.css can attach the drop cap by class rather
-- than by structural position. Same "first Para, wherever it sits"
-- rule as the Typst path above.
local function wrap_html_opening_para(blocks)
  for i, block in ipairs(blocks) do
    if block.t == "Para" then
      blocks[i] = pandoc.Div({block}, pandoc.Attr("", {"opening-para"}))
      break
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

-- Opening raw blocks for the two end sections. Each opens a Typst content
-- block and applies its paragraph settings *inside* it.
--
-- The previous version emitted a bare `#set par(...)` after the heading and
-- relied on it reaching the entries that followed. It never reached the
-- first one: entry 1 rendered with the body's first-line indent while every
-- later entry hung correctly. Scoping the settings inside a block that
-- physically contains the entries removes the ordering question.
--
-- `breakable: true` is deliberate; a bibliography must still flow across
-- pages. `hyphenate: true` is re-enabled here only. The body disables
-- hyphenation house-wide, but justified hanging-indent entries carrying
-- long URLs open up unreadable word gaps without it.
-- Both end sections hang to the same measure, stated absolutely rather than in
-- em. Notes set 9.5pt against the references' 10pt, so equal em values would
-- have produced visibly different indents; the two sections sit one after the
-- other and any difference reads as a mistake.
local HANGING_INDENT = "15pt"

local REFERENCES_OPEN = table.concat({
  "#block(width: 100%, breakable: true)[",
  "#set par(first-line-indent: 0pt, hanging-indent: " .. HANGING_INDENT .. ", justify: true)",
  "#set text(hyphenate: true)",
}, "\n")

local NOTES_OPEN = table.concat({
  "#block(width: 100%, breakable: true)[",
  "#set par(first-line-indent: 0pt, hanging-indent: " .. HANGING_INDENT .. ", leading: 0.55em, justify: true)",
  "#set text(size: 9.5pt, hyphenate: true)",
}, "\n")

local BLOCK_CLOSE = "]"

local function inject_typst_hanging_indent(blocks, is_review)
  -- (a) Wrap the entries under any references-style or Notes heading in a
  -- block carrying that section's paragraph settings. The heading itself
  -- stays outside the block so it keeps the normal heading style.
  -- (b) Start both sections on their own page, per the LiCS print
  -- convention for full articles. Book reviews (is_review) skip that
  -- forced break: a review's body + Works Cited are typically short
  -- enough to share a page, and forcing a new page pushed the review's
  -- short body onto a mostly empty page 1 with Works Cited alone on
  -- page 2. Natural pagination still splits them cleanly when the
  -- review is long enough to warrant it.
  -- Headings are matched at any level: some articles label Works Cited
  -- as H1, others as H3, depending on the DOCX styling.
  local out = {}
  local i, n = 1, #blocks
  while i <= n do
    local block = blocks[i]
    local opener = nil
    if block.t == "Header" and is_references_heading(block) then
      opener = REFERENCES_OPEN
    elseif block.t == "Header" and is_notes_heading(block) then
      opener = NOTES_OPEN
    end

    if opener then
      if not is_review then
        table.insert(out, pandoc.RawBlock("typst", "#pagebreak()"))
      end
      table.insert(out, block)
      table.insert(out, pandoc.RawBlock("typst", opener))
      i = i + 1
      -- Everything up to the next heading belongs to this section.
      while i <= n and blocks[i].t ~= "Header" do
        table.insert(out, blocks[i])
        i = i + 1
      end
      table.insert(out, pandoc.RawBlock("typst", BLOCK_CLOSE))
    else
      table.insert(out, block)
      i = i + 1
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
    -- No explicit Notes heading — append one (LiCS print convention).
    -- The page break before it and the paragraph settings for the notes
    -- themselves are applied by inject_typst_hanging_indent, which runs
    -- after this and treats an appended Notes heading exactly like an
    -- authored one. Inserting them here as well produced a doubled page
    -- break and a stray `set` inside the wrapper.
    local notes_header = pandoc.Header(
      1,
      pandoc.Inlines({ pandoc.Str("Notes") }),
      pandoc.Attr("notes-section", { "notes-endnotes" })
    )
    -- Notes come before Works Cited (LiCS Checklist C, order of
    -- elements), so the section goes in ahead of the references heading
    -- when there is one, and at the end otherwise.
    local notes_blocks = { notes_header }
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
        table.insert(notes_blocks, pandoc.Para(first_inlines))
        -- Any additional paragraphs in the note.
        for j = 2, #content do
          table.insert(notes_blocks, content[j])
        end
      else
        -- Fallback: treat the whole content as separate blocks.
        for _, b in ipairs(content) do
          table.insert(notes_blocks, b)
        end
      end
    end
    local at = #doc.blocks + 1
    for k, block in ipairs(doc.blocks) do
      if block.t == "Header" and is_references_heading(block) then
        at = k
        break
      end
    end
    for k, b in ipairs(notes_blocks) do
      doc.blocks:insert(at + k - 1, b)
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

-- A Works Cited entry that ends in its publication year ("…Press, 2005.")
-- can leave the year alone on the entry's last line. Bind the year to the
-- word before it with a no-break space.
local NBSP = "\u{00A0}"

local function bind_final_year(para)
  local c = para.content
  local n = #c
  if n >= 3 and c[n].t == "Str" and c[n].text:match("^%d%d%d%d%a?%.$")
      and c[n - 1].t == "Space" then
    c[n - 1] = pandoc.Str(NBSP)
  end
end

local function bind_years_in_references(blocks)
  local in_refs = false
  for _, block in ipairs(blocks) do
    if block.t == "Header" then
      in_refs = is_references_heading(block)
    elseif in_refs and block.t == "Para" then
      bind_final_year(block)
    end
  end
end

-- Long links break only after a slash or before a period. Typst gets each
-- run between break points as an unbreakable box, joined by zero-width
-- spaces; HTML gets <wbr> at the same points.
local function url_segments(url)
  local segs, cur = {}, ""
  for ch in url:gmatch(utf8.charpattern) do
    if ch == "." and cur ~= "" then
      table.insert(segs, cur)
      cur = ch
    else
      cur = cur .. ch
      if ch == "/" then
        table.insert(segs, cur)
        cur = ""
      end
    end
  end
  if cur ~= "" then table.insert(segs, cur) end
  return segs
end

local function typst_string(s)
  return '"' .. s:gsub("\\", "\\\\"):gsub('"', '\\"') .. '"'
end

local function html_escape(s)
  return (s:gsub("&", "&amp;"):gsub("<", "&lt;"):gsub(">", "&gt;"))
end

local function is_url_text(s)
  return s:match("^https?://") or s:match("^www%.") or s:match("^doi%.org/")
end

local function breakable_url(text)
  local parts = {}
  if FORMAT == "typst" then
    for _, seg in ipairs(url_segments(text)) do
      table.insert(parts, "#box(" .. typst_string(seg) .. ")")
    end
    return pandoc.RawInline("typst", table.concat(parts, "#sym.zws"))
  end
  for _, seg in ipairs(url_segments(text)) do
    table.insert(parts, html_escape(seg))
  end
  return pandoc.RawInline("html", table.concat(parts, "<wbr>"))
end

local url_filter = {
  Link = function(el)
    if #el.content == 1 and el.content[1].t == "Str" and is_url_text(el.content[1].text) then
      el.content = { breakable_url(el.content[1].text) }
      return el
    end
  end,
  Str = function(el)
    -- A URL typed as plain text ("www.gao.gov/assets/…") rather than a link.
    if #el.text > 20 and is_url_text(el.text) then
      local url, tail = el.text:match("^(.-)([%.,;:]?)$")
      local out = { breakable_url(url) }
      if tail ~= "" then table.insert(out, pandoc.Str(tail)) end
      return out
    end
  end,
}

function Pandoc(doc)
  doc.meta = split_pipes_in_meta(doc.meta)
  local kind_str = doc.meta.kind and pandoc.utils.stringify(doc.meta.kind) or ""
  local is_review = kind_str:lower() == "review"
  bind_years_in_references(doc.blocks)
  if FORMAT == "typst" or FORMAT:match("^html") then
    doc = doc:walk(url_filter)
  end
  if FORMAT == "typst" then
    doc = collect_typst_endnotes(doc)
    doc.blocks = inject_typst_dropcap(doc.blocks)
    doc.blocks = inject_typst_hanging_indent(doc.blocks, is_review)
    doc.blocks = adapt_typst_tables(doc.blocks)
  elseif FORMAT:match("^html") or FORMAT:match("^epub") then
    doc.blocks = wrap_html_opening_para(doc.blocks)
  end
  return doc
end
