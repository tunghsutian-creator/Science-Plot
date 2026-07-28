"""Register render, recipe, replay, and autoplot commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def register_rendering_commands(subparsers: Any) -> None:
    render_parser = subparsers.add_parser(
        "render", help="Low-level primitive: render an already plot-ready source."
    )

    render_parser.add_argument("input", type=Path)

    render_parser.add_argument(
        "--template", help="Template id. Optional when --auto is given."
    )

    render_parser.add_argument("--sheet", default="0")

    render_parser.add_argument(
        "--options", help="JSON object or @path JSON file with render options."
    )

    render_parser.add_argument(
        "--auto",
        action="store_true",
        help="Apply the inspected recommendation's scientific defaults (template, axis scales, reversed axes). Explicit --options still win.",
    )

    render_parser.add_argument("--out", type=Path, required=True)

    recipe_parser = subparsers.add_parser(
        "recipe", help="Low-level primitive: run a known experiment-family recipe."
    )

    recipe_parser.add_argument("name")

    recipe_parser.add_argument("input", type=Path)

    recipe_parser.add_argument(
        "--options", help="JSON object or @path JSON file with recipe/render options."
    )

    recipe_parser.add_argument("--out", type=Path, required=True)

    run_parser = subparsers.add_parser(
        "run", help="Replay an already confirmed plot_request.json."
    )

    run_parser.add_argument("request", type=Path)

    autoplot_parser = subparsers.add_parser(
        "autoplot",
        help="Fully automated non-interactive project orchestration with QA, delivery, and a structured assistant handoff summary.",
    )

    autoplot_parser.add_argument("input", type=Path)

    autoplot_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Dedicated visible handoff directory. Defaults beside the data source; runtime evidence is stored in a sibling hidden .sciplot directory.",
    )

    autoplot_parser.add_argument(
        "--name", help="Project name. Defaults to the input file or folder name."
    )

    autoplot_parser.add_argument(
        "--template",
        help="Explicit supported presentation template. For categorical replicate data this can select bar, box, or box_strip without changing the detected scientific data type.",
    )

    autoplot_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
