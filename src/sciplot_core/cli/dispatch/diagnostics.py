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
    if args.command == "inspect":
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

    if args.command == "readiness":
        from sciplot_core.foundation.file_hashing import file_sha256
        from sciplot_core.readiness import (
            build_validated_envelope_registry,
            load_validated_envelope_registry,
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

        payload = run_runtime_smoke(output_root=args.out)
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
    return None
