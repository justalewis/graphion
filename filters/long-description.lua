-- Put a figure's long description where a reader can reach it.
--
-- Alt text says what a figure is. A flowchart, a whiteboard collage or a
-- data plot needs somebody to say what it shows and in what order a
-- listener needs it, and that is prose rather than a field: it will not fit
-- an `alt` attribute and it should not, because an alt read aloud has no
-- structure and no way back. §3.8 of `docs/accessibility-service.md` named
-- the gap and there was nowhere to put one.
--
-- The prose is kept by hand in the article's `long-descriptions` front
-- matter, keyed by the figure's asset name, which is what an editor has in
-- front of them. Pandoc hands that to a filter as a table of Blocks, so
-- nothing has to be encoded through a sentinel the way `math-alt.lua` does:
-- that filter hex encodes because the TeX to Typst translation is Pandoc's
-- and must not be done twice, and there is no translation here.
--
-- It is emitted visibly, which is the decision worth stating. A description
-- hidden from sighted readers is a description nobody proofreads, and it
-- rots; one on the page is read, corrected and kept. HTML gets a
-- `<details>`, so it is there without taking over the page, with
-- `aria-describedby` tying it to the image for a reader who meets the
-- figure first. Every other writer gets a plain labelled paragraph, because
-- Typst has no disclosure widget and a PDF reader has no way to open one.
--
-- App level by the test `math-alt.lua` and `fig-alt.lua` already meet:
-- whether a figure carrying an argument can be understood without seeing it
-- is not a journal's design. `new_journal.py` clones a bundle, so anything
-- a bundle holds is something a journal can also drop.

local descriptions = {}
local count = 0

local function basename(path)
  return (path or ""):gsub("^.*[/\\]", "")
end

local function wanted(src)
  return descriptions[basename(src)]
end

-- The label a reader meets. Kept here rather than in a template because
-- both writers need the same words and a per journal copy is a copy that
-- does not travel.
local LEAD = "Description of the figure above: "

local function described_blocks(blocks, id)
  if FORMAT:match("html") then
    local out = {pandoc.RawBlock("html",
      '<details class="long-description" id="' .. id .. '">' ..
      '<summary>Full description of this figure</summary>')}
    for _, block in ipairs(blocks) do
      table.insert(out, block)
    end
    table.insert(out, pandoc.RawBlock("html", "</details>"))
    return out
  end
  -- One paragraph, led by a label, so the PDF says what it is.
  local inlines = pandoc.List({pandoc.Strong(pandoc.Str(LEAD))})
  for _, block in ipairs(blocks) do
    if block.content then
      inlines:extend(block.content)
      inlines:insert(pandoc.Space())
    end
  end
  return {pandoc.Para(inlines)}
end

function Meta(meta)
  local held = meta["long-descriptions"]
  if held then
    for key, value in pairs(held) do
      local name = basename(tostring(key))
      if name ~= "" then
        descriptions[name] = pandoc.utils.blocks_to_inlines
          and (pandoc.utils.type(value) == "Blocks" and value
               or pandoc.Blocks({pandoc.Para(value)}))
          or value
      end
    end
  end
  -- The map is not written back: it is instruction to this filter and not
  -- content, and leaving it in the metadata puts it in the EPUB package
  -- document and the JATS header for nothing.
  meta["long-descriptions"] = nil
  return meta
end

function Pandoc(doc)
  if next(descriptions) == nil then
    return doc
  end

  local out = pandoc.List({})
  -- `doc.blocks`, never `doc`: a filter that walks the whole document
  -- reaches the metadata too, which is how soft break points for long URLs
  -- once went through a licence href.
  for _, block in ipairs(doc.blocks) do
    local found = nil
    local tagged = pandoc.walk_block(block, {
      Image = function(img)
        local blocks = wanted(img.src)
        if not blocks or found then
          return nil
        end
        count = count + 1
        found = {blocks = blocks, id = "longdesc-" .. count}
        img.attributes["aria-describedby"] = found.id
        return img
      end,
    })
    out:insert(found and tagged or block)
    if found then
      for _, extra in ipairs(described_blocks(found.blocks, found.id)) do
        out:insert(extra)
      end
    end
  end
  doc.blocks = out
  return doc
end

-- Meta runs before Pandoc in one filter file only if they are ordered, so
-- the two are returned explicitly: the descriptions have to be read before
-- the blocks are walked.
return {{Meta = Meta}, {Pandoc = Pandoc}}
