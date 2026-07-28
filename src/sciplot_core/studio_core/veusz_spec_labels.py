"""Build direct-label and legend portions of a Veusz plot specification."""

from __future__ import annotations

from typing import Any

from sciplot_core.foundation.json_values import json_safe
from sciplot_core.studio_render.axes_spec import (
    _categorical_axis_label_contracts,
    _direct_label_contracts,
)
from sciplot_core.studio_render.label_density import _label_load
from sciplot_core.studio_render.legend_visibility import _legend_columns
from sciplot_core.studio_render.models import (
    StudioSeries,
    _VeuszAxisContract,
    _VeuszStyleContract,
)
from sciplot_core.studio_render.value_parsing import _optional_float

from sciplot_core.studio_core.context import _normalize_optional_string
from sciplot_core.studio_core.legend_specs import (
    _categorical_component_legend_spec,
    _curve_factor_legend_spec,
)


def build_veusz_direct_labels(
    *,
    series: list[StudioSeries],
    render_options: dict[str, Any],
    axis_contract: _VeuszAxisContract,
    style: _VeuszStyleContract,
    show_direct_labels: bool,
    categorical_contract: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Combine curve labels and categorical axis labels in paint order."""

    label_specs = _direct_label_contracts(
        series,
        render_options=render_options,
        axis_contract=axis_contract,
        style=style,
        show_direct_labels=show_direct_labels,
    )
    label_specs.extend(
        _categorical_axis_label_contracts(
            categorical_contract,
            axis_contract=axis_contract,
            style=style,
        )
    )
    return label_specs


def build_veusz_legend_spec(
    *,
    series: list[StudioSeries],
    template_id: str,
    render_options: dict[str, Any],
    categorical_contract: dict[str, Any] | None,
    style: _VeuszStyleContract,
    legend_mode: str,
    show_key: bool,
    width_mm: float,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Build one native, segmented, or factorized legend contract."""

    component_labels = _component_legend_labels(categorical_contract)
    factor_legend = _curve_factor_legend_spec(
        series,
        template_id=template_id,
        style=style,
        mode=legend_mode,
    )
    factor_labels = _factor_legend_labels(factor_legend)
    label_load = _resolved_label_load(
        series,
        component_labels=component_labels,
        factor_labels=factor_labels,
    )
    legend_spec: dict[str, Any] = {
        "show": show_key,
        "columns": _legend_columns(
            series_count=label_load["series_count"],
            mode=legend_mode,
            max_label_length=label_load["max_label_length"],
            figure_width_mm=width_mm,
        ),
        "mode": legend_mode,
        "horz_position": _normalize_optional_string(
            render_options.get("legend_horz_position")
        ),
        "vert_position": _normalize_optional_string(
            render_options.get("legend_vert_position")
        ),
        "horz_manual": _optional_float(render_options.get("legend_horz_manual")),
        "vert_manual": _optional_float(render_options.get("legend_vert_manual")),
    }
    component_legend = _categorical_component_legend_spec(
        categorical_contract,
        style=style,
    )
    if component_legend is not None:
        legend_spec.update(component_legend)
    if factor_legend is not None:
        legend_spec.update(factor_legend)
    placement_diagnostics = render_options.get("_legend_placement_diagnostics")
    if isinstance(placement_diagnostics, dict):
        legend_spec["placement_diagnostics"] = json_safe(placement_diagnostics)
    if show_key:
        legend_spec["label_load"] = label_load
        label_mapping = render_options.get("_legend_label_mapping")
        if isinstance(label_mapping, list) and label_mapping:
            legend_spec["label_mapping"] = json_safe(label_mapping)
    return legend_spec, factor_legend


def _component_legend_labels(
    categorical_contract: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(categorical_contract, dict):
        return []
    if categorical_contract.get("presentation_kind") == "stacked_components":
        values = categorical_contract.get("component_labels", [])
    elif categorical_contract.get("presentation_kind") == "grouped_bar_error":
        values = categorical_contract.get("condition_labels", [])
    else:
        return []
    return [str(value) for value in values]


def _factor_legend_labels(
    factor_legend: dict[str, Any] | None,
) -> list[str]:
    if not isinstance(factor_legend, dict):
        return []
    return [
        str(entry.get("label") or "")
        for group in factor_legend.get("groups", [])
        if isinstance(group, dict)
        for entry in group.get("entries", [])
        if isinstance(entry, dict)
    ]


def _resolved_label_load(
    series: list[StudioSeries],
    *,
    component_labels: list[str],
    factor_labels: list[str],
) -> dict[str, int]:
    labels = component_labels or factor_labels
    if not labels:
        return _label_load(series)
    return {
        "series_count": len(labels),
        "max_label_length": max((len(label) for label in labels), default=0),
        "total_label_length": sum(len(label) for label in labels),
        "duplicate_count": len(labels) - len(set(labels)),
    }
