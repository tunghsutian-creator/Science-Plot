from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_recipes.common import run_material_recipe

NAME = "thermal"
LABEL = "Thermal"
DEFAULT_TEMPLATE = "curve"


def run(input_path: Path, *, output_dir: Path, options: dict[str, Any] | None = None) -> dict[str, Any]:
    return run_material_recipe(
        NAME,
        input_path,
        output_dir=output_dir,
        default_template=DEFAULT_TEMPLATE,
        options=options,
    )


__all__ = ["DEFAULT_TEMPLATE", "LABEL", "NAME", "run"]
