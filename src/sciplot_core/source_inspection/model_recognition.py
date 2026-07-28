"""Classify supported source-table shapes without selecting presentation policy."""

from __future__ import annotations

from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from sciplot_core.source_inspection.header_matching import cell_text
from sciplot_core.source_inspection.intent_recognition import detect_source_intent
from sciplot_core.source_inspection.models import SourceIntent
from sciplot_core.source_tables import (
    CurveSeries,
    HeatmapTable,
    ReplicateGroup,
    canonicalize_token,
    load_curve_table_from_frame,
    load_heatmap_table_from_frame,
    load_replicate_table_from_frame,
    normalize_label,
    read_raw_table,
)


@dataclass(frozen=True)
class RecognizedSource:
    model: str
    raw: pd.DataFrame
    intent: SourceIntent | None = None
    curves: tuple[CurveSeries, ...] = ()
    replicate_groups: tuple[ReplicateGroup, ...] = ()
    heatmap: HeatmapTable | None = None


def _frequency_metric_sheet(curves: list[CurveSeries]) -> bool:
    if not curves:
        return False
    x_labels = {canonicalize_token(series.x_label) for series in curves}
    y_labels = {canonicalize_token(series.y_label) for series in curves}
    frequency_labels = {"angular frequency", "frequency", "ω"}
    rheology_labels = {
        "storage modulus",
        "loss modulus",
        "loss factor",
        "complex viscosity",
        "complex modulus",
        "complex shear modulus",
        "g'",
        'g"',
        "g.",
        "|g.|",
        "tanδ",
        "tand",
        "tan delta",
        "|η.|",
        "eta",
        "eta.",
    }
    return bool(x_labels & frequency_labels) and bool(y_labels & rheology_labels)


def _tensile_curve(curves: list[CurveSeries]) -> bool:
    if not curves:
        return False
    first = curves[0]
    x_label = canonicalize_token(normalize_label(first.x_label))
    y_label = canonicalize_token(normalize_label(first.y_label))
    x_unit = canonicalize_token(first.x_unit)
    y_unit = canonicalize_token(first.y_unit)
    x_matches = (
        x_label in {"strain", "elongation"}
        or "strain" in x_label
        or "elongation" in x_label
    )
    y_matches = y_label in {"stress", "σ"} or "stress" in y_label
    return (
        x_matches
        and y_matches
        and (x_unit in {"%", "percent"} or y_unit in {"pa", "kpa", "mpa", "gpa"})
    )


def _point_line_bundle(raw: pd.DataFrame, source: Path) -> str | None:
    if source.suffix.casefold() not in {".xlsx", ".xlsm"}:
        return None
    compact = raw.dropna(axis=1, how="all")
    if compact.shape[0] < 3 or compact.shape[1] == 0:
        return None
    labels = [
        canonicalize_token(cell_text(value)) for value in compact.iloc[0].tolist()
    ]
    normalized_labels = [
        normalize_label(cell_text(value)) for value in compact.iloc[0].tolist()
    ]
    first_label = labels[0]
    metric_labels = set(labels)
    if (
        compact.shape[1] % 5 == 0
        and {"storage modulus", "loss modulus", "loss factor"}.issubset(metric_labels)
        and {"complex viscosity", "complex modulus"} & metric_labels
    ):
        if first_label == "temperature":
            return "temperature_sweep"
        if first_label in {"angular frequency", "frequency", "ω"}:
            return "frequency_sweep"
    if (
        compact.shape[1] % 4 == 0
        and first_label == "time"
        and r"$\sigma/\sigma_0$" in normalized_labels
    ):
        return "stress_relaxation"
    return None


def _small_table_figure(raw: pd.DataFrame) -> bool:
    if raw.empty or raw.shape[0] > 12 or raw.shape[1] > 8:
        return False
    values = [cell_text(value) for value in raw.to_numpy().ravel() if cell_text(value)]
    if len(values) < 4:
        return False
    numeric_count = 0
    for value in values:
        try:
            float(value)
        except (TypeError, ValueError):
            continue
        numeric_count += 1
    return 0 < numeric_count < len(values)


def recognize_source(
    input_path: Path,
    sheet: str | int = 0,
) -> RecognizedSource:
    """Read a source once and classify its table structure."""

    source = Path(input_path)
    raw = read_raw_table(source, sheet_name=sheet)
    compact = raw.dropna(how="all").dropna(axis=1, how="all")
    bundle = _point_line_bundle(compact, source)
    if bundle is not None:
        return RecognizedSource(model=bundle, raw=raw)

    intent = detect_source_intent(compact, source)
    with suppress(Exception):
        curves = load_curve_table_from_frame(compact)
        model = (
            "frequency_metric_sheet"
            if _frequency_metric_sheet(curves)
            else "tensile_curve"
            if _tensile_curve(curves)
            else "curve_table"
        )
        return RecognizedSource(
            model=model,
            raw=raw,
            intent=intent if intent is not None and intent.model == model else None,
            curves=tuple(curves),
        )

    with suppress(Exception):
        heatmap = load_heatmap_table_from_frame(compact)
        return RecognizedSource(
            model="heatmap_table",
            raw=raw,
            heatmap=heatmap,
        )

    if intent is not None:
        return RecognizedSource(model=intent.model, raw=raw, intent=intent)

    with suppress(Exception):
        groups = load_replicate_table_from_frame(compact)
        return RecognizedSource(
            model="replicate_table",
            raw=raw,
            replicate_groups=tuple(groups),
        )

    if _small_table_figure(compact):
        return RecognizedSource(model="table_summary", raw=raw)

    raise ValueError(
        "Could not recognize this file. Reformat it as a curve_table, "
        "replicate_table, heatmap xyz_long_table, or one of the supported "
        "rheology export tables."
    )


def looks_like_nmr(curves: tuple[CurveSeries, ...]) -> bool:
    if not curves:
        return False
    first = curves[0]
    return (
        canonicalize_token(first.x_label) == "chemical shift"
        or "ppm" in first.x_unit.casefold()
    )


def looks_like_ftir(curves: tuple[CurveSeries, ...]) -> bool:
    if not curves:
        return False
    first = curves[0]
    unit = first.x_unit.casefold()
    return canonicalize_token(first.x_label) == "wavenumber" or (
        "cm" in unit and ("-1" in unit or "^{-1}" in unit)
    )


def looks_like_xrd(curves: tuple[CurveSeries, ...]) -> bool:
    if not curves:
        return False
    first = curves[0]
    x_label = canonicalize_token(first.x_label)
    y_label = canonicalize_token(first.y_label)
    return (
        x_label in {"2theta", "2θ"}
        or "count" in first.y_unit.casefold()
        or x_label == "2 theta"
        and y_label == "intensity"
    )


def looks_like_dsc(curves: tuple[CurveSeries, ...]) -> bool:
    return bool(curves and canonicalize_token(curves[0].y_label) == "heat flow")


__all__ = [
    "RecognizedSource",
    "looks_like_dsc",
    "looks_like_ftir",
    "looks_like_nmr",
    "looks_like_xrd",
    "recognize_source",
]
