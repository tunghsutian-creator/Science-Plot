"""Resumable ordered ManagedPlot export snapshots; never a cross-plot edit."""

from pathlib import Path
import re
import subprocess
from typing import Any, Protocol
from uuid import uuid4

from sciplot_core.delivery import native_snapshot
from sciplot_core.plot_engine.managed_delivery_contract import normalize_request
from sciplot_core.plot_engine.managed_delivery_data import capture_plot_data, project_data
from sciplot_core.plot_engine.managed_delivery_continuation import delivery_inventory, require_native_seal
from sciplot_core.plot_engine.managed_delivery_publication import cached_native_audit, inspect_managed_native, publish
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.plot_engine.current import require_current
from sciplot_core.plot_engine.errors import EngineError
from sciplot_core.plot_engine.storage import digest, load_head, read, write
from sciplot_core.source_coverage.file_snapshots import _assert_snapshot_current
from sciplot_core.plot_engine.managed_delivery_sources import stage_originals, require_originals, resolve_original
from sciplot_core.foundation.canonical_paths import canonical_path
from sciplot_core.project_lifecycle.context import active, external_project_session, exists, prepare_namespace, create_namespace, project_query
from sciplot_core.studio_core.source_update_files import file_inventory

class DeliveryService(Protocol):
    backend: Any


def _save(root: Path, state: dict[str, Any]) -> None:
    state["state_sha256"] = digest({key: value for key, value in state.items() if key != "state_sha256"})
    write(root / "delivery.json", state)


def _selected_head(item: dict[str, Any], *targets: Path) -> dict[str, Any]:
    plot = Path(item["plot"])  # The closed delivery request already canonicalized this exact handle.
    head = load_head(plot)
    document = head["document"]
    if document.get("plot_type") != "ManagedPlot":
        raise EngineError("managed_delivery_authority_required", "This delivery entry accepts current ManagedPlots only.")
    if (document["plot_id"], document["revision"]) != (item["plot_id"], item["revision"]):
        raise EngineError("managed_delivery_revision_conflict", "This exact selection has advanced. Read its current revision and use a new destination.",
                          action="plot.describe", plot=str(plot), new_destination_required=True)
    paths = [plot, Path(head["binding"]["output"])]
    for source in document["scientific"]["data_sources"]:
        literal = Path(source["path"])
        paths.extend((literal, resolve_original(source)))
    for selected_path in paths:
        path = canonical_path(selected_path)
        if any(target == path or target.is_relative_to(path) or path.is_relative_to(target) for target in targets):
            raise EngineError("managed_delivery_path_overlap", "Delivery/checkpoint must not overlap selected plots, sources or artifacts.")
    return head


def _selection(service: DeliveryService, item: dict[str, Any], *targets: Path) -> dict[str, Any]:
    with project_query(Path(item["plot"])):
        head = _selected_head(item, *targets)
        require_current(service.backend, head["binding"])
        pending = active(Path(item["plot"]))
        if pending and pending["phase"] not in {"complete", "rejected"}:
            raise EngineError("managed_delivery_review_pending", "Resolve the current plot transaction before packaging its saved export.",
                              action="resolve_pending_plot_transaction", plot=item["plot"], phase=pending["phase"])
        return head


def _failure(exc: Exception, code: str, selection: dict[str, Any] | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {"reason_code": getattr(exc, "reason_code", code), "message": str(exc)}
    if repair := getattr(exc, "repair", None):
        result["repair"] = repair
    if selection is not None:
        result["selection"] = selection
        if result["reason_code"] in {"document_inputs_changed", "document_state_missing", "managed_delivery_cache_missing",
                "managed_delivery_cache_stale", "managed_delivery_native_unsealed", "managed_delivery_export_changed",
                "managed_delivery_export_pending", "managed_delivery_qa_unverified", "managed_delivery_export_incomplete",
                "managed_delivery_original_native_changed", "managed_delivery_native_changed"}:
            result["export_command"] = ["sciplot", "plot", "export", selection["plot"], "--json"]
    return result


def _destination(request: dict[str, Any]) -> tuple[Path, Path]:
    out = Path(request["out"])
    return canonical_path(out.parent / ".sciplot_deliveries" / digest(str(out))), out


def _load_request(root: Path, request: dict[str, Any]) -> dict[str, Any]:
    state = read(root / "delivery.json")
    if (state.get("request") != request or state.get("state_sha256") != digest(
            {key: value for key, value in state.items() if key != "state_sha256"})):
        raise EngineError("managed_delivery_request_conflict", "Destination already belongs to a different or changed delivery request.")
    return state


def require_paper_location(request: dict[str, Any], paper_dir: Path) -> None:
    """Protect actual selected inputs from the paper wrapper's separate receipt."""
    root, out = _destination(request)
    if any(paper_dir == path or paper_dir.is_relative_to(path) or path.is_relative_to(paper_dir)
           for path in (root, out)):
        raise EngineError("managed_delivery_path_overlap", "Keep the paper checkpoint outside the delivery and its checkpoint.")
    for selection in request["items"]:
        with project_query(Path(selection["plot"])):
            _selected_head(selection, paper_dir)


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
    ir_path = head["binding"]["ir_path"]
    if not files or any(not Path(name).is_file() or file_sha256(Path(name)) != expected
                        for name, expected in files.items() if name != ir_path):
        raise EngineError("managed_delivery_export_changed", "A sealed original artifact is missing or changed; it was not regenerated or overwritten.")
    if exported.get("ir_hash") != head["binding"]["ir_hash"]:
        raise EngineError("managed_delivery_cache_stale", "The export cache does not identify this selected revision's exact PlotIR.")
    document = head["document"]
    plot_data = capture_plot_data(Path(ir_path), sha256=files.get(ir_path), expected={
        "ir_hash": head["binding"]["ir_hash"], "scientific_hash": document["scientific_hash"],
        "presentation_hash": document["presentation_hash"]})
    if exported.get("publication_qa", {}).get("status") != "passed":
        raise EngineError("managed_delivery_qa_unverified", "The sealed export lacks its original passed publication QA.")
    # Packaging does not refresh compiler identity or mutate the original plot.
    # Use the existing scientific/publication owner on these exact saved bytes.
    native_sha256 = files[str(native)]
    inspected = cached_native_audit(record, head, native_sha256, plot_data.snapshot["sha256"])
    if inspected is None:
        inspected = inspect_managed_native(head["binding"])
    if inspected["document_sha256"] != native_sha256:
        raise EngineError("managed_delivery_native_changed", "The audited native bytes changed during delivery capture.")
    result = {**exported, "publication_qa": inspected.get("publication_qa", {})}
    if result.get("status") != "exported" or result.get("ready_to_use") is not True:
        raise EngineError("managed_delivery_export_pending", "Finish this plot's existing export continuation before delivering.",
                          result=result)
    if result.get("publication_qa", {}).get("status") != "passed":
        raise EngineError("managed_delivery_qa_unverified", "The selected export lacks passed publication QA.")
    attempt = root / "attempts" / item["stem"] / uuid4().hex
    item.update(status="preparing", attempt=str(attempt))
    _save(root, state)
    for directory in ("project", "pdf", "tiff"):
        (attempt / directory).mkdir(parents=True)
    with project_query(Path(selection["plot"])):
        current = _selection(service, selection, root, out)
        sources = stage_originals(root, current["document"]["scientific"]["data_sources"])
    plotted_data = project_data(plot_data, attempt, item["stem"])
    exports = result["exports"]
    for fmt, directory, suffix in (("pdf", "pdf", ".pdf"), ("tiff_300", "tiff", "_300dpi.tiff")):
        matches = [export for export in exports if export.get("format") == fmt]
        if len(matches) != 1:
            raise EngineError("managed_delivery_export_incomplete", "Expected exactly one audited PDF and one TIFF for each selected plot.")
        record = matches[0]
        if files.get(record["path"]) != record["sha256"]:
            raise EngineError("managed_delivery_export_changed", "An audited export does not belong to this revision's sealed artifacts.")
        destination = attempt / directory / (item["stem"] + suffix)
        try:
            native_snapshot.copy_sealed_file(Path(record["path"]), destination, record["sha256"])
        except native_snapshot.SnapshotSealChanged as exc:
            raise EngineError("managed_delivery_export_changed", str(exc)) from exc
    native = canonical_path(Path(head["binding"]["document"]))
    try:
        portable = native_snapshot.capture_native(
            native, attempt / "project" / (item["stem"] + ".vsz"), attempt / "data/imports" / item["stem"],
            original_sha256=native_sha256, selected_imports={})
    except native_snapshot.SnapshotSealChanged as exc:
        raise EngineError("managed_delivery_native_changed", str(exc)) from exc
    except native_snapshot.NativeSnapshotError as exc:
        raise EngineError("managed_delivery_native_failed", str(exc)) from exc
    _assert_snapshot_current(plot_data.snapshot, label="Managed delivery audited PlotIR",
                             expected_sha256=plot_data.snapshot["sha256"])
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
                             "independent_native_snapshot_editor": False, "human_managed_editor_provided": False},
            "checkpoint": str(root), "out": state["request"]["out"],
            "items": [{"plot": selection["plot"], "plot_id": selection["plot_id"], "revision": selection["revision"],
                       "label": selection["label"], "status": item["status"],
                       "local_managed_continuation": {"method": "plot.describe", "params": {
                           "plot": selection["plot"], "description": {"scope": "summary"}}},
                       **({"error": item["error"]} if "error" in item else {})}
                      for selection, item in zip(state["request"]["items"], state["items"], strict=True)],
            "delivery": ({"index": str(Path(state["request"]["out"]) / "index.json"),
                          "archive": str(Path(state["request"]["out"]) / "Figures.zip")} if complete else None),
            "next_step": {"action": "deliver" if complete else "retry_same_request", "method": "plot.deliver"},
            **({"blocker": state["blocker"]} if "blocker" in state else {})}


def inspect(service: DeliveryService, request: dict[str, Any]) -> dict[str, Any]:
    """Observe the existing owner receipt and seals; never acquire a writer lease."""
    from sciplot_core.plot_engine.export_status import current_export

    root, out = _destination(request)
    if exists(root / "delivery.json"):
        state = _load_request(root, request)
    else:
        state = {"status": "pending", "request": request,
                 "items": [{"status": "pending"} for _ in request["items"]]}
    summary = _summary(root, state)
    summary.update(recorded_status=state["status"] if state["status"] != "pending" else None, readiness_evaluated=True)
    for selection, item, row in zip(request["items"], state["items"], summary["items"], strict=True):
        try:
            with project_query(Path(selection["plot"])):
                head = _selection(service, selection, root, out)
                row["original_publication"] = current_export(Path(selection["plot"]), head, eligible=True)
                if item["status"] == "sealed":
                    require_native_seal(head, item["audit"]["native_sha256"])
                    if state["status"] != "complete" and not out.exists():
                        _require_sealed_attempt(root, item)
        except (OSError, ValueError, RuntimeError) as exc:
            row.update(status="blocked", error=_failure(exc, "managed_delivery_currentness_failed", selection))
            summary.update(status="blocked", ready_to_use=False)
    if state["status"] == "complete" or out.exists():
        try:
            _require_delivery_files(out, state)
        except (OSError, ValueError, RuntimeError) as exc:
            summary.update(status="blocked", ready_to_use=False, blocker=_failure(exc, "managed_delivery_currentness_failed"))
    if summary["status"] != "complete":
        summary["delivery"] = None
        summary["next_step"] = {"action": "retry_same_request", "method": "plot.deliver"}
    return summary


def _require_sealed_attempt(root: Path, item: dict[str, Any]) -> None:
    try:
        native_snapshot.require_inventory(Path(item["attempt"]), item["files"])
        require_originals(root, item)
    except native_snapshot.SnapshotSealChanged as exc:
        raise EngineError("managed_delivery_staging_changed", str(exc)) from exc


def _require_delivery_files(out: Path, state: dict[str, Any]) -> dict[str, str]:
    recorded = state.get("delivery_files")
    candidate = state.get("publication_candidate") or {}
    expected = recorded or candidate.get("files", {})
    if not out.exists() and state["status"] == "complete":
        raise EngineError("managed_delivery_missing_output", "A completed delivery was removed; choose a new destination, never recreate over uncertain work.")
    if not native_snapshot.installed_snapshot_matches(
            out, expected, pending_candidate=None if recorded or not candidate else Path(candidate["path"]),
            inventory=delivery_inventory):
        raise EngineError("managed_delivery_external_edit", "The destination contains changed or unowned files; all were preserved.")
    return dict(expected)


def deliver(service: DeliveryService, value: Any) -> dict[str, Any]:
    request = normalize_request(value)
    root, out = _destination(request)
    if not exists(root / "delivery.json"):
        from sciplot_core.foundation.research_destination import require_data_destination
        require_data_destination(root)
        require_data_destination(out)
    # All keys for one destination share the same record and exclusion lease.
    prepare_namespace(root)
    with external_project_session(root):
        if exists(root / "delivery.json"):
            state = _load_request(root, request)
        else:
            if out.exists() or exists(root):
                raise EngineError("managed_delivery_output_exists", "Delivery and checkpoint targets must be new; existing files were preserved.")
            # Validate the closed selection/locations before reserving output.
            for selection in request["items"]:
                try:
                    _selection(service, selection, root, out)
                except EngineError as exc:
                    exc.repair["selection"] = selection
                    raise
            create_namespace(root)
            state = {"kind": "sciplot_managed_delivery_state", "version": 1, "request": request, "status": "running",
                     "items": [{"status": "pending", "stem": f"{index:03d}_" + (re.sub(r"[^A-Za-z0-9_-]+", "_", item["label"]).strip("_")[:64] or "Figure")}
                               for index, item in enumerate(request["items"], 1)]}
            _save(root, state)
        selected_failure: dict[str, Any] | None = None
        try:
            for selection, item in zip(request["items"], state["items"], strict=True):
                if item["status"] == "sealed":
                    selected_failure = selection
                    head = _selection(service, selection, root, out)
                    require_native_seal(head, item["audit"]["native_sha256"])
            selected_failure = None
            if out.exists() or "delivery_files" in state:
                state.update(status="complete", delivery_files=_require_delivery_files(out, state))
            else:
                for selection, item in zip(request["items"], state["items"], strict=True):
                    try:
                        if item["status"] == "conflict":
                            raise EngineError("managed_delivery_staging_changed", "Previously edited staging remains preserved; select a new delivery destination.")
                        if item["status"] == "sealed":
                            _require_sealed_attempt(root, item)
                        else:
                            _seal(service, root, state, selection, item)
                    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                        reason = getattr(exc, "reason_code", "managed_delivery_item_failed")
                        item.update(status="conflict" if reason == "managed_delivery_staging_changed" else "failed",
                                    error=_failure(exc, "managed_delivery_item_failed", selection))
                        _save(root, state)
                if any(item["status"] != "sealed" for item in state["items"]):
                    state["status"] = "partial"
                else:
                    def validate() -> None:
                        nonlocal selected_failure
                        for selection, item in zip(request["items"], state["items"], strict=True):
                            selected_failure = selection
                            head = _selection(service, selection, root, out)
                            require_native_seal(head, item["audit"]["native_sha256"])
                        selected_failure = None

                    state["delivery_files"] = publish(root, state, checkpoint=lambda: _save(root, state), validate=validate)
                    state["status"] = "complete"
            state.pop("blocker", None)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            state.update(status="blocked", blocker=_failure(exc, "managed_delivery_failed", selected_failure))
        _save(root, state)
        return _summary(root, state)
