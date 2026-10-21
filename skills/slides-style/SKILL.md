---
name: slides-style
description: >-
  Enforce the author's presentation style on every slide deck: the figure is
  the slide, text only annotates it. 16:9 white slides; title top-left in
  Title Case at 40 pt with a short blue dash under it and a small slide
  number; no bullets outside the summary; 18-28 pt labels with a bold key
  phrase and thin black arrows into the figure; 8-11 pt image credits and
  citations; native editable equations; builds as duplicated slides; no
  speaker notes; a fixed title, acknowledgements and summary formula. Covers
  Claude Slides artifacts (Noto Sans) and PowerPoint .pptx built with
  python-pptx (Aptos). This is the DEFAULT for every deck, talk or slide
  made for the user. Use whenever making, editing, restyling or reviewing
  slides, and when the user mentions: slides, deck, talk, presentation,
  conference talk, defense, PowerPoint, pptx, Claude
  Slides, title slide, or "slides-style". NOT for posters, for figures
  themselves (plot-style), or for decks that must follow a collaboration's
  own template beyond its chrome.
license: MIT
metadata:
  version: "0.1.0"
---

# Slides Style: the Figure Is the Slide

## Overview

The author's talks, eleven decks from 2021 to 2026, share one idea: **each
slide is a figure with a few words pointing into it**. A figure covers a
third to a half of the slide and runs nearly to the edges; two to five short
labels sit around it with thin arrows; one bold phrase says what to take
away; a small credit line says where the figure came from. Bullets, cards,
icons and paragraphs are almost absent. Everything below makes that idea
concrete and checkable. The evidence, deck by deck, is in
[references/evidence.md](references/evidence.md).

This skill is **harness-agnostic**. It has two targets and one rule set:

| Target | When | How | Face |
|---|---|---|---|
| **Claude Slides** artifact | The harness offers the Slides artifact type and the user did not ask for a file | the type's own HTML format, styled as in [references/claude-slides.md](references/claude-slides.md) | Noto Sans (+ Noto Sans Bengali, Latin Modern Math) |
| **PowerPoint .pptx** | Everywhere else, or whenever the user asks for PowerPoint / a file | `assets/slidestyle.py` on `assets/template.pptx`, with python-pptx — [references/pptx.md](references/pptx.md) | Aptos Display / Aptos |

Sizes below are in points. In Claude Slides multiply by 2 for canvas pixels
(1920 px across 13.333 in: 1 pt = 2 px).

---

## When to Apply

<HARD-RULE>
This style is the DEFAULT for every slide deck you make, edit or review for
the user, in either target. Apply it unless the user explicitly asks for
something else. Where a deck must use a collaboration's template (DESI, a
conference's), keep that template's background, logo and title position and
apply every other rule here.
</HARD-RULE>

**Not** for posters, for the figures themselves (plot-style draws them; this
skill places them), or for documents and reports.

### Where this overrides generic slide guidance

Generic slide skills (the pptx skill, the Claude Slides type's own design
notes) give advice this style contradicts. For this user, this skill wins:

| Generic advice | This style |
|---|---|
| Never put an accent line under titles | The short blue dash under every content title **is** the house motif |
| Every slide needs an icon, card, stat callout or colour block | Every slide needs a **figure**; no icons, cards, tiles or stat callouts |
| Body text 14-16 pt, captions 10-12 pt | Text 18-28 pt; only credits and citations go below, to 8-11 pt |
| Pick a bold topic palette; tone whites and blacks | Pure black on pure white; red for warnings; blue for the dash and one keyword |
| Two typefaces, a distinctive display face | One humanist sans for everything |
| Speaker notes on every slide | No speaker notes |
| Shrink text to fit | Text boxes grow; cut words or split the slide instead |
| Stay inside wide margins | Figures run to about 0.3 in (48 px) from the edges |

The Claude Slides type's **procedure** (files, uploads, saving, when to
verify) still governs how a Slides deck is written; this skill governs only
how it looks.

---

## The Rules

### Canvas and chrome

<HARD-RULE>
16:9, white background, no decoration. Every content slide carries the
house chrome and nothing else: the title top-left, a short blue dash under
it, and a small slide number bottom-right. Title, statement, quote and
divider slides carry no number.
</HARD-RULE>

| Element | .pptx (inches) | Claude Slides (px) |
|---|---|---|
| Canvas | 13.333 × 7.5 | 1920 × 1080 |
| Title box | left 1.00, top 0.30, width 11.33, bottom-anchored | left 144, top 48, width 1632 |
| Dash | 6 pt line, 1.07 long, at (1.083, 1.128), colour `#1973EB` | div left 156, top 156, 154 × 12, `#1973EB` |
| Slide number | 10 pt, right-aligned, box at (11.82, 6.95) | 24 px, right edge at 1816, top 1000 |
| Credit line | 10 pt, top 7.02, from left 0.90 or right-aligned to 11.70 | 24 px, top 1000 |
| Content area | (0.40, 1.40) to (12.93, 6.95) | (58, 202) to (1862, 1000) |

No footers, dates, logo strips, gradients, colour bars, sidebars, cards,
icons, drop shadows, sections or transitions. A collaboration template's own
logo is the one exception.

### Typography

<HARD-RULE>
One humanist sans-serif for all text: Aptos Display (titles) / Aptos (text)
in .pptx, Noto Sans in Claude Slides. Titles are regular weight, never bold.
Every piece of text is 18 pt or larger except image credits and citations,
which are 8-11 pt. Nothing in between (12-17 pt) except the captions under
the headshots on the acknowledgements slide (16 pt).
</HARD-RULE>

| Role | Size (pt) | Weight |
|---|---|---|
| Deck title (title slide) | 44 | lead phrase bold, rest regular |
| Content-slide title | 40 (36-44) | regular |
| Statement / section-break sentence | 40 (36-44) | regular, bold key word allowed |
| Takeaway, summary item, main label | 24 | regular, **bold key phrase** |
| Label crowded around a figure | 20 | regular |
| Smallest label | 18 | regular |
| Headshot caption (acknowledgements only) | 16 | name and institution bold |
| Image credit, citation | 10 (8-11) | regular |
| Slide number | 10 | regular |
| Display equation | 28-40 | — |

- **Emphasis is a bold phrase inside a sentence.** Italic only for a
  defined term ("this is called *Photometry*") and for variables. Never
  underline (links aside), never all-caps except the "EXTRA SLIDES" divider.
- **Text boxes grow to fit; text never shrinks.** If it does not fit, cut
  words, widen the box, or split the slide.
- Bengali text (the name line) is tagged `bn-BD` so PowerPoint picks a
  Bengali face; in Claude Slides it uses Noto Sans Bengali.

### Colour

- **Black text on white.** `#000000` on `#FFFFFF`, not toned variants.
- **Red `#C00000` is the one emphasis colour**, used sparingly for a
  warning or a shock: "Very expensive!", "NOT feasible in real world!".
- **Blue `#1973EB`** is the dash, and at most one keyword in the deck title
  ("Next-Generation", "Error-Aware").
- **Links are green `#1AC16E`**, underlined (the Grandview theme's link
  colour).
- All other colour comes from the figures. Drawn shapes that must match a
  figure use matplotlib's C0-C3 (`#1F77B4 #FF7F0E #2CA02C #D62728`).

### Slide anatomy

<HARD-RULE>
A content slide is: title, one figure (or a few panels of one figure), two
to five short labels placed around it with thin black arrows or leader lines
into it, at most one bold takeaway phrase, and a credit line when the figure
is not the author's own. The figure covers a third to a half of the slide.
</HARD-RULE>

- **Titles**: Title Case, one line (about 45 characters at 40 pt), 4-8
  words, no trailing period. Questions make good titles ("Why Do We Need
  Maps of Our Universe?"). "Results: …", "Summary: …" and "Classes of X:
  Model-based Methods" take a colon. Every content title sits at exactly
  the same place.
- **Labels annotate, they do not describe.** 2-8 words, beside the feature
  they name, with a 1.5 pt black arrow (`arrow()`, `x-connector`)
  pointing into the figure. Don't repeat the figure's axis labels.
- **The takeaway** is a phrase, not a paragraph: "~2 hours of DESI dark
  time is comparable to 1 hour on Keck+DEIMOS!". It goes beside or under
  the figure, bold or with a bold key phrase.
- **Credits** ("Image courtesy: Sloan Digital Sky Survey (adapted)") go on
  the bottom credit line; citations ("Dey et al. 2022, arXiv:2112.03939")
  go next to the figure or on the credit line, linked to arXiv or ADS.
  Every cited work must be real (cite-check).

### Text discipline

<HARD-RULE>
No bulleted lists except on the summary, agenda/outline and closing slides,
and there one level only, three to five items, one sentence each, each with a
bold key phrase. Never sub-bullets. Aim for 30 words or fewer on a content
slide; 60 is the ceiling.
</HARD-RULE>

A third to a half of the author's slides carry 20 words or fewer. When a
slide needs more words, it needs to be two slides.

### Figures

- **PNG figures**, at 150 dpi or more on the slide. Reuse paper figures
  as they are. A figure made only for the slide follows plot-style with its
  `figsize` set to **half** its on-slide size, so plot-style's 9-12 pt type
  lands at 18-24 pt on the slide.
- **Never a native chart, SmartArt, or a styled table.** A table is a
  picture of the LaTeX table, or a figure.
- Photographs as JPEG. Videos and GIFs (simulations, sequences) are placed
  like figures.
- **Paper anchors**: when a published result is introduced, show the
  paper's title and abstract as a screenshot with the title boxed in red
  (`outline()`).
- **Code**: a syntax-coloured screenshot of 5-8 lines, plus "Read the
  Docs | Tutorial" links. Never a code font in a text box.
- **Diagrams** from simple shapes: black lines and arrows, a neural-network
  sketch, nested circles, pictogram analogies (cats and koalas). A coloured
  chain of boxes is allowed when its colours carry meaning that an equation
  on the same slide repeats.

### Equations

<HARD-RULE>
Equations are native and editable. In .pptx: PowerPoint's own equation
(OMML) through `equation()`, converted from LaTeX by pandoc, with a rendered
fallback picture for other readers. In Claude Slides: Unicode math in Latin
Modern Math for linear expressions, and an outline SVG from
`scripts/latex_to_svg.py` for fractions, limits and matrices (the format has
no math markup). Annotate terms like a figure: a label under each term,
joined by a thin line.
</HARD-RULE>

### Builds and motion

- **Builds are duplicated slides**: the same title, one thing added or
  highlighted per slide (a list growing beside one figure, one step of a
  numbered list highlighted). This is how most of the author's builds work.
- On a single slide, only the **Appear** effect on click (`appear()` in
  .pptx; `data-build-in="fade"` is the closest Claude Slides allows). No
  motion paths, no emphasis effects, no slide transitions.

### Notes

<HARD-RULE>
No speaker notes unless the user asks for them.
</HARD-RULE>

---

## Slide Types

The decks are made of a fixed vocabulary. Recipes, with coordinates for
both targets, are in [references/slide-types.md](references/slide-types.md).

| # | Type | .pptx function | Where |
|---|---|---|---|
| 1 | Title | `title_slide()` | first |
| 2 | Acknowledgements | `acknowledgements_slide()` | second |
| 3 | Statement / question | `statement_slide()` | section breaks, beats |
| 4 | Quote | `quote_slide()` | openers |
| 5 | Figure + annotation | `content_slide()` + `figure()` / `text()` / `arrow()` | the workhorse |
| 6 | Build sequence | `content_slide()` repeated | concepts in steps |
| 7 | Two-panel comparison | `LEFT_HALF` / `RIGHT_HALF` | method vs method, have vs want |
| 8 | Annotated equation | `equation()` + `text()` + `line()` | the method |
| 9 | Paper anchor | `figure()` + `outline()` | introducing a result |
| 10 | Code | `figure()` of a screenshot + links | software |
| 11 | Summary + closing | `summary_slide()` | last of the talk |
| 12 | Backup | `divider_slide()`, then `hide()` as wanted | after the summary |

The title slide carries the name line "Biprateep Dey | বিপ্রতীপ দে", the
email, the affiliation logos and a hero image on the right. The summary
ends with the closing formula: "Thanks for your attention! / Have
questions, comments or want to collaborate? / Contact: <email>". Both come
from the profile ([references/profile.md](references/profile.md)).

**Slides stand alone.** The author assembles long decks by reusing slides
from earlier talks, so no slide may depend on the one before it for its
meaning, apart from a build sequence.

---

## Workflow

1. **Outline as slides, not sections.** One message per slide, in the
   slide-type vocabulary above: title, acknowledgements, motivation as
   questions and statement slides, method, results, summary, backup. About
   1.5-2 minutes per slide for a live talk.
2. **Figures first.** Gather or make every figure before writing a slide.
   A slide that has no figure is a statement slide or does not exist.
3. **Build** in the target:
   - .pptx: copy `assets/slidestyle.py`, `assets/template.pptx` and
     `assets/profile.json` next to the deck script and follow
     [references/pptx.md](references/pptx.md).
   - Claude Slides: follow the type's own procedure, styled by
     [references/claude-slides.md](references/claude-slides.md).
4. **Check** (.pptx): `uv run scripts/check_slides.py talk.pptx` must exit
   0. Then render with `python scripts/render_deck.py talk.pptx` and look at
   every slide for overflow, overlap, titles off one line, labels away
   from what they name. LibreOffice substitutes Aptos and shows the equation
   fallback pictures, so leave slack and don't trust a tight fit.
5. **Report** which slides you made, what needs the user's assets (a
   missing logo, a figure you could not find), and any rule you broke on
   purpose.

---

## Anti-Patterns

Stop and fix if you catch any of these:

- **A bulleted slide.** Turn it into a figure with labels, or a statement
  slide, or two slides.
- **Description instead of annotation**: a paragraph under the figure
  saying what it shows. Labels on the figure, one takeaway phrase.
- **Small text**: 12-16 pt labels, a 14 pt takeaway, code in a 12 pt font.
- **A small figure in wide margins**: a figure under a third of the slide,
  or 1 in margins around it.
- **Decoration**: cards, tiles, icon rows, stat callouts, colour bars,
  shadows, gradients, a toned background, a second typeface.
- **A bold title, a title with a period, a two-line title**, or titles that
  jump between slides.
- **Speaker notes** nobody asked for.
- **Shrink-to-fit text**, or text overflowing its box.
- **A native chart or table** instead of the PNG figure.
- **A picture of an equation** in .pptx, or LaTeX source on the slide.
- **Fades, flies and transitions.** Appear, or duplicated slides.
- **A missing credit** under someone else's image, or a citation that is
  not a real paper.

---

## Self-Check Before Finishing

- [ ] 16:9, white, house chrome on every content slide (title top-left,
      dash, slide number), none on title / statement / divider slides.
- [ ] One sans face; titles regular, Title Case, one line, no period, all
      at the same position.
- [ ] Every text 18 pt or more except credits and citations (8-11 pt).
- [ ] Every content slide leads with a figure covering a third to a half of
      it; labels annotate with arrows; at most one takeaway phrase.
- [ ] No bullets outside summary / agenda; no sub-bullets; ≤ 60 words per
      slide, most ≤ 30.
- [ ] Credits under borrowed figures; citations real and linked.
- [ ] Equations native; builds as duplicated slides or Appear; no notes.
- [ ] Title slide, acknowledgements and summary follow the profile.
- [ ] .pptx: `check_slides.py` exits 0 and every rendered slide was looked
      at.

---

## Interaction With Other Skills

- **plot-style** draws the figures; this skill places them. A figure made
  only for a slide is drawn at half its on-slide size in plot-style's style.
- **cite-check** verifies every citation that appears on a slide.
- **code-style** and **jupytext** govern the deck script (`import
  slidestyle`, then `slidestyle.content_slide(...)`); it is a jupytext
  percent script like any other.
- **co-writer** is for papers; slide text is too short for it. Write it in
  the labels-and-takeaway register above.
- The **pptx** skill and the **Claude Slides** type supply the mechanics
  (file formats, uploads, validation); their design advice yields to this
  skill, as tabulated under *When to Apply*.

---

## Files

| Path | Contents |
|---|---|
| `assets/slidestyle.py` | python-pptx builder: slide types, figures, labels, arrows, credits, OMML equations, Appear builds |
| `assets/template.pptx` | the house template (theme, Title / Content / Blank layouts, dash, slide number) |
| `assets/profile.json` | the committed text profile: name line, email, closing formula, logo keys |
| `scripts/check_slides.py` | checks a .pptx against the rules (`uv run`, PEP 723 dependencies) |
| `scripts/render_deck.py` | renders a .pptx to PNGs with LibreOffice for visual QA |
| `scripts/latex_to_svg.py` | outline SVG of display math for Claude Slides |
| `scripts/build_template.py` | regenerates `assets/template.pptx` |
| `references/slide-types.md` | a recipe per slide type, both targets |
| `references/pptx.md` | the .pptx workflow and builder API |
| `references/claude-slides.md` | the style in the Claude Slides format |
| `references/profile.md` | the profile and the local assets folder |
| `references/evidence.md` | what the eleven decks show, and the lessons from two Claude-made decks |
| `examples/example_deck.py` | a runnable twelve-slide deck using every slide type |

Derived from the author's decks of 2021-2026 (defense, photo-z overview,
Cal-PIT, DESI, stream search, AI-strophysics and others), measured from their
XML; see `references/evidence.md`.
