"""Reserve vertical axis clearance for a legend without obscuring data."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    MAX_LEGEND_RESERVE_ITERATIONS,
    MAX_LINEAR_LEGEND_RESERVE_FRACTION,
    MAX_LOG_LEGEND_RESERVE_DECADES,
)

from sciplot_core.studio_render.models import (
    StudioSeries,
)

from sciplot_core.studio_render.domain_defaults import (
    _explicit_render_options,
)

from sciplot_core.studio_render.legend_placement import (
    _auto_inside_legend_placement,
)

from sciplot_core.studio_render.axis_scale import (
    _axis_scale,
)

from sciplot_core.studio_render.axis_contract import (
    _veusz_axis_contract,
)

from sciplot_core.studio_render.value_parsing import (
    _optional_float,
)


def _legend_placement_on_vertical_side(
    placement: dict[str, Any],
    *,
    lower: bool,
) -> dict[str, Any]:
    """Keep reserve iterations on the side whose axis bound is being expanded."""

    order = ("lower_right", "lower_left") if lower else ("upper_right", "upper_left")
    metrics = (
        placement.get("candidates")
        if isinstance(placement.get("candidates"), dict)
        else {}
    )
    required = _optional_float(placement.get("required_curve_clearance_mm")) or 0.0

    def score(name: str) -> tuple[Any, ...]:
        item = metrics.get(name) if isinstance(metrics.get(name), dict) else {}
        minimum = _optional_float(item.get("minimum_curve_clearance_mm"))
        overlap = int(item.get("overlap_samples") or 0)
        safe = minimum is None or minimum >= required
        return (
            int(overlap > 0),
            overlap,
            int(not safe),
            float(item.get("proximity_load") or 0.0),
            float(item.get("clearance_deficit_mm") or 0.0),
            -(minimum if minimum is not None else float("inf")),
            order.index(name),
        )

    selected = min(order, key=score)
    selected_metrics = (
        metrics.get(selected) if isinstance(metrics.get(selected), dict) else {}
    )
    minimum = _optional_float(selected_metrics.get("minimum_curve_clearance_mm"))
    revised = dict(placement)
    revised["position"] = selected
    revised["minimum_curve_clearance_mm"] = minimum
    revised["clearance_status"] = (
        "safe"
        if minimum is None or minimum >= required
        else "best_available_needs_reserve"
    )
    return revised


def _reserve_vertical_legend_clearance(
    render_options: dict[str, Any],
    *,
    request: dict[str, Any],
    series: list[StudioSeries],
    template_id: str,
    placement: dict[str, Any],
    source_bindings: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    position = str(placement.get("position") or "")
    if position not in {"lower_left", "lower_right", "upper_left", "upper_right"}:
        return render_options, placement
    required = _optional_float(placement.get("required_curve_clearance_mm")) or 0.0
    initial_minimum = _optional_float(placement.get("minimum_curve_clearance_mm"))
    if initial_minimum is None or initial_minimum >= required:
        return render_options, placement
    lower = position.startswith("lower")
    categorical = request.get("categorical_binding")
    from sciplot_core.studio_render.segmented_legend_clearance import ordinary_grouped_summary

    segmented = ordinary_grouped_summary(request, template_id=template_id)
    fixed_position = (str(categorical.get("legend_position"))
        if isinstance(categorical, dict) and categorical.get("legend_position") in {
            "lower_left", "lower_right", "upper_left", "upper_right"} else None)
    if segmented:
        fixed_position = "upper_left"  # Existing component rows have fixed geometry.
    bound_key = "y_min" if lower else "y_max"
    if bound_key in _explicit_render_options(request):
        return render_options, placement
    graph_height_mm = max(float(placement["footprint"]["graph_height_mm"]), 1.0)
    scale = _axis_scale(render_options, "y")
    updated = dict(render_options)
    revised = placement
    original_bound: float | None = None
    original_span: float | None = None
    total_reserve = 0.0
    for _attempt in range(MAX_LEGEND_RESERVE_ITERATIONS):
        minimum = _optional_float(revised.get("minimum_curve_clearance_mm"))
        if minimum is None or minimum >= required:
            break
        if isinstance(categorical, dict):
            from sciplot_core.studio_render.categorical_legend import categorical_legend_axis

            axis_contract = categorical_legend_axis(series, updated, request=request, template_id=template_id)
        else:
            axis_contract = _veusz_axis_contract(updated, template_id=template_id, series=series)
        y_min = axis_contract.y_min
        y_max = axis_contract.y_max
        if y_min is None or y_max is None or y_max <= y_min:
            break
        if original_bound is None:
            original_bound = y_min if lower else y_max
            original_span = y_max - y_min
        deficit_mm = required - minimum
        if segmented:
            deficit_mm += float(revised.get("overlap_depth_mm") or 0.0)
        previous_bound = updated.get(bound_key)
        if scale == "log":
            if y_min <= 0.0:
                break
            span = math.log10(y_max) - math.log10(y_min)
            increment = min(
                MAX_LOG_LEGEND_RESERVE_DECADES - total_reserve,
                max(0.005, deficit_mm / graph_height_mm * span * 1.5),
            )
            if increment <= 0.0:
                break
            if lower:
                updated["y_min"] = 10.0 ** (math.log10(y_min) - increment)
            else:
                updated["y_max"] = 10.0 ** (math.log10(y_max) + increment)
        else:
            span = y_max - y_min
            maximum_total = span * MAX_LINEAR_LEGEND_RESERVE_FRACTION
            increment = min(
                maximum_total - total_reserve,
                max(span * 0.005, deficit_mm / graph_height_mm * span * 1.5),
            )
            if increment <= 0.0:
                break
            if lower:
                updated["y_min"] = y_min - increment
            else:
                updated["y_max"] = y_max + increment
        if "categorical_binding" in request:
            from sciplot_core.studio_render.categorical_legend import categorical_legend_placement

            updated["_legend_placement_diagnostics"] = {"axis_reserve": {"side": "bottom" if lower else "top"}}
            if segmented:
                from sciplot_core.studio_render.segmented_legend_clearance import segmented_legend_placement

                measured = segmented_legend_placement(series, updated, request=request, template_id=template_id,
                    source_bindings=source_bindings)
            else:
                measured = categorical_legend_placement(series, updated, request=request,
                    template_id=template_id, position=fixed_position)
        else:
            measured = _auto_inside_legend_placement(series, updated, template_id=template_id)
        candidate = measured if fixed_position else _legend_placement_on_vertical_side(measured, lower=lower)
        actual_total = None
        if isinstance(categorical, dict):
            actual_bound = float(candidate["measurement_axes"]["y"][0 if lower else 1])
            actual_total = (abs(math.log10(actual_bound / original_bound)) if scale == "log"
                            else abs(actual_bound - original_bound))
            actual_cap = (MAX_LOG_LEGEND_RESERVE_DECADES if scale == "log"
                          else float(original_span or 0) * MAX_LINEAR_LEGEND_RESERVE_FRACTION)
            if actual_total > actual_cap + 1e-12:
                if previous_bound is None:
                    updated.pop(bound_key, None)
                else:
                    updated[bound_key] = previous_bound
                break
            updated[bound_key] = actual_bound
        candidate_minimum = _optional_float(candidate.get("minimum_curve_clearance_mm"))
        current_metrics = revised.get("candidates", {}).get(
            str(revised.get("position") or ""), {}
        )
        candidate_metrics = candidate.get("candidates", {}).get(
            str(candidate.get("position") or ""), {}
        )
        current_overlap = int(current_metrics.get("overlap_samples") or 0)
        candidate_overlap = int(candidate_metrics.get("overlap_samples") or 0)
        current_load = float(current_metrics.get("proximity_load") or 0.0)
        candidate_load = float(candidate_metrics.get("proximity_load") or 0.0)
        candidate_improved = candidate_minimum is not None and (
            candidate_minimum > minimum + 1e-6
            or candidate_overlap < current_overlap
            or (
                candidate_overlap == current_overlap
                and candidate_load < current_load - 1e-6
            )
        )
        # Zero distance saturates while a curve remains inside the key. Keep
        # bounded reserve probes moving until actual clearance can improve.
        saturated_overlap = current_overlap > 0 and candidate_overlap > 0
        if not candidate_improved and not saturated_overlap:
            if previous_bound is None:
                updated.pop(bound_key, None)
            else:
                updated[bound_key] = previous_bound
            break
        total_reserve = actual_total if actual_total is not None else total_reserve + increment
        revised = candidate
    revised_minimum = _optional_float(revised.get("minimum_curve_clearance_mm"))
    if (
        original_bound is None
        or revised_minimum is None
        or revised_minimum <= initial_minimum + 1e-6
    ):
        return render_options, placement
    revised["axis_reserve"] = {
        "side": "bottom" if lower else "top",
        "original_bound": original_bound,
        "revised_bound": updated[bound_key],
        "scale": scale,
        **(
            {"decades": round(total_reserve, 6)}
            if scale == "log"
            else {"axis_units": round(total_reserve, 6)}
        ),
    }
    return updated, revised
