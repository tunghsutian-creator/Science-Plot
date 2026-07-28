"""Register assisted-cleanup and typed data-mapping commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def register_data_management_commands(subparsers: Any) -> None:
    cleanup_parser = subparsers.add_parser(
        "cleanup", help="Create or inspect assisted-cleanup artifacts."
    )

    cleanup_subparsers = cleanup_parser.add_subparsers(
        dest="cleanup_command", required=True
    )

    cleanup_result_parser = cleanup_subparsers.add_parser(
        "result",
        help="Write a cleanup_result.json from a Codex/agent assisted cleanup job.",
    )

    cleanup_result_parser.add_argument("output_dir", type=Path)

    cleanup_result_parser.add_argument("--cleaned-data", type=Path, required=True)

    cleanup_result_parser.add_argument(
        "--mapping", help="JSON object or @path JSON file with column/sample mapping."
    )

    cleanup_result_parser.add_argument("--confidence", type=float, required=True)

    cleanup_result_parser.add_argument(
        "--confirm",
        action="store_true",
        help="Mark the cleaned result as human-confirmed.",
    )

    cleanup_result_parser.add_argument(
        "--raw-input",
        type=Path,
        action="append",
        help="Raw input path preserved by cleanup.",
    )

    cleanup_result_parser.add_argument(
        "--provider",
        default="manual",
        help="Cleanup provider label, e.g. manual or codex.",
    )

    cleanup_result_parser.add_argument(
        "--notes", default="", help="Short cleanup note."
    )

    cleanup_result_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    cleanup_show_parser = cleanup_subparsers.add_parser(
        "show", help="Show cleanup_result.json from a directory or file."
    )

    cleanup_show_parser.add_argument("target", type=Path)

    cleanup_show_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    mapping_parser = subparsers.add_parser(
        "mapping",
        help="Preview, confirm, execute, or inspect a typed DataMappingProposal.",
    )

    mapping_subparsers = mapping_parser.add_subparsers(
        dest="mapping_command", required=True
    )

    mapping_preview_parser = mapping_subparsers.add_parser(
        "preview",
        help="Validate a proposal and compute metadata-only output changes without writing data.",
    )

    mapping_preview_parser.add_argument("proposal", type=Path)

    mapping_preview_parser.add_argument("--source-root", type=Path, required=True)

    mapping_preview_parser.add_argument("--request", type=Path, required=True)

    mapping_preview_parser.add_argument("--json", action="store_true")

    mapping_confirm_parser = mapping_subparsers.add_parser(
        "confirm",
        help="Create a user confirmation receipt bound to the exact proposal, request, and source hashes.",
    )

    mapping_confirm_parser.add_argument("proposal", type=Path)

    mapping_confirm_parser.add_argument("--source-root", type=Path, required=True)

    mapping_confirm_parser.add_argument("--request", type=Path, required=True)

    mapping_confirm_parser.add_argument(
        "--execution-root",
        type=Path,
        required=True,
        help="Exact parent directory where confirmed execution may write its candidate.",
    )

    mapping_confirm_parser.add_argument("--by", required=True)

    mapping_confirm_parser.add_argument("--out", type=Path)

    mapping_confirm_parser.add_argument("--json", action="store_true")

    mapping_execute_parser = mapping_subparsers.add_parser(
        "execute",
        help="Execute a confirmed proposal atomically and write a mapped request candidate.",
    )

    mapping_execute_parser.add_argument("proposal", type=Path)

    mapping_execute_parser.add_argument("--confirmation", type=Path, required=True)

    mapping_execute_parser.add_argument("--source-root", type=Path, required=True)

    mapping_execute_parser.add_argument("--request", type=Path, required=True)

    mapping_execute_parser.add_argument("--out", type=Path, required=True)

    mapping_execute_parser.add_argument("--json", action="store_true")

    mapping_show_parser = mapping_subparsers.add_parser(
        "show", help="Verify and show a completed data mapping execution."
    )

    mapping_show_parser.add_argument("target", type=Path)

    mapping_show_parser.add_argument("--json", action="store_true")
