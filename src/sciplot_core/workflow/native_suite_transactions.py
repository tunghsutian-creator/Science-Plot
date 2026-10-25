"""Native object commands prepare privately and publish one project generation."""
from __future__ import annotations

from collections.abc import Callable
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
    command_for, command_key, json_bytes, mutation, open_store, saved_command, suite_paths,
)
from sciplot_core.workflow.native_suite_objects import capture_object, descriptor, require_object, native_identity, selected_spec
from sciplot_core.workflow.native_suite_storage import result_for
from sciplot_core.workflow.native_suite_runtime import native_runtime, suite_runtime


NativeHandler = Callable[[Path, dict[str, Any]], dict[str, Any]]


def _admit_wire_before_runtime(operation: str) -> Callable[[NativeHandler], NativeHandler]:
    from functools import wraps
    def decorate(function: NativeHandler) -> NativeHandler:
        @wraps(function)
        def wrapped(target: Path, request: dict[str, Any]) -> dict[str, Any]:
            target = Path(target)
            value = ({"patch": validate_patch, "resume": validate_resume, "decide": validate_decide}[operation])(request)
            from sciplot_core.workflow.native_suite_runtime import read_bound_store
            store = read_bound_store(target)
            if store is not None:
                manifest = json.loads((store.root / "suite.json").read_bytes())
                selected = ([item["id"] for item in manifest["documents"] if item["id"] == target.stem]
                            if target.suffix.lower() == ".vsz" else [item["id"] for item in manifest["documents"]])
                if len(selected) != 1:
                    raise EngineError("native_object_figure_required", "Select one exact existing native figure.")
                identifier = selected[0]
                app = ProjectCommands(store)
                if operation == "decide":
                    if set(value) != {"decision_id", "base_revision", "accept"}:
                        raise EngineError("document_invalid_decision", "Native display decisions require boolean accept.")
                    record = app.query_decision(value["decision_id"])
                    if record is None:
                        aliases = [item for item in app.commands() if item.get("review", {}).get("legacy_decision_id") == value["decision_id"]]
                        if len(aliases) > 1:
                            raise EngineError("document_invalid_decision", "The decision identity is ambiguous.")
                        record = aliases[0] if aliases else None
                    if record is not None and (record.get("review", {}).get("adapter") != "native_display"
                            or record["result"].get("figure_id") != identifier
                            or record["result"].get("request", {}).get("base_revision") != value["base_revision"]):
                        raise EngineError("document_invalid_decision", "Use the exact saved decision for this selected figure.")
                else:
                    identity = native_identity(manifest["workspace"], identifier, [], "", "")["plot_id"]
                    if value["plot_id"] != identity:
                        raise EngineError("document_identity_conflict", "The request belongs to another native figure.")
                    record = app.query(command_key("native_patch", {"figure": identifier, "key": value["idempotency_key"]}))
                    if record is not None:
                        saved = record["metadata"]["request"]
                        saved_request = saved.get("request", {})
                        matches = (saved_request == value if operation == "patch" else
                                   all(saved_request.get(key) == item for key, item in value.items()))
                        if saved.get("adapter") != "native_display" or saved.get("figure_id") != identifier or not matches:
                            raise EngineError("document_idempotency_conflict", "Use the command's exact original identity.")
                # A new/unknown operation cannot repair another pending command.
                # Legacy record discovery proceeds only while all views are current.
                if record is None:
                    store.snapshot()
            return function(target, value)
        return wrapped
    return decorate

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


def _current_exports(context: dict[str, Any], native_sha: str) -> list[dict[str, Any]]:
    from sciplot_core.workflow.rheology_tts_suite import _figure_folder

    manifest, identifier = context["manifest"], context["figure_id"]
    receipts = manifest.get("last_export", manifest["native_result"]["figures"])
    receipt = next((item for item in receipts if Path(item["document"]).stem == identifier), None)
    if receipt is None or receipt["document_sha256"] != native_sha:
        return []
    origin_delivery = Path(manifest.get("delivery", context["delivery"]))
    origin_native = origin_delivery / "editable" / (identifier + ".vsz")
    origin_initial = Path(manifest.get("workspace", context["workspace"])) / "initial_render"
    if Path(receipt["document"]) not in {origin_native, origin_initial / origin_native.name}:
        return []
    exports: list[dict[str, Any]] = deepcopy(receipt["exports"])
    folder = _figure_folder(Path(context["delivery"]), identifier)
    origin_folder = _figure_folder(origin_delivery, identifier)
    suffixes = {"pdf": ".pdf", "tiff_300": "_300dpi.tiff", "png_300": "_300dpi.png"}
    document = context["document"]
    if (document["sha256"] != native_sha or len(document["exports"]) != 3
            or {Path(name) for name in document["exports"]} != {origin_folder / (identifier + suffix) for suffix in suffixes.values()}):
        return []
    if len(exports) != 3 or {item["format"] for item in exports} != set(suffixes):
        return []
    for item in exports:
        name = identifier + suffixes[item["format"]]
        if Path(item["path"]) not in {origin_folder / name, origin_initial / name}:
            return []
        artifact = folder / name
        if (not artifact.is_file() or artifact.is_symlink() or file_sha256(artifact) != item["sha256"]
                or ("exists" in item and item["exists"] is not True)
                or ("size_bytes" in item and item["size_bytes"] != artifact.stat().st_size)):
            return []
        item["path"] = str(artifact)
    return exports


def _sources_current(sources: list[dict[str, Any]]) -> bool:
    from sciplot_core.workflow.rheology_tts_suite import _check_sources
    try:
        _check_sources(sources)
    except (ValueError, OSError):
        return False
    return True


def _legacy_result(context: dict[str, Any], record: dict[str, Any], path: Path, *, replayed: bool = False) -> dict[str, Any]:
    from sciplot_core.workflow.rheology_tts_suite import _active_receipts
    result = result_for(record, path, replayed=replayed)
    if record["phase"] == "complete":
        receipts = _active_receipts(context["manifest"])
        receipt = next((item for item in receipts if item["id"] == context["figure_id"]), None)
        spec = Path(receipt["spec_path"]) if receipt else None
        current = (context["manifest"]["sources"] == record["sources"]
            and file_sha256(Path(context["plot"])) == record["presentation_hash"]
            and spec is not None and spec.is_file() and not spec.is_symlink()
            and file_sha256(spec) == record["spec_sha256"]
            and _sources_current(record["sources"]))
        exports = _current_exports(context, record["presentation_hash"]) if current else []
        result["exports"] = exports
        result["current_state_matches"] = current
        result["ready_to_use"] = bool(exports)
        if not exports:
            result["export_status"] = "pending" if current else "unknown"
            result["next_step"] = {"action": "plot.export" if current else "plot.describe", "plot": context["plot"]}
    return result



def _application(context: dict[str, Any]) -> tuple[FileProjectStore, ProjectCommands]:
    store = open_store(Path(context["workspace"]), Path(context["delivery"]))
    return store, ProjectCommands(store)


def _request(context: dict[str, Any], request: dict[str, Any]) -> dict[str, Any]:
    return {"adapter": "native_display", "figure_id": context["figure_id"], "request": request}


def _key(context: dict[str, Any], request: dict[str, Any]) -> str:
    return command_key("native_patch", {"figure": context["figure_id"], "key": request["idempotency_key"]})


def _public(context: dict[str, Any], record: dict[str, Any], *, replayed: bool = False) -> dict[str, Any]:
    with suite_runtime(Path(context["workspace"])):
        return _public_current(context, record, replayed=replayed)


def _public_current(context: dict[str, Any], record: dict[str, Any], *, replayed: bool = False) -> dict[str, Any]:
    saved = deepcopy(record["result"])
    saved["plot"] = context["plot"]
    phase = record["phase"]
    if not saved:
        original = record["metadata"]["request"]["request"]
        spec, _figure = selected_spec(context)
        saved = {"plot": context["plot"], "figure_id": context["figure_id"], "request": original,
            "scientific_hash": canonical_json_sha256(json.loads(spec.read_bytes())),
            "before_native_sha256": file_sha256(Path(context["plot"])), "diff": []}

    saved["phase"] = phase
    saved["decision_id"] = record.get("decision_id")
    paths = dict(record.get("artifact_paths", {}))
    if not paths.get("preview.png") and phase == "needs_review":
        _store, app = _application(context)
        exported = _preview_export(app, record)
        if exported:
            paths["preview.png"] = exported["artifact_paths"]["preview.png"]
    saved["preview_png"] = paths.get("preview.png", "")
    saved["preview"] = paths.get("preview.json", "")
    if phase == "complete":
        saved.update(accepted=True)
    elif phase == "rejected":
        saved.update(accepted=False)
    evidence = Path(saved["preview"]) if saved["preview"] else Path(context["workspace"]) / ".sciplot_store/head.json"
    result = result_for(saved, evidence, replayed=replayed)
    result["generation"] = record["generation"]
    if phase == "reserved":
        result["next_step"] = {"action": "plot.patch", "plot": context["plot"], "request": saved["request"]}
    if phase == "complete":
        current = require_object(Path(context["plot"]))
        spec, _ = selected_spec(current)
        same = (file_sha256(Path(current["plot"])) == saved["presentation_hash"]
                and file_sha256(spec) == saved["spec_sha256"]
                and current["manifest"]["sources"] == saved["sources"]
                and _sources_current(saved["sources"]))
        exports = _current_exports(current, saved["presentation_hash"]) if same else []
        result.update(current_state_matches=same, exports=exports, ready_to_use=bool(exports),
                      export_status="complete" if exports else "pending" if same else "unknown")
        if not exports:
            result["next_step"] = {"action": "plot.export" if same else "plot.describe", "plot": context["plot"]}
    elif phase == "needs_review" and not paths.get("preview.png"):
        result.update(status="blocked", ready_to_use=False,
                      error=saved.get("error", {"reason_code": "native_preview_export_pending"}),
                      next_step={"action": "plot.resume", "plot": context["plot"],
                                 "request": {key: saved["request"][key] for key in ("plot_id", "base_revision", "idempotency_key")}})
    return result


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
    from sciplot_core.workflow.rheology_tts_suite import _check_sources

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
        from sciplot_core.workflow.rheology_tts_suite import _active_receipts
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


def _preview_export(app: ProjectCommands, parent: dict[str, Any]) -> dict[str, Any] | None:
    records = [item for item in app.commands()
               if item.get("metadata", {}).get("request", {}).get("adapter") == "native_preview_export"
               and item["metadata"]["request"].get("parent") == parent["command_digest"]
               and item["phase"] == "complete"]
    return records[-1] if records else None


def _resume_preview_export(context: dict[str, Any], parent: dict[str, Any],
                           store: FileProjectStore, app: ProjectCommands) -> None:
    from sciplot_core.rheology_tts_render import export_tts_document
    from sciplot_core.workflow.rheology_tts_suite import _check_sources
    if _preview_export(app, parent):
        return
    attempts = [item for item in app.commands()
                if item.get("metadata", {}).get("request", {}).get("adapter") == "native_preview_export"
                and item["metadata"]["request"].get("parent") == parent["command_digest"]]
    request = {"adapter": "native_preview_export", "parent": parent["command_digest"], "attempt": len(attempts)}
    reads, _writes = suite_paths(Path(context["workspace"]), context["manifest"], (context["figure_id"],))
    command = command_for(store, "native_export", command_key("preview_export", request),
                          request=request, reads=reads, writes=[], figure_id=context["figure_id"])
    with tempfile.TemporaryDirectory(prefix="sciplot-native-preview-export-") as temporary:
        directory = Path(temporary).resolve()
        def prepare() -> ProjectMutation:
            candidate = directory / Path(context["plot"]).name
            candidate.write_bytes(Path(parent["artifact_paths"]["native.vsz"]).read_bytes())
            if file_sha256(candidate) != parent["result"]["presentation_hash"]:
                raise ValueError("Frozen native candidate changed.")
            _spec, figure = selected_spec(context)
            exported = export_tts_document(candidate, directory / "exports" / context["figure_id"], figure)
            if exported["document_sha256"] != parent["result"]["presentation_hash"]:
                raise ValueError("Preview export did not use the frozen native candidate.")
            artifacts = {item["format"]: Path(item["path"]).read_bytes() for item in exported["exports"]}
            artifacts["preview.png"] = artifacts["png_300"]
            # Paths are attachment keys. Private temporary paths never become
            # public review references or another persistent operation record.
            for item in exported["exports"]:
                item["path"] = item["format"]
            exported["document"] = "native.vsz"
            exported["native_audit"]["document"] = "native.vsz"
            exported["native_audit_path"] = "native-audit.json"
            _check_sources(context["manifest"]["sources"])
            return mutation(store, {}, {"export": exported}, sources=context["manifest"]["sources"], artifacts=artifacts)
        app.execute(command, prepare)


def _publish_reviewed_exports(context: dict[str, Any], parent: dict[str, Any], child: dict[str, Any],
                             store: FileProjectStore, app: ProjectCommands) -> dict[str, Any]:
    from sciplot_core.workflow.rheology_tts_suite import _check_sources, _figure_folder
    request = {"adapter": "native_reviewed_export_publication", "parent": parent["command_digest"],
               "export": child["command_digest"]}
    key = command_key("reviewed_export", request)
    command = saved_command(app, key, request)
    reads, writes = suite_paths(Path(context["workspace"]), context["manifest"], (context["figure_id"],))
    if command is None:
        command = command_for(store, "native_export", key, request=request, reads=reads, writes=writes,
                              figure_id=context["figure_id"])
    def prepare() -> ProjectMutation:
        current = require_object(Path(context["plot"]))
        if file_sha256(Path(current["plot"])) != parent["result"]["presentation_hash"]:
            raise ValueError("Reviewed native bytes are no longer current.")
        manifest = deepcopy(current["manifest"])
        receipt = deepcopy(child["result"]["export"])
        folder = _figure_folder(Path(context["delivery"]), context["figure_id"])
        updates = {}
        suffixes = {"pdf": ".pdf", "tiff_300": "_300dpi.tiff", "png_300": "_300dpi.png"}
        for item in receipt["exports"]:
            target = folder / (context["figure_id"] + suffixes[item["format"]])
            updates[target] = Path(child["artifact_paths"][item["format"]]).read_bytes()
            item["path"] = str(target)
        receipt["document"] = context["plot"]
        receipt["export_dir"] = str(folder)
        receipt["native_audit"]["document"] = context["plot"]
        audit_path = folder / (context["figure_id"] + ".native-audit.json")
        receipt["native_audit_path"] = str(audit_path)
        updates[audit_path] = json_bytes(receipt["native_audit"])
        existing = {Path(item["document"]).stem: item for item in manifest.get("last_export", manifest["native_result"]["figures"])}
        existing[context["figure_id"]] = receipt
        manifest["last_export"] = [existing[item["id"]] for item in manifest["documents"]]
        updates[Path(context["workspace"]) / "suite.json"] = json_bytes(manifest)
        updates[Path(context["delivery"]) / "data/delivery_manifest.json"] = json_bytes(manifest)
        _check_sources(manifest["sources"])
        return mutation(store, updates, {"status": "ready", "exports": receipt["exports"]}, sources=manifest["sources"])
    return app.execute(command, prepare)


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
    from sciplot_core.workflow.rheology_tts_suite import _check_sources
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
