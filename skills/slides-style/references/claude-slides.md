# The Style in Claude Slides

Claude Slides decks are HTML in a closed format: one `<section>` per slide
on a 1920 × 1080 canvas, every style inline. **The type's own instructions
govern how the deck is written, uploaded and saved, and whether to verify
it.** This page only says what to write so that the deck looks like the
author's. Where the type's design notes disagree (toned whites, two
typefaces, wide margins, icons and cards), this page wins.

Conversion: 1 in = 144 px, 1 pt = 2 px.

## Faces

Three families, declared once in `project/deck.json` `faces` (or the
`<head>` of a `deck.html`):

```json
"faces": {
  "noto-sans": {"family": "Noto Sans",
    "href": "https://fonts.googleapis.com/css2?family=Noto+Sans:ital,wght@0,400;0,700;1,400&display=swap"},
  "noto-sans-bengali": {"family": "Noto Sans Bengali",
    "href": "https://fonts.googleapis.com/css2?family=Noto+Sans+Bengali:wght@400;700&display=swap"},
  "latin-modern-math": {"family": "Latin Modern Math", "src": "/_blob/<uploaded id>"}
}
```

Latin Modern Math is not on Google Fonts: upload TeX Live's
`latinmodern-math.otf` (`kpsewhich latinmodern-math.otf`) as an asset and
use the `/_blob/` url it returns. Every text element names
`font-family:'Noto Sans', Arial, sans-serif`; the Bengali run sits in its own
block with `'Noto Sans Bengali'`.

## The Chrome

Every content slide:

```html
<section id="results" style="background:#ffffff">
  <h2 style="position:absolute; left:144px; top:48px; width:1632px;
      font-family:'Noto Sans', Arial, sans-serif; font-size:80px;
      font-weight:400; line-height:1.1; color:#000000">Photo-z Prediction Performance</h2>
  <div style="position:absolute; left:156px; top:156px; width:154px;
      height:12px; background:#1973eb"></div>
  <!-- figure, labels, arrows, takeaway -->
  <p style="position:absolute; left:130px; top:1000px; width:1200px;
      font-family:'Noto Sans', Arial, sans-serif; font-size:24px;
      color:#000000">Image courtesy: Sloan Digital Sky Survey</p>
  <p style="position:absolute; left:1702px; top:1000px; width:114px;
      font-family:'Noto Sans', Arial, sans-serif; font-size:24px;
      text-align:right; color:#000000">7</p>
</section>
```

- **Background** `#ffffff`, text `#000000`: not the toned colours the type
  suggests.
- **The slide number is literal text** (the format has no number field):
  renumber when slides are added, removed or reordered. Title, statement,
  quote and divider slides have none.
- **No `<aside>`**: no speaker notes unless asked.

## Sizes

| Role | pt | px |
|---|---|---|
| Deck title | 44 | 88 |
| Content title (`h2`, weight 400) | 40 | 80 |
| Statement sentence | 40 | 80 |
| Takeaway, summary item, main label | 24 | 48 |
| Crowded label | 20 | 40 |
| Smallest label | 18 | 36 |
| Headshot caption | 16 | 32 |
| Credit, citation, slide number | 12 | 24 (the type's floor; .pptx uses 10 pt) |

## Content

- **Figures**: `<img>` of the uploaded PNG, `object-fit:contain`, pinned,
  covering a third to a half of the canvas, as close as 48 px to the edges.
  `alt` says what the figure shows.
- **Labels**: pinned `<p>`s with a `width` (so they wrap), 40-48 px,
  `<b>` for the key phrase, `<i>` for a defined term,
  `<span style="color:#c00000">` for the red warning.
- **Arrows**: `<x-connector x1 y1 x2 y2 head="end" style="color:#000000;
  border-width:3px">` from the label into the figure.
- **Links**: `<a href="https://arxiv.org/abs/…">` inside
  `<span style="color:#1ac16e">`.
- **Boxes that point** (a paper's title): a pinned `<div>` with
  `border:4px solid #c00000` and no background.
- **Headshots**: `<img>` with `border-radius:50%` on a square box.
- **Lists** (summary and agenda only): one `<ul>` of plain `<li>`s.
- **No** `<x-icon>`, cards, painted tiles, shadows, gradients or tables
  (a table is an image).

## Equations

The format has no math markup and runs no scripts, so:

- **Linear expressions** (`p(x | θ)`, `𝒩(x̂ | x, Σ)`) are Unicode math
  in their own `<p>` with `font-family:'Latin Modern Math', 'Cambria Math',
  serif` (a `<span>` cannot change font). Inline in a sentence, write the
  variable in `<i>` in Noto Sans ("coverage probability <i>γ</i>").
- **Stacked math** (fractions, integrals with limits, sums, matrices) is an
  outline SVG:

  ```bash
  python <skill-dir>/scripts/latex_to_svg.py '\int_{-\infty}^{y} \hat{f}(y^\prime \mid \mathbf{x})\, dy^\prime' pit.svg --size 32
  ```

  It prints the width and height in canvas pixels at that size. Upload the
  file and place it as `<img src="/_blob/<id>" alt="<the LaTeX>"
  style="position:absolute; left; top; width; height">`.
- Annotate terms as on a figure: labels under them, thin connectors up to
  each term.

## Builds

Duplicated slides, as in .pptx: copy the slide, add or highlight one thing,
keep the title. For one or two items arriving on a slide,
`data-build-in="fade 1"` on those pinned elements (the format has no
Appear; fade is the nearest). No `data-transition`.

## Slide Types in Brief

The recipes in `slide-types.md` translate directly. Inches to px:

| Slide | Geometry (px) |
|---|---|
| Title | title `h1` 88 px at left 144, top 115, width 994, bottom-aligned above the dash at (156, 698); name line 48 px at top 718; email 36 px at top 800; logos height 90 at top 936; hero image right of x 1088 |
| Statement | one `<p>` 80 px, centred, left 180, top 216, width 1560, height 648 |
| Figure + labels | figure left 86-1037, top 202-994; labels from x 1066 |
| Two-panel | halves at left 58 and 976, width 886, top 202 |
| Summary | `<ul>` 48 px at left 144, top 216, width 1632; closing block bold 40 px at top 785 |
| Divider | dash at (156, 156); "EXTRA SLIDES" 64 px at left 144, top 194 |
