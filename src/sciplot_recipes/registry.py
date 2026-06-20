from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from sciplot_recipes.common import run_material_recipe


@dataclass(frozen=True)
class RecipeSpec:
    name: str
    label: str
    default_template: str
    module_name: str


_RECIPE_SPECS: dict[str, tuple[str, str, str]] = {
    "tensile": ("tensile", "Tensile", "curve"),
    "stress_relaxation": ("stress_relaxation", "Stress Relaxation", "curve"),
    "rheology_dma": ("rheology_dma", "Rheology/DMA", "curve"),
    "thermal": ("thermal", "Thermal", "curve"),
    "spectroscopy": ("spectroscopy", "Spectroscopy", "curve"),
    "scattering": ("scattering", "Scattering", "curve"),
    "chromatography": ("chromatography", "Chromatography", "curve"),
    "metrics_swelling": ("metrics_swelling", "Metrics/Swelling", "bar"),
}

_RECIPE_MODULES = tuple(_RECIPE_SPECS.keys())


def normalize_recipe_name(name: str) -> str:
    return name.strip().lower().replace("-", "_")


def list_recipe_names() -> tuple[str, ...]:
    return _RECIPE_MODULES


def _build_recipe_module(name: str, label: str, default_template: str) -> ModuleType:
    def _run(
        input_path: Path,
        *,
        output_dir: Path,
        options: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return run_material_recipe(
            name,
            input_path,
            output_dir=output_dir,
            default_template=default_template,
            options=options,
        )

    module = ModuleType(f"sciplot_recipes.{name}")
    module.NAME = name
    module.LABEL = label
    module.DEFAULT_TEMPLATE = default_template
    module.run = _run
    module.__all__ = ["DEFAULT_TEMPLATE", "LABEL", "NAME", "run"]
    sys.modules[module.__name__] = module
    return module


def get_recipe_module(name: str) -> ModuleType:
    normalized = normalize_recipe_name(name)
    if normalized not in _RECIPE_MODULES:
        known = ", ".join(sorted(_RECIPE_MODULES))
        raise ValueError(f"Unknown recipe `{name}`. Available recipes: {known}.")
    name, label, template = _RECIPE_SPECS[normalized]
    return _build_recipe_module(name, label, template)


def get_recipe_spec(name: str) -> RecipeSpec:
    normalized = normalize_recipe_name(name)
    if normalized not in _RECIPE_SPECS:
        known = ", ".join(sorted(_RECIPE_SPECS.keys()))
        raise ValueError(f"Unknown recipe `{name}`. Available recipes: {known}.")
    recipe_name, label, template = _RECIPE_SPECS[normalized]
    return RecipeSpec(
        name=recipe_name,
        label=label,
        default_template=template,
        module_name=f"sciplot_recipes.{recipe_name}",
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
