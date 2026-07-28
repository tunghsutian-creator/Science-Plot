"""SciPlot command-line API and compatibility facade."""

from __future__ import annotations

from sciplot_core.cli.adapters import run_autoplot, serve_intake
from sciplot_core.cli.value_io import (
    _RECOGNITION_ERROR_MARKERS as _RECOGNITION_ERROR_MARKERS,
    _coerce_sheet as _coerce_sheet,
    _load_options as _load_options,
    _print_json as _print_json,
    _recovery_hint as _recovery_hint,
    _resolve_input as _resolve_input,
)
from sciplot_core.cli.entrypoint import main as _main_impl
from sciplot_core.cli.parsers import _build_parser as _build_parser


def main(argv: list[str] | None = None) -> int:
    """Run the CLI while preserving its historical monkeypatch seams."""

    return _main_impl(
        argv,
        run_autoplot_impl=run_autoplot,
        serve_intake_impl=serve_intake,
    )
