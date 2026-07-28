"""Read GPC chromatogram series and enforce positive SAXS logarithmic domains."""

from __future__ import annotations

import math
from pathlib import Path
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
    token as _token,
)


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)

from sciplot_core.semantic_sources.table_scanning import (
    _float,
    _read_candidate_tables,
    _scan_curve_series_source,
)


def _read_agilent_gpc_series(source: Path) -> CurveSeriesPayload | None:
    """Read the analysed RT/RI slice from an Agilent GPC/SEC workbook."""

    tables = _read_candidate_tables(source)
    sample = source.stem
    detector_unit = "a.u."
    for _table_name, raw in tables:
        for row_index in range(min(raw.shape[0], 80)):
            first = _token(raw.iat[row_index, 0]) if raw.shape[1] else ""
            if first == "samplename" and raw.shape[1] > 1:
                sample = _clean_text(raw.iat[row_index, 1]) or sample
            headers = [_token(value) for value in raw.iloc[row_index].tolist()]
            if "detectortype" not in headers or "detectorunits" not in headers:
                continue
            detector_column = headers.index("detectortype")
            unit_column = headers.index("detectorunits")
            for data_index in range(row_index + 1, min(raw.shape[0], row_index + 16)):
                if _token(raw.iat[data_index, detector_column]) != "ri":
                    continue
                detector_unit = (
                    _clean_text(raw.iat[data_index, unit_column]) or detector_unit
                )
                break

    best_points: list[tuple[float, float]] = []
    best_table = ""
    for table_name, raw in tables:
        for header_index in range(max(0, raw.shape[0] - 1)):
            headers = [_token(value) for value in raw.iloc[header_index].tolist()]
            x_index = next(
                (
                    index
                    for index, value in enumerate(headers)
                    if value in {"rt", "rtmin", "rtmins"}
                ),
                None,
            )
            y_index = next(
                (index for index, value in enumerate(headers) if value == "ri"), None
            )
            if x_index is None or y_index is None:
                continue
            points: list[tuple[float, float]] = []
            for row_index in range(header_index + 1, raw.shape[0]):
                x_value = _float(raw.iat[row_index, x_index])
                y_value = _float(raw.iat[row_index, y_index])
                if x_value is not None and y_value is not None:
                    points.append((x_value, y_value))
            if len(points) > len(best_points):
                best_points = points
                best_table = table_name
    if not best_points:
        return None
    if _float(sample) is not None:
        sample = f"Sample {sample}"
    return CurveSeriesPayload(
        sample=sample,
        x_label="Elution time",
        x_unit="min",
        y_label="Detector response",
        y_unit=detector_unit,
        points=tuple(best_points),
        diagnostics={
            "source_table": best_table,
            "source_file": source.name,
            "detector": "RI",
            "detector_unit": detector_unit,
        },
    )


def _read_gpc_series_list(source: Path) -> list[CurveSeriesPayload]:
    """Extract one or more RI chromatograms from Agilent or canonical GPC tables."""

    paths = (
        [
            path
            for path in sorted(source.rglob("*"))
            if path.is_file()
            and path.suffix.lower() in {".csv", ".tsv", ".txt", ".xlsx", ".xls"}
        ]
        if source.is_dir()
        else [source]
    )
    result: list[CurveSeriesPayload] = []
    for path in paths:
        agilent_series = _read_agilent_gpc_series(path)
        if agilent_series is not None:
            candidate = [agilent_series]
        else:
            candidate = _scan_curve_series_source(
                path,
                x_aliases=("elution time", "time", "rt"),
                y_aliases=("detector response", "rayleigh ratio", "dri", "ri"),
                x_label="Elution time",
                y_label="Detector response",
                default_x_unit="min",
                default_y_unit="a.u.",
                sample_prefix=path.stem,
            )
        if len(candidate) == 1:
            item = candidate[0]
            sample = item.sample if agilent_series is not None else path.stem
            candidate = [
                CurveSeriesPayload(
                    sample=sample,
                    x_label=item.x_label,
                    x_unit=item.x_unit,
                    y_label=item.y_label,
                    y_unit=item.y_unit,
                    points=item.points,
                    diagnostics={**(item.diagnostics or {}), "source_file": path.name},
                )
            ]
        else:
            candidate = [
                CurveSeriesPayload(
                    sample=item.sample,
                    x_label=item.x_label,
                    x_unit=item.x_unit,
                    y_label=item.y_label,
                    y_unit=item.y_unit,
                    points=item.points,
                    diagnostics={**(item.diagnostics or {}), "source_file": path.name},
                )
                for item in candidate
            ]
        result.extend(candidate)
    return result


def _retain_positive_saxs_log_domain(
    series: CurveSeriesPayload,
) -> CurveSeriesPayload:
    source_point_count = len(series.points)
    excluded_nonpositive_q_count = sum(
        math.isfinite(q_value) and q_value <= 0.0
        for q_value, _intensity in series.points
    )
    excluded_nonpositive_intensity_count = sum(
        math.isfinite(intensity) and intensity <= 0.0
        for _q_value, intensity in series.points
    )
    excluded_nonfinite_count = sum(
        not (math.isfinite(q_value) and math.isfinite(intensity))
        for q_value, intensity in series.points
    )
    retained = tuple(
        (q_value, intensity)
        for q_value, intensity in series.points
        if (
            math.isfinite(q_value)
            and math.isfinite(intensity)
            and q_value > 0.0
            and intensity > 0.0
        )
    )
    if len(retained) < 2:
        raise ValueError(
            f"SAXS series {series.sample!r} has fewer than two finite points "
            "with q > 0 and intensity > 0; logarithmic plotting is blocked."
        )
    return CurveSeriesPayload(
        sample=series.sample,
        x_label=series.x_label,
        x_unit=series.x_unit,
        y_label=series.y_label,
        y_unit=series.y_unit,
        points=retained,
        diagnostics={
            **(series.diagnostics or {}),
            "source_point_count": source_point_count,
            "excluded_nonpositive_q_count": excluded_nonpositive_q_count,
            "excluded_nonpositive_intensity_count": (
                excluded_nonpositive_intensity_count
            ),
            "excluded_nonfinite_point_count": excluded_nonfinite_count,
            "selected_point_count": len(retained),
            "log_domain_policy": (
                "retain only finite q > 0 and intensity > 0 for logarithmic axes"
            ),
            "retained_positive_values_preserved_without_scaling": True,
            "sciplot_intensity_scale_factor": 1.0,
            "sciplot_intensity_offset": 0.0,
            "source_series_scaling_status": ("not_validated_from_source_metadata"),
            "absolute_cross_series_intensity_comparison_validated": False,
            "intensity_offset_policy": (
                "preserve source intensity values; do not infer or remove offsets"
            ),
        },
    )
