"""Register inspection, doctor, readiness, smoke, and internal probe commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def register_diagnostics_commands(subparsers: Any) -> None:
    inspect_parser = subparsers.add_parser(
        "inspect", help="Inspect a source and return ranked plot recommendations."
    )

    inspect_parser.add_argument("input", type=Path)

    inspect_parser.add_argument("--sheet", default="0")

    inspect_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Check whether this SciPlot install is ready for supported daily use.",
    )

    doctor_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    readiness_parser = subparsers.add_parser(
        "readiness",
        help="Inspect or certify deterministic ready-rule validation envelopes.",
    )

    readiness_subparsers = readiness_parser.add_subparsers(
        dest="readiness_command", required=True
    )

    readiness_status_parser = readiness_subparsers.add_parser(
        "status", help="Verify current ready-rule contracts against accepted evidence."
    )

    readiness_status_parser.add_argument(
        "--registry", type=Path, help="Optional candidate validated-envelope registry."
    )

    readiness_status_parser.add_argument("--json", action="store_true")

    readiness_certify_parser = readiness_subparsers.add_parser(
        "certify",
        help="Build a candidate registry from a complete real-data acceptance run.",
    )

    readiness_certify_parser.add_argument("acceptance_summary", type=Path)

    readiness_certify_parser.add_argument("--out", type=Path, required=True)

    readiness_certify_parser.add_argument("--json", action="store_true")

    smoke_parser = subparsers.add_parser(
        "smoke", help="Run the fixture-free Studio lifecycle and delivery change gate."
    )

    smoke_parser.add_argument(
        "--out", type=Path, default=Path(".tmp_verify") / "runtime_smoke"
    )

    smoke_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    readiness_probe_parser = subparsers.add_parser(
        "readiness-probe", help=argparse.SUPPRESS
    )

    readiness_probe_parser.add_argument(
        "--out", type=Path, default=Path(".tmp_verify") / "readiness_probe"
    )

    readiness_probe_parser.add_argument("--json", action="store_true")

    openai_provider_probe_parser = subparsers.add_parser(
        "openai-provider-probe", help=argparse.SUPPRESS
    )

    openai_provider_probe_parser.add_argument(
        "--out", type=Path, default=Path(".tmp_verify") / "openai_provider"
    )

    openai_provider_probe_parser.add_argument("--json", action="store_true")

    data_mapping_probe_parser = subparsers.add_parser(
        "data-mapping-probe", help=argparse.SUPPRESS
    )

    data_mapping_probe_parser.add_argument(
        "--out", type=Path, default=Path(".tmp_verify") / "data_mapping"
    )

    data_mapping_probe_parser.add_argument("--json", action="store_true")
