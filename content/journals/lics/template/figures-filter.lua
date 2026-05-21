-- Figures filter — auto-numbering + cross-references.
--
-- Author convention (compatible with pandoc-crossref):
--
--   ![Caption text.](path/to/image.png){#fig:label width=80%}
--
-- Becomes "Figure N: Caption text." auto-numbered in document order.
-- `@fig:label` or `[@fig:label]` elsewhere in the body resolves to
-- "Figure N". Forward references work because we do two explicit
-- walk passes inside Pandoc(): first collect labels, then rewrite.
--
-- Set `figures-list: true` in YAML to append a "List of Figures"
-- section at the end of the document.

local figures = {}        -- identifier -> integer
local figure_records = {} -- ordered: { {label, number, caption_inlines} }


local function register(identifier, caption_inlines)
  if not figures[identifier] then
    local n = #figure_records + 1
    figures[identifier] = n
    table.insert(figure_records, {
      label = identifier,
      number = n,
      caption = caption_inlines,
    })
  end
end


local function caption_inlines_from_figure(el)
  -- Pandoc 3+ Figure has Caption{short, long}; long is a list of blocks.
  local out = pandoc.List({})
  if el.caption and el.caption.long then
    for _, blk in ipairs(el.caption.long) do
      if blk.t == "Plain" or blk.t == "Para" then
        for _, inl in ipairs(blk.content or {}) do
          out:insert(inl)
        end
      end
    end
  end
  return out
end


local function prefix_inlines(number, original_inlines)
  local out = pandoc.List({
    pandoc.Str("Figure"),
    pandoc.Space(),
    pandoc.Str(tostring(number) .. ":"),
    pandoc.Space(),
  })
  for _, inline in ipairs(original_inlines or {}) do
    out:insert(inline)
  end
  return out
end


local collect_filter = {
  Image = function(el)
    if el.identifier and el.identifier:match("^fig:") then
      register(el.identifier, el.caption)
    end
  end,
  Figure = function(el)
    if el.identifier and el.identifier:match("^fig:") then
      register(el.identifier, caption_inlines_from_figure(el))
    end
  end,
}


local rewrite_filter = {
  Image = function(el)
    if el.identifier and el.identifier:match("^fig:") and figures[el.identifier] then
      el.caption = prefix_inlines(figures[el.identifier], el.caption)
      return el
    end
  end,
  Figure = function(el)
    if el.identifier and el.identifier:match("^fig:") and figures[el.identifier] then
      local n = figures[el.identifier]
      if el.caption and el.caption.long then
        local new_blocks = pandoc.List({})
        local prepended = false
        for _, blk in ipairs(el.caption.long) do
          if not prepended and (blk.t == "Plain" or blk.t == "Para") then
            blk.content = prefix_inlines(n, blk.content)
            prepended = true
          end
          new_blocks:insert(blk)
        end
        if not prepended then
          new_blocks:insert(pandoc.Plain(prefix_inlines(n, pandoc.List({}))))
        end
        el.caption = pandoc.Caption(new_blocks, el.caption.short)
      end
      return el
    end
  end,
  Cite = function(el)
    for _, c in ipairs(el.citations or {}) do
      if c.id and c.id:match("^fig:") then
        local n = figures[c.id]
        if n then return pandoc.Str("Figure " .. tostring(n)) end
        return pandoc.Str("Figure ?")
      end
    end
  end,
}


function Pandoc(doc)
  -- Pass 1: collect labels into the figures map (preserves doc order)
  doc.blocks:walk(collect_filter)

  -- Pass 2: rewrite captions and resolve cross-references
  doc.blocks = doc.blocks:walk(rewrite_filter)

  -- Optionally append a "List of Figures" block
  if doc.meta and doc.meta["figures-list"] and #figure_records > 0 then
    local items = pandoc.List({})
    for _, r in ipairs(figure_records) do
      local entry = pandoc.List({
        pandoc.Str("Figure"),
        pandoc.Space(),
        pandoc.Str(tostring(r.number) .. "."),
        pandoc.Space(),
      })
      for _, inl in ipairs(r.caption or {}) do entry:insert(inl) end
      items:insert({pandoc.Plain(entry)})
    end
    table.insert(doc.blocks, pandoc.Header(
      2, pandoc.Inlines({pandoc.Str("List of Figures")}),
      pandoc.Attr("list-of-figures")
    ))
    table.insert(doc.blocks, pandoc.OrderedList(items))
  end

  return doc
end
