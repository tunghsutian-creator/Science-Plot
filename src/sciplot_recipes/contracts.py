from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RecipeSpec:
    name: str
    label: str
    default_template: str
    module_name: str


_RECIPE_SPECS: dict[str, tuple[str, str, str]] = {
    "tensile": ("tensile", "Tensile", "curve"),
    "stress_relaxation": (
        "stress_relaxation",
        "Stress Relaxation",
        "curve",
    ),
    "rheology_dma": ("rheology_dma", "Rheology/DMA", "curve"),
    "thermal": ("thermal", "Thermal", "curve"),
    "spectroscopy": ("spectroscopy", "Spectroscopy", "curve"),
    "scattering": ("scattering", "Scattering", "curve"),
    "chromatography": ("chromatography", "Chromatography", "curve"),
    "metrics_swelling": (
        "metrics_swelling",
        "Metrics/Swelling",
        "box_strip",
    ),
}


def normalize_recipe_name(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def list_recipe_names() -> tuple[str, ...]:
    return tuple(_RECIPE_SPECS)


def get_recipe_spec(name: str) -> RecipeSpec:
    normalized = normalize_recipe_name(name)
    if normalized not in _RECIPE_SPECS:
        known = ", ".join(sorted(_RECIPE_SPECS))
        raise ValueError(f"Unknown recipe `{name}`. Available recipes: {known}.")
    recipe_name, label, template = _RECIPE_SPECS[normalized]
    return RecipeSpec(
        name=recipe_name,
        label=label,
        default_template=template,
        module_name=f"sciplot_recipes.{recipe_name}",
    )


def iter_recipe_specs() -> tuple[RecipeSpec, ...]:
    return tuple(get_recipe_spec(name) for name in _RECIPE_SPECS)


__all__ = [
    "RecipeSpec",
    "get_recipe_spec",
    "iter_recipe_specs",
    "list_recipe_names",
    "normalize_recipe_name",
]
