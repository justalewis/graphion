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

## What lint checks

Run **Run lint** on the article to verify:

- **Alt text** — every image has non-empty alt text.
- **Figure references** — every `@fig:X` points at a real `{#fig:X}` image; no figure labels are duplicated; figures defined but never referenced are flagged.

Both are warnings rather than failures, so you can ship intentional decorative images and intentionally-unreferenced figures. But fix what you can — accessibility tooling and indexers care.

## Limits

- **No cross-reference to tables or equations yet.** The filter handles `fig:` only. If you want table numbering, that's a small extension; the same pattern applies.
- **No automatic image sizing** beyond what you specify in the attribute. The tool doesn't compress, downscale, or pre-process images. Drop in images at the resolution you want them rendered.
- **No automatic figure placement.** Figures appear where you put them in the source. Typst will float them only minimally; for complex placement (top/bottom of page, full-width breakouts), edit the Typst template.
