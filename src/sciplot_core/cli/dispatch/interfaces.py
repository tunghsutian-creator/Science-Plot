"""Dispatch headless Studio, publication and QA commands."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from sciplot_core.cli.value_io import (
    _print_json,
)


class ManualEditorRetired(ValueError):
    reason_code = "manual_editor_retired"


class BrowserIntakeRetired(ValueError):
    reason_code = "browser_intake_retired"


def dispatch_interfaces(
    args: Any, argv: list[str] | None,
) -> int | None:
    if args.command == "edit":
        raise ManualEditorRetired(
            "manual_editor_retired: The manual editor has been retired. "
            "Ask your AI client to use sciplot task edit TARGET --intent INTENT "
            "or sciplot plot describe PLOT --scope edit --json. "
            "This command does not inspect or change the target."
        )

    if args.command == "mcp":
        from sciplot_core.mcp_server import run_stdio

        run_stdio()
        return 0
    if args.command == "task":
        from sciplot_core.cli.dispatch.tasks import dispatch_task

        return dispatch_task(args)
    if args.command == "project":
        from sciplot_core.cli.dispatch.project import dispatch_project_control

        return dispatch_project_control(args)

    if args.command == "app":
        raise BrowserIntakeRetired(
            "browser_intake_retired: Use task create for local original sources, "
            "then answer its source-bound table and scientific questions. "
            "The retired browser command does not open or change the input."
        )

    if args.command == "studio":
        from sciplot_core.cli.dispatch.project_revision import dispatch_project_revision

        revision_result = dispatch_project_revision(args)
        if revision_result is not None:
            return revision_result
        from sciplot_core.studio import run_studio_command

        if args.new or args.qt_smoke or not (args.json or args.export or args.prepare_only):
            from sciplot_core.studio_core.studio_command import NativeInterfaceRetired

            raise NativeInterfaceRetired(
                "native_gui_retired: Use task create/edit or project inspect, "
                "and studio --json/--export for saved native documents. "
                "This command does not open a window or change the target."
            )
        original_argv = list(sys.argv[1:] if argv is None else argv)
        studio_target = args.target.expanduser() if args.target else None
        if studio_target is not None:
            from sciplot_core.studio_core.delivery_target import resolve_delivery_target

            delivery_target = resolve_delivery_target(studio_target.resolve())
            if delivery_target is not None:
                studio_target = Path(
                    delivery_target["project_dir"]
                    if delivery_target["mode"] == "project"
                    else delivery_target["document"]
                )
        studio_output_root = args.out.expanduser() if args.out else None
        studio_delivery_root = None
        if studio_target is not None:
            resolved_target = studio_target.resolve()
            is_vsz = resolved_target.suffix.casefold() == ".vsz"
            is_request = resolved_target.suffix.casefold() == ".json"
            is_project = (
                resolved_target.is_dir()
                and (resolved_target / "plot_request.json").is_file()
            )
            if not is_vsz:
                from sciplot_core.output_contract import resolve_user_output_layout

                if is_project or is_request:
                    studio_delivery_root = studio_output_root
                    studio_output_root = None
                else:
                    layout = resolve_user_output_layout(
                        resolved_target,
                        requested_delivery_root=studio_output_root,
                        project_name=args.name,
                    )
                    studio_delivery_root = layout.delivery_root
                    studio_output_root = layout.workspace_root / "projects"
        return run_studio_command(
            target=studio_target,
            output_root=studio_output_root,
            delivery_root=studio_delivery_root,
            rule_id=args.rule,
            template=args.template,
            project_name=args.name,
            new=args.new,
            export=args.export,
            json_output=args.json,
            prepare_only=args.prepare_only,
            qt_smoke=args.qt_smoke,
            original_argv=original_argv,
        )

    if args.command == "publication":
        from sciplot_core.publication import (
            build_composite_layout,
            get_publication_profile,
            list_composite_layouts,
            list_publication_profiles,
        )

        if args.publication_command == "profiles":
            payload = {
                "kind": "sciplot_publication_profiles",
                "profiles": list_publication_profiles(),
            }
        elif args.publication_command == "profile":
            payload = get_publication_profile(args.profile_id)
        elif args.publication_command == "layouts":
            payload = {
                "kind": "sciplot_composite_layouts",
                "layouts": list_composite_layouts(),
            }
        else:
            payload = build_composite_layout(
                args.layout_id, canvas_height_mm=args.height_mm
            )
        if args.json:
            _print_json(payload)
        else:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0

    if args.command == "qa":
        from sciplot_core.qa import run_qa

        payload = run_qa(
            args.output_dir.expanduser(),
            goldens_dir=args.goldens.expanduser() if args.goldens else None,
            require_all_goldens=args.strict_goldens,
            publication_profile=args.publication_profile,
            strict_publication=args.strict_publication,
        )
        _print_json(payload)
        return 0 if payload.get("status") == "passed" else 1
    return None
