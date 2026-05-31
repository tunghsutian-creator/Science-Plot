from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, dataclass, fields, is_dataclass
from typing import Any

from src import plot_style


@dataclass(frozen=True)
class VisualThemeSpec:
    label: str
    description: str
    soft_overrides: dict[str, Any]


# Publication-critical sizing/stroke/export knobs must remain contract-owned.
_PROTECTED_RCPARAM_KEYS: frozenset[str] = frozenset(
    {
        "figure.dpi",
        "savefig.dpi",
        "savefig.format",
        "pdf.fonttype",
        "ps.fonttype",
        "font.family",
        "font.sans-serif",
        "font.size",
        "axes.labelsize",
        "axes.titlesize",
        "xtick.labelsize",
        "ytick.labelsize",
        "legend.fontsize",
        "axes.labelpad",
        "xtick.major.pad",
        "ytick.major.pad",
        "axes.linewidth",
        "xtick.major.width",
        "ytick.major.width",
        "xtick.major.size",
        "ytick.major.size",
        "xtick.minor.width",
        "ytick.minor.width",
        "xtick.minor.size",
        "ytick.minor.size",
        "lines.linewidth",
        "lines.markersize",
        "axes.spines.left",
        "axes.spines.bottom",
        "axes.spines.top",
        "axes.spines.right",
    }
)


def _flatten_keys(value: Any, *, prefix: str = "") -> tuple[str, ...]:
    keys: list[str] = []
    if is_dataclass(value) and not isinstance(value, type):
        for field in fields(value):
            child = getattr(value, field.name)
            path = f"{prefix}.{field.name}" if prefix else field.name
            if is_dataclass(child) and not isinstance(child, type):
                keys.extend(_flatten_keys(child, prefix=path))
            elif isinstance(child, Mapping):
                for child_key, child_value in child.items():
                    nested = f"{path}.{child_key}"
                    if is_dataclass(child_value) and not isinstance(child_value, type):
                        keys.extend(_flatten_keys(child_value, prefix=nested))
                    else:
                        keys.append(nested)
            else:
                keys.append(path)
    return tuple(keys)


def publication_profile_hard_constraints(publication_profile_id: str) -> dict[str, Any]:
    spec = plot_style.get_style_spec(publication_profile_id)
    return asdict(spec)


def publication_profile_protected_keys(publication_profile_id: str) -> tuple[str, ...]:
    spec = plot_style.get_style_spec(publication_profile_id)
    return _flatten_keys(spec)


def publication_profile_protected_rcparams(publication_profile_id: str) -> tuple[str, ...]:
    # The set is currently style-agnostic, but the profile id keeps the callsite
    # contract explicit: protected keys are tied to publication profiles.
    _ = publication_profile_id
    return tuple(sorted(_PROTECTED_RCPARAM_KEYS))


_VISUAL_THEMES: dict[str, VisualThemeSpec] = {
    "clean_light": VisualThemeSpec(
        label="Clean Light",
        description="A minimal publication surface with plain white panels, dark ink, and no visible grid.",
        soft_overrides={
            "axes.facecolor": "#ffffff",
            "figure.facecolor": "#ffffff",
            "axes.edgecolor": "#111827",
            "axes.labelcolor": "#111827",
            "xtick.color": "#111827",
            "ytick.color": "#111827",
            "text.color": "#111827",
            "axes.grid": False,
            "grid.alpha": 0.0,
            "legend.frameon": False,
        },
    ),
    "soft_grid": VisualThemeSpec(
        label="Soft Grid",
        description="A quiet technical surface with cool paper tones and restrained grid scaffolding.",
        soft_overrides={
            "axes.facecolor": "#fbfcfe",
            "figure.facecolor": "#f5f8fb",
            "axes.edgecolor": "#475569",
            "axes.labelcolor": "#334155",
            "xtick.color": "#334155",
            "ytick.color": "#334155",
            "text.color": "#1f2937",
            "axes.grid": True,
            "grid.alpha": 0.22,
            "grid.color": "#d7e1eb",
            "grid.linestyle": "-",
            "legend.facecolor": "#ffffff",
            "legend.edgecolor": "#d7e1eb",
            "legend.frameon": True,
        },
    ),
    "presentation_like": VisualThemeSpec(
        label="Presentation Like",
        description="A slide-friendly surface with airy mint panels and clearer contrast around the plotting frame.",
        soft_overrides={
            "axes.facecolor": "#fbfffd",
            "figure.facecolor": "#eef8f3",
            "axes.edgecolor": "#235246",
            "axes.labelcolor": "#173d34",
            "xtick.color": "#173d34",
            "ytick.color": "#173d34",
            "text.color": "#173d34",
            "axes.grid": True,
            "grid.alpha": 0.18,
            "grid.color": "#bfdccf",
            "grid.linestyle": "-",
            "legend.frameon": True,
            "legend.fancybox": True,
            "legend.facecolor": "#f7fffb",
            "legend.edgecolor": "#bfdccf",
        },
    ),
    "infographic": VisualThemeSpec(
        label="Infographic",
        description="A brighter editorial surface with warm paper tones and a visible information-design grid.",
        soft_overrides={
            "axes.facecolor": "#fffdf8",
            "figure.facecolor": "#fff5e8",
            "axes.edgecolor": "#8b5e34",
            "axes.labelcolor": "#7c5128",
            "xtick.color": "#7c5128",
            "ytick.color": "#7c5128",
            "text.color": "#6f451f",
            "axes.grid": True,
            "grid.alpha": 0.2,
            "grid.color": "#d8bf93",
            "grid.linestyle": "-",
            "legend.frameon": True,
            "legend.fancybox": True,
            "legend.facecolor": "#fffaf0",
            "legend.edgecolor": "#d8bf93",
        },
    ),
    "roma": VisualThemeSpec(
        label="Roma",
        description="A warm editorial surface with quiet cream panels, no grid, and subtle legend cards.",
        soft_overrides={
            "axes.facecolor": "#fffaf6",
            "figure.facecolor": "#f6eee7",
            "axes.edgecolor": "#6b4f43",
            "axes.labelcolor": "#5b4338",
            "xtick.color": "#5b4338",
            "ytick.color": "#5b4338",
            "text.color": "#503b31",
            "axes.grid": False,
            "grid.alpha": 0.0,
            "legend.frameon": True,
            "legend.fancybox": True,
            "legend.facecolor": "#fff8f2",
            "legend.edgecolor": "#d8c0b1",
        },
    ),
    "macarons": VisualThemeSpec(
        label="Macarons",
        description="A cooler pastel surface with soft blue paper tones and delicate legend chrome.",
        soft_overrides={
            "axes.facecolor": "#fcfdff",
            "figure.facecolor": "#f1f7ff",
            "axes.edgecolor": "#56708f",
            "axes.labelcolor": "#48627e",
            "xtick.color": "#48627e",
            "ytick.color": "#48627e",
            "text.color": "#3f5872",
            "axes.grid": True,
            "grid.alpha": 0.17,
            "grid.color": "#cadcf2",
            "grid.linestyle": "-",
            "legend.frameon": True,
            "legend.fancybox": True,
            "legend.facecolor": "#fcfdff",
            "legend.edgecolor": "#cadcf2",
        },
    ),
    "shine": VisualThemeSpec(
        label="Shine",
        description="A crisp display surface with cool blue panels, clear grid guidance, and brighter chrome.",
        soft_overrides={
            "axes.facecolor": "#fbfdff",
            "figure.facecolor": "#edf6ff",
            "axes.edgecolor": "#1d4e89",
            "axes.labelcolor": "#163f72",
            "xtick.color": "#163f72",
            "ytick.color": "#163f72",
            "text.color": "#16365f",
            "axes.grid": True,
            "grid.alpha": 0.22,
            "grid.color": "#b6d0ea",
            "grid.linestyle": "-",
            "legend.frameon": True,
            "legend.fancybox": True,
            "legend.facecolor": "#fbfdff",
            "legend.edgecolor": "#b6d0ea",
        },
    ),
    "vintage": VisualThemeSpec(
        label="Vintage",
        description="A warm paper-tone surface with sepia text, gentle grid lines, and a printed-poster feel.",
        soft_overrides={
            "axes.facecolor": "#fffaf1",
            "figure.facecolor": "#f9f0e3",
            "axes.edgecolor": "#7b5e46",
            "axes.labelcolor": "#6f523c",
            "xtick.color": "#6f523c",
            "ytick.color": "#6f523c",
            "text.color": "#614733",
            "axes.grid": True,
            "grid.alpha": 0.18,
            "grid.color": "#d8c8aa",
            "grid.linestyle": "-",
            "legend.frameon": True,
            "legend.fancybox": True,
            "legend.facecolor": "#fff7ec",
            "legend.edgecolor": "#d8c8aa",
        },
    ),
}


def visual_theme_ids() -> tuple[str, ...]:
    return tuple(_VISUAL_THEMES.keys())


def visual_theme_spec(visual_theme_id: str) -> VisualThemeSpec:
    try:
        return _VISUAL_THEMES[visual_theme_id]
    except KeyError as exc:
        raise ValueError(f"Unknown visual theme: {visual_theme_id}.") from exc


def visual_theme_soft_overrides(visual_theme_id: str | None) -> dict[str, Any]:
    if visual_theme_id is None:
        return {}
    return dict(visual_theme_spec(visual_theme_id).soft_overrides)


def sanitized_visual_theme_soft_overrides(
    publication_profile_id: str,
    visual_theme_id: str | None,
) -> tuple[dict[str, Any], tuple[str, ...]]:
    raw_overrides = visual_theme_soft_overrides(visual_theme_id)
    if not raw_overrides:
        return {}, ()
    blocked = set(publication_profile_protected_rcparams(publication_profile_id))
    resolved = {key: value for key, value in raw_overrides.items() if key not in blocked}
    blocked_keys = tuple(sorted(key for key in raw_overrides if key in blocked))
    return resolved, blocked_keys


def visual_theme_catalog_payload() -> list[dict[str, Any]]:
    return [
        {
            "id": theme_id,
            "label": spec.label,
            "description": spec.description,
        }
        for theme_id, spec in _VISUAL_THEMES.items()
    ]


__all__ = [
    "publication_profile_hard_constraints",
    "publication_profile_protected_keys",
    "publication_profile_protected_rcparams",
    "sanitized_visual_theme_soft_overrides",
    "visual_theme_catalog_payload",
    "visual_theme_ids",
    "visual_theme_soft_overrides",
    "visual_theme_spec",
]
