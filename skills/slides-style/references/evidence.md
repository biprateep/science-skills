# Evidence: What the Decks Show

Analysed 2026-10-21 from 13 decks (kept outside the repository). Eleven are
Biprateep's own; two (`Tabular Foundation Models Tutorial`, `Generative
Modeling of Astronomical Catalogs`) were made with Claude Slides and exported
to .pptx. Numbers come from the slide XML (fonts, sizes and colours resolved
through layout → master → theme inheritance) and from rendered thumbnails.

## 1. Corpus

| Deck | Era | Template / fonts | Slides | Words per slide (median) | Slides with a figure | Median figure area |
|---|---|---|---|---|---|---|
| PCA_Talk_June2021 | 2021 | Office default, Calibri Light / Calibri | 35 | 14 | 17 / 35 | 0.00 (shape diagrams) |
| microarcsec_astrometry_gaia | 2022 | Office default, Calibri Light / Calibri | 19 | 24 | 17 / 19 | 0.34 |
| phd_defense | 2022 | Own "DashVTI" theme, Grandview Display | 85 | 28 | 78 / 85 | 0.35 |
| Cal-Pit-Stats | 2022–23 | Own "DashVTI" theme, Grandview Display (10 × 5.625 in canvas) | 70 | 20 | 66 / 70 | 0.42 |
| DESI_winter_2023_plenary | 2023 | DESI collaboration template, Calibri / Helvetica | 21 | 26 | 16 / 21 | 0.49 |
| photo_z_overview_2025 | 2025 | Own "DashVTI" theme, Grandview Display | 102 | 28 | 94 / 102 | 0.37 |
| DESI-AI | 2025 | DESI collaboration template | 16 | 20 | 13 / 16 | 0.46 |
| discussion_talk | 2025 | Office default, Aptos Display / Aptos | 18 | 11 | 12 / 18 | 0.46 |
| DESI-Deep_pilot | 2026 | DESI collaboration template | 26 | 30 | 25 / 26 | 0.47 |
| aistrophysics_hype_hope | 2026-06 | Office default, Aptos Display / Aptos | 36 | 6 | 19 / 36 | 0.36 |
| stream_search_skai | 2026-09 | Office default, Aptos Display / Aptos | 17 | 48 | 9 / 17 | 0.06 (shape diagrams) |
| **Claude:** Tabular Foundation Models Tutorial | 2026-10 | Claude Slides, Open Sans (+ JetBrains Mono, Latin Modern Math) | 26 | 40 | 24 / 26 | 0.33 |
| **Claude:** Generative Modeling of Astronomical Catalogs | 2026-10 | Claude Slides, Open Sans (+ Latin Modern Math) | 35 | 35 | 33 / 35 | 0.36 |

All decks are 16:9. Twelve are 13.33 × 7.5 in; Cal-Pit-Stats is 10 × 5.625 in.

## 2. Common patterns in Biprateep's own decks

### 2.1 Canvas, template, chrome

- **16:9, white background, no decoration.** No gradients, no colour
  blocks, no background images on content slides, no icons, no cards. The
  only dark slides are the DESI template's photo-background title slide and
  its "Additional slides" divider.
- **One template motif:** in the Grandview decks (defense, photo-z
  overview, Cal-PIT), a short blue dash (theme accent 1973EB) sits
  left-aligned just under the title on every content slide. It is the only
  recurring graphic element. Nothing comparable in the Office-default or DESI
  decks.
- **Slide numbers** bottom-right, small, on every slide of the Grandview and
  DESI decks; absent from the Office-default decks. Never a footer, date or
  logo strip (the DESI template puts the DESI logo top-left; that is the
  collaboration's template, not a personal choice).
- **No PowerPoint sections** in any deck.

### 2.2 Typography

- **Always a humanist sans-serif, always the template's own.** Grandview
  Display (own theme), Calibri / Calibri Light (2021–22 Office default),
  Aptos / Aptos Display (2025–26 Office default), the DESI template's
  Calibri. No serif anywhere except inside LaTeX-rendered equation images
  (Computer Modern).
- **Titles 36–44 pt, never bold** (bold in ≤ 7 % of title characters, and
  those are typically a bold lead phrase on a title slide). Grandview master:
  40 pt; Calibri Light / Aptos Display: 44 pt; DESI template: 36 pt.
- **Body and annotation text 18–28 pt.** 80–100 % of non-title characters
  are ≥ 18 pt (defense 91 %, stream 80 %, AI-strophysics 100 %). 24 pt is the
  single most common size for free text; 28 pt in the Office-default decks.
- **Small text only for credits and citations:** 8–11 pt "Image courtesy: …"
  and "Dey+2022, arXiv:2112.03939" lines, bottom edge of the slide.
- **Emphasis = bold key phrase inside a sentence.** 15–30 % of body
  characters are bold. Italic is ~0–2 %, used only for defined terms
  ("… is called *Photometry*"). Underline never.
- **Text boxes auto-grow (`spAutoFit`), text is not shrunk to fit.**
  `normAutofit` with a font scale appears on < 5 % of boxes.

### 2.3 Colour

- Black text on white. In the Grandview decks 90 %+ of all characters are
  pure black (`tx1`); in the Office-default decks 100 %.
- **Red (C00000) is the one emphasis colour**, used sparingly for a
  warning or shock ("Very expensive!", "Images have incomplete and noisy
  information about redshift", "NOT feasible in real world!").
- Blue appears only as the template accent (dash, hyperlinks) and in the
  2026 decks as one coloured keyword in the title slide ("Error-Aware",
  "Real", "Hype or Hope" in red/blue).
- All other colour comes from the figures themselves (matplotlib defaults,
  viridis, photographs).

### 2.4 Slide anatomy

- **Title top-left**, left-aligned, one line (median 4–7 words, max 12–14).
  Title box at x ≈ 0.9 in, y ≈ 0.3 in in the Grandview decks; same
  position on every content slide of a deck.
- **The figure is the slide.** 70–95 % of slides carry at least one picture;
  median picture coverage 0.35–0.49 of the slide area; in the big decks a
  quarter to a third of slides have a single figure covering more than half
  the slide. Figures run nearly edge to edge (content extends to ≥ 99 % of
  the width and to the bottom 2 % of the height; left/right margins of
  0.1–0.3 in are normal).
- **Text lives in free-floating text boxes, not placeholders.** 90–100 % of
  text characters are in free text boxes; the content placeholder of the
  "Title and Content" layout is deleted on almost every slide.
- **Annotation, not description.** The typical slide is a figure plus 2–5
  short labels (2–8 words, 18–24 pt) placed around it, with thin black
  arrows or lines pointing into the figure, plus one bold takeaway phrase
  next to or below the figure ("~2 hours of DESI dark time exposure
  comparable to 1 hour on Keck+DEIMOS!"). The big decks have 100–150
  arrows/lines and 35–50 groups each.
- **Credit line** "Image courtesy: <source>" or "Credit: <paper>" at 8–11 pt
  in the bottom corner whenever the figure is not the speaker's own.
- **Citation style on slides:** "Dey et al. 2022" / "Dey+2022" next to the
  figure, often hyperlinked to arXiv (defense: 50 hyperlinks, 15 to
  arxiv.org); explicit "arXiv:2112.03939" on summary slides.

### 2.5 Text discipline

- **Bullets are essentially absent.** In the figure-driven decks ≤ 2 slides
  per deck use a bulleted list; the teaching/discussion decks use 4–7. Sub-
  bullets occur on 0–4 slides per deck. When a list is used (summary,
  agenda, acknowledgements), it is 3–5 items, one sentence each, bold key
  phrase in each.
- **Words per slide:** median 6–30, mean 10–44. In the figure-driven decks
  a third to a half of all slides carry ≤ 20 words.
- **Titles are Title Case** (78–100 % of titles) with no trailing period;
  "Results: …", "Summary: …", "Classes of Photo-z Algorithms: Model-based
  methods" use a colon subtitle. **Questions as titles** are common
  (Cal-PIT 17/65, AI-strophysics 7/14, microarcsec 6/19): "Why Do We Need
  Maps of Our Universe?", "What is a good predicted photo-z distribution?".
- Repeated titles across consecutive slides are the norm for builds (next
  section).
- **Almost never any speaker notes** (0–8 slides per deck, mostly 0).

### 2.6 Figures and media

- **Matplotlib PNGs**, 110–140 per big deck, at 140–210 effective dpi on
  the slide; JPEG only for photographs. Exported plots keep their own
  labels, so slide text rarely repeats axis labels.
- **Videos** (mp4/gif/webm, 2–4 per deck) for simulations and animated
  sequences, placed like figures.
- **Equations** are LaTeX-rendered images (Computer Modern) in all decks
  after 2021 (the 2021 PCA talk used PowerPoint's native equation editor on
  11 slides). Equations are annotated like figures: labels under terms,
  joined by thin lines ("New distribution (calibrated by construction)",
  "Learnt regression function", "Old distribution (uncalibrated)").
- **Never a native PowerPoint chart. Tables ≤ 1 per deck**, and those are
  images of LaTeX tables.
- **Shape diagrams** for concepts: neural-network icon → arrows → equation;
  nested circles (AI ⊃ ML ⊃ DL ⊃ LLM); flow boxes; emoji/pictogram
  analogies in teaching talks (cats and koalas for weak supervision, ant and
  moon for micro-arcseconds, wine glasses for feature summaries, a puppet for
  latent variables).

### 2.7 Recurring slide types

1. **Title slide:** left-aligned title in 2–4 lines (bold lead phrase, or one
   coloured keyword), "Biprateep Dey | বিপ্রতীপ দে", email, a row of
   affiliation/funder logos along the bottom, a hero image (sky survey map,
   galaxy, stream) filling the right half, tiny image credit. DESI talks:
   full-bleed telescope photo with white text.
2. **Acknowledgements** as slide 2: circular headshots of collaborators,
   name in bold, role, department, institution; "Funded by:" logo row.
3. **Statement slides:** a single sentence or question, 36–44 pt, centred
   on an otherwise empty slide, used as section breaks and beats
   ("What if we 'learn' these transformations?", "Cal-PIT is a
   general-purpose method!", "Modelling vs Understanding"). AI-strophysics
   11/36, PCA 8/35, Cal-PIT 4/70.
4. **Quote slides:** a quotation centred with em-dash attribution.
5. **Figure + annotation** (the workhorse, §2.4).
6. **Progressive builds as duplicated slides:** same title, content added
   or highlighted per slide (Cal-PIT 27/70 slides share the previous
   slide's title, defense 16/85, DESI-AI 7/16). "The Boons and Banes of
   Astronomical Data Sets" accumulates a list over 10 slides on top of one
   figure.
7. **Two-panel comparison:** left vs right with a one-line label above each
   ("Classical ML (k-NN)" vs "Deep Capsule Network", "What we have" vs
   "What we want to learn"); pros/cons as two short columns.
8. **Paper-anchor slides:** screenshot of the paper's first page (title and
   abstract, red-boxed) when a published result is introduced; a report
   excerpt with yellow highlighting.
9. **Code slide:** a syntax-coloured screenshot of 5–8 lines plus
   "Read the Docs | Tutorial" links.
10. **Summary slide:** "Summary" or "Summary: <section>", 3–4 one-sentence
    takeaways with bold key phrases, "References:" with arXiv ids and the
    GitHub repo, then the closing formula in bold: "Thanks for your
    attention! Have questions, comments or want to collaborate? Contact:
    <email> | <handle>". The 2026 stream talk adds a QR code to the arXiv
    paper.
11. **Backup:** an "EXTRA SLIDES" / "SUPPLEMENTARY MATERIALS" / "Additional
    Slides" divider followed by backup slides, some hidden (Cal-PIT 9
    hidden, discussion talk 5).
12. **Long decks are assembled by reuse:** the 102-slide photo-z overview and
    the 70-slide Cal-PIT deck share dozens of slides with the defense. Slides
    are the unit of reuse, so each must stand alone.

### 2.8 Motion

- Animations are plain **Appear** (presetID 1) builds, 60–75 per big deck,
  with a few Disappear exits; one deck uses Fade. No motion paths, no
  emphasis effects.
- Slide transitions only where the DESI template supplies them.

### 2.9 What never appears (the negative space)

No bullet-heavy slides, no cards or tiles, no icon rows, no stat callouts,
no colour bars or sidebars (besides the dash), no cream/dark themes, no
native charts, no SmartArt, no speaker notes, no sections, no footers, no
drop shadows, no centred body text except on statement slides, no text
below 18 pt except credits.

## 3. Variation across eras (decisions the skill has to make)

| Aspect | 2021–22 Office | Own Grandview theme | DESI template | 2025–26 Office |
|---|---|---|---|---|
| Font | Calibri Light / Calibri | Grandview Display | Calibri / Helvetica | Aptos Display / Aptos |
| Title size | 44 | 40 | 36 | 44 |
| Body size | 28 (24) | 24 (18–20) | 24 (28) | 24–28 (18) |
| Accent dash | no | yes | no | no |
| Slide numbers | no | yes | yes | no |

Everything else (figure-first, annotation text, no bullets, Title Case,
summary formula, acknowledgements) is constant across all four.

## 4. Lessons from the two Claude Slides decks

Both were built without a design system (`designSystems: []`), Open Sans
throughout, every style hand-written per slide. Compared with the house
style:

**What matched and was worth keeping**

- Same anatomy: title top-left at a fixed position, one figure, one
  takeaway sentence under it, source line at the bottom. Titles Title Case,
  4–8 words, no periods.
- A progressive build done the house way (seven "A Toy Model for an
  Astronomical Survey" slides stepping through a numbered list with one
  item highlighted per slide).
- Acknowledgements slide with circular headshots, as in the own decks.
- Three idioms Biprateep then copied into the September stream talk: the
  coloured pipeline chain (Truth → Noise → Selection → Missingness →
  Observed), the "Physics Driven vs Data Driven" two-card comparison, and the
  equation whose terms are coloured to match the chain's boxes.

**What diverged**

- **Text too small for a talk.** In the Tabular deck 55 % of non-title
  characters are below 14 pt and only 25 % are ≥ 18 pt (own decks: 80–100 %
  ≥ 18 pt). Source lines are 12 pt grey; code is 12 pt JetBrains Mono.
  The Generative deck is better (58 % ≥ 18 pt) but still has 36 % at
  14–17 pt.
- **Too many words:** median 35–40 per slide, only 1 of 26 Tabular slides
  under 20 words (own decks: a third to a half of slides). Takeaway
  sentences run to two lines; the own decks use a 2–8-word bold phrase.
- **Figures smaller:** median coverage 0.33–0.36 with 0 and 2 slides above
  half the slide (own decks: 22–34 such slides in a long deck). The Tabular
  deck keeps 0.9 in side margins; the own decks run figures to the edge.
- **Speaker notes on every slide, ~100 words each.** Biprateep never writes
  notes.
- **Cards, boxes and tables:** 196–253 auto-shapes per deck and 8 tables in
  the Tabular deck versus 4–80 shapes and ≤ 1 table in the own decks.
- **No slide numbers, no accent dash, no summary/contact formula** (the
  Tabular deck ends on a "Thank You" resources slide; the Generative deck's
  summary lacks the contact line).
- Every text box is `normAutofit`, so text shrinks when it overflows; the
  own decks let boxes grow.
- Equations typeset as Latin Modern Math text rather than the Computer
  Modern images used in the own decks (acceptable, but the font must be
  embedded, as it was).
- Open Sans is not a font any own deck uses (all are Office or Microsoft
  365 fonts); it was Claude's default, not a choice.

## 5. Decisions (the author, 2026-10-21)

1. **Font: by target.** Sizes and weights are fixed everywhere (titles
   36–44 pt regular, body 18–28 pt, credits 8–11 pt). The face follows the
   target: Aptos / Aptos Display in .pptx, Noto Sans in Claude Slides, with
   Noto Sans Bengali for the Bengali name. Both are installed here.
2. **Targets: both.** Claude Slides when that artifact type is available,
   .pptx everywhere else, from one rule set. The .pptx path uses
   python-pptx on a bundled template deck, not pptxgenjs, so it runs in
   Codex and VS Code as well as Claude.
3. **Equations: native.** OMML in .pptx, converted from LaTeX by pandoc
   (via the `pypandoc_binary` wheel under uv; pandoc is not installed
   system-wide) and wrapped the way PowerPoint wraps its own equations, with
   a LaTeX-rendered fallback picture. The user chose this over LaTeX images.
   Correction found while building: Claude Slides runs no scripts and has no
   math markup, so KaTeX is impossible there. Its native equivalent is
   Unicode math in Latin Modern Math (as the Generative deck did), with an
   outline SVG from LaTeX for stacked math (fractions, limits, matrices).
4. **Chrome: blue dash and slide numbers on every content slide.** The
   Grandview house chrome: a short accent dash (1973EB) left-aligned under
   the title, a small number bottom-right. Title, statement and backup
   divider slides carry neither. The skill must state that this overrides
   the generic pptx skill's ban on accent lines under titles.
5. **Speaker notes: none** unless the user asks for them.
6. **Profile: text committed, assets local.** A committed profile holds the
   name in Latin and Bengali, email, handle, current affiliation and the
   closing formula. Logos, headshots and hero images live in a local,
   uncommitted folder that the profile points to.

**Revisions (the author, 2026-10-21 and 2026-10-22).** Decision 2 was
narrowed twice. First, Claude Slides became the default target and every
deck starts from a template deck carrying the profile. Then the PowerPoint
path was dropped entirely: the skill builds only the host's native deck,
and PowerPoint, PDF or Google Slides come from the host's export. With it
went decision 3's OMML route and decision 1's Aptos half; the native math
is the Unicode-plus-SVG route above, and the face is Noto Sans. The author
also asked for an alignment pass on every finished deck (centring, left
edges, alignment between slides), which became `scripts/check_deck.py`.
