"""Build validated material definitions from normalized performance rows."""

from __future__ import annotations

import math

import pandas as pd

from sciplot_core.performance_comparison.models import (
    PerformanceComparisonError,
    PerformanceMaterial,
)
from sciplot_core.performance_comparison.field_validation import (
    _normalized_marker,
    _normalized_marker_fill_color,
    _normalized_marker_line_color,
    _unique_bool,
    _unique_float,
    _unique_text,
)
from sciplot_core.performance_comparison.source_values import (
    _text,
    _year_text,
)


def load_performance_materials(
    normalized: pd.DataFrame,
    *,
    material_first_order: dict[str, int],
) -> list[PerformanceMaterial]:
    """Validate material identity, legend metadata, and metric uniqueness."""

    materials = [
        _load_material(
            str(material_id),
            rows,
            source_order=material_first_order[str(material_id)],
        )
        for material_id, rows in normalized.groupby("material", sort=False)
    ]
    materials.sort(
        key=lambda item: (
            item.material_order is None,
            (
                item.material_order
                if item.material_order is not None
                else item.source_order
            ),
            item.source_order,
        )
    )
    return materials


def _load_material(
    material_id: str,
    rows: pd.DataFrame,
    *,
    source_order: int,
) -> PerformanceMaterial:
    owner = f"Material {material_id!r}"
    roles = list(dict.fromkeys(str(value) for value in rows["role"]))
    if len(roles) != 1:
        raise PerformanceComparisonError(
            "performance_material_role_conflict",
            f"{owner} has conflicting Role values: {roles}.",
        )
    role = roles[0]
    legend_label = _unique_text(
        rows,
        "legend_label" if "legend_label" in rows else None,
        field="LegendLabel",
        owner=owner,
        default=material_id,
    )
    legend_column = _legend_integer(
        _unique_float(
            rows,
            "legend_column" if "legend_column" in rows else None,
            field="LegendColumn",
            owner=owner,
        ),
        owner=owner,
        field="LegendColumn",
        reason_code="performance_legend_column_invalid",
    )
    legend_items_per_row = _legend_integer(
        _unique_float(
            rows,
            ("legend_items_per_row" if "legend_items_per_row" in rows else None),
            field="LegendItemsPerRow",
            owner=owner,
        ),
        owner=owner,
        field="LegendItemsPerRow",
        reason_code="performance_legend_items_per_row_invalid",
    )
    return PerformanceMaterial(
        material_id=material_id,
        role=role,
        group=_unique_text(
            rows,
            "group" if "group" in rows else None,
            field="Group",
            owner=owner,
            default="This work" if role == "sample" else "Literature",
        ),
        envelope_include=_unique_bool(
            rows,
            "envelope_include" if "envelope_include" in rows else None,
            field="EnvelopeInclude",
            owner=owner,
            default=role == "sample",
        ),
        legend_label=legend_label,
        legend_label_explicit=bool(
            "legend_label" in rows
            and any(_text(value) for value in rows["legend_label"].tolist())
        ),
        legend_group=_unique_text(
            rows,
            "legend_group" if "legend_group" in rows else None,
            field="LegendGroup",
            owner=owner,
            default="This work" if role == "sample" else "Reference materials",
        ),
        legend_identity=_unique_text(
            rows,
            "legend_identity" if "legend_identity" in rows else None,
            field="LegendIdentity",
            owner=owner,
            default=legend_label,
        ),
        legend_column=legend_column,
        legend_items_per_row=legend_items_per_row,
        source_order=source_order,
        material_order=_unique_float(
            rows,
            "material_order" if "material_order" in rows else None,
            field="MaterialOrder",
            owner=owner,
        ),
        journal=_unique_text(
            rows,
            "journal" if "journal" in rows else None,
            field="Journal",
            owner=owner,
        ),
        year=_year_text(
            _unique_text(
                rows,
                "year" if "year" in rows else None,
                field="Year",
                owner=owner,
            )
        ),
        doi=_unique_text(
            rows,
            "doi" if "doi" in rows else None,
            field="DOI",
            owner=owner,
        ),
        marker=_normalized_marker(
            _unique_text(
                rows,
                "marker" if "marker" in rows else None,
                field="Marker",
                owner=owner,
            ),
            material_id=material_id,
        ),
        marker_line_color=_normalized_marker_line_color(
            _unique_text(
                rows,
                "marker_line_color" if "marker_line_color" in rows else None,
                field="MarkerLineColor",
                owner=owner,
            ),
            material_id=material_id,
        ),
        marker_fill_color=_normalized_marker_fill_color(
            _unique_text(
                rows,
                "marker_fill_color" if "marker_fill_color" in rows else None,
                field="MarkerFillColor",
                owner=owner,
            ),
            material_id=material_id,
        ),
        values=_material_values(rows, owner=owner),
    )


def _legend_integer(
    value: float | None,
    *,
    owner: str,
    field: str,
    reason_code: str,
) -> int:
    if value is None:
        return 1
    if value not in {1.0, 2.0} or not math.isclose(value, round(value)):
        raise PerformanceComparisonError(
            reason_code,
            f"{owner}: {field} must be 1 or 2.",
        )
    return int(round(value))


def _material_values(
    rows: pd.DataFrame,
    *,
    owner: str,
) -> dict[str, float]:
    values: dict[str, float] = {}
    for metric_id, value_rows in rows.groupby("metric", sort=False):
        if len(value_rows) != 1:
            raise PerformanceComparisonError(
                "performance_material_metric_duplicate",
                f"{owner} has {len(value_rows)} values for metric "
                f"{metric_id!r}; replicate aggregation is not implicit.",
            )
        values[str(metric_id)] = float(value_rows.iloc[0]["value"])
    return values
