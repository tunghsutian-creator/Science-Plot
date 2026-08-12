"""Dispatch render, recipe, replay, and fully automated plotting commands."""

from __future__ import annotations

from typing import Any

from sciplot_core.cli.value_io import (
    _coerce_sheet,
    _load_options,
    _print_json,
    _resolve_input,
)


def dispatch_rendering(
    args: Any, argv: list[str] | None, *, run_autoplot
) -> int | None:
    if args.command == "render":
        from sciplot_core.render import inspect_payload, render_to_dir

        source = _resolve_input(args.input)
        sheet = _coerce_sheet(args.sheet)
        template = args.template
        options = _load_options(args.options)
        if args.auto:
            inspection = inspect_payload(source, sheet=sheet)
            resolution = inspection.get("inspection_resolution")
            if (
                isinstance(resolution, dict)
                and resolution.get("status") != "ready_rule_authoritative"
            ):
                raise ValueError(
                    "--auto refused an unverified material-rule candidate; inspect or repair the source, or pass --template and --options explicitly."
                )
            recommendations = inspection.get("recommendations") or []
            if not recommendations:
                raise ValueError(
                    "--auto could not recommend a template; pass --template and --options explicitly."
                )
            top = recommendations[0]
            template = template or str(top.get("template_id"))
            defaults = top.get("default_render_overrides")
            if isinstance(defaults, dict):
                options = {**defaults, **options}
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
        payload = run_autoplot(
            source,
            output_root=layout.workspace_root / "autoplot_projects",
            project_name=args.name,
            delivery_root=layout.delivery_root,
            rule_id=args.rule,
            template=args.template,
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
