"""Summarizes finite measurements and manages caller-owned labels."""

import math


def summarize(values: list[float]) -> dict[str, float]:
    """Returns the mean and minimum of finite measurements.

    Args:
        values: Nonempty finite measurements; not modified.

    Returns:
        The arithmetic mean and minimum, in the input units.

    Raises:
        ValueError: If values is empty.
    """
    if not values:
        raise ValueError("values must not be empty")
    return {"mean": math.fsum(values) / len(values), "minimum": min(values)}


def append_label(label: str, labels: list[str] | None = None) -> list[str]:
    """Appends a label to an existing or freshly allocated list.

    Args:
        label: The label to append.
        labels: Caller-owned labels, or None for a fresh list.

    Returns:
        The supplied list, or a fresh list, containing the appended label.
    """
    if labels is None:
        labels = []
    labels.append(label)
    return labels
