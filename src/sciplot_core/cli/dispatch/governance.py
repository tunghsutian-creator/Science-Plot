"""Dispatch acceptance, curation, rule, cleanup, mapping, and batch commands."""

from __future__ import annotations

import sys
from typing import Any

from sciplot_core.cli.value_io import (
    _load_options,
    _print_json,
    _resolve_input,
)


def dispatch_governance(args: Any, argv: list[str] | None) -> int | None:
    if args.command == "acceptance":
        if args.acceptance_command == "3dpa":
            from sciplot_core.acceptance import run_3dpa_acceptance

            payload = run_3dpa_acceptance(
                _resolve_input(args.input),
                output_root=args.out.expanduser(),
                project_name=args.name,
                representative_count=args.representative_count,
                dense_series_count=args.dense_series,
            )
            if args.json:
                _print_json(payload)
            else:
                print(payload["project_dir"])
            return 0
        if args.acceptance_command == "rules":
            from sciplot_core.studio import maybe_reexec_with_qt_runtime

            original_argv = list(sys.argv[1:] if argv is None else argv)
            maybe_reexec_with_qt_runtime(original_argv)
            from sciplot_core.acceptance import run_rule_acceptance_suite

            payload = run_rule_acceptance_suite(
                output_root=args.out.expanduser(),
                project_name=args.name,
                rule_ids=args.rule_ids,
            )
            if args.json:
                _print_json(payload)
            else:
                print(payload["artifacts"]["matrix_markdown"])
            return 0 if payload["selected_state"] == "ready" else 1
        if args.acceptance_command == "visual-review":
            from sciplot_core.visual_review import record_final_size_visual_decision

            payload = record_final_size_visual_decision(
                _resolve_input(args.review_json, kind="Visual review JSON"),
                reviewer=args.reviewer,
                decision=args.decision,
                notes=args.notes or (),
            )
            if args.json:
                _print_json(payload)
            else:
                print(payload["decision_path"])
            return 0 if args.decision == "passed" else 1

    if args.command == "curate":
        if args.curate_command == "torque":
            from sciplot_core.studio import maybe_reexec_with_qt_runtime

            original_argv = list(sys.argv[1:] if argv is None else argv)
            maybe_reexec_with_qt_runtime(original_argv)
            from sciplot_core.curate import curate_torque_project

            payload = curate_torque_project(
                args.input.expanduser(),
                output_root=args.out.expanduser(),
                project_name=args.name,
                open_review=args.open,
            )
            if args.json:
                _print_json(payload)
            else:
                print(payload["review_html"])
            return 0

    if args.command == "rules":
        from sciplot_core.materials_rules.catalog import (
            list_rules_payload,
            show_rule_payload,
        )
        from sciplot_core.readiness.registry_io import (
            load_validated_envelope_registry,
        )
        from sciplot_core.readiness.rule_certification import (
            current_rule_invocation_contract_payload,
        )

        registry = load_validated_envelope_registry()

        def invocation_projector(rule: Any) -> dict[str, Any]:
            return current_rule_invocation_contract_payload(
                rule=rule,
                registry=registry,
            )

        if args.rules_command == "list":
            payload = list_rules_payload(
                include_pending=args.all,
                invocation_projector=invocation_projector,
            )
            if args.json:
                _print_json(payload)
            else:
                for item in payload["rules"]:
                    status = (
                        ""
                        if item.get("fixture_status") == "ready"
                        else f" [{item['fixture_status']}]"
                    )
                    print(f"{item['rule_id']}{status}: {item['x']} -> {item['y']}")
            return 0
        if args.rules_command == "show":
            payload = show_rule_payload(
                args.rule_id,
                invocation_projector=invocation_projector,
            )
            if args.json:
                _print_json(payload)
            else:
                x_label = payload["axis_plan"]["x"]["display_label"]
                y_label = payload["axis_plan"]["y"]["display_label"]
                print(f"{payload['rule_id']}: {x_label} -> {y_label}")
            return 0

    if args.command == "cleanup":
        from sciplot_core.assisted_cleanup import (
            load_cleanup_result,
            write_cleanup_result,
        )

        if args.cleanup_command == "result":
            payload = write_cleanup_result(
                args.output_dir.expanduser(),
                cleaned_data=_resolve_input(args.cleaned_data, kind="Cleaned data"),
                mapping_proposal=_load_options(args.mapping),
                confidence=args.confidence,
                human_confirmed=args.confirm,
                raw_inputs=[path.expanduser() for path in args.raw_input or []],
                notes=args.notes,
                provider=args.provider,
            )
            if args.json:
                _print_json(payload)
            else:
                print(payload["cleanup_result"])
            return 0
        if args.cleanup_command == "show":
            payload = load_cleanup_result(args.target.expanduser())
            if args.json:
                _print_json(payload)
            else:
                print(
                    f"{payload.get('cleaned_data', {}).get('path', '')} ready={payload.get('ready_for_normal_mode', False)}"
                )
            return 0

    if args.command == "mapping":
        from sciplot_core.data_mapping import (
            create_data_mapping_confirmation,
            execute_data_mapping_proposal,
            load_data_mapping_execution,
            preview_data_mapping_proposal,
            write_data_mapping_confirmation,
        )

        proposal_path = (
            _resolve_input(args.proposal, kind="DataMappingProposal")
            if hasattr(args, "proposal")
            else None
        )
        if args.mapping_command == "preview":
            payload = preview_data_mapping_proposal(
                proposal_path,
                source_root=_resolve_input(
                    args.source_root, kind="Data mapping source root"
                ),
                request_path=_resolve_input(args.request, kind="Plot request"),
            )
            if args.json:
                _print_json(payload)
            else:
                print(
                    f"{payload['status']}: {len(payload['sources'])} source(s), no writes performed"
                )
            return 0
        if args.mapping_command == "confirm":
            confirmation = create_data_mapping_confirmation(
                proposal_path,
                source_root=_resolve_input(
                    args.source_root, kind="Data mapping source root"
                ),
                request_path=_resolve_input(args.request, kind="Plot request"),
                output_root=args.execution_root.expanduser().resolve(),
                confirmed_by=args.by,
            )
            destination = (
                args.out.expanduser()
                if args.out is not None
                else proposal_path.parent / "confirmation.json"
            )
            written = write_data_mapping_confirmation(destination, confirmation)
            payload = {**confirmation.to_dict(), "path": str(written)}
            if args.json:
                _print_json(payload)
            else:
                print(written)
            return 0
        if args.mapping_command == "execute":
            payload = execute_data_mapping_proposal(
                proposal_path,
                _resolve_input(args.confirmation, kind="Data mapping confirmation"),
                source_root=_resolve_input(
                    args.source_root, kind="Data mapping source root"
                ),
                request_path=_resolve_input(args.request, kind="Plot request"),
                output_root=args.out.expanduser(),
            )
            if args.json:
                _print_json(payload)
            else:
                print(payload["request_candidate"])
            return 0
        if args.mapping_command == "show":
            payload = load_data_mapping_execution(
                _resolve_input(args.target, kind="Data mapping execution")
            )
            if args.json:
                _print_json(payload)
            else:
                print(
                    f"{payload['status']}: {payload['proposal_id']} -> {payload['request_candidate']}"
                )
            return 0

    if args.command == "batch":
        from sciplot_core.batch import run_batch

        _print_json(
            run_batch(
                args.input_dir.expanduser(),
                output_dir=args.out.expanduser(),
                mode=args.mode,
                tensile_roots=args.tensile_root,
            )
        )
        return 0
    return None
