"""Coordinate the complete fixture-free runtime smoke gate."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_values import json_safe

from sciplot_core.smoke.contracts import (
    RUNTIME_SMOKE_VERSION,
    EXPECTED_RULE_ID,
    MANUAL_EDIT_MARKER,
    _check,
    _delivery_artifact,
)

from sciplot_core.smoke.delivery import (
    _delivery_layout_probe,
)

from sciplot_core.smoke.runtime_environment import (
    _package_import_probe,
    _source_checkout_wrapper_probe,
    _qt_mainwindow_probe,
    _portable_launcher_probe,
    _relocated_delivery_launcher_probe,
    _standalone_export_probe,
)

from sciplot_core.smoke.data_mapping import (
    _write_synthetic_ftir,
    _data_mapping_studio_lifecycle_probe,
)

from sciplot_core.smoke.semantic_parser import (
    _semantic_parser_probe,
)

from sciplot_core.smoke.scalar_field import (
    _scalar_field_render_probe,
)


def _run_hash_failure_probe(
    output_dir: Path, manifest: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    from sciplot_core.delivery import build_delivery_package

    mismatched_manifest = copy.deepcopy(manifest)
    mismatched_manifest["exported_document_hash"] = "0" * 64
    if isinstance(mismatched_manifest.get("veusz_document_hashes"), dict):
        mismatched_manifest["veusz_document_hashes"] = {
            path: "0" * 64 for path in mismatched_manifest["veusz_document_hashes"]
        }
    rejected = build_delivery_package(output_dir, manifest=mismatched_manifest)
    hash_gate = _delivery_artifact(rejected, "editable_vsz_hash_match")
    rejected_as_expected = (
        rejected.get("complete") is False and hash_gate.get("exists") is False
    )

    restored = build_delivery_package(output_dir, manifest=manifest)
    restored_successfully = restored.get("complete") is True
    return rejected_as_expected and restored_successfully, {
        "mismatched_delivery_complete": rejected.get("complete"),
        "mismatched_hash_gate": hash_gate,
        "restored_delivery_complete": restored.get("complete"),
    }


def run_runtime_smoke(*, output_root: Path) -> dict[str, Any]:
    """Run a fixture-free end-to-end Studio lifecycle and delivery failure probe."""

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(tempfile.mkdtemp(prefix="runtime_smoke_", dir=resolved_output))
    summary_path = run_root / "runtime_smoke.json"
    checks: list[dict[str, Any]] = []
    fixture: dict[str, Any] | None = None
    manifest_path: Path | None = None
    project_dir: Path | None = None
    error: dict[str, str] | None = None

    try:
        import_probe = _package_import_probe()
        checks.append(
            _check(
                "package_import_isolated",
                "Importing sciplot_core does not activate the removed compatibility path",
                import_probe.get("passed") is True,
                detail=import_probe,
            )
        )
        wrapper_probe = _source_checkout_wrapper_probe()
        checks.append(
            _check(
                "source_checkout_wrapper_bootstraps",
                "The source wrapper or installed CLI starts without relying on an editable import leak",
                wrapper_probe.get("passed") is True,
                detail=wrapper_probe,
            )
        )
        from sciplot_core.data_mapping_probe import run_data_mapping_probe

        data_mapping_probe = run_data_mapping_probe(
            output_root=run_root / "data_mapping"
        )
        checks.append(
            _check(
                "deterministic_data_mapping_lifecycle",
                "DataMappingProposal v2 previews without writes, requires an "
                "external confirmation receipt, executes atomically, preserves "
                "raw sources, records transform lineage, and rejects stale or "
                "tampered state",
                data_mapping_probe.get("status") == "passed",
                detail=data_mapping_probe,
            )
        )
        from sciplot_core.readiness_probe import run_readiness_probe

        readiness_probe = run_readiness_probe(output_root=run_root / "readiness")
        readiness_registry = readiness_probe.get("registry_status") or {}
        checks.append(
            _check(
                "validated_ready_envelopes",
                "All current accepted rule contracts remain bound to authorized "
                "real-data evidence, reject contract drift and provider-authored "
                "ready flags, and gate one-step readiness",
                readiness_probe.get("status") == "passed",
                detail={
                    "status": readiness_probe.get("status"),
                    "passed_count": readiness_probe.get("passed_count"),
                    "check_count": readiness_probe.get("check_count"),
                    "ready_without_ai_rule_count": readiness_registry.get(
                        "ready_without_ai_rule_count"
                    ),
                    "evidence_strength_counts": readiness_registry.get(
                        "evidence_strength_counts"
                    ),
                    "artifacts": readiness_probe.get("artifacts"),
                },
            )
        )

        from sciplot_core.doctor import doctor_payload
        from sciplot_core.studio import (
            export_studio_document,
            prepare_studio_document,
            publish_studio_export_run,
        )

        doctor = doctor_payload()
        checks.append(
            _check(
                "runtime_ready",
                "Required runtime dependencies and rule registry are ready",
                doctor.get("status") == "ready",
                detail={
                    "status": doctor.get("status"),
                    "ready_rules": (doctor.get("rule_summary") or {}).get("ready"),
                },
            )
        )
        from sciplot_core.policy import (
            DEFAULT_LOG_MINOR_MULTIPLIERS,
            DEFAULT_LOG_MINOR_TICK_COUNT,
            RHEOLOGY_FREQUENCY_RENDER_OPTIONS,
        )
        from sciplot_core.style_contract import audit_style_template_contract

        log_tick_policy = {
            "subdivisions_per_decade": DEFAULT_LOG_MINOR_TICK_COUNT,
            "visible_minor_multipliers": list(DEFAULT_LOG_MINOR_MULTIPLIERS),
            "rheology_frequency_minor_tick_count": (
                RHEOLOGY_FREQUENCY_RENDER_OPTIONS.get("minor_tick_count")
            ),
        }
        checks.append(
            _check(
                "sparse_log_minor_tick_policy",
                "Log modulus axes retain four visible minor ticks per decade",
                DEFAULT_LOG_MINOR_TICK_COUNT == 5
                and DEFAULT_LOG_MINOR_MULTIPLIERS == (2.0, 4.0, 6.0, 8.0)
                and RHEOLOGY_FREQUENCY_RENDER_OPTIONS.get("minor_tick_count")
                == DEFAULT_LOG_MINOR_TICK_COUNT,
                detail=log_tick_policy,
            )
        )
        style_template_audit = audit_style_template_contract()
        checks.append(
            _check(
                "unified_figure_style_contract",
                "Templates and figure profiles consume the global style contract",
                style_template_audit.get("status") == "passed",
                detail=style_template_audit,
            )
        )
        qt_mainwindow_probe = _qt_mainwindow_probe()
        checks.append(
            _check(
                "qt_mainwindow_constructs",
                "The complete Veusz editor constructs without optional examples or macOS settings noise",
                qt_mainwindow_probe.get("passed") is True,
                detail=qt_mainwindow_probe,
            )
        )
        normal_mode = (
            doctor.get("normal_mode")
            if isinstance(doctor.get("normal_mode"), dict)
            else {}
        )
        checks.append(
            _check(
                "independent_mode",
                "Veusz is the normal frontend and its optional assistant starts independent and hidden",
                normal_mode.get("frontend_default") == "veusz_mainwindow"
                and normal_mode.get("assistant_default") == "independent"
                and normal_mode.get("assistant_visibility_default") == "hidden"
                and normal_mode.get("codex_required") is False
                and normal_mode.get("user_switch_required") is False,
                detail=normal_mode,
            )
        )

        parser_probe = _semantic_parser_probe(run_root)
        checks.append(
            _check(
                "promoted_semantic_parsers",
                "Generated SAXS, Agilent GPC, impact, and explicit-intent swelling contracts parse deterministically",
                parser_probe.get("passed") is True,
                detail=parser_probe,
            )
        )
        from sciplot_core.analysis_contract_probe import (
            run_analysis_contract_probe,
        )
        from sciplot_core.inspection_contract_probe import (
            run_inspection_contract_probe,
        )
        from sciplot_core.semantic_contract_probe import (
            run_semantic_contract_probe,
        )

        analysis_contract_probe = run_analysis_contract_probe(
            output_root=run_root / "analysis_contract_probe"
        )
        checks.append(
            _check(
                "scientific_analysis_contracts",
                "Scientific metrics use the confirmed metric columns, "
                "per-series extrema, and conservative interpretation rules",
                analysis_contract_probe.get("status") == "passed",
                detail=analysis_contract_probe,
            )
        )
        semantic_contract_probe = run_semantic_contract_probe(
            run_root / "semantic_contract_probe"
        )
        checks.append(
            _check(
                "scientific_semantic_contracts",
                "Scientific preprocessing preserves units, interval identity, "
                "log domains, and complete in-scope source coverage",
                semantic_contract_probe.get("status") == "passed",
                detail=semantic_contract_probe,
            )
        )
        inspection_contract_probe = run_inspection_contract_probe(
            run_root / "inspection_contract_probe"
        )
        checks.append(
            _check(
                "inspection_warning_authority",
                "Ready material rules own presentation warnings without hiding unresolved data risks",
                inspection_contract_probe.get("status") == "passed",
                detail=inspection_contract_probe,
            )
        )

        scalar_probe = _scalar_field_render_probe(run_root)
        checks.append(
            _check(
                "scalar_field_render",
                "Synthetic XYZ data render through Veusz with visible contours and colorbar",
                scalar_probe.get("passed") is True,
                detail=scalar_probe,
            )
        )
        scalar_document = Path(str(scalar_probe.get("document") or ""))
        qt_scalar_document_probe = _qt_mainwindow_probe(scalar_document)
        checks.append(
            _check(
                "qt_scalar_vsz_loads",
                "The Studio GUI runtime loads a saved 2D scalar-field VSZ with its dataset and page",
                qt_scalar_document_probe.get("passed") is True,
                detail=qt_scalar_document_probe,
            )
        )

        from sciplot_core.qa import _normalized_label

        qa_label_probe = {
            "veusz_label": r"LS\_5CRW\_20W\_t1",
            "pdf_label": "LS_5CRW_20W_t1",
        }
        qa_label_probe["normalized_veusz_label"] = _normalized_label(
            qa_label_probe["veusz_label"]
        )
        qa_label_probe["normalized_pdf_label"] = _normalized_label(
            qa_label_probe["pdf_label"]
        )
        checks.append(
            _check(
                "veusz_pdf_label_equivalence",
                "Escaped Veusz labels match their rendered PDF text",
                qa_label_probe["normalized_veusz_label"]
                == qa_label_probe["normalized_pdf_label"],
                detail=qa_label_probe,
            )
        )

        from sciplot_core.request_contract import apply_request_patch

        option_provenance_probe = apply_request_patch(
            {
                "exports": ["pdf", "tiff_300"],
                "render_options": {"size": "60x55", "legend_position": "auto"},
                "explicit_render_option_keys": [],
            },
            render_options={"size": "120x55"},
        )
        checks.append(
            _check(
                "explicit_render_option_provenance",
                "A user-selected render option becomes authoritative without promoting semantic defaults",
                option_provenance_probe.get("explicit_render_option_keys") == ["size"]
                and (option_provenance_probe.get("render_options") or {}).get("size")
                == "120x55"
                and (option_provenance_probe.get("render_options") or {}).get(
                    "legend_position"
                )
                == "auto",
                detail=option_provenance_probe,
            )
        )

        from sciplot_core.materials_rules import get_rule
        from sciplot_core.studio import _apply_studio_request_overrides

        override_project = run_root / "explicit_rule_override"
        override_project.mkdir(parents=True, exist_ok=True)
        override_request_path = override_project / "plot_request.json"
        previous_rule = get_rule("swelling_curve")
        previous_options = {
            **previous_rule.render_options,
            "x_label_override": previous_rule.x_axis.display_label,
            "y_label_override": previous_rule.y_axis.display_label,
            "size": "180x55",
        }
        override_request_path.write_text(
            json.dumps(
                {
                    "recipe": "auto",
                    "rule_id": previous_rule.rule_id,
                    "template": previous_rule.template,
                    "render_options": previous_options,
                    "explicit_render_option_keys": ["size"],
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        _apply_studio_request_overrides(
            override_project,
            request_path=override_request_path,
            rule_id="saxs_profile",
        )
        overridden_request = json.loads(
            override_request_path.read_text(encoding="utf-8")
        )
        overridden_options = overridden_request.get("render_options") or {}
        checks.append(
            _check(
                "existing_project_explicit_rule_override",
                "An explicit rule replaces prior semantic defaults while preserving user render choices",
                overridden_request.get("rule_id") == "saxs_profile"
                and overridden_request.get("template") == "curve"
                and overridden_request.get("explicit_render_option_keys") == ["size"]
                and overridden_options.get("size") == "180x55"
                and overridden_options.get("x_label_override") == r"q (nm$^{-1}$)"
                and overridden_options.get("y_label_override") == "Intensity (a.u.)"
                and overridden_options.get("xscale") == "log"
                and overridden_options.get("yscale") == "log"
                and "marker_sequence" not in overridden_options,
                detail=overridden_request,
            )
        )

        fixture_path = run_root / "fixture" / "ftir_runtime_smoke.csv"
        fixture = _write_synthetic_ftir(fixture_path)
        prepared = prepare_studio_document(
            fixture_path,
            output_root=run_root / "projects",
            project_name="Synthetic FTIR runtime smoke",
        )
        project_dir = Path(str(prepared["project_dir"]))
        request_path = Path(str(prepared["request"]))
        document_path = Path(str(prepared["document"]))
        mapped_studio_probe = _data_mapping_studio_lifecycle_probe(
            run_root=run_root,
            source_path=fixture_path,
            base_request_path=request_path,
        )
        checks.append(
            _check(
                "mapped_project_studio_lifecycle",
                "A confirmed mapping candidate uses the standard project "
                "entrypoint, preserves raw input, retains every mapped sample, "
                "records causal lineage, and completes VSZ, QA, and delivery",
                mapped_studio_probe.get("passed") is True,
                detail=mapped_studio_probe,
            )
        )
        from sciplot_core.studio_project_probe import (
            run_studio_project_probe,
        )

        studio_project_probe = run_studio_project_probe(
            project_dir,
            output_root=run_root / "studio_project",
            mapped_document=Path(str(mapped_studio_probe["document"])),
        )
        checks.append(
            _check(
                "veusz_mainwindow_project_integration",
                "One native Veusz MainWindow keeps Project and AI docks opt-in, "
                "tracks live VSZ/source/mapping/QA truth, rejects stale QA, and "
                "exports both project and standalone exact-current receipts",
                studio_project_probe.get("status") == "passed",
                detail={
                    "status": studio_project_probe.get("status"),
                    "summary": studio_project_probe.get("summary"),
                    "artifacts": studio_project_probe.get("artifacts"),
                },
            )
        )
        from sciplot_core.studio_assistant_probe import (
            run_studio_assistant_probe,
        )

        studio_assistant_probe = run_studio_assistant_probe(
            document_path,
            output_root=run_root / "studio_assistant",
        )
        checks.append(
            _check(
                "veusz_mainwindow_assistant_integration",
                "The optional selected-object Assistant shares the native Veusz "
                "document, stays opt-in, applies bounded edits through native "
                "undo, and preserves save/reopen/export authority",
                studio_assistant_probe.get("status") == "passed",
                detail={
                    "status": studio_assistant_probe.get("status"),
                    "summary": studio_assistant_probe.get("summary"),
                    "artifacts": studio_assistant_probe.get("artifacts"),
                    "limitations": studio_assistant_probe.get("limitations"),
                },
            )
        )
        from sciplot_core.studio_figure_set_probe import (
            run_studio_figure_set_probe,
        )

        studio_figure_set_probe = run_studio_figure_set_probe(
            output_root=run_root / "studio_figure_set",
        )
        checks.append(
            _check(
                "rheology_frequency_figure_set",
                "Frequency sweeps create metric-bound independent VSZ files, "
                "fail closed on missing metrics, and never imply a composite",
                studio_figure_set_probe.get("status") == "passed",
                detail=studio_figure_set_probe,
            )
        )
        from sciplot_core.openai_provider_probe import run_openai_provider_probe

        openai_provider_probe = run_openai_provider_probe(
            output_root=run_root / "openai_provider",
        )
        checks.append(
            _check(
                "openai_responses_provider_boundary",
                "The production Responses adapter streams strict structured output, "
                "enforces the selected-object capability catalog, cancels safely, "
                "and redacts credentials",
                openai_provider_probe.get("status") == "passed",
                detail={
                    "status": openai_provider_probe.get("status"),
                    "summary": openai_provider_probe.get("summary"),
                    "artifacts": openai_provider_probe.get("artifacts"),
                    "limitations": openai_provider_probe.get("limitations"),
                },
            )
        )
        launcher_probe = _portable_launcher_probe(project_dir)
        checks.append(
            _check(
                "portable_project_launchers",
                "Generated Studio, Veusz, and exact-export launchers locate and load the moved project",
                launcher_probe.get("passed") is True,
                detail=launcher_probe,
            )
        )
        with document_path.open("a", encoding="utf-8") as handle:
            handle.write(f"\n{MANUAL_EDIT_MARKER}\n")

        export_payload = export_studio_document(
            document_path, formats=["pdf", "tiff_300"]
        )
        exports = (
            export_payload.get("exports")
            if isinstance(export_payload.get("exports"), list)
            else []
        )
        studio_run = publish_studio_export_run(
            project_dir=project_dir,
            request_path=request_path,
            document_path=document_path,
            exports=exports,
            export_document_sha256=str(export_payload["document_sha256"]),
        )
        manifest_path = Path(str(studio_run["manifest"]))
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        semantic = (
            manifest.get("semantic")
            if isinstance(manifest.get("semantic"), dict)
            else {}
        )
        transform = (
            manifest.get("transform_ledger")
            if isinstance(manifest.get("transform_ledger"), dict)
            else {}
        )
        publication_intent = (
            manifest.get("publication_intent")
            if isinstance(manifest.get("publication_intent"), dict)
            else {}
        )
        delivery = (
            manifest.get("delivery_package")
            if isinstance(manifest.get("delivery_package"), dict)
            else {}
        )
        relocated_delivery_probe = _relocated_delivery_launcher_probe(
            run_root, delivery
        )
        editable_vsz = (
            delivery.get("editable_vsz")
            if isinstance(delivery.get("editable_vsz"), dict)
            else {}
        )
        editable_path = (
            Path(str(editable_vsz["path"])) if editable_vsz.get("path") else None
        )
        raw_archive_value = (manifest.get("raw_archive") or {}).get("path")
        raw_archive_path = Path(str(raw_archive_value)) if raw_archive_value else None
        exported_formats = {
            str(item.get("format")) for item in exports if isinstance(item, dict)
        }
        exports_exist = all(
            isinstance(item, dict)
            and item.get("exists") is True
            and int(item.get("size_bytes") or 0) > 0
            for item in exports
        )
        delivery_layout = _delivery_layout_probe(delivery)

        checks.extend(
            [
                _check(
                    "semantic_rule_selected",
                    "Synthetic FTIR input selects the ready FTIR rule",
                    semantic.get("rule_id") == EXPECTED_RULE_ID,
                    detail={
                        "selected": semantic.get("rule_id"),
                        "expected": EXPECTED_RULE_ID,
                    },
                ),
                _check(
                    "vsz_reopen_export",
                    "Veusz reopens the canonical VSZ and exports the canonical format pair",
                    document_path.exists()
                    and int(prepared.get("series_count") or 0) > 0
                    and {"pdf", "tiff_300"} <= exported_formats
                    and exports_exist,
                    detail={
                        "document": str(document_path),
                        "series_count": prepared.get("series_count"),
                        "formats": sorted(exported_formats),
                    },
                ),
                _check(
                    "manual_edit_preserved",
                    "A saved VSZ edit is preserved in the editable delivery copy",
                    manifest.get("manual_edit_detected") is True
                    and MANUAL_EDIT_MARKER in document_path.read_text(encoding="utf-8")
                    and editable_path is not None
                    and editable_path.exists()
                    and MANUAL_EDIT_MARKER in editable_path.read_text(encoding="utf-8"),
                    detail={
                        "manual_edit_detected": manifest.get("manual_edit_detected"),
                        "editable_vsz": str(editable_path)
                        if editable_path is not None
                        else None,
                    },
                ),
                _check(
                    "exact_current_vsz_hash",
                    "The current, exported, and delivered editable VSZ hashes match",
                    manifest.get("exported_document_hash") == file_sha256(document_path)
                    and editable_vsz.get("hash_matches_export") is True,
                    detail={
                        "exported_document_hash": manifest.get(
                            "exported_document_hash"
                        ),
                        "current_document_hash": file_sha256(document_path),
                        "delivery_document_hash": editable_vsz.get("actual_hash"),
                    },
                ),
                _check(
                    "canonical_pdf_tiff_pair",
                    "Delivery contains a canonical PDF and 300 dpi TIFF pair",
                    _delivery_artifact(delivery, "canonical_pdf_tiff_pairs").get(
                        "exists"
                    )
                    is True,
                    detail=_delivery_artifact(delivery, "canonical_pdf_tiff_pairs"),
                ),
                _check(
                    "minimal_delivery_layout",
                    "The user-facing delivery contains only four artifact groups and its Veusz launcher",
                    delivery_layout.get("passed") is True,
                    detail=delivery_layout,
                ),
                _check(
                    "qa_and_delivery_hashes",
                    "Artifact QA passes and its hashes match the delivery copies",
                    (manifest.get("qa") or {}).get("status") == "passed"
                    and _delivery_artifact(
                        delivery, "qa_artifact_hashes_match_delivery"
                    ).get("exists")
                    is True,
                    detail={
                        "qa_status": (manifest.get("qa") or {}).get("status"),
                        "hash_gate": _delivery_artifact(
                            delivery, "qa_artifact_hashes_match_delivery"
                        ),
                    },
                ),
                _check(
                    "delivery_complete",
                    "The portable delivery package is complete",
                    delivery.get("complete") is True,
                    detail={
                        "path": delivery.get("path"),
                        "complete": delivery.get("complete"),
                    },
                ),
                _check(
                    "relocated_delivery_launchers",
                    "A copied editable delivery locates SciPlot and loads its exact VSZ without runtime overrides",
                    relocated_delivery_probe.get("passed") is True,
                    detail=relocated_delivery_probe,
                ),
                _check(
                    "runtime_lineage_recorded",
                    "Runtime transform and publication contracts are recorded",
                    transform.get("status") == "runtime_recorded"
                    and publication_intent.get("kind") == "sciplot_publication_intent"
                    and raw_archive_path is not None
                    and raw_archive_path.exists(),
                    detail={
                        "transform_status": transform.get("status"),
                        "publication_kind": publication_intent.get("kind"),
                        "raw_archive": str(raw_archive_path)
                        if raw_archive_path is not None
                        else None,
                    },
                ),
            ]
        )

        standalone_probe = _standalone_export_probe(run_root, document_path)
        checks.append(
            _check(
                "standalone_vsz_exact_export",
                "A standalone VSZ without a spec sidecar exports to --out, passes artifact QA, and exits zero",
                standalone_probe.get("passed") is True,
                detail=standalone_probe,
            )
        )

        failure_probe_passed, failure_probe = _run_hash_failure_probe(
            Path(str(manifest["output"])),
            manifest,
        )
        checks.append(
            _check(
                "delivery_hash_failure_rejected",
                "A mismatched exported VSZ hash makes delivery incomplete",
                failure_probe_passed,
                detail=failure_probe,
            )
        )
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        checks.append(
            _check(
                "runtime_exception",
                "The runtime smoke completed without an exception",
                False,
                detail=error,
            )
        )

    status = (
        "passed"
        if checks and all(item["status"] == "passed" for item in checks)
        else "failed"
    )
    payload = {
        "kind": "sciplot_runtime_smoke",
        "version": RUNTIME_SMOKE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": status,
        "state": "ready" if status == "passed" else "needs_rule_repair",
        "fixture": fixture,
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(item["status"] == "passed" for item in checks),
            "failed_ids": [item["id"] for item in checks if item["status"] != "passed"],
        },
        "artifacts": {
            "run_root": str(run_root),
            "project_dir": str(project_dir) if project_dir is not None else None,
            "manifest": str(manifest_path) if manifest_path is not None else None,
            "summary": str(summary_path),
        },
        "error": error,
        "limitations": [
            "The generated FTIR and scalar-field tables are synthetic contract fixtures, "
            "not real-data evidence.",
            "This smoke proves one representative Studio lifecycle, project and relocated-delivery "
            "launcher checks, a standalone exact-current export, and a delivery hash failure path; "
            "it does not replace the complete ready-rule acceptance matrix.",
            "The OpenAI provider gates use an in-memory HTTP/SSE wire fixture and do not "
            "claim live-model quality or a successful paid API call.",
            "Lifecycle success and artifact QA do not establish blanket journal compliance.",
        ],
    }
    summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload
