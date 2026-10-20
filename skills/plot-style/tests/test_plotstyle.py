"""Regression tests for plot helper numerical contracts."""

import importlib.util
import pathlib
import sys

import matplotlib.pyplot as plt
import numpy as np
import pytest

_MODULE_PATH = pathlib.Path(__file__).parents[1] / "assets" / "plotstyle.py"
_SPEC = importlib.util.spec_from_file_location("plotstyle", _MODULE_PATH)
plotstyle = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = plotstyle
_SPEC.loader.exec_module(plotstyle)


def test_explicit_bins_exclude_underflow_and_overflow():
    edges, values = plotstyle.binned_quantiles(
        [-100, 0.5, 100], [-1000, 10, 1000], bins=[0, 1]
    )
    np.testing.assert_array_equal(edges, [0, 1])
    np.testing.assert_array_equal(values, [[10], [10], [10]])


def test_edges_follow_histogram_convention():
    _, values = plotstyle.binned_quantiles(
        [0, 1, 2], [10, 20, 30], bins=[0, 1, 2], q=[50]
    )
    np.testing.assert_array_equal(values, [[10, 25]])


def test_empty_explicit_bins_return_nan_and_nonfinite_pairs_are_ignored():
    _, empty = plotstyle.binned_quantiles([], [], bins=[0, 1, 2])
    assert empty.shape == (3, 2)
    assert np.isnan(empty).all()
    _, values = plotstyle.binned_quantiles(
        [0.5, np.nan, 0.6, np.inf], [10, 100, np.nan, 200], bins=[0, 1]
    )
    np.testing.assert_array_equal(values, [[10], [10], [10]])


@pytest.mark.parametrize("equal_count", [True, False])
def test_automatic_bins_and_repeated_coordinates(equal_count):
    edges, values = plotstyle.binned_quantiles(
        [0, 0, 0, 1], [1, 3, 5, 7], nbins=3, equal_count=equal_count
    )
    assert np.all(np.diff(edges) > 0)
    if equal_count:
        np.testing.assert_array_equal(edges, [0, 1])
        assert values[1, 0] == 4
    else:
        assert values[1, 0] == 3
        assert values[1, -1] == 7


@pytest.mark.parametrize(
    "kwargs",
    [
        {"x": [], "y": []},
        {"x": [1, 1], "y": [2, 3]},
        {"x": [0, 1], "y": [1]},
        {"x": [[0, 1]], "y": [[1, 2]]},
        {"nbins": 0},
        {"nbins": 1.5},
        {"nbins": True},
        {"bins": []},
        {"bins": [1]},
        {"bins": [1, 0]},
        {"bins": [0, 0, 1]},
        {"bins": [0, np.inf]},
        {"q": []},
        {"q": [-1]},
        {"q": [101]},
        {"q": [np.nan]},
    ],
)
def test_invalid_binning_inputs_raise(kwargs):
    inputs = {"x": [0, 1], "y": [2, 3], **kwargs}
    with pytest.raises(ValueError):
        plotstyle.binned_quantiles(**inputs)


def test_constant_values_with_explicit_bins():
    _, values = plotstyle.binned_quantiles([1, 1], [2, 4], bins=[0, 2], q=[50])
    np.testing.assert_array_equal(values, [[3]])


def test_step_materializes_generator_heights_and_bands_once():
    fig, ax = plt.subplots()
    try:
        plotstyle.better_step(
            [0, 1, 2],
            (value for value in [2, 4]),
            ((value for value in [1, 3]), (value for value in [3, 5])),
            ax=ax,
        )
        np.testing.assert_array_equal(ax.lines[0].get_xdata(), [0, 1, 1, 2])
        np.testing.assert_array_equal(ax.lines[0].get_ydata(), [2, 2, 4, 4])
        assert len(ax.collections) == 1
    finally:
        plt.close(fig)


@pytest.mark.parametrize(
    ("edges", "heights", "bounds"),
    [
        ([0, 1, 2], [1], None),
        ([0, 1], [[1]], None),
        ([0, 0], [1], None),
        ([0, 1], [1], ([0, 1], [2])),
    ],
)
def test_invalid_step_does_not_partially_draw(edges, heights, bounds):
    fig, ax = plt.subplots()
    try:
        with pytest.raises(ValueError):
            plotstyle.better_step(edges, heights, bounds, ax=ax)
        assert not ax.lines
        assert not ax.collections
    finally:
        plt.close(fig)
