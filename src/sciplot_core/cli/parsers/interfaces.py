"""Register saved native commands and explicit retired-interface errors."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def register_interfaces_commands(subparsers: Any) -> None:
    edit_parser = subparsers.add_parser("edit", help="Retired manual editor; use AI-driven task edit or plot describe.")
    edit_parser.add_argument("target", type=Path, help="Historical target argument; never opened or changed.")
    edit_parser.add_argument("--figure", help=argparse.SUPPRESS)
    edit_parser.add_argument("--port", type=int, default=0, help=argparse.SUPPRESS)
    edit_parser.add_argument("--session-dir", type=Path, help=argparse.SUPPRESS)
    edit_parser.add_argument("--no-open", action="store_true", help=argparse.SUPPRESS)
    edit_parser.add_argument("--portable-fallback", action="store_true",
                             help=argparse.SUPPRESS)
    edit_parser.add_argument("--check", action="store_true",
                             help=argparse.SUPPRESS)
    edit_parser.add_argument("--json", action="store_true", help="Report the retirement through the CLI error contract.")

    app_parser = subparsers.add_parser(
        "app",
        help="Retired browser intake; use task create and source-bound confirmations.",
    )

    app_parser.add_argument("input", nargs="?", type=Path, help=argparse.SUPPRESS)

    app_parser.add_argument("--host", default="127.0.0.1", help=argparse.SUPPRESS)

    app_parser.add_argument("--port", type=int, default=8765, help=argparse.SUPPRESS)

    app_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "intake_projects", help=argparse.SUPPRESS
    )

    app_parser.add_argument(
        "--project", help=argparse.SUPPRESS
    )

    app_parser.add_argument(
        "--no-open", action="store_true", help=argparse.SUPPRESS
    )
    app_parser.add_argument("--json", action="store_true", help="Report the retirement as machine-readable JSON.")

    studio_parser = subparsers.add_parser(
        "studio", help="Headless preparation or exact-current export of saved Veusz projects."
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

    revision = studio_parser.add_mutually_exclusive_group()
    revision.add_argument(
        "--recover-delivery",
        action="store_true",
        help="Preview recovery of a changed visible VSZ into its bound project.",
    )
    revision.add_argument(
        "--update-source",
        type=Path,
        help="Preview new source data and compatible styling in the existing project.",
    )
    revision.add_argument(
        "--apply-revision",
        type=Path,
        help="Apply a reviewed recovery or source-update preview JSON; rejects changed inputs.",
    )
    studio_parser.add_argument(
        "--preview-out",
        type=Path,
        help="Save the recovery or source-update preview for review before applying.",
    )
    studio_parser.add_argument(
        "--worksheet",
        help="Explicit Excel worksheet for a source-update preview when the rule requires a selection.",
    )

    studio_parser.add_argument(
        "--new", action="store_true", help=argparse.SUPPRESS
    )

    studio_parser.add_argument(
        "--export", help="Comma-separated export formats, e.g. pdf,tiff_300."
    )

    studio_parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the headless preparation or export result as JSON.",
    )

    studio_parser.add_argument(
        "--prepare-only", action="store_true", help=argparse.SUPPRESS
    )

    studio_parser.add_argument(
        "--qt-smoke", action="store_true", help=argparse.SUPPRESS
    )
