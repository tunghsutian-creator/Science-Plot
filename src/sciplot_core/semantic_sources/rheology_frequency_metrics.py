"""Source-faithful oscillatory metrics shared by instrument and workbook routes."""

from __future__ import annotations

import math
from typing import Any

import pandas as pd

from sciplot_core.foundation.text_values import clean_text, token
from sciplot_core.materials_rules.unit_formatting import format_unit_label
from sciplot_core.semantic_sources.rheology_units import _unit_conversion


def complete_sweep_metrics(
    rows: list[dict[str, float]],
    units: dict[str, str],
    conversions: dict[str, dict[str, Any]],
    *,
    x_label: str,
    x_unit: str,
) -> None:
    """Derive missing quantities; never fill holes in an instrument-reported column."""
    if (
        "complex_modulus" not in units
        and {"storage_modulus", "loss_modulus"} <= units.keys()
    ):
        units["complex_modulus"] = "Pa"
        for row in rows:
            if "storage_modulus" in row and "loss_modulus" in row:
                row["complex_modulus"] = math.hypot(
                    row["storage_modulus"], row["loss_modulus"]
                )
        conversions["complex_modulus"] = {
            "method": "derived_from_storage_and_loss_modulus",
            "expression": "hypot(storage_modulus, loss_modulus)",
            "source_unit": "Pa",
            "output_unit": "Pa",
            "factor": 1.0,
        }
    if (
        token(x_label) != "angularfrequency"
        or "complex_viscosity" in units
        or "complex_modulus" not in units
    ):
        return
    if (
        format_unit_label(x_unit) != format_unit_label("rad/s")
        or units["complex_modulus"] != "Pa"
    ):
        raise ValueError(
            "Complex viscosity derivation requires angular frequency in rad/s and modulus in Pa."
        )
    for row in rows:
        omega, modulus = row.get("x"), row.get("complex_modulus")
        if (
            omega is None
            or not math.isfinite(omega)
            or omega <= 0
            or modulus is None
            or not math.isfinite(modulus)
            or modulus < 0
        ):
            raise ValueError(
                "Complex viscosity requires positive finite angular frequency and a finite nonnegative modulus at every selected row."
            )
        value = modulus / omega * 1000.0
        if not math.isfinite(value):
            raise ValueError("Derived complex viscosity is not finite.")
        row["complex_viscosity"] = value
    units["complex_viscosity"] = "mPa·s"
    conversions["complex_viscosity"] = {
        "method": "derived_complex_modulus_over_angular_frequency",
        "expression": "complex_modulus / angular_frequency * 1000",
        "source_unit": "Pa / (rad/s)",
        "output_unit": "mPa·s",
        "factor": 1000.0,
        "input_metrics": ["complex_modulus", "angular_frequency"],
    }


def complete_frequency_frame(
    frame: pd.DataFrame,
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Append missing viscosity within each original three-header sample block."""
    if frame.shape[0] < 4:
        return frame, []
    headers = [token(value) for value in frame.iloc[0]]
    starts = [
        i
        for i, header in enumerate(headers)
        if header in {"angularfrequency", "frequency"}
    ]
    labels = {
        "storagemodulus": "storage_modulus",
        "lossmodulus": "loss_modulus",
        "complexmodulus": "complex_modulus",
    }
    parts: list[pd.DataFrame] = []
    ledger: list[dict[str, Any]] = []
    if starts and starts[0]:
        parts.append(frame.iloc[:, : starts[0]])
    for block, start in enumerate(starts):
        end = starts[block + 1] if block + 1 < len(starts) else len(headers)
        block_frame = frame.iloc[:, start:end].copy()
        parts.append(block_frame)
        present = set(headers[start + 1 : end])
        if not (
            "complexviscosity" in present
            or "complexmodulus" in present
            or {"storagemodulus", "lossmodulus"} <= present
        ):
            continue
        sample = clean_text(frame.iat[1, start])
        x_unit, x_factor, x_method = _unit_conversion(
            clean_text(frame.iat[2, start]), "rad/s"
        )
        if x_method == "source_unit_preserved":
            raise ValueError(
                "Complex viscosity requires an explicit angular-frequency unit (rad/s or Hz)."
            )
        unit_changes: list[dict[str, Any]] = []
        if x_factor != 1.0:
            _convert_frame_column(block_frame, 0, factor=x_factor, unit=x_unit)
            block_frame.iat[0, 0] = "Angular Frequency"
            unit_changes.append(
                {
                    "column": start,
                    "method": x_method,
                    "factor": x_factor,
                    "output_unit": x_unit,
                }
            )
        for column in range(start + 1, end):
            if headers[column] not in labels:
                continue
            unit, factor, method = _unit_conversion(
                clean_text(frame.iat[2, column]), "Pa"
            )
            if method == "source_unit_preserved":
                raise ValueError(
                    "Complex viscosity requires explicit supported modulus units."
                )
            if factor != 1.0:
                _convert_frame_column(
                    block_frame, column - start, factor=factor, unit=unit
                )
                unit_changes.append(
                    {
                        "column": column,
                        "method": method,
                        "factor": factor,
                        "output_unit": unit,
                    }
                )
        if "complexviscosity" in present:
            column = next(
                i for i in range(start + 1, end) if headers[i] == "complexviscosity"
            )
            if not sample or clean_text(frame.iat[1, column]) != sample:
                raise ValueError(
                    "Reported viscosity requires matching sample identities."
                )
            unit, factor, method = _unit_conversion(
                clean_text(frame.iat[2, column]), "mPa·s"
            )
            if method == "source_unit_preserved":
                raise ValueError("Unsupported reported complex-viscosity unit.")
            if factor != 1.0 or clean_text(frame.iat[2, column]) != unit:
                _convert_frame_column(
                    block_frame, column - start, factor=factor, unit=unit
                )
                unit_changes.append(
                    {
                        "column": column,
                        "method": method,
                        "factor": factor,
                        "output_unit": unit,
                    }
                )
            if unit_changes:
                ledger.append(
                    {
                        "sample": sample,
                        "unit_conversions": unit_changes,
                        "derivations": {},
                    }
                )
            continue
        indexes = {
            labels[headers[i]]: i for i in range(start + 1, end) if headers[i] in labels
        }
        if not sample or any(
            clean_text(frame.iat[1, i]) != sample for i in indexes.values()
        ):
            raise ValueError(
                "Complex viscosity requires matching original sample identities within each frequency block."
            )
        units, factors, conversions = {}, {}, {}
        for metric, column in indexes.items():
            unit, factor, method = _unit_conversion(
                clean_text(frame.iat[2, column]), "Pa"
            )
            if method == "source_unit_preserved":
                raise ValueError(
                    "Complex viscosity requires explicit supported modulus units."
                )
            units[metric], factors[metric] = unit, factor
        rows, row_indexes = [], []
        output: list[object] = ["Complex Viscosity", sample, "mPa·s"] + [None] * (
            len(frame) - 3
        )
        for row_index in range(3, len(frame)):
            values = [frame.iat[row_index, i] for i in [start, *indexes.values()]]
            if all(pd.isna(value) or clean_text(value) == "" for value in values):
                continue
            try:
                row = {"x": float(values[0]) * x_factor}
                row.update(
                    {
                        metric: float(frame.iat[row_index, column]) * factors[metric]
                        for metric, column in indexes.items()
                    }
                )
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Missing or nonnumeric viscosity input at original row {row_index}."
                ) from exc
            rows.append(row)
            row_indexes.append(row_index)
        complete_sweep_metrics(
            rows, units, conversions, x_label="Angular Frequency", x_unit=x_unit
        )
        for row_index, row in zip(row_indexes, rows, strict=True):
            output[row_index] = row["complex_viscosity"]
        parts.append(pd.DataFrame({0: output}, index=frame.index))
        ledger.append(
            {
                "sample": sample,
                "x_column": start,
                "metric_columns": indexes,
                "unit_conversions": unit_changes,
                "derivations": conversions,
            }
        )
    return (
        (pd.concat(parts, axis=1, ignore_index=True), ledger) if ledger else (frame, [])
    )


def _convert_frame_column(
    frame: pd.DataFrame, column: int, *, factor: float, unit: str
) -> None:
    frame.iat[2, column] = unit
    for row in range(3, len(frame)):
        value = frame.iat[row, column]
        if pd.isna(value) or clean_text(value) == "":
            continue
        converted = float(value) * factor
        if not math.isfinite(converted):
            raise ValueError(f"Nonfinite frequency input at original row {row}.")
        frame.iat[row, column] = converted
