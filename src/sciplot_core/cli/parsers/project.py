"""Register external-agent inspection and controlled native editing commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def register_project_commands(subparsers: Any) -> None:
    parser = subparsers.add_parser(
        "project", help="Inspect, preview and edit saved projects for external AI."
    )
    actions = parser.add_subparsers(dest="project_action", required=True)
    capabilities = actions.add_parser(
        "capabilities", help="Read the external project control contract."
    )
    capabilities.add_argument("--json", action="store_true")
    create = actions.add_parser(
        "create",
        help="Create an editable project and delivery from an exact source plan.",
    )
    create.add_argument(
        "target", type=Path, help="Raw source named in the current plan."
    )
    create.add_argument("--expected-plan", required=True, type=Path)
    create.add_argument(
        "--out", type=Path, help="New source-adjacent visible delivery directory."
    )
    create.add_argument("--json", action="store_true")
    for name in ("annotations", "operations-preview", "peaks"):
        action = actions.add_parser(name)
        action.add_argument("target", type=Path)
        action.add_argument("--figure")
        action.add_argument("--json", action="store_true")
        if name != "annotations":
            action.add_argument("--expected-document", required=True)
        if name == "operations-preview":
            action.add_argument("--full", action="store_true",
                                help="Return the complete signed review; default returns its summary and review_path.")
            action.add_argument("--operations", type=Path, required=True)
            action.add_argument("--out", type=Path, required=True)
        if name == "peaks":
            action.add_argument("--object", required=True)
            action.add_argument("--window", type=Path, required=True,
                                help="JSON object with min, max and exact x-axis unit.")
            action.add_argument("--polarity", choices=("maximum", "minimum"), required=True)
    for name in ("inspect", "preview", "edit-preview", "edit-apply", "operation"):
        action = actions.add_parser(name)
        action.add_argument(
            "target", type=Path, help="Project, canonical VSZ or associated delivery."
        )
        action.add_argument("--json", action="store_true")
        if name in {"inspect", "edit-preview"}:
            action.add_argument("--full", action="store_true",
                                help="Include complete native settings or signed edit state; default is compact.")
        if name in {"inspect", "preview", "edit-preview"}:
            action.add_argument(
                "--figure", help="Exact figure_id returned by project inspect."
            )
        if name == "inspect":
            action.add_argument(
                "--object", help="Exact widget path returned for a figure."
            )
        if name in {"preview", "edit-preview"}:
            action.add_argument(
                "--out",
                required=True,
                type=Path,
                help="New preview directory outside source/project/delivery.",
            )
        if name == "edit-preview":
            action.add_argument(
                "--changes",
                required=True,
                type=Path,
                help="JSON list of explicit native setting changes.",
            )
            action.add_argument(
                "--expected-document",
                required=True,
                help="Saved document SHA-256 returned by inspect.",
            )
        if name == "edit-apply":
            action.add_argument(
                "--preview",
                required=True,
                type=Path,
                help="Unchanged edit-preview.json to apply.",
            )
        if name == "operation":
            action.add_argument(
                "--operation-id",
                required=True,
                help="Operation identity returned by an edit preview.",
            )
