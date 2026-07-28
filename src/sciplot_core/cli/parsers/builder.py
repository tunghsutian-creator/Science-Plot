"""Build the public command parser from bounded command-family registrars."""

from __future__ import annotations

import argparse

from sciplot_core.cli.parsers.diagnostics import register_diagnostics_commands
from sciplot_core.cli.parsers.rendering import register_rendering_commands
from sciplot_core.cli.parsers.governance import register_governance_commands
from sciplot_core.cli.parsers.data_management import register_data_management_commands
from sciplot_core.cli.parsers.batch import register_batch_commands
from sciplot_core.cli.parsers.interfaces import register_interfaces_commands
from sciplot_core.cli.parsers.quality_publication import (
    register_quality_publication_commands,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sciplot",
        description=(
            "Local SciPlot plotting, Studio, recipe, QA, and optional "
            "assisted-cleanup CLI."
        ),
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    register_diagnostics_commands(subparsers)
    register_rendering_commands(subparsers)
    register_governance_commands(subparsers)
    register_data_management_commands(subparsers)
    register_batch_commands(subparsers)
    register_interfaces_commands(subparsers)
    register_quality_publication_commands(subparsers)
    internal_commands = {
        "readiness-probe",
        "openai-provider-probe",
        "data-mapping-probe",
        "batch",
    }

    subparsers._choices_actions[:] = [
        action
        for action in subparsers._choices_actions
        if action.dest not in internal_commands
    ]

    public_commands = [
        name for name in subparsers.choices if name not in internal_commands
    ]

    subparsers.metavar = "{" + ",".join(public_commands) + "}"
    return parser


_build_parser = build_parser
