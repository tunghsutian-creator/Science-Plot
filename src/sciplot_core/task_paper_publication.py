"""Capture current, already audited ordinary exports without rendering them."""

from pathlib import Path
import json
from typing import Any

from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot, _assert_snapshot_current
from sciplot_core.studio_core.project_query_evidence import latest_run, publication_indicators
from sciplot_core.studio_core.project_query_paths import project_snapshot, canonical_path
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.task_contract import TaskControlError


def capture_publication(selection: dict[str, Any]) -> dict[str, Any]:
    project = Path(selection["project"])
    request, _, figures = project_snapshot(project)
    manifest_path, _, error = latest_run(project)
    if manifest_path is None or error:
        raise TaskControlError("paper_publication_unsealed", "The original publication receipt is unavailable or invalid.")
    snapshot = stable_file_snapshot(manifest_path, label="paper sealed publication")
    manifest = json.loads(snapshot["bytes"])
    indicators = publication_indicators(project, request, figures, {"current": True})
    if indicators["qa"]["current"] is not True or manifest.get("qa", {}).get("status") != "passed":
        raise TaskControlError("paper_publication_unsealed", "The current saved figure has no complete current sealed publication. Finish its original export explicitly; paper packaging will not render or export it.")
    if latest_run(project)[0] != manifest_path:
        raise TaskControlError("paper_publication_changed", "The latest publication changed during selection.")
    run = manifest_path.parent
    document = str(run / Path(selection["document"]).relative_to(project))
    if manifest["veusz_document_hashes"].get(document) != selection["version"]["document_sha256"]:
        raise TaskControlError("paper_publication_changed", "The original publication does not bind the exact selected native bytes.")
    exports = []
    for fmt in ("pdf", "tiff_300"):
        matches = [record for record in manifest["result"]["exports"]
                   if record.get("document") == document and record.get("format") == fmt]
        if len(matches) != 1:
            raise TaskControlError("paper_publication_unsealed", "Exactly one sealed PDF and TIFF is required for the selected figure.")
        exports.append({key: matches[0][key] for key in ("format", "path", "sha256")})
    files = file_inventory(run)
    _assert_snapshot_current(snapshot, label="paper sealed publication")
    return {"manifest": str(manifest_path), "manifest_sha256": snapshot["sha256"], "files": files,
            "exports": exports, "qa": {"status": "passed", "scope": "existing_current_sealed_publication",
                                       "evidence": str(manifest_path)}}


def assert_publication_current(publication: dict[str, Any], selection: dict[str, Any]) -> None:
    manifest = canonical_path(Path(publication["manifest"]))
    if file_inventory(manifest.parent) != publication["files"]:
        raise TaskControlError("paper_publication_changed", "The sealed publication inventory changed; no artifact was regenerated or overwritten.")
    fresh = capture_publication(selection)
    if fresh != publication:
        raise TaskControlError("paper_publication_changed", "The selected publication receipt changed. Preserve it and start a new ordered selection.")
