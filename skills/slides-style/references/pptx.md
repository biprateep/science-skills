# PowerPoint Decks with slidestyle

## Setup

Copy three files next to the deck script and import the module, never its
names (code-style):

```bash
cp <skill-dir>/assets/slidestyle.py <skill-dir>/assets/template.pptx \
   <skill-dir>/assets/profile.json talk/
```

The deck script is a standalone jupytext percent script with its
dependencies declared inline (code-style, jupytext), so `uv run` builds it:

```python
# %% Imports
# /// script
# requires-python = ">=3.10"
# dependencies = ["python-pptx>=1.0", "lxml>=5", "pillow", "pypandoc_binary"]
# ///
import slidestyle

# %% Deck
deck = slidestyle.new_deck()
slidestyle.title_slide(deck, "**Lead Phrase:** Rest of the Title")
slide = slidestyle.content_slide(deck, "One Message per Slide")
slidestyle.figure(slide, "figs/result.png", alt="…")
slidestyle.save(deck, "talk.pptx")
```

Add `segno` to the dependencies for a QR code on the summary slide.
Equations need pandoc (the `pypandoc_binary` wheel supplies it) and, for the
fallback picture, `pdflatex` and `pdftocairo` (TeX Live and Poppler) or, as
a lower-fidelity stand-in, matplotlib.

## Building

| Call | Does |
|---|---|
| `new_deck(template=None)` | a deck on `template.pptx` |
| `title_slide(deck, title, subtitle=, hero=, hero_alt=, hero_fit=, hero_credit=, logos=)` | slide type 1 |
| `acknowledgements_slide(deck, people, funders=, title=, intro=)` | type 2; people are `Person` or `"person/…"` keys |
| `statement_slide(deck, content, size=40)` | type 3 |
| `quote_slide(deck, quote, attribution)` | type 4 |
| `content_slide(deck, title)` | a slide with the chrome; types 5-10 build on it |
| `summary_slide(deck, takeaways, title=, references=, qr_url=, qr_label=)` | type 11 |
| `divider_slide(deck, label="EXTRA SLIDES")`, `hide(slide)` | type 12 |
| `blank_slide(deck, kind)` | an empty slide, for anything else |
| `figure(slide, path, box=CONTENT_BOX, alt=, fit="contain", align="center")` | a figure in a box, aspect kept; `fit="cover"` crops to fill |
| `text(slide, content, left, top, width, height=None, size=24, align=, anchor=, bold=, color=)` | a free text box that grows to fit |
| `bullets(slide, items, left, top, width)` | a one-level list (summary and agenda only) |
| `arrow(slide, start, end)`, `line(slide, start, end, head=, weight=, color=, dashed=)` | annotation arrows and leader lines |
| `credit(slide, content, side="left", box=None)` | a 10 pt credit or citation |
| `equation(slide, latex, left, top, size=28, width=None, align=)` | a native, editable equation |
| `outline(slide, left, top, width, height, color=RED)` | an unfilled box to point at something |
| `photo(slide, path, left, top, diameter, alt=)` | a circular headshot |
| `logo_row(slide, paths, left, top, height, max_width=)` | logos at one height |
| `qr_image(slide, url, left, top, size)` | a QR code (needs segno) |
| `appear(slide, steps)` | Appear on click; a step is a shape or a list of shapes |
| `asset(key)`, `person(key)`, `load_profile()` | the profile and local assets |
| `title_case(title)` | the author's Title Case |
| `save(deck, path)` | write the .pptx |

Lengths are inches, sizes points. Useful constants: `CONTENT_BOX`,
`LEFT_HALF`, `RIGHT_HALF`, `TITLE_SIZE`, `BODY_SIZE` (24), `LABEL_SIZE`
(20), `SMALL_LABEL_SIZE` (18), `CREDIT_SIZE` (10), `RED`, `ACCENT`, `LINK`.

### Text markup

Every text argument takes a small markup, one paragraph per line:

| Markup | Gives |
|---|---|
| `**key phrase**` | bold |
| `*Photometry*` | italic (a defined term) |
| `!!Very expensive!!` | red emphasis |
| `==Next-Generation==` | accent blue (title-slide keyword) |
| `[arXiv:2112.03939](https://arxiv.org/abs/2112.03939)` | a green link |
| `$\gamma$` | inline OMML math |
| `\*` | a literal asterisk |

### Equations

`equation()` writes the math as PowerPoint writes its own equations: an
`mc:AlternateContent` whose choice is a text box holding OMML (`a14:m`) and
whose fallback is the same box filled with the LaTeX-rendered picture. The
OMML comes from pandoc (`latex_to_omml()`), so any LaTeX pandoc reads works:
`\frac`, `\int`, `\sum`, `\hat`, `\widetilde`, `\mathbf`, `\left( \right)`,
`\mathcal`, matrices. PowerPoint shows and edits the OMML in Cambria Math;
LibreOffice and previews show the picture. Inline `$…$` in `text()` works
the same way, with a Unicode rendering as the fallback.

The box takes its size from the rendered picture plus slack; Cambria Math
sets a little wider than Computer Modern, so leave room on the right.

### Builds

Prefer duplicated slides (a loop that redraws the slide with one more
item). Use `appear()` for two or three items arriving on one figure:

```python
label = slidestyle.text(slide, "Data points we have", 1.0, 5.5, 4.0)
pointer = slidestyle.arrow(slide, (2.0, 5.5), (3.0, 4.6))
slidestyle.appear(slide, [[label, pointer]])  # one click shows both
```

## Checking

```bash
uv run <skill-dir>/scripts/check_slides.py talk.pptx
python <skill-dir>/scripts/render_deck.py talk.pptx --outdir renders
```

`check_slides.py` exits 1 on any ERROR (`--strict`: on WARN too) and
`--allow-notes` accepts speaker notes when the user asked for them. It
reads the slide kinds that `slidestyle` records, so statement and title
slides are not asked for chrome. It can also review a deck made elsewhere;
there it infers the kinds.

Then look at every rendered slide:

- text overflowing its box or crossing another element;
- a title wrapping to two lines;
- a label away from what it names, an arrow pointing at nothing;
- a figure under a third of the slide;
- the credit line colliding with a figure.

The preview substitutes a different face for Aptos, so text widths are
approximate; keep a 10 % slack in every box.

## Editing an Existing Deck

Restyling a deck made elsewhere: run the checker on it first, and use its
findings as the work list. Structural edits (adding, deleting, reordering
slides) and template-level edits go through the pptx skill's unpack / edit
XML / pack workflow; then fix fonts, sizes, titles and chrome slide by
slide, and check again. A deck on a collaboration template keeps that
template's layouts; `slidestyle`'s slide-type functions need the house
template's Title / Content / Blank layouts, so on another template add the
content with `text()`, `figure()`, `arrow()` and `credit()` on slides made
from its own layouts.

## Regenerating the Template

```bash
uv run <skill-dir>/scripts/build_template.py
```

rebuilds `assets/template.pptx` from python-pptx's default deck. Edit the
constants at the top of `build_template.py` (fonts, colours, geometry), not
the .pptx, and keep `slidestyle.py`'s constants in step.
