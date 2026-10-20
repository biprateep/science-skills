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
# # Measurement summary
# Read finite measurements and compute their arithmetic mean.

# %% Imports
import json
import math
import pathlib

# %% Load measurements
values = json.loads(
    pathlib.Path("measurements.json").read_text(encoding="utf-8")
)

# %% Compute and save
count = len(values)
total = math.fsum(values)
result = {
    "count": count,
    "total": total,
    "mean": total / count if count else None,
}
pathlib.Path("results.json").write_text(
    json.dumps(result) + "\n", encoding="utf-8"
)

# %% [markdown]
# An empty list has no defined arithmetic mean, so its mean is JSON null.
