"""Project saved native outcomes and current export readiness without executing native work."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any
from sciplot_core.foundation.file_hashing import file_sha256
from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.workflow.native_suite_runtime import suite_runtime
from sciplot_core.workflow.native_suite_objects import require_object, selected_spec
from sciplot_core.workflow.native_suite_storage import result_for
from sciplot_core.workflow.native_suite_command_records import _application, _preview_export

def _current_exports(context: dict[str, Any], native_sha: str) -> list[dict[str, Any]]:
    from sciplot_core.workflow.rheology_tts_saved_state import _figure_folder

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
    from sciplot_core.workflow.rheology_tts_saved_state import _check_sources
    try:
        _check_sources(sources)
    except (ValueError, OSError):
        return False
    return True


def _legacy_result(context: dict[str, Any], record: dict[str, Any], path: Path, *, replayed: bool = False) -> dict[str, Any]:
    from sciplot_core.workflow.rheology_tts_saved_state import _active_receipts
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
