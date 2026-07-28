"""Compute TGA, extrema-position, and steepest-drop curve metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import numpy as np
import pandas as pd

from sciplot_core.source_tables import read_raw_table
from sciplot_core.materials_rules.tokens import (
    normalize_token,
)
from sciplot_core.materials_rules.metric_tables import (
    _metric,
    _read_labeled_paired_curve_table,
)


def _raw_table(path: Path) -> pd.DataFrame:
    return read_raw_table(path).dropna(how="all").dropna(axis=1, how="all")


def _tga_metrics(source_path: Path) -> list[dict[str, Any]]:
    raw = _raw_table(source_path)
    tokens = [
        [normalize_token(value) for value in row]
        for row in raw.astype(str).values.tolist()
    ]
    temp_col: int | None = None
    mass_col: int | None = None
    for row in tokens:
        for index, token in enumerate(row):
            if temp_col is None and "temp" in token:
                temp_col = index
            if mass_col is None and ("weight" in token or "mass" in token):
                mass_col = index
    if temp_col is None or mass_col is None:
        return [
            _metric(
                "residual_mass_percent",
                None,
                "%",
                "skipped",
                "Temperature/mass columns not found.",
            )
        ]
    data = (
        raw.iloc[:, [temp_col, mass_col]].apply(pd.to_numeric, errors="coerce").dropna()
    )
    if data.empty:
        return [
            _metric(
                "residual_mass_percent",
                None,
                "%",
                "skipped",
                "No numeric TGA data found.",
            )
        ]
    data.columns = ["temperature", "mass"]
    initial = float(data["mass"].iloc[0])
    residual = float(data["mass"].iloc[-1])
    rows = [_metric("residual_mass_percent", residual, "%")]
    for loss, metric in ((5, "t5_temperature_C"), (10, "t10_temperature_C")):
        threshold = initial - loss
        below = data[data["mass"] <= threshold]
        if below.empty:
            rows.append(
                _metric(
                    metric, None, "C", "skipped", f"Mass never reached {threshold:g} %."
                )
            )
        else:
            rows.append(_metric(metric, float(below["temperature"].iloc[0]), "C"))
    return rows


def _paired_extreme_position_metrics(
    source_path: Path,
    *,
    metric_name: str,
    x_unit: str,
    extreme: str,
    x_tokens: tuple[str, ...] = (),
    y_tokens: tuple[str, ...] = (),
    reason: str = "",
) -> list[dict[str, Any]]:
    series = _read_labeled_paired_curve_table(
        source_path,
        x_tokens=x_tokens,
        y_tokens=y_tokens,
    )
    rows: list[dict[str, Any]] = []
    for sample, data in series:
        finite = data.replace([np.inf, -np.inf], np.nan).dropna()
        suffix = "" if len(series) == 1 else f"[{sample}]"
        if finite.empty:
            rows.append(
                _metric(
                    f"{metric_name}{suffix}",
                    None,
                    x_unit,
                    "skipped",
                    "No finite curve found.",
                )
            )
            continue
        if extreme == "minimum":
            index = finite["y"].idxmin()
        elif extreme == "maximum":
            index = finite["y"].idxmax()
        elif extreme == "magnitude":
            index = finite["y"].abs().idxmax()
        else:
            raise ValueError(f"Unsupported paired extreme mode: {extreme}")
        rows.append(
            _metric(
                f"{metric_name}{suffix}",
                float(finite.loc[index, "x"]),
                x_unit,
                reason=reason,
            )
        )
    return rows or [
        _metric(
            metric_name, None, x_unit, "skipped", "No canonical paired curve found."
        )
    ]


def _paired_steepest_drop_position_metrics(
    source_path: Path,
    *,
    metric_name: str,
    x_unit: str,
    x_tokens: tuple[str, ...] = (),
    y_tokens: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    series = _read_labeled_paired_curve_table(
        source_path,
        x_tokens=x_tokens,
        y_tokens=y_tokens,
    )
    rows: list[dict[str, Any]] = []
    for sample, data in series:
        finite = (
            data.replace([np.inf, -np.inf], np.nan)
            .dropna()
            .sort_values("x", kind="stable")
            .drop_duplicates(subset="x", keep="last")
            .reset_index(drop=True)
        )
        suffix = "" if len(series) == 1 else f"[{sample}]"
        if len(finite) < 3:
            rows.append(
                _metric(
                    f"{metric_name}{suffix}",
                    None,
                    x_unit,
                    "skipped",
                    "At least three distinct finite paired points are required.",
                )
            )
            continue
        x_values = finite["x"].to_numpy(dtype=float)
        y_values = finite["y"].to_numpy(dtype=float)
        slopes = np.gradient(y_values, x_values)
        if not np.isfinite(slopes).any():
            rows.append(
                _metric(
                    f"{metric_name}{suffix}",
                    None,
                    x_unit,
                    "skipped",
                    "No finite local modulus slope could be calculated.",
                )
            )
            continue
        index = int(np.nanargmin(slopes))
        rows.append(
            _metric(
                f"{metric_name}{suffix}",
                float(x_values[index]),
                x_unit,
                reason="Temperature at the most negative discrete storage-modulus gradient.",
            )
        )
    return rows or [
        _metric(
            metric_name, None, x_unit, "skipped", "No canonical paired curve found."
        )
    ]
