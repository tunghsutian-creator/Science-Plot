"""Register the local panel assembly entry without loading Qt or rendering."""

from pathlib import Path
from typing import Any


def register_composition_commands(subparsers: Any) -> None:
    parser = subparsers.add_parser("compose", help="Select, arrange and export existing figures and images locally.")
    actions = parser.add_subparsers(dest="compose_action", required=True)
    capabilities = actions.add_parser("capabilities", help="Read the compact layout intent contract.")
    capabilities.add_argument("--json", action="store_true")
    create = actions.add_parser("new", help="Save a new empty physical panel layout.")
    create.add_argument("layout", type=Path)
    create.add_argument("--rows", type=int, default=2)
    create.add_argument("--columns", type=int, default=2)
    create.add_argument("--width-mm", type=float, default=180)
    create.add_argument("--height-mm", type=float, default=140)
    create.add_argument("--json", action="store_true")
    apply = actions.add_parser("apply", help="Apply one atomic local layout intent batch.")
    apply.add_argument("layout", type=Path)
    apply.add_argument("--operations", required=True, help="JSON array or @path; new panel sources are bound locally.")
    apply.add_argument("--expected-revision", type=int, required=True)
    apply.add_argument("--json", action="store_true")
    inspect = actions.add_parser("inspect", help="Read the saved layout; source checking is explicit.")
    inspect.add_argument("layout", type=Path)
    inspect.add_argument("--check-sources", action="store_true")
    inspect.add_argument("--json", action="store_true")
    export = actions.add_parser("export", help="Reflow supported native panels and export PDF/TIFF plus editable sources.")
    export.add_argument("layout", type=Path)
    export.add_argument("--out", type=Path, required=True)
    export.add_argument("--dpi", type=int, default=300)
    export.add_argument("--json", action="store_true")
    open_parser = actions.add_parser("open", help="Open the native local panel workbench.")
    open_parser.add_argument("layout", type=Path, nargs="?")

