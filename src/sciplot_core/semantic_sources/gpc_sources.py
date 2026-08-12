"""Read GPC chromatogram series."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.foundation.text_values import (
    clean_text as _clean_text,
    token as _token,
)


from sciplot_core.semantic_sources.models import (
    CurveSeriesPayload,
)
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)
from sciplot_core.semantic_sources.gpc_transform_contract import (
    build_gpc_transform_contract,
    gpc_exclusions,
)
from sciplot_core.semantic_sources.series_ordering import (
    _order_curve_series,
    _series_order_map,
)

from sciplot_core.semantic_sources.table_scanning import (
    _float,
    _read_candidate_tables,
    _scan_curve_series_table,
)


def _read_agilent_gpc_series(
    source: Path,
    tables: list[tuple[str, Any]],
) -> CurveSeriesPayload | None:
    """Read the analysed RT/RI slice from an Agilent GPC/SEC workbook."""

    sample = source.stem
    sample_evidence: dict[str, Any] = {
        "source_sample_detection": "fallback_from_source_file",
        "source_sample_table": source.name,
        "source_sample_row_index": None,
        "source_sample_column_index": None,
        "source_sample_value": sample,
    }
    detector_unit = ""
    detector_evidence: dict[str, Any] = {}
    collection_point_count: int | None = None
    for table_name, raw in tables:
        for row_index in range(raw.shape[0]):
            first = _token(raw.iat[row_index, 0]) if raw.shape[1] else ""
            if first == "samplename" and raw.shape[1] > 1:
                detected_sample = _clean_text(raw.iat[row_index, 1]) or sample
                if sample_evidence["source_sample_detection"] != (
                    "fallback_from_source_file"
                ) and detected_sample != sample:
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
            headers = [_token(value) for value in raw.iloc[row_index].tolist()]
            if "detectortype" not in headers or "detectorunits" not in headers:
                continue
            detector_column = headers.index("detectortype")
            unit_column = headers.index("detectorunits")
            for data_index in range(row_index + 1, raw.shape[0]):
                if _token(raw.iat[data_index, detector_column]) != "ri":
                    continue
                detected_unit = _clean_text(raw.iat[data_index, unit_column]) or ""
                if detector_unit and detected_unit != detector_unit:
                    raise ValueError(
                        f"Conflicting GPC RI detector units in {source}: "
                        f"{detector_unit!r} and {detected_unit!r}."
                    )
                detector_unit = detected_unit
                detector_evidence = {
                    "source_y_unit_detection": "detected_from_detector_metadata",
                    "source_y_unit_detection_table": table_name,
                    "source_y_unit_detection_row_index": data_index,
                    "source_y_unit_detection_column_index": unit_column,
                    "source_y_unit_detection_value": detector_unit,
                }
                break

    best_points: list[tuple[float, float]] = []
    best_diagnostics: dict[str, Any] = {}
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
            empty_pair_count = 0
            partial_pair_count = 0
            nonfinite_pair_count = 0
            for row_index in range(header_index + 1, raw.shape[0]):
                raw_x = _clean_text(raw.iat[row_index, x_index])
                raw_y = _clean_text(raw.iat[row_index, y_index])
                x_value = _float(raw.iat[row_index, x_index])
                y_value = _float(raw.iat[row_index, y_index])
                if not raw_x and not raw_y:
                    empty_pair_count += 1
                elif x_value is None or y_value is None:
                    partial_pair_count += 1
                elif not math.isfinite(x_value) or not math.isfinite(y_value):
                    nonfinite_pair_count += 1
                else:
                    points.append((x_value, y_value))
            if len(points) > len(best_points):
                best_points = points
                best_diagnostics = {
                    "source_table": table_name,
                    "source_header_row_index": header_index,
                    "source_x_header": _clean_text(raw.iat[header_index, x_index]),
                    "source_y_header": _clean_text(raw.iat[header_index, y_index]),
                    "source_x_column_index": x_index,
                    "source_y_column_index": y_index,
                    "source_x_unit_detection": "detected_from_header",
                    "source_x_unit_detection_row_index": header_index,
                    "source_x_unit_detection_value": "min",
                    "candidate_row_count": raw.shape[0] - header_index - 1,
                    "retained_point_count": len(points),
                    "excluded_empty_pair_count": empty_pair_count,
                    "excluded_partial_or_nonnumeric_pair_count": partial_pair_count,
                    "excluded_nonfinite_pair_count": nonfinite_pair_count,
                }
    if not best_points:
        return None
    return CurveSeriesPayload(
        sample=sample,
        x_label="Elution time",
        x_unit="min",
        y_label="Detector response",
        y_unit=detector_unit,
        points=tuple(best_points),
        diagnostics={
            **best_diagnostics,
            **sample_evidence,
            **detector_evidence,
            "source_file": str(source.resolve()),
            "detector": "RI",
            "detector_unit": detector_unit,
            "source_collection_point_count": collection_point_count,
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
        tables = _read_candidate_tables(path)
        agilent_series = _read_agilent_gpc_series(path, tables)
        if agilent_series is not None:
            candidate = [agilent_series]
        else:
            candidate = _scan_gpc_tables(tables, sample_prefix=path.stem)
        if len(candidate) == 1:
            item = candidate[0]
            sample = item.sample
            candidate = [
                CurveSeriesPayload(
                    sample=sample,
                    x_label=item.x_label,
                    x_unit=item.x_unit,
                    y_label=item.y_label,
                    y_unit=item.y_unit,
                    points=item.points,
                    diagnostics={
                        **(item.diagnostics or {}),
                        "source_file": str(path.resolve()),
                    },
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
                    diagnostics={
                        **(item.diagnostics or {}),
                        "source_file": str(path.resolve()),
                    },
                )
                for item in candidate
            ]
        result.extend(candidate)
    return result


def _scan_gpc_tables(
    tables: list[tuple[str, Any]],
    *,
    sample_prefix: str,
) -> list[CurveSeriesPayload]:
    best: list[CurveSeriesPayload] = []
    for table_name, raw in tables:
        series = _scan_curve_series_table(
            raw,
            x_aliases=("elution time", "time", "rt"),
            y_aliases=("detector response", "rayleigh ratio", "dri", "ri"),
            x_label="Elution time",
            y_label="Detector response",
            default_x_unit="min",
            default_y_unit="mV",
            sample_prefix=table_name or sample_prefix,
        )
        if sum(len(item.points) for item in series) > sum(
            len(item.points) for item in best
        ):
            best = [
                CurveSeriesPayload(
                    sample=item.sample,
                    x_label=item.x_label,
                    x_unit=item.x_unit,
                    y_label=item.y_label,
                    y_unit=item.y_unit,
                    points=item.points,
                    diagnostics={
                        **(item.diagnostics or {}),
                        "source_table": table_name,
                    },
                )
                for item in series
            ]
    return best


def resolve_gpc_scientific_transform(
    source: Path,
    *,
    rule: SemanticRule,
    series_order: object = None,
) -> ResolvedScientificTransform:
    """Resolve Agilent or canonical GPC traces without changing their identity."""

    series_list = _read_gpc_series_list(source.expanduser().resolve())
    if not series_list:
        raise ValueError(f"No finite GPC RI chromatogram found in {source}.")
    explicit_order = bool(_series_order_map(series_order))
    if explicit_order:
        series_list = _order_curve_series(series_list, series_order)
    normalized = [_normalize_gpc_series(item, rule=rule) for item in series_list]
    samples = [item.sample for item in normalized]
    if any(not sample for sample in samples) or len(samples) != len(set(samples)):
        raise ValueError("GPC series need non-empty unique source sample labels.")
    selected_sources = tuple(
        dict.fromkeys(
            Path(str((item.diagnostics or {})["source_file"])).resolve()
            for item in normalized
        )
    )
    return ResolvedScientificTransform(
        series=tuple(normalized),
        contract=build_gpc_transform_contract(
            normalized,
            rule=rule,
            selected_sources=selected_sources,
            explicit_series_order_applied=explicit_order,
        ),
        selected_sources=selected_sources,
    )


def _normalize_gpc_series(
    series: CurveSeriesPayload,
    *,
    rule: SemanticRule,
) -> CurveSeriesPayload:
    diagnostics = dict(series.diagnostics or {})
    source_x_unit = str(
        diagnostics.get("source_x_unit_detection_value") or series.x_unit
    )
    source_y_unit = str(
        diagnostics.get("source_y_unit_detection_value") or series.y_unit
    )
    for axis in ("x", "y"):
        detection = str(diagnostics.get(f"source_{axis}_unit_detection") or "")
        if not detection or detection == "default_due_to_missing_unit_row":
            raise ValueError(
                f"GPC {axis} unit must be explicit in the selected source."
            )
    _require_gpc_identity_unit(
        source_x_unit,
        canonical_unit=rule.x_axis.canonical_unit,
        axis="x",
    )
    _require_gpc_identity_unit(
        source_y_unit,
        canonical_unit=rule.y_axis.canonical_unit,
        axis="y",
    )
    sample_value = str(diagnostics.get("source_sample_value") or "")
    if not diagnostics.get("source_sample_detection") or sample_value != series.sample:
        raise ValueError(f"GPC sample identity is not source-derived for {series.sample!r}.")
    candidate = int(diagnostics.get("candidate_row_count") or 0)
    exclusions = gpc_exclusions(diagnostics)
    if candidate != len(series.points) + sum(exclusions.values()):
        raise ValueError(f"GPC row evidence is incomplete for {series.sample!r}.")
    if exclusions["nonfinite"]:
        raise ValueError(f"GPC source contains nonfinite values for {series.sample!r}.")
    if not all(
        math.isfinite(x_value) and math.isfinite(y_value)
        for x_value, y_value in series.points
    ):
        raise ValueError(f"GPC series {series.sample!r} is not finite.")
    return CurveSeriesPayload(
        sample=series.sample,
        x_label=rule.x_axis.canonical_label,
        x_unit=rule.x_axis.canonical_unit,
        y_label=rule.y_axis.canonical_label,
        y_unit=rule.y_axis.canonical_unit,
        points=series.points,
        diagnostics={
            **diagnostics,
            "canonical_x_unit": rule.x_axis.canonical_unit,
            "canonical_y_unit": rule.y_axis.canonical_unit,
        },
    )


def _require_gpc_identity_unit(
    source_unit: str,
    *,
    canonical_unit: str,
    axis: str,
) -> None:
    source_token = "".join(source_unit.casefold().split())
    canonical_token = "".join(canonical_unit.casefold().split())
    if canonical_token == "min" and source_token == "mins":
        source_token = "min"
    if source_token != canonical_token:
        raise ValueError(
            f"Unsupported GPC {axis} unit {source_unit!r}; expected an "
            f"identity-equivalent {canonical_unit!r} unit."
        )


__all__ = ["resolve_gpc_scientific_transform"]
