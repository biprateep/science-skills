# The Style in Claude Slides

Claude Slides decks are HTML in a closed format: one `<section>` per slide
on a 1920 × 1080 canvas, every style inline. **The type's own instructions
govern how the deck is written, uploaded and saved, and whether to verify
it.** This page only says what to write so that the deck looks like the
author's. Where the type's design notes disagree (toned whites, two
typefaces, wide margins, icons and cards), this page wins.

Conversion: 1 in = 144 px, 1 pt = 2 px.

## Starting a Deck from the Template

Every new deck is a copy of the author's template deck, never a blank one.
`assets/profile.json` holds its link (`claude_slides_template.url`) and the
ids of its six assets (`claude_slides_template.assets`: five logos and the
Latin Modern Math font). Its slides, in order:

| Id | Slide | Placeholders to fill |
|---|---|---|
| `cover` | title slide: title, dash, name line, email, four affiliation logos | `[Lead Phrase]`, `[Talk Title …]`, the "with …" line, the hero `<img>` (no `src`), its credit |
| `acks` | acknowledgements: three headshot slots, Schmidt Sciences, fellowship credit | each `[Name]`, `[Role]`, `[Institution]` and headshot `<img>` |
| `statement` | one centred sentence | the sentence |
| `content` | the workhorse: title, dash, figure slot, a label with an arrow, a takeaway, credit, slide number | all of it |
| `summary` | three takeaways, references, the closing formula | takeaways and references |
| `extra` | the backup divider | none |

1. **Create the deck** from the Slides type: the usual quickstart for a
   slides intent first, with `design_systems: false` (the template is the
   look), then `publish` with the type's `type_url`, the talk's `title`
   and `auto_open: "after_first_write"`. The result's `url` is the new
   deck; follow the type's instructions it returns for every later call.
2. **Copy the template's assets** server-side, in one call:
   `{action: "publish", url: <new deck>, asset: true, from_url: <template
   url>, asset_ids: [the six ids]}`. The reply pairs each template id with
   its copy's new `/_blob/<id>` url.
3. **Read the template's files** in one call: `{action: "read", url:
   <template url>, paths: ["project/deck.json", "project/slides/cover.html",
   …]}`, one path per id in its `order`. If the template cannot be read,
   use the copy in `assets/claude-slides-template/` (same files, same
   asset ids).
4. **Write the new deck's files** under one fresh folder in the scratchpad,
   with the file-writing tool:
   - `project/deck.json`: the template's, with the talk's `title`,
     `createdOnFiles.at` set to now, the talk's `order` and `sections`, and
     the `latin-modern-math` face's `src` set to the font copy's new url.
   - Each slide file: the template slide with every template
     `/_blob/<id>` replaced by its copy's url and its placeholders filled.
     Duplicate `content` (and `statement`) for as many slides as the talk
     needs, each with a new id (`photoz-results`, `why-distances`) that is
     both its file name and its `section` id. Renumber the literal slide
     numbers in deck order.
   - Publish `project/deck.json` and the cover first, then the rest, as the
     type's instructions say.
5. **Leave nothing bracketed.** Every `[…]` is replaced, or its element
   removed when the talk has no use for it (no hero image: remove the
   `<img>` and its credit). An `<img>` with no `src` gets an uploaded
   figure, headshot or hero image (`hero/…` and `person/…` files from the
   local assets folder, `references/profile.md`). Name any placeholder you
   could not fill in the reply.

**Changing the template itself**: edit the template deck (in its page, or
through the type's revising procedure on its link), then copy its files
into `assets/claude-slides-template/` and update the asset ids in
`assets/profile.json` if its assets changed, so the backup stays the same
deck.

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
  <p style="position:absolute; left:144px; top:1000px; width:1200px;
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
| Credit, citation, slide number | 12 | 24 |

## Content

- **Figures**: `<img>` of the uploaded PNG, `object-fit:contain`, pinned,
  covering a third to a half of the canvas, as close as 48 px to the edges.
  Give the box the image's aspect ratio (width ÷ height of the PNG), so the
  picture fills it and its edges can be aligned. `alt` says what the
  figure shows.
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

Duplicated slides: copy the slide, add or highlight one thing, keep the
title and every element already shown at its exact coordinates. For one or two items arriving on a slide,
`data-build-in="fade 1"` on those pinned elements (the format has no
Appear; fade is the nearest). No `data-transition`.

## The Alignment Pass

When the deck is written, run `scripts/check_deck.py` on the folder that
holds its `project/` files, fix what it reports by editing the values it
names, republish the changed slides, and run it again (SKILL.md,
"Alignment"). It reads only those local files; if the deck was edited in its
page meanwhile, read the changed slides from the deck first.

Slide-type recipes, with their geometry, are in `slide-types.md`.
