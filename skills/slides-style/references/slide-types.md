# Slide Types

Twelve slide types make up the author's decks. Geometry is in canvas px
(1920 × 1080). "Chrome" means the title (left 144, top 48, 80 px), the dash
(156, 156, 154 × 12) and the slide number (24 px, right edge 1816, top
1000). The template deck holds types 1, 2, 3, 5, 11 and 12; the others are
made from its `content` slide.

---

## 1. Title — template `cover`

No slide number.

- **Left column (x 144-1138)**: the title in two to four lines at 88 px,
  its bottom just above the dash (`bottom:398px`). Either bold a lead
  phrase (`<b>Cosmic Cartography:</b> Photometric Redshifts for …`) or
  colour one keyword `#1973eb` (`… with <span style="color:#1973eb">Error-Aware</span> Machine Learning`),
  never both.
- **Dash** at (156, 698), then the name line at 48 px, top 718: "Biprateep
  Dey |" in Noto Sans and "বিপ্রতীপ দে" in Noto Sans Bengali, side by
  side.
- **Under it, 36 px**: an optional "with …" / "on behalf of the DESI
  Collaboration" line at top 800, then the email at top 856, green and
  underlined.
- **Bottom row (top 948, height 66)**: the four affiliation logos, equal
  32 px gaps, from x 144.
- **Right (x 1170-1816, y 48-898)**: a hero image (survey map, galaxy,
  stream, telescope), its box sized to the image, with "Image courtesy: …"
  right-aligned to 1816 at top 1000. No hero: remove the slot and its
  credit.

A talk to a collaboration with its own template keeps that template's title
background (the DESI decks: full-bleed Mayall photograph, white text) and
this slide's content.

## 2. Acknowledgements — template `acks`

Chrome. "In collaboration with:" at 40 px, top 190. Up to six collaborators
in equal columns across x 72-1848: a circular headshot (208 px, centred in
its column, top 266) above a centred 32 px caption with the **name**, the
role and the **institution** (top 494). Three columns are 592 px wide, with
lefts 72, 664, 1256 and headshots at 264, 856, 1448. "Funded by:" (40 px,
top 770) and the funder logos from x 144 (top 832); the fellowship sentence
as a 24 px credit at top 984.

For a big collaboration, a slide of sponsor logos with "Thanks to the
sponsors, N participating institutions and the members of the DESI
collaboration!" goes at the end instead.

## 3. Statement or question — template `statement`

No chrome. One sentence, 80 px, centred on the canvas in a pinned box (left
180, top 216, 1560 × 648, `display:flex; justify-content:center`); one bold
key word allowed. Used as section breaks and beats: "What if we “learn”
these transformations?", "Cal-PIT is a general-purpose method!",
"Modelling vs Understanding".

## 4. Quote

No chrome. The quotation centred at 56-64 px in curly quotes, "— Name
(year)" on the next line; same pinned box as the statement slide.

## 5. Figure + annotation — template `content`

Chrome. One figure, 35-60 % of the slide, close to the edges; two to five
2-8-word labels around it at 40-48 px; a 3 px black `x-connector` from each
label's edge into the figure; one bold takeaway phrase beside or under it;
the credit line.

The template's layout: figure box left 144, top 202, up to 900 × 780 (size
it to the image); labels and takeaway in a second column at left 1080,
width 740; label at top 290 with its arrow from (1080, 330); takeaway at
top 640.

Other layouts that recur, each on shared lines:

- **Figure full width** (left 144, width 1632) with the takeaway centred
  under it.
- **Figure in the middle** with labels on both sides, left column ending at
  the figure's left edge minus 36, right column starting at its right edge
  plus 36 (a pipeline: image → prism → spectrum).
- **A grid of panels**, equal sizes and gaps, one label centred over each.

## 6. Build sequence

The same slide repeated with one thing added or highlighted each time; the
title and every element already shown keep their exact coordinates. A list
that grows beside one figure ("Low signal-to-noise / + Selection cuts /
+ Missing bands"); a numbered list whose current step is highlighted; a
figure whose panels arrive one by one. Duplicate the slide file, give each
copy a new id, add the next piece.

## 7. Two-panel comparison

Chrome. Two equal halves, left 144 and 984, width 792 each (gap 48). A bold
40 px label centred over each half ("Classical ML (k-NN)" / "Deep Capsule
Network"; "What we have" / "What we want to learn"), the two figures the same
size and top, an arrow between them when one becomes the other. Pros and
cons: two short columns of 3-4 lines each, "Pros:" and "Cons:" as labels.

## 8. Annotated equation

Chrome. The equation at 64-80 px, centred on x 960 in the upper middle:
an outline SVG from `scripts/latex_to_svg.py` for stacked math, or a Latin
Modern Math `<p>` for a linear expression. Under each term a 40 px label
("New distribution (calibrated by construction)", "Learnt regression
function", "Old distribution (uncalibrated)") in equal columns, joined to its
term by a thin `x-connector`; one remark under them ("P.S. This is an
**optimal transport** map").

A chain of steps that an equation factorises (Truth → Noise → Selection →
Missingness → Observed) may be drawn as equal coloured boxes with equal gaps,
their colours repeated on the matching terms of the equation.

## 9. Paper anchor

Chrome. A screenshot of the paper's first page (title, authors, abstract)
filling most of the slide from x 144, the title boxed in red (a pinned
`div`, `border:4px solid #c00000`, no background); two papers stacked when a
method has two. A report excerpt with the key sentence highlighted in yellow
works the same way.

## 10. Code

Chrome. A syntax-coloured screenshot of 5-8 lines of real usage from x 144,
a title such as "calpit Python Package: pip install calpit", and "Read the
Docs | Tutorial" as links under it.

## 11. Summary and closing — template `summary`

Chrome. Title "Summary" or "Summary: <section>". Three or four one-sentence
takeaways as a `<ul>` at 48 px (left 144, top 216), each with a bold key
phrase; "References:" with arXiv ids and the repository, 36 px, top 600;
then, bold 40 px at top 785, the closing formula from the profile and
"Contact: <email>". An optional QR code to the paper on the right, its
right edge at 1816.

A long talk has a "Summary: <section>" slide at the end of each section,
then the final summary.

## 12. Backup — template `extra`

After the summary: the divider ("EXTRA SLIDES", 64 px at left 144, top
194, the dash above it), then ordinary content slides kept for questions;
mark those not meant to be paged through `hidden`.
