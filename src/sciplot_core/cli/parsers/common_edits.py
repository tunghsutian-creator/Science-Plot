"""Register the bounded common-edit task entry beside existing task commands."""

from pathlib import Path
from typing import Any


def register_common_edit_command(actions: Any) -> None:
    parser = actions.add_parser("edit", help="Change a named palette, typography or supported legend property in one transaction.")
    parser.add_argument("target", type=Path)
    parser.add_argument("--intent", help="Exact clauses, e.g. '换配色 tol_bright；统一字号 9pt；图例字号 7pt'.")
    parser.add_argument("--palette", help="Exact public palette ID from common-edit capabilities.")
    parser.add_argument("--font-size", help="Typography size with unit, e.g. 9pt.")
    parser.add_argument("--font-family", help="Exact installed font family; Managed FigureSpec v2 only.")
    parser.add_argument("--legend-font-size", help="Size of every represented legend, e.g. 7pt.")
    visibility = parser.add_mutually_exclusive_group()
    visibility.add_argument("--hide-legend", dest="legend_visible", action="store_false")
    visibility.add_argument("--show-legend", dest="legend_visible", action="store_true")
    parser.set_defaults(legend_visible=None)
    parser.add_argument("--legend-position", help="Explicit relative x,y; only when current authority advertises placement.")
    parser.add_argument("--figure", help="Registered figure identity for saved native projects.")
    parser.add_argument("--task-dir", type=Path, help="Stable edit entry for identical replay/recovery.")
    parser.add_argument("--json", action="store_true")
