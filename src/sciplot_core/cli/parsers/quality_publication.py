"""Register QA and publication contract commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def register_quality_publication_commands(subparsers: Any) -> None:
    qa_parser = subparsers.add_parser("qa", help="Validate rendered SciPlot outputs.")

    qa_parser.add_argument("output_dir", type=Path)

    qa_parser.add_argument("--goldens", type=Path)

    qa_parser.add_argument(
        "--strict-goldens",
        action="store_true",
        help="Fail when any golden target is missing from the rendered output.",
    )

    qa_parser.add_argument(
        "--publication-profile",
        "--profile",
        help="Publication profile id or JSON path for final-artifact checks.",
    )

    qa_parser.add_argument(
        "--strict-publication",
        action="store_true",
        help="Return a failed QA status when publication-profile checks need revision.",
    )

    publication_parser = subparsers.add_parser(
        "publication",
        help="Inspect publication profiles and deterministic figure-level layouts.",
    )

    publication_subparsers = publication_parser.add_subparsers(
        dest="publication_command", required=True
    )

    publication_profiles_parser = publication_subparsers.add_parser(
        "profiles", help="List publication profiles."
    )

    publication_profiles_parser.add_argument("--json", action="store_true")

    publication_profile_parser = publication_subparsers.add_parser(
        "profile", help="Show one publication profile."
    )

    publication_profile_parser.add_argument("profile_id")

    publication_profile_parser.add_argument("--json", action="store_true")

    publication_layouts_parser = publication_subparsers.add_parser(
        "layouts", help="List deterministic figure-level layouts."
    )

    publication_layouts_parser.add_argument("--json", action="store_true")

    publication_layout_parser = publication_subparsers.add_parser(
        "layout", help="Show one deterministic figure-level layout."
    )

    publication_layout_parser.add_argument("layout_id")

    publication_layout_parser.add_argument("--height-mm", type=float, default=55.0)

    publication_layout_parser.add_argument("--json", action="store_true")
