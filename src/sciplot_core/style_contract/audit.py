"""Audit shared and template-specific style ownership."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
from sciplot_core.contract import (
    PlotContract,
    lint_public_template_contract,
    load_plot_contract,
)
from sciplot_core.materials_rules import (
    iter_public_rules,
    scientific_unit_expression_contract,
    unit_solidus_violations,
)
from sciplot_core.policy import (
    CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS,
    CURVE_RENDER_OPTIONS,
    DEFAULT_PALETTE_COLORS,
    DEFAULT_PALETTE_PRESET,
    DEFAULT_RENDER_OPTIONS,
    DEFAULT_SCALAR_FIELD_COLORMAP_ID,
    DEFAULT_SCALAR_FIELD_COLORS,
    UNIFIED_FOREGROUND_COLOR,
    UNIFIED_HARD_OPTION_KEYS,
    POINT_LINE_RENDER_OPTIONS,
)
from sciplot_recipes.contracts import iter_recipe_specs

from sciplot_core.style_contract.template_contracts import (
    VEUSZ_IMPLEMENTED_TEMPLATE_IDS,
    VEUSZ_REQUIRED_EDITABLE_OPTIONS,
    VEUSZ_TEMPLATE_COLOR_OPTIONS,
)

from sciplot_core.style_contract.expected_values import (
    _expected_render_hard_values,
    _expected_optional_hard_values,
    _expected_contract_style_values,
    _expected_global_frame,
)

from sciplot_core.style_contract.contract_values import (
    _contract_style_values,
)


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
    ready_rules = list(iter_public_rules())
    recipe_specs = iter_recipe_specs()
    contract_templates = set(resolved_contract.templates)
    issues: list[dict[str, Any]] = []
    unit_expression_violations: list[dict[str, Any]] = []

    contract_reference_issues = list(lint_public_template_contract(resolved_contract))
    if contract_reference_issues:
        issues.append(
            {
                "code": "plot_contract_reference_drift",
                "issues": contract_reference_issues,
            }
        )

    contract_default_palette = resolved_contract.defaults.palette_preset
    runtime_default_palette = str(resolved_render_defaults.get("palette_preset") or "")
    if contract_default_palette != DEFAULT_PALETTE_PRESET or (
        runtime_default_palette != DEFAULT_PALETTE_PRESET
    ):
        issues.append(
            {
                "code": "ordinary_palette_default_drift",
                "expected": DEFAULT_PALETTE_PRESET,
                "contract": contract_default_palette,
                "runtime": runtime_default_palette,
            }
        )
    default_palette = resolved_contract.palettes.get(DEFAULT_PALETTE_PRESET)
    contract_default_colors = (
        tuple(default_palette.categorical) if default_palette is not None else ()
    )
    if contract_default_colors != tuple(DEFAULT_PALETTE_COLORS):
        issues.append(
            {
                "code": "ordinary_palette_color_drift",
                "palette_id": DEFAULT_PALETTE_PRESET,
                "expected": list(DEFAULT_PALETTE_COLORS),
                "contract": list(contract_default_colors),
            }
        )

    template_palette_drift = {
        template_id: {
            "default": template.default_options.get("palette_preset"),
            "available": list(template.available_palettes),
        }
        for template_id, template in sorted(resolved_contract.templates.items())
        if template.default_options.get("palette_preset") != DEFAULT_PALETTE_PRESET
        or DEFAULT_PALETTE_PRESET not in template.available_palettes
    }
    if template_palette_drift:
        issues.append(
            {
                "code": "template_ordinary_palette_drift",
                "templates": template_palette_drift,
            }
        )

    policy_default_drift = {
        policy_name: options.get("palette_preset")
        for policy_name, options in {
            "curve": CURVE_RENDER_OPTIONS,
            "point_line": POINT_LINE_RENDER_OPTIONS,
            "categorical_distribution": CATEGORICAL_DISTRIBUTION_RENDER_OPTIONS,
        }.items()
        if options.get("palette_preset") != DEFAULT_PALETTE_PRESET
    }
    if policy_default_drift:
        issues.append(
            {
                "code": "python_palette_policy_drift",
                "expected": DEFAULT_PALETTE_PRESET,
                "policies": policy_default_drift,
            }
        )

    style_palette_drift = {
        style_id: style.recommended_palette_preset
        for style_id, style in sorted(resolved_contract.styles.items())
        if style.recommended_palette_preset != DEFAULT_PALETTE_PRESET
    }
    if style_palette_drift:
        issues.append(
            {
                "code": "style_palette_recommendation_drift",
                "expected": DEFAULT_PALETTE_PRESET,
                "styles": style_palette_drift,
            }
        )

    rule_palette_drift = {
        rule.rule_id: rule.render_options.get("palette_preset")
        for rule in ready_rules
        if rule.render_options.get("palette_preset") != DEFAULT_PALETTE_PRESET
    }
    if rule_palette_drift:
        issues.append(
            {
                "code": "ready_rule_palette_default_drift",
                "expected": DEFAULT_PALETTE_PRESET,
                "rules": rule_palette_drift,
            }
        )
    for rule in ready_rules:
        candidates = [
            ("x_axis.display_label", rule.x_axis.display_label),
            ("y_axis.display_label", rule.y_axis.display_label),
            *[
                (f"render_options.{key}", value)
                for key, value in rule.render_options.items()
                if isinstance(value, str) and "label" in str(key).casefold()
            ],
        ]
        for field, text in candidates:
            for violation in unit_solidus_violations(text):
                unit_expression_violations.append(
                    {
                        "rule_id": rule.rule_id,
                        "field": field,
                        "text": text,
                        **violation,
                    }
                )
    if unit_expression_violations:
        issues.append(
            {
                "code": "ready_rule_unit_expression_drift",
                "violations": unit_expression_violations,
            }
        )

    missing_implemented_templates = sorted(
        VEUSZ_IMPLEMENTED_TEMPLATE_IDS - contract_templates
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
        missing_options = sorted(required_options - set(template.editable_options))
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
        missing_color_options = sorted(color_options - set(template.editable_options))
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
    actual_render = {key: resolved_render_defaults.get(key) for key in expected_render}
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

    expected_contract_styles = _expected_contract_style_values()
    for style_id, style in sorted(resolved_contract.styles.items()):
        actual_contract_style = _contract_style_values(style)
        if actual_contract_style != expected_contract_styles:
            issues.append(
                {
                    "code": "vendor_style_drift",
                    "style_id": style_id,
                    "expected": expected_contract_styles,
                    "actual": actual_contract_style,
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

    return {
        "kind": "sciplot_style_template_contract_audit",
        "version": 5,
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "implemented_veusz_templates": sorted(VEUSZ_IMPLEMENTED_TEMPLATE_IDS),
        "ready_rule_templates": sorted(resolved_ready_templates),
        "recipe_default_templates": sorted(
            {spec.default_template for spec in recipe_specs}
        ),
        "vendor_templates": sorted(contract_templates),
        "template_color_options": {
            template_id: sorted(options)
            for template_id, options in sorted(VEUSZ_TEMPLATE_COLOR_OPTIONS.items())
        },
        "hard_style_values": {
            "render_defaults": expected_render,
            "optional_render_values": expected_optional_hard,
            "vendor_styles": expected_contract_styles,
            "global_frame": expected_frame,
            "ordinary_foreground_color": UNIFIED_FOREGROUND_COLOR,
        },
        "unit_expression_contract": {
            **scientific_unit_expression_contract(),
            "ready_rule_violations": unit_expression_violations,
        },
        "template_color_defaults": {
            "heatmap": {
                "id": DEFAULT_SCALAR_FIELD_COLORMAP_ID,
                "colors": list(DEFAULT_SCALAR_FIELD_COLORS),
            }
        },
        "ordinary_palette_contract": {
            "palette_id": DEFAULT_PALETTE_PRESET,
            "colors": list(DEFAULT_PALETTE_COLORS),
            "authority_order": [
                "explicit_render_option",
                "direct_render_option",
                "shared_project_default",
            ],
            "explicit_alternatives": sorted(
                palette_id
                for palette_id, palette in resolved_contract.palettes.items()
                if palette.public and palette_id != DEFAULT_PALETTE_PRESET
            ),
            "scalar_field_exception": {
                "template": "heatmap",
                "colormap_id": DEFAULT_SCALAR_FIELD_COLORMAP_ID,
                "colors": list(DEFAULT_SCALAR_FIELD_COLORS),
            },
        },
    }
