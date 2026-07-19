from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from sciplot_core.contract import PlotContract, load_plot_contract
from sciplot_core.figure_layouts import get_figure_layout
from sciplot_core.figure_profiles import get_figure_profile, list_figure_profiles
from sciplot_core.materials_rules import iter_public_rules
from sciplot_core.policy import (
    DEFAULT_RENDER_OPTIONS,
    DEFAULT_SCALAR_FIELD_COLORMAP_ID,
    DEFAULT_SCALAR_FIELD_COLORS,
    FIGURE_SIZE_PRESETS,
    UNIFIED_AXIS_LINEWIDTH_PT,
    UNIFIED_BOTTOM_MARGIN_MM,
    UNIFIED_FONT_FAMILY,
    UNIFIED_FONT_SIZE_PT,
    UNIFIED_FOREGROUND_COLOR,
    UNIFIED_HARD_OPTION_KEYS,
    UNIFIED_LEGEND_FONT_SIZE_PT,
    UNIFIED_LEFT_MARGIN_MM,
    UNIFIED_LINE_WIDTH_PT,
    UNIFIED_MARKER_LINE_WIDTH_PT,
    UNIFIED_MARKER_SIZE_PT,
    UNIFIED_MINOR_TICK_LENGTH_PT,
    UNIFIED_MINOR_TICK_WIDTH_PT,
    UNIFIED_PANEL_LABEL_SIZE_PT,
    UNIFIED_RIGHT_MARGIN_MM,
    UNIFIED_TICK_LENGTH_PT,
    UNIFIED_TICK_WIDTH_PT,
    UNIFIED_TOP_MARGIN_MM,
)
from sciplot_recipes.contracts import iter_recipe_specs
# These are the templates implemented by the production Veusz document builder.
# The vendored contract also describes reference-only templates; advertising
# those through the workbench would make a request validate before failing later.
VEUSZ_IMPLEMENTED_TEMPLATE_IDS = frozenset(
    {
        "curve",
        "point_line",
        "stacked_curve",
        "box",
        "box_strip",
        "heatmap",
    }
)

VEUSZ_REQUIRED_EDITABLE_OPTIONS = {
    "heatmap": frozenset(
        {
            "size",
            "x_min",
            "x_max",
            "y_min",
            "y_max",
            "x_label_override",
            "y_label_override",
            "show_colorbar",
            "data_variables",
            "zscale",
            "z_min",
            "z_max",
            "z_ticks",
            "z_tick_format",
            "z_label_override",
            "colormap_name",
            "colormap_colors",
            "color_invert",
            "field_mapping",
            "field_draw_mode",
            "field_transparency",
            "contour_levels",
            "contour_color",
            "contour_line_style",
            "contour_labels",
            "highlight_contour_levels",
            "highlight_contour_color",
            "highlight_contour_line_style",
            "colorbar_width_mm",
            "colorbar_height_mm",
            "colorbar_direction",
            "colorbar_manual_position",
            "colorbar_horz_manual",
            "colorbar_vert_manual",
            "colorbar_foreground_color",
            "colorbar_background_color",
            "colorbar_background_transparency",
            "colorbar_background_x_fraction",
            "colorbar_background_y_fraction",
            "colorbar_background_width_fraction",
            "colorbar_background_height_fraction",
            "reference_guides",
            "style_preset",
            "palette_preset",
        }
    ),
}

# Color carries scientific meaning in scalar-field figures, so heatmap colors
# are intentionally template-owned.  The global contract still owns every
# typographic, stroke, tick, marker, and physical-frame measurement.
VEUSZ_TEMPLATE_COLOR_OPTIONS = {
    "heatmap": frozenset(
        {
            "colormap_name",
            "colormap_colors",
            "color_invert",
            "contour_color",
            "highlight_contour_color",
            "colorbar_foreground_color",
            "colorbar_background_color",
        }
    ),
}


def _expected_render_hard_values() -> dict[str, float]:
    return {
        "font_size_pt": UNIFIED_FONT_SIZE_PT,
        "legend_font_size_pt": UNIFIED_LEGEND_FONT_SIZE_PT,
        "axis_linewidth_pt": UNIFIED_AXIS_LINEWIDTH_PT,
        "tick_width_pt": UNIFIED_TICK_WIDTH_PT,
        "tick_length_pt": UNIFIED_TICK_LENGTH_PT,
        "minor_tick_width_pt": UNIFIED_MINOR_TICK_WIDTH_PT,
        "minor_tick_length_pt": UNIFIED_MINOR_TICK_LENGTH_PT,
        "line_width_pt": UNIFIED_LINE_WIDTH_PT,
        "marker_size": UNIFIED_MARKER_SIZE_PT,
        "marker_line_width_pt": UNIFIED_MARKER_LINE_WIDTH_PT,
    }


def _expected_optional_hard_values() -> dict[str, float]:
    return {
        **_expected_render_hard_values(),
        "marker_size_pt": UNIFIED_MARKER_SIZE_PT,
        "contour_line_width_pt": UNIFIED_LINE_WIDTH_PT,
        "highlight_contour_line_width_pt": UNIFIED_LINE_WIDTH_PT,
    }


def _expected_vendor_style_values() -> dict[str, object]:
    return {
        "typography.font_family": (UNIFIED_FONT_FAMILY,),
        "typography.font_size_pt": UNIFIED_FONT_SIZE_PT,
        "typography.legend_font_size_pt": UNIFIED_LEGEND_FONT_SIZE_PT,
        "typography.panel_label_size_pt": UNIFIED_PANEL_LABEL_SIZE_PT,
        "stroke.axis_linewidth_pt": UNIFIED_AXIS_LINEWIDTH_PT,
        "stroke.tick_width_pt": UNIFIED_TICK_WIDTH_PT,
        "stroke.tick_length_pt": UNIFIED_TICK_LENGTH_PT,
        "stroke.minor_tick_width_pt": UNIFIED_MINOR_TICK_WIDTH_PT,
        "stroke.minor_tick_length_pt": UNIFIED_MINOR_TICK_LENGTH_PT,
        "stroke.line_width_pt": UNIFIED_LINE_WIDTH_PT,
        "stroke.marker_size_pt": UNIFIED_MARKER_SIZE_PT,
    }


def _expected_global_frame() -> dict[str, float]:
    return {
        "left_margin_mm": UNIFIED_LEFT_MARGIN_MM,
        "right_margin_mm": UNIFIED_RIGHT_MARGIN_MM,
        "bottom_margin_mm": UNIFIED_BOTTOM_MARGIN_MM,
        "top_margin_mm": UNIFIED_TOP_MARGIN_MM,
    }


def _vendor_style_values(style: object) -> dict[str, object]:
    typography = getattr(style, "typography")
    stroke = getattr(style, "stroke")
    return {
        "typography.font_family": typography.font_family,
        "typography.font_size_pt": typography.font_size_pt,
        "typography.legend_font_size_pt": typography.legend_font_size_pt,
        "typography.panel_label_size_pt": typography.panel_label_size_pt,
        "stroke.axis_linewidth_pt": stroke.axis_linewidth_pt,
        "stroke.tick_width_pt": stroke.tick_width_pt,
        "stroke.tick_length_pt": stroke.tick_length_pt,
        "stroke.minor_tick_width_pt": stroke.minor_tick_width_pt,
        "stroke.minor_tick_length_pt": stroke.minor_tick_length_pt,
        "stroke.line_width_pt": stroke.line_width_pt,
        "stroke.marker_size_pt": stroke.marker_size_pt,
    }


def validate_veusz_template_id(template: object) -> str:
    """Return a production template id or fail before document generation."""

    normalized = str(template or "").strip()
    if normalized not in VEUSZ_IMPLEMENTED_TEMPLATE_IDS:
        known = ", ".join(sorted(VEUSZ_IMPLEMENTED_TEMPLATE_IDS))
        raise ValueError(
            f"Template `{normalized or template}` is not implemented by SciPlot's "
            f"Veusz document builder. Supported templates: {known}."
        )
    return normalized


def audit_style_template_contract(
    *,
    contract: PlotContract | None = None,
    ready_rule_templates: Iterable[str] | None = None,
    render_defaults: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return one fail-closed audit of style and implemented-template claims."""

    resolved_contract = contract or load_plot_contract()
    resolved_ready_templates = {
        str(template)
        for template in (
            ready_rule_templates
            if ready_rule_templates is not None
            else (rule.template for rule in iter_public_rules())
        )
    }
    resolved_render_defaults = dict(
        DEFAULT_RENDER_OPTIONS if render_defaults is None else render_defaults
    )
    recipe_specs = iter_recipe_specs()
    vendor_templates = set(resolved_contract.templates)
    issues: list[dict[str, Any]] = []

    missing_implemented_templates = sorted(
        VEUSZ_IMPLEMENTED_TEMPLATE_IDS - vendor_templates
    )
    if missing_implemented_templates:
        issues.append(
            {
                "code": "implemented_template_missing_from_vendor_contract",
                "templates": missing_implemented_templates,
            }
        )

    for template_id, required_options in VEUSZ_REQUIRED_EDITABLE_OPTIONS.items():
        template = resolved_contract.templates.get(template_id)
        if template is None:
            continue
        missing_options = sorted(
            required_options - set(template.editable_options)
        )
        if missing_options:
            issues.append(
                {
                    "code": "implemented_template_missing_runtime_options",
                    "template_id": template_id,
                    "options": missing_options,
                }
            )

    for template_id, color_options in VEUSZ_TEMPLATE_COLOR_OPTIONS.items():
        template = resolved_contract.templates.get(template_id)
        if template is None:
            continue
        missing_color_options = sorted(
            color_options - set(template.editable_options)
        )
        if missing_color_options:
            issues.append(
                {
                    "code": "template_color_contract_missing_runtime_options",
                    "template_id": template_id,
                    "options": missing_color_options,
                }
            )
        incorrectly_global = sorted(color_options & UNIFIED_HARD_OPTION_KEYS)
        if incorrectly_global:
            issues.append(
                {
                    "code": "template_color_contract_misclassified_as_global",
                    "template_id": template_id,
                    "options": incorrectly_global,
                }
            )

    unsupported_ready_templates = sorted(
        resolved_ready_templates - VEUSZ_IMPLEMENTED_TEMPLATE_IDS
    )
    if unsupported_ready_templates:
        issues.append(
            {
                "code": "ready_rule_uses_unimplemented_template",
                "templates": unsupported_ready_templates,
            }
        )

    unsupported_recipe_templates = sorted(
        {
            spec.default_template
            for spec in recipe_specs
            if spec.default_template not in VEUSZ_IMPLEMENTED_TEMPLATE_IDS
        }
    )
    if unsupported_recipe_templates:
        issues.append(
            {
                "code": "recipe_uses_unimplemented_default_template",
                "templates": unsupported_recipe_templates,
            }
        )

    expected_render = _expected_render_hard_values()
    actual_render = {
        key: resolved_render_defaults.get(key) for key in expected_render
    }
    if actual_render != expected_render:
        issues.append(
            {
                "code": "render_default_style_drift",
                "expected": expected_render,
                "actual": actual_render,
            }
        )

    expected_optional_hard = _expected_optional_hard_values()
    for template_id, template in sorted(resolved_contract.templates.items()):
        template_hard_values = {
            key: value
            for key, value in template.default_options.items()
            if key in UNIFIED_HARD_OPTION_KEYS
        }
        drifted_template_values = {
            key: {
                "expected": expected_optional_hard[key],
                "actual": value,
            }
            for key, value in template_hard_values.items()
            if value != expected_optional_hard[key]
        }
        if drifted_template_values:
            issues.append(
                {
                    "code": "vendor_template_hard_style_drift",
                    "template_id": template_id,
                    "values": drifted_template_values,
                }
            )

    expected_vendor = _expected_vendor_style_values()
    for style_id, style in sorted(resolved_contract.styles.items()):
        actual_vendor = _vendor_style_values(style)
        if actual_vendor != expected_vendor:
            issues.append(
                {
                    "code": "vendor_style_drift",
                    "style_id": style_id,
                    "expected": expected_vendor,
                    "actual": actual_vendor,
                }
            )

    expected_frame = _expected_global_frame()
    actual_frame = {
        key: float(getattr(resolved_contract.global_frame, key))
        for key in expected_frame
    }
    if actual_frame != expected_frame:
        issues.append(
            {
                "code": "global_frame_drift",
                "expected": expected_frame,
                "actual": actual_frame,
            }
        )

    profile_ids: list[str] = []
    allowed_sizes = {
        tuple(float(part) for part in size.split("x", 1))
        for size in FIGURE_SIZE_PRESETS
    }
    expected_profile_hard = {
        "font_family": UNIFIED_FONT_FAMILY,
        "font_size_pt": UNIFIED_FONT_SIZE_PT,
        "axis_linewidth_pt": UNIFIED_AXIS_LINEWIDTH_PT,
        "line_width_pt": UNIFIED_LINE_WIDTH_PT,
        "tick_width_pt": UNIFIED_TICK_WIDTH_PT,
        "tick_length_pt": UNIFIED_TICK_LENGTH_PT,
        "minor_tick_width_pt": UNIFIED_MINOR_TICK_WIDTH_PT,
        "minor_tick_length_pt": UNIFIED_MINOR_TICK_LENGTH_PT,
    }
    for summary in list_figure_profiles():
        profile = get_figure_profile(str(summary["profile_id"]))
        profile_ids.append(profile.profile_id)
        if (
            profile.template is not None
            and profile.template not in VEUSZ_IMPLEMENTED_TEMPLATE_IDS
        ):
            issues.append(
                {
                    "code": "figure_profile_uses_unimplemented_template",
                    "profile_id": profile.profile_id,
                    "template": profile.template,
                }
            )
        if profile.frame_margins_mm is not None:
            issues.append(
                {
                    "code": "figure_profile_private_frame",
                    "profile_id": profile.profile_id,
                    "expected": None,
                    "actual": profile.frame_margins_mm,
                }
            )
        if tuple(float(value) for value in profile.size_mm) not in allowed_sizes:
            if not profile.publication_layout_id:
                issues.append(
                    {
                        "code": "nonstandard_profile_without_layout_authority",
                        "profile_id": profile.profile_id,
                        "size_mm": list(profile.size_mm),
                    }
                )
        if profile.publication_layout_id:
            try:
                layout = get_figure_layout(profile.publication_layout_id)
            except ValueError:
                issues.append(
                    {
                        "code": "figure_profile_unknown_layout_authority",
                        "profile_id": profile.profile_id,
                        "layout_id": profile.publication_layout_id,
                    }
                )
            else:
                layout_checks = {
                    "size_mm": (
                        list(profile.size_mm),
                        list(layout.size_mm),
                    ),
                    "outer_frame_x_mm": (
                        profile.qa_contract.get("outer_frame_x_mm"),
                        list(layout.outer_frame_x_mm),
                    ),
                    "panel_frame_y_mm": (
                        profile.qa_contract.get("panel_frame_y_mm"),
                        list(layout.panel_frame_y_mm),
                    ),
                    "panel_gap_mm": (
                        profile.qa_contract.get("panel_gap_mm"),
                        layout.panel_gap_mm,
                    ),
                    "colorbar_frame_mm": (
                        profile.qa_contract.get("colorbar_frame_mm"),
                        list(layout.colorbar_frame_mm),
                    ),
                    "render_outer_frame_x_mm": (
                        [
                            profile.render_options.get(
                                "panel_outer_left_mm"
                            ),
                            profile.render_options.get(
                                "panel_outer_right_mm"
                            ),
                        ],
                        list(layout.outer_frame_x_mm),
                    ),
                    "render_panel_frame_y_mm": (
                        [
                            profile.render_options.get("panel_top_mm"),
                            profile.render_options.get("panel_bottom_mm"),
                        ],
                        list(layout.panel_frame_y_mm),
                    ),
                    "render_panel_gap_mm": (
                        profile.render_options.get("panel_gap_mm"),
                        layout.panel_gap_mm,
                    ),
                    "render_colorbar_frame_mm": (
                        [
                            profile.render_options.get("colorbar_left_mm"),
                            profile.render_options.get("panel_top_mm"),
                            profile.render_options.get("colorbar_right_mm"),
                            profile.render_options.get("panel_bottom_mm"),
                        ],
                        list(layout.colorbar_frame_mm),
                    ),
                }
                drifted_layout = {
                    key: {"actual": actual, "expected": expected}
                    for key, (actual, expected) in layout_checks.items()
                    if actual != expected
                }
                if drifted_layout:
                    issues.append(
                        {
                            "code": "figure_profile_layout_drift",
                            "profile_id": profile.profile_id,
                            "layout_id": profile.publication_layout_id,
                            "values": drifted_layout,
                        }
                    )
        for owner, values in (
            ("render_options", profile.render_options),
            ("qa_contract", profile.qa_contract),
        ):
            profile_hard = {
                key: values[key] for key in expected_profile_hard if key in values
            }
            drifted_profile_hard = {
                key: {
                    "expected": expected_profile_hard[key],
                    "actual": value,
                }
                for key, value in profile_hard.items()
                if value != expected_profile_hard[key]
            }
            if drifted_profile_hard:
                issues.append(
                    {
                        "code": "figure_profile_hard_style_drift",
                        "profile_id": profile.profile_id,
                        "owner": owner,
                        "values": drifted_profile_hard,
                    }
                )
        if profile.figure_kind == "shared_scalar_strip":
            scalar_style = {
                "colormap_name": profile.render_options.get("colormap_name"),
                "colormap_colors": tuple(
                    profile.render_options.get("colormap_colors") or ()
                ),
            }
            expected_scalar_style = {
                "colormap_name": DEFAULT_SCALAR_FIELD_COLORMAP_ID,
                "colormap_colors": DEFAULT_SCALAR_FIELD_COLORS,
            }
            if scalar_style != expected_scalar_style:
                issues.append(
                    {
                        "code": "figure_profile_scalar_style_drift",
                        "profile_id": profile.profile_id,
                        "expected": expected_scalar_style,
                        "actual": scalar_style,
                    }
                )
        expected_outer_frame = [
            UNIFIED_LEFT_MARGIN_MM,
            float(profile.size_mm[0]) - UNIFIED_RIGHT_MARGIN_MM,
        ]
        for key in ("plot_frame_x_mm", "outer_frame_x_mm"):
            if key not in profile.qa_contract:
                continue
            actual_outer_frame = [
                float(value) for value in profile.qa_contract[key]
            ]
            if actual_outer_frame != expected_outer_frame:
                issues.append(
                    {
                        "code": "figure_profile_outer_frame_drift",
                        "profile_id": profile.profile_id,
                        "field": key,
                        "expected": expected_outer_frame,
                        "actual": actual_outer_frame,
                    }
                )

    return {
        "kind": "sciplot_style_template_contract_audit",
        "version": 3,
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "implemented_veusz_templates": sorted(VEUSZ_IMPLEMENTED_TEMPLATE_IDS),
        "ready_rule_templates": sorted(resolved_ready_templates),
        "recipe_default_templates": sorted(
            {spec.default_template for spec in recipe_specs}
        ),
        "vendor_templates": sorted(vendor_templates),
        "template_color_options": {
            template_id: sorted(options)
            for template_id, options in sorted(VEUSZ_TEMPLATE_COLOR_OPTIONS.items())
        },
        "figure_profiles": sorted(profile_ids),
        "hard_style_values": {
            "render_defaults": expected_render,
            "optional_render_values": expected_optional_hard,
            "vendor_styles": expected_vendor,
            "global_frame": expected_frame,
            "ordinary_foreground_color": UNIFIED_FOREGROUND_COLOR,
        },
        "template_color_defaults": {
            "heatmap": {
                "id": DEFAULT_SCALAR_FIELD_COLORMAP_ID,
                "colors": list(DEFAULT_SCALAR_FIELD_COLORS),
            }
        },
    }


__all__ = [
    "VEUSZ_IMPLEMENTED_TEMPLATE_IDS",
    "VEUSZ_REQUIRED_EDITABLE_OPTIONS",
    "VEUSZ_TEMPLATE_COLOR_OPTIONS",
    "audit_style_template_contract",
    "validate_veusz_template_id",
]
