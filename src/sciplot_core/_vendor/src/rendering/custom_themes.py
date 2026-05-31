from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from src import plot_style
from src.rendering.themes import publication_profile_protected_rcparams, visual_theme_ids

_THEME_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*(/[A-Za-z0-9][A-Za-z0-9_.-]*)?$")
_HEX_PATTERN = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")

ALLOWED_EXPERT_RCPARAMS: frozenset[str] = frozenset(
    {
        "axes.facecolor",
        "axes.edgecolor",
        "axes.grid",
        "axes.labelcolor",
        "figure.facecolor",
        "grid.alpha",
        "grid.color",
        "grid.linestyle",
        "legend.edgecolor",
        "legend.facecolor",
        "legend.fancybox",
        "legend.frameon",
        "text.color",
        "xtick.color",
        "ytick.color",
    }
)

_ALLOWED_HARD_OVERRIDES: dict[str, frozenset[str]] = {
    "typography": frozenset(
        {
            "font_size_pt",
            "legend_font_size_pt",
            "panel_label_size_pt",
            "panel_label_weight",
        }
    ),
    "stroke": frozenset(
        {
            "axis_linewidth_pt",
            "tick_width_pt",
            "tick_length_pt",
            "minor_tick_width_pt",
            "minor_tick_length_pt",
            "line_width_pt",
            "line_alpha",
            "marker_alpha",
            "fill_alpha",
            "max_fill_alpha",
            "marker_size_pt",
        }
    ),
    "spacing": frozenset(
        {
            "axes_labelpad",
            "xtick_major_pad",
            "ytick_major_pad",
            "legend_inset_fraction",
        }
    ),
    "annotation": frozenset({"legend_frameon", "legend_tightness", "label_tightness"}),
}


@dataclass(frozen=True)
class CustomThemePackage:
    id: str
    label: str
    base_style_id: str
    palette_preset: str | None = None
    visual_theme_id: str | None = None
    palette: dict[str, Any] | None = None
    hard_overrides: dict[str, dict[str, Any]] | None = None
    soft_overrides: dict[str, Any] | None = None
    expert_rcparams: dict[str, Any] | None = None


@dataclass(frozen=True)
class NormalizedCustomThemePackage:
    package: CustomThemePackage
    blocked_keys: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


def _mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _string(value: object, *, fallback: str = "") -> str:
    if value is None:
        return fallback
    return str(value).strip() or fallback


def _validate_theme_id(theme_id: str) -> str:
    if not _THEME_ID_PATTERN.match(theme_id):
        raise ValueError(
            "Custom theme id must use letters, numbers, dots, dashes, underscores, and one optional slash."
        )
    if theme_id in plot_style.list_style_presets():
        raise ValueError("Custom theme id cannot overwrite a built-in style preset.")
    return theme_id


def _normalize_base_style(value: object) -> str:
    base_style_id = plot_style.normalize_style_preset(_string(value, fallback=plot_style.DEFAULT_STYLE_PRESET))
    if base_style_id not in plot_style.list_public_style_presets():
        raise ValueError(f"Unknown base style for custom theme: {base_style_id}.")
    return base_style_id


def _normalize_palette_preset(value: object) -> str | None:
    if value is None:
        return None
    palette_id = _string(value)
    if not palette_id:
        return None
    if palette_id not in plot_style.list_palette_presets():
        raise ValueError(f"Unknown palette preset for custom theme: {palette_id}.")
    return palette_id


def _normalize_visual_theme(value: object) -> str | None:
    if value is None:
        return None
    theme_id = _string(value)
    if not theme_id:
        return None
    if theme_id not in visual_theme_ids():
        raise ValueError(f"Unknown visual theme for custom theme: {theme_id}.")
    return theme_id


def _normalize_palette(value: object) -> dict[str, Any]:
    payload = dict(_mapping(value))
    categorical = payload.get("categorical")
    if categorical is None:
        return {}
    if not isinstance(categorical, list) or not categorical:
        raise ValueError("Custom theme palette.categorical must be a non-empty list of hex colors.")
    colors: list[str] = []
    for item in categorical:
        color = _string(item)
        if not _HEX_PATTERN.match(color):
            raise ValueError(f"Invalid custom theme hex color: {color}.")
        colors.append(color)
    return {"categorical": colors}


def _normalize_hard_overrides(value: object) -> tuple[dict[str, dict[str, Any]], tuple[str, ...]]:
    payload = _mapping(value)
    normalized: dict[str, dict[str, Any]] = {}
    blocked: list[str] = []
    for group, group_value in payload.items():
        group_name = str(group)
        allowed = _ALLOWED_HARD_OVERRIDES.get(group_name)
        if allowed is None:
            blocked.append(group_name)
            continue
        group_map = _mapping(group_value)
        group_result: dict[str, Any] = {}
        for key, raw_value in group_map.items():
            key_text = str(key)
            if key_text not in allowed:
                blocked.append(f"{group_name}.{key_text}")
                continue
            if isinstance(raw_value, (str, bool)):
                group_result[key_text] = raw_value
            elif isinstance(raw_value, (int, float)):
                group_result[key_text] = float(raw_value)
            else:
                blocked.append(f"{group_name}.{key_text}")
        if group_result:
            normalized[group_name] = group_result
    return normalized, tuple(sorted(blocked))


def _normalize_rcparams(
    value: object,
    *,
    base_style_id: str,
    require_allowlist: bool,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    payload = _mapping(value)
    protected = set(publication_profile_protected_rcparams(base_style_id))
    normalized: dict[str, Any] = {}
    blocked: list[str] = []
    for key, raw_value in payload.items():
        key_text = str(key)
        if key_text in protected:
            blocked.append(key_text)
            continue
        if require_allowlist and key_text not in ALLOWED_EXPERT_RCPARAMS:
            blocked.append(key_text)
            continue
        if isinstance(raw_value, (str, bool, int, float)):
            normalized[key_text] = raw_value
        else:
            blocked.append(key_text)
    return normalized, tuple(sorted(blocked))


def normalize_custom_theme_package(value: object) -> NormalizedCustomThemePackage:
    payload = _mapping(value)
    theme_id = _validate_theme_id(_string(payload.get("id")))
    label = _string(payload.get("label"), fallback=theme_id.rsplit("/", maxsplit=1)[-1])
    base_style_id = _normalize_base_style(payload.get("base_style_id"))
    palette_preset = _normalize_palette_preset(payload.get("palette_preset"))
    visual_theme_id = _normalize_visual_theme(payload.get("visual_theme_id"))
    palette = _normalize_palette(payload.get("palette"))
    hard_overrides, blocked_hard = _normalize_hard_overrides(payload.get("hard_overrides"))
    soft_overrides, blocked_soft = _normalize_rcparams(
        payload.get("soft_overrides"),
        base_style_id=base_style_id,
        require_allowlist=False,
    )
    expert_rcparams, blocked_expert = _normalize_rcparams(
        payload.get("expert_rcparams"),
        base_style_id=base_style_id,
        require_allowlist=True,
    )
    blocked_keys = tuple(sorted({*blocked_hard, *blocked_soft, *blocked_expert}))
    warnings = (
        (f"Blocked unsupported or protected custom theme keys: {', '.join(blocked_keys)}.",)
        if blocked_keys
        else ()
    )
    return NormalizedCustomThemePackage(
        package=CustomThemePackage(
            id=theme_id,
            label=label,
            base_style_id=base_style_id,
            palette_preset=palette_preset,
            visual_theme_id=visual_theme_id,
            palette=palette,
            hard_overrides=hard_overrides,
            soft_overrides=soft_overrides,
            expert_rcparams=expert_rcparams,
        ),
        blocked_keys=blocked_keys,
        warnings=warnings,
    )


def custom_theme_to_payload(theme: CustomThemePackage) -> dict[str, Any]:
    return {
        "id": theme.id,
        "label": theme.label,
        "base_style_id": theme.base_style_id,
        "palette_preset": theme.palette_preset,
        "visual_theme_id": theme.visual_theme_id,
        "palette": dict(theme.palette or {}),
        "hard_overrides": {key: dict(value) for key, value in (theme.hard_overrides or {}).items()},
        "soft_overrides": dict(theme.soft_overrides or {}),
        "expert_rcparams": dict(theme.expert_rcparams or {}),
    }


def custom_theme_summary_payload(theme: CustomThemePackage, *, builtin: bool = False) -> dict[str, Any]:
    palette = dict(theme.palette or {})
    return {
        "id": theme.id,
        "label": theme.label,
        "builtin": builtin,
        "base_style_id": theme.base_style_id,
        "palette_preset": theme.palette_preset,
        "visual_theme_id": theme.visual_theme_id,
        "swatches": list(palette.get("categorical", ())[:6]) if isinstance(palette.get("categorical"), list) else [],
    }


__all__ = [
    "ALLOWED_EXPERT_RCPARAMS",
    "CustomThemePackage",
    "NormalizedCustomThemePackage",
    "custom_theme_summary_payload",
    "custom_theme_to_payload",
    "normalize_custom_theme_package",
]
