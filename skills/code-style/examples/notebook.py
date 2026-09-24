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
# # Line depths from a synthetic spectrum
#
# Build a spectrum with two Gaussian absorption lines on a sloping continuum,
# divide out a running-median continuum, and check that the recovered line
# depths match the ones put in.
#
# In the percent format this title cell stands in for the module docstring.

# %% Imports
# Copyright 2026 The science-skills Authors.
# SPDX-License-Identifier: MIT

# /// script
# requires-python = ">=3.10"
# dependencies = ["numpy"]
# ///

import numpy as np
import numpy.typing as npt

# %% [markdown]
# ## Configuration
#
# Every constant is set once, here, and named in capitals.

# %% Configuration
N_PIXELS = 3000
WAVELENGTH_RANGE_ANGSTROM = (4000.0, 7000.0)
LINE_CENTERS_ANGSTROM = (4861.3, 6562.8)  # H-beta and H-alpha.
LINE_DEPTH = 0.6
LINE_SIGMA_ANGSTROM = 3.0
NOISE_SIGMA = 0.01
MEDIAN_WINDOW_PIXELS = 151
SEED = 20260924

# %% [markdown]
# ## Helpers
#
# Each function takes what it uses as arguments; none reads a notebook global.


# %% Helpers
def absorption_profile(
    wavelength: npt.NDArray[np.float64],
    center: float,
    depth: float,
    sigma: float,
) -> npt.NDArray[np.float64]:
    """Returns a Gaussian absorption line as a multiplicative profile.

    Args:
      wavelength: Wavelength grid in Angstrom, shape (n,).
      center: Line center in Angstrom.
      depth: Fractional depth at the center, between 0 and 1.
      sigma: Gaussian standard deviation in Angstrom.

    Returns:
      Array of shape (n,): 1 far from the line, 1 - depth at its center.
    """
    return 1.0 - depth * np.exp(-0.5 * ((wavelength - center) / sigma) ** 2)


def running_median(
    values: npt.NDArray[np.float64], window: int
) -> npt.NDArray[np.float64]:
    """Returns the running median of values over a centred window.

    Args:
      values: Samples on a uniform grid, shape (n,).
      window: Width of the window in samples; a positive odd integer.

    Returns:
      Array of shape (n,); the ends are padded with the end values.
    """
    padded = np.pad(values, window // 2, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window)
    medians: npt.NDArray[np.float64] = np.median(windows, axis=-1)
    return medians


# %% [markdown]
# ## Build the spectrum

# %% Build
rng = np.random.default_rng(SEED)
wavelength_angstrom = np.linspace(*WAVELENGTH_RANGE_ANGSTROM, N_PIXELS)
true_continuum = 1.0 + 1e-4 * (wavelength_angstrom - wavelength_angstrom[0])
flux = true_continuum.copy()
for line_center in LINE_CENTERS_ANGSTROM:
    flux *= absorption_profile(
        wavelength_angstrom, line_center, LINE_DEPTH, LINE_SIGMA_ANGSTROM
    )
flux += rng.normal(0.0, NOISE_SIGMA, N_PIXELS)

# %% [markdown]
# ## Normalize and measure the depths

# %% Normalize
normalized_flux = flux / running_median(flux, MEDIAN_WINDOW_PIXELS)
for line_center in LINE_CENTERS_ANGSTROM:
    nearest_pixel = np.argmin(np.abs(wavelength_angstrom - line_center))
    measured_depth = 1.0 - normalized_flux[nearest_pixel]
    print(f"{line_center} A: depth {measured_depth:.3f} (true {LINE_DEPTH})")
