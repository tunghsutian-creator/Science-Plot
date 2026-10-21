"""Dispatch inspection, readiness, doctor, smoke, and probe commands."""

from __future__ import annotations

import sys
from typing import Any

from sciplot_core.cli.value_io import (
    _coerce_sheet,
    _print_json,
    _resolve_input,
)


def dispatch_diagnostics(args: Any, argv: list[str] | None) -> int | None:
    if args.command == "plan":
        from sciplot_core.plan_preview import build_plan_preview

        request = {
            key: value
            for key, value in (
                ("rule_id", args.rule),
                ("template", args.template),
            )
            if value is not None
        }
        if args.template is not None:
            request["explicit_template_selection"] = True
        if getattr(args, "performance_selection", None) is not None:
            from sciplot_core.cli.value_io import _load_options
            from sciplot_core.performance_comparison.selection import parse_performance_selection
            request["performance_selection"] = parse_performance_selection(_load_options("@" + str(args.performance_selection)))
        payload = build_plan_preview(args.input, request=request)
        if args.json:
            _print_json(payload)
        else:
            print(f"SciPlot plan: {payload['status']}")
            transform = payload.get("scientific_transform")
            if isinstance(transform, dict):
                output = transform.get("output")
                series_order = (
                    output.get("series_order") if isinstance(output, dict) else []
                )
                print(
                    "Scientific transform: "
                    f"{transform.get('semantic_family')} "
                    f"({len(series_order) if isinstance(series_order, list) else 0} "
                    "series)"
                )
        return 1 if payload["status"] == "blocked" else 0

    if args.command == "inspect":
        if getattr(args, "performance", False):
            from sciplot_core.performance_comparison.metadata import inspect_performance_metadata
            _print_json(inspect_performance_metadata(_resolve_input(args.input)))
            return 0
        from sciplot_core.render import inspect_payload

        payload = inspect_payload(
            _resolve_input(args.input), sheet=_coerce_sheet(args.sheet)
        )
        if args.json:
            _print_json(payload)
        else:
            print(
                payload.get(
                    "recommendation_summary", "No recommendation summary available."
                )
            )
        return 0

    if args.command == "doctor":
        from sciplot_core.doctor import doctor_payload

        payload = doctor_payload()
        if args.json:
            _print_json(payload)
        else:
            print(f"SciPlot doctor: {payload['status']}")
            print(
                f"Rules: {payload['rule_summary']['ready']} ready, {payload['rule_summary']['pending']} pending"
            )
            for check in payload["checks"]:
                marker = "ok" if check["status"] == "passed" else "failed"
                print(
                    f"{marker}  {check['label']}: {check.get('detail') or check['status']}"
                )
        return 0 if payload["status"] == "ready" else 1

    if args.command == "verify":
        if args.start is not None or args.status is not None:
            from sciplot_core.verification.suite_evidence import (
                start_suite_verification,
                suite_verification_status,
            )

            invalid = args.base is not None or args.plan_only or args.record is not None or args.reuse is not None
            invalid = invalid or (args.start is None and any(
                value is not None for value in (args.out, args.audit_plugin_dir, args.audit_out)
            )) or (args.start is not None and args.out is None)
            if invalid:
                payload = {"status": "BLOCKED", "reused": False, "scientific_acceptance": False,
                           "error": {"reason_code": "invalid_verification_mode",
                                     "message": "Suite start requires --out; base/plan/record/reuse apply only to --changed."}}
            elif args.start is not None:
                payload = start_suite_verification(args.start, directory=args.out,
                    audit_plugin_dir=args.audit_plugin_dir, audit_out=args.audit_out)
            else:
                payload = suite_verification_status(args.status)
            if args.json:
                _print_json(payload)
            else:
                print(f"SciPlot durable verification: {payload['status']}")
                print("Claim: " + payload.get("claim", "no completion proven"))
                if payload.get("directory"):
                    print("Directory: " + payload["directory"])
                if payload.get("kind") == "sciplot_changed_verification_status":
                    print(f"Checks completed: {payload.get('completed_check_count', 0)}/{payload.get('check_count', 0)}")
                    for check in payload["checks"]:
                        print(f"{check['check_id']}: {check['status']}")
                        if check.get("reason"):
                            print(f"  {check['reason']}")
                    if payload.get("reason"):
                        print(payload["reason"])
                if payload.get("error"):
                    print(payload["error"]["message"])
            if payload["status"] == "NO_TESTS":
                return 2
            return 0 if payload["status"] in ("RUNNING", "PASS") else 1

        from sciplot_core.verification import run_changed_verification

        if any(value is not None for value in (args.out, args.audit_plugin_dir, args.audit_out)):
            payload = {"status": "BLOCKED", "reused": False, "scientific_acceptance": False,
                       "error": {"reason_code": "invalid_verification_mode",
                                 "message": "Output and audit attachment options require --start."}}
            if args.json:
                _print_json(payload)
            else:
                print(payload["error"]["message"])
            return 1
        options: dict[str, Any] = {}
        if args.base is not None:
            options["base"] = args.base
        if args.plan_only:
            options["plan_only"] = True
        if args.record is not None:
            options["record"] = args.record
        if args.reuse is not None:
            options["reuse"] = args.reuse
        payload = run_changed_verification(**options)
        if args.json:
            _print_json(payload)
        else:
            print(f"SciPlot changed verification: {payload['status']}")
            owner_ids = [owner["owner_id"] for owner in payload["owners"]]
            print("Owners: " + (", ".join(owner_ids) if owner_ids else "none"))
            print(f"Checks: {len(payload['checks'])}; base: {payload['comparison']['base']}")
            if payload["status"] == "NO_TESTS":
                print("No checks selected; this is not new verification evidence.")
            if payload.get("error"):
                print(payload["error"]["message"])
            for check in payload["checks"]:
                print(f"{check['check_id']}: {check['status']}")
                if check.get("reason"):
                    print(f"  {check['reason']}")
                if check["status"] == "failed":
                    detail = str(check.get("stderr") or check.get("stdout") or "").strip()
                    if detail:
                        print(detail)
            if payload["unowned_paths"]:
                print("Unowned: " + ", ".join(payload["unowned_paths"]))
            for scope, gates in payload["required_later"].items():
                if gates:
                    print(f"{scope}: {', '.join(gates)}")
        if payload["status"] == "NO_TESTS":
            return 2
        return 0 if payload["status"] == "passed" or (args.plan_only and payload["status"] == "planned") else 1

    if args.command == "readiness":
        from sciplot_core.foundation.file_hashing import file_sha256
        from sciplot_core.readiness import (
            build_validated_envelope_registry,
            load_validated_envelope_registry,
            merge_validated_envelope_registry,
            validated_envelope_status,
            write_validated_envelope_registry,
        )

        if args.readiness_command == "status":
            registry_path = (
                _resolve_input(args.registry, kind="Validated-envelope registry")
                if args.registry is not None
                else None
            )
            registry = (
                load_validated_envelope_registry(registry_path)
                if registry_path is not None
                else None
            )
            payload = validated_envelope_status(registry, registry_path=registry_path)
            if args.json:
                _print_json(payload)
            else:
                print(f"SciPlot readiness: {payload['status']}")
                print(
                    f"Current validated envelopes: {payload['ready_without_ai_rule_count']}/{payload['current_ready_rule_count']}"
                )
            return 0 if payload["status"] == "ready" else 1
        if args.readiness_command == "merge":
            base_path = _resolve_input(
                args.base_registry,
                kind="Base validated-envelope registry",
            )
            acceptance_summary = _resolve_input(
                args.acceptance_summary,
                kind="Ready-rule acceptance summary",
            )
            registry = merge_validated_envelope_registry(
                load_validated_envelope_registry(base_path),
                acceptance_summary,
            )
            output = write_validated_envelope_registry(args.out, registry)
            selected_rule_ids = list(
                registry.source_acceptance["records"][-1]["rule_ids"]
            )
            payload = {
                "kind": "sciplot_validated_envelope_scoped_merge",
                "version": 1,
                "status": "ready",
                "selected_rule_ids": selected_rule_ids,
                "base_registry": str(base_path),
                "acceptance_summary": str(acceptance_summary),
                "registry": str(output),
            }
            if args.json:
                _print_json(payload)
            else:
                print(
                    "SciPlot readiness scoped merge: "
                    + ", ".join(selected_rule_ids)
                )
                print(payload["registry"])
            return 0
        acceptance_summary = _resolve_input(
            args.acceptance_summary, kind="Ready-rule acceptance summary"
        )
        registry = build_validated_envelope_registry(acceptance_summary)
        output = write_validated_envelope_registry(args.out, registry)
        status = validated_envelope_status(registry)
        payload = {
            "kind": "sciplot_validated_envelope_certification",
            "version": 1,
            "status": status["status"],
            "acceptance_summary": str(acceptance_summary.resolve()),
            "registry": str(output),
            "registry_sha256": file_sha256(output),
            "envelopes": status,
        }
        if args.json:
            _print_json(payload)
        else:
            print(f"SciPlot readiness certification: {payload['status']}")
            print(payload["registry"])
        return 0 if payload["status"] == "ready" else 1

    if args.command == "smoke":
        from sciplot_core.studio import maybe_reexec_with_qt_runtime

        original_argv = list(sys.argv[1:] if argv is None else argv)
        maybe_reexec_with_qt_runtime(original_argv)
        from sciplot_core.smoke import run_runtime_smoke

        profile = getattr(args, "profile", "full")
        payload = (
            run_runtime_smoke(output_root=args.out, profile="quick")
            if profile == "quick"
            else run_runtime_smoke(output_root=args.out)
        )
        if args.json:
            _print_json(payload)
        else:
            print(f"SciPlot runtime smoke: {payload['status']}")
            print(payload["artifacts"]["summary"])
        return 0 if payload["status"] == "passed" else 1

    if args.command == "readiness-probe":
        from sciplot_core.readiness_probe import run_readiness_probe

        payload = run_readiness_probe(output_root=args.out)
        if args.json:
            _print_json(payload)
        else:
            print(f"SciPlot readiness probe: {payload['status']}")
            print(payload["artifacts"]["summary"])
        return 0 if payload["status"] == "passed" else 1

    if args.command == "openai-provider-probe":
        from sciplot_core.openai_provider_probe import run_openai_provider_probe

        payload = run_openai_provider_probe(output_root=args.out)
        if args.json:
            _print_json(payload)
        else:
            print(f"SciPlot OpenAI provider probe: {payload['status']}")
            print(payload["artifacts"]["summary"])
        return 0 if payload["status"] == "passed" else 1

    if args.command == "data-mapping-probe":
        from sciplot_core.data_mapping_probe import run_data_mapping_probe

        payload = run_data_mapping_probe(output_root=args.out)
        if args.json:
            _print_json(payload)
        else:
            print(f"SciPlot data mapping probe: {payload['status']}")
            print(payload["artifacts"]["summary"])
        return 0 if payload["status"] == "passed" else 1

    if args.command == "automation-baseline":
        from sciplot_core.studio import maybe_reexec_with_qt_runtime

        original_argv = list(sys.argv[1:] if argv is None else argv)
        maybe_reexec_with_qt_runtime(original_argv)
        from sciplot_core.automation_baseline_probe import (
            run_automation_baseline_probe,
        )

        payload = run_automation_baseline_probe(
            output_root=args.out,
            repetitions=args.repetitions,
        )
        if args.json:
            _print_json(payload)
        else:
            print(f"SciPlot R0 automation baseline: {payload['status']}")
            print(payload["artifacts"]["markdown"])
        return 0 if payload["status"] == "passed" else 1
    return None
