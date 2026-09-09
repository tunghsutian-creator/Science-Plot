"""Frozen native alternatives, compact differences and a read-only comparison page."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from subprocess import TimeoutExpired
from typing import Any

from sciplot_core.foundation.json_hashing import canonical_json_sha256
from sciplot_core.studio_core.document_edit_state import check_artifact, edit_state
from sciplot_core.studio_core.project_query import inspect_project
from sciplot_core.task_comparison_storage import candidate_review, candidate_task
from sciplot_core.task_comparison_gallery import write_comparison_gallery


def _different(change: dict[str, Any]) -> bool:
    if {"old_value", "new_value"} <= change.keys():
        return bool(change["old_value"] != change["new_value"])
    if {"before", "after"} <= change.keys():
        return bool(change["before"] != change["after"])
    return True


def comparison_snapshot(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    request = state["request"]
    result: dict[str, Any] = {
        "kind": "sciplot_task_comparison_result", "version": 1,
        "comparison_dir": str(root), "title": request["title"],
        "project": request["project"], "figure_id": request["figure_id"],
        "status": state["status"], "updated_at": state["updated_at"],
        "queried_at": datetime.now(timezone.utc).isoformat(),
        "baseline_current": False, "candidates": [], "previews": [],
        "ready_to_use": None, "readiness_evaluated": False,
        "model_calls_by_sciplot": 0, "external_model_tokens": None,
    }
    for key in ("selection", "selection_outcome", "export_task", "blocker"):
        if key in state:
            result[key] = state[key]
    try:
        result["baseline_current"] = edit_state(Path(request["project"])) == state["baseline"]
        current = inspect_project(Path(request["project"]))
        result["current_evidence"] = {key: current.get(key) for key in ("source", "qa", "delivery", "ready_to_use")}
        figure: dict[str, Any] = next((figure for figure in current.get("figures", [])
                       if figure["figure_id"] == request["figure_id"]), {})
        result["current_figure"] = {key: figure[key] for key in ("figure_id", "document", "document_sha256") if key in figure}
    except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
        result["current_error"] = str(exc)
    baseline: dict[str, Any] = {"id": "baseline", "label": "比较时的原图", "status": "unavailable"}
    try:
        artifact = state.get("baseline_preview")
        if artifact is not None:
            if not check_artifact(artifact).is_relative_to(root):
                raise ValueError("原图预览不在比较目录中。")
            baseline.update(status="ready", preview=artifact)
    except (ValueError, OSError) as exc:
        baseline["error"] = str(exc)
    result["baseline"] = baseline
    identity = []
    for item in request["candidates"]:
        entry = {key: item[key] for key in ("id", "label", "rationale") if key in item}
        entry.update(status="pending", selectable=False)
        try:
            child = candidate_task(root, state, item)
            if child:
                entry.update(status=child["status"], task_dir=child["task_dir"])
                if child["status"] == "cancelled":
                    raise ValueError("候选任务已被取消。")
                if child.get("preview"):
                    review = candidate_review(root, state, item, child)
                    changes = [change for change in review["actual_changes"] if _different(change)]
                    entry.update(
                        status="unchanged" if child.get("edit_outcome", {}).get("status") == "unchanged" else "ready",
                        operation_id=review["operation_id"], preview=review["preview"],
                        review_path=str(root / "candidates" / item["id"] / "review.json"),
                        change_count=len(changes), changes=changes[:12], changes_truncated=len(changes) > 12,
                        scientific_audit_status=review["scientific_audit"]["status"],
                    )
                if child.get("blocker"):
                    entry["error"] = child["blocker"]["message"]
            if item["id"] in state.get("candidate_errors", {}):
                entry["error"] = state["candidate_errors"][item["id"]]
        except (ValueError, OSError, RuntimeError, TimeoutExpired) as exc:
            entry.update(status="blocked", error=str(exc))
        identity.append({key: entry[key] for key in ("id", "operation_id", "preview", "error") if key in entry})
        result["candidates"].append(entry)
    result["comparison_id"] = canonical_json_sha256({
        "request": request, "baseline": state["baseline"],
        "baseline_preview": baseline.get("preview"), "candidates": identity,
    })
    can_select = result["baseline_current"] and baseline["status"] == "ready" and "selection" not in state
    baseline["selectable"] = can_select
    for entry in result["candidates"]:
        entry["selectable"] = can_select and entry["status"] in {"ready", "unchanged"} and "error" not in entry
    result["can_select"] = can_select
    if "selection" not in state and not result["baseline_current"]:
        result["status"] = "blocked"
        result["blocker"] = {"reason_code": "comparison_baseline_stale", "message": "项目或成图已变化；这些候选保留为历史比较，请从当前图新建比较。"}
    for entry in [baseline, *result["candidates"]]:
        if entry.get("preview"):
            result["previews"].append({"candidate_id": entry["id"], "figure_id": request["figure_id"],
                                       "scope": "baseline" if entry["id"] == "baseline" else "candidate",
                                       "preview": entry["preview"]})
    return result


def comparison_overview(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    result = comparison_snapshot(root, state)
    result["overview"] = write_comparison_gallery(root, result)
    return result
