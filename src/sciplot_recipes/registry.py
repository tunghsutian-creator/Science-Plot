from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from types import ModuleType


@dataclass(frozen=True)
class RecipeSpec:
    name: str
    label: str
    default_template: str
    module_name: str


_RECIPE_MODULES = (
    "tensile",
    "stress_relaxation",
    "rheology_dma",
    "thermal",
    "spectroscopy",
    "scattering",
    "chromatography",
    "metrics_swelling",
)


def normalize_recipe_name(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def list_recipe_names() -> tuple[str, ...]:
    return _RECIPE_MODULES


def get_recipe_module(name: str) -> ModuleType:
    normalized = normalize_recipe_name(name)
    if normalized not in _RECIPE_MODULES:
        known = ", ".join(sorted(_RECIPE_MODULES))
        raise ValueError(f"Unknown recipe `{name}`. Available recipes: {known}.")
    return import_module(f"sciplot_recipes.{normalized}")


def get_recipe_spec(name: str) -> RecipeSpec:
    module = get_recipe_module(name)
    return RecipeSpec(
        name=module.NAME,
        label=module.LABEL,
        default_template=module.DEFAULT_TEMPLATE,
        module_name=module.__name__,
    )


def iter_recipe_specs() -> tuple[RecipeSpec, ...]:
    return tuple(get_recipe_spec(name) for name in _RECIPE_MODULES)


__all__ = [
    "RecipeSpec",
    "get_recipe_module",
    "get_recipe_spec",
    "iter_recipe_specs",
    "list_recipe_names",
    "normalize_recipe_name",
]
