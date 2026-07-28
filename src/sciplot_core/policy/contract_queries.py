"""Query and validate individual sections of the plot contract."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from sciplot_core.policy.contract_loader import load_plot_contract
from sciplot_core.policy.contract_models import (
    PlotContract,
    SizePresetSpec,
    StyleContract,
    TemplateContract,
    ValidationRuleContract,
)


SUPPORTED_VISUAL_THEME_IDS = frozenset(
    {
        "clean_light",
        "soft_grid",
        "presentation_like",
        "infographic",
        "roma",
        "macarons",
        "shine",
        "vintage",
    }
)


def plot_contract_dict(*, public_only: bool = False) -> dict[str, Any]:
    """Return a JSON-compatible representation of the plot contract."""

    contract = load_plot_contract()
    return {
        "version": contract.version,
        "defaults": asdict(contract.defaults),
        "aliases": {"style_presets": dict(contract.style_aliases)},
        "global_frame": asdict(contract.global_frame),
        "axis_policy": asdict(contract.axis_policy),
        "size_presets": {
            key: asdict(value) for key, value in contract.size_presets.items()
        },
        "special_layouts": contract.special_layouts,
        "qa_profiles": contract.qa_profiles,
        "styles": {
            key: {
                **asdict(value),
                "typography": asdict(value.typography),
                "stroke": asdict(value.stroke),
                "spacing": asdict(value.spacing),
                "annotation": asdict(value.annotation),
                "export": asdict(value.export),
            }
            for key, value in contract.styles.items()
            if not public_only or value.public
        },
        "palettes": {
            key: asdict(value)
            for key, value in contract.palettes.items()
            if not public_only or value.public
        },
        "templates": {key: asdict(value) for key, value in contract.templates.items()},
        "validation_rules": {
            key: asdict(value) for key, value in contract.validation_rules.items()
        },
    }


def template_contract(template: str) -> TemplateContract:
    try:
        return load_plot_contract().templates[template]
    except KeyError as exc:
        raise ValueError(f"Unknown template contract: {template}") from exc


def size_preset_contract(size_name: str) -> SizePresetSpec:
    try:
        return load_plot_contract().size_presets[size_name]
    except KeyError as exc:
        raise ValueError(f"Unknown size preset: {size_name}") from exc


def validation_rule(rule_name: str) -> ValidationRuleContract:
    try:
        return load_plot_contract().validation_rules[rule_name]
    except KeyError as exc:
        raise ValueError(f"Unknown validation rule: {rule_name}") from exc


def qa_profile(profile_name: str) -> dict[str, Any]:
    try:
        return dict(load_plot_contract().qa_profiles[profile_name])
    except KeyError as exc:
        raise ValueError(f"Unknown QA profile: {profile_name}") from exc


def public_style_names() -> tuple[str, ...]:
    return tuple(
        name for name, spec in load_plot_contract().styles.items() if spec.public
    )


def public_palette_names() -> tuple[str, ...]:
    return tuple(
        name for name, spec in load_plot_contract().palettes.items() if spec.public
    )


def style_names() -> tuple[str, ...]:
    return tuple(load_plot_contract().styles)


def palette_names() -> tuple[str, ...]:
    return tuple(load_plot_contract().palettes)


def template_names() -> tuple[str, ...]:
    return tuple(load_plot_contract().templates)


def size_names() -> tuple[str, ...]:
    return tuple(load_plot_contract().size_presets)


def default_size_for_template(template: str) -> str:
    return template_contract(template).default_size


def default_options_for_template(template: str) -> dict[str, Any]:
    return dict(template_contract(template).default_options)


def normalize_style_alias(style_name: str | None) -> str:
    contract = load_plot_contract()
    candidate = (style_name or contract.defaults.style_preset).strip()
    return contract.style_aliases.get(candidate, candidate)


def style_contract(style_name: str) -> StyleContract:
    try:
        return load_plot_contract().styles[normalize_style_alias(style_name)]
    except KeyError as exc:
        raise ValueError(f"Unknown style contract: {style_name}") from exc


def lint_public_template_contract(
    contract: PlotContract | None = None,
) -> tuple[str, ...]:
    """Report broken references in public template defaults and catalogs."""

    resolved = contract or load_plot_contract()
    valid_styles = {name for name, spec in resolved.styles.items() if spec.public}
    valid_palettes = {name for name, spec in resolved.palettes.items() if spec.public}
    issues: list[str] = []
    for template_id, spec in resolved.templates.items():
        defaults = dict(spec.default_options)
        for key in ("style_preset", "palette_preset", "visual_theme_id"):
            if defaults.get(key) in {None, ""}:
                issues.append(
                    f"Template `{template_id}` is missing default_options.{key}."
                )
        if not spec.available_styles:
            issues.append(
                f"Template `{template_id}` must expose at least one available style."
            )
        if not spec.available_palettes:
            issues.append(
                f"Template `{template_id}` must expose at least one available palette."
            )
        if spec.default_size not in spec.allowed_sizes:
            issues.append(
                f"Template `{template_id}` default_size must also appear in "
                "allowed_sizes."
            )
        style_default = defaults.get("style_preset")
        palette_default = defaults.get("palette_preset")
        theme_default = defaults.get("visual_theme_id")
        if style_default is not None and style_default not in spec.available_styles:
            issues.append(
                f"Template `{template_id}` default style `{style_default}` is not "
                "listed in available_styles."
            )
        if (
            palette_default is not None
            and palette_default not in spec.available_palettes
        ):
            issues.append(
                f"Template `{template_id}` default palette `{palette_default}` is "
                "not listed in available_palettes."
            )
        if style_default is not None and style_default not in valid_styles:
            issues.append(
                f"Template `{template_id}` default style `{style_default}` is not public."
            )
        if palette_default is not None and palette_default not in valid_palettes:
            issues.append(
                f"Template `{template_id}` default palette `{palette_default}` is "
                "not public."
            )
        if (
            theme_default is not None
            and theme_default not in SUPPORTED_VISUAL_THEME_IDS
        ):
            issues.append(
                f"Template `{template_id}` default visual theme `{theme_default}` "
                "is unknown."
            )
        for style_id in spec.available_styles:
            if style_id not in valid_styles:
                issues.append(
                    f"Template `{template_id}` lists unknown style `{style_id}`."
                )
        for palette_id in spec.available_palettes:
            if palette_id not in valid_palettes:
                issues.append(
                    f"Template `{template_id}` lists unknown palette `{palette_id}`."
                )
    return tuple(issues)


__all__ = [
    "SUPPORTED_VISUAL_THEME_IDS",
    "default_options_for_template",
    "default_size_for_template",
    "lint_public_template_contract",
    "normalize_style_alias",
    "palette_names",
    "plot_contract_dict",
    "public_palette_names",
    "public_style_names",
    "qa_profile",
    "size_names",
    "size_preset_contract",
    "style_contract",
    "style_names",
    "template_contract",
    "template_names",
    "validation_rule",
]
