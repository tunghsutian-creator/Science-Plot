"""Read source-bound rheology TTS intervals with original row provenance."""

from __future__ import annotations

import hashlib
import math
import re
from pathlib import Path
from typing import Any

import numpy as np

from sciplot_core.foundation.text_values import clean_text, token
from sciplot_core.semantic_sources.models import _RHEOLOGY_SWEEP_METRICS
from sciplot_core.semantic_sources.rheology_sweep_sources import (
    _read_rheology_sweep_sample,
    _rheology_sweep_units,
)
from sciplot_core.semantic_sources.table_scanning import _float
from sciplot_core.semantic_sources.table_candidate_sources import (
    read_raw_table_normalized,
)


def read_tts_blocks(source: str | Path) -> dict[str, Any]:
    """Read all original instrument intervals without using filename identity."""
    path = Path(source).expanduser().resolve()
    before = path.read_bytes()
    raw = read_raw_table_normalized(path)
    blocks: list[dict[str, Any]] = []
    test = result = ""
    declared_count: int | None = None
    for i in range(len(raw)):
        label = token(raw.iat[i, 0])
        if label == "test":
            test = clean_text(raw.iat[i, 1])
        elif label == "result":
            result = clean_text(raw.iat[i, 1])
        elif label == "intervalanddatapoints":
            number = _float(raw.iat[i, 2])
            if number is None or not number.is_integer():
                raise ValueError(f"Invalid declared point count at row {i} in {path}.")
            declared_count = int(number)
        elif label == "intervaldata":
            if not test:
                raise ValueError(f"Missing Test identity before interval in {path}.")
            headers = [clean_text(v) for v in raw.iloc[i]]
            indices = {token(v): j for j, v in enumerate(headers)}
            required = {"pointno", "angularfrequency", "storagemodulus", "lossmodulus"}
            if not required <= indices.keys():
                raise ValueError(
                    f"TTS interval needs explicit point, frequency and both modulus columns in {path}."
                )
            stop = next(
                (
                    j
                    for j in range(i + 1, len(raw))
                    if token(raw.iat[j, 0])
                    in {"test", "result", "intervalanddatapoints", "intervaldata"}
                ),
                len(raw),
            )
            data_indices = [
                j
                for j in range(i + 1, stop)
                if _float(raw.iat[j, indices["pointno"]]) is not None
            ]
            if not data_indices or (
                declared_count is not None and len(data_indices) != declared_count
            ):
                raise ValueError(
                    f"Declared point count does not match interval at row {i} in {path}."
                )
            units = _rheology_sweep_units(
                raw, header_index=i, columns=tuple(indices[k] for k in required)
            )
            expected = {
                "angularfrequency": "rad/s",
                "storagemodulus": "Pa",
                "lossmodulus": "Pa",
            }
            for key in expected:
                if not units or not clean_text(units[indices[key]]):
                    raise ValueError(f"Missing explicit unit for {key} in {path}.")
            optional_units = {
                "temperature": {"°C", "C", "degC"},
                "shearstrain": {"%"},
                "torque": {"mN·m", "mN.m", "mNm"},
                "lossfactor": {"1"},
            }
            for key, accepted in optional_units.items():
                if (
                    key in indices
                    and clean_text(units[indices[key]]).strip("[] ") not in accepted
                ):
                    raise ValueError(
                        f"Unsupported explicit {key} unit in {path}; no unit was inferred."
                    )
            # Reuse the ordinary sweep parser and its validated unit conversions.
            # Exclude the Im(Complex Viscosity) field: it is not |eta*|.
            sample = _read_rheology_sweep_sample(
                path,
                raw=raw.iloc[i:stop].copy(),
                sample=test,
                x_aliases=("angularfrequency",),
                x_label="Angular Frequency",
                default_x_unit="rad/s",
                metrics=_RHEOLOGY_SWEEP_METRICS[:2],
            )
            if len(sample.rows) != len(data_indices):
                raise ValueError(
                    f"Missing numeric acquisition values in interval at row {i} in {path}."
                )
            points: list[dict[str, Any]] = []
            for j, row in zip(data_indices, sample.rows, strict=True):
                if not all(
                    k in row and math.isfinite(row[k]) and row[k] > 0
                    for k in ("x", "storage_modulus", "loss_modulus")
                ):
                    raise ValueError(
                        f"TTS requires finite positive frequency/G'/G''; original row {j} in {path} is invalid. No points were dropped."
                    )
                point: dict[str, Any] = {
                    "source_row": j,
                    "point_no": _float(raw.iat[j, indices["pointno"]]),
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
                        value = _float(raw.iat[j, indices[original]])
                        if value is None or not math.isfinite(value):
                            raise ValueError(
                                f"Invalid original {original} at row {j} in {path}."
                            )
                        point[key] = value
                if "status" in indices:
                    point["status"] = clean_text(raw.iat[j, indices["status"]])
                points.append(point)
            omega = [p["omega_rad_s"] for p in points]
            if len(set(omega)) != len(omega):
                raise ValueError(
                    f"Repeated frequencies within one interval at row {i} in {path}; no averaging is allowed."
                )
            match = re.fullmatch(r"FS\s+(-?\d+(?:\.\d+)?)\s*°C", result)
            temp = float(match.group(1)) if match else None
            actual = [p["temperature_C"] for p in points if "temperature_C" in p]
            blocks.append(
                {
                    "source": str(path),
                    "test": test,
                    "result": result,
                    "header_row": i,
                    "data_start_row": data_indices[0],
                    "data_end_row": data_indices[-1] + 1,
                    "point_count": len(points),
                    "declared_point_count": declared_count,
                    "nominal_temperature_C": temp,
                    "actual_temperature_C": (
                        {
                            "mean": float(np.mean(actual)),
                            "min": min(actual),
                            "max": max(actual),
                        }
                        if actual
                        else None
                    ),
                    "units": {
                        headers[k]: clean_text(v)
                        for k, v in enumerate(units)
                        if clean_text(v)
                    },
                    "metric_conversions": sample.metric_conversions,
                    "points": points,
                }
            )
            declared_count = None
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


__all__ = ["read_tts_blocks"]
