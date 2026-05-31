from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_recipes.common import run_material_recipe

_RECIPE_DEFAULT_TEMPLATES = {
    "tensile": "curve",
    "stress_relaxation": "curve",
    "rheology_dma": "curve",
    "thermal": "curve",
    "spectroscopy": "curve",
    "scattering": "curve",
    "chromatography": "curve",
    "metrics_swelling": "bar",
}


def run_recipe(
    name: str,
    input_path: Path,
    *,
    output_dir: Path,
    options: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized = name.strip().lower().replace("-", "_")
    if normalized not in _RECIPE_DEFAULT_TEMPLATES:
        known = ", ".join(sorted(_RECIPE_DEFAULT_TEMPLATES))
        raise ValueError(f"Unknown recipe `{name}`. Available recipes: {known}.")
    return run_material_recipe(
        normalized,
        input_path,
        output_dir=output_dir,
        default_template=_RECIPE_DEFAULT_TEMPLATES[normalized],
        options=options,
    )


__all__ = ["run_recipe"]
