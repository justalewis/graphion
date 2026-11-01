# Figures

Images with captions and cross-references are handled by a Lua filter that runs before Pandoc's main conversion.

## Inserting a figure

In the article body:

```markdown
![A network diagram of the system.](assets/network.svg){#fig:network width=80%}
```

Breakdown:

- `![...]` — alt text (always include this for accessibility and tagged PDF compliance).
- `(assets/network.svg)` — path to the image file, relative to the article directory.
- `{#fig:network ...}` — Pandoc attribute syntax. `#fig:network` is the identifier; the `fig:` prefix tells our filter to auto-number it. Width as a percentage is preserved.

On render, the figure becomes:

> **Figure 1: A network diagram of the system.**
> (rendered image at 80% width)

## Referencing a figure

Anywhere in the body:

```markdown
See @fig:network for the architecture overview. The data flow in
[@fig:network] illustrates how requests fan out.
```

Both forms — `@fig:network` and `[@fig:network]` — resolve to `Figure 1` (or whatever the number ends up being). Forward references work; the filter does a first pass to collect every `fig:` identifier, then a second pass to rewrite.

If you reference a label that has no matching image, the output shows `Figure ?`. Run lint to catch this.

## Image files

Drop image files into the article's `assets/` directory:

```
content/journals/<slug>/issues/<issue>/articles/<article>/
  assets/
    network.svg
    flowchart.png
    photo-of-classroom.jpg
```

Then reference them with the relative path: `![Caption](assets/network.svg)`. SVG is preferred — it scales without resolution loss in both HTML and PDF. PNG is fine for photos and complex visuals.

For images extracted from a docx upload, the cleanup pipeline drops them into `assets/` automatically with names like `image1.png`, `image2.png`. You can rename for readability.

## Captions

Captions can be Markdown:

```markdown
![A scatter plot of *engagement* over time, from @tacheva2023ai.](assets/plot.png){#fig:engagement}
```

Inline emphasis, citations, and links all work inside captions.

## List of Figures

If you want a list of figures to appear at the end of the article (useful for image-heavy work), set this in the YAML front matter:

```yaml
figures-list: true
```

The filter appends a "List of Figures" section listing each figure by number and caption.

## Equations

An equation needs a spoken description for the same reason a figure does, and
the tagged PDF enforces it: Typst refuses an equation it cannot read aloud, so
one undescribed formula costs the galley its PDF/UA-1 conformance.

Most of the time nothing is required of you. Simple expressions are read from
the expression itself, so `$p < .05$` goes into the galley as "p is less than
.05" and `$a^2 + b^2 = c^2$` as "a squared plus b squared equals c squared".
Anything that reads more than one way is declined rather than guessed at,
because a formula read half right is worse than one a reader is told is
undescribed: a summation, an integral, a nested fraction, or a tilde (which is
"is similar to" in geometry and "is distributed as" in statistics) all come
through as "Undescribed equation".

Write those yourself, in the article's front matter, keyed by the expression as
it appears in the body:

```yaml
math-alt:
  '\sum_{i=1}^{n} x_i': the sum of x sub i, from i equals 1 to n
  'a^2 + b^2 = c^2': the Pythagorean theorem
```

Single quotes around the key, where a backslash means a backslash. Double
quotes need every backslash doubled, and getting that wrong stops the render
with a YAML error. Spacing inside the key does not matter. A description you
write always wins, so it is also how you replace a reading you do not like.

**Run lint** reports how many equations are still undescribed and names them.
The galley is conformant either way, which is why it is a warning: what is at
stake is whether a reader hears the formula or hears that there is one.

The HTML and EPUB galleys need none of this. They carry real MathML, which a
screen reader navigates on its own.

## What lint checks

Run **Run lint** on the article to verify:

- **Alt text** — every image has non-empty alt text.
- **Equation descriptions** — every equation is read aloud rather than placeholdered.
- **Images of text** — the figures listed in `images-of-text` are reported, since a description satisfies WCAG 1.1.1 and leaves 1.4.5 where it was.
- **Figure coverage** — an article that refers to figures it does not contain, which the alt text check cannot see and reads as a pass.
- **Figure references** — every `@fig:X` points at a real `{#fig:X}` image; no figure labels are duplicated; figures defined but never referenced are flagged.

Alt text is a failure and the rest are warnings, so you can ship intentional
decorative images and intentionally-unreferenced figures. But fix what you can;
accessibility tooling and indexers care.

## Limits

- **No cross-reference to tables or equations yet.** The filter handles `fig:` only. If you want table numbering, that's a small extension; the same pattern applies.
- **No automatic image sizing** beyond what you specify in the attribute. The tool doesn't compress, downscale, or pre-process images. Drop in images at the resolution you want them rendered.
- **No automatic figure placement.** Figures appear where you put them in the source. Typst will float them only minimally; for complex placement (top/bottom of page, full-width breakouts), edit the Typst template.
