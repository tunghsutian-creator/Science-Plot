"""Register the internal batch command."""

from __future__ import annotations

from pathlib import Path
from typing import Any


def register_batch_commands(subparsers: Any) -> None:
    batch_parser = subparsers.add_parser(
        "batch", help="Run a batch over a data folder."
    )

    batch_parser.add_argument("input_dir", type=Path)

    batch_parser.add_argument("--out", type=Path, required=True)

    batch_parser.add_argument("--mode", choices=["smoke", "all"], default="smoke")

    batch_parser.add_argument(
        "--tensile-root",
        action="append",
        type=Path,
        help="Allow-list tensile data root. Repeat to allow multiple tensile folders.",
    )
