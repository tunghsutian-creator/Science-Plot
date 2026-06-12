from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from src import plot_style
from src.plot_contract import (
    default_options_for_template,
    size_preset_contract,
    style_contract,
    template_contract,
)
from src.rendering.analytical_layers import normalize_analytical_layers_payload
from src.rendering.axis_breaks import normalize_axis_breaks_payload
from src.rendering.constants import DEFAULT_SIZE_BY_TEMPLATE, LEGACY_TEMPLATE_HINTS, TEMPLATE_CHOICES
from src.rendering.data_transforms import normalize_data_transforms_payload
from src.rendering.extra_axes import normalize_extra_axis_payload
from src.rendering.models import RenderOptions
from src.rendering.reference_guides import normalize_reference_guides_payload
from src.rendering.series_offsets import normalize_series_offsets_payload
from src.rendering.series_styles import normalize_series_styles_payload
from src.rendering.shape_annotations import normalize_shape_annotations_payload
from src.rendering.template_lifecycle import is_supported_template_id, resolve_template_id
from src.rendering.text_annotations import normalize_text_annotations_payload
from src.rendering.themes import visual_theme_ids

_VALID_TICK_DENSITIES = frozenset({"auto", "sparse", "dense"})
_VALID_TICK_EDGE_LABELS = frozenset({"auto", "hide_min", "hide_max", "hide_both"})
_VALID_LEGEND_POSITIONS = frozenset({"auto", "upper_left", "upper_right", "lower_left", "lower_right"})
_VALID_SERIES_LABEL_MODES = frozenset({"legend", "inline"})


def validate_template_name(template: str) -> str:
    if template in LEGACY_TEMPLATE_HINTS:
        raise ValueError(f"Legacy template name `{template}` is no longer supported. {LEGACY_TEMPLATE_HINTS[template]}")
    if not is_supported_template_id(template):
        raise ValueError(f"Unknown template: {template}. Supported templates: {', '.join(TEMPLATE_CHOICES)}")
    return template


def resolve_size(
    size_text: str | None,
    template: str,
    *,
    resolved_template_id: str | None = None,
) -> tuple[float, float]:
    effective_template = resolved_template_id or resolve_template_id(template)
    chosen = size_text or DEFAULT_SIZE_BY_TEMPLATE[effective_template]
    try:
        size_spec = size_preset_contract(chosen)
    except ValueError as exc:
        available = ", ".join(
            size_preset_contract(size_id).label
            for size_id in template_contract(effective_template).allowed_sizes
        )
        raise ValueError(
            f"Unknown figure size `{chosen}` for template `{template}`. Supported sizes: {available}"
        ) from exc
    return size_spec.width_mm, size_spec.height_mm


def _ensure_template_option_supported(
    template: str,
    option_id: str,
    *,
    resolved_template_id: str | None = None,
) -> None:
    spec = template_contract(resolved_template_id or resolve_template_id(template))
    if option_id not in spec.editable_options:
        raise ValueError(
            f"Template `{template}` does not support option `{option_id}`. "
            f"Supported editable options: {', '.join(spec.editable_options)}"
        )


def _normalize_manual_bound(
    template: str,
    option_id: str,
    value: float | None,
    *,
    resolved_template_id: str | None = None,
) -> float | None:
    if value is None:
        return None
    _ensure_template_option_supported(template, option_id, resolved_template_id=resolved_template_id)
    numeric = float(value)
    if not math.isfinite(numeric):
        raise ValueError(f"`{option_id}` must be a finite number.")
    return numeric


def _normalize_fraction_option(
    template: str,
    option_id: str,
    value: object,
    *,
    resolved_template_id: str | None = None,
) -> float | None:
    if value is None or value == "":
        return None
    _ensure_template_option_supported(template, option_id, resolved_template_id=resolved_template_id)
    try:
        numeric = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"`{option_id}` must be a finite non-negative number.") from exc
    if not math.isfinite(numeric) or numeric < 0:
        raise ValueError(f"`{option_id}` must be a finite non-negative number.")
    return numeric


def _normalize_series_order(
    template: str,
    series_order: list[str] | tuple[str, ...] | None,
    *,
    resolved_template_id: str | None = None,
) -> tuple[str, ...] | None:
    if series_order is None:
        return None
    _ensure_template_option_supported(template, "series_order", resolved_template_id=resolved_template_id)
    cleaned: list[str] = []
    seen: set[str] = set()
    for item in series_order:
        label = str(item).strip()
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(label)
    return tuple(cleaned) if cleaned else None


def _normalize_legend_position(
    template: str,
    value: str | None,
    *,
    resolved_template_id: str | None = None,
) -> str:
    if value is None:
        return "auto"
    cleaned = str(value).strip().lower()
    if not cleaned:
        return "auto"
    if cleaned not in _VALID_LEGEND_POSITIONS:
        raise ValueError(
            f"`legend_position` must be one of {', '.join(sorted(_VALID_LEGEND_POSITIONS))}."
        )
    if cleaned != "auto":
        _ensure_template_option_supported(template, "legend_position", resolved_template_id=resolved_template_id)
    return cleaned


def _normalize_series_label_mode(
    template: str,
    value: str | None,
    *,
    resolved_template_id: str | None = None,
) -> str:
    if value is None:
        return "legend"
    cleaned = str(value).strip().lower()
    if cleaned in {"", "auto"}:
        return "legend"
    if cleaned in {"edge", "direct", "direct_labels"}:
        _ensure_template_option_supported(template, "series_label_mode", resolved_template_id=resolved_template_id)
        return "inline"
    if cleaned not in _VALID_SERIES_LABEL_MODES:
        raise ValueError(
            f"`series_label_mode` must be one of {', '.join(sorted(_VALID_SERIES_LABEL_MODES))}."
        )
    if cleaned != "legend":
        _ensure_template_option_supported(template, "series_label_mode", resolved_template_id=resolved_template_id)
    return cleaned


def _normalize_label_override(value: str | None) -> str | None:
    if value is None:
        return None
    cleaned = str(value).strip()
    return cleaned or None


def _normalize_enumerated_option(
    template: str,
    option_id: str,
    value: str | None,
    *,
    allowed: frozenset[str],
    resolved_template_id: str | None = None,
) -> str | None:
    if value is None:
        return None
    _ensure_template_option_supported(template, option_id, resolved_template_id=resolved_template_id)
    cleaned = str(value).strip().lower()
    if not cleaned or cleaned == "auto":
        return None
    if cleaned not in allowed:
        raise ValueError(
            f"`{option_id}` must be one of {', '.join(sorted(allowed))}."
        )
    return cleaned


def _has_enabled_axis_breaks(value: tuple[Mapping[str, object], ...] | None) -> bool:
    if value is None:
        return False
    return any(bool(item.get("enabled", True)) for item in value)


def _axis_break_display_modes(value: tuple[Mapping[str, object], ...] | None) -> tuple[str, ...]:
    if value is None:
        return ()
    modes = {str(item.get("display_mode", "compress")).strip().lower() or "compress" for item in value}
    return tuple(sorted(modes))


def resolve_render_options(
    *,
    template: str,
    size: str | None = None,
    xscale: str | None = None,
    yscale: str | None = None,
    reverse_x: bool | None = None,
    x_min: float | None = None,
    x_max: float | None = None,
    y_min: float | None = None,
    y_max: float | None = None,
    x_padding_fraction: float | None = None,
    x_tick_density: str | None = None,
    y_tick_density: str | None = None,
    x_tick_edge_labels: str | None = None,
    y_tick_edge_labels: str | None = None,
    series_order: list[str] | tuple[str, ...] | None = None,
    series_styles: object | None = None,
    series_offsets: object | None = None,
    legend_position: str | None = None,
    series_label_mode: str | None = None,
    x_label_override: str | None = None,
    y_label_override: str | None = None,
    baseline: str | None = None,
    show_colorbar: bool | None = None,
    style_preset: str | None = None,
    palette_preset: str | None = None,
    use_sidecar: bool | None = None,
    visual_theme_id: str | None = None,
    custom_theme_id: str | None = None,
    custom_theme_draft: object | None = None,
    extra_x_axis: object | None = None,
    extra_y_axis: object | None = None,
    x_axis_breaks: object | None = None,
    y_axis_breaks: object | None = None,
    reference_guides: object | None = None,
    reference_line: object | None = None,
    reference_band: object | None = None,
    text_annotations: object | None = None,
    shape_annotations: object | None = None,
    analytical_layers: object | None = None,
    data_variables: object | None = None,
    data_transforms: object | None = None,
    resolved_template_id: str | None = None,
) -> RenderOptions:
    contract_template = resolved_template_id or resolve_template_id(template)
    width_mm, height_mm = resolve_size(size, template, resolved_template_id=contract_template)
    spec = template_contract(contract_template)
    defaults = default_options_for_template(contract_template)
    normalized_style = plot_style.normalize_style_preset(style_preset or defaults.get("style_preset"))
    if normalized_style not in spec.available_styles:
        raise ValueError(
            f"Template `{template}` does not support style `{normalized_style}`. "
            f"Supported styles: {', '.join(spec.available_styles)}"
        )
    style_defaults = style_contract(normalized_style)
    resolved_palette = palette_preset
    if resolved_palette is None and style_preset is not None:
        recommended_palette = style_defaults.recommended_palette_preset
        if recommended_palette in spec.available_palettes:
            resolved_palette = recommended_palette
    if resolved_palette is None:
        resolved_palette = defaults.get("palette_preset", plot_style.DEFAULT_PALETTE_PRESET)
    if resolved_palette not in spec.available_palettes:
        raise ValueError(
            f"Template `{template}` does not support palette `{resolved_palette}`. "
            f"Supported palettes: {', '.join(spec.available_palettes)}"
        )
    resolved_theme: str | None
    if isinstance(visual_theme_id, str):
        resolved_theme = visual_theme_id.strip()
    elif style_preset is not None and style_defaults.recommended_visual_theme_id is not None:
        resolved_theme = str(style_defaults.recommended_visual_theme_id).strip()
    else:
        default_theme = defaults.get("visual_theme_id")
        resolved_theme = str(default_theme).strip() if default_theme is not None else None
    if resolved_theme and resolved_theme not in visual_theme_ids():
        raise ValueError(
            f"Unknown visual theme: {resolved_theme}. Supported themes: {', '.join(visual_theme_ids())}"
        )
    resolved_xscale = xscale or defaults.get("xscale", "linear")
    resolved_yscale = yscale or defaults.get("yscale", "linear")
    resolved_extra_x_axis = normalize_extra_axis_payload(extra_x_axis, axis_name="x")
    if resolved_extra_x_axis is not None and "extra_x_axis" not in spec.editable_options:
        raise ValueError(f"Template `{template}` does not support option `extra_x_axis`.")
    resolved_extra_y_axis = normalize_extra_axis_payload(extra_y_axis, axis_name="y")
    if resolved_extra_y_axis is not None and "extra_y_axis" not in spec.editable_options:
        raise ValueError(f"Template `{template}` does not support option `extra_y_axis`.")
    if (
        resolved_extra_y_axis is not None
        and resolved_extra_y_axis["binding_mode"] == "series_assignment"
        and contract_template not in {"curve", "point_line", "scatter"}
    ):
        raise ValueError(
            f"Template `{template}` does not support extra_y_axis.binding_mode `series_assignment`."
        )
    resolved_x_axis_breaks = normalize_axis_breaks_payload(x_axis_breaks, axis_name="x")
    if resolved_x_axis_breaks is not None and "x_axis_breaks" not in spec.editable_options:
        raise ValueError(f"Template `{template}` does not support option `x_axis_breaks`.")
    resolved_y_axis_breaks = normalize_axis_breaks_payload(y_axis_breaks, axis_name="y")
    if resolved_y_axis_breaks is not None and "y_axis_breaks" not in spec.editable_options:
        raise ValueError(f"Template `{template}` does not support option `y_axis_breaks`.")
    x_break_modes = _axis_break_display_modes(resolved_x_axis_breaks)
    y_break_modes = _axis_break_display_modes(resolved_y_axis_breaks)
    if len(x_break_modes) > 1:
        raise ValueError("`x_axis_breaks` must share a single `display_mode`.")
    if len(y_break_modes) > 1:
        raise ValueError("`y_axis_breaks` must share a single `display_mode`.")
    if _has_enabled_axis_breaks(resolved_x_axis_breaks) and resolved_xscale != "linear":
        raise ValueError("`x_axis_breaks` are available on linear X axes only.")
    if _has_enabled_axis_breaks(resolved_y_axis_breaks) and resolved_yscale != "linear":
        raise ValueError("`y_axis_breaks` are available on linear Y axes only.")
    has_split_x_breaks = _has_enabled_axis_breaks(resolved_x_axis_breaks) and x_break_modes == ("split",)
    has_split_y_breaks = _has_enabled_axis_breaks(resolved_y_axis_breaks) and y_break_modes == ("split",)
    if has_split_x_breaks and _has_enabled_axis_breaks(resolved_y_axis_breaks):
        raise ValueError("Split broken X axes cannot be combined with active broken Y axes in this release.")
    if has_split_y_breaks and _has_enabled_axis_breaks(resolved_x_axis_breaks):
        raise ValueError("Split broken Y axes cannot be combined with active broken X axes in this release.")
    if (
        _has_enabled_axis_breaks(resolved_x_axis_breaks)
        or _has_enabled_axis_breaks(resolved_y_axis_breaks)
    ) and (
        bool(resolved_extra_x_axis and resolved_extra_x_axis.get("enabled", False))
        or bool(resolved_extra_y_axis and resolved_extra_y_axis.get("enabled", False))
    ):
        raise ValueError("Axis breaks cannot be combined with extra axes in this release.")
    resolved_analytical_layers = normalize_analytical_layers_payload(analytical_layers)
    if resolved_analytical_layers is not None and "analytical_layers" not in spec.editable_options:
        raise ValueError(f"Template `{template}` does not support option `analytical_layers`.")
    resolved_series_styles = normalize_series_styles_payload(series_styles)
    if resolved_series_styles is not None and "series_styles" not in spec.editable_options:
        raise ValueError(f"Template `{template}` does not support option `series_styles`.")
    resolved_series_offsets = normalize_series_offsets_payload(series_offsets)
    if resolved_series_offsets is not None and "series_offsets" not in spec.editable_options:
        raise ValueError(f"Template `{template}` does not support option `series_offsets`.")
    if data_variables is not None:
        if not isinstance(data_variables, Sequence) or isinstance(data_variables, (str, bytes, bytearray)):
            raise ValueError("`data_variables` must be a list of mappings.")
        resolved_data_variables = tuple(dict(item) for item in data_variables)
    else:
        resolved_data_variables = None
    resolved_data_transforms = normalize_data_transforms_payload(data_transforms)
    return RenderOptions(
        width_mm=width_mm,
        height_mm=height_mm,
        xscale=resolved_xscale,
        yscale=resolved_yscale,
        reverse_x=bool(defaults.get("reverse_x", False)) if reverse_x is None else reverse_x,
        baseline=baseline or defaults.get("baseline", "none"),
        show_colorbar=defaults.get("show_colorbar", True) if show_colorbar is None else show_colorbar,
        style_preset=normalized_style,
        palette_preset=resolved_palette,
        x_min=_normalize_manual_bound(template, "x_min", x_min, resolved_template_id=contract_template),
        x_max=_normalize_manual_bound(template, "x_max", x_max, resolved_template_id=contract_template),
        y_min=_normalize_manual_bound(template, "y_min", y_min, resolved_template_id=contract_template),
        y_max=_normalize_manual_bound(template, "y_max", y_max, resolved_template_id=contract_template),
        x_padding_fraction=_normalize_fraction_option(
            template,
            "x_padding_fraction",
            x_padding_fraction,
            resolved_template_id=contract_template,
        ),
        x_tick_density=_normalize_enumerated_option(
            template,
            "x_tick_density",
            x_tick_density,
            allowed=_VALID_TICK_DENSITIES,
            resolved_template_id=contract_template,
        ),
        y_tick_density=_normalize_enumerated_option(
            template,
            "y_tick_density",
            y_tick_density,
            allowed=_VALID_TICK_DENSITIES,
            resolved_template_id=contract_template,
        ),
        x_tick_edge_labels=_normalize_enumerated_option(
            template,
            "x_tick_edge_labels",
            x_tick_edge_labels,
            allowed=_VALID_TICK_EDGE_LABELS,
            resolved_template_id=contract_template,
        ),
        y_tick_edge_labels=_normalize_enumerated_option(
            template,
            "y_tick_edge_labels",
            y_tick_edge_labels,
            allowed=_VALID_TICK_EDGE_LABELS,
            resolved_template_id=contract_template,
        ),
        series_order=_normalize_series_order(
            template,
            series_order,
            resolved_template_id=contract_template,
        ),
        series_styles=resolved_series_styles,
        series_offsets=resolved_series_offsets,
        legend_position=_normalize_legend_position(
            template,
            legend_position,
            resolved_template_id=contract_template,
        ),
        series_label_mode=_normalize_series_label_mode(
            template,
            series_label_mode,
            resolved_template_id=contract_template,
        ),
        x_label_override=_normalize_label_override(x_label_override),
        y_label_override=_normalize_label_override(y_label_override),
        use_sidecar=use_sidecar,
        visual_theme_id=resolved_theme or None,
        custom_theme_id=str(custom_theme_id).strip() if custom_theme_id else None,
        custom_theme_draft=dict(custom_theme_draft) if isinstance(custom_theme_draft, dict) else None,
        extra_x_axis=resolved_extra_x_axis,
        extra_y_axis=resolved_extra_y_axis,
        x_axis_breaks=resolved_x_axis_breaks,
        y_axis_breaks=resolved_y_axis_breaks,
        reference_guides=normalize_reference_guides_payload(
            reference_guides,
            legacy_line=reference_line,
            legacy_band=reference_band,
        ),
        text_annotations=normalize_text_annotations_payload(text_annotations),
        shape_annotations=normalize_shape_annotations_payload(shape_annotations),
        analytical_layers=resolved_analytical_layers,
        data_variables=resolved_data_variables,
        data_transforms=resolved_data_transforms,
    )


__all__ = [
    "resolve_render_options",
    "resolve_size",
    "validate_template_name",
]
