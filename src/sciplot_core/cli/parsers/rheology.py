"""Register explicit source-bound rheology analysis commands."""

from pathlib import Path
from typing import Any


def register_rheology_commands(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "rheology", help="Plot AI-prepared rheology plans and export saved native suites."
    )
    commands = parser.add_subparsers(dest="rheology_command", required=True)
    plot = commands.add_parser("plot", help="Draw AI-prepared coordinates faithfully through shared templates; no data analysis.")
    plot.add_argument("--request", type=Path, required=True)
    plot.add_argument("--resume", action="store_true", help="Resume only the same checkpoint-bound prepared creation; never overwrite existing delivery.")
    plot.add_argument("--json", action="store_true")
    plot.add_argument("--full", action="store_true", help="Include full native creation evidence; the default receipt links its saved manifest.")
    create = commands.add_parser("tts", help="Create a source-bound TTS figure suite.")
    create.add_argument("--request", type=Path, required=True)
    create.add_argument("--json", action="store_true")
    create.add_argument("--full", action="store_true", help="Include full native creation evidence; the default receipt links its saved manifest.")
    export = commands.add_parser("export", help="Export exact saved TTS suite documents.")
    export.add_argument("workspace", type=Path)
    export.add_argument("--json", action="store_true")
    capabilities = commands.add_parser("capabilities", help="Read validated request and shared presentation contracts.")
    capabilities.add_argument("--json", action="store_true")
    preview = commands.add_parser("style-preview", help="Preview template restoration on current saved native files.")
    preview.add_argument("workspace", type=Path)
    preview.add_argument("--presentation-plan", type=Path,
                         help="Caller-prepared display-label/legend plan; scientific values must remain unchanged.")
    preview.add_argument("--json", action="store_true")
    apply = commands.add_parser("style-apply", help="Apply a reviewed, revision-bound presentation preview.")
    apply.add_argument("workspace", type=Path)
    apply.add_argument("--preview", type=Path, required=True)
    apply.add_argument("--json", action="store_true")
