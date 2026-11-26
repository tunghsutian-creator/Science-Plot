"""Register semantic plot commands over the shared local engine."""

from pathlib import Path
from typing import Any


def register_plot_commands(subparsers: Any) -> None:
    parser = subparsers.add_parser("plot", help="Edit persistent scientific documents through semantic patches.")
    actions = parser.add_subparsers(dest="plot_action", required=True)
    for name in ("open", "describe", "create", "patch", "resume", "intent", "render", "export", "rollback", "decide", "deliver"):
        action = actions.add_parser(name)
        if name == "open":
            action.add_argument("target", type=Path, help="Saved figure target or a .sciplot file (read-only summary).")
            action.add_argument("--figure", dest="figure_id", help="Exact saved figure or plot ID; required if selection is ambiguous.")
        elif name == "export":
            action.add_argument("plot", type=Path, help="A saved figure or a .sciplot file for selected-file export.")
        elif name not in {"create", "deliver"}:
            action.add_argument("plot", type=Path)
        if name in {"open", "describe"}:
            action.add_argument("--scope", choices=("summary", "edit"), help="Optional compact ManagedPlot description.")
            action.add_argument("--target-id", help="Stable semantic target ID for --scope edit.")
            action.add_argument("--property", help="Property name for --scope edit.")
        if name in {"create", "patch", "resume", "intent", "rollback", "decide", "deliver"}:
            action.add_argument("--request", type=Path, required=True)
        if name == "export":
            action.add_argument("--output-dir", type=Path, help="Put only selected files in a fresh directory (requires exact plot ID and revision).")
            action.add_argument("--plot-id", help="Exact current Managed v2 identity for --output-dir.")
            action.add_argument("--revision", type=int, help="Exact current Managed v2 revision for --output-dir.")
            formats = action.add_mutually_exclusive_group()
            formats.add_argument("--tiff", action="store_true", help="Also copy the audited 300 dpi TIFF.")
            formats.add_argument("--plotted-csv", action="store_true", help="Export only the current plot's bound data columns as CSVs.")
            formats.add_argument("--editable-vsz", action="store_true", help="Export only one independent editable Veusz file.")
        if name == "create":
            action.add_argument("--project", type=Path, help="Explicit existing project for Managed Template/Binding creation; outside the scientific request.")
        action.add_argument("--json", action="store_true")
        action.add_argument("--socket", type=Path, help="Private local engine socket; defaults to this checkout's engine.")
        action.add_argument("--timeout", type=float, default=600.0)
        action.add_argument("--direct", action="store_true", help="Call the same local engine in this process.")
    editor = actions.add_parser("editor", help="Open one saved Managed v2 figure in the local axis editor.")
    editor.add_argument("plot", type=Path, help="Exact saved plot path or standalone .sciplot file.")
    editor.add_argument("--figure", help="Exact plot or figure ID within a .sciplot file with several figures.")
    editor.add_argument("--socket", type=Path, help="Use the same local engine as an existing client.")
    editor.add_argument("--timeout", type=float, default=600.0)
    serve = actions.add_parser("serve", help="Run the serialized local plot engine in the foreground.")
    serve.add_argument("--socket", type=Path, required=True)
    serve.add_argument("--idle-timeout", type=float, default=900.0)
    serve.add_argument("--request-timeout", type=float, default=600.0)

