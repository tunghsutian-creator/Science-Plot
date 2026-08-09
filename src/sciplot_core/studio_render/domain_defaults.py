"""Apply experiment- and domain-specific defaults to render options."""

from __future__ import annotations

import re
from typing import Any
from sciplot_core.materials_rules.unit_data import (
    NORMALIZED_STRESS_RATIO_DISPLAY_LABEL,
)
from sciplot_core.policy import (
    CATEGORICAL_BOX_FILL_FRACTION,
    CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS,
    DEFAULT_CATEGORICAL_SUMMARY,
    DEFAULT_FIGURE_SIZE,
    DEFAULT_LOG_TICK_FORMAT,
    DEFAULT_RAW_POINT_JITTER_FRACTION,
    POINT_LINE_RENDER_OPTIONS,
    RHEOLOGY_FREQUENCY_X_RENDER_LABEL,
    TENSILE_X_AXIS_LABEL,
    TENSILE_Y_AXIS_LABEL,
    categorical_box_native_fill_scale,
    categorical_box_width_mm,
    categorical_slot_width_mm,
    mechanical_axis_labels,
    normalize_categorical_summary,
    normalize_raw_point_jitter_fraction,
    rheology_metric_axis_label,
)
from sciplot_core.studio_render.models import (
    STACKED_TEMPLATE_IDS,
    CATEGORICAL_TEMPLATE_IDS,
)
from sciplot_core.studio_render.metric_columns import (
    _preferred_metric_pair,
)
from sciplot_core.studio_render.template_resolution import (
    _request_template,
    _looks_like_wavenumber_axis,
    _looks_like_torque_axis,
    _looks_like_frequency_axis,
    _looks_like_tensile_axis,
)
from sciplot_core.studio_render.value_parsing import (
    _size_mm,
)


def _apply_domain_render_defaults(
    render_options: dict[str, Any],
    *,
    request: dict[str, Any],
    axis_info: dict[str, Any],
) -> dict[str, Any]:
    updated = dict(render_options)
    explicit_options = (
        request.get("render_options")
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    explicit_contract = _explicit_render_options(request)
    template_id = _request_template(request)
    category_positions = axis_info.get("category_positions")
    if template_id == "point_line":
        for key, value in POINT_LINE_RENDER_OPTIONS.items():
            if key not in explicit_options:
                updated[key] = list(value) if isinstance(value, list) else value
        if axis_info.get("presentation_kind") == "impact_point_line_raw_overlay":
            category_positions = [
                float(value) for value in axis_info.get("category_positions") or []
            ]
            if category_positions:
                updated.setdefault("x_min", min(category_positions) - 0.5)
                updated.setdefault("x_max", max(category_positions) + 0.5)
                updated.setdefault("x_ticks", category_positions)
            overlay_defaults = {
                "x_label_override": "Sample",
                "y_label_override": "Impact strength (kJ m⁻²)",
                "size": "60x55",
                "legend_position": "upper_left",
                "series_label_mode": "legend",
                "summary_statistic": "arithmetic_mean",
            }
            for key, value in overlay_defaults.items():
                if key not in explicit_contract:
                    updated[key] = value
    if (
        template_id in CATEGORICAL_TEMPLATE_IDS
        and isinstance(category_positions, list)
        and category_positions
    ):
        component_stack = axis_info.get("presentation_kind") == "categorical_components"
        grouped_bar = (
            axis_info.get("presentation_kind") == "categorical_grouped_replicates"
        )
        for key, value in CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS.items():
            if key not in explicit_options:
                updated[key] = list(value) if isinstance(value, list) else value
        if not component_stack:
            updated["summary_statistic"] = normalize_categorical_summary(
                updated.get("summary_statistic") or DEFAULT_CATEGORICAL_SUMMARY
            )
        updated.setdefault("x_min", float(min(category_positions)) - 0.5)
        updated.setdefault("x_max", float(max(category_positions)) + 0.5)
        updated.setdefault("x_ticks", list(category_positions))
        updated.setdefault("x_label_override", "Sample")
        if component_stack:
            updated["_categorical_component_legend"] = True
            if "legend_position" not in explicit_options:
                updated["legend_position"] = "upper_right"
        elif grouped_bar:
            updated["_categorical_grouped_legend"] = True
            if "legend_position" not in explicit_options:
                updated["legend_position"] = "upper_right"
        else:
            updated.setdefault("legend_position", "none")
        updated.setdefault("series_label_mode", "none")
        if "size" not in explicit_contract:
            # Choose the narrowest house frame that can carry the observed
            # category count. Four ordinary sample labels fit the canonical
            # 60 mm frame; broader frames are reserved for genuinely denser
            # categorical axes.
            if len(category_positions) <= 4:
                updated["size"] = "60x55"
            elif len(category_positions) <= 7:
                updated["size"] = "120x55"
            else:
                updated["size"] = "180x55"
        figure_width_mm, _figure_height_mm = _size_mm(
            str(updated.get("size") or DEFAULT_FIGURE_SIZE)
        )
        updated["_categorical_box_fill_fraction"] = CATEGORICAL_BOX_FILL_FRACTION
        updated["_categorical_box_native_fill_scale"] = (
            categorical_box_native_fill_scale(category_count=len(category_positions))
        )
        updated["_categorical_slot_width_mm"] = categorical_slot_width_mm(
            category_count=len(category_positions),
            figure_width_mm=float(figure_width_mm),
        )
        updated["_categorical_box_width_mm"] = categorical_box_width_mm(
            category_count=len(category_positions),
            figure_width_mm=float(figure_width_mm),
        )
        if "raw_point_jitter_fraction" in explicit_contract:
            updated["raw_point_jitter_fraction"] = normalize_raw_point_jitter_fraction(
                updated.get(
                    "raw_point_jitter_fraction",
                    DEFAULT_RAW_POINT_JITTER_FRACTION,
                )
            )
            updated["_categorical_raw_point_layout"] = "fixed"
        else:
            updated["_categorical_raw_point_layout"] = "adaptive"
        if template_id == "bar":
            updated.setdefault("y_min", 0.0)
        if str(request.get("rule_id") or "").strip() == "impact_metric":
            category_labels = [
                str(value) for value in axis_info.get("category_labels") or []
            ]
            thickness_labels = bool(category_labels) and all(
                re.fullmatch(
                    r".+?\s+\(\d+(?:\.\d+)?\s*mm\)", label, flags=re.IGNORECASE
                )
                or re.fullmatch(r".+?/\d+(?:\.\d+)?", label)
                for label in category_labels
            )
            if thickness_labels:
                updated["x_label_override"] = "Sample / thickness (mm)"
            if "y_label_override" not in explicit_options:
                updated["y_label_override"] = "Impact strength (kJ m⁻²)"
    if template_id in STACKED_TEMPLATE_IDS and _looks_like_wavenumber_axis(axis_info):
        detected_y_label = str(axis_info.get("y_label") or "").strip()
        series_count = int(axis_info.get("series_count") or 0)
        label_mode = str(updated.get("series_label_mode") or "").strip().casefold()
        legend_position = str(updated.get("legend_position") or "").strip().casefold()
        domain_defaults: dict[str, Any] = {
            "reverse_x": True,
            "x_min": 400.0,
            "x_max": 4000.0,
            "x_ticks": [400.0, 1000.0, 2000.0, 3000.0, 4000.0],
            "baseline": "none",
            "series_label_side": "left",
            "show_single_series_label": series_count == 1,
            "show_y_ticks": False,
            "x_label_override": "Wavenumber (cm⁻¹)",
            "size": "120x55" if series_count == 1 else "120x110",
        }
        for key, value in domain_defaults.items():
            if (
                key not in explicit_options
                or key == "size"
                and key not in explicit_contract
            ):
                updated[key] = value
        if series_count == 1:
            if "series_label_offset_fraction" not in explicit_contract:
                updated["series_label_offset_fraction"] = 0.0
            if "series_label_vertical_align" not in explicit_contract:
                updated["series_label_vertical_align"] = "top"
        if detected_y_label and "y_label_override" not in explicit_contract:
            updated["y_label_override"] = detected_y_label
        if "show_y_ticks" not in explicit_contract:
            updated["show_y_ticks"] = series_count <= 1
        if legend_position in {"", "auto", "none", "hide", "hidden", "off"}:
            updated["legend_position"] = "none"
        if label_mode in {"", "auto", "legend", "inline", "edge"}:
            updated["series_label_mode"] = "inline"
    if (
        _looks_like_torque_axis(axis_info)
        or str(request.get("rule_id") or "").strip() == "torque_curve"
    ):
        x_label = str(updated.get("x_label_override") or "").strip().casefold()
        if x_label in {"", "time"}:
            updated["x_label_override"] = "Time (s)"
        y_label = str(updated.get("y_label_override") or "").strip().casefold()
        if y_label in {"", "screw torque", "torque"}:
            updated["y_label_override"] = "Screw torque (N·m)"
        updated.setdefault("stack_spacing_scale", 0.05)
        if str(updated.get("series_label_mode") or "").casefold() in {
            "",
            "auto",
            "inline",
        }:
            updated["series_label_mode"] = "legend"
    if _looks_like_frequency_axis(axis_info):
        updated.setdefault("xscale", "log")
        metric_label = next(
            (
                label
                for candidate in (
                    updated.get("y_metric"),
                    request.get("y_metric"),
                    updated.get("y_label_override"),
                    axis_info.get("y_label"),
                )
                if (label := rheology_metric_axis_label(candidate)) is not None
            ),
            None,
        )
        rule_id = str(request.get("rule_id") or "").strip()
        rheology_frequency = (
            rule_id == "rheology_frequency_sweep" or metric_label is not None
        )
        x_axis_text = str(axis_info.get("x_label") or "").casefold()
        if rheology_frequency or "angular" in x_axis_text or "rad" in x_axis_text:
            updated.setdefault("x_label_override", RHEOLOGY_FREQUENCY_X_RENDER_LABEL)
        if rheology_frequency:
            updated.setdefault("yscale", "log")
            updated.setdefault("x_tick_format", DEFAULT_LOG_TICK_FORMAT)
            updated.setdefault("y_tick_format", DEFAULT_LOG_TICK_FORMAT)
            if "y_label_override" not in explicit_options and metric_label is not None:
                updated["y_label_override"] = metric_label
    rule_id = str(request.get("rule_id") or "").strip()
    if rule_id in {"rheology_strain_sweep", "rheology_stress_sweep"}:
        explicit_contract = _explicit_render_options(request)
        metric_pair = _preferred_metric_pair(request)
        y_metric = metric_pair[1] if metric_pair is not None else "storage_modulus"
        metric_label = rheology_metric_axis_label(y_metric)
        if metric_label is not None and "y_label_override" not in explicit_contract:
            updated["y_label_override"] = metric_label
        if "yscale" not in explicit_contract:
            updated["yscale"] = "linear" if y_metric == "loss_factor" else "log"
        if y_metric == "loss_factor":
            if "y_tick_format" not in explicit_contract:
                updated.pop("y_tick_format", None)
        else:
            updated.setdefault("y_tick_format", DEFAULT_LOG_TICK_FORMAT)
    mechanical_rule_id = rule_id
    if mechanical_axis_labels(mechanical_rule_id) is None:
        mechanical_evidence = " ".join(
            str(value or "").casefold()
            for value in (
                request.get("y_metric"),
                updated.get("y_label_override"),
                axis_info.get("y_label"),
            )
        )
        if "flexural" in mechanical_evidence or "bending" in mechanical_evidence:
            mechanical_rule_id = "flexural_curve"
        elif (
            "compressive" in mechanical_evidence or "compression" in mechanical_evidence
        ):
            mechanical_rule_id = "compression_curve"
        elif "tensile" in mechanical_evidence:
            mechanical_rule_id = "tensile_curve"
    mechanical_labels = mechanical_axis_labels(mechanical_rule_id)
    if template_id not in CATEGORICAL_TEMPLATE_IDS and (
        mechanical_labels is not None or _looks_like_tensile_axis(axis_info)
    ):
        x_label, y_label = mechanical_labels or (
            TENSILE_X_AXIS_LABEL,
            TENSILE_Y_AXIS_LABEL,
        )
        updated["x_label_override"] = x_label
        updated["y_label_override"] = y_label
        updated["axis_mode"] = "auto"
    if str(request.get("rule_id") or "").strip() == "rheology_stress_relaxation":
        updated.setdefault("x_label_override", "Time (s)")
        updated.setdefault(
            "y_label_override",
            NORMALIZED_STRESS_RATIO_DISPLAY_LABEL,
        )
    if str(request.get("rule_id") or "").strip() == "gpc_sec_chromatogram":
        detected_y_label = str(axis_info.get("y_label") or "").strip()
        requested_y_label = (
            str(updated.get("y_label_override") or "").strip().casefold()
        )
        if detected_y_label and requested_y_label in {
            "",
            "detector response",
            "detector response (a.u.)",
        }:
            updated["y_label_override"] = detected_y_label
    return updated


def _explicit_render_options(request: dict[str, Any]) -> dict[str, Any]:
    options = (
        request.get("render_options")
        if isinstance(request.get("render_options"), dict)
        else {}
    )
    explicit_keys = request.get("explicit_render_option_keys")
    if not isinstance(explicit_keys, list | tuple | set):
        return options
    return {str(key): options[str(key)] for key in explicit_keys if str(key) in options}
