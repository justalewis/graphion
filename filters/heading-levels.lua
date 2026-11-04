-- Make a galley's heading outline start at one and never skip a level.
--
-- PDF/UA asks two things of a heading outline that a book's own levels do
-- not promise, and Typst validates rather than declares, so either one
-- aborts the compile and `_compile_typst` ships the galley unconstrained:
--
--   PDF/UA-1 error: skipped from heading level 1 to 3
--   PDF/UA-1 error: the first heading must be of level 1
--
-- Both turned up the moment ingest started reading structure trees, and
-- both are the book being faithfully reproduced. `on-the-other-hand` sets
-- its sections in `Header_A` and its five steps in `Header_C`, with no
-- `Header_B` between them, so the chapter really does go from a first
-- level to a third. And a split article renders two documents from one
-- body: the teacher galley's intermediate drops the `Teacher Resources`
-- heading, which the template prints as its title, so that galley's first
-- heading is whatever sat under it, a level 2.
--
-- Which is why this is a filter and not a fix to `blocks_to_markdown`.
-- The constraint is a property of the document being rendered, `article.md`
-- is one body that renders as two documents, and the canonical copy keeps
-- the levels the book states. Each galley is normalised on its own way out.
--
-- The transform is a stack of the levels seen, and the depth written is the
-- stack's height. A heading deeper than the one before it goes exactly one
-- deeper; a heading at or above it pops back to its own place. So nesting
-- is preserved and the gaps close:
--
--   #  ###  ##  ###      ->   1  2  2  3
--   ##  ##                ->   1  1
--
-- Ranking the distinct levels instead would not do: a chapter can hold
-- every level and still skip one positionally, which is `#` then `###`
-- with the `##` somewhere else in the document.
--
-- App level rather than per journal, by the test `math-alt.lua` and
-- `fig-alt.lua` already meet: how deep a book sets its sections is a
-- journal's design, and whether a galley's outline can be navigated is
-- not. `new_journal.py` clones a bundle, so anything a bundle holds is
-- something a journal can also drop.

local stack = {}

local function depth_for(level)
  -- Pop every level at or deeper than this one: they are siblings or
  -- children of something this heading now closes.
  while #stack > 0 and stack[#stack] >= level do
    table.remove(stack)
  end
  table.insert(stack, level)
  return #stack
end

function Pandoc(doc)
  stack = {}
  doc.blocks = doc.blocks:walk {
    Header = function(h)
      local depth = depth_for(h.level)
      if depth ~= h.level then
        h.level = depth
      end
      return h
    end,
  }
  return doc
end
