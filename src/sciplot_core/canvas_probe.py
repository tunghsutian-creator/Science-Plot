from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sciplot_core._utils import file_sha256, json_safe
from sciplot_core.canvas.annotations import (
    REVIEW_ANNOTATION_VERSION,
    ReviewAnnotation,
    ReviewAnnotationStyle,
)
from sciplot_core.canvas.assistant_contract import (
    DataColumnMapping,
    DataMappingConfirmation,
    DataMappingProposal,
    DataSourceReference,
    DeclarativeTransformation,
)
from sciplot_core.canvas.inspector import CanvasInspectorField
from sciplot_core.canvas.model import (
    CanvasDataPointSelection,
    CanvasSelection,
    CanvasSession,
    CanvasTransaction,
)
from sciplot_core.canvas.operations import CanvasOperation, CanvasOperationBatch
from sciplot_core.canvas.persistence import (
    append_operation_journal,
    append_operation_journal_once,
    load_canvas_session,
    load_review_annotations,
    read_operation_journal,
    save_canvas_session,
    save_review_annotations,
)
from sciplot_core.canvas.provider import (
    AssistantDataMappingState,
    AssistantProgressEvent,
    AssistantRequest,
    AssistantRequestRecord,
    AssistantResponse,
    canonical_payload_sha256,
)

CANVAS_CHARACTERIZATION_KIND = "sciplot_canvas_characterization"
CANVAS_CHARACTERIZATION_VERSION = 1


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _check(
    check_id: str, label: str, passed: bool, detail: Any = None
) -> dict[str, Any]:
    return {
        "id": check_id,
        "label": label,
        "status": "passed" if passed else "failed",
        "detail": json_safe(detail),
    }


def _raises_value_error(callback: Callable[[], Any]) -> bool:
    try:
        callback()
    except ValueError:
        return True
    return False


def _resolve_persisted_path(value: str, *, root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = root / path
    return path.resolve()


def run_canvas_contract_probe(*, output_root: Path) -> dict[str, Any]:
    root = output_root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    session_path = root / "canvas_session.json"
    transaction_session_path = root / "canvas_transaction_session.json"
    annotations_path = root / "review_annotations.json"
    journal_path = root / "operation_journal.jsonl"
    idempotent_journal_path = root / "idempotent_journal.jsonl"

    session = CanvasSession(
        project_id="canvas_contract_probe",
        document_id="11111111-1111-4111-8111-111111111111",
        document_path=str(root / "document.vsz"),
        state="canvas_ready",
    )
    session.interface.inspector_visible = False
    session.interface.inspector_width = 412
    session.interface.high_contrast = True
    axis = session.object_registry.bind(
        structural_key="root/page[0]/graph[0]/axis[0]",
        current_path="/page/graph/x",
        object_type="axis",
        revision=session.revision,
    )
    page = session.object_registry.bind(
        structural_key="root/page[0]",
        current_path="/page",
        object_type="page",
        revision=session.revision,
    )
    session.selection = CanvasSelection(
        object_ids=[axis.object_id],
        primary_object_id=axis.object_id,
        data_point=CanvasDataPointSelection(
            target_object_id=axis.object_id,
            x=1.25,
            y=2.5,
            graph_x=140.0,
            graph_y=90.0,
            x_label="Frequency",
            y_label="Storage modulus",
            index="4",
        ),
    )
    session.structural_qa_summary = {
        "kind": "sciplot_canvas_structural_qa",
        "version": 1,
        "status": "warning",
        "revision": 0,
    }
    operation = CanvasOperation.set_setting(
        target_id=axis.object_id,
        setting_path="/page/graph/x/label",
        value="Frequency",
        expected_value="",
        require_expected_value=True,
    )
    batch = CanvasOperationBatch(
        base_revision=0,
        provider="contract_probe",
        rationale="Verify the version 1 typed setting contract.",
        operations=(operation,),
    )
    annotation = ReviewAnnotation(
        page_index=0,
        shape="arrow",
        coordinate_space="object",
        geometry={"start": [0.2, 0.2], "end": [0.4, 0.5]},
        text="Review only",
        target_object_id=axis.object_id,
    )
    native_annotation_operation = CanvasOperation.add_widget(
        target_id=page.object_id,
        widget_type="label",
        name="review_contract",
        index=0,
        settings={
            "positioning": "relative",
            "xPos": [0.1],
            "yPos": [0.9],
            "label": "Promoted review",
            "Text__color": "#ff9f0a",
            "Text__size": "12pt",
        },
    )
    proposal = DataMappingProposal(
        base_request_sha256="b" * 64,
        provider="contract_probe",
        sources=(
            DataSourceReference(
                source_id="example",
                relative_path="raw/example.csv",
                sha256="a" * 64,
            ),
        ),
        columns=(
            DataColumnMapping(
                source_id="example",
                source_column_index=0,
                expected_header="Frequency",
                output_column="Frequency",
                role="x",
            ),
            DataColumnMapping(
                source_id="example",
                source_column_index=1,
                expected_header="Storage modulus",
                output_column="Storage modulus",
                role="y",
            ),
        ),
        transformations=(
            DeclarativeTransformation(
                transformation_type="unit_convert",
                parameters={
                    "column": "Frequency",
                    "from_unit": "rad/s",
                    "to_unit": "Hz",
                },
            ),
        ),
        confidence=0.91,
        rationale="Contract-only proposal; no data are executed.",
    )
    transaction_id = "22222222-2222-4222-8222-222222222222"
    assistant_request = AssistantRequest(
        transaction_id=transaction_id,
        provider_id="contract_probe",
        intent="Rename the selected x-axis without changing its data mapping.",
        base_revision=0,
        context={
            "kind": "sciplot_canvas_assistant_context",
            "version": 2,
            "project_id": session.project_id,
            "document_id": session.document_id,
            "revision": 0,
            "state": "ai_proposing",
            "page": 0,
            "selection": session.selection.to_dict(),
            "selected_object": {
                "object_id": axis.object_id,
                "object_type": "axis",
                "display_name": "x",
            },
            "document_inventory": {
                "object_count": 2,
                "object_types": {"axis": 1, "page": 1},
            },
            "review": {"active_count": 0, "annotations": []},
            "qa": {
                "structural_status": "warning",
                "structural_failed_ids": [],
                "structural_warning_ids": ["artifact_qa_current"],
                "ready_for_artifact_qa": True,
                "artifact_status": "not_run",
                "ready_to_use": None,
            },
            "raw_dataset_arrays_included": False,
            "explicit_selected_point_included": True,
        },
        allowed_proposal_kinds=("canvas_operation_batch",),
    )
    assistant_record = AssistantRequestRecord(request=assistant_request.to_dict())
    assistant_record.append_event(
        AssistantProgressEvent(
            request_id=assistant_request.request_id,
            provider_id=assistant_request.provider_id,
            sequence=1,
            stage="validating",
            message="Validating one typed setting operation.",
            cancellable=True,
            progress=0.8,
        )
    )
    assistant_record.complete(
        AssistantResponse(
            request_id=assistant_request.request_id,
            transaction_id=assistant_request.transaction_id,
            provider_id=assistant_request.provider_id,
            request_sha256=assistant_request.payload_sha256,
            status="proposal",
            understanding="Rename only the selected axis label.",
            proposal_kind="canvas_operation_batch",
            proposal=batch.to_dict(),
        )
    )
    mapping_request = AssistantRequest(
        transaction_id="33333333-3333-4333-8333-333333333333",
        provider_id="contract_probe",
        intent="Map the hash-bound source columns into an isolated candidate project.",
        base_revision=0,
        context=assistant_request.context,
        allowed_proposal_kinds=("data_mapping_proposal",),
    )
    mapping_record = AssistantRequestRecord(request=mapping_request.to_dict())
    mapping_record.complete(
        AssistantResponse(
            request_id=mapping_request.request_id,
            transaction_id=mapping_request.transaction_id,
            provider_id=mapping_request.provider_id,
            request_sha256=mapping_request.payload_sha256,
            status="proposal",
            understanding="Map only the declared, hash-bound source columns.",
            proposal_kind="data_mapping_proposal",
            proposal=proposal.to_dict(),
        )
    )
    proposal_sha256 = canonical_payload_sha256(proposal.to_dict())
    mapping_preview = {
        "kind": "sciplot_data_mapping_preview",
        "version": 1,
        "status": "ready_for_confirmation",
        "proposal_id": proposal.proposal_id,
        "proposal_sha256": proposal_sha256,
        "provider": proposal.provider,
        "base_request": str(root / "plot_request.json"),
        "base_request_sha256": proposal.base_request_sha256,
        "source_root": str(root),
        "sources": [
            {
                "source_id": "example",
                "relative_path": "raw/example.csv",
                "sha256": "a" * 64,
                "source_size_bytes": 128,
                "detected_headers": ["Frequency", "Storage modulus"],
                "mapped_columns": ["Frequency", "Storage modulus"],
                "row_count": 4,
                "column_count": 2,
                "units": {"Frequency": "Hz"},
                "transformations": ["unit_convert"],
                "sample_label": "Example",
            }
        ],
        "request_patch": proposal.request_patch,
        "confidence": proposal.confidence,
        "rationale": proposal.rationale,
        "raw_values_in_preview": False,
        "writes_performed": False,
        "requires_confirmation_receipt": True,
    }
    mapping_record.set_mapping_state(
        AssistantDataMappingState(
            status="preview_ready",
            source_root=str(root),
            output_root=str(root / "mapped_projects"),
            preview=mapping_preview,
        )
    )
    mapping_premature_accept_rejected = _raises_value_error(
        lambda: mapping_record.mark_proposal_outcome(accepted=True)
    )
    mapping_confirmation = DataMappingConfirmation(
        proposal_id=proposal.proposal_id,
        proposal_sha256=proposal_sha256,
        base_request_sha256=proposal.base_request_sha256,
        source_hashes=proposal.source_hashes,
        source_root=str(root),
        request_path=str(root / "plot_request.json"),
        output_root=str(root / "mapped_projects"),
        confirmed_by="canvas_contract_probe",
    )
    mapping_record.set_mapping_state(
        AssistantDataMappingState(
            status="confirmed",
            source_root=str(root),
            output_root=str(root / "mapped_projects"),
            preview=mapping_preview,
            confirmation=mapping_confirmation.to_dict(),
        )
    )
    restored_mapping_record = AssistantRequestRecord.from_dict(mapping_record.to_dict())
    legacy_mapping_record_payload = mapping_record.to_dict()
    legacy_mapping_record_payload["version"] = 1
    legacy_mapping_record_payload.pop("mapping_state")
    migrated_mapping_record_v1 = AssistantRequestRecord.from_dict(
        legacy_mapping_record_payload
    )
    stale_mapping_record_payload = mapping_record.to_dict()
    stale_mapping_record_payload["mapping_state"]["preview"]["proposal_sha256"] = (
        "0" * 64
    )
    stale_mapping_binding_rejected = _raises_value_error(
        lambda: AssistantRequestRecord.from_dict(stale_mapping_record_payload)
    )
    rebound_mapping_path_payload = mapping_record.to_dict()
    rebound_mapping_path_payload["mapping_state"]["source_root"] = str(
        root / "other_source"
    )
    rebound_mapping_path_rejected = _raises_value_error(
        lambda: AssistantRequestRecord.from_dict(rebound_mapping_path_payload)
    )
    mapping_record.set_mapping_state(
        AssistantDataMappingState(
            status="executed",
            source_root=str(root),
            output_root=str(root / "mapped_projects"),
            preview=mapping_preview,
            confirmation=mapping_confirmation.to_dict(),
            execution_manifest=str(
                root
                / "mapped_projects"
                / proposal.proposal_id
                / "execution.json"
            ),
            execution_manifest_sha256="f" * 64,
            mapped_document=str(
                root
                / "mapped_projects"
                / proposal.proposal_id
                / "studio"
                / "document.vsz"
            ),
            mapped_document_sha256="e" * 64,
        )
    )
    executed_mapping_record = AssistantRequestRecord.from_dict(
        mapping_record.to_dict()
    )
    executed_mapping_reject_blocked = _raises_value_error(
        lambda: executed_mapping_record.mark_proposal_outcome(accepted=False)
    )
    mapping_record.mark_proposal_outcome(accepted=True)
    transaction = CanvasTransaction(
        transaction_id=transaction_id,
        provider="contract_probe",
        base_revision=0,
        status="active",
        snapshot_path=".canvas_transactions/contract/baseline.vsz",
        snapshot_sha256="b" * 64,
        review_snapshot_path=(".canvas_transactions/contract/review_annotations.json"),
        review_snapshot_sha256="c" * 64,
        baseline_render_sha256="d" * 64,
        baseline_saved_revision=0,
        baseline_exported_revision=None,
        baseline_state="canvas_ready",
        baseline_document_sha256="e" * 64,
        baseline_page=0,
        baseline_viewport=session.viewport.to_dict(),
        current_revision=0,
        rationale="Contract-only active Assistant transaction.",
        request_record=assistant_record.to_dict(),
        pending_batch=batch.to_dict(),
        pending_preview={
            "kind": "sciplot_canvas_operation_preview",
            "version": 1,
            "batch_id": batch.batch_id,
            "base_revision": 0,
            "provider": "contract_probe",
            "rationale": batch.rationale,
            "operation_count": 1,
            "affected_target_ids": [axis.object_id],
            "changes": [
                {
                    "operation_type": "set_setting",
                    "operation_id": operation.operation_id,
                    "target_id": axis.object_id,
                    "setting_path": "/page/graph/x/label",
                    "old_value": "",
                    "value": "Frequency",
                }
            ],
            "render_before": "f" * 64,
            "publication_document_changed": False,
        },
    )
    outbox_event = {
        "kind": "sciplot_canvas_journal_entry",
        "version": 1,
        "event_id": "contract-event-1",
        "event": "assistant_transaction_started",
        "transaction_id": transaction.transaction_id,
        "revision": 0,
    }
    transaction_session = CanvasSession.from_dict(session.to_dict())
    transaction_session.state = "ai_proposing"
    transaction_session.active_inspector = "assistant"
    transaction_session.active_transaction = transaction
    transaction_session.journal_outbox = [dict(outbox_event)]
    original_request_structural_status = transaction_session.active_transaction.parsed_request_record.parsed_request.context[
        "qa"
    ]["structural_status"]
    detached_session_payload = transaction_session.to_dict()
    detached_session_payload["active_transaction"]["request_record"]["request"][
        "context"
    ]["qa"]["structural_status"] = "tampered"
    transaction_payload_is_detached = bool(
        transaction_session.active_transaction.parsed_request_record.parsed_request.context[
            "qa"
        ]["structural_status"]
        == original_request_structural_status
    )

    save_canvas_session(session_path, session)
    save_canvas_session(transaction_session_path, transaction_session)
    save_review_annotations(annotations_path, [annotation])
    append_operation_journal(
        journal_path,
        {
            "kind": "sciplot_canvas_journal_entry",
            "version": 1,
            "event": "contract_probe",
            "batch": batch.to_dict(),
        },
    )
    _, first_idempotent_append = append_operation_journal_once(
        idempotent_journal_path,
        outbox_event,
    )
    _, duplicate_idempotent_append = append_operation_journal_once(
        idempotent_journal_path,
        outbox_event,
    )

    loaded = load_canvas_session(session_path)
    loaded_transaction_session = load_canvas_session(transaction_session_path)
    loaded_annotations = load_review_annotations(annotations_path)
    journal = read_operation_journal(journal_path)
    idempotent_journal = read_operation_journal(idempotent_journal_path)
    rebound = loaded.object_registry.bind(
        structural_key="root/page[0]/graph[0]/axis[0]",
        current_path="/renamed_page/renamed_graph/renamed_axis",
        object_type="axis",
        revision=1,
    )
    registry_before_insertion = CanvasSession.from_dict(session.to_dict())
    existing_label = registry_before_insertion.object_registry.bind(
        structural_key="root/page[0]/label[0]",
        current_path="/page/title",
        object_type="label",
        revision=0,
    )
    reconciled_records = registry_before_insertion.object_registry.reconcile(
        [
            ("root/page[0]", "/page", "page"),
            (
                "root/page[0]/label[0]",
                "/page/review_contract",
                "label",
            ),
            ("root/page[0]/label[1]", "/page/title", "label"),
        ],
        revision=1,
    )
    reconciled_by_path = {record.current_path: record for record in reconciled_records}
    restored_batch = CanvasOperationBatch.from_dict(batch.to_dict())
    restored_native_annotation_operation = CanvasOperation.from_dict(
        native_annotation_operation.to_dict()
    )
    restored_proposal = DataMappingProposal.from_dict(proposal.to_dict())
    legacy_annotation_payload = annotation.to_dict()
    legacy_annotation_payload["version"] = 1
    legacy_annotation_payload.pop("style")
    migrated_legacy_annotation = ReviewAnnotation.from_dict(legacy_annotation_payload)
    operation_schema_rejected = _raises_value_error(
        lambda: CanvasOperation(
            operation_type="set_setting",
            target_id=axis.object_id,
            arguments={
                "setting_path": "/page/graph/x/label",
                "value": "Frequency",
                "python": "print('unsafe')",
            },
        )
    )
    executable_mapping_rejected = _raises_value_error(
        lambda: DeclarativeTransformation(
            transformation_type="rename",
            parameters={
                "columns": {"x": "Frequency"},
                "nested": {"script": "unsafe"},
            },
        )
    )
    operation_top_level_rejected = _raises_value_error(
        lambda: CanvasOperation.from_dict(
            {
                **operation.to_dict(),
                "python": "print('unsafe')",
            }
        )
    )
    boolean_coercion_rejected = _raises_value_error(
        lambda: CanvasOperationBatch.from_dict(
            {
                **batch.to_dict(),
                "atomic": "false",
            }
        )
    )
    mapping_top_level_rejected = _raises_value_error(
        lambda: DataMappingProposal.from_dict(
            {
                **proposal.to_dict(),
                "script": "unsafe",
            }
        )
    )
    session_integrity_rejected = _raises_value_error(
        lambda: CanvasSession.from_dict(
            {
                **session.to_dict(),
                "dirty": True,
            }
        )
    )
    legacy_payload = session.to_dict()
    legacy_payload["version"] = 1
    legacy_payload.pop("interface")
    legacy_payload.pop("structural_qa_summary")
    legacy_payload["selection"].pop("data_point")
    migrated_legacy_session = CanvasSession.from_dict(legacy_payload)
    version_two_payload = session.to_dict()
    version_two_payload["version"] = 2
    version_two_payload.pop("structural_qa_summary")
    version_two_payload["selection"].pop("data_point")
    migrated_version_two_session = CanvasSession.from_dict(version_two_payload)
    version_four_payload = transaction_session.to_dict()
    version_four_payload["version"] = 4
    version_four_payload["active_transaction"].pop("request_record")
    migrated_version_four_session = CanvasSession.from_dict(version_four_payload)
    version_five_payload = transaction_session.to_dict()
    version_five_payload["version"] = 5
    migrated_version_five_session = CanvasSession.from_dict(version_five_payload)
    invalid_interface_rejected = _raises_value_error(
        lambda: CanvasSession.from_dict(
            {
                **session.to_dict(),
                "interface": {
                    **session.interface.to_dict(),
                    "inspector_width": 40,
                },
            }
        )
    )
    pending_pair_mismatch_rejected = _raises_value_error(
        lambda: CanvasTransaction.from_dict(
            {
                **transaction.to_dict(),
                "pending_preview": None,
            }
        )
    )
    pending_preview_identity_rejected = _raises_value_error(
        lambda: CanvasTransaction.from_dict(
            {
                **transaction.to_dict(),
                "pending_preview": {
                    **dict(transaction.pending_preview or {}),
                    "batch_id": "different-batch",
                },
            }
        )
    )
    pending_preview_value_rejected = _raises_value_error(
        lambda: CanvasTransaction.from_dict(
            {
                **transaction.to_dict(),
                "pending_preview": {
                    **dict(transaction.pending_preview or {}),
                    "changes": [
                        {
                            **dict((transaction.pending_preview or {})["changes"][0]),
                            "value": "Different visible value",
                        }
                    ],
                },
            }
        )
    )
    terminal_pending_rejected = _raises_value_error(
        lambda: CanvasTransaction.from_dict(
            {
                **transaction.to_dict(),
                "status": "committed",
            }
        )
    )
    tampered_request_record = assistant_record.to_dict()
    tampered_request_record["response"]["request_sha256"] = "0" * 64
    assistant_response_hash_rejected = _raises_value_error(
        lambda: AssistantRequestRecord.from_dict(tampered_request_record)
    )
    duplicate_outbox_event_rejected = _raises_value_error(
        lambda: CanvasSession.from_dict(
            {
                **transaction_session.to_dict(),
                "journal_outbox": [
                    dict(outbox_event),
                    dict(outbox_event),
                ],
            }
        )
    )
    choice_field = CanvasInspectorField(
        field_id="line_style",
        section="Line",
        label="Line style",
        setting_path="/page/graph/series/PlotLine/style",
        setting_type="choice",
        editor="choice",
        value="solid",
        choices=("solid", "dashed"),
    )
    dataset_field = CanvasInspectorField(
        field_id="x_data",
        section="Data authority",
        label="X data",
        setting_path="/page/graph/series/xData",
        setting_type="dataset-extended",
        editor="dataset",
        value="x",
        read_only=True,
    )
    auto_field = CanvasInspectorField(
        field_id="minimum",
        section="Range",
        label="Minimum",
        setting_path="/page/graph/x/min",
        setting_type="float-or-auto",
        editor="number_or_auto",
        value="Auto",
    )
    optional_text_field = CanvasInspectorField(
        field_id="legend_title",
        section="Legend",
        label="Title",
        setting_path="/page/graph/key/title",
        setting_type="str",
        editor="text",
        value="",
    )
    invalid_choice_rejected = _raises_value_error(
        lambda: choice_field.coerce_input("arbitrary")
    )
    read_only_dataset_rejected = _raises_value_error(
        lambda: dataset_field.coerce_input("replacement")
    )
    nonfinite_data_point_rejected = _raises_value_error(
        lambda: CanvasDataPointSelection(
            target_object_id=axis.object_id,
            x=float("nan"),
            y=1.0,
            graph_x=2.0,
            graph_y=3.0,
        )
    )
    nonprimary_data_point_rejected = _raises_value_error(
        lambda: CanvasSelection(
            object_ids=[axis.object_id, "another-object"],
            primary_object_id="another-object",
            data_point=CanvasDataPointSelection(
                target_object_id=axis.object_id,
                x=1.0,
                y=2.0,
                graph_x=3.0,
                graph_y=4.0,
            ),
        )
    )
    native_annotation_index_rejected = _raises_value_error(
        lambda: CanvasOperation.add_widget(
            target_id=page.object_id,
            widget_type="label",
            name="review_contract",
            index=4,
            settings={
                "positioning": "relative",
                "xPos": [0.1],
                "yPos": [0.9],
                "label": "Unsafe placement",
            },
        )
    )
    native_annotation_setting_rejected = _raises_value_error(
        lambda: CanvasOperation.add_widget(
            target_id=page.object_id,
            widget_type="label",
            name="review_contract",
            settings={
                "positioning": "relative",
                "xPos": [0.1],
                "yPos": [0.9],
                "label": "Unsafe setting",
                "python": "print('unsafe')",
            },
        )
    )
    invalid_annotation_geometry_rejected = _raises_value_error(
        lambda: ReviewAnnotation(
            page_index=0,
            shape="arrow",
            coordinate_space="normalized_page",
            geometry={"start": [0.2, 0.2], "end": [1.2, 0.5]},
        )
    )
    invalid_annotation_style_rejected = _raises_value_error(
        lambda: ReviewAnnotationStyle(color="orange")
    )
    checks = [
        _check(
            "session_roundtrip",
            "CanvasSession version 6 persists workbench, point-selection, and structural-QA state without Qt",
            loaded.session_id == session.session_id
            and loaded.state == "canvas_ready"
            and loaded.interface.to_dict() == session.interface.to_dict()
            and loaded.selection.to_dict() == session.selection.to_dict()
            and loaded.structural_qa_summary == session.structural_qa_summary,
        ),
        _check(
            "session_v1_migration",
            "CanvasSession version 1 payloads migrate to safe M2 interface defaults",
            migrated_legacy_session.interface.inspector_visible is True
            and migrated_legacy_session.interface.inspector_width == 340
            and migrated_legacy_session.interface.high_contrast is False
            and migrated_legacy_session.selection.data_point is None
            and not migrated_legacy_session.structural_qa_summary,
        ),
        _check(
            "session_v2_migration",
            "CanvasSession version 2 payloads migrate without inventing point or QA state",
            migrated_version_two_session.interface.to_dict()
            == session.interface.to_dict()
            and migrated_version_two_session.selection.data_point is None
            and not migrated_version_two_session.structural_qa_summary,
        ),
        _check(
            "assistant_transaction_session_roundtrip",
            "CanvasSession version 6 persists a hash-bound Assistant request, response, transaction, and journal outbox",
            loaded_transaction_session.active_transaction is not None
            and loaded_transaction_session.active_transaction.to_dict()
            == transaction.to_dict()
            and loaded_transaction_session.active_transaction.parsed_request_record
            is not None
            and (
                loaded_transaction_session.active_transaction.parsed_request_record.parsed_response.request_sha256
                == assistant_request.payload_sha256
            )
            and loaded_transaction_session.journal_outbox
            == transaction_session.journal_outbox
            and loaded_transaction_session.active_inspector == "assistant"
            and loaded_transaction_session.state == "ai_proposing"
            and transaction_payload_is_detached,
        ),
        _check(
            "session_v4_assistant_migration",
            "CanvasSession version 4 Assistant turns migrate without inventing provider request state",
            migrated_version_four_session.active_transaction is not None
            and (
                migrated_version_four_session.active_transaction.request_record is None
            )
            and (
                migrated_version_four_session.active_transaction.pending_batch_id
                == batch.batch_id
            ),
        ),
        _check(
            "session_v5_assistant_migration",
            "CanvasSession version 5 Assistant turns remain readable after mapping-state persistence is added",
            migrated_version_five_session.active_transaction is not None
            and (
                migrated_version_five_session.active_transaction.to_dict()
                == transaction.to_dict()
            ),
        ),
        _check(
            "mapping_request_record_v1_migration",
            "AssistantRequestRecord version 1 mapping proposals migrate without inventing preview or consent",
            migrated_mapping_record_v1.status == "proposal_ready"
            and migrated_mapping_record_v1.parsed_mapping_state is not None
            and migrated_mapping_record_v1.parsed_mapping_state.status == "proposed"
            and migrated_mapping_record_v1.parsed_mapping_state.preview is None
            and migrated_mapping_record_v1.parsed_mapping_state.confirmation is None,
        ),
        _check(
            "mapping_state_roundtrip_is_hash_bound",
            "Mapping preview and confirmation state roundtrip with proposal, request, and source hashes bound",
            restored_mapping_record.parsed_mapping_state is not None
            and restored_mapping_record.parsed_mapping_state.status == "confirmed"
            and restored_mapping_record.parsed_mapping_state.preview == mapping_preview
            and (
                restored_mapping_record.parsed_mapping_state.confirmation
                == mapping_confirmation.to_dict()
            )
            and stale_mapping_binding_rejected
            and rebound_mapping_path_rejected,
        ),
        _check(
            "mapping_acceptance_requires_execution",
            "A mapping proposal cannot be accepted before execution and closes only with a hashed manifest",
            mapping_premature_accept_rejected
            and mapping_record.status == "applied"
            and mapping_record.parsed_mapping_state is not None
            and mapping_record.parsed_mapping_state.status == "executed"
            and mapping_record.parsed_mapping_state.execution_manifest_sha256
            == "f" * 64
            and mapping_record.parsed_mapping_state.mapped_document_sha256
            == "e" * 64
            and executed_mapping_reject_blocked,
        ),
        _check(
            "assistant_response_hash_is_bound",
            "Persisted Assistant responses reject a request-hash mismatch",
            assistant_response_hash_rejected,
        ),
        _check(
            "assistant_pending_pair_is_atomic",
            "Assistant transactions reject a missing or identity-mismatched pending preview",
            pending_pair_mismatch_rejected
            and pending_preview_identity_rejected
            and pending_preview_value_rejected,
        ),
        _check(
            "assistant_terminal_state_is_closed",
            "Committed transactions cannot retain pending or applying work",
            terminal_pending_rejected,
        ),
        _check(
            "assistant_journal_outbox_is_idempotent",
            "Journal outbox IDs are unique and durable appends deduplicate retries",
            duplicate_outbox_event_rejected
            and first_idempotent_append
            and not duplicate_idempotent_append
            and len(idempotent_journal) == 1
            and idempotent_journal[0].get("event_id") == outbox_event["event_id"],
        ),
        _check(
            "stable_object_identity",
            "Stable object IDs survive display-path changes",
            rebound.object_id == axis.object_id
            and rebound.current_path == "/renamed_page/renamed_graph/renamed_axis",
        ),
        _check(
            "stable_object_identity_survives_sibling_insertion",
            "Existing object IDs survive insertion of a same-type native annotation",
            reconciled_by_path["/page/title"].object_id == existing_label.object_id
            and reconciled_by_path["/page/review_contract"].object_id
            != existing_label.object_id,
        ),
        _check(
            "typed_operation_roundtrip",
            "CanvasOperationBatch version 1 roundtrips with its base revision",
            restored_batch.to_dict() == batch.to_dict(),
        ),
        _check(
            "review_annotation_is_non_exported",
            "ReviewAnnotation version 2 persists as a review-only sidecar object",
            len(loaded_annotations) == 1
            and loaded_annotations[0].state == "review_only"
            and loaded_annotations[0].to_dict()["version"] == REVIEW_ANNOTATION_VERSION,
        ),
        _check(
            "review_annotation_v1_migration",
            "ReviewAnnotation version 1 payloads migrate to bounded default style",
            migrated_legacy_annotation.style == ReviewAnnotationStyle()
            and migrated_legacy_annotation.to_dict()["version"]
            == REVIEW_ANNOTATION_VERSION,
        ),
        _check(
            "native_annotation_operation_roundtrip",
            "Typed native annotation operations preserve widget type, draw index, and bounded settings",
            restored_native_annotation_operation.to_dict()
            == native_annotation_operation.to_dict()
            and restored_native_annotation_operation.arguments["index"] == 0,
        ),
        _check(
            "native_annotation_schema_is_closed",
            "Native annotation operations reject unsafe draw positions and renderer settings",
            native_annotation_index_rejected and native_annotation_setting_rejected,
        ),
        _check(
            "review_annotation_geometry_is_bounded",
            "Normalized review coordinates and style colors reject invalid values",
            invalid_annotation_geometry_rejected and invalid_annotation_style_rejected,
        ),
        _check(
            "mapping_proposal_is_declarative",
            "DataMappingProposal carries source hashes and cannot execute before confirmation",
            restored_proposal.source_hashes == proposal.source_hashes
            and restored_proposal.executable is False,
        ),
        _check(
            "journal_is_append_only_jsonl",
            "The operation journal records a typed batch as JSONL",
            len(journal) == 1
            and (journal[0].get("batch") or {}).get("batch_id") == batch.batch_id,
        ),
        _check(
            "operation_schema_is_closed",
            "Typed setting operations reject undeclared executable arguments",
            operation_schema_rejected,
        ),
        _check(
            "mapping_schema_rejects_executable_content",
            "Declarative data mappings reject nested executable content",
            executable_mapping_rejected,
        ),
        _check(
            "operation_payload_schema_is_closed",
            "Typed operation payloads reject undeclared top-level fields",
            operation_top_level_rejected,
        ),
        _check(
            "boolean_types_are_not_coerced",
            "Typed batches reject string values masquerading as booleans",
            boolean_coercion_rejected,
        ),
        _check(
            "mapping_payload_schema_is_closed",
            "Data mapping payloads reject undeclared top-level fields",
            mapping_top_level_rejected,
        ),
        _check(
            "session_computed_state_is_verified",
            "CanvasSession rejects persisted dirty state that conflicts with revisions",
            session_integrity_rejected,
        ),
        _check(
            "interface_state_schema_is_bounded",
            "Canvas interface state rejects unsafe persisted geometry",
            invalid_interface_rejected,
        ),
        _check(
            "inspector_choice_schema_is_closed",
            "Contextual choice fields reject arbitrary renderer values",
            choice_field.coerce_input("dashed") == "dashed" and invalid_choice_rejected,
        ),
        _check(
            "inspector_data_mapping_is_read_only",
            "Dataset mapping cannot be rewritten from the visual inspector",
            read_only_dataset_rejected,
        ),
        _check(
            "inspector_auto_range_is_typed",
            "Auto-range fields normalize only finite numbers or the explicit Auto token",
            auto_field.coerce_input("auto") == "Auto"
            and auto_field.coerce_input(1.5) == 1.5,
        ),
        _check(
            "inspector_optional_text_accepts_empty",
            "Legitimate empty labels and titles do not block unrelated edits",
            optional_text_field.coerce_input("") == "",
        ),
        _check(
            "data_point_schema_rejects_nonfinite_coordinates",
            "Persisted data-point selections reject non-finite coordinates",
            nonfinite_data_point_rejected,
        ),
        _check(
            "data_point_schema_requires_primary_target",
            "A persisted point selection cannot target a background object",
            nonprimary_data_point_rejected,
        ),
    ]
    return {
        "kind": "sciplot_canvas_contract_probe",
        "version": 1,
        "status": "passed"
        if all(item["status"] == "passed" for item in checks)
        else "failed",
        "checks": checks,
        "artifacts": {
            "session": str(session_path),
            "transaction_session": str(transaction_session_path),
            "annotations": str(annotations_path),
            "journal": str(journal_path),
            "idempotent_journal": str(idempotent_journal_path),
        },
    }


def run_canvas_characterization(
    document_path: Path,
    *,
    output_root: Path,
) -> dict[str, Any]:
    """Characterize the pinned embedded Veusz lifecycle on a copied VSZ."""

    source = document_path.expanduser().resolve()
    if not source.is_file():
        raise FileNotFoundError(source)
    resolved_output = output_root.expanduser().resolve()
    resolved_output.mkdir(parents=True, exist_ok=True)
    run_root = Path(
        tempfile.mkdtemp(prefix="canvas_characterization_", dir=resolved_output)
    )
    summary_path = run_root / "canvas_characterization.json"
    copied_document = run_root / "document.vsz"
    shutil.copy2(source, copied_document)
    source_hash = file_sha256(source)

    session_path = run_root / "canvas_session.json"
    journal_path = run_root / "operation_journal.jsonl"
    export_root = run_root / "exact_current_export"
    recovery_root = run_root / "crash_recovery"
    checks: list[dict[str, Any]] = []
    controller: Any = None
    stderr_stack = ExitStack()
    stderr_log = run_root / "logs" / "canvas_qt_stderr.log"
    error: dict[str, str] | None = None
    evidence: dict[str, Any] = {}

    try:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from sciplot_core.studio import _capture_process_stderr, export_studio_document
        from sciplot_gui.document_controller import DocumentController

        stderr_stack.enter_context(_capture_process_stderr(stderr_log))
        controller = DocumentController(
            document_path=copied_document,
            session_path=session_path,
            journal_path=journal_path,
            project_id=source.stem,
        )
        initial_render = controller.adapter.render_fingerprint()
        embedded_window_class = type(controller.adapter.plot_window).__name__
        embedded_document_class = type(controller.adapter.document).__name__
        target = controller.adapter.first_visible_text_target(controller.session)
        original_value = target["value"]
        new_value = (
            f"{original_value} [M0 Canvas]"
            if str(original_value).strip()
            else "M0 Canvas axis"
        )
        stable_ids_before = {
            item["structural_key"]: item["object_id"] for item in controller.inventory
        }

        batch = CanvasOperationBatch(
            base_revision=controller.session.revision,
            provider="m0_characterization",
            rationale="M0 live text-setting redraw characterization",
            operations=(
                CanvasOperation.set_setting(
                    target_id=target["object_id"],
                    setting_path=target["setting_path"],
                    value=new_value,
                    expected_value=original_value,
                    require_expected_value=True,
                ),
            ),
        )
        apply_entry = controller.apply_batch(batch)
        applied_render = controller.adapter.render_fingerprint()
        recovered_after_apply = load_canvas_session(session_path)
        applied_value = controller.adapter.setting_value(target["setting_path"])

        undo_entry = controller.undo(provider="m0_characterization")
        undo_render = controller.adapter.render_fingerprint()
        undo_value = controller.adapter.setting_value(target["setting_path"])

        redo_entry = controller.redo(provider="m0_characterization")
        redo_render = controller.adapter.render_fingerprint()
        redo_value = controller.adapter.setting_value(target["setting_path"])
        interactions = controller.adapter.interaction_characterization()
        saved_document = controller.save()
        saved_hash = file_sha256(saved_document)
        saved_revision = controller.session.saved_revision
        controller.close()
        controller = None

        reopened = DocumentController(
            document_path=copied_document,
            session_path=session_path,
            journal_path=journal_path,
            project_id=source.stem,
        )
        controller = reopened
        reopened_render = reopened.adapter.render_fingerprint()
        reopened_target = reopened.adapter.first_visible_text_target(reopened.session)
        reopened_value = reopened.adapter.setting_value(reopened_target["setting_path"])
        stable_ids_after = {
            item["structural_key"]: item["object_id"] for item in reopened.inventory
        }
        export_payload = export_studio_document(
            copied_document,
            formats=["pdf", "tiff_300"],
            output_dir=export_root,
        )
        exports = (
            export_payload.get("exports")
            if isinstance(export_payload.get("exports"), list)
            else []
        )
        reopened.mark_exported(exports)
        reopened.close()
        controller = None

        recovery_root.mkdir(parents=True, exist_ok=True)
        recovery_document = recovery_root / "document.vsz"
        recovery_session_path = recovery_root / "canvas_session.json"
        recovery_journal_path = recovery_root / "operation_journal.jsonl"
        shutil.copy2(source, recovery_document)
        recovery_controller = DocumentController(
            document_path=recovery_document,
            session_path=recovery_session_path,
            journal_path=recovery_journal_path,
            project_id=f"{source.stem}_recovery",
        )
        controller = recovery_controller
        recovery_target = recovery_controller.adapter.first_visible_text_target(
            recovery_controller.session
        )
        recovery_original_value = recovery_target["value"]
        recovery_new_value = (
            f"{recovery_original_value} [M0 Recovery]"
            if str(recovery_original_value).strip()
            else "M0 Recovery"
        )
        recovery_controller.apply_batch(
            CanvasOperationBatch(
                base_revision=recovery_controller.session.revision,
                provider="m0_crash_recovery",
                rationale="Persist an accepted unsaved edit as a recovery VSZ.",
                operations=(
                    CanvasOperation.set_setting(
                        target_id=recovery_target["object_id"],
                        setting_path=recovery_target["setting_path"],
                        value=recovery_new_value,
                        expected_value=recovery_original_value,
                        require_expected_value=True,
                    ),
                ),
            )
        )
        recovery_expected_render = recovery_controller.adapter.render_fingerprint()
        recovery_snapshot = _resolve_persisted_path(
            recovery_controller.session.recovery_snapshots[-1],
            root=recovery_session_path.parent,
        )
        recovery_controller.close()
        controller = None

        escaped_root = run_root / "escaped_recovery"
        shutil.copytree(recovery_root, escaped_root)
        escaped_session_path = escaped_root / "canvas_session.json"
        escaped_journal_path = escaped_root / "operation_journal.jsonl"
        escaped_document = escaped_root / "document.vsz"
        outside_snapshot = run_root / "outside_recovery.vsz"
        shutil.copy2(recovery_snapshot, outside_snapshot)
        escaped_session = load_canvas_session(escaped_session_path)
        escaped_reference = "../outside_recovery.vsz"
        escaped_session.recovery_snapshots = [escaped_reference]
        escaped_session.recovery_snapshot_hashes = {
            escaped_reference: file_sha256(outside_snapshot)
        }
        save_canvas_session(escaped_session_path, escaped_session)
        escaped_recovery_rejected = False
        escaped_recovery_error = ""
        try:
            escaped_controller = DocumentController(
                document_path=escaped_document,
                session_path=escaped_session_path,
                journal_path=escaped_journal_path,
                project_id=f"{source.stem}_escaped_recovery",
            )
        except RuntimeError as exc:
            escaped_recovery_rejected = "outside" in str(exc)
            escaped_recovery_error = str(exc)
        else:
            controller = escaped_controller
            escaped_controller.close()
            controller = None

        tampered_root = run_root / "tampered_recovery"
        shutil.copytree(recovery_root, tampered_root)
        tampered_session_path = tampered_root / "canvas_session.json"
        tampered_journal_path = tampered_root / "operation_journal.jsonl"
        tampered_document = tampered_root / "document.vsz"
        tampered_session = load_canvas_session(tampered_session_path)
        tampered_snapshot = _resolve_persisted_path(
            tampered_session.recovery_snapshots[-1],
            root=tampered_session_path.parent,
        )
        with tampered_snapshot.open("a", encoding="utf-8") as handle:
            handle.write("\n# M0 tampered recovery probe\n")
        tampered_recovery_rejected = False
        tampered_recovery_error = ""
        try:
            tampered_controller = DocumentController(
                document_path=tampered_document,
                session_path=tampered_session_path,
                journal_path=tampered_journal_path,
                project_id=f"{source.stem}_tampered_recovery",
            )
        except RuntimeError as exc:
            tampered_recovery_rejected = "integrity" in str(exc)
            tampered_recovery_error = str(exc)
        else:
            controller = tampered_controller
            tampered_controller.close()
            controller = None

        recovered_controller = DocumentController(
            document_path=recovery_document,
            session_path=recovery_session_path,
            journal_path=recovery_journal_path,
            project_id=f"{source.stem}_recovery",
        )
        controller = recovered_controller
        recovery_reopened_target = (
            recovered_controller.adapter.first_visible_text_target(
                recovered_controller.session
            )
        )
        recovery_reopened_value = recovered_controller.adapter.setting_value(
            recovery_reopened_target["setting_path"]
        )
        recovery_reopened_render = recovered_controller.adapter.render_fingerprint()
        recovered_from_snapshot = recovered_controller.recovered_from_snapshot
        recovered_controller.save()
        recovered_controller.close()
        controller = None

        with recovery_document.open("a", encoding="utf-8") as handle:
            handle.write("\n# M0 external conflict probe\n")
        external_conflict_rejected = False
        external_conflict_error = ""
        try:
            conflict_controller = DocumentController(
                document_path=recovery_document,
                session_path=recovery_session_path,
                journal_path=recovery_journal_path,
                project_id=f"{source.stem}_recovery",
            )
        except RuntimeError as exc:
            external_conflict_rejected = "changed outside" in str(exc)
            external_conflict_error = str(exc)
        else:
            controller = conflict_controller
            conflict_controller.close()
            controller = None

        journal = read_operation_journal(journal_path)
        recovery_journal = read_operation_journal(recovery_journal_path)
        exports_ready = {
            str(item.get("format"))
            for item in exports
            if isinstance(item, dict)
            and item.get("exists") is True
            and int(item.get("size_bytes") or 0) > 0
        }
        evidence = {
            "source": str(source),
            "copied_document": str(copied_document),
            "target": target,
            "original_value": original_value,
            "new_value": new_value,
            "initial_render": initial_render,
            "embedded_window_class": embedded_window_class,
            "embedded_document_class": embedded_document_class,
            "applied_render": applied_render,
            "undo_render": undo_render,
            "redo_render": redo_render,
            "reopened_render": reopened_render,
            "apply_entry": apply_entry,
            "undo_entry": undo_entry,
            "redo_entry": redo_entry,
            "interactions": interactions,
            "saved_hash": saved_hash,
            "saved_revision": saved_revision,
            "exports": exports,
            "journal_entries": len(journal),
            "crash_recovery": {
                "snapshot": str(recovery_snapshot),
                "snapshot_exists": recovery_snapshot.is_file(),
                "expected_value": recovery_new_value,
                "reopened_value": recovery_reopened_value,
                "expected_render": recovery_expected_render,
                "reopened_render": recovery_reopened_render,
                "recovered_from_snapshot": recovered_from_snapshot,
                "journal_events": [item.get("event") for item in recovery_journal],
                "external_conflict_rejected": external_conflict_rejected,
                "external_conflict_error": external_conflict_error,
                "tampered_recovery_rejected": tampered_recovery_rejected,
                "tampered_recovery_error": tampered_recovery_error,
                "escaped_recovery_rejected": escaped_recovery_rejected,
                "escaped_recovery_error": escaped_recovery_error,
            },
        }
        checks.extend(
            [
                _check(
                    "embedded_document_renders",
                    "Veusz Document renders through an embedded PlotWindow without MainWindow",
                    bool(initial_render)
                    and embedded_window_class == "PlotWindow"
                    and embedded_document_class == "Document",
                    {
                        "render_sha256": initial_render,
                        "window_class": embedded_window_class,
                        "document_class": embedded_document_class,
                    },
                ),
                _check(
                    "typed_setting_redraws_live",
                    "One typed visible-text operation changes the live canvas",
                    applied_value == new_value and applied_render != initial_render,
                    {
                        "setting_path": target["setting_path"],
                        "before": original_value,
                        "after": applied_value,
                        "render_changed": applied_render != initial_render,
                    },
                ),
                _check(
                    "recovery_snapshot_checkpoint",
                    "Accepted operation state is serialized as a recovery VSZ before close",
                    recovered_after_apply.revision == 1
                    and recovered_after_apply.last_render_sha256 == applied_render
                    and bool(recovered_after_apply.recovery_snapshots)
                    and _resolve_persisted_path(
                        recovered_after_apply.recovery_snapshots[-1],
                        root=session_path.parent,
                    ).is_file(),
                    recovered_after_apply.to_dict(),
                ),
                _check(
                    "dirty_session_auto_recovers",
                    "A dirty session reopens from its latest recovery VSZ without changing the canonical source",
                    recovery_snapshot.is_file()
                    and recovered_from_snapshot == str(recovery_snapshot.resolve())
                    and recovery_reopened_value == recovery_new_value
                    and recovery_reopened_render == recovery_expected_render
                    and "recovered_from_snapshot"
                    in {str(item.get("event")) for item in recovery_journal},
                    evidence["crash_recovery"],
                ),
                _check(
                    "external_vsz_conflict_blocks",
                    "A clean session refuses a canonical VSZ changed outside its revision history",
                    external_conflict_rejected,
                    evidence["crash_recovery"],
                ),
                _check(
                    "tampered_recovery_snapshot_blocks",
                    "A dirty session rejects a recovery VSZ whose recorded hash no longer matches",
                    tampered_recovery_rejected,
                    evidence["crash_recovery"],
                ),
                _check(
                    "recovery_path_escape_blocks",
                    "A dirty session rejects recovery references outside its project recovery root",
                    escaped_recovery_rejected,
                    evidence["crash_recovery"],
                ),
                _check(
                    "atomic_undo",
                    "The typed batch undoes as one Veusz history operation",
                    undo_value == original_value and undo_render == initial_render,
                    {
                        "value": undo_value,
                        "render_restored": undo_render == initial_render,
                    },
                ),
                _check(
                    "atomic_redo",
                    "The typed batch redoes and restores the edited render",
                    redo_value == new_value and redo_render == applied_render,
                    {
                        "value": redo_value,
                        "render_restored": redo_render == applied_render,
                    },
                ),
                _check(
                    "plotwindow_object_click",
                    "Embedded PlotWindow emits an object-selection signal",
                    interactions.get("selection_signal_received") is True,
                    interactions,
                ),
                _check(
                    "plotwindow_axis_coordinates",
                    "Embedded PlotWindow reports axis coordinates for a canvas point",
                    interactions.get("axis_coordinates_reported") is True,
                    interactions,
                ),
                _check(
                    "save_reopen_exact_state",
                    "The edited VSZ saves and reopens with the accepted value",
                    reopened_value == new_value
                    and saved_hash == file_sha256(copied_document)
                    and saved_revision == 3
                    and bool(reopened_render),
                    {
                        "reopened_value": reopened_value,
                        "saved_revision": saved_revision,
                        "render_sha256": reopened_render,
                    },
                ),
                _check(
                    "stable_object_ids_after_reopen",
                    "SciPlot object IDs remain stable across save and reopen",
                    stable_ids_before == stable_ids_after,
                    {
                        "object_count_before": len(stable_ids_before),
                        "object_count_after": len(stable_ids_after),
                    },
                ),
                _check(
                    "exact_current_export",
                    "The exact edited VSZ exports the canonical PDF/TIFF pair",
                    {"pdf", "tiff_300"} <= exports_ready,
                    {"formats": sorted(exports_ready), "exports": exports},
                ),
                _check(
                    "source_document_immutable",
                    "Characterization modifies only its copied VSZ",
                    file_sha256(source) == source_hash and source != copied_document,
                    {"source_sha256": source_hash},
                ),
                _check(
                    "typed_operation_journal",
                    "Apply, undo, redo, save, and export events are auditable",
                    {
                        "operation_batch_applied",
                        "undo",
                        "redo",
                        "save",
                        "exact_current_export",
                    }
                    <= {str(item.get("event")) for item in journal},
                    {"events": [item.get("event") for item in journal]},
                ),
            ]
        )
    except Exception as exc:
        error = {"type": type(exc).__name__, "message": str(exc)}
        checks.append(
            _check(
                "canvas_characterization_exception",
                "Canvas characterization completes without an exception",
                False,
                error,
            )
        )
    finally:
        if controller is not None:
            try:
                controller.close()
            except Exception:
                pass
        stderr_stack.close()

    status = (
        "passed"
        if checks and all(item["status"] == "passed" for item in checks)
        else "failed"
    )
    payload = {
        "kind": CANVAS_CHARACTERIZATION_KIND,
        "version": CANVAS_CHARACTERIZATION_VERSION,
        "generated_at": _now(),
        "status": status,
        "state": "ready" if status == "passed" else "needs_rule_repair",
        "checks": checks,
        "summary": {
            "check_count": len(checks),
            "passed_count": sum(item["status"] == "passed" for item in checks),
            "failed_ids": [item["id"] for item in checks if item["status"] != "passed"],
        },
        "evidence": evidence,
        "artifacts": {
            "run_root": str(run_root),
            "copied_document": str(copied_document),
            "session": str(session_path),
            "journal": str(journal_path),
            "exports": str(export_root),
            "recovery_root": str(recovery_root),
            "stderr_log": str(stderr_log) if stderr_log.is_file() else None,
            "summary": str(summary_path),
        },
        "error": error,
        "limitations": [
            "This probe characterizes the pinned Veusz adapter and typed setting path; "
            "it is not the user-facing native Canvas shell.",
            "The probe works on a copied VSZ and does not count as real-data acceptance "
            "unless the supplied source VSZ itself came from authorized real data.",
        ],
    }
    summary_path.write_text(
        json.dumps(json_safe(payload), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return payload


__all__ = [
    "CANVAS_CHARACTERIZATION_KIND",
    "CANVAS_CHARACTERIZATION_VERSION",
    "run_canvas_characterization",
    "run_canvas_contract_probe",
]
