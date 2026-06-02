---
name: jupytext
description: >-
  Write Python files in the Jupytext percent format so they can be opened as
  interactive Jupyter notebooks. ACTIVATE this skill whenever writing a Python
  script (.py) that performs data analysis, plotting, prototyping, exploration,
  or any workflow that benefits from cell-by-cell execution. Also activate when
  the user mentions "jupytext", "notebook format", "percent format",
  "interactive script", "write a script", "analyze data", "create a pipeline",
  "plot", "explore", or "prototype".
---

# Jupytext Percent Format for Python Scripts

## Overview

Every Python script you write must use the **Jupytext percent format**
(`py:percent`). This format makes `.py` files openable as interactive Jupyter
notebooks in VS Code, JupyterLab, PyCharm Professional, and Spyder — while
remaining fully executable as standard Python scripts and producing clean
version-control diffs.

## When to Use This Skill

Apply this format to **every** `.py` file you create unless the user explicitly
requests a plain script. This includes:
- Data analysis and exploration scripts
- Plotting and visualization scripts
- Machine learning pipelines and prototyping
- Scientific computation and simulation
- Any script that benefits from cell-by-cell execution or inline documentation

## Trigger Words

Activate this skill when the user's message contains any of:
`write a script`, `analyze data`, `create a pipeline`, `plot`, `explore`,
`prototype`, `jupytext`, `notebook format`, `percent format`,
`interactive script`, `data analysis`, `visualization script`,
`run cell by cell`, `jupyter-compatible`.

---

## Format Specification

### 1. YAML Header (MANDATORY)

<HARD-RULE>
Every file MUST begin with a commented YAML header block. This block tells
Jupytext and editors how to interpret the file. Without it, the file will NOT
be recognized as a notebook.
</HARD-RULE>

Use this exact template, adjusting only the `jupytext_version` if needed:

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

**Rules for the header:**
- The `# ---` delimiters must be the first and last lines of the block
- Every line inside the block must be a `#`-prefixed comment
- The YAML indentation inside comments must be exact (2-space indent per level)
- `formats: ipynb,py:percent` enables automatic pairing with `.ipynb` files
- The `kernelspec` section ensures Jupyter uses the correct Python kernel

### 2. Cell Delimiters

Every cell begins with a `# %%` marker. There are three cell types:

| Cell Type | Delimiter | Content |
|-----------|-----------|---------|
| **Code** | `# %%` or `# %% Optional Title` | Python code |
| **Markdown** | `# %% [markdown]` | Documentation (commented) |
| **Raw** | `# %% [raw]` | Unprocessed text (commented) |

### 3. Markdown Cells

Use **line comments** (`#`) for markdown cell content. Each line of markdown
must be prefixed with `#` followed by a space:

```python
# %% [markdown]
# # Section Title
#
# This is a paragraph of explanatory text. It supports **bold**,
# *italic*, `code`, and all standard markdown syntax.
#
# - Bullet point one
# - Bullet point two
```

**Alternative: Triple-quote markers.** Use `"""..."""` when the markdown
contains content that could conflict with comment syntax (e.g., lines
starting with `# %%`):

```python
# %% [markdown]
"""
# Section Title

This uses triple-quote delimiters. Useful when markdown content might
contain lines that look like cell boundaries.
"""
```

<HARD-RULE>
Do NOT mix comment-style and triple-quote-style within the same file. Pick one
style and use it consistently throughout the entire script.
</HARD-RULE>

### 4. Code Cells

Code cells start with `# %%` and contain standard Python code:

```python
# %% Imports
import numpy as np
import matplotlib.pyplot as plt

# %% Data Generation
x = np.linspace(0, 2 * np.pi, 200)
y = np.sin(x)
```

**Titles are optional** but strongly encouraged for navigation. The title
appears after `# %%` on the same line.

### 5. Cell Metadata

Cell metadata uses `key="value"` syntax on the delimiter line:

```python
# %% [markdown] tags=["hide-input"]
# This cell has metadata attached.

# %% tags=["skip-execution"]
expensive_computation()
```

### 6. Blank Lines Between Cells

<HARD-RULE>
Separate every cell from the next with exactly ONE blank line. This is required
for clean round-trip conversion between `.py` and `.ipynb` formats.
</HARD-RULE>

```python
# %% [markdown]
# # Title
                          # ← exactly one blank line
# %% Imports
import numpy as np
                          # ← exactly one blank line
# %% [markdown]
# ## Next section
```

### 7. Magic Commands

Jupyter magic commands (`%timeit`, `%%bash`, etc.) are automatically commented
out in the percent format to keep the file valid Python:

```python
# %%
# %matplotlib inline
# %timeit np.sort(arr)
```

Jupytext handles the round-trip conversion automatically — the magics will be
uncommented when opened as a notebook.

---

## Structural Requirements

### Meaningful Chunking

<HARD-RULE>
Do NOT write monolithic scripts. Divide code into small, logical, meaningful
cells. Each cell should do ONE thing.
</HARD-RULE>

**Required cell separation:**
- Imports → own cell
- Configuration / constants → own cell
- Each data processing step → own cell
- Each visualization → own cell
- Model definition → own cell
- Training / fitting → own cell
- Evaluation / results → own cell

### Notebook-Style Narrative

Interleave code cells with markdown cells that explain intent and logic.
The script should read like a well-documented notebook:

1. **Title cell** (markdown): Script title and description
2. **Import cell** (code): All imports
3. **Explanation cell** (markdown): What the next code block does and why
4. **Code cell**: The actual computation
5. Repeat steps 3–4 for each logical block

### Self-Contained Execution

Every script must be runnable top-to-bottom as `python script.py` without
modification. Do not rely on notebook-only features (like cell execution order)
for correctness.

---

## Anti-Patterns

<HARD-RULE>
These are common mistakes. If you catch yourself doing any of these, STOP and
fix immediately.
</HARD-RULE>

- **"Forgetting the YAML header."** Every file MUST start with the `# ---`
  header block. A file without it will not be recognized as a jupytext
  notebook by VS Code or JupyterLab.

- **"Missing the `# %%` before the first code."** The very first code or
  markdown content after the YAML header MUST be preceded by a `# %%` or
  `# %% [markdown]` delimiter. Content before the first delimiter is
  ambiguous.

- **"Writing monolithic cells."** A single cell with 50+ lines of code is
  an anti-pattern. Break it into logical chunks of 5–15 lines each with
  explanatory markdown between them.

- **"Skipping markdown cells."** Do not write code-only scripts. Every
  logical section needs a markdown cell explaining what comes next.

- **"Mixing comment and triple-quote markdown styles."** Pick one per file.
  Mixing causes confusing round-trip behavior.

- **"No blank line between cells."** Every `# %%` marker must be preceded
  by exactly one blank line (except the first cell after the YAML header).

- **"Using `# %%` inside strings or comments."** The literal string `# %%`
  inside code will be misinterpreted as a cell boundary. Escape or reword.

- **"Omitting cell titles."** Untitled cells make navigation difficult.
  Always add a descriptive title: `# %% Load and clean dataset`.

---

## Complete Example

Below is a minimal but complete example of a properly formatted file:

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
# This script demonstrates generating a noisy signal, applying a filter,
# and visualizing the results. It uses the Jupytext percent format for
# interactive notebook compatibility.

# %% Imports
import numpy as np
import matplotlib.pyplot as plt
from scipy.signal import butter, filtfilt

# %% [markdown]
# ## 1. Generate Synthetic Data
#
# We create a sine wave at 5 Hz with additive Gaussian noise to simulate
# a realistic measured signal.

# %% Generate noisy signal
np.random.seed(42)
fs = 500  # Sampling frequency (Hz)
t = np.linspace(0, 1, fs, endpoint=False)
signal_clean = np.sin(2 * np.pi * 5 * t)
noise = np.random.normal(0, 0.5, len(t))
signal_noisy = signal_clean + noise

# %% [markdown]
# ## 2. Apply Butterworth Low-Pass Filter
#
# A 4th-order Butterworth filter with a 10 Hz cutoff removes
# high-frequency noise while preserving the 5 Hz signal.

# %% Filter the signal
cutoff = 10  # Hz
order = 4
b, a = butter(order, cutoff / (fs / 2), btype='low')
signal_filtered = filtfilt(b, a, signal_noisy)

# %% [markdown]
# ## 3. Visualize Results
#
# We overlay the original clean signal, the noisy measurement, and the
# filtered output to assess filter performance.

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

| Element | Syntax |
|---------|--------|
| File header | `# ---` ... `# ---` (YAML block) |
| Code cell | `# %%` or `# %% Title` |
| Markdown cell | `# %% [markdown]` |
| Raw cell | `# %% [raw]` |
| Cell metadata | `# %% [markdown] key="value"` |
| Cell separation | Exactly 1 blank line |
| Markdown content | `# ` prefix on each line |
| Magic commands | Commented: `# %timeit ...` |
