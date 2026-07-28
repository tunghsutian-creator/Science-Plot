"""Register browser confirmation and native Studio commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def register_interfaces_commands(subparsers: Any) -> None:
    app_parser = subparsers.add_parser(
        "app",
        help="Open optional browser source/grouping/export confirmation and read-only result review.",
    )

    app_parser.add_argument("input", nargs="?", type=Path)

    app_parser.add_argument("--host", default="127.0.0.1")

    app_parser.add_argument("--port", type=int, default=8765)

    app_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "intake_projects"
    )

    app_parser.add_argument(
        "--project", help="Open an existing intake project under --out."
    )

    app_parser.add_argument(
        "--no-open", action="store_true", help="Do not open a browser automatically."
    )

    studio_parser = subparsers.add_parser(
        "studio", help="Prepare, open, or exact-current export a Veusz project."
    )

    studio_parser.add_argument(
        "target",
        nargs="?",
        type=Path,
        help="Raw data path, SciPlot project, plot_request.json, or .vsz file.",
    )

    studio_parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Dedicated visible handoff directory for raw input or a project, or artifact root for standalone VSZ export. Raw input defaults beside the source; runtime evidence stays in a sibling hidden .sciplot directory.",
    )

    studio_parser.add_argument(
        "--rule",
        help="Explicit material rule selected by the user or an assistant. Pending rules remain non-ready and are never silently promoted.",
    )

    studio_parser.add_argument(
        "--template",
        help="Preselect an implemented SciPlot template, e.g. curve, scatter, or polar_curve.",
    )

    studio_parser.add_argument(
        "--name", help="Preselect the SciPlot project/figure name."
    )

    studio_parser.add_argument(
        "--new", action="store_true", help="Open an empty native Veusz MainWindow."
    )

    studio_parser.add_argument(
        "--export", help="Comma-separated export formats, e.g. pdf,tiff_300."
    )

    studio_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON and do not open the GUI.",
    )

    studio_parser.add_argument(
        "--prepare-only", action="store_true", help=argparse.SUPPRESS
    )

    studio_parser.add_argument(
        "--qt-smoke", action="store_true", help=argparse.SUPPRESS
    )
