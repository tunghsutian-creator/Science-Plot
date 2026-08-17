"""Resolve calibrated GPC/SEC molar-mass distributions."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from sciplot_core.foundation.text_values import token as _token
from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.materials_rules.unit_formatting import format_unit_label
from sciplot_core.semantic_sources.gpc_agilent_distribution import (
    read_agilent_gpc_distribution,
)
from sciplot_core.semantic_sources.gpc_transform_contract import (
    build_gpc_transform_contract,
    gpc_exclusions,
)
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)
from sciplot_core.semantic_sources.series_ordering import (
    _order_curve_series,
    _series_order_map,
)
from sciplot_core.semantic_sources.table_scanning import (
    _read_candidate_tables,
    _scan_curve_series_table,
)


def _read_gpc_series_list(source: Path) -> list[CurveSeriesPayload]:
    """Extract calibrated distributions from Agilent or canonical GPC tables."""

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
        agilent_series = read_agilent_gpc_distribution(path, tables)
        candidate = (
            [agilent_series]
            if agilent_series is not None
            else _scan_gpc_tables(tables, sample_prefix=path.stem)
        )
        result.extend(_bind_source_file(candidate, path=path))
    return result


def _bind_source_file(
    candidate: list[CurveSeriesPayload],
    *,
    path: Path,
) -> list[CurveSeriesPayload]:
    return [
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


def _scan_gpc_tables(
    tables: list[tuple[str, Any]],
    *,
    sample_prefix: str,
) -> list[CurveSeriesPayload]:
    best: list[CurveSeriesPayload] = []
    for table_name, raw in tables:
        series = _scan_curve_series_table(
            raw,
            x_aliases=("molar mass", "molecular weight", "mw"),
            y_aliases=("differential weight fraction", "dW/dLogM", "dW/dlog M"),
            x_label="Molar mass",
            y_label="Differential weight fraction",
            default_x_unit="g/mol",
            default_y_unit="",
            sample_prefix=table_name or sample_prefix,
        )
        if sum(len(item.points) for item in series) <= sum(
            len(item.points) for item in best
        ):
            continue
        best = [
            CurveSeriesPayload(
                sample=item.sample,
                x_label=item.x_label,
                x_unit=item.x_unit,
                y_label=item.y_label,
                y_unit=item.y_unit,
                points=item.points,
                diagnostics=_canonical_gpc_diagnostics(
                    item.diagnostics or {},
                    source_table=table_name,
                ),
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
    """Resolve source-calibrated GPC distributions without changing their values."""

    series_list = _read_gpc_series_list(source.expanduser().resolve())
    if not series_list:
        raise ValueError(
            "No finite calibrated GPC molar-mass distribution found in "
            f"{source}; explicit Mw (g/mol) and dW/dLogM columns are required."
        )
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
            raise ValueError(f"GPC {axis} unit must be explicit in the selected source.")
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
    if any(x_value <= 0.0 for x_value, _y_value in series.points):
        raise ValueError(
            f"GPC molar mass must be positive for the log axis in {series.sample!r}."
        )
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
    source_token = "".join(format_unit_label(source_unit).casefold().split())
    canonical_token = "".join(format_unit_label(canonical_unit).casefold().split())
    if source_token != canonical_token:
        raise ValueError(
            f"Unsupported GPC {axis} unit {source_unit!r}; expected an "
            f"identity-equivalent {canonical_unit!r} unit."
        )


def _canonical_gpc_diagnostics(
    diagnostics: dict[str, Any],
    *,
    source_table: str,
) -> dict[str, Any]:
    updated = {**diagnostics, "source_table": source_table}
    if _token(updated.get("source_y_header")) in {
        "dwdlogm",
        "dwdlogmolarmass",
    }:
        updated.update(
            {
                "source_y_unit_detection": (
                    "detected_dimensionless_distribution_header"
                ),
                "source_y_unit_detection_row_index": int(
                    updated["source_header_row_index"]
                ),
                "source_y_unit_detection_value": "",
            }
        )
    return updated


__all__ = ["resolve_gpc_scientific_transform"]
