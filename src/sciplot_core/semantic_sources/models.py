"""Define normalized semantic curve, sweep, and replicate payload models."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CurveSeriesPayload:
    sample: str
    x_label: str
    x_unit: str
    y_label: str
    y_unit: str
    points: tuple[tuple[float, float], ...]
    diagnostics: dict[str, Any] | None = None


@dataclass(frozen=True)
class RheologySweepSample:
    sample: str
    source: Path
    x_label: str
    x_unit: str
    metric_units: dict[str, str]
    rows: tuple[dict[str, float], ...]
    interval_count: int = 1
    selected_interval_index: int = 1
    interval_selection_policy: str = "single_interval"
    source_x_unit: str = ""
    x_conversion: dict[str, Any] | None = None
    metric_conversions: dict[str, dict[str, Any]] | None = None


@dataclass(frozen=True)
class ImpactReplicatePayload:
    rows: tuple[tuple[object, ...], ...]
    samples: tuple[str, ...]
    replicate_counts: tuple[int, ...]
    values: tuple[tuple[float, ...], ...]
    unit: str = "kJ/m2"

    @property
    def total_replicates(self) -> int:
        return sum(self.replicate_counts)


class _ImpactDataValidationError(ValueError):
    """Raised when an impact-shaped table contains scientifically invalid data."""


class _StressRelaxationHoldError(ValueError):
    """Raised when a strain-controlled hold cannot be established safely."""


_RHEOLOGY_SWEEP_METRICS = (
    (
        "storage_modulus",
        "Storage Modulus",
        ("storagemodulus", "storage modulus", "g'", "g′"),
        "Pa",
    ),
    ("loss_modulus", "Loss Modulus", ("lossmodulus", 'g"', "g″"), "Pa"),
    ("loss_factor", "Loss Factor", ("lossfactor", "tandelta", "tanδ"), "1"),
    (
        "complex_viscosity",
        "Complex Viscosity",
        ("complexviscosity", "viscosity"),
        "mPa·s",
    ),
)


_RHEOLOGY_COMPLEX_MODULUS_METRIC = (
    "complex_modulus",
    "Complex Modulus",
    ("complexmodulus", "complexshearmodulus", "|g*|", "g*"),
    "Pa",
)


_RHEOLOGY_FREQUENCY_OUTPUT_METRICS = (
    _RHEOLOGY_SWEEP_METRICS[0],
    _RHEOLOGY_SWEEP_METRICS[1],
    _RHEOLOGY_SWEEP_METRICS[2],
    _RHEOLOGY_SWEEP_METRICS[3],
)


_RHEOLOGY_AMPLITUDE_OUTPUT_METRICS = (
    _RHEOLOGY_SWEEP_METRICS[0],
    _RHEOLOGY_SWEEP_METRICS[1],
    _RHEOLOGY_SWEEP_METRICS[2],
)


_RHEOLOGY_TIME_OUTPUT_METRICS = (_RHEOLOGY_COMPLEX_MODULUS_METRIC,)
