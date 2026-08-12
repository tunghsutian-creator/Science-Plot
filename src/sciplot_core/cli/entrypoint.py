"""Parse arguments, dispatch one command, and normalize CLI failures."""

from __future__ import annotations

import sys
from typing import Any, Callable

from sciplot_core.cli.value_io import (
    _RECOGNITION_ERROR_MARKERS,
    _cli_runtime_error_payload,
    _print_json,
    _recovery_hint,
)
from sciplot_core.cli.dispatch import (
    dispatch_diagnostics,
    dispatch_governance,
    dispatch_interfaces,
    dispatch_rendering,
)
from sciplot_core.cli.parsers import build_parser


def main(
    argv: list[str] | None = None,
    *,
    run_autoplot_impl: Callable[..., dict[str, Any]],
    serve_intake_impl: Callable[..., None],
) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        handlers = (
            lambda: dispatch_diagnostics(args, argv),
            lambda: dispatch_rendering(
                args,
                argv,
                run_autoplot=run_autoplot_impl,
            ),
            lambda: dispatch_governance(args, argv),
            lambda: dispatch_interfaces(
                args,
                argv,
                serve_intake=serve_intake_impl,
            ),
        )
        for handler in handlers:
            result = handler()
            if result is not None:
                return result
    except Exception as exc:
        recovery_hint = None
        if args.command in {"inspect", "render", "recipe"} and any(
            marker in str(exc).casefold() for marker in _RECOGNITION_ERROR_MARKERS
        ):
            recovery_hint = _recovery_hint(getattr(args, "input", None))
        if getattr(args, "json", False):
            _print_json(
                _cli_runtime_error_payload(
                    exc,
                    recovery_hint=recovery_hint,
                )
            )
            return 1
        print(f"Error: {exc}", file=sys.stderr)
        if recovery_hint is not None:
            print(recovery_hint, file=sys.stderr)
        return 1
    parser.error(f"Unsupported command: {args.command}")
    return 2
