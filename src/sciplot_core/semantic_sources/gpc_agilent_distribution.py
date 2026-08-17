"""Parse instrument-calibrated distributions from Agilent GPC workbooks."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from sciplot_core.foundation.text_values import clean_text, token
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.table_scanning import _float


def read_agilent_gpc_distribution(
    source: Path,
    tables: list[tuple[str, Any]],
) -> CurveSeriesPayload | None:
    """Read instrument-exported Mw/LogM/dW/dLogM columns without recalculation."""

    sample, sample_evidence, collection_point_count = _workbook_identity(
        source,
        tables,
    )
    best_points: list[tuple[float, float]] = []
    best_diagnostics: dict[str, Any] = {}
    for table_name, raw in tables:
        for header_index in range(max(0, raw.shape[0] - 1)):
            headers = [token(value) for value in raw.iloc[header_index].tolist()]
            x_index = _first_index(
                headers,
                {"mwgmol", "molarmassgmol", "molecularweightgmol"},
            )
            y_index = _first_index(headers, {"dwdlogm", "dwdlogmolarmass"})
            logm_index = _first_index(headers, {"logm"})
            outside_index = _first_index(headers, {"outsidecalib"})
            if x_index is None or y_index is None or logm_index is None:
                continue
            points, logm_values, row_evidence = _distribution_rows(
                source,
                raw,
                header_index=header_index,
                x_index=x_index,
                y_index=y_index,
                logm_index=logm_index,
                outside_index=outside_index,
            )
            if len(points) <= len(best_points):
                continue
            best_points = points
            best_diagnostics = {
                "source_table": table_name,
                "source_header_row_index": header_index,
                "source_x_header": clean_text(raw.iat[header_index, x_index]),
                "source_y_header": clean_text(raw.iat[header_index, y_index]),
                "source_x_column_index": x_index,
                "source_y_column_index": y_index,
                "source_x_unit_detection": "detected_from_header",
                "source_x_unit_detection_row_index": header_index,
                "source_x_unit_detection_value": "g/mol",
                "source_y_unit_detection": (
                    "detected_dimensionless_distribution_header"
                ),
                "source_y_unit_detection_row_index": header_index,
                "source_y_unit_detection_value": "",
                "source_logm_header": clean_text(raw.iat[header_index, logm_index]),
                "source_logm_column_index": logm_index,
                "source_logm_max_abs_error": max(
                    abs(math.log10(point[0]) - logm)
                    for point, logm in zip(points, logm_values, strict=True)
                ),
                "source_distribution_integral_dlogm": _distribution_integral(
                    points,
                    logm_values,
                ),
                **row_evidence,
            }
    if not best_points:
        return None
    return CurveSeriesPayload(
        sample=sample,
        x_label="Molar mass",
        x_unit="g/mol",
        y_label="Differential weight fraction",
        y_unit="",
        points=tuple(best_points),
        diagnostics={
            **best_diagnostics,
            **sample_evidence,
            "source_file": str(source.resolve()),
            "source_collection_point_count": collection_point_count,
        },
    )


def _workbook_identity(
    source: Path,
    tables: list[tuple[str, Any]],
) -> tuple[str, dict[str, Any], int | None]:
    sample = source.stem
    sample_evidence: dict[str, Any] = {
        "source_sample_detection": "fallback_from_source_file",
        "source_sample_table": source.name,
        "source_sample_row_index": None,
        "source_sample_column_index": None,
        "source_sample_value": sample,
    }
    collection_point_count: int | None = None
    for table_name, raw in tables:
        for row_index in range(raw.shape[0]):
            first = token(raw.iat[row_index, 0]) if raw.shape[1] else ""
            if first == "samplename" and raw.shape[1] > 1:
                detected_sample = clean_text(raw.iat[row_index, 1]) or sample
                if (
                    sample_evidence["source_sample_detection"]
                    != "fallback_from_source_file"
                    and detected_sample != sample
                ):
                    raise ValueError(
                        f"Conflicting GPC sample names in {source}: "
                        f"{sample!r} and {detected_sample!r}."
                    )
                sample = detected_sample
                sample_evidence = {
                    "source_sample_detection": "detected_from_workbook_sample_name",
                    "source_sample_table": table_name,
                    "source_sample_row_index": row_index,
                    "source_sample_column_index": 1,
                    "source_sample_value": sample,
                }
            if first == "numberofdatapoints" and raw.shape[1] > 1:
                numeric_count = _float(raw.iat[row_index, 1])
                if numeric_count is not None and math.isfinite(numeric_count):
                    collection_point_count = int(numeric_count)
    return sample, sample_evidence, collection_point_count


def _distribution_rows(
    source: Path,
    raw: Any,
    *,
    header_index: int,
    x_index: int,
    y_index: int,
    logm_index: int,
    outside_index: int | None,
) -> tuple[list[tuple[float, float]], list[float], dict[str, Any]]:
    points: list[tuple[float, float]] = []
    logm_values: list[float] = []
    excluded = {"empty": 0, "partial": 0, "nonfinite": 0}
    outside_counts: dict[str, int] = {}
    for row_index in range(header_index + 1, raw.shape[0]):
        raw_x = clean_text(raw.iat[row_index, x_index])
        raw_y = clean_text(raw.iat[row_index, y_index])
        raw_logm = clean_text(raw.iat[row_index, logm_index])
        x_value = _float(raw.iat[row_index, x_index])
        y_value = _float(raw.iat[row_index, y_index])
        logm_value = _float(raw.iat[row_index, logm_index])
        if not raw_x and not raw_y and not raw_logm:
            excluded["empty"] += 1
            continue
        if x_value is None or y_value is None or logm_value is None:
            excluded["partial"] += 1
            continue
        if (
            not math.isfinite(x_value)
            or not math.isfinite(y_value)
            or not math.isfinite(logm_value)
            or x_value <= 0.0
        ):
            excluded["nonfinite"] += 1
            continue
        if not math.isclose(
            math.log10(x_value),
            logm_value,
            rel_tol=0.0,
            abs_tol=1e-6,
        ):
            raise ValueError(
                f"GPC Mw and LogM columns disagree in {source} at "
                f"source row {row_index + 1}."
            )
        points.append((x_value, y_value))
        logm_values.append(logm_value)
        if outside_index is not None:
            status = clean_text(raw.iat[row_index, outside_index])
            if status:
                outside_counts[status] = outside_counts.get(status, 0) + 1
    return points, logm_values, {
        "source_outside_calibration_counts": outside_counts,
        "candidate_row_count": raw.shape[0] - header_index - 1,
        "retained_point_count": len(points),
        "excluded_empty_pair_count": excluded["empty"],
        "excluded_partial_or_nonnumeric_pair_count": excluded["partial"],
        "excluded_nonfinite_pair_count": excluded["nonfinite"],
    }


def _distribution_integral(
    points: list[tuple[float, float]],
    logm_values: list[float],
) -> float:
    return sum(
        0.5
        * (points[index][1] + points[index + 1][1])
        * abs(logm_values[index] - logm_values[index + 1])
        for index in range(len(points) - 1)
    )


def _first_index(values: list[str], accepted: set[str]) -> int | None:
    return next((index for index, value in enumerate(values) if value in accepted), None)


__all__ = ["read_agilent_gpc_distribution"]
