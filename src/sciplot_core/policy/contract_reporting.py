"""Build user-facing catalog and Markdown views of the plot contract."""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Any

from sciplot_core.policy.contract_loader import load_plot_contract
from sciplot_core.policy.contract_models import PlotContract


DOC_PATH = Path(__file__).resolve().parents[3] / "docs" / "plot_contract.md"


def capability_catalog_payload() -> list[dict[str, Any]]:
    return []


def meta_payload() -> dict[str, Any]:
    """Return the compact contract catalog used by metadata clients."""

    contract = load_plot_contract()
    return {
        "version": contract.version,
        "defaults": asdict(contract.defaults),
        "global_frame": asdict(contract.global_frame),
        "sizes": [
            {"id": key, **asdict(value)} for key, value in contract.size_presets.items()
        ],
        "styles": [
            {
                "id": key,
                "label": value.label,
                "public": value.public,
                "display_group": value.display_group,
                "description": value.description,
                "hard_constraints": value.hard_constraints,
                "preset_note": value.preset_note,
                "recommended_palette_preset": value.recommended_palette_preset,
                "recommended_visual_theme_id": value.recommended_visual_theme_id,
            }
            for key, value in contract.styles.items()
        ],
        "palettes": [
            {
                "id": key,
                "label": value.label,
                "public": value.public,
                "description": value.description,
                "swatches": list(value.categorical[:6]),
            }
            for key, value in contract.palettes.items()
        ],
        "templates": [
            {
                "id": key,
                "label": value.label,
                "description": value.description,
                "category": value.category,
                "presentation_kind": value.presentation_kind,
                "default_size": value.default_size,
                "allowed_sizes": list(value.allowed_sizes),
                "editable_options": list(value.editable_options),
                "default_options": dict(value.default_options),
                "available_styles": list(value.available_styles),
                "available_palettes": list(value.available_palettes),
            }
            for key, value in contract.templates.items()
        ],
        "capability_catalogs": capability_catalog_payload(),
    }


def _global_policy_markdown(contract: PlotContract) -> list[str]:
    return [
        "# SciPlot Plot Contract",
        "",
        f"- Version: `{contract.version}`",
        f"- Default style: `{contract.defaults.style_preset}`",
        f"- Default palette: `{contract.defaults.palette_preset}`",
        "",
        "## Global Frame",
        "",
        (
            f"- Standard panel: `{contract.global_frame.panel_width_mm:.1f} x "
            f"{contract.global_frame.panel_height_mm:.1f} mm`"
        ),
        (
            f"- Margins: left `{contract.global_frame.left_margin_mm:.1f} mm`, "
            f"right `{contract.global_frame.right_margin_mm:.1f} mm`, "
            f"bottom `{contract.global_frame.bottom_margin_mm:.1f} mm`, "
            f"top `{contract.global_frame.top_margin_mm:.1f} mm`"
        ),
        "",
        "## Axis Policy",
        "",
        (
            "- Linear axis nice steps: "
            + ", ".join(
                f"`{value:g}`" for value in contract.axis_policy.linear_nice_steps
            )
        ),
        (
            "- Linear outer padding: "
            f"`{contract.axis_policy.linear_outer_padding_fraction * 100:.1f}%` "
            "on standard axes"
        ),
        (
            "- Force labeled linear endpoints visible: "
            f"`{contract.axis_policy.linear_force_visible_labeled_endpoints}`"
        ),
        (
            "- Log display steps: "
            + ", ".join(
                f"`{value:g}`" for value in contract.axis_policy.log_display_steps
            )
        ),
        f"- Log label mode: `{contract.axis_policy.log_label_mode}`",
        (
            "- Log allows unlabeled outer padding: "
            f"`{contract.axis_policy.log_allow_unlabeled_outer_padding}`"
        ),
        (
            "- Bar zero-baseline lower padding disabled: "
            f"`{contract.axis_policy.bar_zero_baseline_no_lower_padding}`"
        ),
        (
            "- Tensile y-axis includes zero: "
            f"`{contract.axis_policy.tensile_y_include_zero}`"
        ),
        (
            "- Stacked x-axis uses standard endpoint policy: "
            f"`{contract.axis_policy.stacked_x_use_standard_endpoint_policy}`"
        ),
        "",
    ]


def _style_markdown(contract: PlotContract) -> list[str]:
    lines = ["## Styles", ""]
    for name, spec in contract.styles.items():
        lines.extend(
            [
                f"### `{name}` / {spec.label}",
                "",
                f"- Description: {spec.description}",
                f"- Hard constraints: `{spec.hard_constraints}`",
                f"- Recommended palette: `{spec.recommended_palette_preset}`",
                (
                    "- Recommended visual theme: "
                    f"`{spec.recommended_visual_theme_id or 'None'}`"
                ),
                (
                    "- Axis frame: "
                    f"left=`{spec.axis_frame.left}`, "
                    f"bottom=`{spec.axis_frame.bottom}`, "
                    f"top=`{spec.axis_frame.top}`, "
                    f"right=`{spec.axis_frame.right}`"
                ),
                f"- Preset note: {spec.preset_note}",
                "",
            ]
        )
    return lines


def _template_markdown(contract: PlotContract) -> list[str]:
    lines = ["## Templates", ""]
    if contract.qa_profiles:
        lines.extend(["## QA Profiles", ""])
        for name, profile in contract.qa_profiles.items():
            tokens = ", ".join(f"`{key}`={value!r}" for key, value in profile.items())
            lines.append(f"- `{name}`: {tokens}")
        lines.append("")
    for name, spec in contract.templates.items():
        lines.extend(
            [
                f"### `{name}` / {spec.label}",
                "",
                f"- Category: `{spec.category}`",
                f"- Presentation kind: `{spec.presentation_kind}`",
                f"- Default size: `{spec.default_size}`",
                (
                    "- Allowed sizes: "
                    + ", ".join(f"`{item}`" for item in spec.allowed_sizes)
                ),
                (
                    "- Editable options: "
                    + ", ".join(f"`{item}`" for item in spec.editable_options)
                ),
                f"- Description: {spec.description}",
                (
                    "- Hard rules: "
                    + (", ".join(f"`{item}`" for item in spec.hard_rules) or "None")
                ),
                (
                    "- Soft rules: "
                    + (", ".join(f"`{item}`" for item in spec.soft_rules) or "None")
                ),
                "",
            ]
        )
    return lines


def render_contract_markdown(contract: PlotContract | None = None) -> str:
    """Render the complete plot contract as deterministic Markdown."""

    resolved = contract or load_plot_contract()
    lines = [
        *_global_policy_markdown(resolved),
        *_style_markdown(resolved),
        *_template_markdown(resolved),
        "## Validation Rules",
        "",
    ]
    for name, rule in resolved.validation_rules.items():
        tolerance = (
            f", tolerance `{rule.tolerance_mm:.2f} mm`"
            if rule.tolerance_mm is not None
            else ""
        )
        lines.append(
            f"- `{name}`: {rule.label} ({rule.severity}{tolerance}) - "
            f"{rule.description}"
        )
    return "\n".join(lines) + "\n"


def write_contract_markdown(path: Path | None = None) -> Path:
    """Write the deterministic Markdown contract to a requested location."""

    destination = path or DOC_PATH
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_contract_markdown(), encoding="utf-8")
    return destination


__all__ = [
    "DOC_PATH",
    "capability_catalog_payload",
    "meta_payload",
    "render_contract_markdown",
    "write_contract_markdown",
]
