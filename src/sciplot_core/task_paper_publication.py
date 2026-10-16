"""Capture current, already audited ordinary exports without rendering them."""

from pathlib import Path
import json
from typing import Any

from sciplot_core.automation_states import RULE_REPAIR_STATE
from sciplot_core.publish_state import build_publish_state
from sciplot_core.source_coverage.file_snapshots import stable_file_snapshot, _assert_snapshot_current
from sciplot_core.studio_core.project_query_evidence import latest_run, publication_indicators
from sciplot_core.studio_core.project_query_paths import project_snapshot, canonical_path
from sciplot_core.studio_core.rule_readiness import resolve_studio_rule_publication_readiness
from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.task_contract import TaskControlError


def _finished_ready(manifest: dict[str, Any], request: dict[str, Any]) -> bool:
    """Consume the publisher's complete gates, never QA alone or an interim run."""
    if (manifest.get("publish_complete") is not True or manifest.get("ready_to_use") is not True
            or "failure_stage" not in manifest or "failure_reason" not in manifest
            or manifest["failure_stage"] is not None or manifest["failure_reason"] is not None):
        return False
    result, semantic = manifest.get("result"), manifest.get("semantic")
    if not isinstance(result, dict) or not isinstance(semantic, dict):
        return False
    try:
        readiness = resolve_studio_rule_publication_readiness(request)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        raise TaskControlError("paper_publication_unsealed", "The original publication rule readiness cannot be verified.") from exc
    canonical = readiness.to_payload()
    if (manifest.get("rule_readiness") != canonical or result.get("rule_readiness") != canonical
            or semantic.get("studio_rule_publication_readiness") != canonical
            or semantic.get("publication_rule_ready") is not (not readiness.publication_blocked)):
        return False
    projections = {"pending_rule_review": readiness.pending_rule_review,
                   "publication_rule_blocked": readiness.publication_blocked,
                   "autonomous_rule_ready": not readiness.publication_blocked}
    if any(record.get(key) is not value for record in (manifest, result) for key, value in projections.items()):
        return False
    expected = build_publish_state(
        qa=manifest.get("qa"), package_contract=manifest.get("package_contract"),
        delivery_package=manifest.get("delivery_package"),
        delivery_verification=manifest.get("delivery_verification") or {},
        prerequisite_state=RULE_REPAIR_STATE if readiness.publication_blocked else None,
        resolved_figure_plan=manifest.get("resolved_figure_plan"),
    )
    return expected["ready_to_use"] is True and all(manifest.get(key) == value for key, value in expected.items())


def capture_publication(selection: dict[str, Any]) -> dict[str, Any]:
    project = Path(selection["project"])
    request, _, figures = project_snapshot(project)
    manifest_path, _, error = latest_run(project)
    if manifest_path is None or error:
        raise TaskControlError("paper_publication_unsealed", "The original publication receipt is unavailable or invalid.")
    snapshot = stable_file_snapshot(manifest_path, label="paper sealed publication")
    manifest = json.loads(snapshot["bytes"])
    indicators = publication_indicators(project, request, figures, {"current": True})
    if indicators["qa"]["current"] is not True or not _finished_ready(manifest, request):
        raise TaskControlError("paper_publication_unsealed", "The current saved figure has no complete current sealed publication. Finish its original rule, QA and delivery gates explicitly; paper packaging will not render or export it.")
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
