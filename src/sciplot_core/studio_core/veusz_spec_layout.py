"""Report layout and semantic risks in a Veusz plot specification."""

from __future__ import annotations

from typing import Any

from sciplot_core.foundation.json_values import json_safe
from sciplot_core.studio_render.label_density import _legend_is_dense
from sciplot_core.studio_render.models import (
    STACKED_TEMPLATE_IDS,
    StudioSeries,
    _VeuszAxisContract,
)
from sciplot_core.studio_render.value_parsing import _optional_float

from sciplot_core.studio_core.semantic_validation import (
    _semantic_series_contract_issues,
    _spectral_x_coverage_issue,
)


def build_veusz_layout_issues(
    *,
    request: dict[str, Any],
    render_options: dict[str, Any],
    template_id: str,
    series: list[StudioSeries],
    axis_info: dict[str, Any],
    axis_contract: _VeuszAxisContract,
    categorical_contract: dict[str, Any] | None,
    factor_legend: dict[str, Any] | None,
    show_key: bool,
) -> list[dict[str, Any]]:
    """Collect clipping, semantic, density, and legend-clearance issues."""

    issues = _visual_extent_issues(render_options)
    spectral_issue = _spectral_x_coverage_issue(
        series,
        template_id=template_id,
        axis_info=axis_info,
        axis_contract=axis_contract,
    )
    if spectral_issue is not None:
        issues.append(spectral_issue)
    issues.extend(_semantic_series_contract_issues(series, request=request))

    placement = render_options.get("_legend_placement_diagnostics")
    placement_is_safe = (
        isinstance(placement, dict) and placement.get("clearance_status") == "safe"
    )
    component_legend = isinstance(
        categorical_contract, dict
    ) and categorical_contract.get("presentation_kind") in {
        "stacked_components",
        "grouped_bar_error",
    }
    if (
        show_key
        and template_id not in STACKED_TEMPLATE_IDS
        and not component_legend
        and factor_legend is None
        and _legend_is_dense(series)
        and not placement_is_safe
    ):
        issues.append(
            {
                "id": "legend_crowded_inside",
                "severity": "warning",
                "message": "A crowded curve legend remains inside the plot area.",
            }
        )
    if (
        show_key
        and isinstance(placement, dict)
        and placement.get("clearance_status") != "safe"
    ):
        measured_clearance = _optional_float(
            placement.get("minimum_curve_clearance_mm")
        )
        overlap_detected = measured_clearance is not None and measured_clearance <= 0.0
        issues.append(
            {
                "id": "legend_curve_clearance_below_target",
                "severity": "critical" if overlap_detected else "warning",
                "message": (
                    "The inside legend overlaps plotted data at final size."
                    if overlap_detected
                    else "No inside legend corner reached the requested curve clearance at final size."
                ),
                "required_clearance_mm": placement.get("required_curve_clearance_mm"),
                "measured_clearance_mm": placement.get("minimum_curve_clearance_mm"),
            }
        )
    return issues


def _visual_extent_issues(
    render_options: dict[str, Any],
) -> list[dict[str, Any]]:
    diagnostics = render_options.get("_visual_extent_axis_diagnostics")
    if not isinstance(diagnostics, dict):
        return []
    issues: list[dict[str, Any]] = []
    for violation in diagnostics.get("violations", []):
        if not isinstance(violation, dict):
            continue
        issues.append(
            {
                "id": "visual_extent_outside_explicit_axis",
                "severity": "critical",
                "message": (
                    "An explicit axis bound clips a marker, stroke, or "
                    "categorical error-bar extent at final physical size."
                ),
                **json_safe(violation),
            }
        )
    return issues
