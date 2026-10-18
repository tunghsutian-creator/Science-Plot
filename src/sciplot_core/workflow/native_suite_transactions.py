"""Bound native display deltas reuse suite previews, publication and recovery."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_document import validate_patch
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_engine.contracts import validate_decide, validate_resume
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.studio_core.project_session import external_project_session
from sciplot_core.workflow.native_suite_objects import capture_object, descriptor, require_object, native_identity, selected_spec
from sciplot_core.workflow.native_suite_preview import baseline_files, prepare_preview
from sciplot_core.workflow.native_suite_storage import (
    operation_path, operation_paths, read_operation, require_idle, result_for, save_operation,
)


def _check_identity(context: dict[str, Any], request: dict[str, Any]) -> None:
    if request["plot_id"] != context["plot_id"]:
        raise EngineError("document_identity_conflict", "The request belongs to a different native figure.")
    if request["base_revision"] != context["revision"]:
        raise EngineError("document_revision_conflict", "Read the current object revision before changing it.",
                          action="plot.describe", current_revision=context["revision"])


def _changes(context: dict[str, Any], request: dict[str, Any]) -> tuple[list[Any], list[Any]]:
    if request["intent_class"] != "presentation":
        raise EngineError("native_object_intent_unsupported", "This native adapter accepts presentation deltas only.")
    targets, seen, diff, native = context["state"]["targets"], set(), [], []
    for change in request["changes"]:
        prop, value = change["property"], change["value"]
        for identifier in change["target"]:
            item = targets.get(identifier)
            if item is None:
                raise EngineError("document_unknown_target", "Choose an existing advertised target.")
            if prop not in item["properties"]:
                raise EngineError("document_unsupported_property", "This object does not advertise that property.")
            if (identifier, prop) in seen:
                raise EngineError("document_duplicate_change", "Set each target/property once per transaction.")
            seen.add((identifier, prop))
            validate_wire(value, descriptor(prop)["value_schema"], code="figure_edit_invalid_value")
            before = item["properties"][prop]
            if before == value:
                continue
            diff.append({"target": identifier, "property": prop, "before": deepcopy(before),
                         "after": deepcopy(value), "risk": "presentation"})
            native.append({"target": identifier, "property": prop, "value": deepcopy(value),
                           "before_native": deepcopy(item["native_fields"])})
    return diff, native


def _advance(context: dict[str, Any], record: dict[str, Any], path: Path, *, replayed: bool = False) -> dict[str, Any]:
    if record["phase"] in {"complete", "rejected", "needs_review"}:
        return _result(context, record, path, replayed=replayed)
    try:
        record = prepare_preview(context, record, path)
    except Exception as exc:
        record["error"] = {"reason_code": getattr(exc, "reason_code", "native_display_preview_failed"),
                           "message": str(exc)[:500], "action": "plot.resume"}
        save_operation(path, record)
    return result_for(record, path, replayed=replayed)


def _current_exports(context: dict[str, Any], native_sha: str) -> list[dict[str, Any]]:
    from sciplot_core.workflow.rheology_tts_suite import _figure_folder

    receipts = context["manifest"].get("last_export", context["manifest"]["native_result"]["figures"])
    receipt = next((item for item in receipts if Path(item["document"]).stem == context["figure_id"]), None)
    if receipt is None or receipt["document_sha256"] != native_sha:
        return []
    exports = receipt["exports"]
    folder = _figure_folder(Path(context["delivery"]), context["figure_id"])
    expected = {folder / f"{context['figure_id']}{suffix}" for suffix in (".pdf", "_300dpi.tiff", "_300dpi.png")}
    if (len(exports) != 3 or {item["format"] for item in exports} != {"pdf", "tiff_300", "png_300"}
            or {Path(item["path"]) for item in exports} != expected):
        return []
    if any(not Path(item["path"]).is_file() or file_sha256(Path(item["path"])) != item["sha256"] for item in exports):
        return []
    return deepcopy(exports)


def _result(context: dict[str, Any], record: dict[str, Any], path: Path, *, replayed: bool = False) -> dict[str, Any]:
    result = result_for(record, path, replayed=replayed)
    if record["phase"] == "complete":
        receipts = (context["manifest"].get("presentation_revision", {}).get("figures")
                    or context["manifest"]["native_result"]["figures"])
        receipt = next((item for item in receipts if item["id"] == context["figure_id"]), None)
        spec = Path(receipt["spec_path"]) if receipt else None
        current = (context["manifest"]["sources"] == record["sources"]
            and file_sha256(Path(context["plot"])) == record["presentation_hash"]
            and spec is not None and spec.is_file() and not spec.is_symlink()
            and file_sha256(spec) == record["spec_sha256"]
            and all(Path(source["path"]).is_file() and file_sha256(Path(source["path"])) == source["sha256"]
                    for source in record["sources"]))
        exports = _current_exports(context, record["presentation_hash"]) if current else []
        result["current_state_matches"] = current
        result["ready_to_use"] = bool(exports)
        if not exports:
            result["export_status"] = "pending" if current else "unknown"
            result["next_step"] = {"action": "plot.export" if current else "plot.describe", "plot": context["plot"]}
    return result


def patch_native(target: Path, request: dict[str, Any]) -> dict[str, Any]:
    request = validate_patch(request)
    context = require_object(target)
    with external_project_session(Path(context["workspace"])):
        context = require_object(target)
        path = operation_path(context, request["idempotency_key"])
        record = read_operation(path)
        if record is not None:
            if record["request"] != request:
                raise EngineError("document_idempotency_conflict", "This key belongs to a different request.")
            return _advance(context, record, path, replayed=True)
        require_idle(context)
        captured = capture_object(context)
        _check_identity(captured, request)
        diff, native = _changes(captured, request)
        record = {"kind": "sciplot_native_display_operation", "version": 1, "plot": context["plot"],
            "figure_id": context["figure_id"], "request": request, "phase": "planned",
            "decision_id": canonical_json_sha256({"plot": context["plot"], "request": request}),
            "scientific_hash": captured["scientific_hash"], "before_native_sha256": captured["presentation_hash"],
            "diff": diff, "native_changes": native, "baseline": baseline_files(context),
            "sources": deepcopy(context["manifest"]["sources"]), "spec_sha256": captured["spec_sha256"]}
        if not diff:
            record.update(phase="complete", revision=captured["revision"],
                          presentation_hash=captured["presentation_hash"],
                          exports=_current_exports(context, captured["presentation_hash"]))
        save_operation(path, record)
        return _advance(context, record, path)


def resume_native(target: Path, request: dict[str, Any]) -> dict[str, Any]:
    request = validate_resume(request)
    context = require_object(target)
    with external_project_session(Path(context["workspace"])):
        path = operation_path(context, request["idempotency_key"])
        record = read_operation(path)
        if record is None or any(record["request"][key] != request[key] for key in request):
            raise EngineError("document_unknown_transaction", "No saved native edit matches this recovery request.")
        return _advance(require_object(target), record, path, replayed=True)


def _decision_record(context: dict[str, Any], request: dict[str, Any]) -> tuple[Path, dict[str, Any]]:
    for path in operation_paths(context):
        record = read_operation(path)
        if record is not None and record["plot"] == context["plot"] and record["decision_id"] == request["decision_id"]:
            if record["request"]["base_revision"] != request["base_revision"]:
                break
            return path, record
    raise EngineError("document_invalid_decision", "Use the exact decision and base revision returned by this object.")


def decide_native(target: Path, request: dict[str, Any]) -> dict[str, Any]:
    request = validate_decide(request)
    if set(request) != {"decision_id", "base_revision", "accept"}:
        raise EngineError("document_invalid_decision", "Native display decisions require boolean accept.")
    context = require_object(target)
    with external_project_session(Path(context["workspace"])):
        return _decide_locked(require_object(target), request)


def _decide_locked(context: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.workflow.rheology_tts_style_update import apply_suite_style

    path, record = _decision_record(context, request)
    if record["phase"] in {"complete", "rejected"}:
        return _result(context, record, path, replayed=True)
    if not request["accept"]:
        record.update(phase="rejected")
        save_operation(path, record)
        return result_for(record, path)
    if record["phase"] != "needs_review":
        raise EngineError("document_preview_unavailable", "Resume the saved edit to obtain its native preview first.")
    applied = apply_suite_style(Path(context["workspace"]), Path(record["preview"]),
                                native_display=True, _session_held=True)
    # Read no native document a second time: exact reviewed candidate bytes have
    # already passed numerical/unowned-state audits and guarded publication.
    current = require_object(Path(context["plot"]))
    spec, _ = selected_spec(current)
    native_sha = file_sha256(Path(context["plot"]))
    identity = native_identity(context["workspace"], context["figure_id"],
        current["manifest"]["sources"], file_sha256(spec), native_sha)
    receipt = next(item for item in current["manifest"]["last_export"]
                   if Path(item["document"]).stem == context["figure_id"])
    record.update(phase="complete", revision=identity["revision"], presentation_hash=native_sha,
                  exports=receipt["exports"], publication=applied)
    save_operation(path, record)
    return result_for(record, path)


def export_native(target: Path) -> dict[str, Any]:
    from sciplot_core.workflow.rheology_tts_suite import _export_saved_suite

    context = require_object(target)
    with external_project_session(Path(context["workspace"])):
        context = require_object(target)
        require_idle(context)
        result = _export_saved_suite(Path(context["workspace"]), figure_ids=(context["figure_id"],))
        current = require_object(target)
        spec, _ = selected_spec(current)
        identity = native_identity(context["workspace"], context["figure_id"],
            current["manifest"]["sources"], file_sha256(spec), file_sha256(Path(context["plot"])))
    return {**result, "kind": "sciplot_plot_result", "version": 1, "status": "complete",
            **identity, "plot": context["plot"], "plot_type": "LegacyPlot", "ready_to_use": True,
            "scope": "single_figure", "scientific_hash_changed": False}
