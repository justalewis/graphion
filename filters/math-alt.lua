-- Math alt text; the spoken equivalent PDF/UA-1 wants for a formula.
--
-- Typst refuses a `math.equation` carrying no `alt`, and it validates the
-- standard rather than declaring it, so one undescribed equation sends
-- `conversion._compile_typst` down its fallback path and the galley ships
-- with no conformance identifier. Pandoc's Typst writer emits a bare
-- `$...$`, which is exactly that, and nothing reported it: an equation is
-- not an image, so `lint.check_alt_text` never saw one.
--
-- The `alt` goes on by wrapping each equation in a content block that sets
-- it, which leaves Pandoc to write the math. The TeX to Typst translation
-- (`\frac{a}{b}` to `frac(a, b)`, `\bar{x}` to `macron(x)`) is Pandoc's
-- work, and a second copy of it here would be a worse one.
--
-- What the equation sounds like is decided in Python, in `math_alt.py`,
-- because `lint.check_math_alt_text` reports the same descriptions this
-- writes and two copies of that judgement would drift apart. So the filter
-- emits a sentinel holding the expression and `conversion._fill_math_alt`
-- substitutes the description for it, the way the template's author and
-- keyword sentinels are filled. The expression is hex encoded, because the
-- sentinel has to survive a Typst string literal and a formula is mostly
-- backslashes and quotation marks.
--
-- A sentinel left unsubstituted is a bug, and a loud one: it reaches the
-- page as the text of the alt. That is the right way round, since the
-- quiet failure is the one this file exists to end.

local SENTINEL_OPEN = "GRAPHION-MATH-ALT-"
local SENTINEL_CLOSE = "-END"


local function hex(s)
  return (s:gsub(".", function(c)
    return string.format("%02x", string.byte(c))
  end))
end


function Math(el)
  if FORMAT ~= "typst" then
    return nil
  end
  local sentinel = SENTINEL_OPEN .. hex(el.text) .. SENTINEL_CLOSE
  return pandoc.Inlines({
    pandoc.RawInline(
      "typst",
      '#[#set math.equation(alt: "' .. sentinel .. '"); '
    ),
    el,
    pandoc.RawInline("typst", "]"),
  })
end
