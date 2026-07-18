from __future__ import annotations

import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.operations import CanvasOperationBatch
from sciplot_core.canvas_assistant_probe import (
    _capture_window,
    _copy_target,
    _tree_hash,
    _wait_until,
)
from sciplot_core.openai_provider import OPENAI_PROVIDER_ID
from sciplot_core.openai_provider_probe import OpenAIProviderWireFixture

CANVAS_OPENAI_PROVIDER_PROBE_KIND = "sciplot_canvas_openai_provider_probe"
CANVAS_OPENAI_PROVIDER_PROBE_VERSION = 1


def _check(
    check_id: str,
    label: str,
    passed: bool,
    detail: Any = None,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def run_canvas_openai_provider_probe(
    target: Path,
    *,
    output_root: Path,
) -> dict[str, Any]:
    source = target.expanduser().resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="canvas_openai_probe_", dir=resolved_output)
    )
    summary_path = run_root / "canvas_openai_provider_probe.json"
    proposal_screenshot = run_root / "openai_provider_proposal.png"
    applied_screenshot = run_root / "openai_provider_applied.png"
    checks: list[dict[str, Any]] = []
    evidence: dict[str, Any] = {}
    error: dict[str, str] | None = None
    window: Any = None
    source_hash_before = _tree_hash(source)

    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PyQt6 import QtWidgets

        from sciplot_gui.main_window import SciPlotCanvasWindow
        from sciplot_gui.workspace import resolve_canvas_workspace

        application = QtWidgets.QApplication.instance()
        if application is None:
            application = QtWidgets.QApplication([])
        application.setApplicationName("SciPlot OpenAI Provider Probe")
        application.setQuitOnLastWindowClosed(False)

        copied_target = _copy_target(source, run_root)
        workspace = resolve_canvas_workspace(copied_target)
        wire = OpenAIProviderWireFixture()
        provider = wire.provider()
        window = SciPlotCanvasWindow(
            workspace,
            interactive=False,
            assistant_provider=provider,
        )
        window.resize(1380, 860)
        window.show()
        application.processEvents()

        target_info = window.controller.adapter.first_visible_text_target(
            window.controller.session
        )
        target_id = str(target_info["object_id"])
        setting_path = str(target_info["setting_path"])
        window.controller.select_object_id(target_id)
        window._refresh_contextual_inspector()
        window._refresh_assistant_panel()
        window._open_assistant_workspace()
        application.processEvents()

        before = window.controller.adapter.setting_value(setting_path)
        expected_after = f"{before} · AI"
        baseline_revision = window.controller.session.revision
        baseline_render = window.controller.adapter.render_fingerprint()
        baseline_document_hash = file_sha256(workspace.document_path)
        descriptor = window.assistant_runner.descriptor
        checks.append(
            _check(
                "production_provider_visible",
                "The Canvas exposes the environment-compatible OpenAI provider without a mode switch",
                descriptor is not None
                and descriptor.provider_id == OPENAI_PROVIDER_ID
                and descriptor.proposal_kinds == ("canvas_operation_batch",)
                and descriptor.supports_cancellation
                and window.assistant_panel.composer_card.isVisible()
                and window.assistant_panel.request_editor.isEnabled(),
                descriptor.to_dict() if descriptor is not None else None,
            )
        )

        intent = "把当前选中的文字改得更清楚，只改这个对象，不改数据。"
        window.assistant_panel.request_editor.setPlainText(intent)
        window.assistant_panel.send_button.click()
        proposal_ready = _wait_until(
            application,
            lambda: (
                not window.assistant_runner.active
                and window.assistant.transaction is not None
                and window.assistant.transaction.pending_batch is not None
            ),
        )
        if not proposal_ready:
            raise RuntimeError(
                "OpenAI provider did not deliver a visible typed proposal."
            )
        record = window.assistant.request_record
        if record is None or record.parsed_response is None:
            raise RuntimeError("OpenAI provider request record is incomplete.")
        request = record.parsed_request
        response = record.parsed_response
        response.validate_for_request(request)
        batch = CanvasOperationBatch.from_dict(dict(response.proposal or {}))
        operation = batch.operations[0]
        capabilities = request.context["editing_capabilities"]
        advertised = capabilities["allowed_operations"]
        proposal_capture = _capture_window(
            window,
            proposal_screenshot,
            application=application,
        )
        checks.append(
            _check(
                "selected_object_capability_binding",
                "The request exposes only the selected object's editable Inspector paths and exact current values",
                capabilities["target_object_id"] == target_id
                and bool(advertised)
                and all(item["target_id"] == target_id for item in advertised)
                and any(
                    item["setting_path"] == setting_path
                    and item["current_value"] == before
                    and item["editor"] == "text"
                    for item in advertised
                )
                and all(
                    item["editor"] not in {"dataset", "read_only"}
                    for item in advertised
                ),
                {
                    "target_id": capabilities["target_object_id"],
                    "operation_count": len(advertised),
                    "setting_paths": [item["setting_path"] for item in advertised],
                },
            )
        )
        checks.append(
            _check(
                "natural_language_stream_to_preview",
                "A visible natural-language request streams through the production adapter into one typed preview",
                response.status == "proposal"
                and record.status == "proposal_ready"
                and len(record.events) == 4
                and [event["stage"] for event in record.events]
                == ["understanding", "planning", "proposing", "validating"]
                and len(batch.operations) == 1
                and operation.target_id == target_id
                and operation.arguments["setting_path"] == setting_path
                and operation.arguments["expected_value"] == before
                and operation.arguments["value"] == expected_after,
                {
                    "request_id": request.request_id,
                    "status": response.status,
                    "stages": [event["stage"] for event in record.events],
                    "operation": operation.to_dict(),
                },
            )
        )
        checks.append(
            _check(
                "preview_zero_mutation",
                "The model proposal is visible before any document or render mutation",
                window.controller.session.revision == baseline_revision
                and window.controller.adapter.setting_value(setting_path) == before
                and window.controller.adapter.render_fingerprint() == baseline_render
                and file_sha256(workspace.document_path) == baseline_document_hash,
            )
        )
        checks.append(
            _check(
                "proposal_visual_state",
                "The production-provider proposal is visually renderable in the existing Assistant pane",
                proposal_capture.get("visually_plausible") is True
                and window.assistant_panel.state_chip.text() == "Proposal"
                and window.assistant_panel.change_count == 1
                and window.assistant_panel.accept_button.isEnabled(),
                proposal_capture,
            )
        )

        apply_result = window.accept_assistant_proposal()
        application.processEvents()
        applied_capture = _capture_window(
            window,
            applied_screenshot,
            application=application,
        )
        checks.append(
            _check(
                "accepted_edit_uses_live_gateway",
                "Accept applies the host-built operation through the ordinary live Canvas gateway",
                window.controller.session.revision == baseline_revision + 1
                and window.controller.adapter.setting_value(setting_path)
                == expected_after
                and apply_result.get("entry", {}).get("revision")
                == baseline_revision + 1
                and window.controller.adapter.render_fingerprint()
                != baseline_render
                and applied_capture.get("visually_plausible") is True,
                {
                    "revision": window.controller.session.revision,
                    "value": window.controller.adapter.setting_value(setting_path),
                    "capture": applied_capture,
                },
            )
        )

        rollback = window.rollback_assistant_transaction(
            reason="Restore the production-provider probe baseline."
        )
        application.processEvents()
        source_hash_after = _tree_hash(source)
        checks.append(
            _check(
                "exact_rollback_and_source_immutability",
                "Whole-turn rollback restores the exact figure and leaves the source project untouched",
                window.assistant.transaction is None
                and window.controller.adapter.setting_value(setting_path) == before
                and window.controller.adapter.render_fingerprint() == baseline_render
                and file_sha256(workspace.document_path) == baseline_document_hash
                and source_hash_after == source_hash_before
                and rollback.get("verification", {}).get("exact_baseline_render")
                is True,
                {
                    "source_hash_before": source_hash_before,
                    "source_hash_after": source_hash_after,
                    "rollback_verification": rollback.get("verification"),
                },
            )
        )
        wire_record = wire.records[0]
        checks.append(
            _check(
                "provider_wire_and_privacy",
                "The visible Canvas path uses store=false strict structured output and sends no absolute document path",
                wire_record["body"]["store"] is False
                and wire_record["body"]["stream"] is True
                and wire_record["body"]["text"]["format"]["strict"] is True
                and str(workspace.document_path)
                not in wire_record["body"]["input"][0]["content"][0]["text"],
                {
                    "path": wire_record["path"],
                    "store": wire_record["body"]["store"],
                    "stream": wire_record["body"]["stream"],
                    "strict": wire_record["body"]["text"]["format"]["strict"],
                },
            )
        )
        evidence = {
            "provider_id": provider.descriptor.provider_id,
            "model_label": provider.descriptor.model_label,
            "request_context_version": request.context["version"],
            "advertised_operation_count": len(advertised),
            "proposal_operation_count": len(batch.operations),
            "source_hash_before": source_hash_before,
            "source_hash_after": source_hash_after,
        }
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        checks.append(
            _check(
                "canvas_openai_probe_exception",
                "The production-provider Canvas lifecycle completed without an exception",
                False,
                error,
            )
        )
    finally:
        if window is not None:
            try:
                window.set_close_policy_for_test("keep_recovery")
                window.close()
            except Exception:
                try:
                    window.controller.close()
                except Exception:
                    pass

    failed_ids = [item["id"] for item in checks if item["status"] != "passed"]
    payload = {
        "kind": CANVAS_OPENAI_PROVIDER_PROBE_KIND,
        "version": CANVAS_OPENAI_PROVIDER_PROBE_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "passed" if checks and not failed_ids else "failed",
        "state": "ready" if checks and not failed_ids else "needs_rule_repair",
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(item["status"] == "passed" for item in checks),
            "failed_ids": failed_ids,
        },
        "checks": checks,
        "evidence": json_safe(evidence),
        "artifacts": {
            "run_root": str(run_root),
            "summary": str(summary_path),
            "proposal_screenshot": str(proposal_screenshot),
            "applied_screenshot": str(applied_screenshot),
        },
        "error": error,
        "limitations": [
            "The UI probe uses the production adapter with an in-memory Responses/SSE wire fixture; it does not call or evaluate a live OpenAI model.",
            "Automated UI probes do not count as real human daily-use sessions.",
        ],
    }
    serialized = json.dumps(payload, indent=2, ensure_ascii=False)
    if "sk-sciplot-protocol-probe" in serialized:
        raise RuntimeError("Canvas provider probe attempted to persist a credential.")
    summary_path.write_text(serialized, encoding="utf-8")
    return payload


__all__ = [
    "CANVAS_OPENAI_PROVIDER_PROBE_KIND",
    "CANVAS_OPENAI_PROVIDER_PROBE_VERSION",
    "run_canvas_openai_provider_probe",
]
