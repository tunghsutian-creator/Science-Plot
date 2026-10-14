"""Register inspection, doctor, readiness, smoke, and internal probe commands."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any


def register_diagnostics_commands(subparsers: Any) -> None:
    plan_parser = subparsers.add_parser(
        "plan",
        help=(
            "Preview the exact FigurePlan and source-bound scientific transform "
            "without rendering or writing a project."
        ),
    )

    plan_parser.add_argument("input", type=Path)

    plan_parser.add_argument(
        "--rule",
        help="Explicit material rule selected by the user or an assistant.",
    )

    plan_parser.add_argument(
        "--template",
        help="Explicit presentation template within the selected rule.",
    )

    plan_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

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

    verify_parser = subparsers.add_parser(
        "verify",
        help="Verify a changed scope or start and inspect a durable test suite.",
    )

    verify_scope = verify_parser.add_mutually_exclusive_group(required=True)
    verify_scope.add_argument(
        "--changed",
        action="store_true",
        help="Verify the staged, unstaged, and untracked HEAD worktree.",
    )
    verify_scope.add_argument(
        "--start", choices=("focused", "comprehensive", "full"),
        help="Start one durable suite execution; return before the suite finishes.",
    )
    verify_scope.add_argument(
        "--status", type=Path, metavar="DIR",
        help="Read the original durable execution without collecting or rerunning tests.",
    )
    verify_parser.add_argument(
        "--out", type=Path, metavar="DIR",
        help="Fresh named directory under .tmp_verify, required with --start.",
    )
    verify_parser.add_argument(
        "--audit-plugin-dir", type=Path, metavar="DIR",
        help="Frozen local access-observation plugin directory, only with --start.",
    )
    verify_parser.add_argument(
        "--audit-out", type=Path, metavar="DIR",
        help="Fresh separate local audit output, paired with --audit-plugin-dir.",
    )

    verify_parser.add_argument(
        "--json", action="store_true", help="Emit machine-readable JSON."
    )

    verify_parser.add_argument(
        "--base", metavar="REV",
        help="Include committed changes from REV to HEAD, plus the current worktree.",
    )
    verify_mode = verify_parser.add_mutually_exclusive_group()
    verify_mode.add_argument(
        "--plan-only", action="store_true",
        help="Resolve the changed scope and list checks without executing them.",
    )
    verify_mode.add_argument(
        "--record", type=Path, metavar="DIR",
        help="Execute each check once with durable local evidence under .tmp_verify.",
    )
    verify_mode.add_argument(
        "--reuse", type=Path, metavar="DIR",
        help="Validate matching local check receipts without rerunning verification gates.",
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

    readiness_merge_parser = readiness_subparsers.add_parser(
        "merge",
        help="Merge scoped real-data acceptance into one existing registry.",
    )

    readiness_merge_parser.add_argument("base_registry", type=Path)

    readiness_merge_parser.add_argument("acceptance_summary", type=Path)

    readiness_merge_parser.add_argument("--out", type=Path, required=True)

    readiness_merge_parser.add_argument("--json", action="store_true")

    smoke_parser = subparsers.add_parser(
        "smoke", help="Run the fixture-free Studio lifecycle and delivery change gate."
    )

    smoke_parser.add_argument(
        "--out", type=Path, default=Path(".tmp_verify") / "runtime_smoke"
    )

    smoke_parser.add_argument(
        "--profile", choices=("full", "quick"), default="full",
        help="Full lifecycle gate (default), or bounded native/export/QA feedback.",
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

    automation_baseline_parser = subparsers.add_parser(
        "automation-baseline", help=argparse.SUPPRESS
    )

    automation_baseline_parser.add_argument(
        "--out",
        type=Path,
        default=Path(".tmp_verify") / "r0_automation_baseline",
    )

    automation_baseline_parser.add_argument("--repetitions", type=int, default=3)

    automation_baseline_parser.add_argument("--json", action="store_true")
