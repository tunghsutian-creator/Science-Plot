"""Register acceptance, curation, and material-rule commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def register_governance_commands(subparsers: Any) -> None:
    acceptance_parser = subparsers.add_parser(
        "acceptance", help="Run real-data acceptance suites."
    )

    acceptance_subparsers = acceptance_parser.add_subparsers(
        dest="acceptance_command", required=True
    )

    acceptance_3dpa_parser = acceptance_subparsers.add_parser(
        "3dpa", help="Run the representative 3D PA real-data acceptance suite."
    )

    acceptance_3dpa_parser.add_argument("input", type=Path)

    acceptance_3dpa_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "acceptance"
    )

    acceptance_3dpa_parser.add_argument(
        "--name", default="3dpa_acceptance", help="Acceptance project name."
    )

    acceptance_3dpa_parser.add_argument("--representative-count", type=int, default=6)

    acceptance_3dpa_parser.add_argument("--dense-series", type=int, default=44)

    acceptance_3dpa_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    acceptance_rules_parser = acceptance_subparsers.add_parser(
        "rules", help="Run the ready-rule Studio lifecycle acceptance matrix."
    )

    acceptance_rules_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "acceptance"
    )

    acceptance_rules_parser.add_argument(
        "--name", default="ready_rule_acceptance", help="Acceptance project name."
    )

    acceptance_rules_parser.add_argument(
        "--rule",
        dest="rule_ids",
        action="append",
        help="Run one ready rule; repeat for a batch. Defaults to all ready rules.",
    )

    acceptance_rules_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    acceptance_visual_review_parser = acceptance_subparsers.add_parser(
        "visual-review",
        help="Record the explicit contact-sheet decision for a rules acceptance run.",
    )

    acceptance_visual_review_parser.add_argument(
        "review_json",
        type=Path,
        help="Path to final_size_visual_review/final_size_visual_review.json.",
    )

    acceptance_visual_review_parser.add_argument(
        "--decision", choices=("passed", "failed"), required=True
    )

    acceptance_visual_review_parser.add_argument("--reviewer", required=True)

    acceptance_visual_review_parser.add_argument(
        "--note",
        dest="notes",
        action="append",
        help="Optional review note; repeat to record more than one.",
    )

    acceptance_visual_review_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    curate_parser = subparsers.add_parser(
        "curate",
        help="Prepare a reviewable scientific curation project for Studio; does not replace Studio export or delivery.",
    )

    curate_subparsers = curate_parser.add_subparsers(
        dest="curate_command", required=True
    )

    curate_torque_parser = curate_subparsers.add_parser(
        "torque", help="Curate torque event segments."
    )

    curate_torque_parser.add_argument("input", type=Path)

    curate_torque_parser.add_argument(
        "--name", required=True, help="User-facing project name."
    )

    curate_torque_parser.add_argument(
        "--out", type=Path, default=Path("outputs") / "curation_projects"
    )

    curate_torque_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    curate_torque_parser.add_argument(
        "--open", action="store_true", help="Open the review HTML after export."
    )

    rules_parser = subparsers.add_parser(
        "rules", help="Inspect SciPlot material semantic rules."
    )

    rules_subparsers = rules_parser.add_subparsers(dest="rules_command", required=True)

    rules_list_parser = rules_subparsers.add_parser(
        "list", help="List material semantic rules."
    )

    rules_list_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    rules_list_parser.add_argument(
        "--all", action="store_true", help="Include pending internal rules."
    )

    rules_show_parser = rules_subparsers.add_parser(
        "show", help="Show one material semantic rule."
    )

    rules_show_parser.add_argument("rule_id")

    rules_show_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )
