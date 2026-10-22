---
name: slides-style
description: >-
  Enforce the author's presentation style on every slide deck: the figure is
  the slide, text only annotates it. 16:9 white slides; title top-left in
  Title Case with a short blue dash under it and a small slide number; no
  bullets outside the summary; 36-48 px labels with a bold key phrase and
  thin black arrows into the figure; 24 px credits; native editable math;
  builds as duplicated slides; no speaker notes; a fixed title,
  acknowledgements and summary formula; and an alignment pass that measures
  every slide and snaps near-misses. Builds the host's native deck (a
  Claude Slides artifact in Claude), always starting from the author's
  template deck; PowerPoint comes from the host's export. This is the
  DEFAULT for every deck, talk or slide made for the user. Use whenever
  making, editing, restyling, aligning or reviewing slides, and when the
  user mentions: slides, deck, talk, presentation, defense, Claude Slides,
  title slide, alignment, or "slides-style". NOT for posters or for the
  figures themselves (plot-style).
license: MIT
metadata:
  version: "0.3.0"
---

# Slides Style: the Figure Is the Slide

## Overview

The author's talks, eleven decks from 2021 to 2026, share one idea: **each
slide is a figure with a few words pointing into it**. A figure covers a
third to a half of the slide and runs nearly to the edges; two to five short
labels sit around it with thin arrows; one bold phrase says what to take
away; a small credit line says where the figure came from. Bullets, cards,
icons and paragraphs are almost absent. Everything below makes that idea
concrete and checkable, down to the pixel. The evidence, deck by deck, is in
[references/evidence.md](references/evidence.md).

All geometry is on the **1920 × 1080 px canvas** (144 px per inch; 1 pt =
2 px).

---

## The Target: the Host's Native Deck

<HARD-RULE>
Build the deck in the host's own slide format, never as a PowerPoint file.
In Claude (claude.ai, Claude Code, Cowork) that is a **Claude Slides
artifact**, and every new deck starts as a copy of the author's template
deck (`claude_slides_template.url` in `assets/profile.json`): copy it,
replace its bracketed placeholders, duplicate its slides for the talk.
Never start from a blank canvas, and do not ask which format to use.
PowerPoint, PDF and Google Slides come from the host's own export.
</HARD-RULE>

| Host | Deck | How |
|---|---|---|
| Claude | Claude Slides artifact | [references/claude-slides.md](references/claude-slides.md): starting from the template, faces, chrome, sizes, equations |
| Another host with its own deck format (Antigravity, a future Codex one) | that format | the same rules and the same canvas geometry, in that format's units |
| A host with no deck format (Codex today) | the Claude Slides files (`project/deck.json`, `project/slides/<id>.html`) in a folder, copied from `assets/claude-slides-template/` | checkable with `scripts/check_deck.py`; the user publishes it from Claude later, which copies the template's assets then |

---

## When to Apply

<HARD-RULE>
This style is the DEFAULT for every slide deck you make, edit or review for
the user. Apply it unless the user explicitly asks for something else. Where
a deck must follow a collaboration's template (DESI, a conference's), keep
that template's background, logo and title position and apply every other
rule here.
</HARD-RULE>

**Not** for posters, for the figures themselves (plot-style draws them; this
skill places them), or for documents and reports.

### Where this overrides generic slide guidance

The Claude Slides type's own design notes (and other slide skills) give
advice this style contradicts. For this user, this skill wins:

| Generic advice | This style |
|---|---|
| Never put an accent line under titles | The short blue dash under every content title **is** the house motif |
| Every slide needs an icon, card, stat callout or colour block | Every slide needs a **figure**; no icons, cards, tiles or stat callouts |
| Tone whites and blacks; pick a topic palette | Pure `#000000` on pure `#FFFFFF`; red for warnings; blue for the dash and one keyword |
| Two typefaces, a distinctive display face | One humanist sans, Noto Sans, for everything |
| Speaker notes on every slide | No speaker notes |
| Stay inside the 128 px margins | Figures run to 48 px from the edges |
| Never verify unless the user asked | The author asked: run the alignment pass on every deck (below) |

The Claude Slides type's **procedure** (files, uploads, the order of calls)
still governs how a deck is written; this skill governs how it looks.

---

## The Rules

### Canvas and chrome

<HARD-RULE>
16:9, white background, no decoration. Every content slide carries the
house chrome and nothing else: the title top-left, a short blue dash under
it, and a small slide number bottom-right. Title, statement, quote and
divider slides carry no number. Every element is pinned
(`position:absolute`) so it can be measured.
</HARD-RULE>

| Element | Geometry (px) |
|---|---|
| Title (`h2`) | left 144, top 48, width 1632, 80 px, weight 400, line-height 1.1 |
| Dash | painted `div` at left 156, top 156, 154 × 12, `#1973EB` |
| Slide number | 24 px, right-aligned, box left 1702, top 1000, width 114 (right edge 1816) |
| Credit line | 24 px, left 144, top 1000 (or right-aligned to 1816) |
| Content area | x 48-1872, y 202-994 |
| Guide lines | x 144 (the title's left edge), x 960 (centre), x 1776 and 1816 (right edges) |

No footers, dates, logo strips, gradients, colour bars, sidebars, cards,
icons, drop shadows or transitions. A collaboration template's own logo is
the one exception.

### Typography

<HARD-RULE>
Noto Sans for all text (Noto Sans Bengali for the Bengali name, Latin Modern
Math for math). Titles are regular weight, never bold. Every piece of text
is 36 px or larger except credits, citations and slide numbers (24 px) and
the headshot captions on the acknowledgements slide (32 px).
</HARD-RULE>

| Role | px | Weight |
|---|---|---|
| Deck title (title slide) | 88 | lead phrase bold, rest regular |
| Content-slide title | 80 | regular |
| Statement / section-break sentence | 80 | regular, bold key word allowed |
| Takeaway, summary item, main label | 48 | regular, **bold key phrase** |
| Label crowded around a figure | 40 | regular |
| Smallest label | 36 | regular |
| Headshot caption (acknowledgements only) | 32 | name and institution bold |
| Credit, citation, slide number | 24 | regular |
| Display equation | 56-80 | — |

- **Emphasis is a bold phrase inside a sentence.** Italic only for a
  defined term ("this is called *Photometry*") and for variables. Never
  underline (links aside), never all-caps except the "EXTRA SLIDES" divider.
- **Text never shrinks.** If it does not fit, cut words, widen the box, or
  split the slide.

### Colour

- **Black text on white.** `#000000` on `#FFFFFF`.
- **Red `#C00000` is the one emphasis colour**, used sparingly for a
  warning or a shock: "Very expensive!", "NOT feasible in real world!".
- **Blue `#1973EB`** is the dash, and at most one keyword in the deck title
  ("Next-Generation", "Error-Aware").
- **Links are green `#1AC16E`**, underlined.
- All other colour comes from the figures. Drawn shapes that must match a
  figure use matplotlib's C0-C3 (`#1F77B4 #FF7F0E #2CA02C #D62728`).

### Slide anatomy

<HARD-RULE>
A content slide is: title, one figure (or a few panels of one figure), two
to five short labels placed around it with thin black arrows or leader lines
into it, at most one bold takeaway phrase, and a credit line when the figure
is not the author's own. The figure covers a third to a half of the slide.
</HARD-RULE>

- **Titles**: Title Case, one line (about 40 characters at 80 px), 4-8
  words, no trailing period. Questions make good titles ("Why Do We Need
  Maps of Our Universe?"). "Results: …", "Summary: …" and "Classes of X:
  Model-based Methods" take a colon. Every content title sits at exactly
  the same place.
- **Labels annotate, they do not describe.** 2-8 words, beside the feature
  they name, with a 3 px black arrow (`x-connector`, tail at the label)
  pointing into the figure. Don't repeat the figure's axis labels.
- **The takeaway** is a phrase, not a paragraph: "~2 hours of DESI dark
  time is comparable to 1 hour on Keck+DEIMOS!". It goes beside or under
  the figure, bold or with a bold key phrase.
- **Credits** ("Image courtesy: Sloan Digital Sky Survey (adapted)") go on
  the credit line; citations ("Dey et al. 2022, arXiv:2112.03939") go next
  to the figure or on the credit line, linked to arXiv or ADS. Every cited
  work must be real (cite-check).

### Text discipline

<HARD-RULE>
No bulleted lists except on the summary, agenda/outline and acknowledgements
slides, and there one level only, three to five items, one sentence each,
each with a bold key phrase. Aim for 30 words or fewer on a content slide;
60 is the ceiling.
</HARD-RULE>

A third to a half of the author's slides carry 20 words or fewer. When a
slide needs more words, it needs to be two slides.

### Figures

- **PNG figures**, uploaded as assets. Reuse paper figures as they are. A
  figure made only for the slide follows plot-style with its `figsize` set
  to **half** its on-slide size in inches (on-slide px ÷ 144 ÷ 2), so
  plot-style's 9-12 pt type lands at 36-48 px on the slide.
- **Size the figure's box to the image's aspect ratio**, so the box is the
  picture and its edges can be aligned (with `object-fit:contain` a box
  wider than the image leaves invisible margins that break alignment).
- **Never a native chart, an SVG chart, or a styled table.** A table is a
  picture of the LaTeX table, or a figure.
- **Paper anchors**: when a published result is introduced, show the
  paper's title and abstract as a screenshot with the title boxed in red (a
  pinned `div` with `border:4px solid #c00000`).
- **Code**: a syntax-coloured screenshot of 5-8 lines, plus "Read the
  Docs | Tutorial" links. Never a code font in a text box.
- **Diagrams** from simple shapes: black lines and arrows, a neural-network
  sketch, nested circles, pictogram analogies (cats and koalas). A coloured
  chain of boxes is allowed when its colours carry meaning that an equation
  on the same slide repeats.

### Equations

<HARD-RULE>
Equations are native, never a screenshot of LaTeX. Linear expressions are
Unicode math in Latin Modern Math (`p(𝒙 | θ)`, `𝒩(𝒙̂ | 𝒙, Σ)`), each in
its own pinned `<p>`; fractions, limits, sums and matrices are an outline
SVG from `scripts/latex_to_svg.py` (the format has no math markup).
Annotate terms like a figure: a label under each term, joined by a thin
line.
</HARD-RULE>

### Builds and motion

- **Builds are duplicated slides**: the same title, one thing added or
  highlighted per slide (a list growing beside one figure, one step of a
  numbered list highlighted). This is how most of the author's builds work.
- On a single slide, at most `data-build-in="fade"` on one or two pinned
  elements (the nearest the format has to Appear). No transitions.

### Notes

<HARD-RULE>
No speaker notes (`<aside>`) unless the user asks for them.
</HARD-RULE>

---

## Alignment

The author wants every deck aligned to the pixel, within each slide and
from slide to slide. That is a measurable property, so it is measured.

<HARD-RULE>
Lay every slide out on shared lines, then run the alignment pass on the
finished deck and fix what it reports before handing the deck over. The
author asked for this pass on every deck, so it is the check the user asked
for.
</HARD-RULE>

**Laying out:**

- **One left line.** Text and figures start on the title's left edge,
  x = 144, unless they sit in a deliberate second column; everything in
  that column then starts on the same x.
- **Centred means centred** on the canvas (x = 960) or on its column's
  centre; equal columns have equal widths.
- **Rows** of like elements (logos, headshots, panels) share one top and
  have equal gaps.
- **Same element, same place.** A label column, a figure box or a takeaway
  that recurs sits at the same coordinates on every slide of its kind; the
  chrome never moves.
- **Arrows** start at their label's edge and end on the feature.
- **Margins**: nothing within 48 px of the canvas edge except a
  deliberately full-bleed photograph.

**The pass.** After the last slide is written, run:

```bash
python <skill-dir>/scripts/check_deck.py <root>
```

where `<root>` is the folder holding the deck's `project/` files as you
wrote them (if the deck was edited in its page since, read the changed
slides first). It reports house-rule violations and alignment problems,
each with the exact value to set ("left 1080 px is 14 px off 1066; set
left:1066px"), and a per-slide alignment score: the share of content
elements with an edge on a shared line or a place in an evenly spaced row.

1. Fix every ERROR, and every `near-miss`, `drift`, `spacing`, `overlap`
   and `arrow` warning, by editing the named values in the slide files.
2. Republish only the changed slides (the type's revising procedure).
3. Run the pass again until it reports none of those, and every slide
   scores 100 % or has a reason not to (a free-floating annotation inside
   a figure).
4. Report the deck's score and anything left on purpose.

Text heights are estimates (about 0.55 em per character), so an `overlap`
between two close text boxes is probable, not certain; move them apart
anyway or check the slide in its page.

---

## Slide Types

The decks are made of a fixed vocabulary. Recipes are in
[references/slide-types.md](references/slide-types.md); the template deck
holds the six marked ✓.

| # | Type | Template slide | Where |
|---|---|---|---|
| 1 | Title | ✓ `cover` | first |
| 2 | Acknowledgements | ✓ `acks` | second |
| 3 | Statement / question | ✓ `statement` | section breaks, beats |
| 4 | Quote | — | openers |
| 5 | Figure + annotation | ✓ `content` | the workhorse |
| 6 | Build sequence | `content`, duplicated | concepts in steps |
| 7 | Two-panel comparison | `content`, two figures | method vs method, have vs want |
| 8 | Annotated equation | `content` with an equation | the method |
| 9 | Paper anchor | `content` with a screenshot | introducing a result |
| 10 | Code | `content` with a screenshot | software |
| 11 | Summary + closing | ✓ `summary` | last of the talk |
| 12 | Backup | ✓ `extra`, then content slides | after the summary |

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
3. **Copy the template and fill it**, as "Starting a Deck from the
   Template" in [references/claude-slides.md](references/claude-slides.md)
   says; the type's own procedure governs the calls.
4. **Run the alignment pass** and fix what it finds (above).
5. **Report** which slides you made, the deck's alignment score, what
   needs the user's assets (a missing headshot, a figure you could not
   find), and any rule you broke on purpose.

---

## Anti-Patterns

Stop and fix if you catch any of these:

- **A deck started from a blank canvas**, or a PowerPoint file built by
  hand.
- **A bulleted slide.** Turn it into a figure with labels, or a statement
  slide, or two slides.
- **Description instead of annotation**: a paragraph under the figure
  saying what it shows. Labels on the figure, one takeaway phrase.
- **Small text**: labels under 36 px, a 32 px takeaway, code in a text box.
- **A small figure in wide margins**: a figure under a third of the slide.
- **Decoration**: cards, tiles, icon rows, stat callouts, colour bars,
  shadows, gradients, a toned background, a second typeface.
- **A bold title, a title with a period, a two-line title**, or titles that
  jump between slides.
- **Near-miss alignment**: a label at 1066 beside a takeaway at 1080, a
  figure at 150 under a title at 144, three headshots with gaps of 368,
  384 and 400.
- **A figure box wider than its image**, so the picture floats inside it.
- **Speaker notes** nobody asked for.
- **A table or chart drawn in the slide** instead of a PNG figure.
- **A screenshot of an equation**, or LaTeX source on the slide.
- **Bracketed template text left in the deck.**
- **A missing credit** under someone else's image, or a citation that is
  not a real paper.

---

## Self-Check Before Finishing

- [ ] Started from the template; no `[…]` placeholder or empty `<img>` left.
- [ ] 16:9, white, house chrome on every content slide (title, dash,
      slide number that matches its position), none on title / statement /
      divider slides.
- [ ] Noto Sans only; titles regular, Title Case, one line, no period.
- [ ] Every text 36 px or more except 24 px credits, citations and numbers
      (32 px captions on acknowledgements).
- [ ] Every content slide leads with a figure covering a third to a half of
      it; labels annotate with arrows; at most one takeaway phrase.
- [ ] No bullets outside summary / agenda / acknowledgements; ≤ 60 words
      per slide, most ≤ 30.
- [ ] Credits under borrowed figures; citations real and linked.
- [ ] Equations native; builds as duplicated slides; no notes.
- [ ] `check_deck.py` reports no ERROR and no near-miss, drift, spacing,
      overlap or arrow warning; every slide's alignment score is reported.

---

## Interaction With Other Skills

- **plot-style** draws the figures; this skill places them. A figure made
  only for a slide is drawn at half its on-slide size in plot-style's style.
- **cite-check** verifies every citation that appears on a slide.
- **co-writer** is for papers; slide text is too short for it. Write it in
  the labels-and-takeaway register above.
- The **Claude Slides** type supplies the mechanics (files, uploads, the
  order of calls); its design advice yields to this skill, as tabulated
  under *When to Apply*.

---

## Files

| Path | Contents |
|---|---|
| `assets/profile.json` | the committed text profile: name line, email, closing formula, logo keys, the template deck's link and asset ids |
| `assets/claude-slides-template/` | a backup of the template deck's files (`project/deck.json`, `project/slides/*.html`) |
| `scripts/check_deck.py` | the house-rule check and the alignment pass, on a deck's files (standard library only) |
| `scripts/latex_to_svg.py` | outline SVG of display math (needs `latex` and `dvisvgm`) |
| `references/claude-slides.md` | starting from the template, faces, chrome, sizes, content, equations, builds |
| `references/slide-types.md` | a recipe per slide type, in canvas px |
| `references/profile.md` | the profile, the template and the local assets folder |
| `references/evidence.md` | what the eleven decks show, and the lessons from two Claude-made decks |

Derived from the author's decks of 2021-2026 (defense, photo-z overview,
Cal-PIT, DESI, stream search, AI-strophysics and others), measured from their
XML; see `references/evidence.md`.
