"""Resolve one registered paired-curve rule into a source-bound transform."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from sciplot_core.materials_rules.models import SemanticRule
from sciplot_core.materials_rules.unit_formatting import format_unit_label
from sciplot_core.semantic_sources.models import CurveSeriesPayload
from sciplot_core.semantic_sources.registered_paired_curve_contract import (
    build_registered_paired_curve_contract,
    validate_registered_paired_curve_row_evidence,
)
from sciplot_core.semantic_sources.scientific_transform import (
    ResolvedScientificTransform,
)
from sciplot_core.semantic_sources.series_ordering import (
    _order_curve_series,
    _series_order_map,
)
from sciplot_core.semantic_sources.table_scanning import _scan_curve_series_source
from sciplot_core.semantic_sources.table_source_files import (
    resolve_single_table_source,
)
from sciplot_core.source_tables import slugify_canonical_label


_EXPLICIT_UNIT_DETECTIONS = frozenset(
    {
        "detected_from_adjacent_unit_row",
        "detected_from_header",
        "detected_from_instrument_export_schema",
    }
)
_SOURCE_SAMPLE_DETECTIONS = frozenset(
    {
        "detected_from_adjacent_sample_row",
        "detected_from_instrument_metadata",
        "detected_from_preceding_sample_row",
        "fallback_from_source_table",
    }
)


def resolve_registered_paired_curve_transform(
    source: Path,
    *,
    rule: SemanticRule,
    series_order: object = None,
) -> ResolvedScientificTransform:
    """Resolve one finite paired curve using only its registered rule contract."""

    resolved_source = resolve_single_table_source(
        source,
        context=f"{rule.rule_id} paired-curve transform",
    )
    x_metric = slugify_canonical_label(rule.x_axis.canonical_label)
    y_metric = slugify_canonical_label(rule.y_axis.canonical_label)
    series_list = _scan_curve_series_source(
        resolved_source,
        x_aliases=_axis_aliases(
            rule.x_axis.canonical_label,
            rule.x_axis.aliases,
        ),
        y_aliases=_axis_aliases(
            rule.y_axis.canonical_label,
            rule.y_axis.aliases,
        ),
        x_label=rule.x_axis.canonical_label,
        y_label=rule.y_axis.canonical_label,
        default_x_unit=rule.x_axis.canonical_unit,
        default_y_unit=rule.y_axis.canonical_unit,
        sample_prefix=resolved_source.stem,
    )
    if not series_list:
        raise ValueError(
            f"No finite {x_metric}/{y_metric} curve found in {resolved_source}."
        )
    explicit_order = bool(_series_order_map(series_order))
    if explicit_order:
        series_list = _order_curve_series(series_list, series_order)
    projected = [
        _project_registered_log_domain(series, rule=rule) for series in series_list
    ]
    normalized = [
        _normalize_series(series, source=resolved_source, rule=rule)
        for series in projected
    ]
    _validate_source_derived_samples(normalized, rule_id=rule.rule_id)
    selected_sources = (resolved_source,)
    return ResolvedScientificTransform(
        series=tuple(normalized),
        contract=build_registered_paired_curve_contract(
            normalized,
            rule=rule,
            selected_sources=selected_sources,
            explicit_series_order_applied=explicit_order,
        ),
        selected_sources=selected_sources,
    )


def _axis_aliases(canonical_label: str, aliases: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(dict.fromkeys((canonical_label, *aliases)))


def _project_registered_log_domain(
    series: CurveSeriesPayload,
    *,
    rule: SemanticRule,
) -> CurveSeriesPayload:
    x_log = rule.x_axis.scale == "log"
    y_log = rule.y_axis.scale == "log"
    if not (x_log or y_log):
        return series

    retained: list[tuple[float, float]] = []
    excluded_x = 0
    excluded_y = 0
    for x_value, y_value in series.points:
        if x_log and x_value <= 0.0:
            excluded_x += 1
        elif y_log and y_value <= 0.0:
            excluded_y += 1
        else:
            retained.append((x_value, y_value))
    if not retained:
        raise ValueError(
            f"{rule.rule_id} series {series.sample!r} has no points in its "
            "registered logarithmic render domain."
        )

    diagnostics = dict(series.diagnostics or {})
    diagnostics["retained_point_count"] = len(retained)
    if x_log:
        diagnostics["excluded_nonpositive_log_x_count"] = excluded_x
    if y_log:
        diagnostics["excluded_nonpositive_log_y_count"] = excluded_y
    diagnostics.update(
        {
            "render_domain_projection": (
                "exclude_nonpositive_values_for_registered_log_axes"
            ),
            "render_domain_projection_axes": [
                axis for axis, active in (("x", x_log), ("y", y_log)) if active
            ],
            "retained_values_preserved_without_numeric_transform": True,
        }
    )
    return CurveSeriesPayload(
        sample=series.sample,
        x_label=series.x_label,
        x_unit=series.x_unit,
        y_label=series.y_label,
        y_unit=series.y_unit,
        points=tuple(retained),
        diagnostics=diagnostics,
    )


def _normalize_series(
    series: CurveSeriesPayload,
    *,
    source: Path,
    rule: SemanticRule,
) -> CurveSeriesPayload:
    diagnostics = dict(series.diagnostics or {})
    source_x_unit = _required_explicit_unit(
        diagnostics,
        prefix="x",
        metric=slugify_canonical_label(rule.x_axis.canonical_label),
        sample=series.sample,
        rule_id=rule.rule_id,
    )
    source_y_unit = _required_explicit_unit(
        diagnostics,
        prefix="y",
        metric=slugify_canonical_label(rule.y_axis.canonical_label),
        sample=series.sample,
        rule_id=rule.rule_id,
    )
    output_x_unit = _resolve_output_unit(
        source_x_unit,
        canonical_unit=rule.x_axis.canonical_unit,
        axis="x",
        rule_id=rule.rule_id,
    )
    output_y_unit = _resolve_output_unit(
        source_y_unit,
        canonical_unit=rule.y_axis.canonical_unit,
        axis="y",
        rule_id=rule.rule_id,
    )
    source_display_policy = (
        {
            "source_y_display_policy": (
                "raw_detector_counts_presented_as_arbitrary_intensity"
            ),
            "source_y_numeric_scaling_applied": False,
            "source_y_values_preserved": True,
        }
        if rule.rule_id == "xrd_pattern"
        and _comparable_unit(source_y_unit) in {"count", "counts"}
        and _comparable_unit(output_y_unit) == "a.u."
        else {}
    )
    validate_registered_paired_curve_row_evidence(
        series,
        diagnostics,
        rule_id=rule.rule_id,
    )
    return CurveSeriesPayload(
        sample=series.sample,
        x_label=rule.x_axis.canonical_label,
        x_unit=output_x_unit,
        y_label=rule.y_axis.canonical_label,
        y_unit=output_y_unit,
        points=series.points,
        diagnostics={
            **diagnostics,
            "source_file": str(source),
            "canonical_x_unit": output_x_unit,
            "canonical_y_unit": output_y_unit,
            "registered_default_x_unit": rule.x_axis.canonical_unit,
            "registered_default_y_unit": rule.y_axis.canonical_unit,
            **source_display_policy,
        },
    )


def _required_explicit_unit(
    diagnostics: dict[str, Any],
    *,
    prefix: str,
    metric: str,
    sample: str,
    rule_id: str,
) -> str:
    detection = str(diagnostics.get(f"source_{prefix}_unit_detection") or "")
    value = str(diagnostics.get(f"source_{prefix}_unit_detection_value") or "")
    if detection not in _EXPLICIT_UNIT_DETECTIONS or not value:
        raise ValueError(
            f"Missing explicit {rule_id} {metric} unit for {sample!r}; "
            "a header unit or adjacent unit row is required."
        )
    return value


def _resolve_output_unit(
    source_unit: str,
    *,
    canonical_unit: str,
    axis: str,
    rule_id: str,
) -> str:
    if _comparable_unit(source_unit) != _comparable_unit(canonical_unit):
        if rule_id == "xrd_pattern" and axis == "y" and _comparable_unit(
            source_unit
        ) in {"count", "counts"}:
            # Raw detector counts may be presented on the registered XRD
            # arbitrary-intensity axis without changing any numeric values.
            return canonical_unit
        raise ValueError(
            f"Unsupported {rule_id} {axis} unit {source_unit!r}; expected an "
            f"identity-equivalent {canonical_unit!r} unit."
        )
    return canonical_unit


def _comparable_unit(value: str) -> str:
    normalized = value.replace("℃", "°C").replace("º", "°").replace("˚", "°")
    normalized = re.sub(r"(?<=[A-Za-z])-(?=\d)", "^-", normalized)
    normalized = re.sub(r"[·⋅×*]", " ", normalized)
    return format_unit_label(normalized)


def _validate_source_derived_samples(
    series_list: list[CurveSeriesPayload],
    *,
    rule_id: str,
) -> None:
    samples = [series.sample for series in series_list]
    if not samples or any(not sample for sample in samples) or len(samples) != len(
        set(samples)
    ):
        raise ValueError(f"{rule_id} series need non-empty unique sample labels.")
    for series in series_list:
        diagnostics = dict(series.diagnostics or {})
        detection = str(diagnostics.get("source_sample_detection") or "")
        value = str(diagnostics.get("source_sample_value") or "")
        if detection not in _SOURCE_SAMPLE_DETECTIONS or value != series.sample:
            raise ValueError(
                f"{rule_id} sample identity is not source-derived for "
                f"{series.sample!r}."
            )
__all__ = ["resolve_registered_paired_curve_transform"]
