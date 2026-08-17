"""Recognize experiment intent from ordinary instrument-table headers."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from sciplot_core.source_inspection.header_matching import (
    cell_text,
    cell_token,
    columns_matching,
    dedupe_labels,
    header_row_with,
    label_and_unit,
    looks_numeric,
)
from sciplot_core.source_inspection.models import SourceIntent
from sciplot_core.source_tables import canonicalize_token, normalize_label


def _curve_intent(
    raw: pd.DataFrame,
    *,
    family: str,
    model: str,
    template: str,
    reason: str,
    header_row: int,
    x_terms: set[str],
    y_terms: set[str],
    xscale: str = "linear",
    yscale: str = "linear",
    reverse_x: bool = False,
    baseline: str | None = None,
) -> SourceIntent:
    x_column = columns_matching(raw, header_row, x_terms)[0]
    y_column = columns_matching(raw, header_row, y_terms)[0]
    x_label, _x_unit = label_and_unit(raw.iloc[header_row, x_column])
    y_label, _y_unit = label_and_unit(raw.iloc[header_row, y_column])
    return SourceIntent(
        experiment_family=family,
        model=model,
        recommended_template=template,
        reason=reason,
        x_label=x_label,
        y_label=y_label,
        xscale=xscale,
        yscale=yscale,
        reverse_x=reverse_x,
        baseline=baseline,
    )


def _block_metric_intent(
    raw: pd.DataFrame,
    source_path: Path | None,
) -> SourceIntent | None:
    if raw.shape[0] < 3 or raw.shape[1] < 3:
        return None
    first_row = [cell_text(value) for value in raw.iloc[0].tolist()]
    second_row = [cell_text(value) for value in raw.iloc[1].tolist()]
    block_names: list[str] = []
    metric_names: list[str] = []
    for column, group_name in enumerate(first_row):
        if not group_name or looks_numeric(group_name):
            continue
        group_header = second_row[column] if column < len(second_row) else ""
        if (
            cell_token(group_header) not in {"sample", "sample id", "specimen", "id"}
            and "样品" not in group_header
        ):
            continue
        metrics_in_block: list[str] = []
        for metric_column in range(column + 1, min(column + 4, raw.shape[1])):
            header = second_row[metric_column]
            if not header:
                continue
            if (
                cell_token(header) in {"sample", "sample id", "specimen", "id"}
                or "样品" in header
            ):
                continue
            values = pd.to_numeric(raw.iloc[2:, metric_column], errors="coerce")
            if values.notna().any():
                metrics_in_block.append(header)
        if metrics_in_block:
            block_names.append(group_name)
            metric_names.extend(metrics_in_block)
    if len(block_names) < 2 or not metric_names:
        return None

    evidence = canonicalize_token(
        " ".join([str(source_path or ""), *first_row, *second_row])
    )
    impact_terms = (
        "impact",
        "resistence",
        "resistance",
        "foam",
        "izod",
        "charpy",
        "kj/m2",
        "kj/m²",
        "energy",
    )
    family = "impact" if any(term in evidence for term in impact_terms) else "metrics"
    return SourceIntent(
        experiment_family=family,
        model="replicate_table",
        recommended_template="bar" if family == "impact" else "box",
        reason=(
            "Detected a grouped impact/metrics workbook with replicate "
            "measurements per sample group."
            if family == "impact"
            else "Detected a grouped metrics workbook with replicate "
            "measurements per sample group."
        ),
        metric_columns=dedupe_labels(metric_names),
    )


def _metrics_table_intent(raw: pd.DataFrame) -> SourceIntent | None:
    header_row = header_row_with(
        raw,
        ({"sample", "specimen", "composition", "group"},),
        limit=2,
    )
    if header_row is None or header_row + 1 >= raw.shape[0]:
        return None
    headers = [cell_text(value) for value in raw.iloc[header_row].tolist()]
    metric_headers: list[str] = []
    for column, header in enumerate(headers):
        data = pd.to_numeric(raw.iloc[header_row + 1 :, column], errors="coerce")
        if not data.notna().any() or cell_token(header) in {"sample", "specimen"}:
            continue
        token = cell_token(header)
        if not header.replace("_", "").isalnum() or any(
            word in token
            for word in (
                "impact",
                "strength",
                "density",
                "modulus",
                "elongation",
                "fraction",
            )
        ):
            metric_headers.append(normalize_label(header) or f"Metric {column + 1}")
    if len(metric_headers) < 2:
        return None
    family = (
        "impact"
        if any(
            "impact" in cell_token(header) or "foam" in cell_token(header)
            for header in headers
        )
        else "metrics"
    )
    return SourceIntent(
        experiment_family=family,
        model="table_summary",
        recommended_template="bar",
        reason=(
            "Detected a compact sample metrics table; plotting every numeric "
            "column would hide table semantics."
        ),
        metric_columns=dedupe_labels(metric_headers),
    )


def detect_source_intent(
    raw: pd.DataFrame,
    source_path: Path | None = None,
) -> SourceIntent | None:
    """Recognize supported experiment families without invoking a renderer."""

    compact = raw.dropna(how="all").dropna(axis=1, how="all")
    if compact.empty:
        return None

    detectors = (
        (
            "rheology",
            "frequency_metric_sheet",
            "point_line",
            "Detected a raw rheology frequency sweep with modulus/viscosity metrics.",
            (
                {"angular frequency", "frequency", "ω"},
                {"storage modulus", "g'"},
                {"loss modulus", 'g"'},
            ),
            {"angular frequency", "frequency", "ω"},
            {
                "storage modulus",
                "loss modulus",
                "complex viscosity",
                "loss factor",
                "tan delta",
                "g'",
                'g"',
            },
            "log",
            "log",
            False,
            None,
        ),
        (
            "mechanical",
            "tensile_curve",
            "curve",
            "Detected a raw mechanical stress/force versus strain table.",
            (
                {"strain", "elongation", "extension"},
                {"stress", "force", "load"},
            ),
            {"strain", "elongation", "extension"},
            {"stress", "force", "load"},
            "linear",
            "linear",
            False,
            None,
        ),
        (
            "spectroscopy",
            "curve_table",
            "curve",
            (
                "Detected spectroscopy trace columns with wavenumber/wavelength "
                "and response values."
            ),
            (
                {"wavenumber", "wavelength"},
                {"transmittance", "absorbance", "%t", "intensity"},
            ),
            {"wavenumber", "wavelength"},
            {"transmittance", "absorbance", "%t", "intensity"},
            "linear",
            "linear",
            True,
            "none",
        ),
        (
            "thermal",
            "curve_table",
            "curve",
            (
                "Detected thermal analysis columns with temperature and "
                "weight/heat-flow response."
            ),
            (
                {"temp", "temperature", "temp c", "temp (c)"},
                {"weight", "heat flow", "mass", "dtg"},
            ),
            {"temp", "temperature", "temp c", "temp (c)"},
            {"weight", "heat flow", "mass", "dtg"},
            "linear",
            "linear",
            False,
            None,
        ),
        (
            "scattering",
            "curve_table",
            "curve",
            ("Detected scattering/diffraction columns with q or 2theta and intensity."),
            (
                {"q", "q nm-1", "2theta", "2 theta", "2θ"},
                {"intensity", "counts", "count"},
            ),
            {"q", "q nm-1", "2theta", "2 theta", "2θ"},
            {"intensity", "counts", "count"},
            "linear",
            "linear",
            False,
            None,
        ),
        (
            "swelling_gel",
            "curve_table",
            "point_line",
            "Detected swelling/gel time-series columns with sample grouping.",
            (
                {"time", "time h", "time hr", "time min"},
                {"swelling ratio", "swelling", "gel fraction"},
            ),
            {"time", "time h", "time hr", "time min"},
            {"swelling ratio", "swelling"},
            "linear",
            "linear",
            False,
            None,
        ),
        (
            "chromatography",
            "curve_table",
            "curve",
            (
                "Detected a calibrated GPC/SEC molar-mass distribution."
            ),
            (
                {"molar mass", "molecular weight", "mw"},
                {"dwdlogm", "differential weight fraction", "weight distribution"},
            ),
            {"molar mass", "molecular weight", "mw"},
            {"dwdlogm", "differential weight fraction", "weight distribution"},
            "log",
            "linear",
            False,
            None,
        ),
    )
    for (
        family,
        model,
        template,
        reason,
        required,
        x_terms,
        y_terms,
        xscale,
        yscale,
        reverse_x,
        baseline,
    ) in detectors:
        header_row = header_row_with(compact, required)
        if header_row is None:
            continue
        intent = _curve_intent(
            compact,
            family=family,
            model=model,
            template=template,
            reason=reason,
            header_row=header_row,
            x_terms=x_terms,
            y_terms=y_terms,
            xscale=xscale,
            yscale=yscale,
            reverse_x=reverse_x,
            baseline=baseline,
        )
        if family == "spectroscopy":
            x_column = columns_matching(compact, header_row, x_terms)[0]
            return SourceIntent(
                **{
                    **intent.__dict__,
                    "reverse_x": cell_token(compact.iloc[header_row, x_column])
                    == "wavenumber",
                }
            )
        if family == "rheology":
            y_columns = columns_matching(compact, header_row, y_terms)
            return SourceIntent(
                **{
                    **intent.__dict__,
                    "metric_columns": dedupe_labels(
                        [
                            cell_text(compact.iloc[header_row, column])
                            for column in y_columns
                        ]
                    ),
                }
            )
        return intent

    return _block_metric_intent(compact, source_path) or _metrics_table_intent(compact)


__all__ = ["detect_source_intent"]
