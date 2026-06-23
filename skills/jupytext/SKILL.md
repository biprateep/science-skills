---
name: jupytext
description: >-
  Write every Python script (.py) in the Jupytext "percent" format (py:percent)
  so it doubles as an interactive Jupyter notebook (VS Code, JupyterLab,
  PyCharm, Spyder) while remaining a runnable script with clean version-control
  diffs. This is the DEFAULT for all Python you generate or edit — apply it
  unless the user explicitly asks for a plain script. Use whenever creating or
  editing a .py file, or when the user mentions: write a script, data analysis,
  plotting, visualization, pipeline, prototype, explore, notebook, jupyter,
  jupytext, percent format, interactive script, run cell by cell.
license: MIT
metadata:
  version: "1.0.0"
---

# Jupytext Percent Format for Python Scripts

## Overview

The **Jupytext percent format** (`py:percent`) lets a single `.py` file serve
two purposes at once: it runs as an ordinary Python script *and* opens as an
interactive, cell-by-cell Jupyter notebook in VS Code, JupyterLab, PyCharm
Professional, and Spyder. Unlike JSON-based `.ipynb` files, it produces clean,
reviewable version-control diffs.

This skill is **harness-agnostic**: it constrains only *how you write Python
text*. It needs no special tools beyond whatever file-writing capability your
agent already has (and, optionally, a shell to validate). Nothing here assumes a
particular agent, editor, or operating system.

---

## When to Apply

<HARD-RULE>
The percent format is the DEFAULT for every `.py` file you write or edit. Use it
unless the user explicitly asks for a plain script. When in doubt, use it.
</HARD-RULE>

This covers, among others:
- Data analysis, exploration, and cleaning
- Plotting and visualization
- Machine-learning pipelines and prototyping
- Scientific computation and simulation
- Any script that benefits from cell-by-cell execution or inline narrative

The skill also activates on these cues in the user's request: `write a script`,
`analyze data`, `create a pipeline`, `plot`, `visualization`, `explore`,
`prototype`, `notebook`, `jupyter`, `jupytext`, `percent format`,
`interactive script`, `run cell by cell`.

**Only exception:** the user explicitly requests a plain `.py` (e.g. "no
notebook formatting", "just a normal script", a library module / package source
file, or a `setup.py`-style file). Then write conventional Python.

---

## Format Specification

### 1. YAML Header (always include)

Begin every file with this commented YAML block. It declares the format
explicitly and pairs the script with an `.ipynb`, so editors and the `jupytext`
tool behave unambiguously:

```python
# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---
```

Rules for the header:
- The `# ---` delimiters are the first and last lines of the block.
- Every line inside is a `#`-prefixed comment with exact 2-space-per-level YAML
  indentation.
- `formats: ipynb,py:percent` declares pairing with an `.ipynb`. The two stay in
  sync when you use Jupyter with the jupytext plugin or run `jupytext --sync` —
  it does **not** auto-generate the `.ipynb` merely by running `python file.py`.
- `kernelspec` tells Jupyter which kernel to use.

> Technical note: jupytext can auto-detect percent format from the `# %%`
> markers alone, so the header is not strictly required for a file to open as a
> notebook. We always include it anyway, for explicit, unambiguous tooling and
> reliable `.ipynb` pairing.

### 2. Cell Delimiters

<HARD-RULE>
Every cell begins with a `# %%` marker, and the first content after the YAML
header MUST be a `# %%` delimiter. Content before the first delimiter is
ambiguous and may be dropped or misattributed.
</HARD-RULE>

The full marker syntax is `# %% [optional title] [cell type] [key="value"]`:

| Cell Type    | Delimiter                          | Content                  |
|--------------|------------------------------------|--------------------------|
| **Code**     | `# %%` or `# %% Optional Title`     | Python code              |
| **Markdown** | `# %% [markdown]`                  | Documentation (commented)|
| **Raw**      | `# %% [raw]`                       | Unprocessed text         |

### 3. Markdown Cells

The default is **line comments**: prefix each line with `# ` (hash + space):

```python
# %% [markdown]
# # Section Title
#
# A paragraph of explanatory text supporting **bold**, *italic*, `code`,
# and all standard markdown.
#
# - Bullet one
# - Bullet two
```

**Alternative — triple-quoted block.** Use `"""..."""` when the markdown itself
contains lines that look like cell markers (e.g. text starting with `# %%`),
which would otherwise be misread as boundaries:

```python
# %% [markdown]
"""
# Section Title

This block uses triple-quote delimiters instead of `#` comments.
"""
```

<HARD-RULE>
Pick ONE markdown style — comment-prefixed or triple-quoted — and use it
consistently throughout a file. Mixing the two within one file produces
confusing round-trip behavior.
</HARD-RULE>

### 4. Code Cells

Code cells start with `# %%` and hold standard Python. A title after `# %%` is
optional but **strongly encouraged** for navigation:

```python
# %% Imports
import numpy as np
import matplotlib.pyplot as plt

# %% Generate data
x = np.linspace(0, 2 * np.pi, 200)
y = np.sin(x)
```

### 5. Cell Metadata

Attach metadata as `key="value"` on the marker line, after any title and cell
type:

```python
# %% [markdown] tags=["hide-input"]
# This markdown cell carries metadata.

# %% Expensive step tags=["skip-execution"]
expensive_computation()
```

### 6. Blank Lines Between Cells

Separate each cell from the next with a single blank line for readability and
clean diffs. Jupytext splits on the `# %%` markers and tolerates zero or several
blank lines, so this is a style convention rather than a hard requirement — but
keep it consistent:

```python
# %% [markdown]
# # Title
                          # ← one blank line
# %% Imports
import numpy as np
                          # ← one blank line
# %% [markdown]
# ## Next section
```

### 7. Magic Commands

Jupyter magics (`%timeit`, `%%bash`, `%matplotlib inline`, …) are written
commented-out in the script so the file stays valid Python. Jupytext uncomments
them automatically when the file is opened as a notebook:

```python
# %%
# %matplotlib inline
# %timeit np.sort(arr)
```

---

## Structure & Narrative

### Meaningful Chunking

<HARD-RULE>
Do NOT write monolithic cells. Split code into small, single-purpose cells —
each one does ONE thing. A cell with 50+ lines is an anti-pattern; aim for
roughly 5–15 lines per code cell.
</HARD-RULE>

Give each of these its own cell:
- Imports
- Configuration / constants
- Each data-processing step
- Each visualization
- Model definition
- Training / fitting
- Evaluation / results

### Notebook-Style Narrative

Interleave code cells with `# %% [markdown]` cells that explain intent. The
file should read like a well-documented notebook:

1. **Title cell** (markdown) — title and one-line description
2. **Import cell** (code) — all imports
3. **Explanation cell** (markdown) — what the next block does and why
4. **Code cell** — the computation
5. Repeat 3–4 for each logical block

### Self-Contained Execution

Every script must run top-to-bottom as `python script.py` with no edits. Do not
depend on out-of-order cell execution or any notebook-only state for
correctness.

---

## Anti-Patterns

If you catch yourself doing any of these, stop and fix it before finishing:

- **Forgetting the YAML header.** Every file starts with the `# ---` block.
- **Missing the first `# %%`.** The first content after the header must be a
  `# %%` or `# %% [markdown]` delimiter.
- **Monolithic cells.** Break long cells into 5–15-line logical chunks with
  markdown between them.
- **Code-only scripts.** Each logical section needs a markdown cell explaining
  what comes next.
- **Mixing markdown styles.** One style per file — comment OR triple-quote.
- **Literal `# %%` inside code or strings.** It will be misread as a cell
  boundary; reword, or move such markdown into a triple-quoted cell.
- **Untitled cells.** Prefer descriptive titles: `# %% Load and clean dataset`.

---

## Self-Check Before Finishing

Before presenting any `.py` file, confirm:

- [ ] Starts with the `# ---` YAML header block.
- [ ] First content after the header is a `# %%` / `# %% [markdown]` delimiter.
- [ ] Code is split into small, single-purpose cells — no monolith.
- [ ] Code cells are interleaved with `# %% [markdown]` narrative cells.
- [ ] Exactly one markdown style is used (comment `#` *or* triple-quote).
- [ ] Runs top-to-bottom as `python script.py` with no notebook-only state.

**Optional validation** — if you have a shell and `jupytext` is installed, a
clean conversion proves the file is well-formed (a nonzero exit means it is
malformed):

```bash
jupytext --to ipynb script.py    # writes script.ipynb; must succeed
```

---

## Complete Example

A minimal but complete, correctly formatted file. A copy also lives in
`examples/minimal_example.py`, which you can open or run as a reference.

```python
# ---
# jupyter:
#   jupytext:
#     formats: ipynb,py:percent
#     text_representation:
#       extension: .py
#       format_name: percent
#       format_version: '1.3'
#       jupytext_version: 1.16.0
#   kernelspec:
#     display_name: Python 3 (ipykernel)
#     language: python
#     name: python3
# ---

# %% [markdown]
# # Signal Processing Example
#
# Generate a noisy signal, apply a low-pass filter, and visualize the result.
# Written in the Jupytext percent format for interactive notebook compatibility.

# %% Imports
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt

# %% [markdown]
# ## 1. Generate Synthetic Data
#
# A 5 Hz sine wave with additive Gaussian noise simulates a measured signal.
# The seed makes the run reproducible.

# %% Generate noisy signal
rng = np.random.default_rng(42)
fs = 500  # Sampling frequency (Hz)
t = np.linspace(0, 1, fs, endpoint=False)
signal_clean = np.sin(2 * np.pi * 5 * t)
signal_noisy = signal_clean + rng.normal(0, 0.5, len(t))

# %% [markdown]
# ## 2. Apply Butterworth Low-Pass Filter
#
# A 4th-order Butterworth filter with a 10 Hz cutoff removes high-frequency
# noise while preserving the 5 Hz signal.

# %% Filter the signal
cutoff = 10  # Hz
order = 4
b, a = butter(order, cutoff / (fs / 2), btype='low')
signal_filtered = filtfilt(b, a, signal_noisy)

# %% [markdown]
# ## 3. Visualize Results
#
# Overlay the clean, noisy, and filtered signals to assess filter performance.

# %% Plot comparison
fig, ax = plt.subplots(figsize=(10, 5))
ax.plot(t, signal_noisy, alpha=0.4, label='Noisy signal', color='gray')
ax.plot(t, signal_clean, linewidth=2, label='True signal', color='tab:blue')
ax.plot(t, signal_filtered, linewidth=2, label='Filtered', color='tab:red',
        linestyle='--')
ax.set_xlabel('Time (s)')
ax.set_ylabel('Amplitude')
ax.set_title('Low-Pass Butterworth Filter: Noise Removal')
ax.legend()
plt.tight_layout()
plt.savefig('filter_comparison.png', dpi=150)
plt.show()
```

---

## Quick Reference Card

| Element          | Syntax                                          |
|------------------|-------------------------------------------------|
| File header      | `# ---` … `# ---` (commented YAML block)        |
| Code cell        | `# %%` or `# %% Title`                          |
| Markdown cell    | `# %% [markdown]`                               |
| Raw cell         | `# %% [raw]`                                    |
| Marker order     | `# %% [title] [cell type] [key="value"]`        |
| Cell metadata    | `# %% [markdown] tags=["hide-input"]`           |
| Markdown content | `# ` prefix per line (or one triple-quote block)|
| Cell separation  | One blank line (style convention)               |
| Magic commands   | Commented: `# %timeit ...`                      |
