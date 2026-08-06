"""Build and evaluate versioned render-request policy contracts."""

from __future__ import annotations

from copy import deepcopy
from typing import Any
from sciplot_core.foundation.json_values import json_safe
from sciplot_core.materials_rules import (
    SemanticRule,
    get_rule,
    resolve_rule_template,
)
from sciplot_core.policy import (
    DEFAULT_EXPORT_FORMATS_POLICY,
    DEFAULT_FIGURE_SIZE,
    FIGURE_SIZE_PRESETS,
    RENDER_OPTION_KEYS,
    SUPPORTED_EXPORT_FORMATS,
    VALIDATED_VISUAL_OVERRIDE_KEYS,
    canonical_export_format,
)

from sciplot_core.readiness.constants import (
    VALIDATED_RENDER_REQUEST_CONTRACT_KIND,
    VALIDATED_RENDER_REQUEST_CONTRACT_VERSION,
    VALIDATED_RENDER_REQUEST_POLICY_VERSION,
    _RENDER_REQUEST_PACKAGE_FIELDS,
    _RENDER_REQUEST_CONTRACT_FIELDS,
)

from sciplot_core.readiness.validation import (
    _required_text,
    _closed_object,
)

from sciplot_core.readiness.semantic_contract import (
    _certified_render_option_baseline,
)


def validated_render_request_policy_payload(
    rule: SemanticRule | str,
) -> dict[str, Any]:
    """Return the closed runtime-variation policy bound into a rule certificate."""

    resolved = get_rule(rule) if isinstance(rule, str) else rule
    unknown_visual_keys = VALIDATED_VISUAL_OVERRIDE_KEYS - RENDER_OPTION_KEYS
    if unknown_visual_keys:
        raise ValueError(
            "Validated visual override policy contains unknown render options: "
            + ", ".join(sorted(unknown_visual_keys))
        )
    exact_keys = RENDER_OPTION_KEYS - VALIDATED_VISUAL_OVERRIDE_KEYS
    return {
        "version": VALIDATED_RENDER_REQUEST_POLICY_VERSION,
        "allowed_routes": ["auto"],
        "template_policy": "explicit_supported_template_or_default",
        "default_template": resolved.template,
        "supported_templates": list(resolved.presentation_templates),
        "effective_recipe": resolved.recipe,
        "required_exports": list(DEFAULT_EXPORT_FORMATS_POLICY),
        "allowed_exports": sorted(SUPPORTED_EXPORT_FORMATS),
        "figure_size_presets": list(FIGURE_SIZE_PRESETS),
        "split_policy": "empty_only",
        "visual_override_keys": sorted(VALIDATED_VISUAL_OVERRIDE_KEYS),
        "exact_certified_value_keys": sorted(exact_keys),
        "certified_axis_label_source": "semantic_axis_display_label_v1",
    }


def _render_request_route(
    *,
    requested_recipe: str | None,
    requested_template: str | None,
) -> str:
    # Import lazily because the legacy workflow compatibility facade imports
    # readiness during renderer startup.
    from sciplot_core.workflow.route_intent import resolve_workflow_route_intent

    request = {}
    if requested_recipe is not None:
        request["recipe"] = requested_recipe
    if requested_template is not None:
        request["template"] = requested_template
    return resolve_workflow_route_intent(request).route


def render_request_contract_payload(
    rule: SemanticRule | str,
    render_request: dict[str, Any],
) -> dict[str, Any]:
    """Build the portable portion of the actual runtime render request."""

    resolved = get_rule(rule) if isinstance(rule, str) else rule
    requested_recipe = render_request.get("recipe")
    requested_template = render_request.get("template")
    route = _render_request_route(
        requested_recipe=(
            requested_recipe if isinstance(requested_recipe, str) else None
        ),
        requested_template=(
            requested_template if isinstance(requested_template, str) else None
        ),
    )
    effective_recipe = resolved.recipe if route == "auto" else requested_recipe
    effective_template = (
        resolve_rule_template(resolved, requested_template)
        if route == "auto"
        else requested_template
    )
    exports = render_request.get("exports")
    normalized_exports = (
        sorted(dict.fromkeys(str(item) for item in exports))
        if isinstance(exports, list)
        else []
    )
    explicit_keys = render_request.get("explicit_render_option_keys")
    normalized_explicit_keys = (
        sorted(dict.fromkeys(str(item) for item in explicit_keys))
        if isinstance(explicit_keys, list)
        else []
    )
    return {
        "kind": VALIDATED_RENDER_REQUEST_CONTRACT_KIND,
        "version": VALIDATED_RENDER_REQUEST_CONTRACT_VERSION,
        "policy_version": VALIDATED_RENDER_REQUEST_POLICY_VERSION,
        "rule_id": resolved.rule_id,
        "route": route,
        "requested_recipe": requested_recipe,
        "effective_recipe": effective_recipe,
        "requested_template": requested_template,
        "effective_template": effective_template,
        "exports": normalized_exports,
        "render_engine": render_request.get("render_engine"),
        "figure_size": render_request.get("figure_size"),
        "render_options": deepcopy(json_safe(render_request.get("render_options"))),
        "split_policy": deepcopy(json_safe(render_request.get("split_policy"))),
        "series_order": deepcopy(json_safe(render_request.get("series_order"))),
        "explicit_render_option_keys": normalized_explicit_keys,
    }


def _render_request_policy_evaluation(
    rule: SemanticRule,
    render_request: object,
) -> tuple[dict[str, Any] | None, list[str], list[str]]:
    repair_reasons: list[str] = []
    confirmation_reasons: list[str] = []
    try:
        package = _closed_object(
            render_request,
            label="render request package",
            expected=_RENDER_REQUEST_PACKAGE_FIELDS,
        )
    except ValueError:
        return None, ["render_request_contract_invalid"], []

    if (
        package.get("kind") != "sciplot_render_request"
        or isinstance(package.get("version"), bool)
        or not isinstance(package.get("version"), int)
        or package.get("version") != 1
    ):
        repair_reasons.append("render_request_package_contract_invalid")
    try:
        _required_text(package.get("path"), "render request path", maximum=8192)
    except ValueError:
        repair_reasons.append("render_request_path_invalid")

    presented_rule_id = package.get("rule_id")
    if presented_rule_id is not None:
        try:
            presented_rule_id = _required_text(
                presented_rule_id,
                "render request rule_id",
            )
        except ValueError:
            repair_reasons.append("render_request_rule_invalid")
        else:
            if presented_rule_id != rule.rule_id:
                repair_reasons.append("render_request_rule_mismatch")

    requested_recipe = package.get("recipe")
    if requested_recipe is not None:
        try:
            requested_recipe = _required_text(
                requested_recipe,
                "render request recipe",
            )
        except ValueError:
            repair_reasons.append("render_request_recipe_invalid")
            requested_recipe = None
    requested_template = package.get("template")
    if requested_template is not None:
        try:
            requested_template = _required_text(
                requested_template,
                "render request template",
            )
        except ValueError:
            repair_reasons.append("render_request_template_invalid")
            requested_template = None

    route = _render_request_route(
        requested_recipe=requested_recipe,
        requested_template=requested_template,
    )
    if route != "auto":
        confirmation_reasons.append("render_route_outside_validated_policy")
    if (
        requested_template is not None
        and requested_template not in rule.presentation_templates
    ):
        repair_reasons.append("render_template_unsupported_for_rule")
    if package.get("render_engine") != "veusz":
        repair_reasons.append("render_engine_contract_invalid")

    exports = package.get("exports")
    normalized_exports: list[str] = []
    if not isinstance(exports, list) or not exports:
        repair_reasons.append("render_exports_invalid")
    else:
        for index, value in enumerate(exports):
            try:
                export = _required_text(
                    value,
                    f"render export[{index}]",
                    maximum=32,
                ).casefold()
            except ValueError:
                repair_reasons.append("render_exports_invalid")
                continue
            try:
                normalized_exports.append(canonical_export_format(export))
            except ValueError:
                repair_reasons.append("render_export_unsupported")
        if len(set(normalized_exports)) != len(normalized_exports):
            repair_reasons.append("render_exports_not_unique")
        if not set(DEFAULT_EXPORT_FORMATS_POLICY).issubset(normalized_exports):
            repair_reasons.append("canonical_pdf_tiff_exports_missing")

    render_options = package.get("render_options")
    if not isinstance(render_options, dict):
        repair_reasons.append("render_options_contract_invalid")
        render_options = {}
    elif any(not isinstance(key, str) for key in render_options):
        repair_reasons.append("render_options_contract_invalid")
    else:
        unknown_keys = set(render_options) - RENDER_OPTION_KEYS
        if unknown_keys:
            repair_reasons.append("render_options_unsupported")
        effective_template = (
            requested_template
            if requested_template in rule.presentation_templates
            else rule.template
        )
        try:
            from sciplot_core.request_contract import normalize_render_options

            normalized_options = normalize_render_options(
                render_options,
                template=effective_template,
            )
        except ValueError:
            repair_reasons.append("render_options_contract_invalid")
        else:
            if json_safe(normalized_options) != json_safe(render_options):
                repair_reasons.append("render_options_not_canonical")

    figure_size = package.get("figure_size")
    expected_size = render_options.get("size") or DEFAULT_FIGURE_SIZE
    if (
        not isinstance(figure_size, str)
        or figure_size not in FIGURE_SIZE_PRESETS
        or figure_size != expected_size
    ):
        repair_reasons.append("render_figure_size_invalid")

    split_policy = package.get("split_policy")
    if not isinstance(split_policy, dict):
        repair_reasons.append("render_split_policy_invalid")
    elif split_policy:
        confirmation_reasons.append("render_split_policy_requires_confirmation")

    series_order = package.get("series_order")
    normalized_series_order: list[str] = []
    if not isinstance(series_order, list):
        repair_reasons.append("render_series_order_invalid")
    else:
        for index, value in enumerate(series_order):
            try:
                normalized_series_order.append(
                    _required_text(
                        value,
                        f"render series_order[{index}]",
                        maximum=512,
                    )
                )
            except ValueError:
                repair_reasons.append("render_series_order_invalid")
        if len(set(normalized_series_order)) != len(normalized_series_order):
            repair_reasons.append("render_series_order_not_unique")
    options_series_order = render_options.get("series_order")
    if (
        options_series_order is not None
        and json_safe(options_series_order) != normalized_series_order
    ):
        repair_reasons.append("render_series_order_binding_mismatch")

    explicit_keys = package.get("explicit_render_option_keys")
    if not isinstance(explicit_keys, list):
        repair_reasons.append("explicit_render_option_keys_invalid")
    else:
        normalized_explicit: list[str] = []
        for index, value in enumerate(explicit_keys):
            try:
                normalized_explicit.append(
                    _required_text(
                        value,
                        f"explicit render option[{index}]",
                        maximum=128,
                    )
                )
            except ValueError:
                repair_reasons.append("explicit_render_option_keys_invalid")
        if len(set(normalized_explicit)) != len(normalized_explicit):
            repair_reasons.append("explicit_render_option_keys_not_unique")
        if not set(normalized_explicit).issubset(render_options):
            repair_reasons.append("explicit_render_option_keys_unbound")

    certified_baseline = _certified_render_option_baseline(rule)
    for key, value in render_options.items():
        if key in VALIDATED_VISUAL_OVERRIDE_KEYS:
            continue
        if key not in certified_baseline or json_safe(value) != json_safe(
            certified_baseline[key]
        ):
            confirmation_reasons.append(f"render_option_requires_confirmation:{key}")

    try:
        contract = render_request_contract_payload(rule, package)
        _closed_object(
            contract,
            label="render request contract",
            expected=_RENDER_REQUEST_CONTRACT_FIELDS,
        )
    except ValueError:
        contract = None
        repair_reasons.append("render_request_contract_invalid")
    return (
        contract,
        list(dict.fromkeys(repair_reasons)),
        list(dict.fromkeys(confirmation_reasons)),
    )
