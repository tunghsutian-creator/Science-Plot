"""Read source-bound rheology TTS intervals with original row provenance."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from sciplot_core.foundation.text_values import clean_text, token
from sciplot_core.semantic_sources.instrument_regions import rheology_instrument_regions
from sciplot_core.semantic_sources.models import _RHEOLOGY_SWEEP_METRICS
from sciplot_core.semantic_sources.paired_curve_table_metadata import header_quantity_text
from sciplot_core.semantic_sources.rheology_sweep_sources import _read_rheology_sweep_sample
from sciplot_core.semantic_sources.table_scanning import _float
from sciplot_core.semantic_sources.table_candidate_sources import (
    read_raw_table_normalized,
)


def read_tts_blocks(
    source: str | Path, *, selected_tests: set[str] | None = None,
) -> dict[str, Any]:
    """Read selected original Tests strictly and report excluded invalid intervals."""
    path = Path(source).expanduser().resolve()
    before = path.read_bytes()
    raw = read_raw_table_normalized(path)
    blocks: list[dict[str, Any]] = []
    test = result = ""
    count_row: int | None = None
    for i in range(len(raw)):
        label = token(raw.iat[i, 0])
        if label == "test":
            test = clean_text(raw.iat[i, 1])
            result = ""
            count_row = None
        elif label == "result":
            result = clean_text(raw.iat[i, 1])
            count_row = None
        elif label == "intervalanddatapoints":
            count_row = i
        elif label == "intervaldata":
            if not test:
                raise ValueError(f"Missing Test identity before interval in {path}.")
            stop = next(
                (
                    j
                    for j in range(i + 1, len(raw))
                    if token(raw.iat[j, 0])
                    in {"test", "result", "intervalanddatapoints", "intervaldata"}
                ),
                len(raw),
            )
            interval = raw.iloc[i:stop]
            match = re.fullmatch(r"FS\s+(-?\d+(?:\.\d+)?)\s*°C", result)
            block: dict[str, Any] = {
                "source": str(path), "test": test, "result": result, "header_row": i,
                "declared_point_count": None,
                "nominal_temperature_C": float(match.group(1)) if match else None,
            }
            regions = None
            try:
                regions = rheology_instrument_regions(interval)
                declared_count = None
                if count_row is not None:
                    number = _float(raw.iat[count_row, 2]) if raw.shape[1] > 2 else None
                    if number is None or not number.is_integer():
                        raise ValueError(f"Invalid declared point count at original row {count_row + 1} in {path}.")
                    declared_count = int(number)
                    block["declared_point_count"] = declared_count
                block.update(_read_tts_interval(path, interval, regions, test, declared_count))
            except ValueError as exc:
                if selected_tests is None or test in selected_tests:
                    raise
                region = regions[0] if regions else {}
                data_start = region.get("data_start_row")
                data_end = region.get("data_end_row")
                block.update(
                    validation_error=str(exc), point_count=None, points=[],
                    data_start_row=data_start, data_end_row=data_end,
                    source_rows=(list(range(data_start, data_end))
                                 if data_start is not None and data_end is not None else []),
                    actual_temperature_C=None,
                )
            blocks.append(block)
            count_row = None
    if not blocks:
        raise ValueError(f"No instrument rheology blocks in {path}.")
    if path.read_bytes() != before:
        raise ValueError(f"Source changed while reading {path}.")
    return {
        "path": str(path),
        "sha256": hashlib.sha256(before).hexdigest(),
        "size_bytes": len(before),
        "blocks": blocks,
    }


def _read_tts_interval(
    path: Path,
    interval: pd.DataFrame,
    regions: list[dict[str, Any]] | None,
    test: str,
    declared_count: int | None,
) -> dict[str, Any]:
    i = int(interval.index[0])
    headers = [clean_text(v) for v in interval.iloc[0]]
    indices = {token(header_quantity_text(v)): j for j, v in enumerate(headers)}
    frequency_columns = {"angularfrequency", "frequency"} & indices.keys()
    required = {"pointno", "storagemodulus", "lossmodulus"}
    if not required <= indices.keys() or len(frequency_columns) != 1:
        raise ValueError(
            f"TTS interval needs explicit point, frequency and both modulus columns in {path}."
        )
    frequency = next(iter(frequency_columns))
    unit_row = regions[0].get("unit_row") if regions else None
    units = [clean_text(v) for v in interval.loc[unit_row]] if unit_row is not None else []
    optional_units = {
        "temperature": {"°C", "C", "degC"},
        "shearstrain": {"%"},
        "torque": {"mN·m", "mN.m", "mNm"},
        "lossfactor": {"1"},
    }
    for key, accepted in optional_units.items():
        if (
            key in indices
            and (not units or clean_text(units[indices[key]]).strip("[] ") not in accepted)
        ):
            raise ValueError(
                f"Unsupported explicit {key} unit in {path}; no unit was inferred."
            )
    # Reuse the ordinary sweep parser and its validated unit conversions.
    # Exclude the Im(Complex Viscosity) field: it is not |eta*|.
    sample = _read_rheology_sweep_sample(
        path,
        raw=interval,
        source_regions=regions,
        sample=test,
        x_aliases=(frequency,),
        x_label="Angular Frequency",
        default_x_unit="rad/s",
        metrics=_RHEOLOGY_SWEEP_METRICS[:2],
        tts_point_column=indices["pointno"],
    )
    data_indices = sample.source_rows
    if declared_count is not None and len(data_indices) != declared_count:
        raise ValueError(
            f"Declared point count does not match interval at row {i} in {path}."
        )
    metric_conversions = sample.metric_conversions or {}
    if (sample.x_conversion or {}).get("source_column") != indices[frequency] or any(
        metric_conversions.get(metric, {}).get("source_column") != indices[header]
        for metric, header in (
            ("storage_modulus", "storagemodulus"), ("loss_modulus", "lossmodulus")
        )
    ):
        raise ValueError(f"Ambiguous TTS frequency or modulus columns at row {i + 1} in {path}.")
    points: list[dict[str, Any]] = []
    for j, row in zip(data_indices, sample.rows, strict=True):
        original_cells = interval.loc[j]
        point: dict[str, Any] = {
            "source_row": j,
            "point_no": _float(original_cells.iloc[indices["pointno"]]),
            "omega_rad_s": row["x"],
            "storage_modulus_Pa": row["storage_modulus"],
            "loss_modulus_Pa": row["loss_modulus"],
            "tan_delta": row["loss_modulus"] / row["storage_modulus"],
            "complex_viscosity_Pa_s": math.hypot(
                row["storage_modulus"], row["loss_modulus"]
            )
            / row["x"],
        }
        for original, key in (
            ("temperature", "temperature_C"),
            ("shearstrain", "shear_strain_percent"),
            ("torque", "torque_mNm"),
            ("lossfactor", "instrument_loss_factor"),
        ):
            if original in indices:
                value = _float(original_cells.iloc[indices[original]])
                if value is None or not math.isfinite(value):
                    raise ValueError(
                        f"Invalid original {original} at row {j} in {path}."
                    )
                point[key] = value
        if "status" in indices:
            point["status"] = clean_text(original_cells.iloc[indices["status"]])
        points.append(point)
    omega = [p["omega_rad_s"] for p in points]
    if len(set(omega)) != len(omega):
        raise ValueError(
            f"Repeated frequencies within one interval at row {i} in {path}; no averaging is allowed."
        )
    actual = [p["temperature_C"] for p in points if "temperature_C" in p]
    return {
        "data_start_row": data_indices[0],
        "data_end_row": data_indices[-1] + 1,
        "point_count": len(points),
        "actual_temperature_C": (
            {"mean": float(np.mean(actual)), "min": min(actual), "max": max(actual)}
            if actual else None
        ),
        "units": {
            headers[k]: clean_text(v)
            for k, v in enumerate(units)
            if clean_text(v)
        },
        "x_conversion": sample.x_conversion,
        "metric_conversions": metric_conversions,
        "points": points,
    }


__all__ = ["read_tts_blocks"]
