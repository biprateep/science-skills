# Copyright 2026 The science-skills Authors.
# SPDX-License-Identifier: MIT
"""Continuum normalization of one-dimensional spectra.

The continuum is estimated with a running median, which is robust to
absorption and emission lines narrower than its window. Wavelengths are in
Angstrom; the flux density may be in any unit, and the normalized flux is
dimensionless.

Typical usage example:

  spectrum = continuum.load_spectrum(pathlib.Path("target.npz"))
  normalized = continuum.normalize(spectrum, window=101)

Run as a program, it normalizes the spectrum in one .npz file and writes the
result to another:

  python continuum.py target.npz target_normalized.npz --window 101
"""

import argparse
from collections.abc import Sequence
import dataclasses
import logging
import pathlib
import sys
from typing import TypeAlias

import numpy as np
import numpy.typing as npt

_logger = logging.getLogger(__name__)

# The running-median window in pixels. Odd, so that each window is centred on
# its pixel.
DEFAULT_WINDOW = 101

FloatArray: TypeAlias = npt.NDArray[np.float64]


class ShapeMismatchError(ValueError):
    """The arrays of a spectrum do not share one shape."""


@dataclasses.dataclass(frozen=True)
class Spectrum:
    """A one-dimensional spectrum on a fixed wavelength grid.

    Attributes:
      wavelength: Wavelength of each pixel in Angstrom, increasing, shape
        (n_pixels,).
      flux: Flux density of each pixel, shape (n_pixels,).
      ivar: Inverse variance of the flux, shape (n_pixels,); zero marks a
        masked pixel.
    """

    wavelength: FloatArray
    flux: FloatArray
    ivar: FloatArray

    def __post_init__(self) -> None:
        """Checks that the three arrays share one shape."""
        shapes = {self.wavelength.shape, self.flux.shape, self.ivar.shape}
        if len(shapes) != 1:
            raise ShapeMismatchError(f"Arrays have different shapes: {shapes}")

    @property
    def snr(self) -> FloatArray:
        """The signal-to-noise ratio of each pixel; zero where masked."""
        return self.flux * np.sqrt(self.ivar)


def running_median(values: FloatArray, window: int) -> FloatArray:
    """Returns the running median of values over a centred window.

    The ends of the array are padded with the end values, so the output has
    the shape of the input.

    Args:
      values: Samples on a uniform grid, shape (n,), with n > 0.
      window: Width of the window in samples; a positive odd integer.

    Returns:
      Array of shape (n,) holding the median of each window.
    """
    if not values.size:
        raise ValueError("values is empty.")
    if window <= 0 or window % 2 == 0:
        raise ValueError(f"window must be a positive odd integer: {window=}")
    padded = np.pad(values, window // 2, mode="edge")
    windows = np.lib.stride_tricks.sliding_window_view(padded, window)
    medians: FloatArray = np.median(windows, axis=-1)
    return medians


def normalize(spectrum: Spectrum, window: int = DEFAULT_WINDOW) -> Spectrum:
    """Divides a spectrum by its running-median continuum.

    Masked pixels are filled by linear interpolation before the median is
    taken, so that they do not drag the continuum towards zero; they stay
    masked in the result.

    Args:
      spectrum: The spectrum to normalize.
      window: Width of the running median in pixels; see running_median.

    Returns:
      A new Spectrum whose flux is dimensionless and whose inverse variance
      is scaled to match.

    Raises:
      ValueError: If every pixel is masked.
    """
    good = spectrum.ivar > 0
    if not good.any():
        raise ValueError("Every pixel is masked; there is no continuum.")
    filled = np.interp(
        spectrum.wavelength, spectrum.wavelength[good], spectrum.flux[good]
    )
    continuum = running_median(filled, window)
    return Spectrum(
        wavelength=spectrum.wavelength,
        flux=spectrum.flux / continuum,
        ivar=spectrum.ivar * continuum**2,
    )


def load_spectrum(path: pathlib.Path) -> Spectrum:
    """Reads a spectrum from an .npz file.

    Args:
      path: The .npz file to read, as written by save_spectrum.

    Returns:
      The spectrum, with float64 arrays.

    Raises:
      KeyError: If the file lacks the wavelength, flux or ivar array.
      ShapeMismatchError: If those arrays differ in shape.
    """
    with np.load(path) as arrays:
        return Spectrum(
            wavelength=arrays["wavelength"].astype(np.float64),
            flux=arrays["flux"].astype(np.float64),
            ivar=arrays["ivar"].astype(np.float64),
        )


def save_spectrum(spectrum: Spectrum, path: pathlib.Path) -> None:
    """Writes a spectrum to an .npz file that load_spectrum can read.

    Args:
      spectrum: The spectrum to write.
      path: The file to create or overwrite.
    """
    np.savez(
        path,
        wavelength=spectrum.wavelength,
        flux=spectrum.flux,
        ivar=spectrum.ivar,
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Normalizes the spectrum in one .npz file and writes it to another.

    Args:
      argv: Command-line arguments after the program name; None reads
        sys.argv.

    Returns:
      The exit status.
    """
    parser = argparse.ArgumentParser(description="Continuum-normalize.")
    parser.add_argument("source", type=pathlib.Path)
    parser.add_argument("destination", type=pathlib.Path)
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    arguments = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO)
    spectrum = load_spectrum(arguments.source)
    save_spectrum(normalize(spectrum, arguments.window), arguments.destination)
    _logger.info(
        "Wrote %s (window of %d pixels).",
        arguments.destination,
        arguments.window,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
