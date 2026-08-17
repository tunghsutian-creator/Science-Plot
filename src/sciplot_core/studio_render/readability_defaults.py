"""Apply physical readability defaults to rendering options."""

from __future__ import annotations

import math
from typing import Any
from sciplot_core.policy import (
    TENSILE_AXIS_PADDING_FRACTION,
    compact_linear_axis,
    is_removed_outside_legend_position,
    normalize_legend_position,
)

from sciplot_core.studio_render.models import (
    STACKED_TEMPLATE_IDS,
    CATEGORICAL_TEMPLATE_IDS,
    StudioSeries,
)

from sciplot_core.studio_render.domain_defaults import (
    _explicit_render_options,
)

from sciplot_core.studio_render.label_density import (
    _legend_is_dense,
    _wide_size_for_dense_legend,
)

from sciplot_core.studio_render.legend_placement import (
    _auto_inside_legend_placement,
)

from sciplot_core.studio_render.legend_clearance import (
    _reserve_vertical_legend_clearance,
)

from sciplot_core.studio_render.categorical_layout import (
    _categorical_bar_axis_defaults,
)

from sciplot_core.studio_render.template_resolution import (
    _looks_like_wavenumber_axis,
    _looks_like_torque_axis,
    _looks_like_tensile_axis,
)

from sciplot_core.studio_render.axis_scale import (
    _axis_scale,
)

from sciplot_core.studio_render.value_parsing import (
    _string_list,
)


def _apply_readability_render_defaults(
    render_options: dict[str, Any],
    *,
    request: dict[str, Any],
    axis_info: dict[str, Any],
    series: list[StudioSeries],
    template_id: str,
) -> dict[str, Any]:
    updated = dict(render_options)
    explicit_options = _explicit_render_options(request)
    label_mode = str(updated.get("series_label_mode") or "legend").strip().casefold()
    raw_legend_position = updated.get("legend_position")
    legend_position = normalize_legend_position(raw_legend_position)
    autofixes = _string_list(updated.get("_autofixes_applied"))
    temperature_axis_text = " ".join(
        str(value or "")
        for value in (
            request.get("rule_id"),
            updated.get("x_metric"),
            updated.get("x_label_override"),
            axis_info.get("x_label"),
        )
    ).casefold()
    if template_id not in CATEGORICAL_TEMPLATE_IDS and (
        str(request.get("rule_id") or "").strip() == "tensile_curve"
        or _looks_like_tensile_axis(axis_info)
    ):
        for axis, values in (
            ("x", (value for item in series for value in item.x_values)),
            ("y", (value for item in series for value in item.y_values)),
        ):
            if _axis_scale(updated, axis) != "linear":
                continue
            keys = {f"{axis}_min", f"{axis}_max", f"{axis}_ticks"}
            if keys & explicit_options.keys():
                continue
            compact_axis = compact_linear_axis(
                (value for value in values if math.isfinite(value)),
                padding_fraction=TENSILE_AXIS_PADDING_FRACTION,
            )
            if compact_axis is None:
                continue
            axis_min, axis_max, axis_ticks = compact_axis
            if len(axis_ticks) >= 2:
                tick_step = min(
                    right - left
                    for left, right in zip(axis_ticks, axis_ticks[1:], strict=False)
                    if right > left
                )
                edge_step = tick_step / 2.0
                axis_min = math.floor(axis_min / edge_step + 1e-12) * edge_step
                axis_max = math.ceil(axis_max / edge_step - 1e-12) * edge_step
                first_tick = math.ceil(axis_min / tick_step - 1e-12)
                last_tick = math.floor(axis_max / tick_step + 1e-12)
                axis_ticks = tuple(
                    round(index * tick_step, 12)
                    for index in range(first_tick, last_tick + 1)
                )
            updated.update(
                {
                    f"{axis}_min": float(axis_min),
                    f"{axis}_max": float(axis_max),
                    f"{axis}_ticks": list(axis_ticks),
                }
            )
        autofixes.append("tensile_two_sided_axis_whitespace")
    if (
        "temperature" in temperature_axis_text
        and _axis_scale(updated, "x") == "linear"
        and not {"x_min", "x_max", "x_ticks"} & explicit_options.keys()
    ):
        compact_axis = compact_linear_axis(
            value for item in series for value in item.x_values if math.isfinite(value)
        )
        if compact_axis is not None:
            x_min, x_max, x_ticks = compact_axis
            updated.update({"x_min": x_min, "x_max": x_max, "x_ticks": list(x_ticks)})
            autofixes.append("temperature_axis_compacted")
    if (
        str(request.get("rule_id") or "").strip() == "tga_curve"
        and _axis_scale(updated, "y") == "linear"
        and not {"y_min", "y_max", "y_ticks"} & explicit_options.keys()
    ):
        compact_axis = compact_linear_axis(
            value for item in series for value in item.y_values if math.isfinite(value)
        )
        if compact_axis is not None:
            y_min, y_max, y_ticks = compact_axis
            updated.update({"y_min": y_min, "y_max": y_max, "y_ticks": list(y_ticks)})
            autofixes.append("tga_mass_axis_compacted")
    if str(request.get("rule_id") or "").strip() == "gpc_sec_chromatogram":
        if (
            _axis_scale(updated, "x") == "linear"
            and not {"x_min", "x_max", "x_ticks"} & explicit_options.keys()
        ):
            compact_axis = compact_linear_axis(
                value
                for item in series
                for value in item.x_values
                if math.isfinite(value)
            )
            if compact_axis is not None:
                x_min, x_max, x_ticks = compact_axis
                updated.update(
                    {"x_min": x_min, "x_max": x_max, "x_ticks": list(x_ticks)}
                )
                autofixes.append("gpc_molar_mass_axis_compacted")
        if (
            _axis_scale(updated, "y") == "linear"
            and not {"y_min", "y_max", "y_ticks"} & explicit_options.keys()
        ):
            compact_axis = compact_linear_axis(
                value
                for item in series
                for value in item.y_values
                if math.isfinite(value)
            )
            if compact_axis is not None:
                y_min, y_max, y_ticks = compact_axis
                if all(
                    value >= 0.0
                    for item in series
                    for value in item.y_values
                    if math.isfinite(value)
                ):
                    y_min = 0.0
                    y_ticks = tuple(value for value in y_ticks if value >= 0.0)
                updated.update(
                    {"y_min": y_min, "y_max": y_max, "y_ticks": list(y_ticks)}
                )
                autofixes.append("gpc_distribution_axis_compacted")
    if is_removed_outside_legend_position(raw_legend_position):
        updated["legend_position"] = "auto"
        for key in (
            "legend_horz_position",
            "legend_vert_position",
            "legend_horz_manual",
            "legend_vert_manual",
        ):
            updated.pop(key, None)
        autofixes.append("legend_outside_removed")

    if template_id in STACKED_TEMPLATE_IDS:
        if (
            updated.get("stack_peak_envelope") is True
            and _axis_scale(updated, "y") == "linear"
            and not {"y_min", "y_max", "y_ticks"} & explicit_options.keys()
        ):
            compact_axis = compact_linear_axis(
                (
                    value
                    for item in series
                    for value in item.y_values
                    if math.isfinite(value)
                ),
                padding_fraction=0.08,
            )
            if compact_axis is not None:
                y_min, y_max, y_ticks = compact_axis
                updated.update(
                    {"y_min": y_min, "y_max": y_max, "y_ticks": list(y_ticks)}
                )
                autofixes.append("stack_full_peak_envelope_axis")
        if _looks_like_wavenumber_axis(axis_info):
            y_label = str(
                updated.get("y_label_override") or axis_info.get("y_label") or ""
            ).strip()
            if (
                len(series) == 1
                and str(updated.get("baseline") or "none").casefold() == "none"
            ):
                updated["show_y_ticks"] = True
                updated.setdefault("show_single_series_label", True)
                updated.setdefault("series_label_offset_fraction", 0.018)
                updated.setdefault("series_label_vertical_align", "bottom")
                if not {"y_min", "y_max", "y_ticks"} & explicit_options.keys():
                    compact_axis = compact_linear_axis(
                        value
                        for item in series
                        for value in item.y_values
                        if math.isfinite(value)
                    )
                    if compact_axis is not None:
                        y_min, y_max, y_ticks = compact_axis
                        updated.update(
                            {"y_min": y_min, "y_max": y_max, "y_ticks": list(y_ticks)}
                        )
                        autofixes.append("single_spectrum_y_axis_compacted")
                autofixes.append("single_spectrum_raw_y_scale")
            elif len(series) > 1:
                updated["show_y_ticks"] = False
                # Stacking is a presentation transform, not the measured
                # quantity. Keep the scientific axis name unchanged instead
                # of appending implementation language such as "(offset)".
                if "transmittance" in y_label.casefold():
                    updated["y_label_override"] = "Transmittance (%)"
                elif "absorbance" in y_label.casefold():
                    updated["y_label_override"] = "Absorbance"
        if label_mode in {"inline", "edge", "auto"} and (
            len(series) > 1 or updated.get("show_single_series_label") is True
        ):
            updated.setdefault("series_label_offset_fraction", 0.018)
            updated.setdefault("series_label_vertical_align", "bottom")
            autofixes.append("direct_label_offset")
        if autofixes:
            updated["_autofixes_applied"] = sorted(set(autofixes))
        return updated
    if template_id in CATEGORICAL_TEMPLATE_IDS:
        if (
            template_id == "bar"
            and _axis_scale(updated, "y") == "linear"
            and not {"y_min", "y_max", "y_ticks"} & explicit_options.keys()
        ):
            bar_axis = _categorical_bar_axis_defaults(series)
            if bar_axis is not None:
                updated.update(bar_axis)
                autofixes.append("categorical_bar_mean_and_error_headroom")
        if autofixes:
            updated["_autofixes_applied"] = sorted(set(autofixes))
        return updated

    if legend_position in {"", "auto"} and label_mode in {"", "auto", "legend"}:
        if _legend_is_dense(series) and "size" not in explicit_options:
            updated["size"] = _wide_size_for_dense_legend(series)
            autofixes.append("legend_auto_widened_inside")
        if (
            _looks_like_torque_axis(axis_info)
            or str(request.get("rule_id") or "").strip() == "torque_curve"
        ):
            updated["legend_position"] = "upper_right"
            updated["series_label_mode"] = "legend"
            autofixes.append("legend_auto_upper_right")
        else:
            placement = _auto_inside_legend_placement(
                series, updated, template_id=template_id
            )
            updated, placement = _reserve_vertical_legend_clearance(
                updated,
                request=request,
                series=series,
                template_id=template_id,
                placement=placement,
            )
            position = str(placement["position"])
            updated["legend_position"] = position
            updated["series_label_mode"] = "legend"
            updated["_legend_placement_diagnostics"] = placement
            if isinstance(placement.get("axis_reserve"), dict):
                autofixes.append(
                    f"legend_axis_reserve_{placement['axis_reserve']['side']}"
                )
            footprint = placement["footprint"]
            graph_width_mm = max(float(footprint["graph_width_mm"]), 1.0)
            graph_height_mm = max(float(footprint["graph_height_mm"]), 1.0)
            box_width_mm = min(float(footprint["box_width_mm"]), graph_width_mm)
            box_height_mm = min(float(footprint["box_height_mm"]), graph_height_mm)
            edge_padding_mm = max(float(placement.get("edge_padding_mm") or 0.0), 0.0)
            horizontal_pad = min(
                edge_padding_mm / graph_width_mm,
                max(0.0, 1.0 - box_width_mm / graph_width_mm),
            )
            vertical_pad = min(
                edge_padding_mm / graph_height_mm,
                max(0.0, 1.0 - box_height_mm / graph_height_mm),
            )
            updated["legend_horz_position"] = "manual"
            updated["legend_vert_position"] = "manual"
            updated["legend_horz_manual"] = (
                horizontal_pad
                if position.endswith("left")
                else max(0.0, 1.0 - horizontal_pad - box_width_mm / graph_width_mm)
            )
            updated["legend_vert_manual"] = (
                vertical_pad
                if position.startswith("lower")
                else max(0.0, 1.0 - vertical_pad - box_height_mm / graph_height_mm)
            )
            placement["manual_anchor_fraction"] = {
                "x": round(float(updated["legend_horz_manual"]), 6),
                "y": round(float(updated["legend_vert_manual"]), 6),
            }
            autofixes.append("legend_corner_edge_reclaimed")
            autofixes.append(f"legend_auto_{position}")

    if autofixes:
        updated["_autofixes_applied"] = sorted(set(autofixes))
    return updated
