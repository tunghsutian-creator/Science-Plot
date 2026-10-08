"""Dispatch render, recipe, replay, and fully automated plotting commands."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from sciplot_core.cli.value_io import (
    _coerce_sheet,
    _load_options,
    _print_json,
    _resolve_input,
)


def _render_auto(source: Path, args: Any, options: dict[str, Any]) -> dict[str, Any]:
    """Keep automatic selection on the existing scientific production workflow."""
    from sciplot_core.foundation.json_io import atomic_write_json
    from sciplot_core.foundation.path_names import reserve_unique_file
    from sciplot_core.materials_rules.catalog import resolve_rule_template
    from sciplot_core.policy import AUTOPLOT_RENDER_OPTIONS, DEFAULT_EXPORT_FORMATS_POLICY
    from sciplot_core.render import inspect_payload
    from sciplot_core.request_contract import normalize_render_options
    from sciplot_core.workflow import run_request

    if _coerce_sheet(args.sheet) != 0:
        raise ValueError(
            "render --auto cannot bind a non-default worksheet. Use task create/start "
            "and its source-bound table selection; no worksheet is chosen silently."
        )
    inspection = inspect_payload(source)
    resolution = inspection.get("inspection_resolution")
    if (not isinstance(resolution, dict)
            or resolution.get("status") != "ready_rule_authoritative"
            or not isinstance(resolution.get("rule_id"), str)):
        raise ValueError(
            "--auto requires an authoritative ready material rule; use task create "
            "to resolve scientific choices. A generic recommendation cannot select a renderer."
        )
    rule_id = resolution["rule_id"]
    template = resolve_rule_template(rule_id, args.template)
    explicit = normalize_render_options(options, template=template)
    source, output = source.resolve(), args.out.expanduser().resolve()
    if source.is_relative_to(output) or (source.is_dir() and output.is_relative_to(source)):
        raise ValueError("Automatic output and original source must be separate; choose --out outside the source tree.")
    request: dict[str, Any] = {
        "recipe": "auto", "input": str(source), "output": str(output),
        "rule_id": rule_id, "template": template,
        "exports": list(DEFAULT_EXPORT_FORMATS_POLICY),
        "render_options": {**normalize_render_options(AUTOPLOT_RENDER_OPTIONS), **explicit},
        "explicit_render_option_keys": sorted(explicit),
    }
    if args.template is not None:
        request["explicit_template_selection"] = True
    request_path = reserve_unique_file(output, "render_auto_request.json")
    atomic_write_json(request_path, request)
    return run_request(request_path)


def dispatch_rendering(
    args: Any, argv: list[str] | None, *, run_autoplot
) -> int | None:
    if args.command == "render":
        from sciplot_core.render import render_to_dir

        source = _resolve_input(args.input)
        sheet = _coerce_sheet(args.sheet)
        template = args.template
        options = _load_options(args.options)
        if args.auto:
            if not isinstance(options, dict):
                raise ValueError("render --auto --options requires a JSON object.")
            payload = _render_auto(source, args, options)
            _print_json(payload)
            return 0 if payload.get("state") == "ready" and payload.get("ready_to_use") is True else 1
        if not template:
            raise ValueError(
                "render needs a template: pass --template NAME, or --auto to choose one."
            )
        payload = render_to_dir(
            source,
            template=template,
            output_dir=args.out.expanduser(),
            sheet=sheet,
            options=options,
        )
        _print_json(payload)
        return 0

    if args.command == "recipe":
        from sciplot_recipes import run_recipe

        payload = run_recipe(
            args.name,
            _resolve_input(args.input),
            output_dir=args.out.expanduser(),
            options=_load_options(args.options),
        )
        _print_json(payload)
        return 0

    if args.command == "run":
        from sciplot_core.workflow import run_request

        payload = run_request(_resolve_input(args.request, kind="Request file"))
        _print_json(payload)
        one_step = (
            payload.get("one_step") if isinstance(payload.get("one_step"), dict) else {}
        )
        state = str(payload.get("state") or one_step.get("state") or "").strip()
        return 0 if state == "ready" and payload.get("ready_to_use") is True else 1

    if args.command == "autoplot":
        from sciplot_core.output_contract import resolve_user_output_layout

        source = args.input if args.rule is not None else _resolve_input(args.input)
        layout = resolve_user_output_layout(
            source, requested_delivery_root=args.out, project_name=args.name
        )
        expected = None
        if args.expected_plan is not None:
            expected = _load_options("@" + str(args.expected_plan))
            if not isinstance(expected, dict):
                raise ValueError("--expected-plan must contain one plan JSON object.")
        payload = run_autoplot(
            source,
            output_root=layout.workspace_root / "autoplot_projects",
            project_name=args.name,
            delivery_root=layout.delivery_root,
            rule_id=args.rule,
            template=args.template,
            **({"expected_plan": expected} if expected is not None else {}),
        )
        if args.json:
            _print_json(payload)
        else:
            print(payload["delivery"] or payload["run_output"])
        return (
            0
            if payload.get("state") == "ready" and payload.get("ready_to_use") is True
            else 1
        )
    return None
