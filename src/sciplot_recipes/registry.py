from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from typing import Any

from sciplot_recipes.common import run_material_recipe
from sciplot_recipes.contracts import (
    RecipeSpec,
    get_recipe_spec,
    iter_recipe_specs,
    list_recipe_names,
    normalize_recipe_name,
)

_RECIPE_MODULES = list_recipe_names()
_MODULE_CACHE: dict[str, ModuleType] = {}


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
    if normalized in _MODULE_CACHE:
        return _MODULE_CACHE[normalized]
    spec = get_recipe_spec(normalized)
    module = _build_recipe_module(
        spec.name,
        spec.label,
        spec.default_template,
    )
    _MODULE_CACHE[normalized] = module
    return module


__all__ = [
    "RecipeSpec",
    "get_recipe_module",
    "get_recipe_spec",
    "iter_recipe_specs",
    "list_recipe_names",
    "normalize_recipe_name",
]
