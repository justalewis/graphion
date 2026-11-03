-- Put a figure's description where a reader can reach it.
--
-- A figure that has been through `pair_figure_captions` keeps the caption
-- people see in the bracket and the description in a `fig-alt` attribute.
-- Nothing downstream read it. Pandoc 3.11 emits `data-fig-alt` in HTML,
-- which is a data attribute no assistive technology looks at, and its Typst
-- writer drops the attribute entirely, so every galley published the
-- caption as the alt text and the description reached nobody:
--
--   <img src="fig.png" data-fig-alt="A slide headed Discovering Open..."
--        alt="Figure 1. An example of an ideal attribution..." />
--   #figure(image("fig.png", alt: "Figure 1. An example of an ideal..."))
--
-- An image's inlines are what every writer turns into alt text, and a
-- Figure's own caption is what becomes the `<figcaption>` or the printed
-- caption, so moving the description into the image leaves the caption
-- exactly where it was. The two then say different things, which is the
-- whole point of keeping them in different slots: a caption says what a
-- figure is called and alt text says what is in it.
--
-- App level rather than per journal, by the test `math-alt.lua` already
-- meets: how a caption is set is a journal's design, and whether a figure
-- can be read aloud is not. `new_journal.py` clones a bundle, so anything
-- a bundle holds is something a journal can also drop.
--
-- Runs after the journal's figures filter, which prefixes "Figure N." to a
-- labelled image's caption. On an inline image that caption is also the alt
-- text, so running first would mean writing the description and then having
-- the label pasted in front of it.

function Image(el)
  if el.attributes == nil or el.attributes["fig-alt"] == nil then
    return nil
  end
  local alt = pandoc.utils.stringify(el.attributes["fig-alt"])
  -- Dropped either way, so no writer emits it as a data attribute saying
  -- the same thing a second time, or saying nothing at all.
  el.attributes["fig-alt"] = nil
  if alt:match("^%s*$") then
    -- An attribute with nothing in it has nothing to move, and an alt text
    -- emptied here would cost the galley its conformance: Typst refuses an
    -- image that carries none. The bracket stays as it was.
    return el
  end
  el.caption = pandoc.Inlines({ pandoc.Str(alt) })
  return el
end
