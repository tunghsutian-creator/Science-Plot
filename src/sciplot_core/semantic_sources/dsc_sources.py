"""Extract active DSC cooling and second-heating ramp series."""

from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Any
import pandas as pd
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
)
from sciplot_core.materials_rules import (
    format_unit_label,
)


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)


def _dsc_sample_code(path: Path) -> str:
    match = re.search(r"(?i)(?:^|[^a-z0-9])(e\d+)(?:[^a-z0-9]|$)", path.stem)
    return match.group(1).upper() if match else path.stem


def _dsc_header_columns(raw: pd.DataFrame) -> tuple[int, int, int, int] | None:
    aliases = {
        "time": ("time", "时间"),
        "temperature": ("temperature", "temp", "温度"),
        "heat_flow": ("heatflow", "heat flow", "热流"),
    }
    for row_index in range(min(12, raw.shape[0])):
        found: dict[str, int] = {}
        for column_index, value in enumerate(raw.iloc[row_index].tolist()):
            normalized = _clean_text(value).strip().casefold()
            compact = re.sub(r"[\s_]+", "", normalized)
            for role, role_aliases in aliases.items():
                if any(
                    compact == re.sub(r"[\s_]+", "", alias.casefold())
                    for alias in role_aliases
                ):
                    found.setdefault(role, column_index)
        if set(found) == set(aliases):
            return (
                row_index,
                found["time"],
                found["temperature"],
                found["heat_flow"],
            )
    return None


def _dsc_active_ramp_points(
    frame: pd.DataFrame,
) -> tuple[tuple[tuple[float, float], ...], dict[str, Any]]:
    frame = frame.dropna().reset_index(drop=True)
    if len(frame) < 50:
        raise ValueError("DSC ramp contains fewer than 50 numeric rows.")
    time_values = frame["time"].astype(float)
    temperature = frame["temperature"].astype(float)
    overall_delta = float(temperature.iloc[-1] - temperature.iloc[0])
    if abs(overall_delta) < 100.0:
        raise ValueError("DSC ramp temperature span is below 100 °C.")
    direction = 1.0 if overall_delta > 0.0 else -1.0
    dt = time_values.diff()
    rate = temperature.diff() / dt.where(dt.abs() > 1.0e-12)
    smoothed_rate = rate.rolling(11, center=True, min_periods=3).median()
    central = smoothed_rate.iloc[len(frame) // 5 : len(frame) * 4 // 5].abs()
    expected_rate = float(central[central > 0.0].median())
    if not math.isfinite(expected_rate) or expected_rate <= 0.0:
        raise ValueError("DSC ramp rate could not be inferred.")
    active = smoothed_rate.mul(direction).gt(0.0) & smoothed_rate.abs().ge(
        expected_rate * 0.65
    )
    active_indices = [int(index) for index, value in active.items() if bool(value)]
    if not active_indices:
        raise ValueError("DSC active ramp could not be isolated.")
    start = max(0, active_indices[0] - 1)
    stop = min(len(frame), active_indices[-1] + 2)
    selected = frame.iloc[start:stop].reset_index(drop=True)
    selected_temperature = selected["temperature"].astype(float)
    initial_selected_span = abs(
        float(selected_temperature.iloc[-1] - selected_temperature.iloc[0])
    )
    boundary_guard = initial_selected_span * 0.015
    lower_guard = float(selected_temperature.min()) + boundary_guard
    upper_guard = float(selected_temperature.max()) - boundary_guard
    selected = selected.loc[
        selected_temperature.between(lower_guard, upper_guard)
    ].reset_index(drop=True)
    selected_temperature = selected["temperature"].astype(float)
    monotonic_fraction = float(
        (
            selected_temperature.diff().dropna().mul(direction)
            >= -max(expected_rate * 0.02, 1.0e-6)
        ).mean()
    )
    selected_span = abs(
        float(selected_temperature.iloc[-1] - selected_temperature.iloc[0])
    )
    if (
        len(selected) < 50
        or selected_span < abs(overall_delta) * 0.80
        or monotonic_fraction < 0.95
    ):
        raise ValueError("DSC active-ramp selection failed coverage checks.")
    points = tuple(
        (float(x_value), float(y_value))
        for x_value, y_value in zip(
            selected_temperature, selected["heat_flow"].astype(float), strict=True
        )
    )
    return points, {
        "source_point_count": int(len(frame)),
        "selected_point_count": int(len(selected)),
        "trimmed_leading_point_count": int(start),
        "trimmed_trailing_point_count": int(len(frame) - stop),
        "temperature_boundary_guard_fraction": 0.015,
        "temperature_boundary_guard_C": boundary_guard,
        "temperature_direction": "increasing" if direction > 0 else "decreasing",
        "source_temperature_span_C": abs(overall_delta),
        "selected_temperature_span_C": selected_span,
        "inferred_ramp_rate_C_per_min": expected_rate,
        "monotonic_fraction": monotonic_fraction,
    }


def _read_dsc_workbook_phases(path: Path) -> list[CurveSeriesPayload]:
    sheets = pd.read_excel(path, sheet_name=None, header=None)
    candidates: list[CurveSeriesPayload] = []
    sample = _dsc_sample_code(path)
    for sheet_name, raw in sheets.items():
        header = _dsc_header_columns(raw)
        if header is None:
            continue
        header_index, time_column, temperature_column, heat_flow_column = header
        unit_row = raw.iloc[header_index + 1] if header_index + 1 < len(raw) else []
        temperature_unit = _clean_text(unit_row.iloc[temperature_column]).casefold()
        heat_flow_unit = _clean_text(unit_row.iloc[heat_flow_column])
        if "c" not in temperature_unit and "°" not in temperature_unit:
            raise ValueError(f"{path.name}/{sheet_name}: missing Celsius unit.")
        if (
            format_unit_label(heat_flow_unit).casefold()
            != format_unit_label("W/g").casefold()
        ):
            raise ValueError(f"{path.name}/{sheet_name}: heat-flow unit is not W g⁻¹.")
        numeric = pd.DataFrame(
            {
                "time": pd.to_numeric(
                    raw.iloc[header_index + 1 :, time_column], errors="coerce"
                ),
                "temperature": pd.to_numeric(
                    raw.iloc[header_index + 1 :, temperature_column], errors="coerce"
                ),
                "heat_flow": pd.to_numeric(
                    raw.iloc[header_index + 1 :, heat_flow_column], errors="coerce"
                ),
            }
        )
        points, diagnostics = _dsc_active_ramp_points(numeric)
        phase = "Second heating" if points[-1][0] > points[0][0] else "Cooling"
        candidates.append(
            CurveSeriesPayload(
                sample=f"{phase} {sample}",
                x_label="Temperature",
                x_unit="°C",
                y_label="Heat flow",
                y_unit=format_unit_label("W/g"),
                points=points,
                diagnostics={
                    **diagnostics,
                    "source": str(path),
                    "source_table": str(sheet_name),
                    "phase": phase,
                    "sample": sample,
                },
            )
        )
    cooling = [item for item in candidates if item.sample.startswith("Cooling ")]
    reheating = [
        item for item in candidates if item.sample.startswith("Second heating ")
    ]
    if len(cooling) != 1 or len(reheating) != 1:
        raise ValueError(
            f"{path.name}: expected exactly one cooling and one second-heating ramp; "
            f"found {len(cooling)} and {len(reheating)}."
        )
    return [cooling[0], reheating[0]]


def _read_dsc_cycle_series(source: Path) -> list[CurveSeriesPayload]:
    workbooks = (
        [
            path
            for path in sorted(source.iterdir())
            if path.is_file() and path.suffix.lower() in {".xls", ".xlsx"}
        ]
        if source.is_dir()
        else [source]
    )
    if not workbooks:
        raise ValueError(f"No DSC workbooks found under {source}.")
    parsed = [
        series for path in workbooks for series in _read_dsc_workbook_phases(path)
    ]

    def sort_key(item: CurveSeriesPayload) -> tuple[int, int, str]:
        diagnostics = item.diagnostics or {}
        phase_rank = 0 if diagnostics.get("phase") == "Cooling" else 1
        sample = str(diagnostics.get("sample") or item.sample)
        match = re.fullmatch(r"E(\d+)", sample, flags=re.IGNORECASE)
        return phase_rank, int(match.group(1)) if match else 10**9, sample

    return sorted(parsed, key=sort_key)
