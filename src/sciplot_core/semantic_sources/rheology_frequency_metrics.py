"""Source-faithful oscillatory metrics shared by instrument and workbook routes."""

from __future__ import annotations

import math
import re
from typing import Any

import pandas as pd

from sciplot_core.foundation.text_values import clean_text, token
from sciplot_core.materials_rules.unit_formatting import format_unit_label
from sciplot_core.semantic_sources.rheology_units import _unit_conversion
from sciplot_core.semantic_sources.paired_curve_table_metadata import explicit_header_unit


def _quantity_header(value: object) -> str:
    text = clean_text(value)
    if explicit_header_unit(text):
        text = re.sub(r"(?:\([^()]*\)|\[[^\[\]]*\])\s*$", "", text).strip()
    return text


def is_rheology_magnitude_header(header: object, *, metric: str) -> bool:
    """Recognize an explicit magnitude identity without matching its components."""
    names = {
        "complex_viscosity": ("complexviscosity", "|η*|", "|eta*|"),
        "complex_modulus": ("complexmodulus", "|g*|", "|gstar|"),
    }
    if metric not in names:
        return False
    text = _quantity_header(header).casefold()
    name, *symbols = names[metric]
    compact = re.sub(r"\s+", "", text)
    identity = token(text)
    return compact in symbols or identity in {
        name,
        f"{name}magnitude",
        f"magnitude{name}",
        f"magnitudeof{name}",
        f"absolute{name}",
        f"absolutevalueof{name}",
        f"abs{name}",
        *(('complexshearmodulus',) if metric == 'complex_modulus' else ()),
    }


def is_rheology_component_header(header: object) -> bool:
    """Identify real/imaginary viscosity or modulus; neither denotes magnitude."""
    text = _quantity_header(header).casefold()
    identity = token(text)
    named = any(name in identity for name in ('complexviscosity', 'complexmodulus'))
    return bool(
        named
        and (
            re.search(r"\b(?:imaginary|real|imag|re|im)\b", text)
            or identity.startswith(('imcomplex', 'recomplex', 'imaginarycomplex', 'realcomplex'))
        )
    )


def validate_complex_viscosity_units(
    *,
    frequency_unit: str,
    storage_unit: str,
    loss_unit: str,
    output_unit: str = 'Pa s',
) -> tuple[float, float, float]:
    """Validate source/output dimensions even when every observation is missing."""
    factors = []
    for unit, target in (
        (frequency_unit, 'rad/s'),
        (storage_unit, 'Pa'),
        (loss_unit, 'Pa'),
    ):
        _unit, factor, method = _unit_conversion(unit, target)
        if not unit.strip() or method == 'source_unit_preserved':
            raise ValueError('Complex viscosity requires explicit supported frequency and modulus units.')
        factors.append(factor)
    _viscosity_output_factor(output_unit)
    return factors[0], factors[1], factors[2]


def derive_complex_viscosity(
    omega: float,
    storage: float,
    loss: float,
    *,
    frequency_unit: str,
    storage_unit: str,
    loss_unit: str,
    output_unit: str = 'Pa s',
) -> float:
    """Deterministic |eta*| from original G'/G'' and explicit frequency units."""
    factors = validate_complex_viscosity_units(
        frequency_unit=frequency_unit, storage_unit=storage_unit,
        loss_unit=loss_unit, output_unit=output_unit,
    )
    values = [value * factor for value, factor in zip((omega, storage, loss), factors, strict=True)]
    normalized_omega, normalized_storage, normalized_loss = values
    if not all(math.isfinite(value) for value in values):
        raise ValueError('Complex viscosity requires finite original frequency and moduli.')
    return _viscosity_from_modulus(
        normalized_omega,
        math.hypot(normalized_storage, normalized_loss),
        output_unit=output_unit,
    )


def _viscosity_output_factor(output_unit: str) -> float:
    output = re.sub(r'\s+', '·', format_unit_label(output_unit))
    if output not in {'Pa·s', 'mPa·s'}:
        raise ValueError('Complex viscosity output unit must be Pa·s or mPa·s.')
    return 1000. if output == 'mPa·s' else 1.


def _viscosity_from_modulus(omega: float, modulus: float, *, output_unit: str) -> float:
    if (
        not math.isfinite(omega) or omega <= 0
        or not math.isfinite(modulus) or modulus < 0
    ):
        raise ValueError(
            'Complex viscosity requires positive finite angular frequency and a finite nonnegative modulus at every selected row.'
        )
    value = modulus / omega * _viscosity_output_factor(output_unit)
    if not math.isfinite(value):
        raise ValueError('Derived complex viscosity is not finite.')
    return value


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
        if any(units[key] != 'Pa' for key in ('storage_modulus', 'loss_modulus')):
            raise ValueError('Complex modulus derivation requires both modulus inputs normalized to Pa.')
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
        row["complex_viscosity"] = _viscosity_from_modulus(
            omega, modulus, output_unit='mPa·s'
        )
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
