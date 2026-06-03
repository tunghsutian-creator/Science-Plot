from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_recipes.registry import get_recipe_module, iter_recipe_specs, list_recipe_names


def run_recipe(
    name: str,
    input_path: Path,
    *,
    output_dir: Path,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    module = get_recipe_module(name)
    return module.run(
        input_path,
        output_dir=output_dir,
        options=options,
    )


__all__ = ["iter_recipe_specs", "list_recipe_names", "run_recipe"]
