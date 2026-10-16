"""Read-only frozen paper status; historical receipts never imply currentness."""

from pathlib import Path
from typing import Any

from sciplot_core.studio_core.source_update_commit import file_inventory
from sciplot_core.task_contract import TaskControlError
from sciplot_core.task_paper_sources import assert_selection_current
from sciplot_core.task_paper_publication import assert_publication_current


def _verify_delivery(state: dict[str, Any]) -> None:
    if file_inventory(Path(state["request"]["out"])) != state["delivery_files"]:
        raise TaskControlError("paper_delivery_changed", "The published paper package changed; no file was replaced.")


def _summary(state: dict[str, Any]) -> dict[str, Any]:
    return {"kind": state["kind"], "version": 1, "paper_dir": state["paper_dir"], "status": state["status"],
            "title": state["request"]["title"], "out": state["request"]["out"],
            "selection_origin": state.get("selection_origin"),
            "items": [{"stem": item["stem"], "status": item["status"], "project": source["project"],
                       "figure_id": source["figure_id"], "version": source["version"],
                       **({"scientific_sha256": item["scientific_sha256"]} if item["status"] == "sealed" else {})}
                      for source, item in zip(state["selections"], state["items"], strict=True)],
            **({"blocker": state["blocker"]} if state.get("blocker") else {}),
            **({"result": state["delivery"]} if state.get("delivery") else {}),
            "next_step": {"action": "review_selected_exports_and_deliver" if state["status"] == "complete" else "inspect_and_retry_exact_selection",
                          "paper_dir": state["paper_dir"]},
            "model_calls_by_sciplot": 0, "journal_acceptance_evaluated": False}


def _current_summary(root: Path, state: dict[str, Any]) -> dict[str, Any]:
    """Project currentness under the caller's existing lease without writes."""
    current = []
    for selection in state["selections"]:
        try:
            assert_selection_current(selection)
            if selection.get("publication"):
                assert_publication_current(selection["publication"], selection)
            current.append({"project": selection["project"], "figure_id": selection["figure_id"], "current": True})
        except (OSError, ValueError) as exc:
            current.append({"project": selection["project"], "figure_id": selection["figure_id"], "current": False, "message": str(exc)})
    summary = _summary(state)
    summary["recorded_status"] = state["status"]
    summary["selection_scope"] = "frozen_selected_versions"
    summary["result_scope"] = "historical_frozen_delivery"
    summary["current_selections"] = current
    summary["source_versions_current"] = all(item["current"] for item in current)
    summary["delivery_current"] = None
    if state.get("delivery_files"):
        try:
            _verify_delivery(state)
            summary["delivery_current"] = True
        except (OSError, ValueError):
            summary["delivery_current"] = False
    summary["ready_to_use"] = bool(state["status"] == "complete"
                                   and summary["source_versions_current"]
                                   and summary["delivery_current"] is True)
    summary["readiness_evaluated"] = True
    summary["readiness_scope"] = "Frozen package and selected source byte identities; no fresh native audit."
    if summary["delivery_current"] is False:
        summary.update(status="blocked", blocker={
            "reason_code": "paper_delivery_changed",
            "message": "The published paper package differs from its frozen inventory. Preserve the changed package and choose a new output for a new selection.",
        }, repair={"action": "preserve_changed_package_and_start_new_selection",
                   "output": state["request"]["out"], "new_output_required": True,
                   "automatic_overwrite": False},
            next_step={"action": "preserve_changed_package_and_start_new_selection", "paper_dir": str(root)})
    elif not summary["source_versions_current"]:
        summary.update(status="blocked", blocker={
            "reason_code": "paper_selection_changed",
            "message": "The package retains the frozen selected versions; its original projects or sources have changed. Review those changes and start a new current selection.",
        }, repair={"action": "review_changed_sources_and_start_new_selection",
                   "new_output_required": True, "automatic_overwrite": False},
            next_step={"action": "review_changed_sources_and_start_new_selection", "paper_dir": str(root)})
    elif state["status"] == "complete" and summary["delivery_current"] is not True:
        summary.update(status="blocked", blocker={
            "reason_code": "paper_delivery_unverified",
            "message": "The completed receipt has no verifiable frozen package inventory. Preserve it and inspect its evidence.",
        }, repair={"action": "inspect_paper_delivery_evidence", "automatic_overwrite": False},
            next_step={"action": "inspect_paper_delivery_evidence", "paper_dir": str(root)})
    return summary
