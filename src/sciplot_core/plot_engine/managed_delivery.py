"""Resumable ordered ManagedPlot export snapshots; never a cross-plot edit."""

from pathlib import Path
import json
import re
import shutil
import subprocess
from typing import Any, Protocol
from uuid import uuid4

from sciplot_core.plot_engine.managed_delivery_contract import normalize_request
from sciplot_core.plot_engine.managed_delivery_data import project_data
from sciplot_core.plot_engine.managed_delivery_continuation import delivery_inventory, require_native_seal
from sciplot_core.plot_engine.managed_delivery_publication import inspect_managed_native, portable_native, publish
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.current import require_current
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.storage import digest, load_head, read, write
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot, _assert_snapshot_current
from sciplot_core.studio_core.project_query_paths import canonical_path
from sciplot_core.project_lifecycle.context import external_project_session, exists, prepare_namespace, create_namespace
from sciplot_core.studio_core.source_update_commit import file_inventory

class DeliveryService(Protocol):
    backend: Any


def _save(root: Path, state: dict[str, Any]) -> None:
    state["state_sha256"] = digest({key: value for key, value in state.items() if key != "state_sha256"})
    write(root / "delivery.json", state)


def _selection(service: DeliveryService, item: dict[str, Any], root: Path, out: Path) -> dict[str, Any]:
    plot = canonical_path(Path(item["plot"]))
    head = load_head(plot)
    document = head["document"]
    if document.get("plot_type") != "ManagedPlot":
        raise EngineError("managed_delivery_authority_required", "This delivery entry accepts current ManagedPlots only.")
    if (document["plot_id"], document["revision"]) != (item["plot_id"], item["revision"]):
        raise EngineError("managed_delivery_revision_conflict", "Read each selected plot's current identity and revision.")
    paths = [plot, Path(head["binding"]["output"]),
             *[Path(source["path"]) for source in document["scientific"]["data_sources"]]]
    for selected_path in paths:
        path = canonical_path(selected_path)
        if any(target == path or target.is_relative_to(path) or path.is_relative_to(target) for target in (root, out)):
            raise EngineError("managed_delivery_path_overlap", "Delivery/checkpoint must not overlap selected plots, sources or artifacts.")
    require_current(service.backend, head["binding"])
    return head


def _seal(service: DeliveryService, root: Path, state: dict[str, Any], selection: dict[str, Any], item: dict[str, Any]) -> None:
    out = Path(state["request"]["out"])
    head = _selection(service, selection, root, out)
    cache = Path(selection["plot"]) / "export-cache.json"
    native = Path(head["binding"]["document"])
    if not exists(cache):
        raise EngineError("managed_delivery_cache_missing", "Delivery consumes a sealed current publication. Finish the original plot export explicitly; delivery will not rebuild or overwrite it.")
    record = read(cache)
    exported = record.get("export", {})
    files = record.get("artifact_files", {})
    if str(native) not in files:
        raise EngineError("managed_delivery_native_unsealed", "The export cache lacks the exact original native byte seal.")
    if not files or any(not Path(name).is_file() or file_sha256(Path(name)) != expected for name, expected in files.items()):
        raise EngineError("managed_delivery_export_changed", "A sealed original artifact is missing or changed; it was not regenerated or overwritten.")
    if exported.get("ir_hash") != head["binding"]["ir_hash"]:
        raise EngineError("managed_delivery_cache_stale", "The export cache does not identify this selected revision's exact PlotIR.")
    ir_snapshot = stable_file_snapshot(Path(head["binding"]["ir_path"]), label="Managed delivery audited PlotIR")
    ir = json.loads(ir_snapshot["bytes"])
    document = head["document"]
    if (ir["ir_hash"], ir["scientific_hash"], ir["presentation_hash"]) != (
            head["binding"]["ir_hash"], document["scientific_hash"], document["presentation_hash"]):
        raise EngineError("managed_delivery_cache_stale", "The export cache is not bound to the selected scientific/presentation/export configuration.")
    if exported.get("publication_qa", {}).get("status") != "passed":
        raise EngineError("managed_delivery_qa_unverified", "The sealed export lacks its original passed publication QA.")
    # Packaging does not refresh compiler identity or mutate the original plot.
    # Use the existing scientific/publication owner on these exact saved bytes.
    inspected = inspect_managed_native(head["binding"])
    _assert_snapshot_current(ir_snapshot, label="Managed delivery audited PlotIR")
    native_sha256 = files[str(native)]
    if inspected["document_sha256"] != native_sha256:
        raise EngineError("managed_delivery_native_changed", "The audited native bytes changed during delivery capture.")
    result = {**exported, "publication_qa": inspected.get("publication_qa", {})}
    if result.get("status") != "exported" or result.get("ready_to_use") is not True:
        raise EngineError("managed_delivery_export_pending", "Finish this plot's existing export continuation before delivering.",
                          result=result)
    if result.get("publication_qa", {}).get("status") != "passed":
        raise EngineError("managed_delivery_qa_unverified", "The selected export lacks passed publication QA.")
    head = _selection(service, selection, root, out)
    attempt = root / "attempts" / item["stem"] / uuid4().hex
    item.update(status="preparing", attempt=str(attempt))
    _save(root, state)
    for directory in ("project", "pdf", "tiff", "data/originals"):
        (attempt / directory).mkdir(parents=True)
    sources = []
    for source in head["document"]["scientific"]["data_sources"]:
        path = canonical_path(Path(source["path"]))
        snapshot = stable_file_snapshot(path, label="Managed delivery original source")
        if snapshot["sha256"] != source["sha256"]:
            raise EngineError("managed_delivery_source_changed", "An original source changed during delivery.")
        name = snapshot["sha256"] + path.suffix.lower()
        target = attempt / "data/originals" / name
        if not target.exists():
            target.write_bytes(snapshot["bytes"])
        _assert_snapshot_current(snapshot, label="Managed delivery original source")
        sources.append({"source_id": source["source_id"], "original_name": path.name, "sha256": snapshot["sha256"],
                        "path": "data/originals/" + name})
    plotted_data = project_data(Path(head["binding"]["ir_path"]), attempt, item["stem"],
                                expected={"ir_hash": head["binding"]["ir_hash"], "scientific_hash": document["scientific_hash"],
                                          "presentation_hash": document["presentation_hash"]})
    if plotted_data["ir"]["sha256"] != ir_snapshot["sha256"]:
        raise EngineError("managed_delivery_ir_changed", "The PlotIR changed between native audit and data serialization.")
    _assert_snapshot_current(ir_snapshot, label="Managed delivery audited PlotIR")
    exports = result["exports"]
    for fmt, directory, suffix in (("pdf", "pdf", ".pdf"), ("tiff_300", "tiff", "_300dpi.tiff")):
        matches = [export for export in exports if export.get("format") == fmt]
        if len(matches) != 1:
            raise EngineError("managed_delivery_export_incomplete", "Expected exactly one audited PDF and one TIFF for each selected plot.")
        record = matches[0]
        original = canonical_path(Path(record["path"]))
        if file_sha256(original) != record["sha256"]:
            raise EngineError("managed_delivery_export_changed", "An audited export changed before capture.")
        destination = attempt / directory / (item["stem"] + suffix)
        shutil.copy2(original, destination)
        if file_sha256(destination) != record["sha256"]:
            raise EngineError("managed_delivery_export_changed", "The delivery copy differs from its audited export.")
    native = canonical_path(Path(head["binding"]["document"]))
    portable = portable_native(native, attempt / "project" / (item["stem"] + ".vsz"), attempt / "data/imports" / item["stem"])
    if portable.get("original_sha256") != native_sha256 or file_sha256(native) != native_sha256:
        raise EngineError("managed_delivery_native_changed", "Native Save did not consume the exact freshly audited original bytes.")
    _selection(service, selection, root, out)
    item.update(status="sealed", sources=sources, plotted_data=plotted_data, portable=portable, files=file_inventory(attempt),
                scientific_hash=head["document"]["scientific_hash"], presentation_hash=head["document"]["presentation_hash"],
                export_configuration=head["document"]["presentation"]["export_configuration"],
                audit={"publication_qa": result["publication_qa"], "native_sha256": native_sha256,
                       "ir_hash": head["binding"]["ir_hash"], "revision": selection["revision"]})
    item.pop("error", None)
    _save(root, state)


def _summary(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    complete = state["status"] == "complete"
    return {"kind": "sciplot_managed_delivery_result", "version": 1, "status": state["status"],
            "mode": "native_snapshot", "managed_project_included": False, "ready_to_use": complete,
            "capabilities": {"local_managed_semantic_continuation": True, "portable_managed_project": False,
                             "independent_native_snapshot_editor": complete, "human_managed_editor_provided": False},
            "checkpoint": str(root), "out": state["request"]["out"],
            "items": [{"plot": selection["plot"], "plot_id": selection["plot_id"], "revision": selection["revision"],
                       "label": selection["label"], "status": item["status"],
                       "local_managed_continuation": {"method": "plot.describe", "params": {
                           "plot": selection["plot"], "description": {"scope": "summary"}}},
                       **({"error": item["error"]} if "error" in item else {})}
                      for selection, item in zip(state["request"]["items"], state["items"], strict=True)],
            "delivery": ({"index": str(Path(state["request"]["out"]) / "index.json"),
                          "archive": str(Path(state["request"]["out"]) / "Figures.zip"),
                          "native_launcher": str(Path(state["request"]["out"]) / "Open_in_Veusz.command")} if complete else None),
            "next_step": {"action": "deliver" if complete else "retry_same_request", "method": "plot.deliver"},
            **({"blocker": state["blocker"]} if "blocker" in state else {})}


def deliver(service: DeliveryService, value: Any) -> dict[str, Any]:
    request = normalize_request(value)
    out = Path(request["out"])
    root = canonical_path(out.parent / ".sciplot_deliveries" / digest(str(out)))
    # All keys for one destination share the same record and exclusion lease.
    prepare_namespace(root)
    with external_project_session(root):
        if exists(root / "delivery.json"):
            state = read(root / "delivery.json")
            if (state.get("request") != request or state.get("state_sha256") != digest(
                    {key: value for key, value in state.items() if key != "state_sha256"})):
                raise EngineError("managed_delivery_request_conflict", "Destination already belongs to a different or changed delivery request.")
        else:
            if out.exists() or exists(root):
                raise EngineError("managed_delivery_output_exists", "Delivery and checkpoint targets must be new; existing files were preserved.")
            # Validate the closed selection/locations before reserving output.
            for selection in request["items"]:
                _selection(service, selection, root, out)
            create_namespace(root)
            state = {"kind": "sciplot_managed_delivery_state", "version": 1, "request": request, "status": "running",
                     "items": [{"status": "pending", "stem": f"{index:03d}_" + (re.sub(r"[^A-Za-z0-9_-]+", "_", item["label"]).strip("_")[:64] or "Figure")}
                               for index, item in enumerate(request["items"], 1)]}
            _save(root, state)
        try:
            for selection, item in zip(request["items"], state["items"], strict=True):
                head = _selection(service, selection, root, out)
                if item["status"] == "sealed":
                    require_native_seal(head, item["audit"]["native_sha256"])
            if out.exists():
                expected = state.get("delivery_files") or state.get("publication_candidate", {}).get("files")
                if not expected or delivery_inventory(out) != expected:
                    raise EngineError("managed_delivery_external_edit", "The destination contains changed or unowned files; all were preserved.")
                state.update(status="complete", delivery_files=expected)
            else:
                if state["status"] == "complete":
                    raise EngineError("managed_delivery_missing_output", "A completed delivery was removed; choose a new destination, never recreate over uncertain work.")
                for selection, item in zip(request["items"], state["items"], strict=True):
                    try:
                        if item["status"] == "conflict":
                            raise EngineError("managed_delivery_staging_changed", "Previously edited staging remains preserved; select a new delivery destination.")
                        if item["status"] == "sealed":
                            if file_inventory(Path(item["attempt"])) != item["files"]:
                                raise EngineError("managed_delivery_staging_changed", "A sealed item was externally edited.")
                        else:
                            _seal(service, root, state, selection, item)
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                        reason = getattr(exc, "reason_code", "managed_delivery_item_failed")
                        item.update(status="conflict" if reason == "managed_delivery_staging_changed" else "failed",
                                    error={"reason_code": reason, "message": str(exc)})
                        _save(root, state)
                if any(item["status"] != "sealed" for item in state["items"]):
                    state["status"] = "partial"
                else:
                    def validate() -> None:
                        for selection, item in zip(request["items"], state["items"], strict=True):
                            head = _selection(service, selection, root, out)
                            require_native_seal(head, item["audit"]["native_sha256"])

                    state["delivery_files"] = publish(root, state, checkpoint=lambda: _save(root, state), validate=validate)
                    state["status"] = "complete"
            state.pop("blocker", None)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            state.update(status="blocked", blocker={"reason_code": getattr(exc, "reason_code", "managed_delivery_failed"), "message": str(exc)})
        _save(root, state)
        return _summary(root, state)
