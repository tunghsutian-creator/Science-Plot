"""Apply and validate linear or logarithmic domain contracts for Studio series."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    DEFAULT_PALETTE_PRESET,
)

from sciplot_core.studio_render.models import (
    StudioPreparationBlocked,
    StudioSeries,
)

from sciplot_core.studio_render.series_options import (
    _effective_render_options,
)

from sciplot_core.studio_render.domain_defaults import (
    _apply_domain_render_defaults,
    _explicit_render_options,
)

from sciplot_core.studio_render.axis_scale import (
    _axis_scale,
)


def _apply_series_domain_contract_defaults(
    render_options: dict[str, Any],
    *,
    request: dict[str, Any],
    series: list[StudioSeries],
) -> dict[str, Any]:
    """Apply rule-specific bounds only when the current data justify them."""

    updated = dict(render_options)
    rule_id = str(request.get("rule_id") or "").strip()
    explicit = _explicit_render_options(request)
    x_values = [
        value for item in series for value in item.x_values if math.isfinite(value)
    ]
    y_values = [
        value for item in series for value in item.y_values if math.isfinite(value)
    ]
    if rule_id == "xrd_pattern":
        if x_values and min(x_values) >= 0.0 and "x_min" not in explicit:
            updated["x_min"] = 0.0
        if y_values and min(y_values) >= 0.0 and "y_min" not in explicit:
            updated["y_min"] = 0.0
    elif rule_id == "rheology_stress_relaxation" and y_values:
        lower = float(min(y_values))
        upper = float(max(y_values))
        configured_lower = updated.get("y_min")
        configured_upper = updated.get("y_max")
        adjusted: list[str] = []
        if (
            isinstance(configured_lower, int | float)
            and lower < float(configured_lower)
            and "y_min" not in explicit
        ):
            updated.pop("y_min", None)
            adjusted.append("y_min_auto_for_observed_negative_response")
        if (
            isinstance(configured_upper, int | float)
            and upper > float(configured_upper)
            and "y_max" not in explicit
        ):
            updated.pop("y_max", None)
            adjusted.append("y_max_auto_for_observed_response")
        if adjusted and "y_ticks" not in explicit:
            updated.pop("y_ticks", None)
            adjusted.append("y_ticks_auto_for_observed_response")
        if adjusted:
            updated["_domain_contract_adjustments"] = sorted(set(adjusted))
    return updated


def _resolved_domain_render_options(
    request: dict[str, Any],
    *,
    axis_info: dict[str, Any],
    series: list[StudioSeries],
) -> dict[str, Any]:
    render_options = _effective_render_options(request)
    if "palette_preset" not in _explicit_render_options(request):
        # Persisted requests may contain the default that was current when the
        # project was created.  Non-explicit defaults follow the live shared
        # policy; a user-selected palette remains authoritative.
        render_options["palette_preset"] = DEFAULT_PALETTE_PRESET
    render_options = _apply_series_domain_contract_defaults(
        render_options,
        request=request,
        series=series,
    )
    return _apply_domain_render_defaults(
        render_options,
        request=request,
        axis_info=axis_info,
    )


def _validate_log_domain_series(
    series: list[StudioSeries],
    *,
    render_options: dict[str, Any],
) -> None:
    """Fail closed instead of silently dropping nonpositive log-axis data."""

    invalid: dict[str, list[dict[str, Any]]] = {}
    for axis in ("x", "y"):
        if _axis_scale(render_options, axis) != "log":
            continue
        axis_issues: list[dict[str, Any]] = []
        for item in series:
            values = item.x_values if axis == "x" else item.y_values
            nonfinite_count = sum(1 for value in values if not math.isfinite(value))
            nonpositive_count = sum(
                1 for value in values if math.isfinite(value) and value <= 0.0
            )
            if nonfinite_count or nonpositive_count:
                axis_issues.append(
                    {
                        "series": item.label,
                        "nonfinite_count": nonfinite_count,
                        "nonpositive_count": nonpositive_count,
                    }
                )
        if axis_issues:
            invalid[axis] = axis_issues
    if invalid:
        detail = "; ".join(
            f"{axis}: "
            + ", ".join(
                f"{item['series']} "
                f"(nonfinite={item['nonfinite_count']}, "
                f"nonpositive={item['nonpositive_count']})"
                for item in issues
            )
            for axis, issues in invalid.items()
        )
        raise StudioPreparationBlocked(
            "log_axis_nonpositive_data",
            "Logarithmic axes require strictly positive finite values; "
            f"semantic preparation must mask or resolve nonpositive points ({detail}).",
        )
