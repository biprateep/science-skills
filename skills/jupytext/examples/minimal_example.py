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
# # Minimal Jupytext Example
#
# This file demonstrates the correct structure of a Python script
# in the Jupytext percent format. It can be:
# - Run as `python minimal_example.py`
# - Opened as a Jupyter notebook in VS Code, JupyterLab, or PyCharm

# %% Imports
import numpy as np

# %% [markdown]
# ## Generate Data
#
# Create a simple array and compute summary statistics. The seeded generator
# keeps the output reproducible across runs.

# %% Generate and summarize
rng = np.random.default_rng(42)
data = rng.standard_normal(1000)
print(f"Mean: {data.mean():.4f}")
print(f"Std:  {data.std():.4f}")
print(f"Min:  {data.min():.4f}")
print(f"Max:  {data.max():.4f}")

# %% [markdown]
# ## Conclusion
#
# This minimal example shows the three essential elements:
# 1. YAML header (`# ---` block)
# 2. Cell delimiters (`# %%` and `# %% [markdown]`)
# 3. Interleaved code and documentation
