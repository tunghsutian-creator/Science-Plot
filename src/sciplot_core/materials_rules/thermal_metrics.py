"""Compute DSC and swelling analysis metrics."""

from __future__ import annotations

from pathlib import Path
from typing import Any
import numpy as np

from sciplot_core.materials_rules.metric_tables import (
    _metric,
    _read_labeled_paired_curve_table,
)


def _dsc_metrics(source_path: Path) -> list[dict[str, Any]]:
    series = _read_labeled_paired_curve_table(
        source_path, y_tokens=("heat flow", "dsc")
    )
    rows: list[dict[str, Any]] = []
    for sample, data in series:
        finite = (
            data.replace([np.inf, -np.inf], np.nan)
            .dropna()
            .sort_values("x", kind="stable")
            .drop_duplicates(subset="x", keep="last")
        )
        suffix = "" if len(series) == 1 else f"[{sample}]"
        if len(finite) < 3:
            reason = "At least three finite temperature/heat-flow points are required."
            rows.append(
                _metric(
                    f"maximum_absolute_heat_flow_slope_temperature_C{suffix}",
                    None,
                    "C",
                    "skipped",
                    reason,
                )
            )
            rows.append(
                _metric(
                    f"maximum_absolute_heat_flow_temperature_C{suffix}",
                    None,
                    "C",
                    "skipped",
                    reason,
                )
            )
            continue
        temperatures = finite["x"].to_numpy(dtype=float)
        heat_flow = finite["y"].to_numpy(dtype=float)
        slope = np.gradient(heat_flow, temperatures)
        slope_index = int(np.nanargmax(np.abs(slope)))
        peak_index = int(np.nanargmax(np.abs(heat_flow)))
        rows.append(
            _metric(
                f"maximum_absolute_heat_flow_slope_temperature_C{suffix}",
                float(temperatures[slope_index]),
                "C",
                reason=(
                    "Temperature of the largest absolute finite heat-flow slope; "
                    "no transition identity is assigned."
                ),
            )
        )
        rows.append(
            _metric(
                f"maximum_absolute_heat_flow_temperature_C{suffix}",
                float(temperatures[peak_index]),
                "C",
                reason=(
                    "Temperature of the largest absolute finite recorded heat-flow "
                    "value; no melting or crystallization identity is assigned."
                ),
            )
        )
    if rows:
        return rows
    return [
        _metric(
            "maximum_absolute_heat_flow_slope_temperature_C",
            None,
            "C",
            "skipped",
            "No finite DSC curve found.",
        ),
        _metric(
            "maximum_absolute_heat_flow_temperature_C",
            None,
            "C",
            "skipped",
            "No finite DSC curve found.",
        ),
    ]


def _swelling_metrics(source_path: Path) -> list[dict[str, Any]]:
    series = _read_labeled_paired_curve_table(source_path, y_tokens=("swelling ratio",))
    if not series:
        return [
            _metric(
                "terminal_swelling_ratio",
                None,
                "1",
                "skipped",
                "No prepared swelling curves found.",
            )
        ]
    multiple = len(series) > 1
    rows: list[dict[str, Any]] = []
    for sample, data in series:
        metric_name = (
            f"terminal_swelling_ratio[{sample}]"
            if multiple
            else "terminal_swelling_ratio"
        )
        rows.append(
            _metric(
                metric_name,
                float(data["y"].iloc[-1]),
                "1",
                reason="Last finite reported observation; no equilibrium plateau is inferred.",
            )
        )
    return rows
