"""Load the serialized plot contract into immutable policy models."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from sciplot_core.policy.contract_models import (
    AnnotationContract,
    AxisFrameContract,
    AxisPolicySpec,
    DefaultsSpec,
    ExportContract,
    GlobalFrameSpec,
    PaletteContract,
    PlotContract,
    SizePresetSpec,
    SpacingContract,
    StrokeContract,
    StyleContract,
    TemplateContract,
    TypographyContract,
    ValidationRuleContract,
)


CONTRACT_PATH = Path(__file__).with_name("plot_contract.json")


def _strings(values: list[str] | tuple[str, ...]) -> tuple[str, ...]:
    return tuple(str(value) for value in values)


def _load_raw_contract() -> dict[str, Any]:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def _load_style(value: dict[str, Any]) -> StyleContract:
    typography = value["typography"]
    return StyleContract(
        label=value["label"],
        public=bool(value["public"]),
        display_group=str(value.get("display_group", "publication")),
        description=value["description"],
        hard_constraints=bool(value["hard_constraints"]),
        preset_note=value["preset_note"],
        recommended_palette_preset=value["recommended_palette_preset"],
        recommended_visual_theme_id=value.get("recommended_visual_theme_id"),
        typography=TypographyContract(
            font_family=_strings(typography["font_family"]),
            font_size_pt=float(typography["font_size_pt"]),
            legend_font_size_pt=float(typography["legend_font_size_pt"]),
            panel_label_size_pt=float(typography["panel_label_size_pt"]),
            panel_label_weight=typography["panel_label_weight"],
        ),
        stroke=StrokeContract(**value["stroke"]),
        spacing=SpacingContract(**value["spacing"]),
        annotation=AnnotationContract(**value["annotation"]),
        axis_frame=AxisFrameContract(**value["axis_frame"]),
        export=ExportContract(**value["export"]),
    )


def _load_template(value: dict[str, Any]) -> TemplateContract:
    return TemplateContract(
        label=value["label"],
        description=value["description"],
        category=value["category"],
        presentation_kind=value["presentation_kind"],
        default_size=value["default_size"],
        allowed_sizes=_strings(value["allowed_sizes"]),
        editable_options=_strings(value["editable_options"]),
        default_options=dict(value.get("default_options", {})),
        available_styles=_strings(value["available_styles"]),
        available_palettes=_strings(value["available_palettes"]),
        hard_rules=_strings(value["hard_rules"]),
        soft_rules=_strings(value["soft_rules"]),
    )


@lru_cache(maxsize=1)
def load_plot_contract() -> PlotContract:
    """Return the process-cached canonical SciPlot plot contract."""

    raw = _load_raw_contract()
    axis_policy = raw["axis_policy"]
    return PlotContract(
        version=int(raw["version"]),
        defaults=DefaultsSpec(**raw["defaults"]),
        style_aliases=dict(raw.get("aliases", {}).get("style_presets", {})),
        global_frame=GlobalFrameSpec(**raw["global_frame"]),
        axis_policy=AxisPolicySpec(
            linear_nice_steps=tuple(
                float(value) for value in axis_policy["linear_nice_steps"]
            ),
            linear_outer_padding_fraction=float(
                axis_policy["linear_outer_padding_fraction"]
            ),
            linear_force_visible_labeled_endpoints=bool(
                axis_policy["linear_force_visible_labeled_endpoints"]
            ),
            log_display_steps=tuple(
                float(value) for value in axis_policy["log_display_steps"]
            ),
            log_label_mode=str(axis_policy["log_label_mode"]),
            log_allow_unlabeled_outer_padding=bool(
                axis_policy["log_allow_unlabeled_outer_padding"]
            ),
            bar_zero_baseline_no_lower_padding=bool(
                axis_policy["bar_zero_baseline_no_lower_padding"]
            ),
            tensile_y_include_zero=bool(axis_policy["tensile_y_include_zero"]),
            stacked_x_use_standard_endpoint_policy=bool(
                axis_policy["stacked_x_use_standard_endpoint_policy"]
            ),
        ),
        size_presets={
            key: SizePresetSpec(**value) for key, value in raw["size_presets"].items()
        },
        special_layouts={
            key: dict(value) for key, value in raw.get("special_layouts", {}).items()
        },
        qa_profiles={
            key: dict(value) for key, value in raw.get("qa_profiles", {}).items()
        },
        styles={key: _load_style(value) for key, value in raw["styles"].items()},
        palettes={
            key: PaletteContract(
                label=value["label"],
                public=bool(value["public"]),
                description=value["description"],
                categorical=_strings(value["categorical"]),
                sequential=value["sequential"],
                diverging=value["diverging"],
            )
            for key, value in raw["palettes"].items()
        },
        templates={
            key: _load_template(value) for key, value in raw["templates"].items()
        },
        validation_rules={
            key: ValidationRuleContract(
                label=value["label"],
                description=value["description"],
                severity=value["severity"],
                tolerance_mm=(
                    float(value["tolerance_mm"])
                    if value.get("tolerance_mm") is not None
                    else None
                ),
            )
            for key, value in raw["validation_rules"].items()
        },
    )


__all__ = ["CONTRACT_PATH", "load_plot_contract"]
