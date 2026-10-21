# Slide Types

Twelve slide types make up the author's decks. Each recipe gives the
`slidestyle` call for .pptx and the geometry for Claude Slides (inches × 144
= canvas px; points × 2 = px). "Chrome" means title + dash + slide number.

---

## 1. Title

First slide. No slide number.

- **Left column (x 1.00-7.90 in)**: the title in two to four lines at 44 pt,
  bottom-anchored above the dash. Either bold a lead phrase
  (`**Cosmic Cartography:** Photometric Redshifts for …`) or colour one
  keyword accent blue (`… with ==Error-Aware== Machine Learning`), never
  both.
- **Dash** at (1.083, 4.85), then the name line at 24 pt:
  "Biprateep Dey | বিপ্রতীপ দে".
- **Under it, 18 pt**: an optional "with …" / "on behalf of the DESI
  Collaboration" line, then the email as a link.
- **Bottom row (y 6.50, height 0.62)**: affiliation logos, left to right,
  from the profile's `title_logos`.
- **Right (x 7.55-13.13, y 0.30-6.20)**: a hero image (survey map, galaxy,
  stream, telescope), contained for cut-outs, covered for photographs, with
  "Image courtesy: …" at the bottom right.

```python
slidestyle.title_slide(
    deck,
    "**Cosmic Cartography:** Photometric Redshifts for Sky Surveys",
    subtitle="with Jeff Newman, on behalf of the DESI Collaboration",
    hero=slidestyle.asset("hero/desi-3d-map"),
    hero_alt="DESI 3D map of galaxies",
    hero_credit="Image courtesy: DESI Collaboration",
)
```

A talk to a collaboration with its own template keeps that template's title
background (the DESI decks: full-bleed Mayall photograph, white text) and
this slide's content.

## 2. Acknowledgements

Second slide. Chrome. "In collaboration with:" at 20 pt, then up to six
collaborators across the slide: a circular headshot (diameter up to 1.45 in)
above a centred 16 pt caption with the **name**, the role and the
**institution**. "Funded by:" and the funder logos along the bottom; the
fellowship sentence from the profile as a 10 pt credit.

```python
slidestyle.acknowledgements_slide(
    deck, ["person/alexandros-pratsos", "person/josh-speagle", "person/ting-li"]
)
```

For a big collaboration, a slide of sponsor logos with "Thanks to the
sponsors, N participating institutions and the members of the DESI
collaboration!" goes at the end instead.

## 3. Statement or question

No chrome. One sentence, 36-44 pt, centred on an empty slide; one bold key
word allowed. Used as section breaks and beats: "What if we "learn" these
transformations?", "Cal-PIT is a general-purpose method!", "Modelling vs
Understanding". A subtitle line at 24 pt under it is allowed.

```python
slidestyle.statement_slide(deck, "Why do we need to know galaxy distances?")
```

Claude Slides: one `<p>` pinned at left 180, top 216, width 1560, height
648, `font-size:80px; text-align:center`, the section `display:flex;
align-items:center`.

## 4. Quote

No chrome. The quotation centred at 28-32 pt in curly quotes, "— Name
(year)" under it.

```python
slidestyle.quote_slide(
    deck, "Machine Learning is just glorified curve fitting.", "Judea Pearl"
)
```

## 5. Figure + annotation (the workhorse)

Chrome. One figure, 35-60 % of the slide, close to the edges; two to five
2-8-word labels around it at 20-24 pt; thin black arrows from each label
into the figure; one bold takeaway phrase beside or under it; the credit
line.

```python
slide = slidestyle.content_slide(deck, "Photo-z Prediction Performance")
slidestyle.figure(
    slide,
    "figs/one_to_one.png",
    (0.6, 1.4, 6.6, 5.5),
    alt="Predicted against true redshift",
    align="left",
)
label = slidestyle.text(
    slide,
    "Ideal photo-z’s follow\nthe identity line",
    7.4,
    2.0,
    4.6,
    size=slidestyle.LABEL_SIZE,
)
pointer = slidestyle.arrow(slide, (7.45, 2.45), (5.2, 3.2))
slidestyle.text(
    slide, "Scatter is **3× smaller** than classical k-NN", 7.4, 4.4, 5.2
)
slidestyle.credit(
    slide,
    "Dey et al. 2022, [arXiv:2112.03939](https://arxiv.org/abs/2112.03939)",
)
```

Layouts that recur: figure left with labels right (above); figure full
width with the takeaway under it; figure in the middle with labels on both
sides (a pipeline: image → prism → spectrum); a grid of panels with one
label over each.

## 6. Build sequence

The same slide repeated with one thing added or highlighted each time; the
title does not change. A list that grows beside one figure ("Low
signal-to-noise / + Selection cuts / + Missing bands"); a numbered list
whose current step is highlighted; a figure whose panels arrive one by one.

```python
steps = ["Low signal-to-noise", "+ Selection cuts", "+ Missing bands"]
for count in range(1, len(steps) + 1):
    slide = slidestyle.content_slide(deck, "The Boons and Banes of Survey Data")
    slidestyle.figure(slide, "figs/map.png", (4.6, 1.5, 8.3, 5.3), alt="…")
    slidestyle.text(slide, "\n".join(steps[:count]), 0.8, 2.2, 3.7, size=20)
```

For two or three pieces arriving on one slide, `appear(slide, [a, [b, c]])`
instead.

## 7. Two-panel comparison

Chrome. Left and right halves (`LEFT_HALF`, `RIGHT_HALF`), a bold 20 pt
label centred over each ("Classical ML (k-NN)" / "Deep Capsule Network";
"What we have" / "What we want to learn"), the figures the same size, a
bold arrow between them when one becomes the other. Pros and cons: two
short columns of 3-4 lines each, "Pros:" and "Cons:" as labels.

## 8. Annotated equation

Chrome. The equation at 32-40 pt in the upper middle; under each term a
20 pt label ("New distribution (calibrated by construction)", "Learnt
regression function", "Old distribution (uncalibrated)"), joined to the term
by a thin line; one remark under it ("P.S. This is an **optimal transport**
map").

```python
slidestyle.equation(
    slide,
    r"\widetilde{F}(z\mid\mathbf{x}) := \hat{r}^{\hat f}(\hat F(z\mid\mathbf{x}); \mathbf{x})",
    3.2,
    2.3,
    size=40,
)
slidestyle.text(
    slide, "Learnt regression\nfunction", 5.0, 4.3, 3.4, size=20, align="center"
)
slidestyle.line(slide, (6.7, 4.3), (6.5, 3.45))
```

A chain of steps that an equation factorises (Truth → Noise → Selection →
Missingness → Observed) may be drawn as coloured boxes whose colours are
repeated on the matching terms of the equation.

## 9. Paper anchor

Chrome. A screenshot of the paper's first page (title, authors, abstract)
filling most of the slide, the title boxed in red with `outline()`; two
papers stacked when a method has two. A report excerpt with the key
sentence highlighted in yellow works the same way.

## 10. Code

Chrome. A syntax-coloured screenshot of 5-8 lines of real usage, a title
such as "calpit Python Package: pip install calpit", and "Read the Docs |
Tutorial" as links under it.

## 11. Summary and closing

Chrome. Title "Summary" or "Summary: <section>". Three or four one-sentence
takeaways as one-level bullets with a bold key phrase each; "References:"
with arXiv ids and the repository, as links; then, in bold, the closing
formula from the profile and "Contact: <email>". An optional QR code to the
paper on the right.

```python
slidestyle.summary_slide(
    deck,
    [
        "Photo-z’s derived from **resolved images** are more accurate.",
        "We can **test and produce** meaningful photo-z distributions.",
    ],
    references=[
        "Dey et al. 2022 ([arXiv:2205.14568](https://arxiv.org/abs/2205.14568))"
    ],
    qr_url="https://arxiv.org/abs/2606.09576",
    qr_label="arXiv:2606.09576",
)
```

A long talk has a "Summary: <section>" slide at the end of each section,
then the final summary.

## 12. Backup

After the summary: a divider ("EXTRA SLIDES", the dash above it), then
ordinary content slides kept for questions. Hide the ones not meant to be
paged through (`hide(slide)`).
