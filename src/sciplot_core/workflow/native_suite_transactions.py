"""Native object commands prepare privately and publish one project generation."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import tempfile
from typing import Any

from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
import json
from sciplot_core.plot_document import validate_patch
from sciplot_core.plot_document.validation import validate_wire
from sciplot_core.plot_engine.contracts import validate_decide, validate_resume
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.project_commands import ProjectCommand, ProjectCommands, ProjectMutation
from sciplot_core.project_store import FileProjectStore
from sciplot_core.workflow.native_suite_generation import (
    command_for, json_bytes, mutation, saved_command, suite_paths,
)
from sciplot_core.workflow.native_suite_objects import capture_object, descriptor, require_object, native_identity, selected_spec
from sciplot_core.workflow.native_suite_runtime import native_runtime, suite_runtime


from sciplot_core.workflow.native_suite_admission import _admit_wire_before_runtime
from sciplot_core.workflow.native_suite_command_records import _application, _request, _key, _preview_export
from sciplot_core.workflow.native_suite_receipts import _public, _legacy_result, _current_exports
from sciplot_core.workflow.native_suite_review_exports import _resume_preview_export, _publish_reviewed_exports

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


def _prepare_requested(context: dict[str, Any], request: dict[str, Any], store: FileProjectStore) -> ProjectMutation:
    captured = capture_object(context)
    _check_identity(captured, request)
    diff, changes = _changes(captured, request)
    if diff:
        return _prepare(context, captured, request, diff, changes, store)
    _reads, writes = suite_paths(Path(context["workspace"]), context["manifest"], (context["figure_id"],), native_writes=True)
    current = store.snapshot()
    unchanged = {path: store.read_bytes(store.logical_path(path)) if store.logical_path(path) in current["files"] else None
                 for path in writes}
    result = {"plot": context["plot"], "figure_id": context["figure_id"], "request": request,
        "scientific_hash": captured["scientific_hash"], "before_native_sha256": captured["presentation_hash"],
        "presentation_hash": captured["presentation_hash"], "revision": captured["revision"],
        "spec_sha256": captured["spec_sha256"], "sources": context["manifest"]["sources"], "diff": [], "no_change": True}
    return mutation(store, unchanged, result, sources=result["sources"])


def _finish_preview(app: ProjectCommands, command: ProjectCommand, record: dict[str, Any]) -> dict[str, Any]:
    if record["phase"] == "needs_review" and record["result"].get("no_change"):
        return app.decide(command, decision_id=record["decision_id"], accept=True)
    return record


def _prepare(context: dict[str, Any], captured: dict[str, Any], request: dict[str, Any],
             diff: list[Any], native: list[Any], store: FileProjectStore) -> ProjectMutation:
    with suite_runtime(Path(context["workspace"])):
        return _prepare_current(context, captured, request, diff, native, store)


def _prepare_current(context: dict[str, Any], captured: dict[str, Any], request: dict[str, Any],
                     diff: list[Any], native: list[Any], store: FileProjectStore) -> ProjectMutation:
    from sciplot_core.rheology_tts_render import export_tts_document, patch_tts_display
    from sciplot_core.workflow.rheology_tts_contract import rheology_capabilities
    from sciplot_core.workflow.rheology_tts_style_update import publication_updates
    from sciplot_core.workflow.rheology_tts_saved_state import _check_sources

    with tempfile.TemporaryDirectory(prefix="sciplot-native-command-") as temporary:
        directory = Path(temporary).resolve()
        candidate = directory / Path(context["plot"]).name
        edit = patch_tts_display(Path(context["plot"]), candidate, captured["figure"], native,
                                 captured["presentation_hash"])
        digest = file_sha256(candidate)
        if digest != edit["document_sha256"]:
            raise ValueError("Native candidate does not match its audited receipt.")
        artifacts = {"native.vsz": candidate.read_bytes()}
        error = None
        try:
            exported = export_tts_document(candidate, directory / "exports" / context["figure_id"], captured["figure"])
        except Exception as exc:
            # The exact audited native mutation is retained, independently from
            # its read-only export. Resume may export this sealed candidate; it
            # never invokes the native edit callback again.
            error = {"reason_code": "native_preview_export_pending", "message": str(exc)[:500]}
            exported = {"document": str(candidate), "document_sha256": digest, "exports": [],
                        "native_audit": deepcopy(edit.get("candidate_audit", edit.get("native_audit", {})))}
        if exported["document_sha256"] != digest:
            raise ValueError("Native candidate changed during export.")
        from sciplot_core.workflow.rheology_tts_saved_state import _active_receipts
        preview = {"contract_sha256": rheology_capabilities()["contract_sha256"],
            "figures": deepcopy(_active_receipts(context["manifest"])),
            "candidates": [{"id": context["figure_id"], "edit": edit, "export": exported}], "presentation_plan": {}}
        updates = publication_updates(Path(context["workspace"]), context["manifest"], preview,
                                      directory, native_display=True)
        _, writes = suite_paths(Path(context["workspace"]), context["manifest"], (context["figure_id"],), native_writes=True)
        for path in writes:
            if path not in updates:
                name = store.logical_path(path)
                updates[path] = store.read_bytes(name) if name in store.snapshot()["files"] else None
        if exported["exports"]:
            artifacts["preview.png"] = Path(next(item["path"] for item in exported["exports"] if item["format"] == "png_300")).read_bytes()
        artifacts["preview.json"] = json_bytes({"kind": "sciplot_native_display_preview", "version": 2,
            "figure_id": context["figure_id"], "native_artifact": "native.vsz", "native_sha256": digest,
            "scientific_hash": captured["scientific_hash"], "diff": diff, "export_pending": error is not None})
        identity = native_identity(context["manifest"]["workspace"], context["figure_id"], context["manifest"]["sources"],
                                   captured["spec_sha256"], digest)
        result = {"plot": context["plot"], "figure_id": context["figure_id"], "request": request,
            "scientific_hash": captured["scientific_hash"], "before_native_sha256": captured["presentation_hash"],
            "presentation_hash": digest, "revision": identity["revision"], "spec_sha256": captured["spec_sha256"],
            "sources": deepcopy(context["manifest"]["sources"]), "diff": diff, "error": error,
            "export_pending": error is not None}
        _check_sources(result["sources"])
        return mutation(store, updates, result, sources=result["sources"],
            review={"adapter": "native_display", "figure_id": context["figure_id"],
                    "preview": "preview.json", "preview_image": "preview.png", "native": "native.vsz"}, artifacts=artifacts)


def _import_legacy_preview(context: dict[str, Any], record: dict[str, Any], path: Path,
                           store: FileProjectStore, app: ProjectCommands) -> dict[str, Any]:
    """Freeze an already reviewed legacy candidate without rerunning its edit."""
    from sciplot_core.workflow.native_suite_preview import check_acceptance
    from sciplot_core.workflow.native_suite_storage import recorded_decision
    from sciplot_core.workflow.rheology_tts_style_update import publication_updates
    request = validate_patch(record["request"])
    if record.get("plot") != context["plot"] or record.get("figure_id") != context["figure_id"]:
        raise EngineError("document_identity_conflict", "The legacy candidate belongs to another native figure.")
    if record["phase"] not in {"needs_review", "prepared"} or not record.get("preview"):
        raise EngineError("native_legacy_transaction_requires_inspection", "Unsealed legacy native effects cannot be reapplied.")
    if record.get("sources") != context["manifest"]["sources"]:
        raise ValueError("Legacy candidate source bindings disagree with its selected suite.")
    spec, _figure = selected_spec(context)
    if (record.get("spec_sha256") != file_sha256(spec)
            or record.get("scientific_hash") != canonical_json_sha256(json.loads(spec.read_bytes()))):
        raise ValueError("Legacy scientific specification binding changed.")
    roots = (Path(context["workspace"]), Path(context["delivery"]))
    source_paths = {source["path"] for source in record["sources"]}
    if any(not any(Path(name).is_relative_to(root) for root in roots) and name not in source_paths
           for name in record["baseline"]):
        raise ValueError("Legacy baseline contains an unadmitted external resource.")
    check_acceptance(context, record, path)
    preview = json.loads(Path(record["preview"]).read_bytes())
    if len(preview["candidates"]) != 1 or preview["candidates"][0]["id"] != context["figure_id"]:
        raise ValueError("Legacy native preview does not bind exactly this figure.")
    selected = preview["candidates"][0]
    if any(not Path(name).is_relative_to(path.parent) for name in preview["candidate_files"]):
        raise ValueError("Legacy candidate evidence escapes its private preview directory.")
    candidate = Path(selected["export"]["document"])
    digest = file_sha256(candidate)
    if digest != selected["export"]["document_sha256"] or digest != selected["edit"]["document_sha256"]:
        raise ValueError("Legacy native candidate bytes changed.")
    edit = selected["edit"]
    if (edit.get("source_document") != context["plot"]
            or edit.get("source_document_sha256") != record["before_native_sha256"]
            or edit.get("baseline_audit", {}).get("status") != "passed"
            or edit.get("candidate_audit", {}).get("status") != "passed"
            or edit.get("candidate_audit", {}).get("document_sha256") != digest
            or edit.get("candidate_audit", {}).get("changed_presentation", {}).get("unrelated_native_state_unchanged") is not True):
        raise ValueError("Legacy display candidate lacks its original full-state preservation audit.")
    reads, writes = suite_paths(Path(context["workspace"]), context["manifest"], (context["figure_id"],), native_writes=True)
    reads.extend(Path(name) for name in record["baseline"] if any(Path(name).is_relative_to(root) for root in roots))
    command = command_for(store, "native_patch", _key(context, request), request=_request(context, request),
        reads=reads, writes=writes, figure_id=context["figure_id"], expected_revision=request["base_revision"])
    def prepare() -> ProjectMutation:
        # This is a new read-only scientific audit of the frozen candidate,
        # never another native display mutation or a guessed continuation.
        from sciplot_core.rheology_tts_render import audit_tts_document
        spec, figure = selected_spec(context)
        audit = audit_tts_document(candidate, figure)
        if audit.get("status") != "passed" or audit.get("document_sha256") != digest:
            raise ValueError("Legacy candidate did not pass its exact current scientific audit.")
        with tempfile.TemporaryDirectory(prefix="sciplot-legacy-native-import-") as temporary:
            updates = publication_updates(Path(context["workspace"]), context["manifest"], preview,
                                          Path(temporary).resolve(), native_display=True)
            result = {**record, "presentation_hash": digest, "spec_sha256": file_sha256(spec),
                "revision": native_identity(context["manifest"]["workspace"], context["figure_id"],
                    context["manifest"]["sources"], file_sha256(spec), digest)["revision"]}
            image = next(item["path"] for item in selected["export"]["exports"] if item["format"] == "png_300")
            return mutation(store, updates, result, sources=record["sources"],
                review={"adapter": "native_display", "figure_id": context["figure_id"],
                        "legacy_decision_id": record["decision_id"], "legacy_operation": str(path)},
                artifacts={"preview.json": json_bytes({"kind": "sciplot_native_display_preview", "version": 2,
                    "native": "native.vsz", "native_sha256": digest, "legacy_decision_id": record["decision_id"]}),
                    "native.vsz": candidate.read_bytes(), "preview.png": Path(image).read_bytes()})
    imported = app.preview(command, prepare)
    if recorded_decision(context, record, path) is True:
        return app.decide(command, decision_id=imported["decision_id"], accept=True)
    return imported


@_admit_wire_before_runtime("patch")
@native_runtime(repair=True)
def patch_native(target: Path, request: dict[str, Any]) -> dict[str, Any]:
    request = validate_patch(request)
    context = require_object(target, repair=True)
    store, app = _application(context)
    original = _request(context, request)
    command = saved_command(app, _key(context, request), original)
    if command is not None:
        record = app.query(command.key)
        if record is None or record["phase"] != "reserved":
            return _public(context, app.resume(command), replayed=True)
        record = app.preview(command, lambda: _prepare_requested(context, request, store))
        return _public(context, _finish_preview(app, command, record), replayed=True)
    from sciplot_core.workflow.native_suite_storage import operation_path, read_operation
    legacy_path = operation_path(context, request["idempotency_key"])
    legacy = read_operation(legacy_path)
    if legacy is not None:
        if legacy["request"] != request:
            raise EngineError("document_idempotency_conflict", "This key belongs to a preserved legacy request.")
        if legacy["phase"] in {"complete", "rejected"}:
            return _legacy_result(context, legacy, legacy_path, replayed=True)
        return _public(context, _import_legacy_preview(context, legacy, legacy_path, store, app), replayed=True)
    from sciplot_core.workflow.native_suite_storage import require_idle
    require_idle(context)
    spec, figure = selected_spec(context)
    identity = native_identity(context["manifest"]["workspace"], context["figure_id"],
                               context["manifest"]["sources"], file_sha256(spec), file_sha256(Path(context["plot"])))
    _check_identity(identity, request)
    # Validate the advertised closed target/property/value contract before any
    # native process. Actual values and native fields are read only after admit.
    from sciplot_core.rheology_tts_native_display import native_targets
    contract = native_targets(figure)
    _changes({"state": {"targets": {name: {"properties": {prop: None for prop in item["properties"]}, "native_fields": {}}
        for name, item in contract.items()}}}, request)
    from sciplot_core.workflow.native_suite_generation import adopt_saved_native
    adopt_saved_native(store, context["manifest"], (context["figure_id"],))
    reads, writes = suite_paths(Path(context["workspace"]), context["manifest"], (context["figure_id"],), native_writes=True)
    command = command_for(store, "native_patch", _key(context, request), request=original, reads=reads,
                          writes=writes, figure_id=context["figure_id"], expected_revision=request["base_revision"])
    record = app.preview(command, lambda: _prepare_requested(context, request, store))
    return _public(context, _finish_preview(app, command, record))


@_admit_wire_before_runtime("resume")
@native_runtime(repair=True)
def resume_native(target: Path, request: dict[str, Any]) -> dict[str, Any]:
    request = validate_resume(request)
    context = require_object(target, repair=True)
    store, app = _application(context)
    record = app.query(_key(context, request))
    if record is None:
        from sciplot_core.workflow.native_suite_storage import operation_path, read_operation
        path = operation_path(context, request["idempotency_key"])
        legacy = read_operation(path)
        if legacy and all(legacy["request"][key] == request[key] for key in request):
            if legacy["phase"] in {"complete", "rejected"}:
                return _legacy_result(context, legacy, path, replayed=True)
            return _public(context, _import_legacy_preview(context, legacy, path, store, app), replayed=True)
        raise EngineError("document_unknown_transaction", "No saved generation command matches this request.")
    command = ProjectCommand.from_payload(record["metadata"])
    original = command.to_payload()["request"]
    if original.get("adapter") != "native_display" or any(original["request"][key] != request[key] for key in request):
        raise EngineError("document_idempotency_conflict", "Use this command's exact original identity.")
    resumed = app.resume(command)
    if resumed["phase"] == "needs_review" and not resumed.get("artifact_paths", {}).get("preview.png"):
        _resume_preview_export(context, resumed, store, app)
    elif resumed["phase"] == "complete" and resumed["result"].get("export_pending"):
        child = _preview_export(app, resumed)
        if child:
            _publish_reviewed_exports(require_object(target), resumed, child, store, app)
    return _public(context, resumed, replayed=True)


@_admit_wire_before_runtime("decide")
@native_runtime(repair=True)
def decide_native(target: Path, request: dict[str, Any]) -> dict[str, Any]:
    from sciplot_core.workflow.rheology_tts_saved_state import _check_sources
    request = validate_decide(request)
    if set(request) != {"decision_id", "base_revision", "accept"}:
        raise EngineError("document_invalid_decision", "Native display decisions require boolean accept.")
    context = require_object(target, repair=True)
    store, app = _application(context)
    record = app.query_decision(request["decision_id"])
    if record is None:
        aliases = [item for item in app.commands() if item.get("review", {}).get("legacy_decision_id") == request["decision_id"]]
        if len(aliases) > 1:
            raise EngineError("document_invalid_decision", "The legacy decision is ambiguous.")
        record = aliases[0] if aliases else None
    if record is None:
        from sciplot_core.workflow.native_suite_storage import operation_paths, read_operation, recorded_decision
        for path in operation_paths(context):
            legacy = read_operation(path)
            if (legacy and legacy.get("decision_id") == request["decision_id"]
                    and legacy["request"]["base_revision"] == request["base_revision"]):
                accepted = recorded_decision(context, legacy, path)
                if accepted is not None and accepted != request["accept"]:
                    raise EngineError("document_decision_conflict", "The preserved decision cannot be reversed.")
                if legacy["phase"] in {"complete", "rejected"}:
                    return _legacy_result(context, legacy, path, replayed=True)
                record = _import_legacy_preview(context, legacy, path, store, app)
                break
    if (record is None or record.get("review", {}).get("adapter") != "native_display"
            or record["result"]["figure_id"] != context["figure_id"]
            or record["result"]["request"]["base_revision"] != request["base_revision"]):
        raise EngineError("document_invalid_decision", "Use the exact decision returned by this native figure.")
    child = _preview_export(app, record)
    if request["accept"] and not record.get("artifact_paths", {}).get("preview.png") and child is None:
        raise EngineError("document_preview_unavailable", "Export the sealed native candidate before accepting it.")
    _check_sources(record["result"]["sources"])
    command = ProjectCommand.from_payload(record["metadata"])
    decided = app.decide(command, decision_id=record["decision_id"], accept=request["accept"])
    if request["accept"] and child is not None:
        _publish_reviewed_exports(require_object(target), decided, child, store, app)
    return _public(context, decided, replayed=record["phase"] in {"complete", "rejected"})

def _verified_native_sha(context: dict[str, Any]) -> str:
    native = Path(context["plot"])
    receipt = next((item for item in context["manifest"].get("last_export", [])
                    if Path(item["document"]) == Path(context["manifest"]["delivery"]) / "editable" / native.name), None)
    if receipt is None or file_sha256(native) != receipt["document_sha256"]:
        raise EngineError("native_export_revision_conflict",
            "Native figure changed after verified publication/export; preserve the current native save and inspect it.",
            action="plot.describe", plot=context["plot"])
    expected: str = receipt["document_sha256"]
    return expected


@native_runtime(repair=True)
def export_native(target: Path) -> dict[str, Any]:
    from sciplot_core.workflow.rheology_tts_suite import _export_saved_suite
    context = require_object(target, repair=True)
    result = _export_saved_suite(Path(context["workspace"]), figure_ids=(context["figure_id"],))
    current = require_object(target)
    spec, _ = selected_spec(current)
    native_sha = _verified_native_sha(current)
    identity = native_identity(context["manifest"]["workspace"], context["figure_id"],
        current["manifest"]["sources"], file_sha256(spec), native_sha)
    exports = _current_exports(current, native_sha)
    return {**result, "kind": "sciplot_plot_result", "version": 1, "status": "complete", **identity,
            "plot": context["plot"], "plot_type": "LegacyPlot", "ready_to_use": bool(exports),
            "scope": "single_figure", "scientific_hash_changed": False, "exports": exports,
            "export_status": "complete" if exports else "unknown"}
