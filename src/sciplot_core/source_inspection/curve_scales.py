"""Infer readable linear or logarithmic scales from normalized curve values."""

from __future__ import annotations

import math

import pandas as pd

from sciplot_core.source_tables import CurveSeries


def _axis_dynamic_range(
    curves: tuple[CurveSeries, ...],
    axis: str,
) -> tuple[float, bool] | None:
    positive_min: float | None = None
    positive_max: float | None = None
    all_positive = True
    for curve in curves:
        values = pd.to_numeric(curve.data[axis], errors="coerce").dropna()
        if values.empty:
            continue
        positive = values[values > 0]
        if positive.empty:
            all_positive = False
            continue
        if len(positive) != len(values):
            all_positive = False
        current_min = float(positive.min())
        current_max = float(positive.max())
        positive_min = (
            current_min if positive_min is None else min(positive_min, current_min)
        )
        positive_max = (
            current_max if positive_max is None else max(positive_max, current_max)
        )
    if positive_min is None or positive_max is None or positive_max <= 0:
        return None
    ratio = positive_max / positive_min if positive_min > 0 else 0.0
    return math.log10(ratio) if ratio > 0 else 0.0, all_positive


def _recommend_axis(
    curves: tuple[CurveSeries, ...],
    axis: str,
    *,
    label: str,
    min_orders: float,
) -> tuple[str, str]:
    summary = _axis_dynamic_range(curves, axis)
    if summary is None:
        return (
            "linear",
            f"{label} does not show a stable positive range, so linear stays on.",
        )
    orders, all_positive = summary
    if all_positive and orders >= min_orders:
        return (
            "log",
            f"{label} spans about {orders:.1f} orders of magnitude, so log is recommended.",
        )
    if not all_positive:
        return (
            "linear",
            f"{label} includes non-positive or near-zero values, so linear stays on.",
        )
    return (
        "linear",
        f"{label} varies by about {orders:.1f} orders of magnitude, and linear stays easier to read.",
    )


def recommend_curve_scales(
    curves: tuple[CurveSeries, ...],
) -> tuple[str, str, tuple[str, ...]]:
    """Return X/Y scales plus the human-readable evidence for both choices."""

    xscale, x_signal = _recommend_axis(
        curves,
        "x",
        label="X axis",
        min_orders=2.0,
    )
    yscale, y_signal = _recommend_axis(
        curves,
        "y",
        label="Y axis",
        min_orders=2.3,
    )
    return xscale, yscale, (x_signal, y_signal)


__all__ = ["recommend_curve_scales"]
